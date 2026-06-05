"""House of Memories adapter — slots HoM in as an episodic/graph layer.

Solves the two integration mismatches HoM has with an always-on voice assistant:

  * Session boundary (HoM weakness #2): HoM consolidates on *session end*, but a
    voice assistant never explicitly "ends". This layer derives sessions from
    activity: the first turn lazily opens a session, and a new turn after an idle
    gap (HOM_SESSION_IDLE_MINUTES) closes the old one — triggering consolidation —
    and opens a fresh one. end_session() is also called on WebSocket disconnect.

  * Identity (HoM weakness #3) is solved at the facade level, NOT here: Shore's
    Postgres Profile keeps running, so structured identity is still pinned into
    every prompt. HoM only contributes recall.
"""

import asyncio
import time
from typing import Optional

from app.core.config import settings
from app.services.hom_client import hom_client
from app.services.memory.types import GraphFact


class HoMMemory:
    def __init__(self) -> None:
        self._session_id: Optional[str] = None
        self._last_activity: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return settings.HOM_ENABLED

    async def startup(self) -> None:
        # Nothing to warm up; session is created lazily on first turn.
        pass

    async def shutdown(self) -> None:
        await self.end_session()
        await hom_client.close()

    async def health(self) -> bool:
        return await hom_client.health()

    # ── session management ───────────────────────────────────────────

    def _idle_expired(self) -> bool:
        gap = settings.HOM_SESSION_IDLE_MINUTES * 60
        return self._last_activity > 0 and (time.time() - self._last_activity) > gap

    async def _ensure_session(self) -> Optional[str]:
        """Return a live session id, rotating it when the idle gap is exceeded."""
        # Idle rollover: close the stale session (fires consolidation) then reopen.
        if self._session_id and self._idle_expired():
            old = self._session_id
            self._session_id = None
            jobs = await hom_client.end_session(old)
            print(f"[HoM] idle rollover: closed session {old[:8]} ({jobs} jobs enqueued)")

        if self._session_id is None:
            self._session_id = await hom_client.create_session()
            if self._session_id:
                print(f"[HoM] opened session {self._session_id[:8]}")
        return self._session_id

    async def record_turn(self, role: str, content: str) -> None:
        """Append a turn to the current HoM session. Cheap (no embedding)."""
        if not self.enabled or not content:
            return
        async with self._lock:
            sid = await self._ensure_session()
            if not sid:
                return
            await hom_client.add_turn(sid, role, content)
            self._last_activity = time.time()

    async def end_session(self) -> int:
        """Close the active session, enqueuing consolidation. No-op if none open."""
        if not self.enabled:
            return 0
        async with self._lock:
            if not self._session_id:
                return 0
            sid, self._session_id = self._session_id, None
        jobs = await hom_client.end_session(sid)
        print(f"[HoM] closed session {sid[:8]} ({jobs} jobs enqueued)")
        return jobs

    # ── recall ───────────────────────────────────────────────────────

    async def recall(self, query: str) -> list[GraphFact]:
        if not self.enabled or not query:
            return []
        rows = await hom_client.recall(query, session_id=self._session_id)
        hits: list[GraphFact] = []
        for r in rows[: settings.HOM_RECALL_TOP_K]:
            content = r.get("content_summary") or r.get("content_raw") or ""
            if not content:
                continue
            hits.append(GraphFact(
                mem_id=r.get("mem_id", ""),
                content=content,
                source=r.get("source", "event"),
                confidence=float(r.get("confidence", 1.0) or 1.0),
                importance=float(r.get("importance_score", 0.0) or 0.0),
            ))
        return hits
