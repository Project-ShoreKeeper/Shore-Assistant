/**
 * Event bridge between the main chat window and the HUD overlay window.
 *
 * The main window is the only owner of the chat WebSocket; the HUD window
 * is purely presentational. State flows one way (main → HUD) over Tauri
 * events; the HUD sends back only `hud://ready` (request a snapshot) and
 * `hud://focus-main` (user clicked a widget in active mode).
 *
 * `deriveHudState` is a pure function over duck-typed inputs so it can be
 * unit-tested without React or Tauri once test infra exists.
 */
import { isTauri } from "@Shore/utils/tauri.util";
import type { WebSocketStatus } from "./chat-websocket.service";

export const HUD_STATE_EVENT = "hud://state";
export const HUD_MODE_EVENT = "hud://mode";
export const HUD_READY_EVENT = "hud://ready";
export const HUD_FOCUS_MAIN_EVENT = "hud://focus-main";

export type HudAgentStatus = "thinking" | "monitoring" | "idle";
export type HudConnection = "active" | "reconnecting" | "offline";

export interface HudStatePayload {
  agent: HudAgentStatus;
  /** Last agent tool action, or null if none this session. */
  lastTask: { label: string; ts: number } | null;
  /** Tail of the latest reasoning stream, or null. */
  thought: string | null;
  connection: HudConnection;
}

/** Duck-typed subset of ChatMessage — avoids importing the hook's types. */
export interface HudBridgeInput {
  wsStatus: WebSocketStatus;
  copilotActive: boolean;
  isAssistantThinking: boolean;
  messages: Array<{
    thinkingText?: string;
    agentActions?: Array<{ tool?: string; detail: string; timestamp: Date }>;
  }>;
}

const THOUGHT_TAIL_CHARS = 120;
const TASK_LABEL_CHARS = 60;
const EMIT_THROTTLE_MS = 250;

export function deriveHudState(input: HudBridgeInput): HudStatePayload {
  const agent: HudAgentStatus = input.isAssistantThinking
    ? "thinking"
    : input.copilotActive
      ? "monitoring"
      : "idle";

  let lastTask: HudStatePayload["lastTask"] = null;
  for (let i = input.messages.length - 1; i >= 0 && !lastTask; i--) {
    const actions = input.messages[i].agentActions;
    if (actions && actions.length > 0) {
      const a = actions[actions.length - 1];
      lastTask = {
        label: (a.tool || a.detail).slice(0, TASK_LABEL_CHARS),
        ts: a.timestamp.getTime(),
      };
    }
  }

  let thought: string | null = null;
  for (let i = input.messages.length - 1; i >= 0 && thought === null; i--) {
    const t = input.messages[i].thinkingText;
    if (t && t.trim()) thought = t.trim().slice(-THOUGHT_TAIL_CHARS);
  }

  const connection: HudConnection =
    input.wsStatus === "OPEN"
      ? "active"
      : input.wsStatus === "CONNECTING"
        ? "reconnecting"
        : "offline";

  return { agent, lastTask, thought, connection };
}

// ── Emit side (main window) ──────────────────────────────────────────────

let lastEmitAt = 0;
let trailingTimer: ReturnType<typeof setTimeout> | null = null;

/** Throttled emit: leading edge + one trailing emit per window. */
export function publishHudState(payload: HudStatePayload): void {
  if (!isTauri()) return;
  const send = () => {
    lastEmitAt = Date.now();
    void import("@tauri-apps/api/event").then(({ emit }) =>
      emit(HUD_STATE_EVENT, payload),
    );
  };
  const elapsed = Date.now() - lastEmitAt;
  if (elapsed >= EMIT_THROTTLE_MS) {
    send();
    return;
  }
  if (trailingTimer) clearTimeout(trailingTimer);
  trailingTimer = setTimeout(send, EMIT_THROTTLE_MS - elapsed);
}

// ── HUD-window side helpers ──────────────────────────────────────────────

export function emitHudReady(): void {
  if (!isTauri()) return;
  void import("@tauri-apps/api/event").then(({ emit }) =>
    emit(HUD_READY_EVENT),
  );
}

export function emitHudFocusMain(): void {
  if (!isTauri()) return;
  void import("@tauri-apps/api/event").then(({ emit }) =>
    emit(HUD_FOCUS_MAIN_EVENT),
  );
}
