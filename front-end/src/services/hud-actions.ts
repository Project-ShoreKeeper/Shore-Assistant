export const HUD_ACTION_EVENT = "hud://action";
export const HUD_ACTION_RESULT_EVENT = "hud://action-result";

const REQUEST_ID_PATTERN = /^[A-Za-z0-9._:-]{1,128}$/;
const PROMPT_MAX_CHARS = 2_000;
const DEFAULT_CACHE_SIZE = 100;
const DEFAULT_CACHE_TTL_MS = 5 * 60_000;

export type HudAction =
  | {
      requestId: string;
      version: 1;
      action: "send_prompt";
      payload: { text: string };
    }
  | {
      requestId: string;
      version: 1;
      action: "cancel_generation";
    }
  | {
      requestId: string;
      version: 1;
      action: "stop_copilot";
    }
  | {
      requestId: string;
      version: 1;
      action: "retry_connection";
    }
  | {
      requestId: string;
      version: 1;
      action: "focus_main";
      payload: {
        destination: "chat" | "settings" | "terminal";
        messageId?: string;
      };
    }
  | {
      requestId: string;
      version: 1;
      action: "terminal_confirm";
      payload: { confirmId: string; decision: "approve" | "deny" };
    };

export type HudActionRequest = HudAction extends infer Action
  ? Action extends HudAction
    ? Omit<Action, "requestId" | "version">
    : never
  : never;

export type HudActionError =
  | "invalid"
  | "unavailable"
  | "unauthorized"
  | "timeout"
  | "failed";

export interface HudActionResult {
  requestId: string;
  ok: boolean;
  error?: HudActionError;
  message?: string;
}

export type HudActionOutcome = Omit<HudActionResult, "requestId">;

export type HudActionValidation =
  | { ok: true; action: HudAction }
  | { ok: false; result: HudActionResult | null };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasOnlyKeys(
  value: Record<string, unknown>,
  allowed: readonly string[],
): boolean {
  return Object.keys(value).every((key) => allowed.includes(key));
}

function validRequestId(value: unknown): value is string {
  return typeof value === "string" && REQUEST_ID_PATTERN.test(value);
}

function invalidResult(
  requestId: string | null,
  message: string,
): HudActionValidation {
  return {
    ok: false,
    result: requestId
      ? { requestId, ok: false, error: "invalid", message }
      : null,
  };
}

export function validateHudAction(value: unknown): HudActionValidation {
  if (!isRecord(value)) return invalidResult(null, "Malformed HUD action.");

  const requestId = validRequestId(value.requestId) ? value.requestId : null;
  if (!requestId) return invalidResult(null, "Invalid request ID.");
  if (value.version !== 1) {
    return invalidResult(requestId, "Unsupported HUD action version.");
  }
  if (typeof value.action !== "string") {
    return invalidResult(requestId, "Missing HUD action.");
  }

  switch (value.action) {
    case "send_prompt": {
      if (
        !hasOnlyKeys(value, ["requestId", "version", "action", "payload"])
        || !isRecord(value.payload)
        || !hasOnlyKeys(value.payload, ["text"])
        || typeof value.payload.text !== "string"
      ) {
        return invalidResult(requestId, "Invalid prompt payload.");
      }
      const text = value.payload.text.trim();
      if (!text || text.length > PROMPT_MAX_CHARS) {
        return invalidResult(
          requestId,
          `Prompt must contain 1–${PROMPT_MAX_CHARS} characters.`,
        );
      }
      return {
        ok: true,
        action: {
          requestId,
          version: 1,
          action: "send_prompt",
          payload: { text },
        },
      };
    }
    case "cancel_generation":
    case "stop_copilot":
    case "retry_connection":
      if (!hasOnlyKeys(value, ["requestId", "version", "action"])) {
        return invalidResult(requestId, "Unexpected action payload.");
      }
      return {
        ok: true,
        action: {
          requestId,
          version: 1,
          action: value.action,
        },
      };
    case "focus_main": {
      if (
        !hasOnlyKeys(value, ["requestId", "version", "action", "payload"])
        || !isRecord(value.payload)
        || !hasOnlyKeys(value.payload, ["destination", "messageId"])
        || !["chat", "settings", "terminal"].includes(
          String(value.payload.destination),
        )
        || (
          value.payload.messageId !== undefined
          && !validRequestId(value.payload.messageId)
        )
      ) {
        return invalidResult(requestId, "Invalid focus destination.");
      }
      return {
        ok: true,
        action: {
          requestId,
          version: 1,
          action: "focus_main",
          payload: {
            destination: value.payload.destination as
              | "chat"
              | "settings"
              | "terminal",
            ...(typeof value.payload.messageId === "string"
              ? { messageId: value.payload.messageId }
              : {}),
          },
        },
      };
    }
    case "terminal_confirm": {
      if (
        !hasOnlyKeys(value, ["requestId", "version", "action", "payload"])
        || !isRecord(value.payload)
        || !hasOnlyKeys(value.payload, ["confirmId", "decision"])
        || !validRequestId(value.payload.confirmId)
        || !["approve", "deny"].includes(String(value.payload.decision))
      ) {
        return invalidResult(requestId, "Invalid terminal confirmation.");
      }
      return {
        ok: true,
        action: {
          requestId,
          version: 1,
          action: "terminal_confirm",
          payload: {
            confirmId: value.payload.confirmId,
            decision: value.payload.decision as "approve" | "deny",
          },
        },
      };
    }
    default:
      return invalidResult(requestId, "Unknown HUD action.");
  }
}

