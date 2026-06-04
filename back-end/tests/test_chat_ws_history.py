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
from app.services import memory_service as memory_module


@pytest.fixture
def client(monkeypatch):
    """Minimal FastAPI app with only the chat websocket — skip heavy lifespan."""
    app = FastAPI()
    app.include_router(chat_ws_router)
    return TestClient(app)


def test_history_message_sent_on_connect_with_persisted_data(client, monkeypatch):
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
        },
    ]
    monkeypatch.setattr(
        memory_module.memory_service, "load", lambda session_id: fake_history
    )

    with client.websocket_connect("/ws/chat") as ws:
        first = ws.receive_json()
        assert first["type"] == "history"
        assert first["messages"] == fake_history


def test_history_message_sent_on_connect_when_empty(client, monkeypatch):
    monkeypatch.setattr(
        memory_module.memory_service, "load", lambda session_id: []
    )

    with client.websocket_connect("/ws/chat") as ws:
        first = ws.receive_json()
        assert first["type"] == "history"
        assert first["messages"] == []
