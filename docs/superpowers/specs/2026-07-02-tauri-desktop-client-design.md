# Tauri Desktop Client — Design

Date: 2026-07-02

## Goal

Distribute Shore Assistant as an installable native desktop app so allowlisted
users (`AUTH_ALLOWED_EMAILS`) can run it on their own machine instead of
opening `bearer.shore-keeper.com` in a browser. The app talks to the existing
production backend over the internet — it is a client, not a self-hosted
deployment.

## Scope decisions

- **Target platform:** macOS first. Design must not preclude adding
  Windows/Linux later, but no Windows/Linux work happens in this iteration.
- **Build environment:** Manual builds on real Mac hardware. No CI/GitHub
  Actions in this iteration.
- **Code signing:** None for v1. Users accept the one-time Gatekeeper
  bypass (right-click → Open) on first launch. Apple Developer
  enrollment + notarization is an explicit backlog item, not required now.
- **Frontend delivery:** The existing React build (`front-end/`) is bundled
  into the Tauri app (not a native window pointed at the hosted web app).
  This lets the Tauri updater ship UI and shell together, and keeps the door
  open for native APIs later. Cost: a desktop build/publish step is now
  needed whenever the frontend changes and a desktop release is cut.

## Architecture

```
desktop/                       # new top-level dir, sibling to front-end/, back-end/
└── src-tauri/
    ├── tauri.conf.json        # frontendDist: "../../front-end/dist"
    │                          # plugins: deep-link, updater
    ├── Cargo.toml
    ├── capabilities/          # explicit permission allowlist:
    │                          # deep-link + updater ONLY — no fs/shell/process
    └── src/main.rs            # registers `shore-assistant://` scheme,
                                # relays deep-link events to the webview
