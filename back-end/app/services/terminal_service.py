"""Terminal service: one-shot subprocess runner + PTY session pool."""

import asyncio
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


SHELL_INVOCATIONS = {
    "powershell": ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"],
    "pwsh": ["pwsh", "-NoLogo", "-NoProfile", "-Command"],
    "cmd": ["cmd.exe", "/c"],
    "bash": ["bash", "-c"],
}

# Shells that should use create_subprocess_shell (let the OS handle quoting)
# vs create_subprocess_exec (argv list passed directly).
# On Windows, cmd.exe /c with a command string as a single argv element
# does not correctly handle nested quotes; create_subprocess_shell uses
# the Windows CreateProcess API which handles the full command string natively.
_USE_SHELL_API = {"cmd", "powershell", "pwsh"}


class TerminalService:

    def __init__(
        self,
        whitelist,
        runs_dir: Path,
        audit_log_path: Path,
        default_cwd: str,
        oneshot_timeout: int = 60,
        max_output_bytes: int = 1_048_576,
        llm_preview_bytes: int = 8192,
    ):
        self.whitelist = whitelist
        self.runs_dir = Path(runs_dir)
        self.audit_log_path = Path(audit_log_path)
        self.default_cwd = default_cwd
        self.oneshot_timeout = oneshot_timeout
        self.max_output_bytes = max_output_bytes
        self.llm_preview_bytes = llm_preview_bytes
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        # Hook set by chat_ws to broadcast WS messages
        self.broadcast = None  # async callable(dict)
        self.confirm_timeout = 60
        self._pending_confirms: dict[str, asyncio.Future] = {}
        self.sessions: dict = {}
        self.session_idle_seconds = 30 * 60

    async def _broadcast(self, msg: dict):
        if self.broadcast:
            try:
                await self.broadcast(msg)
            except Exception:
                pass

    def _audit(self, entry: dict):
        entry["ts"] = datetime.now(timezone.utc).isoformat()
        with open(self.audit_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def resolve_confirm(self, request_id: str, decision: str) -> bool:
        fut = self._pending_confirms.pop(request_id, None)
        if fut and not fut.done():
            fut.set_result(decision)
            return True
        return False

    async def _request_confirm(self, command: str, shell: str, cwd: str, reason: str) -> str:
        request_id = uuid.uuid4().hex[:12]
        fut = asyncio.get_running_loop().create_future()
        self._pending_confirms[request_id] = fut
        await self._broadcast({
            "type": "terminal_confirm_request",
            "request_id": request_id,
            "command": command,
            "shell": shell,
            "cwd": cwd,
            "reason": reason,
        })
        try:
            return await asyncio.wait_for(fut, timeout=self.confirm_timeout)
        except asyncio.TimeoutError:
            self._pending_confirms.pop(request_id, None)
            return "deny"

    async def _on_session_output(self, session, data: str):
        await self._broadcast({
            "type": "terminal_session_output",
            "session_id": session.session_id,
            "data": data,
        })

    async def _on_session_closed(self, session, reason: str, exit_code):
        self.sessions.pop(session.name, None)
        await self._broadcast({
            "type": "terminal_session_closed",
            "session_id": session.session_id,
            "name": session.name,
            "reason": reason,
            "exit_code": exit_code,
        })
        self._audit({
            "kind": "session_closed", "name": session.name,
            "reason": reason, "exit_code": exit_code,
        })

    async def open_session(self, name: Optional[str], shell: str = "powershell", cwd: Optional[str] = None) -> dict:
        from app.services.terminal_session import WinPtySession
        cwd = cwd or self.default_cwd or os.getcwd()
        if not Path(cwd).is_dir():
            return {"error": f"CWD not found: {cwd}"}
        name = name or f"session-{len(self.sessions) + 1}"
        if name in self.sessions:
            return {"error": f"Session '{name}' already exists"}
        try:
            session = WinPtySession(name, shell, cwd, self._on_session_output, self._on_session_closed)
        except Exception as e:
            return {"error": f"Failed to open: {e}"}
        self.sessions[name] = session
        await session.wait_ready()
        await self._broadcast({
            "type": "terminal_session_opened",
            "session_id": session.session_id,
            "name": name, "shell": shell, "cwd": cwd, "pid": session.pid,
        })
        self._audit({
            "kind": "session_opened", "name": name,
            "shell": shell, "cwd": cwd, "pid": session.pid,
        })
        return {"session_id": session.session_id, "name": name, "message": f"Opened {shell} session '{name}'"}

    async def send_to_session(self, name: str, data: str, wait_seconds: float = 2.0) -> dict:
        session = self.sessions.get(name)
        if not session:
            return {"error": f"No terminal named '{name}'. Open one first.", "available": list(self.sessions.keys())}
        try:
            await session.write(data)
        except RuntimeError as e:
            return {"error": str(e)}
        raw = await session.collect_output(wait_seconds)
        return {
            "output": raw,
            "ansi_stripped": strip_ansi(raw),
            "exit_code_if_dead": None if session.pty.isalive() else session.pty.exitstatus,
        }

    def list_sessions(self) -> list:
        now = time.time()
        result = []
        for name, s in self.sessions.items():
            result.append({
                "name": name,
                "session_id": s.session_id,
                "shell": s.shell,
                "cwd": s.cwd,
                "idle_seconds": int(now - s.last_activity),
                "last_output_preview": s._buffer[-200:].decode("utf-8", errors="replace") if s._buffer else "",
            })
        return result

    async def close_session(self, name: str) -> dict:
        session = self.sessions.get(name)
        if not session:
            return {"closed": False, "message": f"No session named '{name}'"}
        await session.close(reason="llm")
        return {"closed": True, "message": f"Closed '{name}'"}

    async def shutdown_all(self):
        for name in list(self.sessions.keys()):
            try:
                await self.sessions[name].close(reason="shutdown")
            except Exception:
                pass

    async def run_oneshot(
        self,
        command: str,
        shell: str = "powershell",
        cwd: Optional[str] = None,
        timeout: Optional[int] = None,
        reason: str = "",
    ) -> dict:
        run_id = uuid.uuid4().hex[:12]
        cwd = cwd or self.default_cwd or os.getcwd()
        timeout = timeout or self.oneshot_timeout
        if not Path(cwd).is_dir():
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"CWD not found: {cwd}",
                "truncated": False,
                "duration_ms": 0,
                "log_path": "",
            }
        if shell not in SHELL_INVOCATIONS:
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Unknown shell: {shell}",
                "truncated": False,
                "duration_ms": 0,
                "log_path": "",
            }
        # Whitelist gate
        if self.whitelist:
            check = self.whitelist.check(command, shell)
            if check.decision == "block":
                self._audit({
                    "kind": "oneshot", "command": command, "shell": shell, "cwd": cwd,
                    "decision": "blocked", "reason": check.reason,
                })
                return {
                    "exit_code": -1, "stdout": "",
                    "stderr": f"Blocked: {check.reason}",
                    "truncated": False, "duration_ms": 0, "log_path": "",
                }
            if check.decision == "confirm":
                response = await self._request_confirm(command, shell, cwd, reason or check.reason)
                if response == "always_allow":
                    head = command.strip().split()[0] if command.strip() else ""
                    if head:
                        self.whitelist.add_user_allow(head)
                elif response != "approve":
                    self._audit({
                        "kind": "oneshot", "command": command, "shell": shell, "cwd": cwd,
                        "decision": "denied",
                    })
                    return {
                        "exit_code": -1, "stdout": "",
                        "stderr": "User denied execution",
                        "truncated": False, "duration_ms": 0, "log_path": "",
                    }
        argv = SHELL_INVOCATIONS[shell] + [command]

        await self._broadcast(
            {
                "type": "terminal_oneshot_start",
                "run_id": run_id,
                "command": command,
                "shell": shell,
                "cwd": cwd,
            }
        )
        start = time.time()
        try:
            if shell in _USE_SHELL_API:
                # Use the OS shell API so Windows CreateProcess handles quoting correctly.
                # For cmd: pass command directly (shell=True wraps with cmd /c internally).
                # For powershell/pwsh: prepend the shell prefix flags.
                if shell == "cmd":
                    shell_str = command
                else:
                    shell_str = " ".join(argv[:-1]) + " " + command
                proc = await asyncio.create_subprocess_shell(
                    shell_str,
                    cwd=cwd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            else:
                proc = await asyncio.create_subprocess_exec(
                    *argv,
                    cwd=cwd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
        except FileNotFoundError:
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Shell binary not found: {argv[0]}",
                "truncated": False,
                "duration_ms": 0,
                "log_path": "",
            }

        log_path = self.runs_dir / f"{run_id}.log"
        stdout_buf = bytearray()
        stderr_buf = bytearray()
        truncated = False

        async def pump(stream, label, buf):
            nonlocal truncated
            while True:
                line = await stream.readline()
                if not line:
                    return
                text = line.decode("utf-8", errors="replace")
                if len(buf) < self.max_output_bytes:
                    space = self.max_output_bytes - len(buf)
                    buf.extend(line[:space])
                    if len(buf) >= self.max_output_bytes:
                        truncated = True
                with open(log_path, "ab") as f:
                    f.write(line)
                await self._broadcast(
                    {
                        "type": "terminal_oneshot_output",
                        "run_id": run_id,
                        "stream": label,
                        "data": text,
                    }
                )

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    pump(proc.stdout, "stdout", stdout_buf),
                    pump(proc.stderr, "stderr", stderr_buf),
                ),
                timeout=timeout,
            )
            exit_code = await proc.wait()
            timed_out = False
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

        await self._broadcast(
            {
                "type": "terminal_oneshot_end",
                "run_id": run_id,
                "exit_code": exit_code,
                "duration_ms": duration_ms,
                "truncated": truncated,
            }
        )
        self._audit(
            {
                "kind": "oneshot",
                "run_id": run_id,
                "command": command,
                "shell": shell,
                "cwd": cwd,
                "decision": "executed",
                "exit_code": exit_code,
                "duration_ms": duration_ms,
                "reason": reason,
            }
        )
        return {
            "exit_code": exit_code,
            "stdout": stdout[: self.llm_preview_bytes],
            "stderr": stderr[: self.llm_preview_bytes],
            "truncated": truncated
            or len(stdout) > self.llm_preview_bytes
            or len(stderr) > self.llm_preview_bytes,
            "duration_ms": duration_ms,
            "log_path": str(log_path),
        }


