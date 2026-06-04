// Backend API host used by every component that talks to the FastAPI server
// directly (not over WebSocket). The chat WebSocket / VAD service still use
// their own hosts; keep them in sync if this ever changes.
export const BACKEND_URL = "https://api.shore-keeper.com";
