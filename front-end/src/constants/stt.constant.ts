/**
 * Cấu hình cho module STT
 */

// Auto-detect backend host from browser URL (works with Tailscale, localhost, etc.)
const BACKEND_HOST = `${window.location.hostname}:8000`;
const WS_PROTOCOL = window.location.protocol === "https:" ? "wss:" : "ws:";

// WebSocket URL kết nối tới Backend STT Server
export const STT_WS_URL = `${WS_PROTOCOL}//${BACKEND_HOST}/ws/audio`;

// WebSocket URL for the unified chat endpoint (STT + LLM + TTS)
export const CHAT_WS_URL = `${WS_PROTOCOL}//${BACKEND_HOST}/ws/chat`;

// Ngôn ngữ mặc định cho STT
export const STT_DEFAULT_LANGUAGE = "en";

// Danh sách ngôn ngữ hỗ trợ
export const STT_LANGUAGES = [
  { value: "en", label: "English" },
  { value: "vi", label: "Tiếng Việt" },
  { value: "auto", label: "Auto Detect" },
] as const;
// Danh sách model hỗ trợ (Faster-Whisper)
export const STT_MODELS = [
  { value: "tiny", label: "Tiny (Very Fast)" },
  { value: "base", label: "Base (Balanced)" },
  { value: "small", label: "Small" },
  { value: "medium", label: "Medium" },
  {
    value: "large-v3-turbo",
    label: "Large V3 Turbo",
  },
  { value: "large-v3", label: "Large V3 (Most Accurate)" },
] as const;
