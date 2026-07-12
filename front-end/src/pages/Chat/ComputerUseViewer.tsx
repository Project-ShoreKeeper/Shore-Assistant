import type {
  ComputerUseStateMessage,
  ComputerUseStepMessage,
} from "../../services/chat-websocket.service";

interface Props {
  state: ComputerUseStateMessage | null;
  step: ComputerUseStepMessage | null;
  onStop: () => void;
}

const ACTIVE = new Set(["started", "running"]);

export function ComputerUseViewer({ state, step, onStop }: Props) {
  if (!state) return null;
  const active = ACTIVE.has(state.status);

  return (
    <div className="rounded-lg border border-neutral-700 bg-neutral-900/60 p-3 text-sm">
      <div className="mb-2 flex items-center justify-between">
        <div className="font-medium text-neutral-200">
          Computer-use: <span className="text-neutral-400">{state.goal}</span>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={
              "rounded px-2 py-0.5 text-xs " +
              (state.status === "done"
                ? "bg-green-800 text-green-200"
                : state.status === "failed"
                  ? "bg-red-800 text-red-200"
                  : state.status === "stopped"
                    ? "bg-neutral-700 text-neutral-300"
                    : "bg-blue-800 text-blue-200")
            }
          >
            {state.status} · step {state.steps_taken}
          </span>
          {active && (
            <button
              onClick={onStop}
              className="rounded bg-red-700 px-2 py-0.5 text-xs text-white hover:bg-red-600"
            >
              Stop
            </button>
          )}
        </div>
      </div>

      {step?.som_image && (
        <img
          src={step.som_image}
          alt={`OmniParser step ${step.step}`}
          className="mb-2 max-h-[50vh] w-full rounded object-contain"
        />
      )}

      {step && (
        <div className="text-xs text-neutral-300">
          <span className="font-mono text-neutral-400">#{step.step}</span>{" "}
          <span className="font-semibold">{step.action}</span>
          {step.element_content && (
            <span className="text-neutral-400"> → “{step.element_content}”</span>
          )}
          {step.reason && <div className="text-neutral-500">{step.reason}</div>}
          {step.status === "invalid" && step.error && (
            <div className="text-red-400">invalid: {step.error}</div>
          )}
        </div>
      )}

      {(state.summary || state.error) && (
        <div className="mt-2 text-xs text-neutral-400">
          {state.summary || state.error}
        </div>
      )}
    </div>
  );
}
