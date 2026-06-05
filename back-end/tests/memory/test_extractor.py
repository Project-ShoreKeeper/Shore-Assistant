"""Unit tests for LocomoExtractor — httpx client mocked."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import httpx

from app.services.memory.extractor import LocomoExtractor, ExtractorDisabled
from app.services.memory.types import Message, WorkerOutput


def _turns():
    return [
        Message(role="user", content="I switched to oat milk lattes.",
                timestamp=100.0),
        Message(role="assistant", content="Noted — oat milk it is.",
                timestamp=101.0),
    ]


def _fake_response(json_str: str):
    response = SimpleNamespace(
        json=lambda: {"choices": [{"message": {"content": json_str}}]},
        raise_for_status=lambda: None
    )
    return response


@pytest.fixture(autouse=True)
def _enable(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.WORKER_ENABLED", True)


async def test_extract_returns_worker_output_on_happy_path():
    payload = {
        "profile_changes": [{
            "key_path": "preferences.coffee", "new_value": "oat milk latte",
            "source_turn_ts": 100.0, "confidence": 0.95,
            "reason": "User explicitly switched.",
        }],
        "episodic_facts": [],
    }
    ex = LocomoExtractor()
    fake_client = AsyncMock()
    fake_client.post.return_value = _fake_response(json.dumps(payload))
    ex._http_client = fake_client
    
    out = await ex.extract(turns=_turns(), profile_snapshot={})
    assert isinstance(out, WorkerOutput)
    assert len(out.profile_changes) == 1
    assert out.profile_changes[0].key_path == "preferences.coffee"


async def test_extract_raises_when_worker_disabled(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.WORKER_ENABLED", False)
    ex = LocomoExtractor()
    with pytest.raises(ExtractorDisabled):
        await ex.extract(turns=_turns(), profile_snapshot={})


async def test_extract_retries_once_on_transient_error(monkeypatch):
    payload = {"profile_changes": [], "episodic_facts": []}
    ex = LocomoExtractor()
    call_count = {"n": 0}

    async def flaky(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.ReadTimeout("first call timed out")
        return _fake_response(json.dumps(payload))

    fake_client = AsyncMock()
    fake_client.post.side_effect = flaky
    ex._http_client = fake_client

    monkeypatch.setattr(
        "app.services.memory.extractor._BACKOFF_BASE_SECONDS", 0.0,
    )
    out = await ex.extract(turns=_turns(), profile_snapshot={})
    assert call_count["n"] == 2
    assert out.profile_changes == []


async def test_extract_gives_up_after_max_retries(monkeypatch):
    ex = LocomoExtractor()

    async def always_fail(*args, **kwargs):
        raise httpx.ReadTimeout("never works")

    fake_client = AsyncMock()
    fake_client.post.side_effect = always_fail
    ex._http_client = fake_client

    monkeypatch.setattr(
        "app.services.memory.extractor._BACKOFF_BASE_SECONDS", 0.0,
    )
    with pytest.raises(httpx.ReadTimeout):
        await ex.extract(turns=_turns(), profile_snapshot={})