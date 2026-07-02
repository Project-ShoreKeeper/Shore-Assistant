//! Shore Assistant desktop shell.
//!
//! This is a thin wrapper: the window hosts the bundled React app
//! (`front-end/dist`) and only three plugins are registered — deep-link
//! (OAuth callback), updater, and opener (system browser). No
//! filesystem/shell/process capabilities are granted; see
//! `capabilities/default.json` and
//! `docs/superpowers/specs/2026-07-02-tauri-desktop-client-design.md`.
//!
//! Deep-link events (`shore-assistant://auth?xchg=<token>`) are consumed
//! entirely from the frontend via the plugin's JS API (`onOpenUrl` /
//! `getCurrent`, see `front-end/src/services/deep-link.service.ts`) — Rust
//! only needs to register the plugin, there is no event relaying to do
//! here.
//!
//! Single-instance: intentionally not wired up. The single-instance
//! plugin only matters for deep-link delivery on Windows/Linux, where a
//! second process launch carries the URL as a CLI argument that needs to
//! be forwarded to the already-running instance. On macOS (the only
//! target for this iteration) the OS delivers the open-URL event
//! straight to the running app via `application:openURLs:`, so
//! `tauri-plugin-deep-link` works correctly without it. Revisit if/when
//! Windows/Linux support is added.

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_deep_link::init())
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            #[cfg(desktop)]
            {
                app.handle()
                    .plugin(tauri_plugin_updater::Builder::new().build())?;
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Shore Assistant");
}
