/**
 * Browser-side & Native PCM audio queue player for TTS streaming.
 * Receives PCM chunks over WebSocket and plays them seamlessly.
 *
 * In web browsers: uses Web Audio API (AudioBufferSourceNode scheduling).
 * In Tauri desktop app: routes PCM directly to Rust rodio native player while
 * maintaining AnalyserNode for avatar lip-sync.
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
   * Pre-unlock the Web Audio pipeline. Must be called inside a user-gesture
   * event handler (click, keydown, touchstart) so WebKit allows audio output.
   */
  static unlock(sampleRate: number = 24000): void {
    if (isTauriApp()) return; // Native rodio handles audio directly in Tauri

    if (
      TTSPlayer._unlocked &&
      TTSPlayer._sharedCtx &&
      TTSPlayer._sharedCtx.state !== "closed" &&
      TTSPlayer._sharedRate === sampleRate
    ) {
      return;
    }

    if (TTSPlayer._sharedCtx && TTSPlayer._sharedCtx.state !== "closed") {
      TTSPlayer._sharedCtx.close().catch(() => {});
    }

    try {
      const ctx = new AudioContext({ sampleRate });
      const buf = ctx.createBuffer(1, 1, sampleRate);
      const src = ctx.createBufferSource();
      src.buffer = buf;
      src.connect(ctx.destination);
      src.start(0);

      TTSPlayer._sharedCtx = ctx;
      TTSPlayer._sharedRate = sampleRate;
      TTSPlayer._unlocked = true;

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

  // Promise that resolves once the native rodio player is ready.
  // enqueueChunk() awaits this before sending data to avoid dropping
  // chunks that arrive before OutputStream::try_default() completes.
  private nativeReady: Promise<void> = Promise.resolve();

  /**
   * Initialize or reconfigure for a new TTS stream.
   */
  start(sampleRate: number = 22050): void {
    this.sampleRate = sampleRate;
    this.isPlaying = true;
    this.pendingChunks = 0;

    if (isTauriApp()) {
      // Store a promise that resolves once the Rust rodio player is
      // initialised.  enqueueChunk() awaits this so PCM data is never
      // sent before the OutputStream is open.
      this.nativeReady = import("@tauri-apps/api/core")
        .then(({ invoke }) => invoke("tts_audio_start", { sampleRate }))
        .then(() => {
          console.log("[TTS Native] rodio stream ready");
        })
        .catch((err) => {
          console.error("[TTS Native] Failed to start native stream:", err);
        });
    }

    const canReuseShared =
      TTSPlayer._sharedCtx &&
      TTSPlayer._sharedCtx.state !== "closed" &&
      TTSPlayer._sharedRate === sampleRate;

    const needsNewContext =
      !this.audioContext ||
      this.audioContext.state === "closed" ||
      this.audioContext.sampleRate !== sampleRate;

    if (needsNewContext) {
      if (
        this.audioContext &&
        this.audioContext.state !== "closed" &&
        this.audioContext !== TTSPlayer._sharedCtx
      ) {
        this.audioContext.close().catch(() => {});
      }

      if (canReuseShared) {
        this.audioContext = TTSPlayer._sharedCtx;
      } else {
        try {
          this.audioContext = new AudioContext({ sampleRate });
        } catch (e) {
          console.warn("[TTS] Could not create AudioContext:", e);
        }
      }

      if (this.audioContext) {
        this.analyser = this.audioContext.createAnalyser();
        this.analyser.fftSize = 256;

        this.gainNode = this.audioContext.createGain();
        // Mute Web Audio output in Tauri since native rodio plays the audio
        this.gainNode.gain.value = isTauriApp() ? 0.0 : 1.0;
        this.gainNode.connect(this.analyser);
        this.analyser.connect(this.audioContext.destination);
      }
    }

    if (this.audioContext && this.audioContext.state === "suspended") {
      this.audioContext.resume().catch(() => {});
    }

    if (this.audioContext) {
      this.nextStartTime = this.audioContext.currentTime;
    }
  }

  /**
   * Enqueue a PCM chunk (signed 16-bit little-endian) for playback.
   */
  enqueueChunk(pcmData: ArrayBuffer): void {
    this.pendingChunks++;

    // Calculate duration in ms
    const numSamples = pcmData.byteLength / 2;
    const durationMs = (numSamples / this.sampleRate) * 1000;

    if (isTauriApp()) {
      const pcmBase64 = arrayBufferToBase64(pcmData);
      // Wait for the native player to be ready before enqueuing.
      // This prevents chunks from being silently dropped when they
      // arrive before OutputStream::try_default() finishes.
      this.nativeReady
        .then(() => import("@tauri-apps/api/core"))
        .then(({ invoke }) => {
          invoke("tts_audio_enqueue", { pcmBase64 }).catch((err) => {
            console.error("[TTS Native] Failed to enqueue chunk:", err);
          });
        });

      // Track chunk duration for Tauri native player
      setTimeout(() => {
        this.pendingChunks = Math.max(0, this.pendingChunks - 1);
        this.checkEnded();
      }, durationMs);
    }

    if (!this.audioContext || !this.gainNode) {
      if (!isTauriApp()) {
        this.pendingChunks = Math.max(0, this.pendingChunks - 1);
        this.checkEnded();
      }
      return;
    }

    if (this.audioContext.state === "suspended") {
      this.audioContext.resume().catch(() => {});
    }

    // Convert Int16 PCM to Float32
    const int16View = new Int16Array(pcmData);
    const float32 = new Float32Array(int16View.length);
    for (let i = 0; i < int16View.length; i++) {
      float32[i] = int16View[i] / 32768.0;
    }

    const buffer = this.audioContext.createBuffer(
      1,
      float32.length,
      this.sampleRate,
    );
    buffer.getChannelData(0).set(float32);

    const source = this.audioContext.createBufferSource();
    source.buffer = buffer;
    source.connect(this.gainNode);

    const startTime = Math.max(
      this.nextStartTime,
      this.audioContext.currentTime,
    );
    source.start(startTime);

    if (!isTauriApp()) {
      source.onended = () => {
        this.pendingChunks = Math.max(0, this.pendingChunks - 1);
        this.checkEnded();
      };
    }

    this.nextStartTime = startTime + buffer.duration;
  }

  /**
   * Signal that no more chunks will arrive for this TTS stream.
   */
  end(): void {
    this.isPlaying = false;
    this.checkEnded();
  }

  private checkEnded(): void {
    if (!this.isPlaying && this.pendingChunks <= 0) {
      this.onPlaybackEnd?.();
    }
  }

  /**
   * Stop playback immediately and discard queued audio.
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

