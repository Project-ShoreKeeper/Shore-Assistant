// Prevents an additional console window from appearing on Windows in
// release builds. Harmless on macOS. DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    shore_assistant_lib::run();
}
