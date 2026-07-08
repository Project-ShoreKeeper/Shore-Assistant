import json

import httpx
import pytest

from app.services.cua.client import CuaClient, CuaUnavailable


def _transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_next_step_returns_text():
    def handler(request):
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                "## Action:\nok\n```python\n"
                                "pyautogui.click(x=1, y=1)\n```"
                            )
                        }
                    }
                ]
            },
        )

    client = CuaClient(transport=_transport(handler))
    text = await client.next_step(
        [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
    )
    assert "pyautogui.click" in text


@pytest.mark.asyncio
async def test_connect_error_raises_unavailable():
    def handler(request):
        raise httpx.ConnectError("refused")

    client = CuaClient(transport=_transport(handler))
    with pytest.raises(CuaUnavailable):
        await client.next_step([{"role": "user", "content": []}])


@pytest.mark.asyncio
async def test_http_error_raises_unavailable():
    def handler(request):
        return httpx.Response(500, text="boom")

    client = CuaClient(transport=_transport(handler))
    with pytest.raises(CuaUnavailable):
        await client.next_step([{"role": "user", "content": []}])


@pytest.mark.asyncio
async def test_api_key_sent_as_bearer(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "EVOCUA_API_KEY", "secret-key")
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}}]}
        )

    client = CuaClient(transport=_transport(handler))
    await client.next_step([{"role": "user", "content": []}])
    assert seen["auth"] == "Bearer secret-key"


@pytest.mark.asyncio
async def test_no_api_key_sends_no_auth_header(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "EVOCUA_API_KEY", "")
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}}]}
        )

    client = CuaClient(transport=_transport(handler))
    await client.next_step([{"role": "user", "content": []}])
    assert seen["auth"] is None


@pytest.mark.asyncio
async def test_model_and_extra_params_forwarded():
    seen = {}

    def handler(request):
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}}]}
        )

    client = CuaClient(transport=_transport(handler))
    await client.next_step(
        [{"role": "user", "content": []}],
        model="ui-tars-1.5-7b",
        extra_params={"frequency_penalty": 1.0},
    )
    assert seen["payload"]["model"] == "ui-tars-1.5-7b"
    assert seen["payload"]["frequency_penalty"] == 1.0


@pytest.mark.asyncio
async def test_default_model_is_evocua():
    seen = {}

    def handler(request):
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}}]}
        )

    client = CuaClient(transport=_transport(handler))
    await client.next_step([{"role": "user", "content": []}])
    assert seen["payload"]["model"] == "evocua-8b"
