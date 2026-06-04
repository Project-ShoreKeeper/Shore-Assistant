import type { TerminalSession } from "../../models/terminal.model";

interface Props {
  sessions: TerminalSession[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onClose: (id: string) => void;
}

export default function SessionTabs({ sessions, activeId, onSelect, onClose }: Props) {
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
