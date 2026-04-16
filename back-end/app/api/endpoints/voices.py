from typing import List

from fastapi import APIRouter, File, UploadFile, Form, HTTPException
from pydantic import BaseModel

from app.services.fish_tts_service import fish_tts_service

router = APIRouter(prefix="/api/voices", tags=["voices"])

class VoiceInfo(BaseModel):
    name: str
    has_transcript: bool
    format: str

@router.get("/", response_model=List[VoiceInfo])
async def list_voices():
    """List all available reference voices from the Fish Server."""
    ids = await fish_tts_service.list_references()
    
    # Map to our response format
    # Since Fish Server logic is opaque here, we assume if it's listed, it has a transcript
    return [
        VoiceInfo(
            name=vid,
            has_transcript=True, 
            format="wav" # Default format on server disk
        ) for vid in ids
    ]

@router.post("/")
async def upload_voice(
    name: str = Form(...),
    transcript: str = Form(...),
    audio: UploadFile = File(...)
):
    """Upload a new reference voice to the Fish Server (proxied)."""
    try:
        audio_bytes = await audio.read()
        success = await fish_tts_service.add_reference(name, audio_bytes, transcript)
        
        if success:
            return {"status": "success", "message": f"Voice '{name}' uploaded to Fish Server"}
        else:
            raise HTTPException(status_code=500, detail="Fish Server failed to add reference")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/{name}")
async def delete_voice(name: str):
    """Delete a reference voice from the Fish Server (proxied)."""
    success = await fish_tts_service.delete_reference(name)
    if not success:
        raise HTTPException(status_code=404, detail=f"Voice '{name}' not found on Fish Server")
    
    return {"status": "success", "message": f"Voice '{name}' deleted from Fish Server"}
