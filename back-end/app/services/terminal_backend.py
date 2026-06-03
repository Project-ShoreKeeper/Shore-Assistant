"""Terminal execution backend abstraction.

Two implementations:
  - PywinptyBackend: runs commands locally via asyncio.subprocess + WinPtySession (legacy).
  - NodePtyBackend:  delegates to the shore-pty-service microservice over JSON-RPC.

Whitelist gating, confirm flow, audit logging, and broadcasting live in TerminalService
(not here). Backends only execute.
"""

import asyncio
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Optional, Protocol

from app.services.terminal_session import WinPtySession


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    truncated: bool


@dataclass
class SessionHandle:
    session_id: str
    pid: int


StreamCallback = Callable[[str, str], Awaitable[None]]  # (stream, data) for oneshot
SessionOutputCallback = Callable[[str, str], Awaitable[None]]  # (session_id, data)
SessionExitCallback = Callable[[str, Optional[int], str], Awaitable[None]]  # (session_id, exit_code, reason)


class TerminalBackend(Protocol):

    async def run_oneshot_exec(
        self,
        run_id: str,
        command: str,
        shell: str,
        cwd: str,
        timeout: int,
        on_output: StreamCallback,
    ) -> ExecResult: ...

    async def open_session_exec(
        self,
        session_id: str,
        name: str,
        shell: str,
        cwd: str,
        cols: int,
        rows: int,
        on_output: SessionOutputCallback,
        on_exit: SessionExitCallback,
    ) -> SessionHandle: ...

    async def send_to_session_exec(self, session_id: str, data: str) -> None: ...

    async def resize_session_exec(self, session_id: str, cols: int, rows: int) -> None: ...

    async def close_session_exec(self, session_id: str) -> None: ...

    async def shutdown(self) -> None: ...


SHELL_INVOCATIONS = {
    "powershell": ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"],
    "pwsh": ["pwsh", "-NoLogo", "-NoProfile", "-Command"],
    "cmd": ["cmd.exe", "/c"],
    "bash": ["bash", "-c"],
}

_USE_SHELL_API = {"cmd", "powershell", "pwsh"}


class PywinptyBackend:

    def __init__(self, max_output_bytes: int):
        self.max_output_bytes = max_output_bytes
        self.sessions: dict[str, WinPtySession] = {}

    async def run_oneshot_exec(self, run_id, command, shell, cwd, timeout, on_output) -> ExecResult:
        if shell not in SHELL_INVOCATIONS:
            return ExecResult(-1, "", f"Unknown shell: {shell}", 0, False)
        argv = SHELL_INVOCATIONS[shell] + [command]
        start = time.time()
        try:
            if shell in _USE_SHELL_API:
                if shell == "cmd":
                    shell_str = command
                else:
                    shell_str = " ".join(argv[:-1]) + " " + command
                proc = await asyncio.create_subprocess_shell(
                    shell_str, cwd=cwd,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
            else:
                proc = await asyncio.create_subprocess_exec(
                    *argv, cwd=cwd,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
        except FileNotFoundError:
            return ExecResult(-1, "", f"Shell binary not found: {argv[0]}", 0, False)

        stdout_buf = bytearray()
        stderr_buf = bytearray()
        truncated = False

        async def pump(stream, label, buf):
            nonlocal truncated
            while True:
                line = await stream.readline()
                if not line:
                    return
                if len(buf) < self.max_output_bytes:
                    space = self.max_output_bytes - len(buf)
                    buf.extend(line[:space])
                    if len(buf) >= self.max_output_bytes:
                        truncated = True
                await on_output(label, line.decode("utf-8", errors="replace"))

        timed_out = False
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    pump(proc.stdout, "stdout", stdout_buf),
                    pump(proc.stderr, "stderr", stderr_buf),
                ),
                timeout=timeout,
            )
            exit_code = await proc.wait()
        except asyncio.TimeoutError:
            timed_out = True
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()
            exit_code = -1

        duration_ms = int((time.time() - start) * 1000)
        stdout = stdout_buf.decode("utf-8", errors="replace")
        stderr = stderr_buf.decode("utf-8", errors="replace")
        if timed_out:
            stderr = (stderr + f"\n[Timed out after {timeout}s]").strip()
        return ExecResult(exit_code, stdout, stderr, duration_ms, truncated)

    async def open_session_exec(self, session_id, name, shell, cwd, cols, rows, on_output, on_exit) -> SessionHandle:
        async def _on_output(session, data):
            await on_output(session_id, data)
        async def _on_closed(session, reason, exit_code):
            self.sessions.pop(session_id, None)
            await on_exit(session_id, exit_code, reason)

        session = WinPtySession(name, shell, cwd, _on_output, _on_closed)
        self.sessions[session_id] = session
        await session.wait_ready()
        return SessionHandle(session_id=session_id, pid=session.pid)

    async def send_to_session_exec(self, session_id, data):
        s = self.sessions.get(session_id)
        if not s:
            raise RuntimeError(f"session not found: {session_id}")
        await s.write(data)

    async def resize_session_exec(self, session_id, cols, rows):
        s = self.sessions.get(session_id)
        if s:
            await s.resize(cols, rows)

    async def close_session_exec(self, session_id):
        s = self.sessions.get(session_id)
        if s:
            await s.close(reason="user")

    async def shutdown(self):
        for sid in list(self.sessions.keys()):
            try:
                await self.sessions[sid].close(reason="shutdown")
            except Exception:
                pass


