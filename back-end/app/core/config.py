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

    # Ollama LLM
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "gemma4-e4b"
    OLLAMA_TIMEOUT: int = 120
    OLLAMA_NUM_CTX: int = 8192

    # Vision
    VISION_MODEL: str = "qwen2.5vl:7b"
    VISION_USE_PRIMARY_MODEL: bool = False  # True = use primary LLM (must be multimodal), False = hot-swap to VISION_MODEL

    # Piper TTS
    PIPER_PATH: str = "piper"
    PIPER_MODEL: str = ""
    TTS_SAMPLE_RATE: int = 22050

    # Conversation Memory
    MEMORY_DIR: str = "data/memory"
    MEMORY_MAX_TURNS: int = 20

    # Persona
    PERSONA: str = "kuudere"  # "base" or "kuudere"

    # Scheduler
    SCHEDULER_TASKS_FILE: str = "data/scheduled_tasks.json"
    SCHEDULER_PENDING_FILE: str = "data/pending_notifications.json"

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

    class Config:
        env_file = ".env"


settings = Settings()
