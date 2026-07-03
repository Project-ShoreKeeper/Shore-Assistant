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
