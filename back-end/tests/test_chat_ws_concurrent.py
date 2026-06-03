"""Regression test: /ws/chat must not deadlock while the agent is running.

The WebSocket message loop has to keep processing inbound control messages
(e.g. ``terminal_confirm_response``) while a long-running agent task is in
flight — otherwise the confirm flow deadlocks because the agent is waiting for
a confirm that can never be delivered.
"""

import asyncio
import os
import time

os.environ.setdefault("STT_ENABLED", "False")

import pytest

pytest.importorskip("anthropic", reason="cloud_llm_service requires anthropic")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.websockets.chat_ws import router as chat_ws_router
from app.services import memory_service as memory_module
from app.services.agent_service import agent_service
from app.services.terminal_service import terminal_service


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(chat_ws_router)
    monkeypatch.setattr(
        memory_module.memory_service, "load", lambda session_id: []
    )
    monkeypatch.setattr(
        memory_module.memory_service,
        "append",
        lambda **kwargs: None,
    )
    return TestClient(app)


def test_terminal_confirm_response_not_blocked_by_running_agent(client, monkeypatch):
    """While ``run_agent_pipeline`` is awaiting, inbound terminal_confirm_response
    messages must still be dispatched to ``terminal_service.resolve_confirm``."""

    agent_sleep = 1.5

    async def slow_agent_run(*args, **kwargs):
        await asyncio.sleep(agent_sleep)
        yield {"type": "llm_complete", "text": "done"}

    monkeypatch.setattr(agent_service, "run", slow_agent_run)

    resolve_times: list[float] = []
    original_resolve = terminal_service.resolve_confirm

    def spy_resolve(request_id, decision):
        resolve_times.append(time.monotonic())
        return original_resolve(request_id, decision)

    monkeypatch.setattr(terminal_service, "resolve_confirm", spy_resolve)

    with client.websocket_connect("/ws/chat") as ws:
        first = ws.receive_json()
        assert first["type"] == "history"

        start = time.monotonic()
        ws.send_json(
            {"type": "user_message", "text": "hello", "source": "keyboard"}
        )
        # Let the agent task start awaiting
        time.sleep(0.1)
        ws.send_json(
            {
                "type": "terminal_confirm_response",
                "request_id": "fake-id",
                "decision": "approve",
            }
        )

        # Poll for resolve_confirm to be invoked — should happen quickly
        # (well before the agent finishes its sleep).
        deadline = start + agent_sleep - 0.3
        while time.monotonic() < deadline and not resolve_times:
            time.sleep(0.05)

    assert resolve_times, "resolve_confirm was never called"
    elapsed = resolve_times[0] - start
    assert elapsed < agent_sleep - 0.3, (
        f"resolve_confirm called {elapsed:.2f}s after user_message; "
        f"expected well under {agent_sleep:.2f}s (agent run blocked the WS loop)"
    )


def test_terminal_resync_with_active_session_returns_snapshot(client, monkeypatch):
    """terminal_service.sessions stores plain dicts, not objects. The resync
    handler previously did ``v.session_id`` / ``v._buffer`` on those dicts,
    raising AttributeError → uncaught exception closed the WS → the frontend
    reconnected → loop. Regression: handler must read the dict by key and the
    snapshot must arrive in the same connection."""
    # Seed terminal_service with a fake active session entry (same shape that
    # TerminalService.open_session() builds — see terminal_service.py).
    fake_session = {
        "session_id": "deadbeef1234",
        "shell": "powershell",
        "cwd": r"D:\Jupiter",
        "pid": 9999,
        "last_activity": time.time(),
        "_buffer_tail": "PS D:\\Jupiter> ",
    }
    terminal_service.sessions["fake-session"] = fake_session
    try:
        with client.websocket_connect("/ws/chat") as ws:
            first = ws.receive_json()
            assert first["type"] == "history"

            ws.send_json({"type": "terminal_resync"})
            snapshot = ws.receive_json()

        assert snapshot["type"] == "terminal_sessions_snapshot"
        names = [s["name"] for s in snapshot["sessions"]]
        assert "fake-session" in names
    finally:
        terminal_service.sessions.pop("fake-session", None)
