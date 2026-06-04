"""Tests for memory_bundle threading through agent_service.run."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.agent_service import agent_service
from app.services.memory.types import ContextBundle, EmotionVector, EpisodicFact, ScoredFact


def _bundle_with_profile():
    return ContextBundle(
        short_term=[],
        profile={"name": "Luna"},
        episodic_hits=[],
    )


async def _drain(gen):
    async for _ in gen:
        pass


async def test_memory_bundle_threaded_into_system_prompt():
    """When memory_bundle is given, build_system_prompt receives it."""
    captured = {}

    async def fake_stream(messages, system_prompt, **kwargs):
        captured["system_prompt"] = system_prompt
        yield {"type": "done", "full_text": ""}

    with patch(
        "app.services.agent_service.llm_service.stream_chat_sentences",
        new=fake_stream,
    ):
        await _drain(agent_service.run(
            user_text="hi",
            conversation_history=[{"role": "user", "content": "hi"}],
            memory_bundle=_bundle_with_profile(),
        ))

    assert "[Profile]" in captured["system_prompt"]
    assert "Luna" in captured["system_prompt"]


async def test_no_tools_path_drops_memory_bundle():
    """no_tools=True (notifications) must NOT inject Profile/Episodic."""
    captured = {}

    async def fake_stream(messages, system_prompt, **kwargs):
        captured["system_prompt"] = system_prompt
        yield {"type": "done", "full_text": ""}

    with patch(
        "app.services.agent_service.llm_service.stream_chat_sentences",
        new=fake_stream,
    ):
        await _drain(agent_service.run(
            user_text="reminder fires",
            conversation_history=[{"role": "user", "content": "x"}],
            memory_bundle=_bundle_with_profile(),
            no_tools=True,
        ))

    assert "[Profile]" not in captured["system_prompt"]