interface CachedAction {
  expiresAt: number;
  result: Promise<HudActionResult>;
}

export class HudActionDeduplicator {
  private readonly entries = new Map<string, CachedAction>();
  private readonly maxEntries: number;
  private readonly ttlMs: number;

  constructor(
    maxEntries = DEFAULT_CACHE_SIZE,
    ttlMs = DEFAULT_CACHE_TTL_MS,
  ) {
    this.maxEntries = maxEntries;
    this.ttlMs = ttlMs;
  }

  run(
    action: HudAction,
    executor: (action: HudAction) => Promise<HudActionOutcome>,
    now = Date.now(),
  ): Promise<HudActionResult> {
    this.prune(now);
    const cached = this.entries.get(action.requestId);
    if (cached) return cached.result;

    const result = Promise.resolve()
      .then(() => executor(action))
      .then((outcome) => ({ requestId: action.requestId, ...outcome }))
      .catch((cause: unknown): HudActionResult => ({
        requestId: action.requestId,
        ok: false,
        error: "failed",
        message: cause instanceof Error ? cause.message : "HUD action failed.",
      }));

    this.entries.set(action.requestId, {
      expiresAt: now + this.ttlMs,
      result,
    });
    while (this.entries.size > this.maxEntries) {
      const oldest = this.entries.keys().next().value;
      if (typeof oldest !== "string") break;
      this.entries.delete(oldest);
    }
    return result;
  }

  private prune(now: number): void {
    for (const [requestId, entry] of this.entries) {
      if (entry.expiresAt <= now) this.entries.delete(requestId);
    }
  }
}

export interface HudPendingAction {
  action: HudAction["action"];
  startedAt: number;
}

export type HudPendingState = Record<string, HudPendingAction>;

export type HudPendingEvent =
  | {
      type: "started";
      requestId: string;
      action: HudAction["action"];
      now: number;
    }
  | { type: "settled"; requestId: string }
  | { type: "expired"; now: number; timeoutMs: number };

export function reduceHudPending(
  state: HudPendingState,
  event: HudPendingEvent,
): HudPendingState {
  if (event.type === "started") {
    return {
      ...state,
      [event.requestId]: { action: event.action, startedAt: event.now },
    };
  }

  if (event.type === "settled") {
    if (!(event.requestId in state)) return state;
    const next = { ...state };
    delete next[event.requestId];
    return next;
  }

  return Object.fromEntries(
    Object.entries(state).filter(
      ([, pending]) => event.now - pending.startedAt < event.timeoutMs,
    ),
  );
}

export function createHudRequestId(): string {
  const cryptoApi = globalThis.crypto;
  if (cryptoApi?.randomUUID) return cryptoApi.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}
