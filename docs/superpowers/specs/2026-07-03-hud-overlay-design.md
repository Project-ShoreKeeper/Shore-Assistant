# HUD Overlay Mode (Desktop) — Implemented Design

**Date:** 2026-07-03

**Status:** Implemented; terminal confirmation remains security-gated

**Platform:** macOS, primary monitor

## Goal

Keep Shore visible while the user works in another application. The HUD is a
transparent, always-on-top Tauri window over the primary monitor's usable work
area. It provides ambient state in passive mode and a small keyboard-first
control surface when explicitly activated.

The HUD is not a second chat client:

- the main window remains the sole owner of `/ws/chat`, auth and backend APIs;
- the `/hud` route mounts outside `AuthProvider` and opens no backend connection;
- state and typed actions cross only targeted Tauri window events;
- the HUD has no filesystem, shell, process, opener or deep-link permissions.

## Native window and activation

- `hud_show` creates window label `hud` at `/hud` on demand.
- Geometry comes from `primary_monitor().work_area()`, excluding the macOS menu
  bar/notch and Dock.
- The window is transparent, undecorated, always on top, omitted from the
  taskbar and visible across normal workspaces.
- Passive mode is non-focusable and uses
  `set_ignore_cursor_events(true)`.
- `Cmd+Shift+Space` is registered only while the HUD is enabled and toggles
  passive/active mode.
- Active mode is visibly labelled `HUD active · Esc to close`.
- `Esc` closes the current palette/popover/customize layer first, then returns
  the HUD to passive.
- Ten seconds without pointer/keyboard/input activity always restores passive
  mode. A prompt draft is preserved.
- Any failure while entering active mode rolls back to click-through. The Rust
  side logs focus/mode failures instead of silently leaving an invisible
  input-blocking window.

`macOSPrivateApi` remains enabled for transparent-window behavior, so this
distribution is outside the Mac App Store.

## Application ownership

`HudProvider`, mounted inside the app-level `AssistantProvider`, owns:

- the Settings toggle;
- `hud_show`/`hud_hide`;
- `shore.hud.enabled` restore;
- bridge heartbeat and state derivation;
- action execution through `useAssistant`;
- navigation targets back into PageChat.

This keeps the bridge alive while the main window moves between Chat, Dashboard,
Memory and Chronicles. Unmounting the authenticated app shell hides the HUD
without clearing the stored preference, preventing stale conversation data from
remaining visible after logout.

The HUD branch in `App.tsx` skips both `AuthProvider` and `ThemePanel`.

## Event flow

```text
main window
  └─ emitTo("hud", "hud://state", HudStatePayload)  [≤ every 250 ms]
       └─ HUD presentation

HUD window
  └─ emitTo("main", "hud://action", HudAction)
       └─ validate → deduplicate → execute through main-window hooks
            └─ emitTo("hud", "hud://action-result", HudActionResult)
```

The main window also emits a full snapshot every three seconds. The HUD marks
the link unavailable after five seconds without a snapshot.

Every action:

- uses protocol `version: 1`;
- carries a bounded `requestId`;
- is validated as a discriminated union;
- receives an acknowledgement when its request ID is valid;
- times out visibly after five seconds;
- is cached for five minutes (maximum 100 results), so retries or React
  StrictMode cannot execute it twice.

Supported actions:

- `send_prompt` — trimmed text, 1–2,000 characters;
- `cancel_generation`;
- `stop_copilot`;
- `retry_connection`;
- `focus_main` — Chat, Settings or Terminal, optionally at a message ID;
- `terminal_confirm` — defined but rejected/disabled until its security gate
  passes.

## Interaction surface

### Command bar

`Cmd+Shift+Space` focuses the central `Ask Shore…` input.

- `Enter`: send.
- `Shift+Enter`: newline.
- `Cmd+K`: command palette.
- Palette: stop response, pause Co-pilot, open Co-pilot setup, retry connection,
  open chat and customize HUD.

Starting Co-pilot is intentionally not executed from a HUD event callback.
`getDisplayMedia()` requires transient user activation in the main webview, so
the HUD focuses Settings for the user to grant screen-sharing permission.

### Widgets

| Widget | Active behavior |
|---|---|
| Agent | Stop current answer, pause Co-pilot, open setup/chat |
| Last task | Show tool/status/time and open the associated message |
| Latest answer | Expand up to 4,000 characters, copy, Web Speech read/stop, open associated message |
| Connection | Retry a normal disconnect or open Settings |

Task payloads contain only message/action IDs, bounded tool name, status,
timestamp and a generated status summary. Raw args/results, commands, terminal
output, signed URLs, tokens, image data and arbitrary `detail` are not sent to
the HUD.

Manual reconnect:

- cancels old retry timers;
- detaches/replaces the stale socket;
- ignores delayed callbacks from an older socket generation;
- never retries close code `4401`; that code notifies `AuthProvider` and returns
  the app to login.

## Customization

Customize mode is available from the command palette.

- Drag widgets only while Customize mode is active.
- Arrow keys move a focused widget by 1%; Shift+arrow moves by 5%.
- Opacity range: 20–100%.
- Scale range: 75–150%.
- Stored positions are the user's intent (corner defaults or a dragged
  center); the on-screen position is resolved on every render from each
  widget's measured dimensions, so late-mounting widgets (the answer widget)
  and content-size changes keep the 16 px edge margin without ever writing
  the derived value back into preferences.
- Reset restores defaults.
- Preferences use the versioned key `shore.hud.preferences.v1`; malformed or
  incompatible data falls back safely.
- The active-mode warning is outside preference opacity/scale.

## Terminal confirmation security gate

Terminal approval from HUD is not enabled. `terminalConfirm` remains `false`
and the main executor rejects the action.

The current backend fails the prerequisites:

- `terminal_*` WebSocket messages do not enforce `ws_user_role == "admin"`;
- `terminal_service.sessions` and pending confirmations are global;
- `terminal_service.broadcast` is a singleton callback overwritten by the most
  recently connected client.

Before enabling HUD approval, backend tests must prove:

1. all terminal messages are admin-only;
2. sessions, output and confirms are scoped to their owning user/connection;
3. user A cannot view or resolve user B's confirm;
4. disconnect cleanup cannot clear another connection's broadcaster.

The HUD must expose only `Approve once`, `Deny` and `Open terminal`; never
`always_allow`.

## Verification

Automated:

```bash
cd desktop/src-tauri
cargo fmt --check
cargo check --locked
cargo clippy --locked --all-targets -- -D warnings

cd ../../front-end
npm run test:hud
npx tsc -b
npm run build
```

The scoped ESLint command and manual macOS procedure live in
`docs/superpowers/manual/hud-interactions-macos.md`.
