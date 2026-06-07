"""Controller ABC and ServiceState model shared by all service-control backends."""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Literal, Optional

from pydantic import BaseModel


ServiceKind = Literal["process", "docker", "internal", "remote"]


class ServiceState(BaseModel):
    """Snapshot of a single registered service's current state."""

    name: str
    display_name: str
    kind: ServiceKind
    correlates_with: Optional[str] = None

    running: bool = False
    transitioning: bool = False
    pid: Optional[int] = None

    last_action: Optional[Literal["start", "stop"]] = None
    last_action_at: Optional[float] = None
    last_error: Optional[str] = None


class Controller(ABC):
    """Each registered service entry owns one Controller instance.

    Controllers are not thread-safe on their own; the ServiceManager wraps
    every call in a per-service ``asyncio.Lock`` so start/stop/state never
    race against each other for the same name.
    """

    def __init__(
        self,
        name: str,
        *,
        display_name: str,
        correlates_with: Optional[str] = None,
    ) -> None:
        self.name = name
        self.display_name = display_name
        self.correlates_with = correlates_with
        self.last_action: Optional[str] = None
        self.last_action_at: Optional[float] = None
        self.last_error: Optional[str] = None

    @property
    @abstractmethod
    def kind(self) -> ServiceKind: ...

    @abstractmethod
    async def is_running(self) -> bool: ...

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    async def state(self, *, transitioning: bool = False) -> ServiceState:
        return ServiceState(
            name=self.name,
            display_name=self.display_name,
            kind=self.kind,
            correlates_with=self.correlates_with,
            running=await self.is_running(),
            transitioning=transitioning,
            pid=self._pid_hint(),
            last_action=self.last_action,
            last_action_at=self.last_action_at,
            last_error=self.last_error,
        )

    def _pid_hint(self) -> Optional[int]:
        """Overridden by ProcessController; other kinds return None."""
        return None

    def _record_action(self, action: str, error: Optional[str] = None) -> None:
        self.last_action = action
        self.last_action_at = time.time()
        self.last_error = error
