import type { PendingConfirm } from "../../models/terminal.model";

interface Props {
  pending: PendingConfirm[];
  onRespond: (request_id: string, decision: "approve" | "deny" | "always_allow") => void;
}

export default function ConfirmBanner({ pending, onRespond }: Props) {
  if (pending.length === 0) return null;
  return (
    <div className="border-b border-amber-300 bg-amber-50 p-3 space-y-2">
      {pending.map((p) => (
        <div key={p.request_id} className="flex flex-col gap-2">
          <div className="text-sm">
            <div className="font-semibold text-amber-700">Shore wants to run:</div>
            <code className="block bg-amber-100/50 border border-amber-200 px-2 py-1 rounded text-amber-900 break-all">
              {p.command}
            </code>
            <div className="text-xs text-amber-600/80 mt-1">
              shell: <code>{p.shell}</code> · cwd: <code>{p.cwd}</code>
              {p.reason && <> · reason: {p.reason}</>}
            </div>
          </div>
          <div className="flex gap-2 text-white">
            <button
              onClick={() => onRespond(p.request_id, "approve")}
              className="px-3 py-1 rounded bg-emerald-500 hover:bg-emerald-600 text-sm"
            >
              Approve
            </button>
            <button
              onClick={() => onRespond(p.request_id, "always_allow")}
              className="px-3 py-1 rounded bg-sky-500 hover:bg-sky-600 text-sm"
            >
              Always allow
            </button>
            <button
              onClick={() => onRespond(p.request_id, "deny")}
              className="px-3 py-1 rounded bg-rose-500 hover:bg-rose-600 text-sm"
            >
              Deny
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
