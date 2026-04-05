from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "Shore Assistant"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"

    # Audio
    SAMPLE_RATE: int = 16000
    AUDIO_CHANNELS: int = 1

    # Ollama LLM
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5:14b"
    OLLAMA_TIMEOUT: int = 120

    # Vision (hot-swap)
    VISION_MODEL: str = "qwen2.5vl:7b"

    # Piper TTS
    PIPER_PATH: str = "piper"
    PIPER_MODEL: str = ""
    TTS_SAMPLE_RATE: int = 22050

    class Config:
        env_file = ".env"


settings = Settings()
