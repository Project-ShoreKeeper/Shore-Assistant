import pytest

from shore_ai.handlers.embed import EmbedHandler
from shore_ai._pb import embed_pb2


@pytest.mark.asyncio
async def test_encode_returns_vectors_with_correct_dim():
    handler = EmbedHandler()
    req = embed_pb2.EncodeRequest(texts=["hello", "world"])
    resp = await handler.Encode(req, context=None)
    assert len(resp.vectors) == 2
    assert resp.dim == 384      # all-MiniLM-L6-v2
    assert len(resp.vectors[0].values) == 384
    assert resp.model == "all-MiniLM-L6-v2"
