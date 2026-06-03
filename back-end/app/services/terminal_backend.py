"""Terminal execution backend abstraction.

The only backend is :class:`NodePtyBackend`, which delegates to the
shore-pty-service microservice over JSON-RPC. Whitelist gating, confirm flow,
audit logging, and broadcasting live in :class:`TerminalService` — backends only
execute.
"""

from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, Protocol


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
