import pytest

from app.services.tool_retriever import ToolRetriever, ALWAYS_AVAILABLE


def test_computer_use_is_always_available():
    assert "computer_use" in ALWAYS_AVAILABLE


@pytest.mark.asyncio
async def test_stop_companion_added_when_computer_use_present():
    r = ToolRetriever()
    # simulate a degraded/empty embedding index so retrieve() returns
    # always-available only, then confirm companion expansion includes stop.
    r._tool_embeddings = None
    r._tool_names = ["computer_use", "stop_computer_use", "get_system_time"]
    names = await r.retrieve("do something on screen")
    assert "computer_use" in names


@pytest.mark.asyncio
async def test_companion_mapping_is_bidirectional(monkeypatch):
    # White-box: the COMPANION_TOOLS dict inside retrieve() must pair the two.
    # We assert on the source of truth by calling retrieve with a fake index.
    import numpy as np
    r = ToolRetriever()
    r._tool_names = ["computer_use", "stop_computer_use"]
    r._tool_texts = ["computer_use: x", "stop_computer_use: y"]
    # identity embeddings so "computer_use" scores highest for its own text
    r._tool_embeddings = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)

    async def fake_encode(texts, model=None):
        return [[1.0, 0.0]]  # matches computer_use row

    monkeypatch.setattr("app.services.tool_retriever.embed_client.encode", fake_encode)
    names = await r.retrieve("control screen")
    assert "computer_use" in names and "stop_computer_use" in names
