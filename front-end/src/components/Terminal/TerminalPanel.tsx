import { useTerminal } from "../../hooks/useTerminal";
import ConfirmBanner from "./ConfirmBanner";
import SessionTabs from "./SessionTabs";
import OneShotHistory from "./OneShotHistory";
import XtermView from "./XtermView";

export default function TerminalPanel() {
  const t = useTerminal();
  const activeOutput = t.activeSessionId ? t.sessionOutput[t.activeSessionId] || "" : "";

  return (
    <div className="flex flex-col h-full bg-slate-950 text-slate-100">
      <ConfirmBanner pending={t.pendingConfirms} onRespond={t.respondConfirm} />
      <OneShotHistory runs={t.oneShotRuns} />
      <SessionTabs
        sessions={t.sessions}
        activeId={t.activeSessionId}
        onSelect={t.setActiveSessionId}
        onClose={t.closeSession}
      />
      <div className="flex-1 min-h-0 p-1">
        {t.activeSessionId ? (
          <XtermView
            output={activeOutput}
            onInput={(d) => t.sendInput(t.activeSessionId!, d)}
            onResize={(c, r) => t.resizeSession(t.activeSessionId!, c, r)}
          />
        ) : (
          <div className="h-full flex items-center justify-center text-sm text-slate-500">
            No active session. Shore can open one with the open_terminal tool.
          </div>
        )}
      </div>
    </div>
  );
}
