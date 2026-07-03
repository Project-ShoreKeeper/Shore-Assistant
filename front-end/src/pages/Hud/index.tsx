/**
 * /hud — ambient overlay page rendered inside the transparent `hud` Tauri
 * window. Purely presentational: all data arrives over Tauri events (see
 * hud-bridge.service.ts); no WebSocket, no REST, no auth.
 */
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { useHudState } from "./useHudState";
import { useHudActions } from "./useHudActions";
import { useHudInteractionMode } from "./useHudInteractionMode";
import HudCommandBar from "./HudCommandBar";
import HudCustomizePanel from "./HudCustomizePanel";
import EdgeRing from "./EdgeRing";
import AgentStatusWidget from "./widgets/AgentStatusWidget";
import LastTaskWidget from "./widgets/LastTaskWidget";
import AnswerWidget from "./widgets/AnswerWidget";
import ConnectionWidget from "./widgets/ConnectionWidget";
import {
  DEFAULT_HUD_PREFERENCES,
  loadHudPreferences,
  parseHudPreferences,
  saveHudPreferences,
  type HudPreferencesV1,
  type HudWidgetId,
} from "./hud-preferences";
import "./hud.css";

type HudRootStyle = CSSProperties & Record<`--hud-${string}`, string>;

function hudWidgetFromTarget(target: EventTarget | null): HTMLElement | null {
  return target instanceof Element
    ? target.closest<HTMLElement>("[data-hud-widget]")
    : null;
}

