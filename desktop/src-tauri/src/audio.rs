//! Native Rust audio playback engine using `rodio`.
//!
//! Bypasses WebKit / WKWebView autoplay policies by streaming PCM chunks
//! directly to the OS audio output device via rodio / cpal.
//!
//! `rodio::OutputStream` is `!Send`, so it cannot live inside Tauri's
//! `State<T>` (which requires `Send + Sync`). Instead we spawn a dedicated
//! audio thread that owns the stream and communicate with it via an `mpsc`
//! channel. This also guarantees command ordering — `Start` is always
//! processed before any `Enqueue` that was sent after it.

use base64::Engine as _;
use rodio::buffer::SamplesBuffer;
use rodio::{OutputStream, Sink};
use std::sync::{mpsc, Mutex};
use tauri::State;

/// Commands sent to the dedicated audio thread.
enum AudioCmd {
    Start(u32),
    Enqueue(Vec<f32>),
    Stop,
}

/// Tauri-managed state. Only holds a channel sender (behind a `Mutex` for
/// `Sync`), so it satisfies the `Send + Sync + 'static` bound that
/// `State<T>` requires. The non-`Send` `OutputStream` lives exclusively
/// on the background audio thread.
pub struct AudioState {
    tx: Mutex<mpsc::Sender<AudioCmd>>,
}

impl Default for AudioState {
    fn default() -> Self {
        let (tx, rx) = mpsc::channel::<AudioCmd>();

        std::thread::spawn(move || {
            // OutputStream is !Send, so it must live on this thread.
            let mut current: Option<(OutputStream, Sink, u32)> = None;

            for cmd in rx {
                match cmd {
                    AudioCmd::Start(sample_rate) => {
                        // Stop any existing stream first.
                        if let Some((_, sink, _)) = current.take() {
                            sink.stop();
                        }

                        match OutputStream::try_default() {
                            Ok((stream, handle)) => match Sink::try_new(&handle) {
                                Ok(sink) => {
                                    sink.play();
                                    println!(
                                        "[Native Audio] Started rodio stream at {sample_rate} Hz"
                                    );
                                    current = Some((stream, sink, sample_rate));
                                }
                                Err(e) => {
                                    eprintln!("[Native Audio] Failed to create audio sink: {e}");
                                }
                            },
                            Err(e) => {
                                eprintln!("[Native Audio] Failed to open output device: {e}");
                            }
                        }
                    }

                    AudioCmd::Enqueue(samples) => {
                        if let Some((_, ref sink, sr)) = current {
                            let buffer = SamplesBuffer::new(1, sr, samples);
                            sink.append(buffer);
                        } else {
                            eprintln!(
                                "[Native Audio] ⚠ enqueue called but no player active \
                                 — chunk dropped ({} samples)",
                                samples.len()
                            );
                        }
                    }

                    AudioCmd::Stop => {
                        if let Some((_, sink, _)) = current.take() {
                            sink.stop();
                            println!("[Native Audio] Stopped stream");
                        }
                    }
                }
            }
        });

        AudioState {
            tx: Mutex::new(tx),
        }
    }
}

/// Start a new native TTS audio stream with the specified sample rate (e.g. 24000 or 44100 Hz).
#[tauri::command]
pub fn tts_audio_start(state: State<AudioState>, sample_rate: u32) -> Result<(), String> {
    state
        .tx
        .lock()
        .unwrap()
        .send(AudioCmd::Start(sample_rate))
        .map_err(|e| format!("Audio thread gone: {e}"))
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

    state
        .tx
        .lock()
        .unwrap()
        .send(AudioCmd::Enqueue(samples))
        .map_err(|e| format!("Audio thread gone: {e}"))
}

/// Immediately stop native audio playback and discard remaining buffer.
#[tauri::command]
pub fn tts_audio_stop(state: State<AudioState>) -> Result<(), String> {
    state
        .tx
        .lock()
        .unwrap()
        .send(AudioCmd::Stop)
        .map_err(|e| format!("Audio thread gone: {e}"))
}
