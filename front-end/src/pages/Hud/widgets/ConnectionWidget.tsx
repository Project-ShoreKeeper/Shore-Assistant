import type {
  HudConnection,
  HudStatePayload,
} from "@Shore/services/hud-bridge.service";
import type { HudActionRequest } from "@Shore/services/hud-actions";
import HudPopover from "../HudPopover";

export default function ConnectionWidget({
  connection,
  linked,
  active,
  expanded,
  capabilities,
  hasPending,
  onToggle,
  sendAction,
}: {
  connection: HudConnection;
  linked: boolean;
  active: boolean;
  expanded: boolean;
  capabilities: HudStatePayload["capabilities"];
  hasPending: boolean;
  onToggle: () => void;
  sendAction: (action: HudActionRequest) => string;
}) {
  const label = !linked
    ? "No link to app"
    : connection === "active"
      ? "Connection: Active"
      : connection === "reconnecting"
        ? "Connection: Reconnecting…"
        : "Connection: Offline";
  const dot = !linked
    ? "hud-dot-red"
    : connection === "active"
      ? "hud-dot-green"
      : connection === "reconnecting"
        ? "hud-dot-orange"
        : "hud-dot-red";
  return (
    <>
      <button
        type="button"
        className="hud-widget hud-br"
        aria-expanded={expanded}
        onClick={() => {
          if (active) onToggle();
        }}
      >
        <span className={`hud-dot ${dot}`} />
        {label}
      </button>
      {active && expanded && (
        <HudPopover
          title="Connection"
          className="hud-connection-popover"
          onClose={onToggle}
        >
          <p className="hud-connection-label">{label}</p>
          <div className="hud-popover-actions">
            <button
              type="button"
              disabled={
                !linked
                || !capabilities.retryConnection
                || hasPending
              }
              onClick={() => sendAction({ action: "retry_connection" })}
            >
              Retry
            </button>
            <button
              type="button"
              disabled={!linked || hasPending}
              onClick={() => sendAction({
                action: "focus_main",
                payload: { destination: "settings" },
              })}
            >
              Open Settings
            </button>
          </div>
        </HudPopover>
      )}
    </>
  );
}
