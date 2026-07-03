/**
 * HUD-window state: listens for pushes from the main window. `linked`
 * flips false when no `hud://state` (heartbeat: every 3 s) arrives for 5 s
 * — i.e. the main window is gone or off the chat page.
 */
import { useEffect, useRef, useState } from "react";
import { isTauri } from "@Shore/utils/tauri.util";
import {
  HUD_MODE_EVENT,
  HUD_STATE_EVENT,
  emitHudReady,
  type HudStatePayload,
} from "@Shore/services/hud-bridge.service";

const LINK_TIMEOUT_MS = 5000;

export function useHudState(): {
  state: HudStatePayload | null;
  active: boolean;
  linked: boolean;
  modeRevision: number;
} {
  const [state, setState] = useState<HudStatePayload | null>(null);
  const [active, setActive] = useState(false);
  const [linked, setLinked] = useState(false);
  const [modeRevision, setModeRevision] = useState(0);
  const lastSeenRef = useRef(0);

  useEffect(() => {
    if (!isTauri()) return;
    const unlisteners: Array<() => void> = [];
    let disposed = false;

    void import("@tauri-apps/api/event").then(async ({ listen }) => {
      const un1 = await listen<HudStatePayload>(HUD_STATE_EVENT, (e) => {
        lastSeenRef.current = Date.now();
        setLinked(true);
        setState(e.payload);
      });
      const un2 = await listen<{ active: boolean }>(HUD_MODE_EVENT, (e) => {
        setActive(e.payload.active);
        setModeRevision((revision) => revision + 1);
      });
      if (disposed) {
        un1();
        un2();
        return;
      }
      unlisteners.push(un1, un2);
      emitHudReady();
    });

    const linkCheck = setInterval(() => {
      setLinked(Date.now() - lastSeenRef.current < LINK_TIMEOUT_MS);
    }, 1000);

    return () => {
      disposed = true;
      unlisteners.forEach((fn) => fn());
      clearInterval(linkCheck);
    };
  }, []);

  return { state, active, linked, modeRevision };
}
