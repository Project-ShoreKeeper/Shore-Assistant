import type { TerminalSession } from "../../models/terminal.model";

interface Props {
  sessions: TerminalSession[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onClose: (id: string) => void;
}

export default function SessionTabs({ sessions, activeId, onSelect, onClose }: Props) {
  return (
    <div className="flex gap-1 px-2 py-1 bg-slate-900 border-b border-slate-700 overflow-x-auto">
      {sessions.length === 0 && (
        <div className="text-xs text-slate-400 py-1 px-2">No active sessions</div>
      )}
      {sessions.map((s) => (
        <div
          key={s.session_id}
          className={`flex items-center gap-1 px-2 py-1 rounded text-xs cursor-pointer ${
            activeId === s.session_id
              ? "bg-slate-700 text-white"
              : "bg-slate-800 text-slate-300 hover:bg-slate-700"
          }`}
        >
          <span onClick={() => onSelect(s.session_id)}>
            {s.name} <span className="text-slate-500">({s.shell})</span>
          </span>
          <button
            onClick={(e) => {
              e.stopPropagation();
              onClose(s.session_id);
            }}
            className="ml-1 text-slate-500 hover:text-rose-400"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
