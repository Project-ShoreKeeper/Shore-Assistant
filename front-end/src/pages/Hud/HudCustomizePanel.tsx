import HudPopover from "./HudPopover";
import type { HudPreferencesV1 } from "./hud-preferences";

export default function HudCustomizePanel({
  preferences,
  onChange,
  onReset,
  onClose,
}: {
  preferences: HudPreferencesV1;
  onChange: (preferences: HudPreferencesV1) => void;
  onReset: () => void;
  onClose: () => void;
}) {
  return (
    <HudPopover
      title="Customize HUD"
      className="hud-customize-popover"
      onClose={onClose}
    >
      <label className="hud-preference-control">
        <span>Opacity</span>
        <input
          type="range"
          min="0.2"
          max="1"
          step="0.05"
          value={preferences.opacity}
          onChange={(event) => onChange({
            ...preferences,
            opacity: Number(event.target.value),
          })}
        />
        <output>{Math.round(preferences.opacity * 100)}%</output>
      </label>
      <label className="hud-preference-control">
        <span>Scale</span>
        <input
          type="range"
          min="0.75"
          max="1.5"
          step="0.05"
          value={preferences.scale}
          onChange={(event) => onChange({
            ...preferences,
            scale: Number(event.target.value),
          })}
        />
        <output>{Math.round(preferences.scale * 100)}%</output>
      </label>
      <p className="hud-customize-hint">
        Drag a widget, or focus it and use arrow keys. Hold Shift for 5% steps.
      </p>
      <div className="hud-popover-actions">
        <button type="button" onClick={onReset}>Reset defaults</button>
        <button type="button" onClick={onClose}>Done</button>
      </div>
    </HudPopover>
  );
}
