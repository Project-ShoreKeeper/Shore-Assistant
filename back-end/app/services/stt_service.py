"""
STT Service using HuggingFace Transformers (Whisper).
No ctranslate2 dependency -- uses PyTorch directly.

Model is loaded once at server startup and reused for all requests (singleton).
"""

import threading
from typing import Optional
import asyncio
import time
import numpy as np
import torch
from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline

# ─── Default config ───

SUPPORTED_MODELS = {
    "tiny": "openai/whisper-tiny",
    "base": "openai/whisper-base",
    "small": "openai/whisper-small",
    "medium": "openai/whisper-medium",
    "large-v3": "openai/whisper-large-v3",
    "large-v3-turbo": "openai/whisper-large-v3-turbo",
}

MODEL_SIZE = "base"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
TORCH_DTYPE = torch.float16 if DEVICE == "cuda" else torch.float32


class STTService:
    """
    Service managing Whisper model via HuggingFace Transformers for Speech-To-Text.
    Supports dynamic model size switching.
    """

    def __init__(
        self,
        model_size: str = MODEL_SIZE,
        device: str = DEVICE,
    ):
        self.model_size = model_size
        self.device = device
        self.torch_dtype = torch.float16 if device == "cuda" else torch.float32
        self.pipe = None
        self._is_loaded = False
        self._lock = threading.Lock()

    def load_model(self, model_size: Optional[str] = None) -> None:
        """
        Load Whisper model into memory.
        If model_size differs from current, release old model and load new one.
        """
        target_size = model_size or self.model_size

        if target_size not in SUPPORTED_MODELS:
            print(f"[STT] Warning: Model '{target_size}' not supported. Using '{MODEL_SIZE}'.")
            target_size = MODEL_SIZE

        model_id = SUPPORTED_MODELS[target_size]

        with self._lock:
            if self._is_loaded and target_size == self.model_size and self.pipe is not None:
                print(f"[STT] Model '{target_size}' already loaded and ready.")
                return

            print(f"[STT] {'Switching' if self._is_loaded else 'Loading'} model to '{target_size}' "
                  f"({model_id}, device={self.device})...")

            # Release old model
            self.pipe = None
            self._is_loaded = False
            self.model_size = target_size

            if self.device == "cuda":
                torch.cuda.empty_cache()

            start = time.time()
            try:
                model = AutoModelForSpeechSeq2Seq.from_pretrained(
                    model_id,
                    torch_dtype=self.torch_dtype,
                    low_cpu_mem_usage=True,
                    use_safetensors=True,
                )
                model.to(self.device)

                processor = AutoProcessor.from_pretrained(model_id)

                self.pipe = pipeline(
                    "automatic-speech-recognition",
                    model=model,
                    tokenizer=processor.tokenizer,
                    feature_extractor=processor.feature_extractor,
                    torch_dtype=self.torch_dtype,
                    device=self.device,
                )

                elapsed = time.time() - start
                self._is_loaded = True
                print(f"[STT] Model '{self.model_size}' ready! (loaded in {elapsed:.1f}s)")
            except Exception as e:
                print(f"[STT] Error loading model: {e}")
                self._is_loaded = False
                raise

    @property
    def is_loaded(self) -> bool:
        return self._is_loaded

    def transcribe(
        self,
        audio: np.ndarray,
        language: str = "en",
        **kwargs,
    ) -> dict:
        """
        Run STT on an audio segment (synchronous).
        """
        if not self._is_loaded or self.pipe is None:
            self.load_model()
            if self.pipe is None:
                raise RuntimeError("Cannot start STT model.")

        # Build generate_kwargs
        generate_kwargs = {}
        if language and language != "auto":
            generate_kwargs["language"] = language
            generate_kwargs["task"] = "transcribe"

        with self._lock:
            result = self.pipe(
                {"raw": audio, "sampling_rate": 16000},
                return_timestamps=True,
                generate_kwargs=generate_kwargs,
            )

        # Parse result
        text = result.get("text", "").strip()
        chunks = result.get("chunks", [])

        segments = []
        for chunk in chunks:
            ts = chunk.get("timestamp", (0, 0))
            segments.append({
                "start": round(ts[0], 2) if ts[0] is not None else 0,
                "end": round(ts[1], 2) if ts[1] is not None else 0,
                "text": chunk.get("text", "").strip(),
            })

        # Detect language (from generate_kwargs or fallback)
        detected_language = language if language != "auto" else "unknown"

        return {
            "text": text,
            "language": detected_language,
            "language_prob": 1.0 if language != "auto" else 0.0,
            "segments": segments,
            "model": self.model_size,
        }

    async def transcribe_async(
        self,
        audio: np.ndarray,
        language: str = "en",
        **kwargs,
    ) -> dict:
        """Async wrapper for transcribe()."""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self.transcribe(
                audio=audio,
                language=language,
                **kwargs,
            ),
        )
        return result


# ─── Singleton Instance ───
stt_service = STTService()
