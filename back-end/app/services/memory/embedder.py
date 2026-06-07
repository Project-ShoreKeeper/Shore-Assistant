"""Async embedding wrapper used by the memory layer."""
from __future__ import annotations

from app.services.ai_client.embed import EmbedUnavailable, embed_client


class MemoryEmbedderUnavailable(RuntimeError):
    """Raised when shore-ai-service embedding is unavailable."""


class Embedder:
    DIM = 384  # all-MiniLM-L6-v2

    async def encode(self, text: str) -> list[float]:
        vectors = await self.encode_many([text])
        return vectors[0] if vectors else []

    async def encode_many(self, texts: list[str]) -> list[list[float]]:
        try:
            return await embed_client.encode(texts)
        except EmbedUnavailable as exc:
            raise MemoryEmbedderUnavailable(str(exc)) from exc


embedder = Embedder()
