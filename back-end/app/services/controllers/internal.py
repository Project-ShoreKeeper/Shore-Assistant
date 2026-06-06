"""InternalController — toggles for in-process singletons.

Targets:
  - stt:            stt_service.load_model() / unload() + STT_ENABLED flag
  - tts:            tts_service.load() / unload() + TTS_ENABLED flag
  - locomo_worker:  WORKER_ENABLED flag only (worker reads from runtime_flags)
  - canonicalizer:  CANONICALIZER_ENABLED flag + APScheduler job add/remove

A target may be supplied with its dependencies injected (testability) or
default to importing the real singletons.
"""
from __future__ import annotations

import asyncio
from typing import Callable, Literal, Optional

from app.core import runtime_flags
from app.services.controllers.base import Controller, ServiceKind


InternalTarget = Literal["stt", "tts", "locomo_worker", "canonicalizer"]


class InternalController(Controller):

    def __init__(
        self,
        name: str,
        *,
        display_name: str,
        target: InternalTarget,
        correlates_with: Optional[str] = None,
        # Optional dependency injection (used by tests).
        stt=None, tts=None, scheduler=None,
        canonicalizer_func: Optional[Callable] = None,
        canonicalizer_cron: Optional[str] = None,
    ) -> None:
        super().__init__(
            name, display_name=display_name, correlates_with=correlates_with,
        )
        if target not in ("stt", "tts", "locomo_worker", "canonicalizer"):
            raise ValueError(f"Unknown internal target: {target!r}")
        self._target: InternalTarget = target
        self._stt = stt
        self._tts = tts
        self._scheduler = scheduler
        self._canonicalizer_func = canonicalizer_func
        self._canonicalizer_cron = canonicalizer_cron

    @property
    def kind(self) -> ServiceKind:
        return "internal"

    # ── State ──

    async def is_running(self) -> bool:
        if self._target == "stt":
            return runtime_flags.get("STT_ENABLED") and self._stt_service().is_loaded
        if self._target == "tts":
            return runtime_flags.get("TTS_ENABLED") and self._tts_service()._pipeline is not None
        if self._target == "locomo_worker":
            return bool(runtime_flags.get("WORKER_ENABLED"))
        if self._target == "canonicalizer":
            return bool(runtime_flags.get("CANONICALIZER_ENABLED"))
        return False

    # ── Lifecycle ──

    async def start(self) -> None:
        loop = asyncio.get_event_loop()
        try:
            if self._target == "stt":
                runtime_flags.set("STT_ENABLED", True)
                await loop.run_in_executor(None, self._stt_service().load_model)
            elif self._target == "tts":
                runtime_flags.set("TTS_ENABLED", True)
                await loop.run_in_executor(None, self._tts_service().load)
            elif self._target == "locomo_worker":
                runtime_flags.set("WORKER_ENABLED", True)
            elif self._target == "canonicalizer":
                runtime_flags.set("CANONICALIZER_ENABLED", True)
                self._register_canonicalizer_job()
        except Exception as e:
            self._record_action("start", error=f"{type(e).__name__}: {e}")
            raise
        self._record_action("start")

    async def stop(self) -> None:
        loop = asyncio.get_event_loop()
        try:
            if self._target == "stt":
                runtime_flags.set("STT_ENABLED", False)
                await loop.run_in_executor(None, self._stt_service().unload)
            elif self._target == "tts":
                runtime_flags.set("TTS_ENABLED", False)
                await loop.run_in_executor(None, self._tts_service().unload)
            elif self._target == "locomo_worker":
                runtime_flags.set("WORKER_ENABLED", False)
            elif self._target == "canonicalizer":
                runtime_flags.set("CANONICALIZER_ENABLED", False)
                self._unregister_canonicalizer_job()
        except Exception as e:
            self._record_action("stop", error=f"{type(e).__name__}: {e}")
            raise
        self._record_action("stop")

    # ── Lazy singleton getters ──

    def _stt_service(self):
        if self._stt is not None:
            return self._stt
        from app.services.stt_service import stt_service
        return stt_service

    def _tts_service(self):
        if self._tts is not None:
            return self._tts
        from app.services.tts_service import tts_service
        return tts_service

    def _scheduler_service(self):
        if self._scheduler is not None:
            return self._scheduler
        from app.services.scheduler_service import scheduler_service
        return scheduler_service

    def _register_canonicalizer_job(self) -> None:
        sched = self._scheduler_service()
        if sched.has_system_job("memory_canonicalizer"):
            return
        if self._canonicalizer_func is None:
            from app.services.memory.canonicalizer import run_canonicalization
            from app.core.config import settings
            func = run_canonicalization
            cron = self._canonicalizer_cron or settings.CANONICALIZER_CRON
        else:
            func = self._canonicalizer_func
            cron = self._canonicalizer_cron or "0 4 * * *"
        sched.add_system_job(func, cron=cron, job_id="memory_canonicalizer")

    def _unregister_canonicalizer_job(self) -> None:
        sched = self._scheduler_service()
        sched.remove_system_job("memory_canonicalizer")
