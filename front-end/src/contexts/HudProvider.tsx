import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useNavigate } from "react-router-dom";

import { useAssistantContext } from "@Shore/contexts/AssistantContext";
import { HudContext } from "@Shore/contexts/hud-context";
import type { HudNavigationTarget } from "@Shore/contexts/hud-context";
import { useHudBridge } from "@Shore/hooks/useHudBridge";
import type {
  HudAction,
  HudActionOutcome,
} from "@Shore/services/hud-actions";
import { isTauri } from "@Shore/utils/tauri.util";

const HUD_ENABLED_KEY = "shore.hud.enabled";
let pendingUnmountHide = 0;

export function HudProvider({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  const {
    wsStatus,
    lastCloseCode,
    copilotActive,
    isAssistantThinking,
    messages,
    sendTextMessage,
    cancelGeneration,
    stopCopilot,
    reconnectChat,
  } = useAssistantContext();
  const [enabled, setEnabledState] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [navigationTarget, setNavigationTarget] =
    useState<HudNavigationTarget | null>(null);

  const executeAction = useCallback(async (
    action: HudAction,
  ): Promise<HudActionOutcome> => {
    switch (action.action) {
      case "send_prompt":
        return sendTextMessage(action.payload.text);
      case "cancel_generation":
        return cancelGeneration();
      case "stop_copilot":
        return stopCopilot();
      case "focus_main": {
        if (!isTauri()) {
          return {
            ok: false,
            error: "unavailable",
            message: "Main-window focus is available only on desktop.",
          };
        }
        setNavigationTarget({
          requestId: action.requestId,
          destination: action.payload.destination,
          ...(action.payload.messageId
            ? { messageId: action.payload.messageId }
            : {}),
        });
        await invoke("hud_set_mode", { active: false });
        navigate("/chat");
        const { getAllWindows } = await import("@tauri-apps/api/window");
        const mainWindow = (await getAllWindows()).find(
          (window) => window.label === "main",
        );
        if (!mainWindow) {
          return {
            ok: false,
            error: "unavailable",
            message: "The main app window is not available.",
          };
        }
        await mainWindow.show();
        await mainWindow.unminimize();
        await mainWindow.setFocus();
        return { ok: true, message: "Opened the main app." };
      }
      case "retry_connection":
        return reconnectChat();
      case "terminal_confirm":
        return {
          ok: false,
          error: "unauthorized",
          message: "Terminal confirmation is not enabled in HUD.",
        };
    }
  }, [
    cancelGeneration,
    navigate,
    reconnectChat,
    sendTextMessage,
    stopCopilot,
  ]);

  useHudBridge(
    {
      wsStatus,
      lastCloseCode,
      copilotActive,
      isAssistantThinking,
      messages,
    },
    executeAction,
    enabled,
  );

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

  useEffect(() => {
    window.clearTimeout(pendingUnmountHide);
    pendingUnmountHide = 0;
    return () => {
      // Delay cleanup so React StrictMode's development remount can cancel it.
      // A real route/auth unmount hides stale conversation data immediately.
      pendingUnmountHide = window.setTimeout(() => {
        if (isTauri()) void invoke("hud_hide");
      }, 100);
    };
  }, []);

  const clearNavigationTarget = useCallback((requestId: string) => {
    setNavigationTarget((current) =>
      current?.requestId === requestId ? null : current
    );
  }, []);

  return (
    <HudContext.Provider
      value={{
        enabled,
        error,
        setEnabled,
        navigationTarget,
        clearNavigationTarget,
      }}
    >
      {children}
    </HudContext.Provider>
  );
}
