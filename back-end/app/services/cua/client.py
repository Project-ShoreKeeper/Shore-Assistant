"""HTTP client for the EvoCUA llama-server."""

import httpx

from app.core.config import settings


class CuaUnavailable(Exception):
    """Raised when the EvoCUA endpoint cannot provide a usable response."""


class CuaClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport

    async def next_step(self, messages: list[dict]) -> str:
        try:
            async with httpx.AsyncClient(
                base_url=settings.EVOCUA_BASE_URL,
                timeout=settings.EVOCUA_TIMEOUT,
                transport=self._transport,
            ) as client:
                response = await client.post(
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
