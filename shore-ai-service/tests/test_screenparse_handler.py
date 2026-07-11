import pytest

from shore_ai.handlers.screenparse import ScreenParseHandler
from shore_ai._pb import screenparse_pb2


def _fake_parser(calls):
    """Return a parser fn that records calls and returns fixed elements."""
    def parse(image_bytes):
        calls.append(image_bytes)
        elements = [
            {"type": "text", "content": "File",
             "interactable": True, "bbox": [0.0, 0.0, 0.1, 0.05]},
            {"type": "icon", "content": "settings gear",
             "interactable": True, "bbox": [0.9, 0.0, 0.95, 0.05]},
        ]
        return elements, b"FAKE_JPEG_BYTES"
    return parse


@pytest.mark.asyncio
async def test_parse_maps_elements_to_proto():
    calls = []
    handler = ScreenParseHandler(parser=_fake_parser(calls), device="cpu")
    req = screenparse_pb2.ParseRequest(image=b"PNGDATA")
    resp = await handler.Parse(req, context=None)

    assert calls == [b"PNGDATA"]
    assert len(resp.elements) == 2
    e0 = resp.elements[0]
    assert e0.id == 0
    assert e0.type == "text"
    assert e0.content == "File"
    assert e0.interactable is True
    assert (e0.x1, e0.y1, e0.x2, e0.y2) == pytest.approx((0.0, 0.0, 0.1, 0.05))
    assert resp.elements[1].id == 1
    assert resp.som_image_jpeg == b"FAKE_JPEG_BYTES"
    assert resp.latency_ms >= 0.0


@pytest.mark.asyncio
async def test_loaded_reflects_parser_presence():
    handler = ScreenParseHandler(parser=_fake_parser([]), device="cpu")
    assert handler.loaded() is True
    unloaded = ScreenParseHandler(parser=None, device="cpu")
    assert unloaded.loaded() is False


@pytest.mark.asyncio
async def test_parse_aborts_when_not_loaded():
    handler = ScreenParseHandler(parser=None, device="cpu")
    req = screenparse_pb2.ParseRequest(image=b"PNGDATA")

    class _Ctx:
        def __init__(self):
            self.code = None
            self.details = None

        async def abort(self, code, details):
            self.code = code
            self.details = details
            raise RuntimeError("aborted")

    ctx = _Ctx()
    with pytest.raises(RuntimeError):
        await handler.Parse(req, context=ctx)
    assert ctx.code is not None
