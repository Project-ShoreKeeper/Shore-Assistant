"""Unit tests for Pydantic types in app.services.memory.types."""

import json
import pytest

from app.services.memory.types import (
    ContextBundle,
    EmotionVector,
    EpisodicFact,
    Message,
    ProfileChange,
    ScoredFact,
    WorkerOutput,
)


# ─── Message ─────────────────────────────────────────────────────────

def test_message_round_trip_preserves_extras():
    extras = {
        "thinking_text": "let me think",
        "agent_actions": [{"tool": "x", "status": "completed"}],
        "attachments": [{"type": "image", "mime": "image/png", "data_b64": "iVBOR"}],
    }
    msg = Message(role="assistant", content="hi", timestamp=1.5, extras=extras)
    payload = msg.model_dump_json()
    restored = Message.model_validate_json(payload)
    assert restored == msg
    assert restored.extras == extras


def test_message_extras_optional():
    msg = Message(role="user", content="hi", timestamp=1.0)
    assert msg.extras is None
    restored = Message.model_validate_json(msg.model_dump_json())
    assert restored.extras is None


# ─── EmotionVector ───────────────────────────────────────────────────

def test_emotion_valence_all_zeros():
    assert EmotionVector().valence == 0.0


def test_emotion_valence_pure_joy():
    # joy alone with intensity 1.0 → (1+0+0 - 0)/4 = 0.25
    assert EmotionVector(joy=1.0).valence == pytest.approx(0.25)


def test_emotion_valence_max_positive_clamps():
    v = EmotionVector(joy=1.0, trust=1.0, anticipation=1.0).valence
    assert v == pytest.approx(0.75)
    saturated = EmotionVector(joy=5.0, trust=5.0, anticipation=5.0).valence
    assert saturated == 1.0


def test_emotion_valence_max_negative_clamps():
    v = EmotionVector(fear=5.0, sadness=5.0, disgust=5.0, anger=5.0).valence
    assert v == -1.0


# ─── EpisodicFact ────────────────────────────────────────────────────

def test_episodic_fact_confidence_bounds():
    EpisodicFact(
        fact="test", entity_tags=["x"], emotion=EmotionVector(),
        source_turn_ts=1.0, source_role="user", confidence=0.0,
    )
    EpisodicFact(
        fact="test", entity_tags=["x"], emotion=EmotionVector(),
        source_turn_ts=1.0, source_role="user", confidence=1.0,
    )
    with pytest.raises(ValueError):
        EpisodicFact(
            fact="test", entity_tags=["x"], emotion=EmotionVector(),
            source_turn_ts=1.0, source_role="user", confidence=1.01,
        )


# ─── ProfileChange ───────────────────────────────────────────────────

def test_profile_change_none_value_means_delete():
    pc = ProfileChange(
        key_path="favorite_coffee", new_value=None,
        source_turn_ts=1.0, confidence=0.9, reason="user said never mind",
    )
    assert pc.new_value is None


def test_profile_change_complex_value():
    pc = ProfileChange(
        key_path="projects.shore_assistant",
        new_value={"status": "active", "phase": "p1"},
        source_turn_ts=1.0, confidence=0.95, reason="confirmed by user",
    )
    assert pc.new_value["status"] == "active"


# ─── WorkerOutput / ScoredFact / ContextBundle ───────────────────────

def test_worker_output_empty_lists_valid():
    out = WorkerOutput(profile_changes=[], episodic_facts=[])
    assert out.profile_changes == []
    assert out.episodic_facts == []


def test_scored_fact_score_bounds():
    fact = EpisodicFact(
        fact="x", entity_tags=[], emotion=EmotionVector(),
        source_turn_ts=1.0, source_role="user", confidence=0.5,
    )
    ScoredFact(fact=fact, score=0.0)
    ScoredFact(fact=fact, score=1.0)


def test_context_bundle_round_trip():
    bundle = ContextBundle(short_term=[], profile={}, episodic_hits=[])
    restored = ContextBundle.model_validate_json(bundle.model_dump_json())
    assert restored == bundle
