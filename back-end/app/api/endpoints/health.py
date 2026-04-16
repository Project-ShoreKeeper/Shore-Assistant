from fastapi import APIRouter
from app.core.config import settings

router = APIRouter()


@router.get("/")
def read_root():
    return {"message": "Welcome to Shore STT FastAPI Backend"}


@router.get("/health")
def health_check():
    return {"status": "ok", "service": "STT Backend is running"}


@router.get("/config")
def get_config():
    return {
        "llm_model": settings.OLLAMA_MODEL,
    }


@router.delete("/memory")
def clear_memory():
    from app.services.memory_service import memory_service
    cleared = memory_service.clear("default")
    return {"cleared": cleared}
