/**
 * Main-window half of the HUD bridge: derives the compact HUD payload from
 * chat state and pushes it to the HUD window. Also answers `hud://ready`
 * with an immediate snapshot, re-emits every 3 s as a keepalive (the HUD
 * shows "No link to app" after 5 s of silence), and focuses this window on
 * `hud://focus-main`. No-op outside Tauri.
 */
import { useEffect, useRef } from "react";
import { isTauri } from "@Shore/utils/tauri.util";
import {
  HUD_ACTION_EVENT,
  HUD_FOCUS_MAIN_EVENT,
  HUD_READY_EVENT,
  deriveHudState,
  emitHudActionResult,
  publishHudState,
  type HudBridgeInput,
} from "@Shore/services/hud-bridge.service";
import {
  HudActionDeduplicator,
  validateHudAction,
  type HudAction,
  type HudActionOutcome,
} from "@Shore/services/hud-actions";

const HEARTBEAT_MS = 3000;
const actionDeduplicator = new HudActionDeduplicator();

export type HudActionExecutor = (
  action: HudAction,
) => Promise<HudActionOutcome>;

export function useHudBridge(
  input: HudBridgeInput,
  executeAction?: HudActionExecutor,
): void {
  const inputRef = useRef(input);
  const executorRef = useRef(executeAction);
  inputRef.current = input;
  executorRef.current = executeAction;

  // Push on every relevant state change (throttled inside publishHudState).
  const snapshot = JSON.stringify(deriveHudState(input));
  useEffect(() => {
    if (!isTauri()) return;
    publishHudState(deriveHudState(inputRef.current));
  }, [snapshot]);

  useEffect(() => {
    if (!isTauri()) return;
    const unlisteners: Array<() => void> = [];
    let disposed = false;

    void import("@tauri-apps/api/event").then(async ({ listen }) => {
      const un1 = await listen(HUD_READY_EVENT, () => {
        publishHudState(deriveHudState(inputRef.current));
      });
      const un2 = await listen(HUD_FOCUS_MAIN_EVENT, () => {
        void import("@tauri-apps/api/window").then(({ getCurrentWindow }) => {
          const w = getCurrentWindow();
          void w.unminimize();
          void w.setFocus();
        });
      });
      const un3 = await listen<unknown>(HUD_ACTION_EVENT, (event) => {
        const validation = validateHudAction(event.payload);
        if (!validation.ok) {
          if (validation.result) emitHudActionResult(validation.result);
          return;
        }

        void actionDeduplicator
          .run(
            validation.action,
            (action) => executorRef.current
              ? executorRef.current(action)
              : Promise.resolve({
                  ok: false,
                  error: "unavailable",
                  message: "HUD action is not available yet.",
                }),
          )
          .then(emitHudActionResult);
      });
      if (disposed) {
        un1();
        un2();
        un3();
        return;
      }
      unlisteners.push(un1, un2, un3);
    });

    const heartbeat = setInterval(() => {
      publishHudState(deriveHudState(inputRef.current));
    }, HEARTBEAT_MS);

    return () => {
      disposed = true;
      unlisteners.forEach((fn) => fn());
      clearInterval(heartbeat);
    };
  }, []);
}