function hudWidgetId(element: HTMLElement): HudWidgetId | null {
  const value = element.dataset.hudWidget;
  return value === "agent"
    || value === "task"
    || value === "answer"
    || value === "connection"
    ? value
    : null;
}

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
  const [customizeModeRevision, setCustomizeModeRevision] =
    useState<number | null>(null);
  const customizing =
    active && customizeModeRevision === modeRevision;
  const [preferences, setPreferences] =
    useState<HudPreferencesV1>(loadHudPreferences);
  const dragRef = useRef<{
    widget: HudWidgetId;
    pointerId: number;
    halfXPct: number;
    halfYPct: number;
  } | null>(null);

  useEffect(() => {
    document.documentElement.classList.add("hud-transparent");
    return () => document.documentElement.classList.remove("hud-transparent");
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(
      () => saveHudPreferences(preferences),
      120,
    );
    return () => window.clearTimeout(timer);
  }, [preferences]);

  useEffect(() => {
    const keepWidgetsInBounds = () => {
      setPreferences((current) => {
        let changed = false;
        const positions = { ...current.positions };
        for (const widget of Object.keys(positions) as HudWidgetId[]) {
          const element = document.querySelector<HTMLElement>(
            `[data-hud-widget="${widget}"]`,
          );
          if (!element) continue;
          const rect = element.getBoundingClientRect();
          const halfXPct = rect.width / 2 / window.innerWidth * 100;
          const halfYPct = rect.height / 2 / window.innerHeight * 100;
          const position = positions[widget];
          const xPct = Math.min(
            100 - halfXPct,
            Math.max(halfXPct, position.xPct),
          );
          const yPct = Math.min(
            100 - halfYPct,
            Math.max(halfYPct, position.yPct),
          );
          if (xPct !== position.xPct || yPct !== position.yPct) {
            positions[widget] = { xPct, yPct };
            changed = true;
          }
        }
        return changed ? { ...current, positions } : current;
      });
    };
    const frame = window.requestAnimationFrame(keepWidgetsInBounds);
    window.addEventListener("resize", keepWidgetsInBounds);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", keepWidgetsInBounds);
    };
  }, [preferences.scale]);

  const dismissTopLayer = useCallback(() => {
    if (paletteOpen) {
      setPaletteOpen(false);
      return true;
    }
    if (openPanel) {
      setPanel({ name: null, modeRevision });
      return true;
    }
    if (customizing) {
      setCustomizeModeRevision(null);
      return true;
    }
    return false;
  }, [
    customizing,
    modeRevision,
    openPanel,
    paletteOpen,
    setPaletteOpen,
  ]);
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
  const updateWidgetPosition = (
    widget: HudWidgetId,
    xPct: number,
    yPct: number,
    halfXPct: number,
    halfYPct: number,
  ) => {
    setPreferences((current) => ({
      ...current,
      positions: {
        ...current.positions,
        [widget]: {
          xPct: Math.min(100 - halfXPct, Math.max(halfXPct, xPct)),
          yPct: Math.min(100 - halfYPct, Math.max(halfYPct, yPct)),
        },
      },
    }));
  };
  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!customizing) return;
    const element = hudWidgetFromTarget(event.target);
    if (!element) return;
    const widget = hudWidgetId(element);
    if (!widget) return;
    event.preventDefault();
    event.stopPropagation();
    const rect = element.getBoundingClientRect();
    dragRef.current = {
      widget,
      pointerId: event.pointerId,
      halfXPct: rect.width / 2 / window.innerWidth * 100,
      halfYPct: rect.height / 2 / window.innerHeight * 100,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    updateWidgetPosition(
      widget,
      event.clientX / window.innerWidth * 100,
      event.clientY / window.innerHeight * 100,
      dragRef.current.halfXPct,
      dragRef.current.halfYPct,
    );
  };
  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!customizing || !drag || drag.pointerId !== event.pointerId) return;
    updateWidgetPosition(
      drag.widget,
      event.clientX / window.innerWidth * 100,
      event.clientY / window.innerHeight * 100,
      drag.halfXPct,
      drag.halfYPct,
    );
  };
  const onPointerUp = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (dragRef.current?.pointerId !== event.pointerId) return;
    dragRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };
  const onWidgetKeyDown = (
    event: ReactKeyboardEvent<HTMLDivElement>,
  ) => {
    if (!customizing || !event.key.startsWith("Arrow")) return;
    const element = hudWidgetFromTarget(event.target);
    if (!element) return;
    const widget = hudWidgetId(element);
    if (!widget) return;
    event.preventDefault();
    event.stopPropagation();
    const rect = element.getBoundingClientRect();
    const halfXPct = rect.width / 2 / window.innerWidth * 100;
    const halfYPct = rect.height / 2 / window.innerHeight * 100;
    const step = event.shiftKey ? 5 : 1;
    const current = preferences.positions[widget];
    updateWidgetPosition(
      widget,
      current.xPct
        + (event.key === "ArrowRight" ? step : 0)
        - (event.key === "ArrowLeft" ? step : 0),
      current.yPct
        + (event.key === "ArrowDown" ? step : 0)
        - (event.key === "ArrowUp" ? step : 0),
      halfXPct,
      halfYPct,
    );
  };
  const rootStyle: HudRootStyle = {
    "--hud-widget-opacity": String(preferences.opacity),
    "--hud-passive-opacity": String(preferences.opacity * 0.4),
    "--hud-widget-scale": String(preferences.scale),
    "--hud-agent-x": `${preferences.positions.agent.xPct}%`,
    "--hud-agent-y": `${preferences.positions.agent.yPct}%`,
    "--hud-task-x": `${preferences.positions.task.xPct}%`,
    "--hud-task-y": `${preferences.positions.task.yPct}%`,
    "--hud-answer-x": `${preferences.positions.answer.xPct}%`,
    "--hud-answer-y": `${preferences.positions.answer.yPct}%`,
    "--hud-connection-x": `${preferences.positions.connection.xPct}%`,
    "--hud-connection-y": `${preferences.positions.connection.yPct}%`,
  };

  return (
    <div
      className={`hud-root${active ? " hud-active" : ""}${
        customizing ? " hud-customizing" : ""
      }`}
      style={rootStyle}
      onPointerDownCapture={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onKeyDownCapture={onWidgetKeyDown}
      onClickCapture={(event) => {
        if (customizing && hudWidgetFromTarget(event.target)) {
          event.preventDefault();
          event.stopPropagation();
        }
      }}
    >
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
        onCustomize={() => {
          setPanel({ name: null, modeRevision });
          setCustomizeModeRevision(modeRevision);
        }}
      />
      {customizing && (
        <HudCustomizePanel
          preferences={preferences}
          onChange={(next) => setPreferences(parseHudPreferences(next))}
          onReset={() => setPreferences(
            structuredClone(DEFAULT_HUD_PREFERENCES),
          )}
          onClose={() => setCustomizeModeRevision(null)}
        />
      )}
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
