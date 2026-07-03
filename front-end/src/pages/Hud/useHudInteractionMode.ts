import { useCallback, useEffect } from "react";

import { isTauri } from "@Shore/utils/tauri.util";

const IDLE_TIMEOUT_MS = 10_000;

async function setNativeHudMode(active: boolean): Promise<void> {
  if (!isTauri()) return;
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke("hud_set_mode", { active });
}

export function useHudInteractionMode({
  active,
  dismissTopLayer,
}: {
  active: boolean;
  dismissTopLayer: () => boolean;
}) {
  const setPassive = useCallback(() => {
    void setNativeHudMode(false).catch((cause) => {
      console.error("[HUD] Could not return to passive mode:", cause);
    });
  }, []);

  useEffect(() => {
    if (!active) return;
    let idleTimer = 0;

    const armIdleTimer = () => {
      window.clearTimeout(idleTimer);
      idleTimer = window.setTimeout(setPassive, IDLE_TIMEOUT_MS);
    };
    const onActivity = () => armIdleTimer();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        if (!dismissTopLayer()) setPassive();
        else armIdleTimer();
        return;
      }
      armIdleTimer();
    };

    armIdleTimer();
    window.addEventListener("pointermove", onActivity, { passive: true });
    window.addEventListener("pointerdown", onActivity, { passive: true });
    window.addEventListener("input", onActivity);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.clearTimeout(idleTimer);
      window.removeEventListener("pointermove", onActivity);
      window.removeEventListener("pointerdown", onActivity);
      window.removeEventListener("input", onActivity);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [active, dismissTopLayer, setPassive]);

  return { setPassive };
}
