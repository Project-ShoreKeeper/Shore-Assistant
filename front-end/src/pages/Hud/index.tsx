/**
 * /hud — ambient overlay page rendered inside the transparent `hud` Tauri
 * window. Purely presentational: all data arrives over Tauri events (see
 * hud-bridge.service.ts); no WebSocket, no REST, no auth.
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type Dispatch,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type SetStateAction,
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
import {
  clampHudAxis,
  hudMarginPct,
  resolveHudPositions,
  type HudViewport,
  type HudWidgetHalfSizes,
} from "./hud-layout";
import "./hud.css";

type HudRootStyle = CSSProperties & Record<`--hud-${string}`, string>;
const HUD_WIDGET_IDS: readonly HudWidgetId[] = [
  "agent",
  "task",
  "answer",
  "connection",
];

/** Unscaled layout half-sizes in pixels; 0 while a widget is unmounted. */
type HudWidgetHalfSizesPx = Record<HudWidgetId, { x: number; y: number }>;

const ZERO_HALF_SIZES_PX: HudWidgetHalfSizesPx = {
  agent: { x: 0, y: 0 },
  task: { x: 0, y: 0 },
  answer: { x: 0, y: 0 },
  connection: { x: 0, y: 0 },
};

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

/**
 * One callback ref per widget: measures pre-paint on mount, follows content
 * size changes through a ResizeObserver, and resets to 0 on unmount. Sizes
 * come from offsetWidth/offsetHeight (transform-free), so the render-time
 * resolver can apply the preference scale itself without re-measuring.
 */
function createWidgetMeasureRefs(
  setHalfSizes: Dispatch<SetStateAction<HudWidgetHalfSizesPx>>,
): Record<HudWidgetId, (element: HTMLElement | null) => void> {
  const observers = new Map<HudWidgetId, ResizeObserver>();
  const refs = {} as Record<HudWidgetId, (element: HTMLElement | null) => void>;
  for (const widget of HUD_WIDGET_IDS) {
    refs[widget] = (element) => {
      observers.get(widget)?.disconnect();
      observers.delete(widget);
      const apply = (x: number, y: number) => {
        setHalfSizes((current) =>
          current[widget].x === x && current[widget].y === y
            ? current
            : { ...current, [widget]: { x, y } }
        );
      };
      if (!element) {
        apply(0, 0);
        return;
      }
      const measure = () =>
        apply(element.offsetWidth / 2, element.offsetHeight / 2);
      measure();
      const observer = new ResizeObserver(measure);
      observer.observe(element);
      observers.set(widget, observer);
    };
  }
  return refs;
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
  const [halfSizesPx, setHalfSizesPx] =
    useState<HudWidgetHalfSizesPx>(ZERO_HALF_SIZES_PX);
  const [viewport, setViewport] = useState<HudViewport>(() => ({
    width: window.innerWidth,
    height: window.innerHeight,
  }));
  const measureRefs = useMemo(
    () => createWidgetMeasureRefs(setHalfSizesPx),
    [],
  );
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
    const onResize = () =>
      setViewport({ width: window.innerWidth, height: window.innerHeight });
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
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
          xPct: clampHudAxis(xPct, halfXPct, hudMarginPct(window.innerWidth)),
          yPct: clampHudAxis(yPct, halfYPct, hudMarginPct(window.innerHeight)),
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
  const halfSizes = {} as HudWidgetHalfSizes;
  for (const widget of HUD_WIDGET_IDS) {
    halfSizes[widget] = {
      xPct: halfSizesPx[widget].x * preferences.scale
        / viewport.width * 100,
      yPct: halfSizesPx[widget].y * preferences.scale
        / viewport.height * 100,
    };
  }
  const positions = resolveHudPositions(
    preferences.positions,
    halfSizes,
    viewport,
  );
  const rootStyle: HudRootStyle = {
    "--hud-widget-opacity": String(preferences.opacity),
    "--hud-passive-opacity": String(preferences.opacity * 0.4),
    "--hud-widget-scale": String(preferences.scale),
    "--hud-agent-x": `${positions.agent.xPct}%`,
    "--hud-agent-y": `${positions.agent.yPct}%`,
    "--hud-task-x": `${positions.task.xPct}%`,
    "--hud-task-y": `${positions.task.yPct}%`,
    "--hud-answer-x": `${positions.answer.xPct}%`,
    "--hud-answer-y": `${positions.answer.yPct}%`,
    "--hud-connection-x": `${positions.connection.xPct}%`,
    "--hud-connection-y": `${positions.connection.yPct}%`,
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
        measureRef={measureRefs.agent}
      />
      <LastTaskWidget
        task={state?.lastTask ?? null}
        active={active}
        expanded={openPanel === "task"}
        hasPending={hasPending}
        onToggle={() => togglePanel("task")}
        sendAction={sendAction}
        measureRef={measureRefs.task}
      />
      <AnswerWidget
        answer={state?.answer ?? null}
        active={active}
        expanded={openPanel === "answer"}
        hasPending={hasPending}
        onToggle={() => togglePanel("answer")}
        sendAction={sendAction}
        measureRef={measureRefs.answer}
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
        measureRef={measureRefs.connection}
      />
    </div>
  );
}
