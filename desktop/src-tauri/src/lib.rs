//! Shore Assistant desktop shell.
//!
//! This is a thin wrapper: the window hosts the bundled React app
//! (`front-end/dist`) and only three plugins are registered — deep-link
//! (OAuth callback), updater, and opener (system browser). No
//! filesystem/shell/process capabilities are granted; see
//! `capabilities/default.json` and
//! `docs/superpowers/specs/2026-07-02-tauri-desktop-client-design.md`.
//! One app command is exposed: `capture_screen_png`, the native
//! screen-capture path for the Screen Co-pilot / analyze_screen (WKWebView
//! has no `getDisplayMedia`).
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

use base64::Engine as _;

/// Capture the primary monitor as a PNG and return it as a
/// `data:image/png;base64,...` URL.
///
/// WKWebView does not implement `getDisplayMedia`, so the frontend's
/// screen-capture service (`front-end/src/services/screen-capture.service.ts`)
/// falls back to this native path when running inside Tauri. Full resolution
/// on purpose — downscaling happens in the frontend canvas, mirroring the
/// browser path. On macOS the first capture triggers the Screen Recording
/// (TCC) permission prompt; until granted the OS returns a black/empty image
/// or an error, which is surfaced as the `Err(String)`.
#[tauri::command]
async fn capture_screen_png() -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(|| {
        let monitors =
            xcap::Monitor::all().map_err(|e| format!("Failed to enumerate monitors: {e}"))?;
        let monitor = monitors
            .iter()
            .find(|m| m.is_primary().unwrap_or(false))
            .or_else(|| monitors.first())
            .ok_or_else(|| "No monitor found to capture.".to_string())?;
        let image = monitor
            .capture_image()
            .map_err(|e| format!("Screen capture failed: {e}"))?;
        let mut png = Vec::new();
        image
            .write_to(
                &mut std::io::Cursor::new(&mut png),
                xcap::image::ImageFormat::Png,
            )
            .map_err(|e| format!("PNG encoding failed: {e}"))?;
        Ok(format!(
            "data:image/png;base64,{}",
            base64::engine::general_purpose::STANDARD.encode(png)
        ))
    })
    .await
    .map_err(|e| format!("Screen capture task failed: {e}"))?
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_deep_link::init())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![capture_screen_png])
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
