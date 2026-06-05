from fastapi import APIRouter
from app.core.config import settings
from app.services.memory import memory_facade
from app.services.file_tool_client import file_tool_client

router = APIRouter()


@router.get("/")
def read_root():
    return {"message": "Welcome to Shore STT FastAPI Backend"}


@router.get("/health")
async def health_check():
    redis_ok = (
        await memory_facade.short_term.health()
        if memory_facade.short_term is not None
        else False
    )
    pg_ok = await memory_facade.profile.health()
    qd_ok = await memory_facade.episodic.health()
    hom_ok = await memory_facade.hom.health()
    file_tool_ok = await file_tool_client.health()

    if redis_ok and pg_ok and qd_ok:
        status = "healthy"
    elif redis_ok:
        status = "degraded"
    else:
        status = "unhealthy"

    return {
        "status": status,
        "memory": {
            "redis": "ok" if redis_ok else "down",
            "postgres": "ok" if pg_ok else "down",
            "qdrant": "ok" if qd_ok else "down",
            "hom": ("ok" if hom_ok else "down") if memory_facade.hom.enabled else "off",
        },
        "file_tool": "ok" if file_tool_ok else "down",
    }


@router.get("/config")
def get_config():
    return {
        "llm_model": settings.LLAMA_MODEL,
    }


@router.post("/clear-memory")
async def clear_memory():
    cleared = await memory_facade.clear()
    return {"cleared": cleared}
