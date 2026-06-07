"""Supervisor handler: shells docker compose for allowed targets."""
from __future__ import annotations

import asyncio
from typing import Iterable

import grpc

from shore_supervisor._pb import supervisor_pb2, supervisor_pb2_grpc


class SupervisorHandler(supervisor_pb2_grpc.SupervisorServicer):
    def __init__(self, compose_file: str, allowed_targets: Iterable[str]):
        self.compose_file = compose_file
        self.allowed = set(allowed_targets)

    async def _compose(self, *args: str) -> tuple[str, str, int]:
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "compose",
            "-f",
            self.compose_file,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        return out.decode(), err.decode(), proc.returncode or 0

    async def _check(self, target: str, context) -> None:
        if target not in self.allowed:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                f"unknown target {target!r}",
            )

    async def Start(self, request, context):
        await self._check(request.target, context)
        out, err, rc = await self._compose("start", request.target)
        if rc != 0:
            out2, err2, rc2 = await self._compose("up", "-d", request.target)
            if rc2 != 0:
                return supervisor_pb2.ActionResponse(
                    ok=False,
                    detail=(err2 or err or "start failed").strip(),
                )
            return supervisor_pb2.ActionResponse(
                ok=True,
                detail=out2.strip() or "created",
            )
        return supervisor_pb2.ActionResponse(
            ok=True,
            detail=out.strip() or "started",
        )

    async def Stop(self, request, context):
        await self._check(request.target, context)
        out, err, rc = await self._compose("stop", request.target)
        if rc != 0:
            return supervisor_pb2.ActionResponse(
                ok=False,
                detail=(err or "stop failed").strip(),
            )
        return supervisor_pb2.ActionResponse(
            ok=True,
            detail=out.strip() or "stopped",
        )

    async def Status(self, request, context):
        await self._check(request.target, context)
        out, err, rc = await self._compose("ps", "-q", request.target)
        if rc != 0:
            return supervisor_pb2.StatusResponse(
                running=False,
                container_id="",
                state=err.strip(),
            )
        cid = (out or "").strip()
        return supervisor_pb2.StatusResponse(
            running=bool(cid),
            container_id=cid,
            state="running" if cid else "stopped",
        )
