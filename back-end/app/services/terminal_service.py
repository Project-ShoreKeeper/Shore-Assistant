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
