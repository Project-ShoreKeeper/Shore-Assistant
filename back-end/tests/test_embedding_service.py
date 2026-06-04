"""Unit tests for the shared EmbeddingService singleton."""

import numpy as np
import pytest

from app.services.embedding_service import EmbeddingService


def test_encode_before_startup_raises():
    svc = EmbeddingService()
    with pytest.raises(RuntimeError):
        svc.encode("hello")


def test_startup_idempotent_and_encode_returns_384(monkeypatch):
    svc = EmbeddingService()
    svc.startup()
    # Calling startup a second time must not reload (model attr stays the same instance).
    model_ref = svc._model
    svc.startup()
    assert svc._model is model_ref

    vec = svc.encode("hello world")
    assert isinstance(vec, np.ndarray)
    assert vec.shape == (384,)


def test_encode_batch_returns_matrix():
    svc = EmbeddingService()
    svc.startup()
    mat = svc.encode(["a", "b", "c"])
    assert mat.shape == (3, 384)


async def test_aencode_offloads_to_executor():
    svc = EmbeddingService()
    svc.startup()
    vec = await svc.aencode("hello")
    assert vec.shape == (384,)
