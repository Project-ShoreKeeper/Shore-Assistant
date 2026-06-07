"""Mutable runtime overrides for backend feature flags."""
from __future__ import annotations

import threading
from typing import Any

from app.core.config import settings


_MANAGED_KEYS: tuple[str, ...] = (
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
            _values[key] = getattr(settings, key)


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
    """Test helper: clear cached values so the next access re-reads settings."""
    with _lock:
        _values.clear()
