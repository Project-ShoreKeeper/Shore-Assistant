import pytest

from shore_ai.handlers.health import HealthHandler
from shore_ai._pb import health_pb2


class _Fake:
    def __init__(self, name, loaded, detail): self.n, self.l, self.d = name, loaded, detail
    def loaded(self): return self.l


@pytest.mark.asyncio
async def test_health_reports_all_components():
    handler = HealthHandler(
        components={
            "stt":   (_Fake("stt", True, "base"),       "base"),
            "tts":   (_Fake("tts", False, "af_heart"),  "af_heart"),
            "embed": (_Fake("embed", True, "MiniLM"),   "all-MiniLM-L6-v2"),
        },
        version="0.1.0",
    )
    resp = await handler.Get(health_pb2.GetRequest(), context=None)
    assert resp.version == "0.1.0"
    assert resp.ready is False                          # tts not loaded
    names = {c.name for c in resp.components}
    assert names == {"stt", "tts", "embed"}
