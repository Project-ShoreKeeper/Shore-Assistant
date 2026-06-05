import type { TerminalSession } from "../../models/terminal.model";

interface Props {
  sessions: TerminalSession[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onClose: (id: string) => void;
  /** Tighter spacing + no surrounding bar — for use inside a header. */
  compact?: boolean;
}

export default function SessionTabs({
  sessions,
  activeId,
  onSelect,
  onClose,
  compact = false,
}: Props) {
  if (compact) {
    if (sessions.length === 0) {
      return <div className="text-xs text-slate-400 px-1">no sessions</div>;
    }
    return (
      <div className="flex gap-1">
        {sessions.map((s) => (
          <div
            key={s.session_id}
            className={`flex items-center gap-1 px-2 py-0.5 rounded text-xs cursor-pointer whitespace-nowrap ${
              activeId === s.session_id
                ? "bg-white border border-slate-300 text-slate-800"
                : "bg-slate-200 text-slate-600 hover:bg-slate-300"
            }`}
          >
            <span onClick={() => onSelect(s.session_id)} title={`${s.name} (${s.shell})`}>
              {s.name}
            </span>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onClose(s.session_id);
              }}
              className="text-slate-400 hover:text-rose-500"
              aria-label={`Close ${s.name}`}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="flex gap-1 px-2 py-1 bg-slate-100 border-b border-slate-300 overflow-x-auto">
      {sessions.length === 0 && (
        <div className="text-xs text-slate-500 py-1 px-2">No active sessions</div>
      )}
      {sessions.map((s) => (
        <div
          key={s.session_id}
          className={`flex items-center gap-1 px-2 py-1 rounded text-xs cursor-pointer ${
            activeId === s.session_id
              ? "bg-white border border-slate-300 shadow-sm text-slate-800"
              : "bg-slate-200 text-slate-600 hover:bg-slate-300"
          }`}
        >
          <span onClick={() => onSelect(s.session_id)}>
            {s.name} <span className="text-slate-400">({s.shell})</span>
          </span>
          <button
            onClick={(e) => {
              e.stopPropagation();
              onClose(s.session_id);
            }}
            className="ml-1 text-slate-400 hover:text-rose-500"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
