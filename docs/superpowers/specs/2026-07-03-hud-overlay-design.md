# HUD Overlay Mode (Desktop) — Design

**Date:** 2026-07-03
**Status:** Draft (pending user review)
**Scope:** A second, fully transparent, always-on-top Tauri window that covers the
primary monitor's usable work area (excluding the macOS menu bar/notch and Dock)
and renders an ambient HUD: a soft glowing ring around the work-area edges plus
four low-opacity corner widgets (agent status, last task, thought process,
connection). Click-through by default; a global hotkey (`Cmd+Shift+Space`) switches
between **passive** (observe-only) and **active** (interactive) modes.
**Out of scope (Phase 1):** Windows/Linux support, multi-monitor coverage, voice
invocation from the HUD, overlaying apps in native macOS fullscreen Spaces, a
standalone HUD process with its own backend connection.

## Goal

Let the user keep working in a primary application (Blender, IDE, browser) while
Shore stays visible as ambient peripheral awareness rather than a window they must
switch to. The HUD says "the agent is here and watching" without stealing a single
pixel of interactive screen estate: the mouse and keyboard pass straight through to
the app underneath until the user explicitly summons the HUD with the hotkey.

Key properties:

- **Separate window, zero backend changes.** The HUD is a second Tauri webview
  window (label `hud`) loading the `/hud` route of the same frontend bundle. The
  existing chat window remains the sole owner of the `/ws/chat` connection and
  forwards state to the HUD via Tauri events (`emit`/`listen`). The backend's
  single-client `connection_manager` is untouched.
- **Presentational only.** The `/hud` route opens no WebSocket, calls no API, and
  needs no AuthGuard. It renders exclusively from Tauri events pushed by the main
  window. If the main window dies, the HUD shows its "disconnected" state.
- **Two modes, one hotkey.** Passive: `set_ignore_cursor_events(true)`, widgets at
  ~35% opacity, ring subtle. Active: cursor events enabled, opacity ramps up, ring
  brightens, widgets become clickable. `Cmd+Shift+Space` (global, via
  `tauri-plugin-global-shortcut`) toggles; `Esc` in active mode returns to passive.
- **All data sources already exist.** No new backend telemetry: agent status maps
  from `copilotActive` + `isAssistantThinking`; last task from the tail of the
  Agent Action log; thought process from `copilot_message` / reasoning-token
  streams; connection from `wsStatus`.

## Decisions (locked with user)

| Decision | Choice |
|---|---|
| Architecture | **A** — separate HUD window fed by Tauri events from the main window (over "transform main window" and "standalone HUD + multi-client backend") |
| Global hotkey | `Cmd+Shift+Space` default (NOT `Ctrl+Space` — macOS input-source switcher conflict, especially for Vietnamese IME users); configurable later |
| Activation | Dedicated "HUD overlay" switch in the chat `SettingsPanel`, independent of the Co-pilot toggle |
| Phase 1 platform | macOS only, primary monitor only (matches current bundle targets and native screen capture) |

## Architecture

```
desktop/src-tauri/
├── tauri.conf.json               # MODIFY — "macOSPrivateApi": true (transparent windows)
├── Cargo.toml                    # ADD tauri-plugin-global-shortcut
└── src/lib.rs                    # ADD hud window builder + commands + shortcut handler

front-end/src/
├── routers/PublicRoutes.tsx      # ADD  /hud route (no AuthGuard, no AppLayout)
├── pages/Hud/
│   ├── index.tsx                 # NEW — full-screen transparent page, mode-aware
│   ├── EdgeRing.tsx              # NEW — glowing border ring (CSS only)
│   └── widgets/
│       ├── AgentStatusWidget.tsx     # top-left:  Monitoring / Thinking / Idle
│       ├── LastTaskWidget.tsx        # top-right: last agent action + relative time
│       ├── ThoughtProcessWidget.tsx  # bottom-left: copilot/reasoning stream tail
│       └── ConnectionWidget.tsx      # bottom-right: WS status dot + label
├── services/hud-bridge.service.ts # NEW — dual-role:
│                                  #   main window: subscribe app state → emit hud://state
│                                  #   hud window:  listen hud://state + hud://mode → store
└── pages/Chat/SettingsPanel.tsx   # MODIFY — "HUD overlay" switch
```

### Tauri side (Rust)

- **Window creation (runtime, not static config).** `hud_show` command builds the
  window on demand: `WebviewWindowBuilder::new(app, "hud", App("/hud"))` with
  `transparent(true)`, `decorations(false)`, `always_on_top(true)`,
  `skip_taskbar(true)`, `visible_on_all_workspaces(true)`, `focusable(false)` in
  passive mode, position/size taken from the primary monitor's `work_area()` so
  widgets stay below the macOS menu bar/notch and above the Dock, and
  `set_ignore_cursor_events(true)` immediately after creation. `hud_hide` closes it.
  Building at runtime (vs a static entry in `tauri.conf.json`) avoids paying the
  webview cost when the HUD is off.
