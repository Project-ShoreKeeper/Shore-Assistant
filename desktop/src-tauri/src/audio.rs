//! Native Rust audio playback engine using `rodio`.
//!
//! Bypasses WebKit / WKWebView autoplay policies by streaming PCM chunks
//! directly to the OS audio output device via rodio / cpal.

use base64::Engine as _;
use rodio::{OutputStream, Sink, Source};
use std::collections::VecDeque;
use std::sync::mpsc::{self, Receiver, Sender, TryRecvError};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tauri::State;

/// Custom `rodio::Source` that yields Float32 PCM samples received over an MPSC channel.
pub struct PcmSource {
    receiver: Receiver<Vec<f32>>,
    buffer: VecDeque<f32>,
    sample_rate: u32,
    channels: u16,
}

impl PcmSource {
    pub fn new(receiver: Receiver<Vec<f32>>, sample_rate: u32) -> Self {
        Self {
            receiver,
            buffer: VecDeque::with_capacity(16384),
            sample_rate,
            channels: 1,
        }
    }
}

impl Iterator for PcmSource {
    type Item = f32;

    fn next(&mut self) -> Option<Self::Item> {
        while self.buffer.is_empty() {
            match self.receiver.try_recv() {
                Ok(chunk) => {
                    self.buffer.extend(chunk);
                }
                Err(TryRecvError::Empty) => {
                    // Return silence (0.0) while waiting for next WebSocket chunk
                    // to prevent audio stream underflow.
                    return Some(0.0);
                }
                Err(TryRecvError::Disconnected) => {
                    // Channel closed — end of stream.
                    return None;
                }
            }
        }
        self.buffer.pop_front()
    }
}

impl Source for PcmSource {
    fn current_frame_len(&self) -> Option<usize> {
        None
    }

    fn channels(&self) -> u16 {
        self.channels
    }

    fn sample_rate(&self) -> u32 {
        self.sample_rate
    }

    fn total_duration(&self) -> Option<Duration> {
        None
    }
}

#[derive(Default)]
pub struct AudioState {
    pcm_sender: Arc<Mutex<Option<Sender<Vec<f32>>>>>,
}

/// Start a new native TTS audio stream with the specified sample rate (e.g. 24000 or 44100 Hz).
#[tauri::command]
pub fn tts_audio_start(state: State<AudioState>, sample_rate: u32) -> Result<(), String> {
    // Stop any existing stream by dropping its sender
    tts_audio_stop(state.clone())?;

    let (tx, rx) = mpsc::channel::<Vec<f32>>();

    std::thread::Builder::new()
        .name("shore-audio-player".into())
        .spawn(move || {
            let stream_res = OutputStream::try_default();
            let (_stream, stream_handle) = match stream_res {
                Ok(res) => res,
                Err(err) => {
                    eprintln!("[Native Audio] Failed to open output device: {err}");
                    return;
                }
            };

            let sink_res = Sink::try_new(&stream_handle);
            let sink = match sink_res {
                Ok(s) => s,
                Err(err) => {
                    eprintln!("[Native Audio] Failed to create sink: {err}");
                    return;
                }
            };

            let source = PcmSource::new(rx, sample_rate);
            sink.append(source);
            sink.play();
            sink.sleep_until_end();
        })
        .map_err(|e| format!("Failed to spawn audio thread: {e}"))?;

    *state.pcm_sender.lock().unwrap() = Some(tx);
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

    let guard = state.pcm_sender.lock().unwrap();
    if let Some(ref tx) = *guard {
        let _ = tx.send(samples);
    }

    Ok(())
}

/// Immediately stop native audio playback and discard remaining buffer.
#[tauri::command]
pub fn tts_audio_stop(state: State<AudioState>) -> Result<(), String> {
    let mut guard = state.pcm_sender.lock().unwrap();
    if guard.is_some() {
        *guard = None; // Dropping the sender causes rx.try_recv() -> Disconnected, stopping PcmSource & thread
        println!("[Native Audio] Stopped stream");
    }
    Ok(())
}
