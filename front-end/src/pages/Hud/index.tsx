/**
 * /hud — ambient overlay page rendered inside the transparent `hud` Tauri
 * window. Purely presentational: all data arrives over Tauri events (see
 * hud-bridge.service.ts); no WebSocket, no REST, no auth.
 */
import { useCallback, useEffect, useState } from "react";
import { emitHudFocusMain } from "@Shore/services/hud-bridge.service";
import { useHudState } from "./useHudState";
import { useHudActions } from "./useHudActions";
import { useHudInteractionMode } from "./useHudInteractionMode";
import HudCommandBar from "./HudCommandBar";
import EdgeRing from "./EdgeRing";
import AgentStatusWidget from "./widgets/AgentStatusWidget";
import LastTaskWidget from "./widgets/LastTaskWidget";
import AnswerWidget from "./widgets/AnswerWidget";
import ConnectionWidget from "./widgets/ConnectionWidget";
import "./hud.css";

export default function PageHud() {
  const { state, active, linked, modeRevision } = useHudState();
  const {
    sendAction,
    hasPending,
    lastResult,
  } = useHudActions();
  const [palette, setPalette] = useState({ open: false, modeRevision: 0 });
  const paletteOpen = palette.open && palette.modeRevision === modeRevision;
  const setPaletteOpen = useCallback((open: boolean) => {
    setPalette({ open, modeRevision });
  }, [modeRevision]);

  useEffect(() => {
    document.documentElement.classList.add("hud-transparent");
    return () => document.documentElement.classList.remove("hud-transparent");
  }, []);

  const dismissTopLayer = useCallback(() => {
    if (!paletteOpen) return false;
    setPaletteOpen(false);
    return true;
  }, [paletteOpen, setPaletteOpen]);
  const { setPassive } = useHudInteractionMode({
    active,
    dismissTopLayer,
  });

  const focusMain = () => {
    if (active) emitHudFocusMain();
  };

  return (
    <div className={`hud-root${active ? " hud-active" : ""}`}>
      <EdgeRing />
      <HudCommandBar
        active={active}
        linked={linked}
        capabilities={state?.capabilities ?? {
          sendPrompt: false,
          cancelGeneration: false,
          stopCopilot: false,
          retryConnection: false,
          terminalConfirm: false,
        }}
        hasPending={hasPending}
        lastResult={lastResult}
        paletteOpen={paletteOpen}
        setPaletteOpen={setPaletteOpen}
        sendAction={sendAction}
        onPromptSent={setPassive}
      />
      <AgentStatusWidget status={state?.agent ?? "idle"} onClick={focusMain} />
      <LastTaskWidget task={state?.lastTask ?? null} onClick={focusMain} />
      <AnswerWidget answer={state?.answer ?? null} onClick={focusMain} />
      <ConnectionWidget
        connection={state?.connection ?? "offline"}
        linked={linked}
        onClick={focusMain}
      />
    </div>
  );
}
