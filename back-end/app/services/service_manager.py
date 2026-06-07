"""ServiceManager — load services.yaml, dispatch start/stop/state to controllers.

A single ``ServiceManager`` instance is created at app startup. It reads the
registry from ``config/services.yaml`` (override path via env or constructor
arg). Missing file or parse error => empty registry; existing dashboard
behavior is preserved.

Each registered service has its own ``asyncio.Lock`` so two requests against
the same name serialize, while different services may transition in parallel.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Optional

import yaml

from app.services.controllers import (
    Controller,
    DockerController,
    InternalController,
    ProcessController,
    RemoteServiceController,
    ServiceState,
)


log = logging.getLogger(__name__)


class ServiceNotFound(Exception):
    pass


class ServiceConflict(Exception):
    """Raised on 409: already transitioning or already in desired state."""


class ServiceManager:

    DEFAULT_REGISTRY_PATH = Path("config/services.yaml")

    def __init__(self, registry_path: Optional[Path] = None) -> None:
        self._registry_path = registry_path or self.DEFAULT_REGISTRY_PATH
        self._controllers: dict[str, Controller] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._transitioning: set[str] = set()

    # ── Lifecycle ──

    def load(self) -> None:
        """Parse the registry file. Idempotent. Safe to call at startup."""
        self._controllers = {}
        self._locks = {}
        self._transitioning = set()

        if not self._registry_path.exists():
            log.info(
                "service_manager: %s missing, no services registered",
                self._registry_path,
            )
            return

        try:
            raw = yaml.safe_load(self._registry_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as e:
            log.error("service_manager: failed to read %s: %r", self._registry_path, e)
            return

        services = raw.get("services") or {}
        if not isinstance(services, dict):
            log.error("service_manager: top-level 'services' must be a mapping")
            return

        for name, entry in services.items():
            if not isinstance(name, str) or not isinstance(entry, dict):
                log.warning("service_manager: skipping invalid entry %r", name)
                continue
            try:
                self._controllers[name] = self._build(name, entry)
                self._locks[name] = asyncio.Lock()
            except Exception as e:
                log.error("service_manager: failed to build %r: %r", name, e)

        log.info(
            "service_manager: loaded %d services from %s",
            len(self._controllers), self._registry_path,
        )

    def _build(self, name: str, entry: dict[str, Any]) -> Controller:
        kind = entry.get("kind")
        display_name = entry.get("display_name") or name
        correlates_with = entry.get("correlates_with")
        if kind == "process":
            return ProcessController(
                name,
                display_name=display_name,
                correlates_with=correlates_with,
                start_cmd=entry["start_cmd"],
                cwd=entry.get("cwd"),
                env=entry.get("env"),
                grace_seconds=float(entry.get("grace_seconds", 10.0)),
            )
        if kind == "docker":
            return DockerController(
                name,
                display_name=display_name,
                correlates_with=correlates_with,
                compose_file=entry["compose_file"],
                compose_service=entry["compose_service"],
                use_up_on_start=bool(entry.get("use_up_on_start", False)),
            )
        if kind == "internal":
            return InternalController(
                name,
                display_name=display_name,
                correlates_with=correlates_with,
                target=entry["target"],
            )
        if kind == "remote":
            return RemoteServiceController(
                name,
                display_name=display_name,
                correlates_with=correlates_with,
                target=entry["target"],
            )
        raise ValueError(f"unknown kind: {kind!r}")

    # ── Introspection ──

    def names(self) -> list[str]:
        return list(self._controllers.keys())

    def has(self, name: str) -> bool:
        return name in self._controllers

    async def list_state(self) -> list[ServiceState]:
        out: list[ServiceState] = []
        for name, ctrl in self._controllers.items():
            out.append(await ctrl.state(transitioning=name in self._transitioning))
        return out

    async def get_state(self, name: str) -> ServiceState:
        ctrl = self._controllers.get(name)
        if ctrl is None:
            raise ServiceNotFound(name)
        return await ctrl.state(transitioning=name in self._transitioning)

    # ── Lifecycle dispatch ──
    #
    # The `transitioning` set is the synchronization primitive: read+add+discard
    # all happen without `await` between them, so they're atomic on a single
    # event loop. Two simultaneous start() callers can never both pass the
    # gate.

    async def start(self, name: str) -> None:
        ctrl = self._controllers.get(name)
        if ctrl is None:
            raise ServiceNotFound(name)
        if name in self._transitioning:
            raise ServiceConflict(f"{name} is already transitioning")
        self._transitioning.add(name)
        try:
            if await ctrl.is_running():
                raise ServiceConflict(f"{name} is already running")
            await ctrl.start()
        finally:
            self._transitioning.discard(name)

    async def stop(self, name: str) -> None:
        ctrl = self._controllers.get(name)
        if ctrl is None:
            raise ServiceNotFound(name)
        if name in self._transitioning:
            raise ServiceConflict(f"{name} is already transitioning")
        self._transitioning.add(name)
        try:
            if not await ctrl.is_running():
                raise ServiceConflict(f"{name} is not running")
            await ctrl.stop()
        finally:
            self._transitioning.discard(name)

    def schedule_start(self, name: str) -> asyncio.Task:
        """Fire-and-forget start. Validates synchronously (404/409), then
        runs the actual start in a background task. Used by /api/services/
        endpoints that want to return 202 immediately.
        """
        return self._schedule(name, action="start")

    def schedule_stop(self, name: str) -> asyncio.Task:
        return self._schedule(name, action="stop")

    def _schedule(self, name: str, action: str) -> asyncio.Task:
        ctrl = self._controllers.get(name)
        if ctrl is None:
            raise ServiceNotFound(name)
        if name in self._transitioning:
            raise ServiceConflict(f"{name} is already transitioning")
        self._transitioning.add(name)

        async def _runner() -> None:
            try:
                if action == "start":
                    if await ctrl.is_running():
                        ctrl._record_action("start", error="already running")
                        return
                    await ctrl.start()
                else:
                    if not await ctrl.is_running():
                        ctrl._record_action("stop", error="not running")
                        return
                    await ctrl.stop()
            except Exception as e:
                log.exception("%s failed for %s", action, name)
                # Controller usually records its own error; ensure something is set.
                if ctrl.last_error is None:
                    ctrl._record_action(action, error=f"{type(e).__name__}: {e}")
            finally:
                self._transitioning.discard(name)

        return asyncio.create_task(_runner())


service_manager = ServiceManager()
