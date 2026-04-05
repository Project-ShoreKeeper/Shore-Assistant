from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.services.stt_service import stt_service
from app.services.tts_service import tts_service
from app.api.endpoints.health import router as health_router
from app.api.websockets.stt_ws import router as stt_ws_router
from app.api.websockets.chat_ws import router as chat_ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load models once at startup, clean up on shutdown."""
    stt_service.load_model()
    tts_service.warmup()
    yield


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
