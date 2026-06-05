"""Thin async wrapper over the shared EmbeddingService for memory layers."""
import asyncio

import numpy as np

from app.services.embedding_service import embedding_service


class Embedder:
    DIM = 384  # all-MiniLM-L6-v2

    async def encode(self, text: str) -> list[float]:
        vec: np.ndarray = await embedding_service.aencode(text)
        return vec.tolist()

    async def encode_many(self, texts: list[str]) -> list[list[float]]:
        return list(await asyncio.gather(*(self.encode(t) for t in texts)))


embedder = Embedder()
