/**
 * Cấu hình cho module STT
 */

// WebSocket URL kết nối tới Backend STT Server
// Trong production, thay bằng env variable hoặc reverse proxy
export const STT_WS_URL = "ws://localhost:8000/ws/audio";

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
