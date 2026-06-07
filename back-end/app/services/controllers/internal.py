"""InternalController — toggles for in-process singletons.

Targets:
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


InternalTarget = Literal["locomo_worker", "canonicalizer"]


class InternalController(Controller):

    def __init__(
        self,
        name: str,
        *,
        display_name: str,
        target: InternalTarget,
        correlates_with: Optional[str] = None,
        # Optional dependency injection (used by tests).
        scheduler=None,
        canonicalizer_func: Optional[Callable] = None,
        canonicalizer_cron: Optional[str] = None,
    ) -> None:
        super().__init__(
            name, display_name=display_name, correlates_with=correlates_with,
        )
        if target not in ("locomo_worker", "canonicalizer"):
            raise ValueError(f"Unknown internal target: {target!r}")
        self._target: InternalTarget = target
        self._scheduler = scheduler
        self._canonicalizer_func = canonicalizer_func
        self._canonicalizer_cron = canonicalizer_cron

    @property
    def kind(self) -> ServiceKind:
        return "internal"

    # ── State ──

    async def is_running(self) -> bool:
        if self._target == "locomo_worker":
            return bool(runtime_flags.get("WORKER_ENABLED"))
        if self._target == "canonicalizer":
            return bool(runtime_flags.get("CANONICALIZER_ENABLED"))
        return False

    # ── Lifecycle ──

    async def start(self) -> None:
        try:
            if self._target == "locomo_worker":
                runtime_flags.set("WORKER_ENABLED", True)
            elif self._target == "canonicalizer":
                runtime_flags.set("CANONICALIZER_ENABLED", True)
                self._register_canonicalizer_job()
        except Exception as e:
            self._record_action("start", error=f"{type(e).__name__}: {e}")
            raise
        self._record_action("start")

    async def stop(self) -> None:
        try:
            if self._target == "locomo_worker":
                runtime_flags.set("WORKER_ENABLED", False)
            elif self._target == "canonicalizer":
                runtime_flags.set("CANONICALIZER_ENABLED", False)
                self._unregister_canonicalizer_job()
        except Exception as e:
            self._record_action("stop", error=f"{type(e).__name__}: {e}")
            raise
        self._record_action("stop")

    # ── Lazy singleton getters ──

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
