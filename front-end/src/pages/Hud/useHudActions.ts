import {
  useCallback,
  useEffect,
  useReducer,
  useState,
} from "react";

import { emitHudAction } from "@Shore/services/hud-bridge.service";
import {
  createHudRequestId,
  HUD_ACTION_RESULT_EVENT,
  reduceHudPending,
  type HudAction,
  type HudActionRequest,
  type HudActionResult,
} from "@Shore/services/hud-actions";
import { isTauri } from "@Shore/utils/tauri.util";

const ACTION_TIMEOUT_MS = 5_000;

export function useHudActions() {
  const [pending, dispatchPending] = useReducer(reduceHudPending, {});
  const [lastResult, setLastResult] = useState<HudActionResult | null>(null);

  useEffect(() => {
    if (!isTauri()) return;
    let disposed = false;
    let unlisten: (() => void) | undefined;

    void import("@tauri-apps/api/event").then(async ({ listen }) => {
      const cleanup = await listen<HudActionResult>(
        HUD_ACTION_RESULT_EVENT,
        (event) => {
          dispatchPending({
            type: "settled",
            requestId: event.payload.requestId,
          });
          setLastResult(event.payload);
        },
      );
      if (disposed) cleanup();
      else unlisten = cleanup;
    });

    return () => {
      disposed = true;
      unlisten?.();
    };
  }, []);

  useEffect(() => {
    if (Object.keys(pending).length === 0) return;
    const interval = window.setInterval(() => {
      const now = Date.now();
      const timedOut = Object.entries(pending).filter(
        ([, action]) => now - action.startedAt >= ACTION_TIMEOUT_MS,
      );
      if (timedOut.length === 0) return;

      const [requestId] = timedOut[timedOut.length - 1];
      setLastResult({
        requestId,
        ok: false,
        error: "timeout",
        message: "The main app did not answer this HUD action.",
      });
      dispatchPending({
        type: "expired",
        now,
        timeoutMs: ACTION_TIMEOUT_MS,
      });
    }, 250);
    return () => window.clearInterval(interval);
  }, [pending]);

  const sendAction = useCallback((request: HudActionRequest): string => {
    const requestId = createHudRequestId();
    if (!isTauri()) {
      setLastResult({
        requestId,
        ok: false,
        error: "unavailable",
        message: "HUD actions are available only in the desktop app.",
      });
      return requestId;
    }

    const action = {
      ...request,
      requestId,
      version: 1,
    } as HudAction;
    dispatchPending({
      type: "started",
      requestId,
      action: action.action,
      now: Date.now(),
    });
    setLastResult(null);
    emitHudAction(action);
    return requestId;
  }, []);

  const clearLastResult = useCallback(() => setLastResult(null), []);

  return {
    sendAction,
    pending,
    hasPending: Object.keys(pending).length > 0,
    lastResult,
    clearLastResult,
  };
}
