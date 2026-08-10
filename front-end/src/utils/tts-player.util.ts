/**
 * Browser-side PCM audio queue player for TTS streaming.
 * Receives PCM chunks over WebSocket and plays them with minimal gaps
 * using AudioBufferSourceNode scheduling.
 *
 * On macOS Tauri (WKWebView), AudioContext must be unlocked during a user
 * gesture (click / keydown) before any audio can play.  Call the static
 * `TTSPlayer.unlock()` from a user-interaction handler to pre-warm the
 * shared context.
 */

function isTauriApp(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

export class TTSPlayer {
  // ── Static shared AudioContext (unlocked by user gesture) ──
  private static _sharedCtx: AudioContext | null = null;
  private static _sharedRate: number = 0;
  private static _unlocked = false;

  /**
   * Pre-unlock the Web Audio pipeline.  Must be called inside a user-gesture
   * event handler (click, keydown, touchstart, etc.) so that WebKit (WKWebView
   * on macOS / Safari) allows audio output.
   *
   * Safe to call multiple times — only the first effective call matters.
   */
  static unlock(sampleRate: number = 24000): void {
    if (isTauriApp()) return; // Native rodio handles audio directly

    // Already unlocked with matching rate → nothing to do
    if (
      TTSPlayer._unlocked &&
      TTSPlayer._sharedCtx &&
      TTSPlayer._sharedCtx.state !== "closed" &&
      TTSPlayer._sharedRate === sampleRate
    ) {
      return;
    }

    // Close stale context if rate changed
    if (TTSPlayer._sharedCtx && TTSPlayer._sharedCtx.state !== "closed") {
      TTSPlayer._sharedCtx.close().catch(() => {});
    }

    try {
      const ctx = new AudioContext({ sampleRate });
      // Play a single silent sample to fully activate the audio hardware.
      // WebKit marks the context as "allowed" only after a source has played
      // inside a user-gesture call-stack.
      const buf = ctx.createBuffer(1, 1, sampleRate);
      const src = ctx.createBufferSource();
      src.buffer = buf;
      src.connect(ctx.destination);
      src.start(0);

      TTSPlayer._sharedCtx = ctx;
      TTSPlayer._sharedRate = sampleRate;
      TTSPlayer._unlocked = true;

      // Auto-resume when the app regains focus (macOS can suspend the
      // context when the window is hidden or the lid is closed).
      ctx.onstatechange = () => {
        console.log("[TTS] AudioContext state →", ctx.state);
      };
      document.addEventListener("visibilitychange", () => {
        if (
          document.visibilityState === "visible" &&
          ctx.state === "suspended"
        ) {
          ctx.resume().catch(() => {});
        }
      });

      console.log(
        "[TTS] AudioContext unlocked",
        `(rate=${sampleRate}, state=${ctx.state})`,
      );
    } catch (err) {
      console.error("[TTS] Failed to unlock AudioContext:", err);
    }
  }

  // ── Instance fields ──
  private audioContext: AudioContext | null = null;
  private sampleRate: number = 22050;
  private nextStartTime: number = 0;
  private isPlaying: boolean = false;
  private analyser: AnalyserNode | null = null;
  private gainNode: GainNode | null = null;

  // Callback when playback finishes (all queued chunks played)
  public onPlaybackEnd: (() => void) | null = null;
  private pendingChunks: number = 0;

  /**
   * Initialize or reconfigure for a new TTS stream.
   */
  start(sampleRate: number = 22050): void {
    this.sampleRate = sampleRate;

    if (isTauriApp()) {
      void import("@tauri-apps/api/core").then(({ invoke }) => {
        invoke("tts_audio_start", { sampleRate }).catch((err) => {
          console.error("[TTS Native] Failed to start native stream:", err);
        });
      });
    }

    // Try to reuse the pre-unlocked shared context when the rate matches.
    // This is critical on WKWebView: a context created outside a user
    // gesture will start suspended and resume() will be silently rejected.
    const canReuseShared =
      TTSPlayer._sharedCtx &&
      TTSPlayer._sharedCtx.state !== "closed" &&
      TTSPlayer._sharedRate === sampleRate;

    const needsNewContext =
      !this.audioContext ||
      this.audioContext.state === "closed" ||
      this.audioContext.sampleRate !== sampleRate;

    if (needsNewContext) {
      // Detach from the old context (but don't close the shared one)
      if (
        this.audioContext &&
        this.audioContext.state !== "closed" &&
        this.audioContext !== TTSPlayer._sharedCtx
      ) {
        this.audioContext.close().catch(() => {});
      }

      if (canReuseShared) {
        this.audioContext = TTSPlayer._sharedCtx;
        console.log("[TTS] Reusing pre-unlocked AudioContext");
      } else {
        try {
          this.audioContext = new AudioContext({ sampleRate });
          console.log(
            "[TTS] Created new AudioContext",
            `(rate=${sampleRate}, state=${this.audioContext.state})`,
          );
        } catch (e) {
          console.warn("[TTS] Could not create AudioContext:", e);
        }
      }

      if (this.audioContext) {
        // Create analyser for volume/frequency data (for avatar lip-sync)
        this.analyser = this.audioContext.createAnalyser();
        this.analyser.fftSize = 256;

        this.gainNode = this.audioContext.createGain();
        // Mute Web Audio destination when in Tauri app since native rodio plays the audio
        this.gainNode.gain.value = isTauriApp() ? 0.0 : 1.0;
        this.gainNode.connect(this.analyser);
        this.analyser.connect(this.audioContext.destination);
      }
    }

    const audioContext = this.audioContext;
    if (audioContext && audioContext.state === "suspended") {
      audioContext.resume().catch((err) => {
        console.warn("[TTS] AudioContext.resume() rejected:", err);
      });
    }

    if (audioContext) {
      this.nextStartTime = audioContext.currentTime;
    }
    this.isPlaying = true;
    this.pendingChunks = 0;
  }

  /**
   * Enqueue a PCM chunk (signed 16-bit little-endian) for playback.
   */
  enqueueChunk(pcmData: ArrayBuffer): void {
    if (isTauriApp()) {
      const pcmBase64 = arrayBufferToBase64(pcmData);
      void import("@tauri-apps/api/core").then(({ invoke }) => {
        invoke("tts_audio_enqueue", { pcmBase64 }).catch((err) => {
          console.error("[TTS Native] Failed to enqueue chunk:", err);
        });
      });
    }

    if (!this.audioContext || !this.gainNode) return;

    // Attempt to resume if suspended when receiving chunks
    if (this.audioContext.state === "suspended") {
      this.audioContext.resume().catch((err) => {
        console.warn("[TTS] AudioContext.resume() rejected in enqueue:", err);
      });
    }

    // Convert Int16 PCM to Float32
    const int16View = new Int16Array(pcmData);
    const float32 = new Float32Array(int16View.length);
    for (let i = 0; i < int16View.length; i++) {
      float32[i] = int16View[i] / 32768.0;
    }

    // Create audio buffer
    const buffer = this.audioContext.createBuffer(
      1,
      float32.length,
      this.sampleRate,
    );
    buffer.getChannelData(0).set(float32);

    // Schedule playback
    const source = this.audioContext.createBufferSource();
    source.buffer = buffer;
    source.connect(this.gainNode);

    // Schedule at the end of the current queue
    const startTime = Math.max(
      this.nextStartTime,
      this.audioContext.currentTime,
    );
    source.start(startTime);

    this.pendingChunks++;
    source.onended = () => {
      this.pendingChunks--;
      if (this.pendingChunks <= 0 && !this.isPlaying) {
        this.onPlaybackEnd?.();
      }
    };

    // Advance next start time by the duration of this chunk
    this.nextStartTime = startTime + buffer.duration;
  }

  /**
   * Signal that no more chunks will arrive for this TTS stream.
   */
  end(): void {
    this.isPlaying = false;
    // If no pending chunks, fire callback immediately
    if (this.pendingChunks <= 0) {
      this.onPlaybackEnd?.();
    }
  }

  /**
   * Stop playback immediately and discard queued audio.
   *
   * Note: does NOT close the shared AudioContext — only detaches this
   * instance's nodes so a new stream can reuse the unlocked context.
   */
  stop(): void {
    if (isTauriApp()) {
      void import("@tauri-apps/api/core").then(({ invoke }) => {
        invoke("tts_audio_stop").catch((err) => {
          console.error("[TTS Native] Failed to stop stream:", err);
        });
      });
    }

    this.isPlaying = false;
    this.pendingChunks = 0;
    if (this.audioContext && this.audioContext.state !== "closed") {
      // Don't close the shared context — we'll reuse it for the next stream
      if (this.audioContext !== TTSPlayer._sharedCtx) {
        this.audioContext.close().catch(() => {});
      }
      this.audioContext = null;
      this.analyser = null;
      this.gainNode = null;
    }
  }

  /**
   * Get current volume level (0-1). Useful for avatar lip-sync.
   */
  getVolume(): number {
    if (!this.analyser) return 0;
    const data = new Uint8Array(this.analyser.frequencyBinCount);
    this.analyser.getByteTimeDomainData(data);

    let max = 0;
    for (let i = 0; i < data.length; i++) {
      const val = Math.abs(data[i] - 128) / 128;
      if (val > max) max = val;
    }
    return max;
  }

  /**
   * Get frequency data array. Useful for avatar visualization.
   */
  getFrequencyData(): Uint8Array {
    if (!this.analyser) return new Uint8Array(0);
    const data = new Uint8Array(this.analyser.frequencyBinCount);
    this.analyser.getByteFrequencyData(data);
    return data;
  }

  /**
   * Set output volume (0-1).
   */
  setVolume(vol: number): void {
    if (this.gainNode && !isTauriApp()) {
      this.gainNode.gain.value = Math.max(0, Math.min(1, vol));
    }
  }
}
