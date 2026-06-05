"""HTTP client for the House of Memories (HoM) Go server.

Thin async wrapper over the HoM REST API. Never raises: every method returns
either parsed JSON or None, so memory layers can degrade gracefully when HoM
is down. Gated behind HOM_ENABLED.
"""

import logging
from typing import Any, Optional

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)


class HoMClient:
    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=settings.HOM_BASE_URL,
                timeout=httpx.Timeout(settings.HOM_RECALL_TIMEOUT, connect=1.0),
            )
        return self._client

    # ── lifecycle ────────────────────────────────────────────────────

    async def create_session(self) -> Optional[str]:
        """POST /session → session_id, or None on failure."""
        data = await self._post("/session")
        return data.get("session_id") if data else None

    async def add_turn(self, session_id: str, role: str, content: str) -> bool:
        """POST /session/{id}/turn. Cheap (no embedding); awaited on the write path."""
        data = await self._post(
            f"/session/{session_id}/turn", {"role": role, "content": content}
        )
        return bool(data and data.get("ok"))

    async def end_session(self, session_id: str) -> int:
        """POST /session/{id}/end → number of consolidation jobs enqueued."""
        data = await self._post(f"/session/{session_id}/end")
        return int(data.get("jobs_enqueued", 0)) if data else 0

    # ── read ─────────────────────────────────────────────────────────

    async def recall(self, query: str, session_id: Optional[str] = None) -> list[dict]:
        """GET /recall?q=... → ranked memories. Embeds the query via Gemini server-side."""
        params: dict[str, str] = {"q": query}
        if session_id:
            params["session_id"] = session_id
        data = await self._get("/recall", params=params)
        return data if isinstance(data, list) else []

    async def health(self) -> bool:
        """HoM has no /health endpoint; probe cheaply by hitting the root.

        Any HTTP response (even 404) means the server is up and reachable.
        """
        if not settings.HOM_ENABLED:
            return False
        try:
            resp = await self._get_client().get("/")
            return resp.status_code < 500
        except Exception:
            return False

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ── internals ────────────────────────────────────────────────────

    async def _post(self, path: str, body: Optional[dict] = None) -> Optional[dict]:
        if not settings.HOM_ENABLED:
            return None
        try:
            resp = await self._get_client().post(path, json=body or {})
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            log.warning("HoM POST %s failed: %s", path, e)
            return None

    async def _get(self, path: str, params: Optional[dict] = None) -> Any:
        if not settings.HOM_ENABLED:
            return None
        try:
            resp = await self._get_client().get(path, params=params)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            log.warning("HoM GET %s failed: %s", path, e)
            return None


hom_client = HoMClient()
