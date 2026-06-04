import type { OneShotRun } from "../../models/terminal.model";

interface Props {
  runs: OneShotRun[];
}

export default function OneShotHistory({ runs }: Props) {
  if (runs.length === 0) return null;
  return (
    <div className="border-b border-slate-300 max-h-40 overflow-y-auto bg-slate-50 text-xs font-mono">
      {runs.slice(-5).map((r) => (
        <details key={r.run_id} className="border-b border-slate-200">
          <summary className="px-2 py-1 cursor-pointer hover:bg-slate-100 flex justify-between">
            <span
              className={
                r.exitCode === 0
                  ? "text-emerald-600"
                  : r.exitCode === undefined
                    ? "text-amber-600"
                    : "text-rose-600"
              }
            >
              {r.exitCode === undefined ? "…" : `exit ${r.exitCode}`}
            </span>
            <code className="flex-1 ml-2 truncate text-slate-700">{r.command}</code>
            <span className="text-slate-400 ml-2">{r.shell}</span>
          </summary>
          <pre className="px-2 py-1 whitespace-pre-wrap text-slate-600">
            {r.stdout}
            {r.stderr ? "\n" + r.stderr : ""}
          </pre>
        </details>
      ))}
    </div>
  );
}
