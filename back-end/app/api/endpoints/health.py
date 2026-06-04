from fastapi import APIRouter
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
    return {
        "status": "ok",
        "memory": {"redis": redis_ok},
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
