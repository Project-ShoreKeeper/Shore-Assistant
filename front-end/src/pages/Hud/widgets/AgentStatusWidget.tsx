import type { HudAgentStatus } from "@Shore/services/hud-bridge.service";

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
  onClick,
}: {
  status: HudAgentStatus;
  onClick: () => void;
}) {
  return (
    <div className="hud-widget hud-tl" onClick={onClick}>
      <span className={`hud-dot ${DOT[status]}`} />
      {LABEL[status]}
    </div>
  );
}
