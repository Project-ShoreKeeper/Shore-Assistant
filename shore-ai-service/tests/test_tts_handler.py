import pytest

from shore_ai.handlers.tts import TtsHandler
from shore_ai._pb import tts_pb2


@pytest.mark.asyncio
async def test_synthesize_emits_pcm_chunks():
    handler = TtsHandler()
    req = tts_pb2.SynthesizeRequest(text="hello world", voice="af_heart", chunk_size=4096)
    chunks = []
    async for chunk in handler.Synthesize(req, context=None):
        chunks.append(chunk.pcm_s16le)
    assert len(chunks) > 0
    assert sum(len(c) for c in chunks) > 0
    assert sum(len(c) for c in chunks) % 2 == 0  # int16 = 2 bytes/sample
