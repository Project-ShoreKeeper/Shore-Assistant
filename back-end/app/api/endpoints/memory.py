"""Memory admin endpoints — read/write Profile, Episodic, and Audit log.

Originally introduced as `memory_debug.py` (gated by DEBUG_MEMORY) in Phase 2.
Promoted in Phase 4 to back the frontend memory panel; always mounted.
"""
import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import csrf_check, require_admin
from app.services.memory import memory_facade
from app.services.memory.types import EmotionVector, EpisodicFact, ProfileChange

# Every /api/memory/* route requires admin. Writes additionally require CSRF.
router = APIRouter(
    prefix="/api/memory",
    tags=["memory"],
    dependencies=[Depends(require_admin)],
)


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
    reason: str = "manual edit"


@router.post("/profile/change", dependencies=[Depends(csrf_check)])
async def profile_change(req: ProfileChangeRequest) -> dict:
    change = ProfileChange(**req.model_dump())
    try:
        await memory_facade.profile.apply_change(change)
    except Exception as e:
        print(f"[memory] profile_change failed: {e!r}")
        raise HTTPException(status_code=502, detail=type(e).__name__)
    return {"ok": True, "key_path": req.key_path}


@router.get("/profile")
async def profile_read() -> dict:
    try:
        data = await memory_facade.profile.read()
    except Exception as e:
        print(f"[memory] profile_read failed: {e!r}")
        raise HTTPException(status_code=502, detail=type(e).__name__)
    size = len(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    return {"data": data, "size_bytes": size}


@router.get("/profile/history")
async def profile_history(key: str, limit: int = 20) -> dict:
    try:
        rows = await memory_facade.profile.history(key, limit)
    except Exception as e:
        print(f"[memory] profile_history failed: {e!r}")
        raise HTTPException(status_code=502, detail=type(e).__name__)
    return {"key_path": key, "rows": rows}


@router.get("/profile/audit")
async def profile_audit(limit: int = 50) -> dict:
    """Global audit log across all keys, newest first."""
    try:
        rows = await memory_facade.profile.audit_recent(limit)
    except Exception as e:
        print(f"[memory] profile_audit failed: {e!r}")
        raise HTTPException(status_code=502, detail=type(e).__name__)
    return {"rows": rows}


class ProfileRestoreRequest(BaseModel):
    audit_id: int
    reason: Optional[str] = None


@router.post("/profile/restore", dependencies=[Depends(csrf_check)])
async def profile_restore(req: ProfileRestoreRequest) -> dict:
    try:
        new_row = await memory_facade.profile.restore(req.audit_id, req.reason)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        print(f"[memory] profile_restore failed: {e!r}")
        raise HTTPException(status_code=502, detail=type(e).__name__)
    return {"ok": True, "new_row": new_row}


# ── Episodic ───────────────────────────────────────────────────────────

class EpisodicUpsertRequest(BaseModel):
    fact: str
    entity_tags: list[str] = []
    emotion: Optional[EmotionVector] = None
    source_turn_ts: float = 0.0
    source_role: str = "user"
    confidence: float = Field(1.0, ge=0.0, le=1.0)


@router.post("/episodic/upsert", dependencies=[Depends(csrf_check)])
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
        print(f"[memory] episodic_upsert failed: {e!r}")
        raise HTTPException(status_code=502, detail=type(e).__name__)
    return {"ok": True, "point_id": point_id}


def _scored_to_dict(sf) -> dict:
    return {
        "point_id": sf.point_id,
        "score": sf.score,
        "created_at": sf.created_at,
        "fact": sf.fact.fact,
        "entity_tags": sf.fact.entity_tags,
        "emotion": sf.fact.emotion.model_dump(),
        "valence": sf.fact.emotion.valence,
        "source_turn_ts": sf.fact.source_turn_ts,
        "source_role": sf.fact.source_role,
        "confidence": sf.fact.confidence,
    }


@router.get("/episodic/recent")
async def episodic_recent(limit: int = 50) -> dict:
    try:
        results = await memory_facade.episodic.list_recent(limit=limit)
    except Exception as e:
        print(f"[memory] episodic_recent failed: {e!r}")
        raise HTTPException(status_code=502, detail=type(e).__name__)
    return {"rows": [_scored_to_dict(r) for r in results]}


@router.get("/episodic/search")
async def episodic_search(q: str, top_k: int = 20) -> dict:
    try:
        results = await memory_facade.episodic.search(q, top_k=top_k)
    except Exception as e:
        print(f"[memory] episodic_search failed: {e!r}")
        raise HTTPException(status_code=502, detail=type(e).__name__)
    return {"query": q, "hits": [_scored_to_dict(r) for r in results]}


@router.delete("/episodic/{point_id}", dependencies=[Depends(csrf_check)])
async def episodic_delete(point_id: str) -> dict:
    try:
        ok = await memory_facade.episodic.delete(point_id)
    except Exception as e:
        print(f"[memory] episodic_delete failed: {e!r}")
        raise HTTPException(status_code=502, detail=type(e).__name__)
    if not ok:
        raise HTTPException(status_code=404, detail="point not found")
    return {"ok": True, "point_id": point_id}
