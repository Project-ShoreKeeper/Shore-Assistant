"""Mutable runtime overrides for select feature flags.

The dashboard service-control feature needs to flip a handful of "is feature
enabled" booleans at runtime without writing back to .env. Reading code paths
that previously consulted `settings.X` for one of these keys must go through
``runtime_flags.get(...)`` instead.

Flags are initialized from `settings` at startup and reset to those defaults
on the next process start (no persistence in v1).
"""
from __future__ import annotations

import threading
from typing import Any

from app.core.config import settings


_MANAGED_KEYS: tuple[str, ...] = (
    "STT_ENABLED",
    "TTS_ENABLED",
    "WORKER_ENABLED",
    "CANONICALIZER_ENABLED",
)

_lock = threading.Lock()
_values: dict[str, Any] = {}


def _ensure_initialized() -> None:
    if _values:
        return
    with _lock:
        if _values:
            return
        for key in _MANAGED_KEYS:
            # TTS has no env flag today — default to True (TTS is on unless
            # someone toggles it off via the dashboard).
            _values[key] = getattr(settings, key, True)


def get(key: str) -> Any:
    _ensure_initialized()
    with _lock:
        if key not in _values:
            raise KeyError(f"runtime_flags has no key {key!r}")
        return _values[key]


def set(key: str, value: Any) -> None:
    _ensure_initialized()
    with _lock:
        if key not in _MANAGED_KEYS:
            raise KeyError(f"runtime_flags cannot set unmanaged key {key!r}")
        _values[key] = value


def snapshot() -> dict[str, Any]:
    _ensure_initialized()
    with _lock:
        return dict(_values)


def reset_for_tests() -> None:
    """Test helper — clear cached values so the next access re-reads settings."""
    with _lock:
        _values.clear()
