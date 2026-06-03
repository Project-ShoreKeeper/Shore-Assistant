import type { OneShotRun } from "../../models/terminal.model";

interface Props {
  runs: OneShotRun[];
}

export default function OneShotHistory({ runs }: Props) {
  if (runs.length === 0) return null;
  return (
    <div className="border-b border-slate-700 max-h-40 overflow-y-auto bg-slate-950 text-xs font-mono">
      {runs.slice(-5).map((r) => (
        <details key={r.run_id} className="border-b border-slate-800">
          <summary className="px-2 py-1 cursor-pointer hover:bg-slate-900 flex justify-between">
            <span
              className={
                r.exitCode === 0
                  ? "text-emerald-400"
                  : r.exitCode === undefined
                    ? "text-amber-400"
                    : "text-rose-400"
              }
            >
              {r.exitCode === undefined ? "…" : `exit ${r.exitCode}`}
            </span>
            <code className="flex-1 ml-2 truncate text-slate-200">{r.command}</code>
            <span className="text-slate-500 ml-2">{r.shell}</span>
          </summary>
          <pre className="px-2 py-1 whitespace-pre-wrap text-slate-300">
            {r.stdout}
            {r.stderr ? "\n" + r.stderr : ""}
          </pre>
        </details>
      ))}
    </div>
  );
}
