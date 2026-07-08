from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "Shore Assistant"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"

    # Audio
    SAMPLE_RATE: int = 16000
    AUDIO_CHANNELS: int = 1

    # Llama-server LLM (llama.cpp OpenAI-compatible API)
    LLAMA_BASE_URL: str = "http://localhost:8080"
    LLAMA_MODEL: str = "gemma-4-26B-A4B-it-UD-Q5_K_M"  # llama-server typically ignores this; used only as a display label
    LLAMA_TIMEOUT: int = 120

    # Piper TTS
    PIPER_PATH: str = "piper"
    PIPER_MODEL: str = ""
    TTS_SAMPLE_RATE: int = 22050

    # Conversation Memory
    MEMORY_MAX_TURNS: int = 15

    # ── Short-term memory (Phase 1) ──
    REDIS_URL: str = "redis://localhost:6379/0"
    # Base key prefix; per-user window stored at
    # `{prefix}:{user_id}:messages`.
    REDIS_SHORT_TERM_KEY: str = "shore:short_term"

    # ── Phase 2: Profile (Postgres) + Episodic (Qdrant) ──
    POSTGRES_URL: str = "postgresql://shore:changeme@localhost:5432/shore_memory"
    POSTGRES_POOL_MIN: int = 1
    POSTGRES_POOL_MAX: int = 5
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_COLLECTION: str = "shore_episodic"
    MEMORY_EPISODIC_TOP_K: int = 5
    MEMORY_EPISODIC_MIN_SCORE: float = 0.3
    MEMORY_PROFILE_MAX_BYTES: int = 2048

    # ── Phase 3: LOCOMO worker + canonicalizer ──
    WORKER_ENABLED: bool = True
    WORKER_IDLE_DELAY_SECONDS: float = 30.0
    WORKER_MAX_UNPROCESSED_MESSAGES: int = 20
    WORKER_LOCAL_LLM_URL: str = "http://localhost:8080/v1"
    # Per-attempt deadline. The request is non-streaming, so the entire
    # grammar-constrained generation must finish inside it — too low and every
    # extraction burns a full timeout on attempt 1, then silently retries.
    WORKER_LOCAL_TIMEOUT: float = 180.0
    WORKER_LOCK_KEY: str = "shore:worker:lock"
    WORKER_LOCK_TTL_SECONDS: int = 600  # must exceed WORKER_LOCAL_TIMEOUT * 3 attempts + margin
    WORKER_LAST_TS_KEY: str = "shore:worker:last_extracted_ts"

    CANONICALIZER_ENABLED: bool = True
    CANONICALIZER_CRON: str = "0 4 * * *"  # daily at 04:00 local
    CANONICALIZER_SIMILARITY_THRESHOLD: float = 0.85

    # FileBrowser
    FILEBROWSER_URL: str = "http://image.shore-keeper.com"

    # Chat image attachments — raw file storage (separate from the semantic
    # memory layers; the agent never reads this, it's purely for re-viewing
    # an image the user sent). Path is relative to the back-end/ CWD.
    IMAGE_STORAGE_DIR: str = "data/images"
    IMAGE_ATTACHMENT_MAX_DIMENSION: int = 1600  # longest edge after downscale
    IMAGE_ATTACHMENT_JPEG_QUALITY: int = 80  # re-encoded as JPEG at this quality

    # Remote server hardware probe (Glances JSON API)
    REMOTE_SERVER_ENABLED: bool = False
    REMOTE_SERVER_NAME: str = "DB Server"
    REMOTE_SERVER_GLANCES_URL: str = ""  # e.g. http://192.168.1.50:61208
    REMOTE_SERVER_SSH_ENABLED: bool = False
    REMOTE_SERVER_SSH_HOST: str = ""  # e.g. 192.168.1.211
    REMOTE_SERVER_SSH_USER: str = "monitor"
    REMOTE_SERVER_SSH_KEY_PATH: str = ""  # e.g. /home/luna/.ssh/ai_monitor_key
    REMOTE_SERVER_SSH_TIMEOUT_SECONDS: float = 5.0

    # Persona
    PERSONA: str = "kuudere"  # "base" or "kuudere"

    # Scheduler
    SCHEDULER_TASKS_FILE: str = "data/scheduled_tasks.json"
    SCHEDULER_PENDING_FILE: str = "data/pending_notifications.json"

    # Multimodal (images in chat)
    MULTIMODAL_ENABLED: bool = True
    MAX_IMAGES_PER_MESSAGE: int = 6
    MAX_IMAGE_BYTES: int = 6 * 1024 * 1024  # 6 MB after base64 decode

    # Tool Retriever
    TOOL_RETRIEVER_MODEL: str = "all-MiniLM-L6-v2"
    TOOL_RETRIEVER_TOP_K: int = 3
    TOOL_RETRIEVER_THRESHOLD: float = 0.3

    # n8n Integration
    N8N_ENABLED: bool = False
    N8N_BASE_URL: str = "http://localhost:5678"
    N8N_API_KEY: str = ""
    N8N_WEBHOOK_SECRET: str = ""
    N8N_REFRESH_INTERVAL_MINUTES: int = 0
    N8N_WORKFLOWS_DIR: str = "data/n8n-workflows"

    # Cloud AI sub-agents
    ANTHROPIC_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    CLOUD_MAX_TOKENS: int = 4096
    CLOUD_HISTORY_MAX_TURNS: int = 10

    # Shore AI microservice
    SHORE_AI_GRPC_URL: str = "ai.shore-keeper.com:443"
    SHORE_AI_SUPERVISOR_GRPC_URL: str = "ai.shore-keeper.com:8443"
    SHORE_AI_TOKEN: str = ""
    SHORE_AI_USE_TLS: bool = True
    SHORE_AI_TIMEOUT_SECONDS: float = 30.0
    SHORE_AI_EMBED_TIMEOUT_SECONDS: float = 10.0
    SHORE_AI_TTS_FIRST_CHUNK_TIMEOUT_SECONDS: float = 15.0

    # Terminal
    TERMINAL_DEFAULT_CWD: str = r"D:\Jupiter"
    TERMINAL_DEFAULT_SHELL: str = "powershell"
    TERMINAL_ONESHOT_TIMEOUT_SECONDS: int = 60
    TERMINAL_SESSION_IDLE_MINUTES: int = 30
    TERMINAL_ORPHAN_TIMEOUT_MINUTES: int = 5
    TERMINAL_CONFIRM_TIMEOUT_SECONDS: int = 300
    TERMINAL_MAX_OUTPUT_BYTES: int = 1_048_576
    TERMINAL_LLM_OUTPUT_PREVIEW_BYTES: int = 8192
    TERMINAL_WHITELIST_FILE: str = "data/terminal_whitelist.json"
    TERMINAL_USER_WHITELIST_FILE: str = "data/terminal_whitelist_user.json"
    TERMINAL_RUNS_DIR: str = "data/terminal_runs"
    TERMINAL_AUDIT_LOG: str = "data/terminal_audit.log"
    BACKGROUND_SERVICES_LOG_DIR: str = "data/background_services"

    # ── Auth (Google OAuth + Redis-backed sessions) ──
    # Master switch. When False, no login is required and all requests
    # run as a synthetic admin user — preserves pre-auth behavior.
    AUTH_ENABLED: bool = False
    # Comma-separated list of Google emails allowed to sign in.
    # The first email in the list is granted the "admin" role; all
    # others get "user". Whitespace is trimmed, case-insensitive match.
    AUTH_ALLOWED_EMAILS: str = ""
    AUTH_GOOGLE_CLIENT_ID: str = ""
    AUTH_GOOGLE_CLIENT_SECRET: str = ""
    # Secret used to sign the session-id cookie (defense in depth on
    # top of the Redis lookup). Generate a random 32+ byte value.
    AUTH_SESSION_SECRET: str = ""
    AUTH_SESSION_TTL_SECONDS: int = 7 * 24 * 3600  # 7 days, sliding
    AUTH_SESSION_KEY_PREFIX: str = "shore:session:"
    AUTH_OAUTH_STATE_KEY_PREFIX: str = "shore:oauth_state:"
    AUTH_OAUTH_STATE_TTL_SECONDS: int = 300
    AUTH_COOKIE_NAME: str = "shore_session"
    AUTH_COOKIE_SECURE: bool = True  # set False for local http dev
    # The hosted web client uses this cookie. The desktop client uses an
    # Authorization Bearer token and does not require cross-site cookies.
    AUTH_COOKIE_SAMESITE: str = "lax"
    # When frontend and backend live on different subdomains of the same
    # registrable domain (e.g. bearer.shore-keeper.com ↔ api.shore-keeper.com),
    # set this to the shared parent (e.g. ".shore-keeper.com") so the
    # session cookie is sent on both. Leave empty for same-origin dev.
    AUTH_COOKIE_DOMAIN: str = ""
    # Comma-separated allowed origins for CORS when AUTH_ENABLED.
    # Required because cookies + wildcard CORS is rejected by browsers.
    AUTH_FRONTEND_ORIGINS: str = "http://localhost:5173"
    # Where Google redirects after consent. Must exactly match a URI
    # registered in the Google Cloud OAuth client.
    AUTH_OAUTH_REDIRECT_URL: str = "http://localhost:9000/api/auth/callback"
    # Where the OAuth callback sends the browser AFTER it sets the cookie.
    # For cross-subdomain deploys (frontend on bearer.shore-keeper.com,
    # backend on api.shore-keeper.com) this MUST be an absolute URL
    # pointing at the frontend; otherwise the browser lands on the
    # backend domain. Defaults to "/" for same-origin dev.
    AUTH_POST_LOGIN_REDIRECT_URL: str = "/"
    # Custom URL scheme the desktop (Tauri) app registers for deep-link
    # OAuth handoff. /callback redirects here (with a one-time exchange
    # token) instead of AUTH_POST_LOGIN_REDIRECT_URL when the login was
    # initiated with ?client=desktop.
    AUTH_DESKTOP_REDIRECT_SCHEME: str = "shore-assistant"
    # One-time exchange-token namespace (desktop OAuth handoff). Short TTL
    # since it's consumed within seconds of the deep-link firing.
    AUTH_EXCHANGE_KEY_PREFIX: str = "shore:auth_exchange:"
    AUTH_EXCHANGE_TTL_SECONDS: int = 60

    # Node PTY microservice
    NODE_PTY_WS_URL: str = "wss://terminal.shore-keeper.com"
    NODE_PTY_AUTH_TOKEN: str = ""
    NODE_PTY_RECONNECT_BASE_MS: int = 1000
    NODE_PTY_RECONNECT_MAX_MS: int = 30000
    NODE_PTY_PING_INTERVAL_SECONDS: int = 30
    NODE_PTY_PING_TIMEOUT_SECONDS: int = 5

    # ── Client screen capture ──
    # Screen capture is client-side (browser getDisplayMedia, relayed over
    # /ws/chat) -- the backend host has no guaranteed display of its own.
    COPILOT_MAX_IMAGE_SIZE: int = 1280  # longest edge the client should target when capturing a full frame

    # --- Computer use (CUA sub-agent) ---
    EVOCUA_BASE_URL: str = "http://localhost:8081"  # second OpenAI-compatible CUA model server
    EVOCUA_API_KEY: str = ""  # sent as `Authorization: Bearer` when set (llama-server --api-key)
    EVOCUA_TIMEOUT: float = 60.0  # per-completion timeout (seconds)
    CUA_MAX_STEPS: int = 15  # hard cap on actions per run
    CUA_STEP_TIMEOUT_SECONDS: float = 30.0  # one execute+capture round-trip deadline
    CUA_SETTLE_MS: int = 800  # client wait after an action before recapture
    CUA_CAPTURE_MAX_SIZE: int = 3000  # longest-edge px for CUA frames (Retina needs more detail than the 1280 co-pilot default)
    CUA_HISTORY_MAX_TURNS: int = 4  # screenshot/action turns kept in CUA context
    CUA_AUDIT_LOG: str = "data/cua_audit.log"
    CUA_MODEL_FORMAT: str = "evocua"  # computer-use model format: evocua | ui_tars | gui_owl

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
