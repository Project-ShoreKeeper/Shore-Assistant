import { describe, expect, it } from "vitest";

import {
  HUD_WIDGET_MARGIN_PX,
  clampHudAxis,
  hudMarginPct,
  resolveHudPositions,
  type HudWidgetHalfSizes,
} from "./hud-layout";
import { DEFAULT_HUD_PREFERENCES } from "./hud-preferences";

const VIEWPORT = { width: 1600, height: 1000 };

const HALVES: HudWidgetHalfSizes = {
  agent: { xPct: 3, yPct: 2 },
  task: { xPct: 5, yPct: 2 },
  answer: { xPct: 10, yPct: 2 },
  connection: { xPct: 4, yPct: 2 },
};

describe("hudMarginPct", () => {
  it("converts the pixel margin into a percentage of the axis", () => {
    expect(hudMarginPct(1600)).toBe(HUD_WIDGET_MARGIN_PX / 1600 * 100);
  });
});

describe("clampHudAxis", () => {
  it("keeps a corner intent one margin away from the edge", () => {
    expect(clampHudAxis(0, 3, 1)).toBe(4);
    expect(clampHudAxis(100, 3, 1)).toBe(96);
  });

  it("leaves interior positions untouched", () => {
    expect(clampHudAxis(37, 3, 1)).toBe(37);
  });

  it("pins an oversized widget to the center", () => {
    expect(clampHudAxis(0, 55, 1)).toBe(50);
    expect(clampHudAxis(100, 55, 1)).toBe(50);
  });
});

describe("resolveHudPositions", () => {
  it("resolves the default corner intents to edges inset by the margin", () => {
    const resolved = resolveHudPositions(
      DEFAULT_HUD_PREFERENCES.positions,
      HALVES,
      VIEWPORT,
    );
    const marginX = hudMarginPct(VIEWPORT.width);
    const marginY = hudMarginPct(VIEWPORT.height);
    expect(resolved.agent.xPct).toBeCloseTo(HALVES.agent.xPct + marginX);
    expect(resolved.agent.yPct).toBeCloseTo(HALVES.agent.yPct + marginY);
    expect(resolved.task.xPct).toBeCloseTo(100 - HALVES.task.xPct - marginX);
    expect(resolved.connection.yPct).toBeCloseTo(
      100 - HALVES.connection.yPct - marginY,
    );
  });

  it("keeps a widget that mounts late fully on screen from its raw corner intent", () => {
    // Regression: the answer widget mounts only when the first answer
    // arrives; its raw (0, 100) intent must resolve on screen at that point.
    const resolved = resolveHudPositions(
      DEFAULT_HUD_PREFERENCES.positions,
      HALVES,
      VIEWPORT,
    );
    const marginX = hudMarginPct(VIEWPORT.width);
    const marginY = hudMarginPct(VIEWPORT.height);
    expect(resolved.answer.xPct).toBeCloseTo(HALVES.answer.xPct + marginX);
    expect(resolved.answer.yPct).toBeCloseTo(
      100 - HALVES.answer.yPct - marginY,
    );
    expect(resolved.answer.xPct - HALVES.answer.xPct).toBeGreaterThan(0);
    expect(resolved.answer.yPct + HALVES.answer.yPct).toBeLessThan(100);
  });

  it("returns to the original margin after a widget grows and shrinks back", () => {
    const grown: HudWidgetHalfSizes = {
      ...HALVES,
      answer: { xPct: 18, yPct: 4 },
    };
    const before = resolveHudPositions(
      DEFAULT_HUD_PREFERENCES.positions,
      HALVES,
      VIEWPORT,
    );
    const during = resolveHudPositions(
      DEFAULT_HUD_PREFERENCES.positions,
      grown,
      VIEWPORT,
    );
    const after = resolveHudPositions(
      DEFAULT_HUD_PREFERENCES.positions,
      HALVES,
      VIEWPORT,
    );
    expect(during.answer.xPct).toBeGreaterThan(before.answer.xPct);
    expect(after.answer).toEqual(before.answer);
  });

  it("does not move an unmeasured widget past the margin fallback", () => {
    const unmounted: HudWidgetHalfSizes = {
      ...HALVES,
      answer: { xPct: 0, yPct: 0 },
    };
    const resolved = resolveHudPositions(
      DEFAULT_HUD_PREFERENCES.positions,
      unmounted,
      VIEWPORT,
    );
    expect(resolved.answer.xPct).toBeCloseTo(hudMarginPct(VIEWPORT.width));
    expect(resolved.answer.yPct).toBeCloseTo(
      100 - hudMarginPct(VIEWPORT.height),
    );
  });

  it("respects a user-dragged interior intent", () => {
    const resolved = resolveHudPositions(
      {
        ...DEFAULT_HUD_PREFERENCES.positions,
        agent: { xPct: 40, yPct: 60 },
      },
      HALVES,
      VIEWPORT,
    );
    expect(resolved.agent).toEqual({ xPct: 40, yPct: 60 });
  });
});
