"""GET /api/images/{id} — serves a previously-saved chat image attachment.

Raw bytes only, gated behind login. Separate from `/api/memory/*` on
purpose: this store is never read by the agent or the LOCOMO worker.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.api.deps import current_user
from app.core.auth import User
from app.services.image_store import image_store

router = APIRouter()


@router.get("/api/images/{image_id}")
async def get_image(image_id: str, user: User = Depends(current_user)):
    record = await image_store.get(image_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(record["path"], media_type=record["mime_type"])
