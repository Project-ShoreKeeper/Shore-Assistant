"""Image-attachment validation and memory/live-message split for /ws/chat."""
import base64
import os

os.environ.setdefault("STT_ENABLED", "False")

import pytest
pytest.importorskip("anthropic", reason="cloud_llm_service requires anthropic")

from app.api.websockets.chat_ws import (
    _validate_images,
    _build_memory_message,
    _build_live_message,
)
from app.core.config import settings


def _tiny_jpeg_data_url() -> str:
    # 1x1 white JPEG — valid header so MIME sniff is unnecessary.
    raw = bytes.fromhex(
        "FFD8FFE000104A46494600010101006000600000FFDB0043000806060706050806070707"
        "090908070A0C140D0C0B0B0C1912130F141D1A1F1E1D1A1C1C20242E2720222C231C1C28"
        "37292C30313434341F27393D38323C2E333432FFC00011080001000103012200021101031"
        "10100FFC4001F0000010501010101010100000000000000000102030405060708090A0BFF"
        "C400B5100002010303020403050504040000017D01020300041105122131410613516107"
        "227114328191A1082342B1C11552D1F02433627282090A161718191A25262728292A3435"
        "363738393A434445464748494A535455565758595A636465666768696A737475767778797"
        "A838485868788898A92939495969798999AA2A3A4A5A6A7A8A9AAB2B3B4B5B6B7B8B9BAC2"
        "C3C4C5C6C7C8C9CACAD2D3D4D5D6D7D8D9DAE1E2E3E4E5E6E7E8E9EAF1F2F3F4F5F6F7F8F"
        "9FAFFDA0008010100003F00FBD0"
    )
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode()


def test_validate_images_accepts_valid_payload():
    images = [{"data_url": _tiny_jpeg_data_url(), "width": 1, "height": 1}]
    err = _validate_images(images)
    assert err is None


def test_validate_images_rejects_too_many():
    img = {"data_url": _tiny_jpeg_data_url(), "width": 1, "height": 1}
    images = [img] * (settings.MAX_IMAGES_PER_MESSAGE + 1)
    err = _validate_images(images)
    assert err is not None and "max" in err.lower()


def test_validate_images_rejects_unsupported_mime():
    images = [{"data_url": "data:image/bmp;base64,AAAA", "width": 1, "height": 1}]
    err = _validate_images(images)
    assert err is not None and "format" in err.lower()


def test_validate_images_rejects_oversize(monkeypatch):
    monkeypatch.setattr(settings, "MAX_IMAGE_BYTES", 10)
    images = [{"data_url": _tiny_jpeg_data_url(), "width": 1, "height": 1}]
    err = _validate_images(images)
    assert err is not None and "large" in err.lower()


def test_validate_images_rejects_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "MULTIMODAL_ENABLED", False)
    images = [{"data_url": _tiny_jpeg_data_url(), "width": 1, "height": 1}]
    err = _validate_images(images)
    assert err is not None and "vision" in err.lower()


def test_build_memory_message_appends_placeholder():
    images = [{"data_url": "data:image/jpeg;base64,X", "width": 1024, "height": 768},
              {"data_url": "data:image/jpeg;base64,Y", "width": 640, "height": 480}]
    msg = _build_memory_message("what is this?", images)
    assert msg["role"] == "user"
    assert "what is this?" in msg["content"]
    assert "[Attached 2 image(s):" in msg["content"]
    assert "1024x768" in msg["content"]
    assert "640x480" in msg["content"]


def test_build_memory_message_handles_empty_text():
    images = [{"data_url": "data:image/jpeg;base64,X", "width": 10, "height": 10}]
    msg = _build_memory_message("", images)
    assert msg["content"].startswith("[Attached 1 image(s):")


def test_build_live_message_returns_openai_content_array():
    images = [{"data_url": "data:image/jpeg;base64,Z", "width": 1, "height": 1}]
    msg = _build_live_message("hi", images)
    assert msg["role"] == "user"
    assert isinstance(msg["content"], list)
    assert msg["content"][0] == {"type": "text", "text": "hi"}
    assert msg["content"][1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/jpeg;base64,Z"},
    }


def test_build_live_message_substitutes_space_for_empty_text():
    """llama-server tool-calling chokes on an empty text part; emit a single space."""
    images = [{"data_url": "data:image/jpeg;base64,Z", "width": 1, "height": 1}]
    msg = _build_live_message("", images)
    assert msg["content"][0]["text"] == " "
