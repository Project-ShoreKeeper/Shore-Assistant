# Dashboard Skeleton Loading State — Design

**Date:** 2026-06-06
**Scope:** Initial-load skeleton for `front-end/src/pages/Dashboard/index.tsx`

## Problem

The dashboard shows a plain `"Loading…"` text span while the first `/api/dashboard` fetch is in flight. This looks unfinished and causes layout shift when data arrives.

## Goal

Replace the text with a pixel-accurate skeleton that matches the real card layout, animates with a shimmer, and respects all existing mobile breakpoints.

## Constraints

- Initial load only (`loading && !data`). Subsequent 5-second poll refreshes keep showing live data.
- Stay consistent with the file's inline-style pattern (no Tailwind class proliferation in JSX).
- No new dependencies.

## Design

### 1. CSS — `src/index.css`

Add at the bottom of the file:

```css
@keyframes shimmer {
  0%   { background-position: -400px 0; }
  100% { background-position:  400px 0; }
}
.skeleton-shimmer {
  background: linear-gradient(
    90deg,
    var(--md-outline-variant) 25%,
    rgba(196,198,208,0.35) 50%,
    var(--md-outline-variant) 75%
  );
  background-size: 800px 100%;
  animation: shimmer 1.4s ease-in-out infinite;
  border-radius: 6px;
}
```

Uses existing `--md-outline-variant` token so shimmer color stays on-theme.

### 2. `SkeletonBlock` primitive — `index.tsx`

```tsx
function SkeletonBlock({ width, height, style }: {
  width?: string | number;
  height?: string | number;
  style?: React.CSSProperties;
}) {
  return (
    <div
      className="skeleton-shimmer"
      style={{ width: width ?? "100%", height: height ?? 14, ...style }}
    />
  );
}
```

### 3. `DashboardSkeleton` component — `index.tsx`

Mirrors the real page layout section-by-section. Uses the same CSS class names as the live components so all mobile breakpoint overrides in `dashboard-mobile.css` apply automatically.

| Section | CSS classes reused | Card count |
|---|---|---|
| Hardware tiles | `.hw-section-grid` `.hw-tiles-row` `.hw-tile` | 4 tiles |
| GPU card | `.hw-gpu-col` | 1 card |
| Services | `.dash-grid6` `.service-card` | 6 cards |
| Databases | `.dash-grid3` | 3 cards |
| Workers | `.dash-grid3` | 3 cards |

Each skeleton card uses the real `Card` component (preserves border-radius, padding, box-shadow, accent styling) with `SkeletonBlock` children for text lines, big-number placeholders, and bars.

### 4. Wiring — `PageDashboard`

Replace line 540–541:

```tsx
// Before
{loading && !data ? (
  <span style={{ ... }}>Loading…</span>
) : data ? (

// After
{loading && !data ? (
  <DashboardSkeleton />
) : data ? (
```

No changes to `useDashboardPoll`, `DashboardContext`, or any backend code.

## Responsive behaviour

The skeleton reuses the same class names as the live layout, so `dashboard-mobile.css` breakpoints apply without any extra skeleton-specific media queries:

- Services grid collapses to single-column flex
- Service cards switch to horizontal row layout
- DB/Worker grids collapse to single column
- HW section switches to flex-column
- GPU card drops its label row
- HW tiles wrap into 2×2

## Files touched

| File | Change |
|---|---|
| `front-end/src/index.css` | Add `@keyframes shimmer` + `.skeleton-shimmer` |
| `front-end/src/pages/Dashboard/index.tsx` | Add `SkeletonBlock`, `DashboardSkeleton`; wire into `PageDashboard` |
