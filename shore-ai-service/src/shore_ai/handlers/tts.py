"""TTS gRPC handler wrapping Kokoro."""
from __future__ import annotations

import asyncio
from typing import Optional

import numpy as np

from shore_ai._pb import tts_pb2, tts_pb2_grpc


VOICE_MAP = {"en": "af_heart", "ja": "jf_alpha", "zh": "zf_xiaobei"}
DEFAULT_VOICE = "af_heart"


def _lang_for_voice(voice: str) -> str:
    if voice.startswith(("af_", "am_")): return "a"
    if voice.startswith(("bf_", "bm_")): return "b"
    if voice.startswith(("jf_", "jm_")): return "j"
    if voice.startswith(("zf_", "zm_")): return "z"
    return "a"


class TtsHandler(tts_pb2_grpc.TTSServicer):
    SAMPLE_RATE = 24000

    def __init__(self):
        self._pipeline = None
        self._current_lang: Optional[str] = None

    def loaded(self) -> bool:
        return self._pipeline is not None

    def _get_pipeline(self, lang_code: str):
        from kokoro import KPipeline
        if self._pipeline is None or self._current_lang != lang_code:
            self._pipeline = KPipeline(lang_code=lang_code, device="cpu")
            self._current_lang = lang_code
        return self._pipeline

    async def Synthesize(self, request, context):
        voice = request.voice or DEFAULT_VOICE
        chunk_size = request.chunk_size or 8192
        lang = _lang_for_voice(voice)

        def _synth() -> list[bytes]:
            pipe = self._get_pipeline(lang)
            out = []
            for _gs, _ps, audio in pipe(request.text, voice=voice, speed=1.0):
                if audio is None or len(audio) == 0:
                    continue
                if not isinstance(audio, np.ndarray):
                    audio = audio.cpu().numpy()
                pcm = (audio * 32767).clip(-32768, 32767).astype(np.int16).tobytes()
                for off in range(0, len(pcm), chunk_size):
                    out.append(pcm[off:off + chunk_size])
            return out

        chunks = await asyncio.get_event_loop().run_in_executor(None, _synth)
        for i, chunk in enumerate(chunks):
            yield tts_pb2.SynthesizeChunk(pcm_s16le=chunk, is_last=(i == len(chunks) - 1))
