"""Debug endpoints for manual memory seeding (Phase 2).
Included in app router only when DEBUG_MEMORY=True.
"""
import json
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.memory import memory_facade
from app.services.memory.types import EmotionVector, EpisodicFact, ProfileChange

router = APIRouter(prefix="/api/memory", tags=["memory-debug"])


# ── Profile ────────────────────────────────────────────────────────────

class ProfileChangeRequest(BaseModel):
    """Body for POST /api/memory/profile/change.

    NOTE — destructive default: setting `new_value` to null OR omitting it
    entirely deletes `key_path` from the profile. To set a key to nothing
    semantically, prefer an explicit value like an empty string.
    """
    key_path: str
    new_value: Any | None = None
    source_turn_ts: float = 0.0
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    reason: str = "manual debug seed"


@router.post("/profile/change")
async def profile_change(req: ProfileChangeRequest) -> dict:
    change = ProfileChange(**req.model_dump())
    try:
        await memory_facade.profile.apply_change(change)
    except Exception as e:
        print(f"[memory-debug] profile_change failed: {e!r}")
        raise HTTPException(status_code=502, detail=type(e).__name__)
    return {"ok": True, "key_path": req.key_path}


@router.get("/profile")
async def profile_read() -> dict:
    try:
        data = await memory_facade.profile.read()
    except Exception as e:
        print(f"[memory-debug] profile_read failed: {e!r}")
        raise HTTPException(status_code=502, detail=type(e).__name__)
    size = len(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    return {"data": data, "size_bytes": size}


@router.get("/profile/history")
async def profile_history(key: str, limit: int = 20) -> dict:
    try:
        rows = await memory_facade.profile.history(key, limit)
    except Exception as e:
        print(f"[memory-debug] profile_history failed: {e!r}")
        raise HTTPException(status_code=502, detail=type(e).__name__)
    return {"key_path": key, "rows": rows}


# ── Episodic ───────────────────────────────────────────────────────────

class EpisodicUpsertRequest(BaseModel):
    fact: str
    entity_tags: list[str] = []
    emotion: Optional[EmotionVector] = None
    source_turn_ts: float = 0.0
    source_role: str = "user"
    confidence: float = Field(1.0, ge=0.0, le=1.0)


@router.post("/episodic/upsert")
async def episodic_upsert(req: EpisodicUpsertRequest) -> dict:
    fact = EpisodicFact(
        fact=req.fact,
        entity_tags=req.entity_tags,
        emotion=req.emotion or EmotionVector(),
        source_turn_ts=req.source_turn_ts,
        source_role=req.source_role,
        confidence=req.confidence,
    )
    try:
        point_id = await memory_facade.episodic.upsert(fact)
    except Exception as e:
        print(f"[memory-debug] episodic_upsert failed: {e!r}")
        raise HTTPException(status_code=502, detail=type(e).__name__)
    return {"ok": True, "point_id": point_id}


@router.get("/episodic/search")
async def episodic_search(q: str, top_k: int = 5) -> dict:
    try:
        results = await memory_facade.episodic.search(q, top_k=top_k)
    except Exception as e:
        print(f"[memory-debug] episodic_search failed: {e!r}")
        raise HTTPException(status_code=502, detail=type(e).__name__)
    return {
        "query": q,
        "hits": [
            {
                "score": r.score,
                "fact": r.fact.fact,
                "entity_tags": r.fact.entity_tags,
                "confidence": r.fact.confidence,
            }
            for r in results
        ],
    }
