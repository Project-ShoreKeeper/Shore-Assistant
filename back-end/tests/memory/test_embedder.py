"""Unit tests for the memory.embedder thin wrapper."""

from unittest.mock import AsyncMock, patch

import numpy as np

from app.services.memory.embedder import Embedder


async def test_encode_returns_list_of_floats_length_384():
    fake_vec = np.zeros(384, dtype=np.float32)
    with patch(
        "app.services.memory.embedder.embedding_service.aencode",
        new=AsyncMock(return_value=fake_vec),
    ):
        emb = Embedder()
        out = await emb.encode("hello")
    assert isinstance(out, list)
    assert len(out) == 384
    assert all(isinstance(x, float) for x in out)


def test_dim_constant_is_384():
    assert Embedder.DIM == 384
