import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

import { useAssistantContext } from "@Shore/contexts/AssistantContext";
import { HudContext } from "@Shore/contexts/hud-context";
import { useHudBridge } from "@Shore/hooks/useHudBridge";
import { isTauri } from "@Shore/utils/tauri.util";

const HUD_ENABLED_KEY = "shore.hud.enabled";

export function HudProvider({ children }: { children: React.ReactNode }) {
  const {
    wsStatus,
    copilotActive,
    isAssistantThinking,
    messages,
  } = useAssistantContext();
  const [enabled, setEnabledState] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useHudBridge({ wsStatus, copilotActive, isAssistantThinking, messages });

  const setEnabled = useCallback(async (nextEnabled: boolean) => {
    if (!isTauri()) return;

    setError(null);
    try {
      if (nextEnabled) {
        const warning = await invoke<string | null>("hud_show");
        if (warning) setError(warning);
      } else {
        await invoke("hud_hide");
      }

      setEnabledState(nextEnabled);
      window.localStorage.setItem(
        HUD_ENABLED_KEY,
        nextEnabled ? "1" : "0",
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }, []);

  useEffect(() => {
    if (
      !isTauri()
      || window.localStorage.getItem(HUD_ENABLED_KEY) !== "1"
    ) {
      return;
    }

    // A timer lets the first StrictMode effect clean itself up before the
    // development-only remount, avoiding two concurrent hud_show invokes.
    const timer = window.setTimeout(() => void setEnabled(true), 0);
    return () => window.clearTimeout(timer);
  }, [setEnabled]);

  return (
    <HudContext.Provider value={{ enabled, error, setEnabled }}>
      {children}
    </HudContext.Provider>
  );
}
