export const HUD_PREFERENCES_KEY = "shore.hud.preferences.v1";

export type HudWidgetId = "agent" | "task" | "answer" | "connection";

export interface HudWidgetPosition {
  xPct: number;
  yPct: number;
}

export interface HudPreferencesV1 {
  version: 1;
  opacity: number;
  scale: number;
  positions: Record<HudWidgetId, HudWidgetPosition>;
}

export const DEFAULT_HUD_PREFERENCES: HudPreferencesV1 = {
  version: 1,
  opacity: 0.9,
  scale: 1,
  positions: {
    agent: { xPct: 12, yPct: 6 },
    task: { xPct: 88, yPct: 6 },
    answer: { xPct: 12, yPct: 94 },
    connection: { xPct: 88, yPct: 94 },
  },
};

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readPosition(
  value: unknown,
  fallback: HudWidgetPosition,
): HudWidgetPosition {
  if (
    !isRecord(value)
    || typeof value.xPct !== "number"
    || !Number.isFinite(value.xPct)
    || typeof value.yPct !== "number"
    || !Number.isFinite(value.yPct)
  ) {
    return { ...fallback };
  }
  return {
    xPct: clamp(value.xPct, 0, 100),
    yPct: clamp(value.yPct, 0, 100),
  };
}

export function parseHudPreferences(value: unknown): HudPreferencesV1 {
  if (
    !isRecord(value)
    || value.version !== 1
    || typeof value.opacity !== "number"
    || !Number.isFinite(value.opacity)
    || typeof value.scale !== "number"
    || !Number.isFinite(value.scale)
    || !isRecord(value.positions)
  ) {
    return structuredClone(DEFAULT_HUD_PREFERENCES);
  }

  return {
    version: 1,
    opacity: clamp(value.opacity, 0.2, 1),
    scale: clamp(value.scale, 0.75, 1.5),
    positions: {
      agent: readPosition(
        value.positions.agent,
        DEFAULT_HUD_PREFERENCES.positions.agent,
      ),
      task: readPosition(
        value.positions.task,
        DEFAULT_HUD_PREFERENCES.positions.task,
      ),
      answer: readPosition(
        value.positions.answer,
        DEFAULT_HUD_PREFERENCES.positions.answer,
      ),
      connection: readPosition(
        value.positions.connection,
        DEFAULT_HUD_PREFERENCES.positions.connection,
      ),
    },
  };
}

export function loadHudPreferences(): HudPreferencesV1 {
  try {
    const stored = window.localStorage.getItem(HUD_PREFERENCES_KEY);
    return stored
      ? parseHudPreferences(JSON.parse(stored))
      : structuredClone(DEFAULT_HUD_PREFERENCES);
  } catch {
    return structuredClone(DEFAULT_HUD_PREFERENCES);
  }
}

export function saveHudPreferences(preferences: HudPreferencesV1): void {
  try {
    window.localStorage.setItem(
      HUD_PREFERENCES_KEY,
      JSON.stringify(parseHudPreferences(preferences)),
    );
  } catch {
    // The current in-memory layout remains usable when storage is unavailable.
  }
}
