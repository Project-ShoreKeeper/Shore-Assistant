import type { HudConnection } from "@Shore/services/hud-bridge.service";

export default function ConnectionWidget({
  connection,
  linked,
  onClick,
}: {
  connection: HudConnection;
  linked: boolean;
  onClick: () => void;
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
    <div className="hud-widget hud-br" onClick={onClick}>
      <span className={`hud-dot ${dot}`} />
      {label}
    </div>
  );
}
