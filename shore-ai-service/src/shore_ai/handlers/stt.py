"""STT gRPC handler wrapping HuggingFace Whisper."""
from __future__ import annotations

import asyncio
import threading
from typing import Optional

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


class SttHandler(stt_pb2_grpc.STTServicer):
    def __init__(self, model_size: str = "base", device: Optional[str] = None):
        self.model_size = model_size
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.torch_dtype = torch.float16 if self.device == "cuda" else torch.float32
        self.pipe = None
        self._lock = threading.Lock()
        self._load()

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
        audio = np.frombuffer(request.audio_f32, dtype=np.float32)
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
