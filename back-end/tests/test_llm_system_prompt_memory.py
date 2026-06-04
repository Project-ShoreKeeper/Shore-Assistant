"""Tests for the [Profile] + [Relevant memories] block appended to system prompt."""

from app.services.llm_service import build_system_prompt, _format_memory_block
from app.services.memory.types import (
    ContextBundle, EmotionVector, EpisodicFact, ScoredFact,
)


def _bundle(profile=None, hits=None) -> ContextBundle:
    return ContextBundle(
        short_term=[],
        profile=profile or {},
        episodic_hits=hits or [],
    )


def test_format_block_empty_returns_empty_string():
    assert _format_memory_block(_bundle()) == ""


def test_format_block_profile_only():
    out = _format_memory_block(_bundle(profile={"name": "Luna"}))
    assert out.startswith("[Profile]")
    assert "Luna" in out
    assert "[Relevant memories]" not in out


def test_format_block_episodic_only():
    fact = EpisodicFact(
        fact="Luna drinks espresso",
        entity_tags=["coffee"],
        emotion=EmotionVector(),
        source_turn_ts=1.0,
        source_role="user",
        confidence=0.9,
    )
    out = _format_memory_block(_bundle(hits=[ScoredFact(fact=fact, score=0.8)]))
    assert "[Profile]" not in out
    assert "[Relevant memories]" in out
    assert "Luna drinks espresso" in out
    assert "[tags: coffee]" in out


def test_format_block_no_tags_em_dash():
    fact = EpisodicFact(
        fact="solo fact",
        entity_tags=[],
        emotion=EmotionVector(),
        source_turn_ts=1.0,
        source_role="user",
        confidence=0.9,
    )
    out = _format_memory_block(_bundle(hits=[ScoredFact(fact=fact, score=0.5)]))
    assert "[tags: —]" in out


def test_build_system_prompt_appends_memory_block_when_bundle_present():
    bundle = _bundle(profile={"name": "Luna"})
    prompt = build_system_prompt(
        retrieved_tool_names=["get_system_time"],
        memory_bundle=bundle,
    )
    assert "[Profile]" in prompt
    assert "Luna" in prompt


def test_build_system_prompt_no_block_when_bundle_empty():
    prompt = build_system_prompt(
        retrieved_tool_names=["get_system_time"],
        memory_bundle=_bundle(),
    )
    assert "[Profile]" not in prompt
    assert "[Relevant memories]" not in prompt


def test_build_system_prompt_no_block_when_bundle_none():
    prompt = build_system_prompt(
        retrieved_tool_names=["get_system_time"],
        memory_bundle=None,
    )
    assert "[Profile]" not in prompt
