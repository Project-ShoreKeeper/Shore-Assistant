"""
TTS Service using Kokoro TTS (local, offline, ~82M params).
Runs on CPU or GPU. No internet connection required.
Outputs 24kHz mono Float32 audio, converted to Int16 PCM for WebSocket streaming.
"""

import asyncio
import numpy as np
from typing import AsyncGenerator, Optional


# Kokoro voice IDs per language
VOICE_MAP = {
    "en": "af_heart",       # American English female (default, high quality)
    "ja": "jf_alpha",       # Japanese female
    "zh": "zf_xiaobei",     # Chinese female
}

DEFAULT_VOICE = "af_heart"
DEFAULT_LANG = "a"  # 'a' = American English

# Map language code to Kokoro lang_code
LANG_CODE_MAP = {
    "en": "a",  # American English
    "ja": "j",  # Japanese
    "zh": "z",  # Chinese
}


class TTSService:
    def __init__(self):
        self.sample_rate: int = 24000  # Kokoro outputs 24kHz
        self._available: Optional[bool] = None
        self._pipeline = None
        self._current_lang: str = "a"
        self.voice: str = DEFAULT_VOICE

    @property
    def is_available(self) -> bool:
        """Check if Kokoro is importable."""
        if self._available is not None:
            return self._available
        try:
            import kokoro
            self._available = True
            print("[TTS] Kokoro TTS available")
            return True
        except ImportError:
            self._available = False
            print("[TTS] Kokoro not installed. Run: pip install kokoro soundfile")
            return False

    def warmup(self):
        """Pre-load the default Kokoro pipeline so the first request is fast."""
        if self.is_available:
            self._get_pipeline(DEFAULT_LANG)

    def _get_pipeline(self, lang_code: str):
        """Lazy-init or re-init the Kokoro pipeline for the given language."""
        if self._pipeline is None or self._current_lang != lang_code:
            from kokoro import KPipeline
            print(f"[TTS] Loading Kokoro pipeline (lang={lang_code})...")
            self._pipeline = KPipeline(lang_code=lang_code, device="cpu")
            self._current_lang = lang_code
            print("[TTS] Kokoro pipeline ready")
        return self._pipeline

    def set_voice_for_language(self, language: str):
        """Set TTS voice based on language code."""
        self.voice = VOICE_MAP.get(language, DEFAULT_VOICE)

    async def synthesize_stream_pcm(
        self,
        text: str,
        voice: Optional[str] = None,
        chunk_size: int = 8192,
    ) -> AsyncGenerator[bytes, None]:
        """
        Synthesize text and yield raw PCM s16le audio chunks.
        Kokoro generates Float32 numpy arrays, converted to Int16 PCM bytes.
        Runs synthesis in a thread to avoid blocking the event loop.
        """
        if not self.is_available:
            return

        target_voice = voice or self.voice
        lang_code = LANG_CODE_MAP.get(self._current_lang, DEFAULT_LANG)

        # Determine lang_code from voice prefix
        if target_voice.startswith(("af_", "am_")):
            lang_code = "a"
        elif target_voice.startswith(("bf_", "bm_")):
            lang_code = "b"
        elif target_voice.startswith(("jf_", "jm_")):
            lang_code = "j"
        elif target_voice.startswith(("zf_", "zm_")):
            lang_code = "z"

        def _synthesize() -> list[bytes]:
            """Run Kokoro synthesis (blocking) and return PCM chunks."""
            pipeline = self._get_pipeline(lang_code)
            chunks = []

            for _gs, _ps, audio in pipeline(text, voice=target_voice, speed=1.0):
                if audio is not None and len(audio) > 0:
                    # Ensure numpy array (Kokoro may return a PyTorch tensor)
                    if not isinstance(audio, np.ndarray):
                        audio = audio.cpu().numpy()
                    # Convert float32 [-1, 1] to int16 PCM bytes
                    int16_audio = (audio * 32767).clip(-32768, 32767).astype(np.int16)
                    pcm_bytes = int16_audio.tobytes()

                    # Split into chunks
                    offset = 0
                    while offset < len(pcm_bytes):
                        end = min(offset + chunk_size, len(pcm_bytes))
                        chunks.append(pcm_bytes[offset:end])
                        offset = end

            return chunks

        try:
            loop = asyncio.get_event_loop()
            pcm_chunks = await loop.run_in_executor(None, _synthesize)

            for chunk in pcm_chunks:
                yield chunk

        except Exception as e:
            print(f"[TTS] Kokoro synthesis error: {type(e).__name__}: {e}")

    async def synthesize_full(self, text: str) -> bytes:
        """Synthesize text and return complete PCM audio as bytes."""
        chunks = []
        async for chunk in self.synthesize_stream_pcm(text):
            chunks.append(chunk)
        return b"".join(chunks)


tts_service = TTSService()
