"""RemoteServiceController: controls a remote service via shore-ai-supervisor."""
from __future__ import annotations

from typing import Optional

from app.services.controllers.base import Controller, ServiceKind


class RemoteServiceController(Controller):
    def __init__(
        self,
        name: str,
        *,
        display_name: str,
        target: str,
        correlates_with: Optional[str] = None,
        supervisor_client=None,
    ) -> None:
        super().__init__(
            name,
            display_name=display_name,
            correlates_with=correlates_with,
        )
        self._target = target
        self._sup = supervisor_client

    @property
    def kind(self) -> ServiceKind:
        return "remote"

    def _client(self):
        if self._sup is not None:
            return self._sup
        from app.services.ai_client.supervisor import supervisor_client

        return supervisor_client

    async def is_running(self) -> bool:
        st = await self._client().status(self._target)
        return st.running

    async def start(self) -> None:
        try:
            await self._client().start(self._target)
        except Exception as e:
            self._record_action("start", error=f"{type(e).__name__}: {e}")
            raise
        self._record_action("start")

    async def stop(self) -> None:
        try:
            await self._client().stop(self._target)
        except Exception as e:
            self._record_action("stop", error=f"{type(e).__name__}: {e}")
            raise
        self._record_action("stop")
