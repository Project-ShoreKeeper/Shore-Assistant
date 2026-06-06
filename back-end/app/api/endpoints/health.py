from fastapi import APIRouter, Depends
from app.api.deps import csrf_check, require_admin
from app.core.auth import User
from app.core.config import settings
from app.services.memory import memory_facade

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
        },
    }


@router.get("/config")
def get_config():
    return {
        "llm_model": settings.LLAMA_MODEL,
    }


@router.post(
    "/clear-memory",
    dependencies=[Depends(csrf_check)],
)
async def clear_memory(user: User = Depends(require_admin)):
    cleared = await memory_facade.clear(user_id=user.id)
    return {"cleared": cleared}
