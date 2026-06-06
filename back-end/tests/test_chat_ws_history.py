"""Integration test: /ws/chat sends a `history` message immediately on connect."""

import os

# Disable heavy startup work before importing app
os.environ.setdefault("STT_ENABLED", "False")

import pytest

# Skip the whole module if optional cloud deps aren't installed in this env.
pytest.importorskip("anthropic", reason="cloud_llm_service requires anthropic")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.websockets.chat_ws import router as chat_ws_router
from app.services.memory import memory_facade
from app.services.memory.types import Message


@pytest.fixture
def _stub_short_term(monkeypatch):
    """Stub memory_facade.short_term since tests don't run the full lifespan."""
    class _Stub:
        async def load(self):
            return []
        async def append(self, m):
            pass
        async def clear(self):
            return True
        async def health(self):
            return True
    monkeypatch.setattr(memory_facade, "short_term", _Stub())


@pytest.fixture
def client(monkeypatch, _stub_short_term):
    """Minimal FastAPI app with only the chat websocket — skip heavy lifespan."""
    app = FastAPI()
    app.include_router(chat_ws_router)
    return TestClient(app)


def test_history_message_sent_on_connect_with_persisted_data(client, monkeypatch):
    # Assistant turn carries thinking + tool actions in `extras`, the schema
    # rehydration relies on. The test asserts they survive the load/serialize
    # round-trip end-to-end through the websocket history frame.
    assistant_extras = {
        "thinking_text": "be friendly",
        "agent_actions": [
            {
                "action": "tool_call",
                "tool": "get_system_time",
                "args": {},
                "result": "noon",
                "status": "completed",
                "timestamp": 1.5,
            }
        ],
        "is_notification": False,
        "task_id": None,
    }
    fake_history = [
        {
            "role": "user",
            "content": "hello",
            "timestamp": 1.0,
        },
        {
            "role": "assistant",
            "content": "hi back",
            "timestamp": 2.0,
            "extras": assistant_extras,
        },
    ]

    async def _fake_load(**_):
        return [Message(**m) for m in fake_history]

    monkeypatch.setattr(memory_facade.short_term, "load", _fake_load)

    with client.websocket_connect("/ws/chat") as ws:
        first = ws.receive_json()
        assert first["type"] == "history"
        assert len(first["messages"]) == 2
        assert first["messages"][0]["role"] == "user"
        assert first["messages"][0]["content"] == "hello"
        # No extras on the user turn — neither nested nor flattened.
        assert "extras" not in first["messages"][0]
        assert "thinking_text" not in first["messages"][0]
        assert first["messages"][1]["role"] == "assistant"
        assert first["messages"][1]["content"] == "hi back"
        # Rehydration coverage: assistant metadata flattened to the top
        # level of the wire message (extras is the storage shape; the
        # frontend rehydration code expects thinking/agent_actions at the
        # message root).
        for key, value in assistant_extras.items():
            assert first["messages"][1][key] == value
        # And the nested form is NOT also sent — avoids dual rendering.
        assert "extras" not in first["messages"][1]


def test_history_message_sent_on_connect_when_empty(client, monkeypatch):
    async def _fake_load_empty(**_):
        return []

    monkeypatch.setattr(memory_facade.short_term, "load", _fake_load_empty)

    with client.websocket_connect("/ws/chat") as ws:
        first = ws.receive_json()
        assert first["type"] == "history"
        assert first["messages"] == []
