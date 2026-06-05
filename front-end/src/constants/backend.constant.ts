// Backend API host used by every component that talks to the FastAPI server
// directly (not over WebSocket). The chat WebSocket / VAD service still use
// their own hosts; keep them in sync if this ever changes.
export const BACKEND_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
