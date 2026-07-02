# Shore Assistant — Desktop Client

A Tauri v2 shell around the existing `front-end/` React app. It talks to
the production backend over the internet (`api.shore-keeper.com` /
`conv.shore-keeper.com`) — this is a client, not a self-hosted deployment.
Desktop authentication uses an opaque Bearer token obtained through the
system-browser OAuth/deep-link exchange; it does not depend on webview
cookies.
See `docs/superpowers/specs/2026-07-02-tauri-desktop-client-design.md`
for the full design (architecture, auth flow, scope decisions).

v1 scope: **macOS only**, **manual builds on real Mac hardware** (no CI),
**unsigned** (Gatekeeper bypass required on first launch).

## Prerequisites (on the Mac doing the build)

- [Rust](https://rustup.rs/) (stable toolchain)
- Xcode Command Line Tools: `xcode-select --install`
- Node.js + npm (same version the `front-end/` package expects)
- Tauri CLI: `cargo install tauri-cli --version "^2"` (or use
  `npm run tauri <cmd>` from this directory once `@tauri-apps/cli` is
  added as a devDependency — either works; examples below use `cargo
  tauri`)

## First-time setup

### 1. App icon

`tauri.conf.json` expects `icons/32x32.png`, `icons/128x128.png`,
`icons/128x128@2x.png`, `icons/icon.icns`, `icons/icon.ico` under
`desktop/src-tauri/`. These are **not committed** (binary assets,
generated from a single source image) — generate them once from a
1024x1024 source PNG:

```bash
cd desktop/src-tauri
cargo tauri icon /path/to/shore-1024.png
```

This writes the full `icons/` set (including the macOS `.icns`) via
Tauri's built-in icon pipeline — no separate macOS-only tooling needed.

### 2. Updater signing keys

The updater plugin verifies update artifacts with a keypair. Generate it
once:

```bash
cd desktop/src-tauri
cargo tauri signer generate -w ~/.tauri/shore-assistant.key
```

This prints/writes a private key (`~/.tauri/shore-assistant.key` — keep
this secret, needed to sign every future release) and a public key
(`~/.tauri/shore-assistant.key.pub`). Paste the **public** key contents
into `tauri.conf.json` → `plugins.updater.pubkey`, replacing the
`REPLACE_WITH_PUBKEY_CONTENTS_FROM_publickey.pem` placeholder.

The private key is supplied at build time via environment variables so
`cargo tauri build` can sign the artifacts it produces:

```bash
export TAURI_SIGNING_PRIVATE_KEY="$(cat ~/.tauri/shore-assistant.key)"
export TAURI_SIGNING_PRIVATE_KEY_PASSWORD="<password you set during generate, if any>"
```

## Build

From the repo root (or `desktop/src-tauri/`):

```bash
cd desktop/src-tauri
cargo tauri build
```

`beforeBuildCommand` in `tauri.conf.json` runs the existing Vite build
in `front-end/` with production env vars pointed at the real backend
(`VITE_API_URL=https://api.shore-keeper.com`,
`VITE_WS_URL=wss://conv.shore-keeper.com`) before bundling —
`front-end/` is not duplicated or modified for the desktop build, it's
built unmodified. `frontendDist` (`../../front-end/dist`) is what gets
bundled into the app.

Output lands under `desktop/src-tauri/target/release/bundle/`:
`dmg/Shore Assistant_<version>_<arch>.dmg` and `macos/Shore
Assistant.app` (also tarred to `.app.tar.gz` alongside a `.sig` file for
the updater — that's what `cargo tauri build` produces when signing keys
are set, see above).

## First-run Gatekeeper bypass

The app is unsigned (no Apple Developer account in v1), so macOS
Gatekeeper will refuse a normal double-click launch ("Shore Assistant is
damaged and can't be opened" / "cannot be opened because the developer
cannot be verified"). One-time bypass per machine:

1. Right-click (or Control-click) `Shore Assistant.app` in Finder.
2. Choose **Open**.
3. Click **Open** again in the confirmation dialog.

Subsequent launches (double-click) work normally. This is expected for
every install until the app is signed + notarized (tracked as backlog,
not required for v1 — see the spec's "Out of scope" section).

## Release process (manual, v1)

1. Bump `version` in `desktop/src-tauri/tauri.conf.json`.
2. `cargo tauri build` (with signing env vars set, see above).
3. On GitHub, create/update a release with:
   - `Shore Assistant_<version>_<arch>.dmg`
   - `Shore Assistant.app.tar.gz`
   - `Shore Assistant.app.tar.gz.sig`
   - `latest.json` — the updater manifest. `cargo tauri build` prints the
     signature; hand-assemble (or script) `latest.json` in the shape the
     updater plugin expects, e.g.:
     ```json
     {
       "version": "0.1.0",
       "notes": "Release notes here",
       "pub_date": "2026-07-03T00:00:00Z",
       "platforms": {
         "darwin-aarch64": {
           "signature": "<contents of the .sig file>",
           "url": "https://github.com/Project-ShoreKeeper/Shore-Assistant/releases/download/v0.1.0/Shore.Assistant.app.tar.gz"
         }
       }
     }
     ```
4. Upload `latest.json` to the release too — it must be reachable at the
   URL configured in `tauri.conf.json` → `plugins.updater.endpoints`
   (currently `.../releases/latest/download/latest.json`, which GitHub
   resolves to whatever release is tagged "latest").

Already-installed apps check that endpoint and prompt to update once a
newer `latest.json` is published.

## Notes / things a maintainer should know

- The `opener` capability is scoped to `https://api.shore-keeper.com/*`
  only (`capabilities/default.json`) — if the production backend host
  ever changes, update both `tauri.conf.json`'s `beforeBuildCommand` env
  vars and this capability's URL scope.
- No filesystem, shell, or process capabilities are granted to the
  webview (see `capabilities/default.json`). Terminal (PTY) and screen
  capture already run through the backend/browser APIs, not local native
  access — the desktop shell doesn't need it.
- Single-instance handling is intentionally not wired up. It only
  matters for deep-link delivery on Windows/Linux (a second process
  launch carries the URL as a CLI arg that needs forwarding); macOS
  delivers the open-URL event straight to the running app, so
  `tauri-plugin-deep-link` works correctly without it. Revisit if/when
  Windows/Linux builds are added.
- Windows/Linux, code signing, and notarization are explicitly out of
  scope for this iteration (see the design spec's "Out of scope"
  section).