```

`front-end/` is not duplicated or forked. The Tauri build's
`beforeBuildCommand` runs the existing Vite build with production env vars
pointed at the real backend:

```
VITE_API_URL=https://api.shore-keeper.com \
VITE_WS_URL=wss://conv.shore-keeper.com \
npm run build   # (in front-end/)
```

This works unmodified because `front-end/src/constants/backend.constant.ts`
and `stt.constant.ts` already externalize the API/WS base URL via
`import.meta.env.VITE_API_URL` / `VITE_WS_URL` — no frontend code changes
needed for bundling.

Runtime shape:

```
[macOS client]
  Tauri shell (Rust) — window, updater, deep-link handler
    └── WKWebView (bundled React dist, origin = tauri://localhost)
          ├── Chat WS  → wss://conv.shore-keeper.com/ws/chat
          ├── REST     → https://api.shore-keeper.com/api/*
          └── OAuth    → opens the user's system browser (never the webview)
```

## Auth flow

Google's guidance disallows OAuth consent inside an embedded webview.
Desktop login uses the standard native-app pattern: system browser +
custom URL scheme + one-time exchange.

**Why an exchange step is required:** the system browser and the app's
WKWebView have separate cookie jars. A cookie set while the OAuth callback
runs in the system browser is invisible to the app. The exchange endpoint
lets the *app's own webview* make the request that receives `Set-Cookie`,
so the session cookie lands in the right cookie jar.

### Sequence

1. User clicks "Sign in" in the app. App calls the Tauri `opener` plugin to
   open `https://api.shore-keeper.com/api/auth/login?client=desktop` in the
   OS default browser (not an in-app navigation).
2. `/api/auth/login` stores `client=desktop` alongside the existing
   `oauth_state` Redis entry, redirects to Google as today.
3. User authenticates/consents in the real browser. Google redirects to
   `/api/auth/callback` as today.
4. `/api/auth/callback`:
   - If Google returned an `error` param, or the email fails the allowlist
     check → return the error directly in the browser tab (JSON/HTML, same
     as today's `403 not_allowlisted`). Do **not** deep-link failures back
     into the app — this avoids passing error/email details through a
     URL scheme, and a plain browser-tab error is sufficient UX for "you're
     not allowed" cases.
   - On success, if the consumed state was tagged `client=desktop`: create
     the session as today, but instead of redirecting to
     `AUTH_POST_LOGIN_REDIRECT_URL`, mint a one-time exchange token (new
     Redis key, TTL ~60s, single-use, mapped to the new session id) and
     redirect to `shore-assistant://auth?xchg=<token>`.
   - If the state was not tagged desktop, behavior is unchanged (redirect
     to `AUTH_POST_LOGIN_REDIRECT_URL`, web flow as today).
5. macOS routes the `shore-assistant://` URL to the running (or newly
   launched) app. The Tauri deep-link plugin fires an event; `main.rs`
   forwards the URL to the webview.
6. The frontend (inside the app's webview) receives the deep-link URL,
   extracts `xchg`, and calls
   `POST https://api.shore-keeper.com/api/auth/exchange {token}` with
   `credentials: 'include'`.
7. Backend validates + deletes the one-time token (single-use) and sets the
   session cookie on **this** response — now stored in the app's own
   WKWebView cookie jar. From this point, every REST/WS call from the app
   is authenticated exactly like the web app today.

### Cross-site cookie requirement

The app's webview origin (`tauri://localhost` on macOS) is not part of the
`shore-keeper.com` site, unlike `bearer.shore-keeper.com` →
`api.shore-keeper.com` (same registrable domain, different subdomain,
already works with `SameSite=Lax` today). A `tauri://localhost` → 
`api.shore-keeper.com` fetch is genuinely cross-site, so the session cookie
must use `SameSite=None; Secure` or the webview will not send it back on
subsequent requests.

This is a global config change (`AUTH_COOKIE_SAMESITE` default → `"none"`),
so it also affects the existing web cookie. Accepted because CSRF token
verification (`csrf_check`) and admin-role gating already guard all
state-changing endpoints — `SameSite` was defense-in-depth, not the only
protection.

## Backend changes

- `app/core/config.py`:
  - `AUTH_COOKIE_SAMESITE` default changes from `"lax"` to `"none"`.
  - New `AUTH_DESKTOP_REDIRECT_SCHEME: str = "shore-assistant"`.
  - `AUTH_FRONTEND_ORIGINS` gains `tauri://localhost` in deployed config
    (not a code change — an env value change, documented in the config
    table).
- `app/core/auth.py` (`SessionStore`): add a one-time exchange-token
  namespace, following the existing `create_oauth_state` /
  `consume_oauth_state` pattern (TTL ~60s, single-use, delete-on-read).
- `app/api/endpoints/auth.py`:
  - `/login` accepts an optional `client` query param, threads it into the
    stored oauth_state.
  - `/callback` branches on the stored `client` flag: desktop → mint
    exchange token + redirect to the custom scheme; web → unchanged.
    Also gains explicit handling of Google's `error` query param (today's
    handler assumes `code`/`state` are always present).
  - New `POST /api/auth/exchange {token}` — validates + consumes the
    token, sets the session cookie on the response, returns the same shape
    as `/api/auth/me` (`{email, role, csrf}`). No `csrf_check` dependency:
    like `/callback`, the one-time token itself is the proof of
    possession — there is no prior session to hold a CSRF value against.
- No changes to `/ws/chat` upgrade auth, `current_user`, `csrf_check`,
  memory/dashboard/services endpoints — all continue to work unmodified
  because the desktop client ends up with an ordinary cookie session.

## Distribution & updates

- `tauri-plugin-updater`, keys generated once via `tauri signer generate`
  (update artifacts must be signed regardless of manual vs CI builds).
- Release process (manual, v1): build `.dmg`/`.app.tar.gz` on Mac hardware
  via `cargo tauri build`, upload the artifact + updated `latest.json`
  manifest to GitHub Releases. The app's updater checks this manifest.
- `desktop/README.md` documents the first-run Gatekeeper bypass
  (right-click → Open) since the app is unsigned in v1.

## Native permission scope

Tauri v2's capability system requires explicit allowlisting per API. This
app only enables `deep-link` (OAuth callback) and `updater`. No filesystem,
shell, or process capabilities are granted — the app is a webview + auth
shell. Terminal (PTY) and screen capture (Co-pilot) already run
server-side, so the client never needs local filesystem/process access.

## Error handling

- Expired or already-consumed exchange token → frontend shows "Login
  session expired, please try again," not a crash.
- Backend/WS unreachable after login → reuses the existing WS reconnect
  logic already in the frontend; no new code needed.
- Google consent denied or allowlist rejection → surfaced directly in the
  system browser tab (see step 4 above), user returns to the app and
  retries.

## Testing

- Backend: pytest coverage for `POST /api/auth/exchange` and the
  `client=desktop` branch of `/api/auth/callback` (error param handling,
  token single-use, token expiry), following existing auth test patterns.
- Desktop: manual QA on Mac hardware — full login flow (system browser →
  deep link → exchange → authenticated chat), WS reconnect after network
  loss, logout, re-login.

## Out of scope (backlog, not this iteration)

- Windows/Linux builds, CI-based build/sign/release pipeline.
- Apple Developer enrollment, code signing, notarization.
- System tray, global hotkey / wake-word, native OS notifications,
  launch-at-login — genuine "native" features beyond wrapping the existing
  web UI, deferred because the immediate goal is distribution, not new
  capability.
