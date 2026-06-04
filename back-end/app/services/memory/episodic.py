"""Episodic memory stub — implemented in Phase 2 against Qdrant."""

from typing import Any


class EpisodicMemory:
    async def search(
        self,
        query: str,
        entity_filter: list[str] | None = None,
        top_k: int = 5,
        min_score: float = 0.3,
    ) -> list:
        return []

    async def upsert(self, fact: Any) -> None:
        raise NotImplementedError("Episodic writes wired in Phase 2")

    async def health(self) -> bool:
        return False
