import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.services.stt_service import stt_service
from app.services.tts_service import tts_service
from app.services.tool_retriever import tool_retriever
from app.services.scheduler_service import scheduler_service
from app.services.notification_service import notification_service
from app.services.memory import memory_facade, worker_service
from app.tools import ALL_TOOLS
from app.core.config import settings
from app.api.endpoints.health import router as health_router
from app.api.endpoints.memory import router as memory_router
from app.api.endpoints.dashboard import router as dashboard_router
from app.api.endpoints.chronicles import router as chronicles_router
from app.api.endpoints.auth import router as auth_router
from app.api.endpoints.services import router as services_router
from app.api.websockets.chat_ws import router as chat_ws_router
from app.services.service_manager import service_manager
from app.services.ai_client import channel as ai_channel_mod
from app.api import deps as auth_deps
from app.core.auth import SessionStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load models once at startup, clean up on shutdown."""
    ai_channel_mod.init()
    if settings.STT_ENABLED:
        stt_service.load_model()
    else:
        print("[Startup] STT disabled — skipping Whisper model load")
    tts_service.warmup()

    from app.services.embedding_service import embedding_service
    embedding_service.startup()

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

    # Start terminal service (deferred tasks e.g. NodePtyClient reconnect/heartbeat)
    from app.services.terminal_service import terminal_service, _idle_reaper
    await terminal_service.startup()
    idle_reaper_task = asyncio.create_task(_idle_reaper(terminal_service))

    # Initialize memory facade
    await memory_facade.startup()

    # Wire the auth session store onto the same Redis the memory facade uses.
    # Session lookups share the connection pool — no extra infra cost.
    auth_deps.set_session_store(SessionStore(
        redis=memory_facade._redis,
        ttl_seconds=settings.AUTH_SESSION_TTL_SECONDS,
        key_prefix=settings.AUTH_SESSION_KEY_PREFIX,
    ))
    if settings.AUTH_ENABLED:
        print(
            f"[Auth] enabled — allowlist={settings.AUTH_ALLOWED_EMAILS!r} "
            f"redirect={settings.AUTH_OAUTH_REDIRECT_URL}"
        )
    else:
        print("[Auth] disabled (AUTH_ENABLED=False) — running as legacy admin")

    # Phase 3: LOCOMO worker
    if settings.WORKER_ENABLED:
        await worker_service.startup(
            redis=memory_facade._redis, facade=memory_facade,
        )

    # Register canonicalizer as internal scheduler job
    if settings.CANONICALIZER_ENABLED:
        from app.services.memory.canonicalizer import run_canonicalization
        scheduler_service.add_system_job(
            run_canonicalization,
            cron=settings.CANONICALIZER_CRON,
            job_id="memory_canonicalizer",
        )

    # Load service control registry (no-op if config/services.yaml missing)
    service_manager.load()

    yield

    idle_reaper_task.cancel()
    await terminal_service.shutdown_all()

    await worker_service.shutdown()
    await memory_facade.shutdown()

    scheduler_service.shutdown()

    if settings.N8N_ENABLED:
        from app.services.n8n_service import n8n_service
        from app.services.n8n_workflow_service import n8n_workflow_service
        await n8n_service.shutdown()
        await n8n_workflow_service.shutdown()

    await ai_channel_mod.close()


app = FastAPI(
    title="Shore Assistant API",
    description="Backend for Shore Assistant - Voice AI with LLM, TTS, and Vision",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS: when auth is on, we MUST pin origins to a specific list because
# cookies + wildcard CORS is rejected by browsers. When auth is off, keep
# the open-everything default for dev convenience.
if settings.AUTH_ENABLED:
    _allowed_origins = [
        o.strip() for o in settings.AUTH_FRONTEND_ORIGINS.split(",") if o.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*", "X-CSRF-Token"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(memory_router)
app.include_router(dashboard_router)
app.include_router(services_router)
app.include_router(chronicles_router)
app.include_router(chat_ws_router)

if settings.N8N_ENABLED:
    from app.api.endpoints.n8n_webhook import router as n8n_router
    app.include_router(n8n_router)
