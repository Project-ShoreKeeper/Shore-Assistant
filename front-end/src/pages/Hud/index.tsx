/**
 * /hud — ambient overlay page rendered inside the transparent `hud` Tauri
 * window. Purely presentational: all data arrives over Tauri events (see
 * hud-bridge.service.ts); no WebSocket, no REST, no auth.
 */
import { useCallback, useEffect, useState } from "react";
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
  const [panel, setPanel] = useState<{
    name: "agent" | "task" | "answer" | "connection" | null;
    modeRevision: number;
  }>({ name: null, modeRevision: 0 });
  const openPanel = panel.modeRevision === modeRevision ? panel.name : null;

  useEffect(() => {
    document.documentElement.classList.add("hud-transparent");
    return () => document.documentElement.classList.remove("hud-transparent");
  }, []);

  const dismissTopLayer = useCallback(() => {
    if (paletteOpen) {
      setPaletteOpen(false);
      return true;
    }
    if (openPanel) {
      setPanel({ name: null, modeRevision });
      return true;
    }
    return false;
  }, [modeRevision, openPanel, paletteOpen, setPaletteOpen]);
  const { setPassive } = useHudInteractionMode({
    active,
    dismissTopLayer,
  });

  const capabilities = state?.capabilities ?? {
    sendPrompt: false,
    cancelGeneration: false,
    stopCopilot: false,
    retryConnection: false,
    terminalConfirm: false,
  };
  const togglePanel = (
    name: "agent" | "task" | "answer" | "connection",
  ) => {
    setPanel({
      name: openPanel === name ? null : name,
      modeRevision,
    });
  };

  return (
    <div className={`hud-root${active ? " hud-active" : ""}`}>
      <EdgeRing />
      <HudCommandBar
        active={active}
        linked={linked}
        capabilities={capabilities}
        hasPending={hasPending}
        lastResult={lastResult}
        paletteOpen={paletteOpen}
        setPaletteOpen={setPaletteOpen}
        sendAction={sendAction}
        onPromptSent={setPassive}
      />
      <AgentStatusWidget
        status={state?.agent ?? "idle"}
        active={active}
        expanded={openPanel === "agent"}
        capabilities={capabilities}
        hasPending={hasPending}
        onToggle={() => togglePanel("agent")}
        sendAction={sendAction}
      />
      <LastTaskWidget
        task={state?.lastTask ?? null}
        active={active}
        expanded={openPanel === "task"}
        hasPending={hasPending}
        onToggle={() => togglePanel("task")}
        sendAction={sendAction}
      />
      <AnswerWidget
        answer={state?.answer ?? null}
        active={active}
        expanded={openPanel === "answer"}
        hasPending={hasPending}
        onToggle={() => togglePanel("answer")}
        sendAction={sendAction}
      />
      <ConnectionWidget
        connection={state?.connection ?? "offline"}
        linked={linked}
        active={active}
        expanded={openPanel === "connection"}
        capabilities={capabilities}
        hasPending={hasPending}
        onToggle={() => togglePanel("connection")}
        sendAction={sendAction}
      />
    </div>
  );
}
