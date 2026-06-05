"""HTTP client for the file_tool System Core (Rust binary)."""

import logging
from typing import Any

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)


class FileToolClient:
    """Thin async HTTP wrapper around the file_tool --serve API.

    Lazy-initialises a single httpx.AsyncClient on first use.
    Call close() during app shutdown to release the connection pool.
    """

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers: dict[str, str] = {}
            if settings.FILE_TOOL_TOKEN:
                headers["Authorization"] = f"Bearer {settings.FILE_TOOL_TOKEN}"
            self._client = httpx.AsyncClient(
                base_url=settings.FILE_TOOL_URL,
                headers=headers,
                timeout=30.0,
            )
        return self._client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def post(self, endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
        """POST to a file_tool endpoint and return the parsed JSON response.

        Returns the raw ToolEnvelope dict on success.
        Returns {"status": "error", "message": "..."} on HTTP or network failure
        so callers never have to catch exceptions.
        """
        if not settings.FILE_TOOL_ENABLED:
            return {
                "status": "error",
                "message": "file_tool is disabled (FILE_TOOL_ENABLED=False)",
            }

        try:
            resp = await self._get_client().post(endpoint, json=body)
            resp.raise_for_status()
            return resp.json()
        except httpx.ConnectError:
            log.warning("file_tool unreachable at %s", settings.FILE_TOOL_URL)
            return {
                "status": "error",
                "message": f"file_tool service is not running at {settings.FILE_TOOL_URL}",
            }
        except httpx.HTTPStatusError as exc:
            log.warning("file_tool %s returned HTTP %d", endpoint, exc.response.status_code)
            try:
                return exc.response.json()
            except Exception:
                return {
                    "status": "error",
                    "message": f"HTTP {exc.response.status_code} from file_tool",
                }
        except Exception as exc:
            log.exception("file_tool request failed")
            return {"status": "error", "message": str(exc)}

    async def health(self) -> bool:
        """Check if the file_tool server is reachable. Uses the public /health endpoint (no auth)."""
        if not settings.FILE_TOOL_ENABLED:
            return False
        try:
            resp = await self._get_client().get("/health", headers={})
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


file_tool_client = FileToolClient()
