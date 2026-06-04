"""Embedder — wired in Phase 2."""


class Embedder:
    async def encode(self, text: str) -> list[float]:
        raise NotImplementedError("Embedder is wired in Phase 2")
