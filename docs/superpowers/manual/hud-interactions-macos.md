# Interactive HUD — macOS Verification

Run this checklist in a development or signed desktop build on macOS.

## Automated preflight

```bash
cd desktop/src-tauri
cargo fmt --check
cargo check --locked
cargo clippy --locked --all-targets -- -D warnings

cd ../../front-end
npm run test:hud
npx tsc -b
npx eslint src/services/hud-actions.ts \
  src/services/hud-bridge.service.ts \
  src/services/chat-websocket.service.ts \
  src/hooks/useHudBridge.ts src/hooks/useAssistant.ts \
  src/contexts/HudProvider.tsx src/pages/Hud src/pages/Chat/index.tsx
npm run build
```

## Manual checklist

1. Enable `HUD overlay` in Chat Settings. Confirm the HUD fits below the menu
   bar/notch and above the Dock.
2. While passive, click, drag and scroll through the HUD area. The underlying
   application must receive every interaction.
3. Press `Cmd+Shift+Space`. Confirm the active warning and command input are
   visible and the input receives focus.
4. Enter a short prompt and press Return. Confirm exactly one user message is
   added in Chat and the HUD returns to passive after acknowledgement.
5. Activate again while Shore is responding. Stop the response from Agent or
   the command palette.
6. With Co-pilot active, pause it from Agent. When inactive, `Set up Co-pilot`
   must focus the main Settings panel instead of attempting screen capture from
   the HUD.
7. Open Latest answer. Verify expand, Copy, Read aloud/Stop speaking and
   Open in chat. The target chat message should scroll into view and highlight.
8. Open Last task. Verify only tool/status/time/safe summary appear and
   Open in chat targets the associated message. No raw args, terminal output or
   secret values may appear.
9. Simulate a normal WebSocket loss and press Retry. Confirm one fresh
   connection is created. Simulate close code `4401`; Retry must be disabled
   and the main app must return to login without a loop.
10. Leave the active HUD idle with both empty and non-empty drafts. It must
    become passive after ten seconds; a non-empty draft returns on reactivation.
11. Open a widget popover and press Esc twice. The first press closes the
    popover; the second returns passive.
12. Navigate the main window away from Chat. Confirm the HUD remains linked.
    Relaunch with HUD previously enabled and confirm it restores after the
    authenticated app shell mounts.
13. Open `/hud` in the hosted web build. DevTools must show no `/api/auth/me`,
    REST, WebSocket, token or deep-link activity from that route.
14. Enter Customize from `Cmd+K`. Test drag, arrow/Shift+arrow, scale, opacity,
    Reset and relaunch persistence. Resize the work area and confirm widgets
    remain visible.
15. Disable HUD. Confirm the window closes and `Cmd+Shift+Space` is no longer
    registered by Shore.

## Release blockers

- No invisible active window may intercept desktop input.
- Passive mode must not emit actions.
- Each valid request must receive one acknowledgement or a visible timeout.
- The HUD must own no backend credential or second backend connection.
- Terminal confirm must remain disabled until backend role and per-user
  isolation tests pass.
