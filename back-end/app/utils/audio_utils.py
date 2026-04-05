"""Audio format conversion utilities."""

import struct
import numpy as np


def pcm16_to_float32(pcm_bytes: bytes) -> np.ndarray:
    """Convert signed 16-bit PCM bytes to float32 numpy array [-1.0, 1.0]."""
    samples = np.frombuffer(pcm_bytes, dtype=np.int16)
    return samples.astype(np.float32) / 32768.0


def float32_to_pcm16(audio: np.ndarray) -> bytes:
    """Convert float32 numpy array [-1.0, 1.0] to signed 16-bit PCM bytes."""
    clipped = np.clip(audio, -1.0, 1.0)
    pcm = (clipped * 32767).astype(np.int16)
    return pcm.tobytes()
