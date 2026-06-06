// Production backend via Cloudflare Tunnel (standard HTTPS 443 → localhost:9000)
const WS_BASE_URL = import.meta.env.VITE_WS_URL || "ws://localhost:8000";

// WebSocket URL for the unified chat endpoint (STT + LLM + TTS)
export const CHAT_WS_URL = `${WS_BASE_URL}/ws/chat`;

// Default STT language used by useAssistant
export const STT_DEFAULT_LANGUAGE = "en";

export const STT_LANGUAGES = [
  { value: "en", label: "English" },
  { value: "vi", label: "Tiếng Việt" },
  { value: "auto", label: "Auto Detect" },
] as const;
