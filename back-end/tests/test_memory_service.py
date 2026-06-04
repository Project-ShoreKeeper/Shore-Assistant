"""Tests for memory_service: extras persistence, full load, backward compat."""

import json
from pathlib import Path

import pytest

from app.services.memory_service import MemoryService


@pytest.fixture
def svc(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MEMORY_DIR", str(tmp_path))
    monkeypatch.setenv("MEMORY_MAX_TURNS", "20")
    # Build a fresh service rooted at tmp_path so tests don't touch real disk
    service = MemoryService()
    service.memory_dir = tmp_path
    service.max_turns = 20
    return service


def test_append_user_message_minimal_fields(svc, tmp_path):
    svc.append("s1", "user", "hello")
    data = json.loads((tmp_path / "s1.json").read_text(encoding="utf-8"))
    assert len(data) == 1
    msg = data[0]
    assert msg["role"] == "user"
    assert msg["content"] == "hello"
    assert "timestamp" in msg
    # User messages should not carry assistant extras
    assert "thinking_text" not in msg
    assert "agent_actions" not in msg


def test_append_with_extras_persists_them(svc, tmp_path):
    extras = {
        "thinking_text": "let me think",
        "agent_actions": [
            {
                "action": "tool_call",
                "tool": "get_system_time",
                "args": {},
                "result": "2026-06-03",
                "status": "completed",
                "timestamp": 123.0,
            }
        ],
        "is_notification": False,
        "task_id": None,
    }
    svc.append("s1", "assistant", "It's noon.", extras=extras)
    data = json.loads((tmp_path / "s1.json").read_text(encoding="utf-8"))
    msg = data[0]
    assert msg["role"] == "assistant"
    assert msg["content"] == "It's noon."
    assert msg["thinking_text"] == "let me think"
    assert msg["agent_actions"][0]["tool"] == "get_system_time"
    assert msg["is_notification"] is False
    assert msg["task_id"] is None


def test_load_returns_full_dicts_including_extras(svc):
    svc.append("s2", "user", "hi")
    svc.append(
        "s2",
        "assistant",
        "hello back",
        extras={"thinking_text": "respond warmly", "agent_actions": None},
    )
    loaded = svc.load("s2")
    assert len(loaded) == 2
    assert loaded[0]["role"] == "user"
    assert loaded[0]["content"] == "hi"
    assert loaded[1]["thinking_text"] == "respond warmly"


def test_load_backward_compat_with_legacy_format(svc, tmp_path):
    # Old-format file: only role, content, timestamp; no extras
    legacy = [
        {"role": "user", "content": "old", "timestamp": 1.0},
        {"role": "assistant", "content": "old reply", "timestamp": 2.0},
    ]
    (tmp_path / "legacy.json").write_text(json.dumps(legacy), encoding="utf-8")
    loaded = svc.load("legacy")
    assert len(loaded) == 2
    assert loaded[0]["content"] == "old"
    assert loaded[1]["content"] == "old reply"
    # Optional fields simply absent — readers should handle .get()
    assert loaded[1].get("thinking_text") is None
    assert loaded[1].get("agent_actions") is None


def test_append_extras_none_does_not_add_keys(svc, tmp_path):
    svc.append("s3", "assistant", "plain", extras=None)
    data = json.loads((tmp_path / "s3.json").read_text(encoding="utf-8"))
    msg = data[0]
    assert msg["content"] == "plain"
    assert "thinking_text" not in msg
    assert "agent_actions" not in msg
