//! Native Rust audio playback engine using `rodio`.
//!
//! Bypasses WebKit / WKWebView autoplay policies by streaming PCM chunks
//! directly to the OS audio output device via rodio / cpal.

use base64::Engine as _;
use rodio::buffer::SamplesBuffer;
use rodio::{OutputStream, Sink};
use std::sync::{Arc, Mutex};
use tauri::State;

pub struct AudioPlayer {
    _stream: OutputStream,
    sink: Sink,
    sample_rate: u32,
}

#[derive(Default)]
pub struct AudioState {
    player: Arc<Mutex<Option<AudioPlayer>>>,
}

/// Start a new native TTS audio stream with the specified sample rate (e.g. 24000 or 44100 Hz).
#[tauri::command]
pub fn tts_audio_start(state: State<AudioState>, sample_rate: u32) -> Result<(), String> {
    // Stop any existing stream
    tts_audio_stop(state.clone())?;

    let (stream, stream_handle) = OutputStream::try_default()
        .map_err(|e| format!("Failed to open output device: {e}"))?;

    let sink = Sink::try_new(&stream_handle)
        .map_err(|e| format!("Failed to create audio sink: {e}"))?;

    sink.play();

    let player = AudioPlayer {
        _stream: stream,
        sink,
        sample_rate,
    };

    *state.player.lock().unwrap() = Some(player);
    println!("[Native Audio] Started rodio stream at {sample_rate} Hz");

    Ok(())
}

/// Enqueue a base64-encoded signed 16-bit PCM chunk into the active native stream.
#[tauri::command]
pub fn tts_audio_enqueue(state: State<AudioState>, pcm_base64: String) -> Result<(), String> {
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(&pcm_base64)
        .map_err(|e| format!("Invalid base64 PCM data: {e}"))?;

    // Convert Int16 PCM to Float32
    let samples: Vec<f32> = bytes
        .chunks_exact(2)
        .map(|chunk| {
            let sample = i16::from_le_bytes([chunk[0], chunk[1]]);
            sample as f32 / 32768.0
        })
        .collect();

    let guard = state.player.lock().unwrap();
    if let Some(ref player) = *guard {
        let buffer = SamplesBuffer::new(1, player.sample_rate, samples);
        player.sink.append(buffer);
    } else {
        eprintln!("[Native Audio] ⚠ enqueue called but no player active — chunk dropped ({} samples)", bytes.len() / 2);
    }

    Ok(())
}

/// Immediately stop native audio playback and discard remaining buffer.
#[tauri::command]
pub fn tts_audio_stop(state: State<AudioState>) -> Result<(), String> {
    let mut guard = state.player.lock().unwrap();
    if let Some(player) = guard.take() {
        player.sink.stop();
        println!("[Native Audio] Stopped stream");
    }
    Ok(())
}
