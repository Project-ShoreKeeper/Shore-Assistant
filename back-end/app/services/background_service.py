"""Detached background process manager — for long-running services like
filebrowser, dev servers, watchers.

Spawns processes WITHOUT a console window (Windows: ``CREATE_NO_WINDOW``;
POSIX: ``start_new_session``) and tracks them so they can be listed / stopped /
log-tailed. Combined stdout+stderr is redirected to a per-service log file under
``BACKGROUND_SERVICES_LOG_DIR``.

Whitelist gating + confirm flow live in :meth:`TerminalService.start_background`;
this module only executes.
"""

import os
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


SHELL_ARGV = {
    "powershell": ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"],
    "pwsh": ["pwsh", "-NoLogo", "-NoProfile", "-Command"],
    "cmd": ["cmd.exe", "/c"],
    "bash": ["bash", "-c"],
}


def _platform_creationflags() -> int:
    if sys.platform != "win32":
        return 0
    # CREATE_NO_WINDOW: child gets no console window (suppresses the PowerShell
    # popup that Start-Process would otherwise create).
    # CREATE_NEW_PROCESS_GROUP: Ctrl+C in the back-end console does not cascade.
    return subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP


def _kill_process_tree(pid: int) -> None:
    """Kill the process and every descendant.

    On Windows, ``proc.terminate()`` only kills the immediate process — when the
    tracked PID is a shell wrapper (powershell/cmd) that spawned the real service,
    the service is orphaned and keeps running. ``taskkill /T /F`` walks the
    parent-child tree maintained by Windows and force-kills every descendant.

    On POSIX we set ``start_new_session=True`` at spawn so the child is the
    leader of its own process group; ``os.killpg`` then signals every member.
    """
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(pid)],
            capture_output=True, check=False,
        )
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except ProcessLookupError:
        pass


@dataclass
class ServiceEntry:
    service_id: str
    name: str
    command: str
    shell: str
    cwd: str
    started_at: float
    log_path: str
    proc: subprocess.Popen = field(repr=False)

    @property
    def pid(self) -> int:
        return self.proc.pid

    @property
    def alive(self) -> bool:
        return self.proc.poll() is None


class BackgroundServiceManager:

    def __init__(self, log_dir: Path):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.services: dict[str, ServiceEntry] = {}

    def _reap(self) -> None:
        """Drop entries for processes that have exited on their own."""
        for name, entry in list(self.services.items()):
            if not entry.alive:
                self.services.pop(name, None)

    def start(
        self,
        name: str,
        command: str,
        shell: str = "powershell",
        cwd: Optional[str] = None,
    ) -> dict:
        self._reap()
        if name in self.services:
            return {
                "error": f"Service '{name}' already running (pid={self.services[name].pid}). "
                         f"Call stop_background_service first if you want to restart it."
            }
        argv_prefix = SHELL_ARGV.get(shell)
        if not argv_prefix:
            return {"error": f"Unsupported shell: {shell}"}
        cwd = cwd or os.getcwd()
        if not Path(cwd).is_dir():
            return {"error": f"CWD not found: {cwd}"}

        service_id = uuid.uuid4().hex[:12]
        log_path = self.log_dir / f"{name}-{service_id}.log"
        log_f = open(log_path, "ab", buffering=0)

        try:
            proc = subprocess.Popen(
                argv_prefix + [command],
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                creationflags=_platform_creationflags(),
                start_new_session=(sys.platform != "win32"),
                close_fds=True,
            )
        except FileNotFoundError as e:
            log_f.close()
            return {"error": f"Shell binary not found: {argv_prefix[0]} ({e})"}
        except Exception as e:
            log_f.close()
            return {"error": f"Failed to spawn: {e}"}

        entry = ServiceEntry(
            service_id=service_id,
            name=name,
            command=command,
            shell=shell,
            cwd=cwd,
            started_at=time.time(),
            log_path=str(log_path),
            proc=proc,
        )
        self.services[name] = entry
        return {
            "service_id": service_id,
            "name": name,
            "pid": proc.pid,
            "log_path": str(log_path),
            "message": f"Started '{name}' (pid={proc.pid}). "
                       f"Tail logs with get_background_service_logs('{name}').",
        }

    def list(self) -> list[dict]:
        self._reap()
        now = time.time()
        return [
            {
                "name": e.name,
                "service_id": e.service_id,
                "pid": e.pid,
                "command": e.command,
                "shell": e.shell,
                "cwd": e.cwd,
                "uptime_seconds": int(now - e.started_at),
                "log_path": e.log_path,
            }
            for e in self.services.values()
        ]

    def stop(self, name: str) -> dict:
        entry = self.services.get(name)
        if not entry:
            return {"stopped": False, "message": f"No service named '{name}'"}
        if not entry.alive:
            self.services.pop(name, None)
            return {"stopped": True, "message": f"Service '{name}' had already exited"}
        pid = entry.pid
        try:
            _kill_process_tree(pid)
            try:
                entry.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # taskkill /F should have killed it; belt-and-suspenders.
                entry.proc.kill()
                try:
                    entry.proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
        except Exception as e:
            return {"stopped": False, "message": f"Failed to stop: {e}"}
        self.services.pop(name, None)
        return {"stopped": True, "message": f"Stopped '{name}' (pid={pid}) and its child processes"}

    def tail_log(self, name: str, lines: int = 50) -> str:
        entry = self.services.get(name)
        if not entry:
            return f"No service named '{name}'"
        try:
            with open(entry.log_path, "rb") as f:
                content = f.read().decode("utf-8", errors="replace")
        except FileNotFoundError:
            return ""
        return "\n".join(content.splitlines()[-lines:])

    def shutdown_all(self) -> None:
        for name in list(self.services.keys()):
            try:
                self.stop(name)
            except Exception:
                pass


def _build_manager() -> BackgroundServiceManager:
    from app.core.config import settings
    return BackgroundServiceManager(log_dir=Path(settings.BACKGROUND_SERVICES_LOG_DIR))


background_service_manager = _build_manager()