- **`macOSPrivateApi: true`** in `tauri.conf.json` — required for true window
  transparency on macOS. Consequence: the app cannot be distributed through the Mac
  App Store (irrelevant for this personal-distribution app; updater flow is GitHub
  releases).
- **Global shortcut.** `tauri-plugin-global-shortcut`, registered when the HUD is
  shown and unregistered when hidden (no dangling system-wide hotkey while the HUD
  is off). Handler flips an `AtomicBool` mode, calls
  `hud.set_ignore_cursor_events(!active)` + `hud.set_focusable(active)`, and emits
  `hud://mode {active}` to all windows.
- **Commands:** `hud_show()`, `hud_hide()`, `hud_set_mode(active: bool)` (the last
  one so the frontend `Esc` handler and future UI buttons can drop back to passive
  without the hotkey).

### Frontend side

- **`/hud` route** renders outside `AppLayout` (no sidebar/footer). The page sets a
  `hud-transparent` class on `<html>` on mount (removed on unmount) whose CSS forces
  `html, body, #root { background: transparent }`. Radix theme stays loaded so
  widget styling matches the app.
- **`hud-bridge.service.ts`** exposes two halves:
  - `startHudBridge(snapshotFns)` — called once in the main window (inside
    `useAssistant` or a small hook next to it). Emits `hud://state` with a compact
    payload `{agent, lastTask, thought, connection}` on every relevant state change,
    throttled to ≥250 ms between emits. Also re-emits a full snapshot when the HUD
    window announces itself (`hud://ready`).
  - `useHudState()` — used by the HUD page. Listens for `hud://state`, `hud://mode`,
    emits `hud://ready` on mount, and exposes `{state, active}`. If no `hud://state`
    arrives within 5 s of mount, connection widget shows "No link to app".
- **Mode behavior in the HUD page.** `active` toggles a top-level class:
  widget opacity 0.35 → 0.9, ring intensity up, `pointer-events: none → auto`.
  `Esc` keydown (only receivable while active/focusable) invokes
  `hud_set_mode(false)`. Clicking a widget in active mode emits `hud://focus-main`;
  the main window listens and calls `setFocus()` on itself — no extra Rust command
  needed.
- **SettingsPanel switch.** "HUD overlay" `Switch` beside the Co-pilot one; on
  enable → `invoke("hud_show")`, on disable → `invoke("hud_hide")`. Switch state
  restored from `localStorage` on app start (auto-reshow if it was on). The switch
  renders only when running inside Tauri (`"__TAURI_INTERNALS__" in window`) — the
  hosted web app never shows it.

### Data mapping (no new backend events)

| Widget | Source (already in `useAssistant`) | Display |
|---|---|---|
| Agent status (top-left) | `copilotActive`, `isAssistantThinking` | `Thinking…` > `Monitoring` > `Idle` (priority order) |
| Last task (top-right) | last `AgentAction` entry | tool name + relative time ("3m ago"), refreshed every 30 s |
| Thought process (bottom-left) | streaming reasoning tokens / latest `copilot_message` | last ~120 chars, single line, ellipsized |
| Connection (bottom-right) | `wsStatus` | `Active` / `Reconnecting` / `Offline` dot + label |

## Error handling

- **Main window closed / crashed:** Tauri events stop; HUD keeps last state but the
  connection widget flips to "No link to app" after a 5 s heartbeat gap (main window
  emits `hud://state` at least every 3 s as a keepalive, even without changes).
- **Hotkey registration fails** (another app owns it): `hud_show` still succeeds;
  the error string is returned to the frontend and surfaced under the Settings
  switch (same pattern as `copilotError`). HUD remains passive-only until fixed.
- **Monitor geometry changes** (display unplugged / resolution change): Phase 1
  re-derives size on `hud_show` only; a mid-session change may leave the HUD
  mis-sized until toggled off/on. Documented limitation.
- **`set_ignore_cursor_events` failure:** if it errors on creation, `hud_show`
  returns `Err` and the window is destroyed — a non-click-through invisible
  fullscreen window would block the whole desktop, which is worse than no HUD.

## Testing

- **Unit (vitest is absent — manual + typecheck only, consistent with repo):**
  bridge payload mapping functions kept pure (state → widget payload) so they can
  be unit-tested later if test infra arrives.
- **Manual test script (added to the plan):** toggle HUD on/off; verify
  click-through in passive (click/drag/scroll reach Blender/browser underneath);
  hotkey toggles active and widgets become clickable; `Esc` returns to passive;
  quit main window → HUD shows "No link"; re-enable after relaunch restores from
  localStorage; verify no HUD switch appears in the hosted web build.

## Phasing

1. **Phase 1 (this spec):** HUD window + ring + 4 widgets + hotkey + click-through;
   active-mode interaction limited to focusing the main window.
2. **Phase 2:** voice invocation from active mode (HUD signals main window to start
   VAD), per-widget quick actions, configurable hotkey UI.
3. **Phase 3 (optional):** standalone HUD with its own backend connection —
   requires multi-client `connection_manager` refactor.
