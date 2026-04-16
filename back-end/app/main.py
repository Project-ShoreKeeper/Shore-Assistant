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

    # n8n workflow discovery + n8nac init
    if settings.N8N_ENABLED:
        from app.services.n8n_service import n8n_service
        from app.services.n8n_workflow_service import n8n_workflow_service
        from app.tools import register_dynamic_tools

        n8n_tools = await n8n_service.initialize()
        if n8n_tools:
            register_dynamic_tools(n8n_tools)
            tool_retriever.reindex(ALL_TOOLS)
        await n8n_service.start_periodic_refresh()
        await n8n_workflow_service.init_n8nac()

    # Start proactive agent scheduler
    scheduler_service.set_fire_callback(notification_service.notify)
    scheduler_service.start()

    yield

    scheduler_service.shutdown()

    if settings.N8N_ENABLED:
        from app.services.n8n_service import n8n_service
        from app.services.n8n_workflow_service import n8n_workflow_service
        await n8n_service.shutdown()
        await n8n_workflow_service.shutdown()


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

if settings.N8N_ENABLED:
    from app.api.endpoints.n8n_webhook import router as n8n_router
    app.include_router(n8n_router)
