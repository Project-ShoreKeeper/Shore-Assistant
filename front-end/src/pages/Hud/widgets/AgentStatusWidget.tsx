import type { HudAgentStatus } from "@Shore/services/hud-bridge.service";
import type { HudStatePayload } from "@Shore/services/hud-bridge.service";
import type { HudActionRequest } from "@Shore/services/hud-actions";

const LABEL: Record<HudAgentStatus, string> = {
  thinking: "Agent: Thinking…",
  monitoring: "Agent: Monitoring",
  idle: "Agent: Idle",
};
const DOT: Record<HudAgentStatus, string> = {
  thinking: "hud-dot-orange",
  monitoring: "hud-dot-green",
  idle: "hud-dot-gray",
};

export default function AgentStatusWidget({
  status,
  active,
  expanded,
  capabilities,
  hasPending,
  onToggle,
  sendAction,
}: {
  status: HudAgentStatus;
  active: boolean;
  expanded: boolean;
  capabilities: HudStatePayload["capabilities"];
  hasPending: boolean;
  onToggle: () => void;
  sendAction: (action: HudActionRequest) => string;
}) {
  const run = (action: HudActionRequest) => {
    if (!hasPending) sendAction(action);
  };

  return (
    <>
      <button
        type="button"
        className="hud-widget hud-tl"
        data-hud-widget="agent"
        aria-expanded={expanded}
        onClick={() => {
          if (active) onToggle();
        }}
      >
        <span className={`hud-dot ${DOT[status]}`} />
        {LABEL[status]}
      </button>
      {active && expanded && (
        <div
          className="hud-widget-popover hud-agent-popover"
          aria-label="Agent controls"
        >
          {status === "thinking" && (
            <button
              type="button"
              disabled={!capabilities.cancelGeneration || hasPending}
              onClick={() => run({ action: "cancel_generation" })}
            >
              Stop response
            </button>
          )}
          {status === "monitoring" && (
            <button
              type="button"
              disabled={!capabilities.stopCopilot || hasPending}
              onClick={() => run({ action: "stop_copilot" })}
            >
              Pause Co-pilot
            </button>
          )}
          {status === "idle" && (
            <button
              type="button"
              disabled={hasPending}
              onClick={() => run({
                action: "focus_main",
                payload: { destination: "settings" },
              })}
            >
              Set up Co-pilot in app
            </button>
          )}
          <button
            type="button"
            disabled={hasPending}
            onClick={() => run({
              action: "focus_main",
              payload: { destination: "chat" },
            })}
          >
            Open chat
          </button>
        </div>
      )}
    </>
  );
}
