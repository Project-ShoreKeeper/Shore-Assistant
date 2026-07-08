"""HTTP client for the computer-use model llama-server."""

import httpx

from app.core.config import settings


class CuaUnavailable(Exception):
    """Raised when the CUA endpoint cannot provide a usable response."""


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

    async def next_step(
        self,
        messages: list[dict],
        *,
        model: str = "evocua-8b",
        extra_params: dict | None = None,
    ) -> str:
        payload: dict = {
            "model": model,
            "messages": messages,
            "temperature": 0.0,
        }
        if extra_params:
            payload.update(extra_params)
        try:
            response = await self._get_client().post(
                "/v1/chat/completions",
                json=payload,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"] or ""
        except httpx.HTTPError as exc:
            raise CuaUnavailable(f"CUA model server error: {exc!r}") from exc
        except (KeyError, IndexError, ValueError) as exc:
            raise CuaUnavailable(
                f"CUA model server returned an unexpected payload: {exc!r}"
            ) from exc


cua_client = CuaClient()
