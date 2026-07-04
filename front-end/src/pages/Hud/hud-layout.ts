/**
 * Render-time widget layout resolution.
 *
 * Stored preferences hold the *intent* (corner defaults or a user-dragged
 * center); the on-screen position is derived here on every render from the
 * widget's measured half-size. Persisting the clamped output instead of the
 * intent is what previously let late-mounting widgets sit on the screen
 * corner and let margins ratchet inward as widget content changed size.
 */
import type { HudWidgetId, HudWidgetPosition } from "./hud-preferences";

export const HUD_WIDGET_MARGIN_PX = 16;

export interface HudWidgetHalfSize {
  xPct: number;
  yPct: number;
}

export type HudWidgetHalfSizes = Record<HudWidgetId, HudWidgetHalfSize>;

export interface HudViewport {
  width: number;
  height: number;
}

export function hudMarginPct(viewportAxisPx: number): number {
  if (viewportAxisPx <= 0) return 0;
  return HUD_WIDGET_MARGIN_PX / viewportAxisPx * 100;
}

/**
 * Clamp a center coordinate (percent) so the widget's edge stays at least
 * one margin inside the viewport. An oversized widget pins to the center.
 */
export function clampHudAxis(
  centerPct: number,
  halfSizePct: number,
  marginPct: number,
): number {
  const min = Math.min(50, halfSizePct + marginPct);
  const max = Math.max(50, 100 - halfSizePct - marginPct);
  return Math.min(max, Math.max(min, centerPct));
}

export function resolveHudPositions(
  intent: Record<HudWidgetId, HudWidgetPosition>,
  halfSizes: HudWidgetHalfSizes,
  viewport: HudViewport,
): Record<HudWidgetId, HudWidgetPosition> {
  const marginX = hudMarginPct(viewport.width);
  const marginY = hudMarginPct(viewport.height);
  const resolved = {} as Record<HudWidgetId, HudWidgetPosition>;
  for (const widget of Object.keys(intent) as HudWidgetId[]) {
    resolved[widget] = {
      xPct: clampHudAxis(
        intent[widget].xPct,
        halfSizes[widget].xPct,
        marginX,
      ),
      yPct: clampHudAxis(
        intent[widget].yPct,
        halfSizes[widget].yPct,
        marginY,
      ),
    };
  }
  return resolved;
}
