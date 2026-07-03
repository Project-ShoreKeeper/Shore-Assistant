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
import {
  HUD_ACTION_EVENT,
  HUD_ACTION_RESULT_EVENT,
  type HudAction,
  type HudActionResult,
} from "./hud-actions";

export { HUD_ACTION_EVENT, HUD_ACTION_RESULT_EVENT };

export const HUD_STATE_EVENT = "hud://state";
export const HUD_MODE_EVENT = "hud://mode";
export const HUD_READY_EVENT = "hud://ready";
export const HUD_FOCUS_MAIN_EVENT = "hud://focus-main";

export type HudAgentStatus = "thinking" | "monitoring" | "idle";
export type HudConnection = "active" | "reconnecting" | "offline";

export interface HudTask {
  messageId: string;
  actionId: string;
  tool: string;
  status: "running" | "completed" | "error";
  summary: string;
  ts: number;
}

export interface HudAnswer {
  messageId: string;
  text: string;
}

export interface HudStatePayload {
  agent: HudAgentStatus;
  /** Last agent tool action, or null if none this session. */
  lastTask: HudTask | null;
  /** Bounded latest assistant answer, or null. */
  answer: HudAnswer | null;
  connection: HudConnection;
  capabilities: {
    sendPrompt: boolean;
    cancelGeneration: boolean;
    stopCopilot: boolean;
    retryConnection: boolean;
    terminalConfirm: boolean;
  };
}

/** Duck-typed subset of ChatMessage — avoids importing the hook's types. */
export interface HudBridgeInput {
  wsStatus: WebSocketStatus;
  lastCloseCode?: number | null;
  cuaRunning: boolean;
  isAssistantThinking: boolean;
  messages: Array<{
    id: string;
    role: "user" | "assistant";
    text: string;
    agentActions?: Array<{
      id: string;
      tool?: string;
      detail: string;
      status: "running" | "completed" | "error";
      timestamp: Date;
    }>;
  }>;
}

const ANSWER_PREVIEW_CHARS = 4_000;
const TASK_TOOL_CHARS = 60;
const EMIT_THROTTLE_MS = 250;

export function deriveHudState(input: HudBridgeInput): HudStatePayload {
  const agent: HudAgentStatus = input.isAssistantThinking
    ? "thinking"
    : input.cuaRunning
      ? "monitoring"
      : "idle";

  let lastTask: HudStatePayload["lastTask"] = null;
  for (let i = input.messages.length - 1; i >= 0 && !lastTask; i--) {
    const actions = input.messages[i].agentActions;
    if (actions && actions.length > 0) {
      const a = actions[actions.length - 1];
      const tool = (a.tool || "Tool").slice(0, TASK_TOOL_CHARS);
      const statusLabel = a.status === "running"
        ? "is running"
        : a.status === "error"
          ? "failed"
          : "completed";
      lastTask = {
        messageId: input.messages[i].id,
        actionId: a.id,
        tool,
        status: a.status,
        // Raw args, detail and result are intentionally excluded. They may
        // contain commands, signed URLs, tokens, file contents or image data.
        summary: `${tool} ${statusLabel}`.slice(0, 240),
        ts: a.timestamp.getTime(),
      };
    }
  }

  let answer: HudAnswer | null = null;
  for (let i = input.messages.length - 1; i >= 0 && answer === null; i--) {
    const message = input.messages[i];
    if (message.role !== "assistant") continue;
    const text = message.text.trim();
    if (text) {
      answer = {
        messageId: message.id,
        text: text.slice(0, ANSWER_PREVIEW_CHARS),
      };
    }
  }

  const connection: HudConnection =
    input.wsStatus === "OPEN"
      ? "active"
      : input.wsStatus === "CONNECTING"
        ? "reconnecting"
        : "offline";

  return {
    agent,
    lastTask,
    answer,
    connection,
    capabilities: {
      sendPrompt: input.wsStatus === "OPEN",
      cancelGeneration:
        input.wsStatus === "OPEN" && input.isAssistantThinking,
      stopCopilot: input.wsStatus === "OPEN" && input.cuaRunning,
      retryConnection:
        input.lastCloseCode !== 4401
        && input.wsStatus !== "OPEN"
        && input.wsStatus !== "CONNECTING",
      terminalConfirm: false,
    },
  };
}

// ── Emit side (main window) ──────────────────────────────────────────────

let lastEmitAt = 0;
let trailingTimer: ReturnType<typeof setTimeout> | null = null;

/** Throttled emit: leading edge + one trailing emit per window. */
export function publishHudState(payload: HudStatePayload): void {
  if (!isTauri()) return;
  const send = () => {
    lastEmitAt = Date.now();
    void import("@tauri-apps/api/event").then(({ emitTo }) =>
      emitTo("hud", HUD_STATE_EVENT, payload),
    ).catch((error) => {
      console.warn("[HUD] Could not publish state:", error);
    });
  };
  const elapsed = Date.now() - lastEmitAt;
  if (elapsed >= EMIT_THROTTLE_MS) {
    send();
    return;
  }
  if (trailingTimer) clearTimeout(trailingTimer);
  trailingTimer = setTimeout(() => {
    trailingTimer = null;
    send();
  }, EMIT_THROTTLE_MS - elapsed);
}

export function cancelPendingHudStatePublish(): void {
  if (!trailingTimer) return;
  clearTimeout(trailingTimer);
  trailingTimer = null;
}

// ── HUD-window side helpers ──────────────────────────────────────────────

export function emitHudReady(): void {
  if (!isTauri()) return;
  void import("@tauri-apps/api/event").then(({ emitTo }) =>
    emitTo("main", HUD_READY_EVENT),
  ).catch((error) => {
    console.warn("[HUD] Could not announce ready state:", error);
  });
}

export function emitHudFocusMain(): void {
  if (!isTauri()) return;
  void import("@tauri-apps/api/event").then(({ emitTo }) =>
    emitTo("main", HUD_FOCUS_MAIN_EVENT),
  ).catch((error) => {
    console.warn("[HUD] Could not request main-window focus:", error);
  });
}

export function emitHudAction(action: HudAction): void {
  if (!isTauri()) return;
  void import("@tauri-apps/api/event").then(({ emitTo }) =>
    emitTo("main", HUD_ACTION_EVENT, action),
  ).catch((error) => {
    console.warn("[HUD] Could not send action:", error);
  });
}

export function emitHudActionResult(result: HudActionResult): void {
  if (!isTauri()) return;
  void import("@tauri-apps/api/event").then(({ emitTo }) =>
    emitTo("hud", HUD_ACTION_RESULT_EVENT, result),
  ).catch((error) => {
    console.warn("[HUD] Could not publish action result:", error);
  });
}
