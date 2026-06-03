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
