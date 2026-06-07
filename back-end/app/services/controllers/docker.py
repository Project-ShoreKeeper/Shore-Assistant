"""DockerController — start/stop a single docker-compose service.

Uses ``docker compose -f <file> {start|stop|up -d|ps} <service>`` as a subprocess.
``ps --format json`` is parsed to detect the current state.
"""
from __future__ import annotations

import asyncio
import json
from typing import Optional

from app.services.controllers.base import Controller, ServiceKind


_SUBPROCESS_TIMEOUT_SECONDS = 30.0


class DockerController(Controller):

    def __init__(
        self,
        name: str,
        *,
        display_name: str,
        compose_file: str,
        compose_service: str,
        use_up_on_start: bool = False,
        correlates_with: Optional[str] = None,
    ) -> None:
        super().__init__(
            name, display_name=display_name, correlates_with=correlates_with,
        )
        self._compose_file = compose_file
        self._compose_service = compose_service
        self._use_up_on_start = use_up_on_start

    @property
    def kind(self) -> ServiceKind:
        return "docker"

    async def _run_compose(self, *args: str) -> tuple[int, str, str]:
        cmd = ["docker", "compose", "-f", self._compose_file, *args]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=_SUBPROCESS_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError(
                f"docker compose {' '.join(args)} timed out after "
                f"{_SUBPROCESS_TIMEOUT_SECONDS}s"
            )
        return proc.returncode or 0, stdout.decode("utf-8", errors="replace"), \
               stderr.decode("utf-8", errors="replace")

    async def is_running(self) -> bool:
        try:
            rc, out, _err = await self._run_compose(
                "ps", "--format", "json", self._compose_service,
            )
        except RuntimeError:
            return False
        if rc != 0:
            return False
        for entry in _parse_compose_ps(out):
            state = (entry.get("State") or entry.get("state") or "").lower()
            if state == "running":
                return True
        return False

    async def start(self) -> None:
        action = "up" if self._use_up_on_start else "start"
        args = ["up", "-d", self._compose_service] if self._use_up_on_start \
            else ["start", self._compose_service]
        try:
            rc, _out, err = await self._run_compose(*args)
        except RuntimeError as e:
            self._record_action("start", error=str(e))
            raise
        if rc != 0:
            msg = err.strip() or f"docker compose {action} exited {rc}"
            self._record_action("start", error=msg)
            raise RuntimeError(msg)
        self._record_action("start")

    async def stop(self) -> None:
        try:
            rc, _out, err = await self._run_compose("stop", self._compose_service)
        except RuntimeError as e:
            self._record_action("stop", error=str(e))
            raise
        if rc != 0:
            msg = err.strip() or f"docker compose stop exited {rc}"
            self._record_action("stop", error=msg)
            raise RuntimeError(msg)
        self._record_action("stop")


def _parse_compose_ps(out: str) -> list[dict]:
    """Parse `docker compose ps --format json` output.

    Older docker compose v2 emits a single JSON array; newer versions emit
    one JSON object per line (JSONL). Tolerate both.
    """
    out = out.strip()
    if not out:
        return []
    # Try JSON-array first.
    try:
        parsed = json.loads(out)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        return [p for p in parsed if isinstance(p, dict)]
    if isinstance(parsed, dict):
        return [parsed]
    # Fall back to JSONL.
    entries: list[dict] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            entries.append(obj)
    return entries
