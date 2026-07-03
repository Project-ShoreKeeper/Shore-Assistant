//! HUD overlay window: transparent, always-on-top, click-through cover of
//! the primary monitor's usable work area (excluding the macOS menu bar
//! and Dock). Created on demand by `hud_show` (so the webview costs nothing
//! while the HUD is off) and destroyed by `hud_hide`.
//!
//! Two modes, tracked in [`HudState`]: passive (cursor events ignored,
//! window not focusable) and active (interactive). The global shortcut
//! toggles between them; `hud://mode { active }` is emitted on every
//! transition so both webviews can restyle.

use std::sync::atomic::{AtomicBool, Ordering};

use tauri::{AppHandle, Emitter, Manager, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};

pub const HUD_LABEL: &str = "hud";
const HUD_SHORTCUT: &str = "cmd+shift+space";

#[derive(Default)]
pub struct HudState {
    active: AtomicBool,
}

fn apply_mode(app: &AppHandle, active: bool) -> Result<(), String> {
    let Some(hud) = app.get_webview_window(HUD_LABEL) else {
        return Err("HUD window is not open.".to_string());
    };
    if active {
        hud.set_focusable(true)
            .map_err(|e| format!("Failed to make HUD focusable: {e}"))?;
        if let Err(error) = hud.set_ignore_cursor_events(false) {
            if let Err(rollback_error) = hud.set_focusable(false) {
                eprintln!("[HUD] Failed to roll back focusable state: {rollback_error}");
            }
            return Err(format!("Failed to enable HUD interaction: {error}"));
        }
        if let Err(error) = hud.set_focus() {
            if let Err(rollback_error) = hud.set_ignore_cursor_events(true) {
                eprintln!("[HUD] CRITICAL: failed to restore click-through: {rollback_error}");
            }
            if let Err(rollback_error) = hud.set_focusable(false) {
                eprintln!("[HUD] Failed to roll back focusable state: {rollback_error}");
            }
            return Err(format!("Failed to focus HUD: {error}"));
        }
    } else {
        hud.set_ignore_cursor_events(true)
            .map_err(|e| format!("Failed to restore HUD click-through: {e}"))?;
        if let Err(error) = hud.set_focusable(false) {
            eprintln!("[HUD] Failed to make passive HUD non-focusable: {error}");
        }
    }

    app.state::<HudState>()
        .active
        .store(active, Ordering::SeqCst);
    if let Err(error) = app.emit_to(
        HUD_LABEL,
        "hud://mode",
        serde_json::json!({ "active": active }),
    ) {
        if active {
            app.state::<HudState>()
                .active
                .store(false, Ordering::SeqCst);
            if let Err(rollback_error) = hud.set_ignore_cursor_events(true) {
                eprintln!("[HUD] CRITICAL: failed to restore click-through: {rollback_error}");
            }
            if let Err(rollback_error) = hud.set_focusable(false) {
                eprintln!("[HUD] Failed to roll back focusable state: {rollback_error}");
            }
        }
        return Err(format!("Failed to publish HUD mode: {error}"));
    }
    Ok(())
}

/// Returns `Ok(None)` on full success, `Ok(Some(warning))` when the window
/// was created but the global hotkey could not be registered (another app
/// owns it) — the HUD then works passive-only, per the spec's error-handling
/// section. Hard failures (no monitor, window creation, click-through)
/// return `Err` and leave no window behind.
#[tauri::command]
pub async fn hud_show(app: AppHandle) -> Result<Option<String>, String> {
    if app.get_webview_window(HUD_LABEL).is_some() {
        return Ok(None);
    }
    let monitor = app
        .primary_monitor()
        .map_err(|e| format!("Monitor query failed: {e}"))?
        .ok_or_else(|| "No primary monitor found.".to_string())?;
    let scale = monitor.scale_factor();
    // Use the OS-visible work area instead of the monitor's full bounds.
    // On macOS this keeps the top HUD widgets below the menu bar/notch and
    // the bottom widgets above the Dock without hardcoding either inset.
    let work_area = monitor.work_area();
    let size = work_area.size.to_logical::<f64>(scale);
    let pos = work_area.position.to_logical::<f64>(scale);

    let hud = WebviewWindowBuilder::new(&app, HUD_LABEL, WebviewUrl::App("/hud".into()))
        .transparent(true)
        .decorations(false)
        .always_on_top(true)
        .skip_taskbar(true)
        .visible_on_all_workspaces(true)
        .focusable(false)
        .shadow(false)
        .position(pos.x, pos.y)
        .inner_size(size.width, size.height)
        .build()
        .map_err(|e| format!("Failed to create HUD window: {e}"))?;

    // A transparent fullscreen window that is NOT click-through would
    // swallow every click on the desktop — worse than no HUD. Destroy it.
    if let Err(e) = hud.set_ignore_cursor_events(true) {
        let _ = hud.close();
        return Err(format!("Failed to enable click-through: {e}"));
    }

    app.state::<HudState>()
        .active
        .store(false, Ordering::SeqCst);
    if let Err(error) = app.emit_to(
        HUD_LABEL,
        "hud://mode",
        serde_json::json!({ "active": false }),
    ) {
        eprintln!("[HUD] Failed to publish initial passive mode: {error}");
    }

    let hotkey_warning = app
        .global_shortcut()
        .on_shortcut(HUD_SHORTCUT, |app, _shortcut, event| {
            if event.state() == ShortcutState::Pressed {
                let next = !app.state::<HudState>().active.load(Ordering::SeqCst);
                if let Err(error) = apply_mode(app, next) {
                    eprintln!("[HUD] Hotkey mode change failed: {error}");
                }
            }
        })
        .err()
        .map(|e| format!("Hotkey registration failed ({HUD_SHORTCUT}): {e}. HUD is passive-only."));
    Ok(hotkey_warning)
}

#[tauri::command]
pub async fn hud_hide(app: AppHandle) -> Result<(), String> {
    let _ = app.global_shortcut().unregister(HUD_SHORTCUT);
    app.state::<HudState>()
        .active
        .store(false, Ordering::SeqCst);
    if let Some(hud) = app.get_webview_window(HUD_LABEL) {
        hud.close()
            .map_err(|e| format!("Failed to close HUD window: {e}"))?;
    }
    Ok(())
}

#[tauri::command]
pub async fn hud_set_mode(app: AppHandle, active: bool) -> Result<(), String> {
    apply_mode(&app, active)
}
