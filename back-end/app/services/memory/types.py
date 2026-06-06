"""
Pydantic contracts shared by every memory layer.

These are intentionally schema-only (no behavior). Each phase's
implementation imports from here so contracts stay in one place.
"""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class Message(BaseModel):
    """A single short-term memory entry, stored in Redis as JSON."""

    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: float
    extras: Optional[dict] = None


class EmotionVector(BaseModel):
    """Plutchik 8 emotions with intensity 0-1 each."""

    joy: float = 0.0
    trust: float = 0.0
    fear: float = 0.0
    surprise: float = 0.0
    sadness: float = 0.0
    disgust: float = 0.0
    anger: float = 0.0
    anticipation: float = 0.0

    @property
    def valence(self) -> float:
        pos = self.joy + self.trust + self.anticipation
        neg = self.fear + self.sadness + self.disgust + self.anger
        return max(-1.0, min(1.0, (pos - neg) / 4.0))


class EpisodicFact(BaseModel):
    """A worker-distilled fact, embedded in Qdrant."""

    fact: str
    entity_tags: list[str]
    emotion: EmotionVector
    source_turn_ts: float
    source_role: Literal["user", "assistant"]
    confidence: float = Field(ge=0.0, le=1.0)


class ProfileChange(BaseModel):
    """A single change to profile JSONB, applied transactionally with audit."""

    key_path: str
    new_value: Any | None
    source_turn_ts: float
    confidence: float
    reason: str


class WorkerOutput(BaseModel):
    """Sole contract between LOCOMO worker and the write side."""

    profile_changes: list[ProfileChange]
    episodic_facts: list[EpisodicFact]


class ScoredFact(BaseModel):
    """Returned by episodic.search() and list_recent() — fact plus score.

    `point_id` and `created_at` are populated when the row came from a live
    Qdrant query (search / list_recent). They are optional so the type stays
    backward-compatible with worker round-trip tests that construct
    ScoredFact directly without a Qdrant write.
    """

    fact: EpisodicFact
    score: float
    point_id: Optional[str] = None
    created_at: Optional[float] = None


class ContextBundle(BaseModel):
    """Output of MemoryFacade.assemble_context()."""

    short_term: list[Message]
    profile: dict
    episodic_hits: list[ScoredFact]
