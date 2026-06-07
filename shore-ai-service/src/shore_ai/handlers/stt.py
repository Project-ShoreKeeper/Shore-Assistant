"""STT gRPC handler wrapping HuggingFace Whisper."""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Optional

import grpc
import numpy as np
import torch
from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline

from shore_ai._pb import stt_pb2, stt_pb2_grpc


SUPPORTED_MODELS = {
    "tiny": "openai/whisper-tiny",
    "base": "openai/whisper-base",
    "small": "openai/whisper-small",
    "medium": "openai/whisper-medium",
    "large-v3": "openai/whisper-large-v3",
    "large-v3-turbo": "openai/whisper-large-v3-turbo",
}


log = logging.getLogger(__name__)


class SttHandler(stt_pb2_grpc.STTServicer):
    """Whisper STT servicer with lazy model load.

    The model is large (large-v3 ~3GB) and load is slow (10-30s on cold cache).
    Loading synchronously in __init__ would delay grpc.aio.server.start() —
    Health.Get would be unreachable during load, and the supervisor would see
    the container as "running" while clients got raw connection errors.
    Instead, kick off load in a background task right after construction and
    let Transcribe return UNAVAILABLE while it's still warming up. The
    Dashboard polls Health.Get every 5s and surfaces `loaded=false` until
    the model is ready, matching the spec's cold-start UX contract.
    """

    def __init__(self, model_size: str = "base", device: Optional[str] = None):
        self.model_size = model_size
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.torch_dtype = torch.float16 if self.device == "cuda" else torch.float32
        self.pipe = None
        self._lock = threading.Lock()
        self._load_started = False

    def start_load(self) -> asyncio.Task:
        """Schedule the model load on a thread so the event loop stays free.
        Idempotent — safe to call multiple times. Returns the load Task."""
        if self._load_started:
            return asyncio.create_task(asyncio.sleep(0))
        self._load_started = True

        async def _load_async() -> None:
            try:
                await asyncio.get_event_loop().run_in_executor(None, self._load)
                log.info("stt: model %s loaded on %s", self.model_size, self.device)
            except Exception as e:
                log.exception("stt: model load failed: %r", e)

        return asyncio.create_task(_load_async())

    def _load(self) -> None:
        model_id = SUPPORTED_MODELS[self.model_size]
        model = AutoModelForSpeechSeq2Seq.from_pretrained(
            model_id,
            torch_dtype=self.torch_dtype,
            low_cpu_mem_usage=True,
            use_safetensors=True,
        ).to(self.device)
        processor = AutoProcessor.from_pretrained(model_id)
        self.pipe = pipeline(
            "automatic-speech-recognition",
            model=model,
            tokenizer=processor.tokenizer,
            feature_extractor=processor.feature_extractor,
            torch_dtype=self.torch_dtype,
            device=self.device,
        )

    def loaded(self) -> bool:
        return self.pipe is not None

    async def Transcribe(self, request, context):
        if self.pipe is None:
            # Kick off the load if the server boot path didn't, then fail fast
            # so the backend's SttUnavailable branch fires and the user sees
            # an "stt loading" transcript instead of hanging on a 30s warmup.
            self.start_load()
            if context is not None:
                await context.abort(
                    grpc.StatusCode.UNAVAILABLE, "stt model still loading",
                )
            raise RuntimeError("stt model still loading")

        audio = np.frombuffer(request.audio_f32, dtype=np.float32).copy()
        language = request.language or "en"

        def _run():
            generate_kwargs = {}
            if language != "auto":
                generate_kwargs = {"language": language, "task": "transcribe"}
            with self._lock:
                return self.pipe(
                    {"raw": audio, "sampling_rate": 16000},
                    return_timestamps=True,
                    generate_kwargs=generate_kwargs,
                )

        result = await asyncio.get_event_loop().run_in_executor(None, _run)
        segs = [
            stt_pb2.TranscribeSegment(
                start=round(c.get("timestamp", (0, 0))[0] or 0, 2),
                end=round(c.get("timestamp", (0, 0))[1] or 0, 2),
                text=c.get("text", "").strip(),
            )
            for c in result.get("chunks", [])
        ]
        return stt_pb2.TranscribeResponse(
            text=result.get("text", "").strip(),
            language=language,
            language_prob=1.0 if language != "auto" else 0.0,
            segments=segs,
            model=self.model_size,
        )
