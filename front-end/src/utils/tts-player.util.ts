/**
 * Browser-side PCM audio queue player for TTS streaming.
 * Receives PCM chunks over WebSocket and plays them with minimal gaps
 * using AudioBufferSourceNode scheduling.
 */

export class TTSPlayer {
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
    // Recreate AudioContext if sample rate changed (e.g. switching Kokoro↔Fish Speech)
    const needsNewContext =
      !this.audioContext ||
      this.audioContext.state === "closed" ||
      this.sampleRate !== sampleRate;

    this.sampleRate = sampleRate;

    if (needsNewContext) {
      if (this.audioContext && this.audioContext.state !== "closed") {
        this.audioContext.close();
      }
      this.audioContext = new AudioContext({ sampleRate });

      // Create analyser for volume/frequency data (for avatar lip-sync)
      this.analyser = this.audioContext.createAnalyser();
      this.analyser.fftSize = 256;

      this.gainNode = this.audioContext.createGain();
      this.gainNode.gain.value = 1.0;
      this.gainNode.connect(this.analyser);
      this.analyser.connect(this.audioContext.destination);
    }

    // Resume if suspended (browser autoplay policy)
    if (this.audioContext.state === "suspended") {
      this.audioContext.resume();
    }

    this.nextStartTime = this.audioContext.currentTime;
    this.isPlaying = true;
    this.pendingChunks = 0;
  }

  /**
   * Enqueue a PCM chunk (signed 16-bit little-endian) for playback.
   */
  enqueueChunk(pcmData: ArrayBuffer): void {
    if (!this.audioContext || !this.gainNode) return;

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
   */
  stop(): void {
    this.isPlaying = false;
    this.pendingChunks = 0;
    if (this.audioContext && this.audioContext.state !== "closed") {
      this.audioContext.close();
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
    if (this.gainNode) {
      this.gainNode.gain.value = Math.max(0, Math.min(1, vol));
    }
  }
}
