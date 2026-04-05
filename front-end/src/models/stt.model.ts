export type STTMode = "STREAMING" | "FILE_UPLOAD";

// Configuration for VAD (Voice Activity Detection)

export interface VADConfig {
  // Sample rate of the audio
  sampleRate: number;
  // Probabilities above this value are considered speech
  speechThreshold: number;
  // Threshold to exit speech state
  exitThreshold: number;
  // Minimum silence duration to consider speech ended (ms)
  minSilenceDurationMs: number;
  // Padding to add before and after speech (ms)
  speechPadMs: number;
  // Minimum duration of speech to consider valid (ms)
  minSpeechDurationMs: number;
  // Maximum buffer duration in seconds
  maxBufferDuration: number;
  // Size of input buffers from audio source
  newBufferSize: number;
}

export interface VADEvents {
  // Emitted when speech is detected
  "speech-start": void;
  // Emitted when speech has ended
  "speech-end": void;
  // Emitted when a complete speech segment is ready for transcription
  "speech-ready": { buffer: Float32Array; duration: number };
  // Emitted for status updates and errors
  status: { type: string; message: string };
  // Debug info
  debug: { message: string; data?: unknown };
}

export type VADEventCallback<K extends keyof VADEvents> = (
  event: VADEvents[K],
) => void;

//Configuration for ASR (Automatic Speech Recognition)

export interface ASRConfig {
  // Default language for recognition (e.g., 'vi', 'en', 'auto')
  defaultLanguage: string;
  // Flag to enable automatic language detection instead of using defaultLanguage
  autoDetectLanguage: boolean;
  // Size/type of the model (e.g., 'tiny', 'base', 'small', 'medium', 'large')
  modelSize?: string;
  // Automatically add punctuation and capitalization to the transcription result
  enablePunctuation: boolean;
  // Local dictionary (or context) used by the model for accurate recognition of names and acronyms
  initialPrompt?: string;
  // Decoding algorithm parameter: beam search size, expanding the search space for the best result
  beamSize?: number;
  // Temperature parameter for the AI, higher temperature generates variations but may hallucinate (usually 0 - 0.2 for ASR)
  temperature?: number;
}

// Configuration related to audio input and format

export interface AudioInputConfig {
  // Sampling frequency (e.g., 16000 Hz, optimal for STT)
  sampleRate: number;
  // Number of audio channels (1: Mono, 2: Stereo)
  channels: number;
  // Size of each data chunk when transmitting in streaming mode (bytes or number of samples)
  chunkBufferBytes?: number;
}

/**
 * Global configuration interface for the entire STT Module.
 * Can be exported to configure hooks and API calls.
 */
export interface STTConfig {
  // Operating mode of the module: Real-time streaming or audio file upload
  mode: STTMode;
  // Maximum time (ms) to wait for a server response after a request before reporting a Timeout
  responseTimeoutMs: number;
  // Maximum file size limit (MB) for uploads (if in FILE_UPLOAD mode)
  maxFileSizeMB: number;
  // Number of connection retries/request resends upon failure
  maxRetries: number;

  // Audio Input Configuration
  audio: AudioInputConfig;
  // VAD parameter configuration
  vad: VADConfig;
  // ASR parameter configuration
  asr: ASRConfig;
}

// Default configuration object for quick module initialization

export const DEFAULT_STT_CONFIG: STTConfig = {
  mode: "STREAMING",
  responseTimeoutMs: 15000,
  maxFileSizeMB: 25,
  maxRetries: 3,

  audio: {
    sampleRate: 16000,
    channels: 1,
    chunkBufferBytes: 4096, // Depends on ws sending
  },

  vad: {
    sampleRate: 16000,
    speechThreshold: 0.2,
    exitThreshold: 0.1,
    minSilenceDurationMs: 500,
    speechPadMs: 400,
    minSpeechDurationMs: 250,
    maxBufferDuration: 30,
    newBufferSize: 512,
  },

  asr: {
    defaultLanguage: "en",
    autoDetectLanguage: false,
    modelSize: "large-v3-turbo",
    enablePunctuation: true,
    beamSize: 5,
    temperature: 0.0,
  },
};
