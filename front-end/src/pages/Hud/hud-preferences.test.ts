import { describe, expect, it } from "vitest";

import {
  DEFAULT_HUD_PREFERENCES,
  parseHudPreferences,
} from "./hud-preferences";

describe("parseHudPreferences", () => {
  it("clamps numeric preferences and positions", () => {
    const parsed = parseHudPreferences({
      version: 1,
      opacity: 4,
      scale: 0.1,
      positions: {
        agent: { xPct: -10, yPct: 120 },
        task: { xPct: 80, yPct: 5 },
        answer: { xPct: 20, yPct: 95 },
        connection: { xPct: 90, yPct: 95 },
      },
    });

    expect(parsed.opacity).toBe(1);
    expect(parsed.scale).toBe(0.75);
    expect(parsed.positions.agent).toEqual({ xPct: 0, yPct: 100 });
  });

  it("falls back for malformed or old data", () => {
    expect(parseHudPreferences({ version: 2 })).toEqual(
      DEFAULT_HUD_PREFERENCES,
    );
    expect(parseHudPreferences("broken")).toEqual(DEFAULT_HUD_PREFERENCES);
  });

  it("migrates the oversized percentage defaults back to edge anchors", () => {
    const parsed = parseHudPreferences({
      version: 1,
      opacity: 0.9,
      scale: 1,
      positions: {
        agent: { xPct: 12, yPct: 6 },
        task: { xPct: 88, yPct: 6 },
        answer: { xPct: 12, yPct: 94 },
        connection: { xPct: 88, yPct: 94 },
      },
    });

    expect(parsed.positions).toEqual(DEFAULT_HUD_PREFERENCES.positions);
  });
});
