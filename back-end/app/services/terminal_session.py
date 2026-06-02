"""Single PTY session wrapping pywinpty."""

import asyncio
import time
import uuid
from typing import Callable, Optional


class WinPtySession:

    def __init__(self, name: str, shell: str, cwd: str, on_output: Callable, on_closed: Callable):
        import winpty
        self.name = name
        self.session_id = uuid.uuid4().hex[:12]
        self.shell = shell
        self.cwd = cwd
        self.created_at = time.time()
        self.last_activity = time.time()
        self.on_output = on_output  # async callable(session, str)
        self.on_closed = on_closed  # async callable(session, reason, exit_code)
        self._buffer = bytearray()
        self._closed = False

        cmd_map = {"powershell": "powershell.exe", "pwsh": "pwsh", "cmd": "cmd.exe", "bash": "bash"}
        if shell not in cmd_map:
            raise ValueError(f"Unsupported shell: {shell}")
        self.pty = winpty.PtyProcess.spawn(cmd_map[shell], cwd=cwd, dimensions=(24, 80))
        self.pid = self.pty.pid
        self._read_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self):
        loop = asyncio.get_running_loop()
        while not self._closed:
            try:
                data = await loop.run_in_executor(None, self._read_chunk)
            except EOFError:
                break
            except Exception as e:
                print(f"[WinPtySession {self.name}] read error: {e}")
                break
            if not data:
                if not self.pty.isalive():
                    break
                await asyncio.sleep(0.05)
                continue
            self.last_activity = time.time()
            self._buffer.extend(data.encode("utf-8", errors="replace"))
            try:
                await self.on_output(self, data)
            except Exception as e:
                print(f"[WinPtySession {self.name}] on_output error: {e}")
        exit_code = None
        try:
            exit_code = self.pty.exitstatus
        except Exception:
            pass
        reason = "crash" if self.pty.isalive() is False and not self._closed else "user"
        self._closed = True
        try:
            await self.on_closed(self, reason, exit_code)
        except Exception:
            pass

    def _read_chunk(self) -> str:
        try:
            return self.pty.read(4096)
        except EOFError:
            raise
        except Exception:
            return ""

    async def wait_ready(self, timeout: float = 10.0):
        """Block until the shell has emitted its first prompt (contains '>') or timeout."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            snippet = self._buffer.decode("utf-8", errors="replace")
            if ">" in snippet:
                return
            await asyncio.sleep(0.1)

    async def write(self, data: str):
        if self._closed:
            raise RuntimeError("Session already closed")
        self.last_activity = time.time()
        self.pty.write(data)

    async def collect_output(self, wait_seconds: float) -> str:
        before = len(self._buffer)
        await asyncio.sleep(wait_seconds)
        return self._buffer[before:].decode("utf-8", errors="replace")

    async def resize(self, cols: int, rows: int):
        try:
            self.pty.setwinsize(rows, cols)
        except Exception:
            pass

    async def close(self, reason: str = "user"):
        if self._closed:
            return
        self._closed = True
        try:
            self.pty.terminate(force=True)
        except Exception:
            pass
