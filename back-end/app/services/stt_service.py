"""
STT Service sử dụng Faster-Whisper
Chạy inference trên CPU (hoặc GPU nếu có CUDA).

Model được load 1 lần duy nhất khi server khởi động,
tái sử dụng cho tất cả các request (singleton).
"""

import threading
from typing import Optional, List
import asyncio
import time
import numpy as np
from faster_whisper import WhisperModel

# ─── Cấu hình mặc định ───

# Model sizes: tiny, base, small, medium, large-v1, large-v2, large-v3, large-v3-turbo
SUPPORTED_MODELS = [
    "tiny", "base", "small", "medium", 
    "large-v1", "large-v2", "large-v3", "large-v3-turbo"
]

MODEL_SIZE = "base"
COMPUTE_TYPE = "int8"
DEVICE = "cpu"


class STTService:
    """
    Service quản lý mô hình Faster-Whisper cho Speech-To-Text.
    Hỗ trợ thay đổi model size linh hoạt.
    """

    def __init__(
        self,
        model_size: str = MODEL_SIZE,
        device: str = DEVICE,
        compute_type: str = COMPUTE_TYPE,
    ):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.model: Optional[WhisperModel] = None
        self._is_loaded = False
        self._lock = threading.Lock()

    def load_model(self, model_size: Optional[str] = None) -> None:
        """
        Load mô hình Whisper vào bộ nhớ. 
        Nếu model_size khác với model hiện tại, tiến hành giải phóng cũ và nạp mới.
        """
        target_model = model_size or self.model_size
        
        # Kiểm tra model hợp lệ
        if target_model not in SUPPORTED_MODELS:
            print(f"[STT] Cảnh báo: Model '{target_model}' không nằm trong danh sách hỗ trợ. Dùng '{MODEL_SIZE}' thay thế.")
            target_model = MODEL_SIZE

        with self._lock:
            # Nếu đã load và đúng size → bỏ qua
            if self._is_loaded and target_model == self.model_size and self.model is not None:
                print(f"[STT] Model '{target_model}' đã được load và sẵn sàng.")
                return

            print(f"[STT] {'Đang chuyển đổi' if self._is_loaded else 'Đang tải'} model sang '{target_model}' "
                  f"(device={self.device}, compute={self.compute_type})...")

            # Giải phóng model cũ (Python GC sẽ tự thu hồi khi reference = None)
            self.model = None
            self._is_loaded = False
            self.model_size = target_model

            start = time.time()
            try:
                self.model = WhisperModel(
                    self.model_size,
                    device=self.device,
                    compute_type=self.compute_type,
                )
                elapsed = time.time() - start
                self._is_loaded = True
                print(f"[STT] Model '{self.model_size}' đã sẵn sàng! (tải trong {elapsed:.1f}s)")
            except Exception as e:
                print(f"[STT] Lỗi khi load model: {e}")
                self._is_loaded = False
                raise e

    @property
    def is_loaded(self) -> bool:
        return self._is_loaded

    def transcribe(
        self,
        audio: np.ndarray,
        language: str = "vi",
        beam_size: int = 5,
        temperature: float = 0.0,
        initial_prompt: Optional[str] = None,
    ) -> dict:
        """
        Chạy STT trên đoạn audio (đồng bộ).
        """
        if not self._is_loaded or self.model is None:
            # Cố gắng load mặc định nếu chưa có
            self.load_model()
            if self.model is None:
                raise RuntimeError("Không thể khởi động Model STT.")

        # Nếu language = "auto", để Whisper tự detect
        lang_param = None if language == "auto" else language

        with self._lock: # Đảm bảo không transcribe khi đang đổi model
            segments, info = self.model.transcribe(
                audio,
                language=lang_param,
                beam_size=beam_size,
                temperature=temperature,
                initial_prompt=initial_prompt,
                vad_filter=False,
                word_timestamps=False,
            )

            # Lấy toàn bộ segments (generator → list)
            segment_list = []
            full_text_parts = []

            for seg in segments:
                segment_list.append({
                    "start": round(seg.start, 2),
                    "end": round(seg.end, 2),
                    "text": seg.text.strip(),
                })
                full_text_parts.append(seg.text.strip())

        full_text = " ".join(full_text_parts)

        return {
            "text": full_text,
            "language": info.language,
            "language_prob": round(info.language_probability, 3),
            "segments": segment_list,
            "model": self.model_size,
        }

    async def transcribe_async(
        self,
        audio: np.ndarray,
        language: str = "vi",
        beam_size: int = 5,
        temperature: float = 0.0,
        initial_prompt: Optional[str] = None,
    ) -> dict:
        """
        Wrapper async cho transcribe().
        """
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self.transcribe(
                audio=audio,
                language=language,
                beam_size=beam_size,
                temperature=temperature,
                initial_prompt=initial_prompt,
            ),
        )
        return result


# ─── Singleton Instance ───
stt_service = STTService()
