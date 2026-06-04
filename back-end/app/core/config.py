from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "Shore Assistant"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"

    # Audio
    SAMPLE_RATE: int = 16000
    AUDIO_CHANNELS: int = 1

    # STT
    STT_ENABLED: bool = False

    # Llama-server LLM (llama.cpp OpenAI-compatible API)
    LLAMA_BASE_URL: str = "http://localhost:8080"
    LLAMA_MODEL: str = "gemma-4-26B-A4B-it-UD-Q5_K_M"  # llama-server typically ignores this; used only as a display label
    LLAMA_TIMEOUT: int = 120

    # Piper TTS
    PIPER_PATH: str = "piper"
    PIPER_MODEL: str = ""
    TTS_SAMPLE_RATE: int = 22050

    # Conversation Memory
    MEMORY_DIR: str = "data/memory"
    MEMORY_MAX_TURNS: int = 15

    # ── Short-term memory (Phase 1) ──
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_SHORT_TERM_KEY: str = "shore:short_term:messages"

    # ── Reserved for Phase 2 (declared, unused in P1) ──
    POSTGRES_URL: str = "postgresql://shore:changeme@localhost:5432/shore_memory"
    QDRANT_URL: str = "http://localhost:6333"

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

    # Node PTY microservice
    NODE_PTY_WS_URL: str = "wss://terminal.shore-keeper.com"
    NODE_PTY_AUTH_TOKEN: str = ""
    NODE_PTY_RECONNECT_BASE_MS: int = 1000
    NODE_PTY_RECONNECT_MAX_MS: int = 30000
    NODE_PTY_PING_INTERVAL_SECONDS: int = 30
    NODE_PTY_PING_TIMEOUT_SECONDS: int = 5

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
