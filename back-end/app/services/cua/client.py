"""HTTP client for the EvoCUA llama-server."""

import httpx

from app.core.config import settings


class CuaUnavailable(Exception):
    """Raised when the EvoCUA endpoint cannot provide a usable response."""


class CuaClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = (
                {"Authorization": f"Bearer {settings.EVOCUA_API_KEY}"}
                if settings.EVOCUA_API_KEY
                else None
            )
            self._client = httpx.AsyncClient(
                base_url=settings.EVOCUA_BASE_URL,
                timeout=settings.EVOCUA_TIMEOUT,
                transport=self._transport,
                headers=headers,
            )
        return self._client

    async def next_step(self, messages: list[dict]) -> str:
        try:
            response = await self._get_client().post(
                "/v1/chat/completions",
                json={
                    "model": "evocua-8b",
                    "messages": messages,
                    "temperature": 0.0,
                },
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"] or ""
        except httpx.HTTPError as exc:
            raise CuaUnavailable(f"EvoCUA server error: {exc!r}") from exc
        except (KeyError, IndexError, ValueError) as exc:
            raise CuaUnavailable(
                f"EvoCUA returned an unexpected payload: {exc!r}"
            ) from exc


cua_client = CuaClient()
