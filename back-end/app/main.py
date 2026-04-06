from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.services.stt_service import stt_service
from app.services.tts_service import tts_service
from app.services.tool_retriever import tool_retriever
from app.services.scheduler_service import scheduler_service
from app.services.notification_service import notification_service
from app.tools import ALL_TOOLS
from app.core.config import settings
from app.api.endpoints.health import router as health_router
from app.api.websockets.stt_ws import router as stt_ws_router
from app.api.websockets.chat_ws import router as chat_ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load models once at startup, clean up on shutdown."""
    if settings.STT_ENABLED:
        stt_service.load_model()
    else:
        print("[Startup] STT disabled — skipping Whisper model load")
    tts_service.warmup()
    tool_retriever.initialize(ALL_TOOLS)

    # Start proactive agent scheduler
    scheduler_service.set_fire_callback(notification_service.notify)
    scheduler_service.start()

    yield

    scheduler_service.shutdown()


app = FastAPI(
    title="Shore Assistant API",
    description="Backend for Shore Assistant - Voice AI with LLM, TTS, and Vision",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(stt_ws_router)
app.include_router(chat_ws_router)
