//! Mouse/keyboard executor for computer-use steps. Coordinates are logical
//! screen pixels on the primary display. Requires the macOS Accessibility
//! permission; enigo errors surface as `Err(String)` so the frontend can
//! show a one-time setup callout.

use enigo::{Axis, Button, Coordinate, Direction, Enigo, Key, Keyboard, Mouse, Settings};
use serde::Deserialize;

#[derive(Debug, Deserialize)]
pub struct InputAction {
    pub func: String,
    pub x: Option<i32>,
    pub y: Option<i32>,
    pub text: Option<String>,
    pub keys: Option<Vec<String>>,
    pub dx: Option<i32>,
    pub dy: Option<i32>,
}

fn named_key(name: &str) -> Result<Key, String> {
    let key = match name.to_ascii_lowercase().as_str() {
        "enter" | "return" => Key::Return,
        "tab" => Key::Tab,
        "space" => Key::Space,
        "esc" | "escape" => Key::Escape,
        "backspace" => Key::Backspace,
        "delete" | "del" => Key::Delete,
        "up" => Key::UpArrow,
        "down" => Key::DownArrow,
        "left" => Key::LeftArrow,
        "right" => Key::RightArrow,
        "home" => Key::Home,
        "end" => Key::End,
        "pageup" => Key::PageUp,
        "pagedown" => Key::PageDown,
        "cmd" | "command" | "win" | "super" | "meta" => Key::Meta,
        "ctrl" | "control" => Key::Control,
        "alt" | "option" => Key::Alt,
        "shift" => Key::Shift,
        "f1" => Key::F1,
        "f2" => Key::F2,
        "f3" => Key::F3,
        "f4" => Key::F4,
        "f5" => Key::F5,
        "f6" => Key::F6,
        "f7" => Key::F7,
        "f8" => Key::F8,
        "f9" => Key::F9,
        "f10" => Key::F10,
        "f11" => Key::F11,
        "f12" => Key::F12,
        value if value.chars().count() == 1 => Key::Unicode(value.chars().next().unwrap()),
        other => return Err(format!("Unknown key: {other}")),
    };
    Ok(key)
}

fn run(action: InputAction) -> Result<(), String> {
    let mut enigo = Enigo::new(&Settings::default())
        .map_err(|error| format!("accessibility-denied: {error}"))?;
    let input_error = |error: enigo::InputError| format!("Input failed: {error}");
    let coords = || -> Result<(i32, i32), String> {
        match (action.x, action.y) {
            (Some(x), Some(y)) => Ok((x, y)),
            _ => Err("Missing x/y for a pointer action.".into()),
        }
    };

    match action.func.as_str() {
        "moveTo" => {
            let (x, y) = coords()?;
            enigo
                .move_mouse(x, y, Coordinate::Abs)
                .map_err(input_error)?;
        }
        "click" | "doubleClick" | "tripleClick" | "rightClick" | "middleClick" => {
            let (x, y) = coords()?;
            enigo
                .move_mouse(x, y, Coordinate::Abs)
                .map_err(input_error)?;
            let (button, times) = match action.func.as_str() {
                "rightClick" => (Button::Right, 1),
                "middleClick" => (Button::Middle, 1),
                "doubleClick" => (Button::Left, 2),
                "tripleClick" => (Button::Left, 3),
                _ => (Button::Left, 1),
            };
            for _ in 0..times {
                enigo
                    .button(button, Direction::Click)
                    .map_err(input_error)?;
            }
        }
        "dragTo" => {
            let (x, y) = coords()?;
            enigo
                .button(Button::Left, Direction::Press)
                .map_err(input_error)?;
            enigo
                .move_mouse(x, y, Coordinate::Abs)
                .map_err(input_error)?;
            enigo
                .button(Button::Left, Direction::Release)
                .map_err(input_error)?;
        }
        "scroll" | "hscroll" => {
            if let (Some(x), Some(y)) = (action.x, action.y) {
                enigo
                    .move_mouse(x, y, Coordinate::Abs)
                    .map_err(input_error)?;
            }
            if action.func == "scroll" {
                enigo
                    .scroll(-action.dy.unwrap_or(0), Axis::Vertical)
                    .map_err(input_error)?;
            } else {
                enigo
                    .scroll(action.dx.unwrap_or(0), Axis::Horizontal)
                    .map_err(input_error)?;
            }
        }
        "write" => {
            enigo
                .text(action.text.as_deref().unwrap_or(""))
                .map_err(input_error)?;
        }
        "press" => {
            for name in action.keys.clone().unwrap_or_default() {
                enigo
                    .key(named_key(&name)?, Direction::Click)
                    .map_err(input_error)?;
            }
        }
        "hotkey" => {
            let keys = action.keys.clone().unwrap_or_default();
            let parsed: Vec<Key> = keys
                .iter()
                .map(|key| named_key(key))
                .collect::<Result<_, _>>()?;
            for key in &parsed {
                enigo.key(*key, Direction::Press).map_err(input_error)?;
            }
            for key in parsed.iter().rev() {
                enigo.key(*key, Direction::Release).map_err(input_error)?;
            }
        }
        "keyDown" | "keyUp" => {
            let direction = if action.func == "keyDown" {
                Direction::Press
            } else {
                Direction::Release
            };
            for name in action.keys.clone().unwrap_or_default() {
                enigo
                    .key(named_key(&name)?, direction)
                    .map_err(input_error)?;
            }
        }
        other => return Err(format!("Unknown input func: {other}")),
    }
    Ok(())
}

#[tauri::command]
pub async fn input_execute(action: InputAction) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || run(action))
        .await
        .map_err(|error| format!("Executor task failed: {error}"))?
}