from app.services.node_pty_client import NodePtyClient, NodePtyRpcError


class NodePtyBackend:

    def __init__(self, client: NodePtyClient):
        self.client = client
        self._session_callbacks: dict[str, tuple] = {}
        self._oneshot_callbacks: dict[str, tuple] = {}
        self.client.on_notification(self._on_notification)
        self.client.on_disconnect(self._on_disconnect)

    async def _on_disconnect(self):
        for sid, (_, on_exit) in list(self._session_callbacks.items()):
            try:
                await on_exit(sid, None, "node_disconnect")
            except Exception:
                pass
        self._session_callbacks.clear()
        self._oneshot_callbacks.clear()

    async def _on_notification(self, method: str, params: dict):
        if method == "session.output":
            cb = self._session_callbacks.get(params["session_id"])
            if cb:
                on_output, _ = cb
                await on_output(params["session_id"], params["data"])
        elif method == "session.exit":
            sid = params["session_id"]
            cb = self._session_callbacks.pop(sid, None)
            if cb:
                _, on_exit = cb
                await on_exit(sid, params.get("exit_code"), params.get("reason", "natural"))
        elif method == "session.output_dropped":
            cb = self._session_callbacks.get(params["session_id"])
            if cb:
                on_output, _ = cb
                await on_output(params["session_id"], f"\n[Output dropped: {params['dropped_bytes']} bytes]\n")
        elif method == "oneshot.output":
            cb = self._oneshot_callbacks.get(params["run_id"])
            if cb:
                on_output, _ = cb
                await on_output(params["stream"], params["data"])

    async def run_oneshot_exec(self, run_id, command, shell, cwd, timeout, on_output) -> ExecResult:
        stdout_buf: list[str] = []
        stderr_buf: list[str] = []

        async def _on_out(stream, data):
            if stream == "stdout":
                stdout_buf.append(data)
            else:
                stderr_buf.append(data)
            await on_output(stream, data)

        self._oneshot_callbacks[run_id] = (_on_out, None)
        try:
            res = await self.client.call("oneshot.run", {
                "run_id": run_id,
                "command": command,
                "shell": shell,
                "cwd": cwd,
                "timeout_ms": timeout * 1000,
            }, timeout=timeout + 30)
        except NodePtyRpcError as e:
            return ExecResult(-1, "", f"Node error: {e.message}", 0, False)
        finally:
            self._oneshot_callbacks.pop(run_id, None)

        stdout = "".join(stdout_buf)
        stderr = "".join(stderr_buf)
        if res.get("timed_out"):
            stderr = (stderr + f"\n[Timed out after {timeout}s]").strip()
        return ExecResult(
            exit_code=res["exit_code"],
            stdout=stdout,
            stderr=stderr,
            duration_ms=res["duration_ms"],
            truncated=False,
        )

    async def open_session_exec(self, session_id, name, shell, cwd, cols, rows, on_output, on_exit) -> SessionHandle:
        self._session_callbacks[session_id] = (on_output, on_exit)
        try:
            res = await self.client.call("session.open", {
                "session_id": session_id,
                "name": name,
                "shell": shell,
                "cwd": cwd,
                "cols": cols,
                "rows": rows,
            })
        except NodePtyRpcError:
            self._session_callbacks.pop(session_id, None)
            raise
        return SessionHandle(session_id=res["session_id"], pid=res["pid"])

    async def send_to_session_exec(self, session_id, data):
        await self.client.call("session.send", {"session_id": session_id, "data": data})

    async def resize_session_exec(self, session_id, cols, rows):
        await self.client.call("session.resize", {"session_id": session_id, "cols": cols, "rows": rows})

    async def close_session_exec(self, session_id):
        try:
            await self.client.call("session.close", {"session_id": session_id})
        except NodePtyRpcError:
            pass
        self._session_callbacks.pop(session_id, None)

    async def shutdown(self):
        await self.client.close()
