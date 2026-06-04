"""Shared SentenceTransformer singleton.
Used by tool_retriever (tool descriptions) and memory.embedder (facts / queries)
so the embedding model is loaded exactly once.
"""
import asyncio
from typing import Union

import numpy as np
from sentence_transformers import SentenceTransformer

from app.core.config import settings


class EmbeddingService:
    def __init__(self):
        self._model: SentenceTransformer | None = None

    def startup(self) -> None:
        if self._model is None:
            print(f"[Embedding] Loading {settings.TOOL_RETRIEVER_MODEL}")
            self._model = SentenceTransformer(
                settings.TOOL_RETRIEVER_MODEL, device="cpu",
            )

    def encode(self, text: Union[str, list[str]]) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("EmbeddingService not started")
        is_single = isinstance(text, str)
        inputs = [text] if is_single else text
        vecs = self._model.encode(inputs, normalize_embeddings=True)
        return vecs[0] if is_single else vecs

    async def aencode(self, text: Union[str, list[str]]) -> np.ndarray:
        """Run encode in the default executor to avoid blocking the event loop."""
        return await asyncio.get_running_loop().run_in_executor(
            None, self.encode, text,
        )


embedding_service = EmbeddingService()
