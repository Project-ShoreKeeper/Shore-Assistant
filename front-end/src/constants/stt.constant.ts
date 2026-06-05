/**
 * Cấu hình cho module STT
 */

// Production backend via Cloudflare Tunnel (standard HTTPS 443 → localhost:9000)
const WS_BASE_URL = import.meta.env.VITE_WS_URL || "ws://localhost:8000";

// WebSocket URL kết nối tới Backend STT Server
export const STT_WS_URL = `${WS_BASE_URL}/ws/audio`;

// WebSocket URL for the unified chat endpoint (STT + LLM + TTS)
export const CHAT_WS_URL = `${WS_BASE_URL}/ws/chat`;

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
