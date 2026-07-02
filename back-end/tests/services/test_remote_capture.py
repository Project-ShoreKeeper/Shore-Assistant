"""Unit tests for RemoteCaptureService's request/resolve Future round trip."""
import asyncio

import pytest

from app.core.config import settings
from app.services.remote_capture import RemoteCaptureService


def _svc_with_recorder():
    svc = RemoteCaptureService()
    sent: list[dict] = []

    async def send_json(msg: dict):
        sent.append(msg)

    svc.send_json = send_json
    return svc, sent


@pytest.mark.asyncio
async def test_request_returns_none_when_no_connection():
    svc = RemoteCaptureService()
    assert await svc.request("thumbnail") is None


@pytest.mark.asyncio
async def test_request_sends_expected_message_shape():
    svc, sent = _svc_with_recorder()

    async def resolve_soon():
        await asyncio.sleep(0)
        request_id = sent[0]["request_id"]
        svc.resolve(request_id, "data:image/jpeg;base64,QUJD", "Entire screen")

    asyncio.create_task(resolve_soon())
    result = await svc.request("full")

    assert sent[0]["type"] == "screen_capture_request"
    assert sent[0]["kind"] == "full"
    assert sent[0]["max_size"] == settings.COPILOT_MAX_IMAGE_SIZE
    assert result == {"data_url": "data:image/jpeg;base64,QUJD", "label": "Entire screen"}


@pytest.mark.asyncio
async def test_thumbnail_kind_uses_fixed_max_size():
    svc, sent = _svc_with_recorder()

    async def resolve_soon():
        await asyncio.sleep(0)
        svc.resolve(sent[0]["request_id"], "data:image/jpeg;base64,QUJD")

    asyncio.create_task(resolve_soon())
    await svc.request("thumbnail")

    assert sent[0]["max_size"] == 64


@pytest.mark.asyncio
async def test_resolve_updates_last_label():
    svc, sent = _svc_with_recorder()

    async def resolve_soon():
        await asyncio.sleep(0)
        svc.resolve(sent[0]["request_id"], "data:image/jpeg;base64,QUJD", "My Window")

    asyncio.create_task(resolve_soon())
    await svc.request("full")

    assert svc.last_label == "My Window"


@pytest.mark.asyncio
async def test_denial_resolves_to_none():
    svc, sent = _svc_with_recorder()

    async def resolve_soon():
        await asyncio.sleep(0)
        svc.resolve(sent[0]["request_id"], None)

    asyncio.create_task(resolve_soon())
    result = await svc.request("full")

    assert result is None


@pytest.mark.asyncio
async def test_timeout_resolves_to_none(monkeypatch):
    monkeypatch.setattr(settings, "SCREEN_CAPTURE_THUMBNAIL_TIMEOUT_SECONDS", 0.01)
    svc, _sent = _svc_with_recorder()
    # Nobody ever calls svc.resolve() -> must time out, not hang.
    result = await svc.request("thumbnail")
    assert result is None


@pytest.mark.asyncio
async def test_resolve_on_unknown_request_id_returns_false():
    svc, _sent = _svc_with_recorder()
    assert svc.resolve("does-not-exist", "data:image/jpeg;base64,QUJD") is False


@pytest.mark.asyncio
async def test_resolve_twice_second_call_returns_false():
    svc, sent = _svc_with_recorder()

    async def resolve_soon():
        await asyncio.sleep(0)
        request_id = sent[0]["request_id"]
        assert svc.resolve(request_id, "data:image/jpeg;base64,QUJD") is True
        assert svc.resolve(request_id, "data:image/jpeg;base64,QUJD") is False

    asyncio.create_task(resolve_soon())
    await svc.request("full")