async def _idle_reaper(service: "TerminalService"):
    while True:
        await asyncio.sleep(60)
        now = time.time()
        for name, s in list(service.sessions.items()):
            if now - s.last_activity > service.session_idle_seconds:
                try:
                    await s.close(reason="idle")
                except Exception:
                    pass


def _build_service() -> TerminalService:
    from app.core.config import settings
    from app.services.terminal_whitelist import WhitelistGuard
    default_cwd = settings.TERMINAL_DEFAULT_CWD or os.getcwd()
    guard = WhitelistGuard(
        default_path=settings.TERMINAL_WHITELIST_FILE,
        user_path=settings.TERMINAL_USER_WHITELIST_FILE,
    )
    svc = TerminalService(
        whitelist=guard,
        runs_dir=Path(settings.TERMINAL_RUNS_DIR),
        audit_log_path=Path(settings.TERMINAL_AUDIT_LOG),
        default_cwd=default_cwd,
        oneshot_timeout=settings.TERMINAL_ONESHOT_TIMEOUT_SECONDS,
        max_output_bytes=settings.TERMINAL_MAX_OUTPUT_BYTES,
        llm_preview_bytes=settings.TERMINAL_LLM_OUTPUT_PREVIEW_BYTES,
    )
    svc.confirm_timeout = settings.TERMINAL_CONFIRM_TIMEOUT_SECONDS
    svc.session_idle_seconds = settings.TERMINAL_SESSION_IDLE_MINUTES * 60
    return svc


terminal_service = _build_service()
