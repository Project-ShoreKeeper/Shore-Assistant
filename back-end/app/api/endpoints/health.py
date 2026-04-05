from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def read_root():
    return {"message": "Welcome to Shore STT FastAPI Backend"}


@router.get("/health")
def health_check():
    return {"status": "ok", "service": "STT Backend is running"}
