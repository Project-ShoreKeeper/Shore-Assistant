"""TTS gRPC handler wrapping Kokoro."""
from __future__ import annotations

import asyncio
import threading

import numpy as np

from shore_ai._pb import tts_pb2, tts_pb2_grpc


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
        # Per-language pipeline cache. Synthesize runs in run_in_executor
        # (worker thread), so concurrent calls with different languages can
        # race here — keep one pipeline per language and guard the dict.
        self._pipelines: dict[str, object] = {}
        self._pipelines_lock = threading.Lock()

    def loaded(self) -> bool:
        return bool(self._pipelines)

    def _get_pipeline(self, lang_code: str):
        from kokoro import KPipeline
        with self._pipelines_lock:
            pipe = self._pipelines.get(lang_code)
            if pipe is None:
                pipe = KPipeline(lang_code=lang_code, device="cpu")
                self._pipelines[lang_code] = pipe
            return pipe

    async def Synthesize(self, request, context):
        """Server-streaming synthesize. If text is empty, yields no chunks (silent end-of-stream)."""
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
