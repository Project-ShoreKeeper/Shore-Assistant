"""Unit tests for the memory.embedder thin wrapper."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.ai_client.embed import EmbedUnavailable
from app.services.memory.embedder import Embedder, MemoryEmbedderUnavailable


async def test_encode_returns_list_of_floats_length_384():
    fake_vec = [0.0] * 384
    with patch(
        "app.services.memory.embedder.embed_client.encode",
        new=AsyncMock(return_value=[fake_vec]),
    ):
        emb = Embedder()
        out = await emb.encode("hello")
    assert isinstance(out, list)
    assert len(out) == 384
    assert all(isinstance(x, float) for x in out)


async def test_encode_many_returns_list_of_vectors():
    fake = [[0.1] * 384, [0.2] * 384]
    with patch(
        "app.services.memory.embedder.embed_client.encode",
        new=AsyncMock(return_value=fake),
    ):
        emb = Embedder()
        out = await emb.encode_many(["a", "b"])
    assert out == fake


async def test_encode_translates_unavailable_to_memory_embedder_unavailable():
    """MemoryFacade's circuit breaker relies on this typed translation."""
    with patch(
        "app.services.memory.embedder.embed_client.encode",
        new=AsyncMock(side_effect=EmbedUnavailable("shore-ai down")),
    ):
        emb = Embedder()
        with pytest.raises(MemoryEmbedderUnavailable):
            await emb.encode("hello")


async def test_encode_many_translates_unavailable():
    with patch(
        "app.services.memory.embedder.embed_client.encode",
        new=AsyncMock(side_effect=EmbedUnavailable("shore-ai down")),
    ):
        emb = Embedder()
        with pytest.raises(MemoryEmbedderUnavailable):
            await emb.encode_many(["a"])


def test_dim_constant_is_384():
    assert Embedder.DIM == 384
