import { useEffect, useRef } from "react";
import ConfirmBanner from "./ConfirmBanner";
import OneShotHistory from "./OneShotHistory";
import SessionTabs from "./SessionTabs";
import XtermView from "./XtermView";
import type {
  OneShotRun,
  PendingConfirm,
  TerminalSession,
} from "../../models/terminal.model";

interface Props {
  open: boolean;
  height: number;
  onClose: () => void;
  onHeightChange: (h: number) => void;

  // Terminal state (lifted from useTerminal in parent)
  sessions: TerminalSession[];
  activeSessionId: string | null;
  setActiveSessionId: (id: string) => void;
  sessionOutput: Record<string, string>;
  oneShotRuns: OneShotRun[];
  pendingConfirms: PendingConfirm[];
  onRespondConfirm: (
    request_id: string,
    decision: "approve" | "deny" | "always_allow",
  ) => void;
  onSendInput: (session_id: string, data: string) => void;
  onCloseSession: (session_id: string) => void;
  onResizeSession: (session_id: string, cols: number, rows: number) => void;
}

const MIN_HEIGHT = 160;
const MAX_HEIGHT_RATIO = 0.7;

function CloseIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
      <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function TerminalIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
      <rect x="1.5" y="2.5" width="13" height="11" rx="1.5" stroke="currentColor" strokeWidth="1.2" />
      <path d="M4 6l2 2-2 2M8 10h4" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function TerminalDrawer({
  open,
  height,
  onClose,
  onHeightChange,
  sessions,
  activeSessionId,
  setActiveSessionId,
  sessionOutput,
  oneShotRuns,
  pendingConfirms,
  onRespondConfirm,
  onSendInput,
  onCloseSession,
  onResizeSession,
}: Props) {
  const dragState = useRef<{ startY: number; startHeight: number } | null>(null);

  // Global mouse handlers active only while dragging
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!dragState.current) return;
      const delta = dragState.current.startY - e.clientY; // dragging up = positive
      const next = dragState.current.startHeight + delta;
      const maxH = Math.floor(window.innerHeight * MAX_HEIGHT_RATIO);
      const clamped = Math.max(MIN_HEIGHT, Math.min(maxH, next));
      onHeightChange(clamped);
    };
    const onUp = () => {
      dragState.current = null;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [onHeightChange]);

  if (!open) return null;

  const activeOutput = activeSessionId ? sessionOutput[activeSessionId] || "" : "";

  const onDragStart = (e: React.MouseEvent) => {
    e.preventDefault();
    dragState.current = { startY: e.clientY, startHeight: height };
    document.body.style.cursor = "ns-resize";
    document.body.style.userSelect = "none";
  };

  return (
    <div
      className="flex flex-col bg-white text-slate-800 border-t border-slate-300"
      style={{
        height: `${height}px`,
        flexShrink: 0,
        position: "relative",
      }}
    >
      {/* Drag handle */}
      <div
        onMouseDown={onDragStart}
        style={{
          position: "absolute",
          top: -3,
          left: 0,
          right: 0,
          height: 6,
          cursor: "ns-resize",
          zIndex: 1,
        }}
        aria-label="Resize terminal"
      />

      {/* Header bar */}
      <div className="flex items-center gap-2 px-2 py-1 bg-slate-100 border-b border-slate-300 flex-shrink-0" style={{ height: 32 }}>
        <div className="flex items-center gap-1.5 text-slate-700 text-xs font-semibold">
          <TerminalIcon />
          Terminal
        </div>
        <div className="flex-1 min-w-0 overflow-x-auto">
          <SessionTabs
            sessions={sessions}
            activeId={activeSessionId}
            onSelect={setActiveSessionId}
            onClose={onCloseSession}
            compact
          />
        </div>
        <button
          onClick={onClose}
          aria-label="Close terminal"
          title="Close (Esc)"
          className="text-slate-500 hover:text-slate-800 px-1.5 py-1 rounded hover:bg-slate-200"
        >
          <CloseIcon />
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 min-h-0 flex flex-col">
        <ConfirmBanner pending={pendingConfirms} onRespond={onRespondConfirm} />
        <OneShotHistory runs={oneShotRuns} />
        <div className="flex-1 min-h-0 p-1">
          {activeSessionId ? (
            <XtermView
              key={activeSessionId}
              output={activeOutput}
              onInput={(d) => onSendInput(activeSessionId, d)}
              onResize={(c, r) => onResizeSession(activeSessionId, c, r)}
            />
          ) : (
            <div className="h-full flex items-center justify-center text-sm text-slate-400">
              No active session. Shore can open one with the open_terminal tool.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
