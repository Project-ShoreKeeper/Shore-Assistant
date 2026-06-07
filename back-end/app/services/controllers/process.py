"""ProcessController — spawn and stop long-lived OS processes (Windows).

Identity defense
----------------
A PID alone is unsafe — Windows reuses PIDs aggressively. We persist
``(pid, create_time)`` in the PID file. On every ``is_running`` check, we
verify both that ``psutil.pid_exists(pid)`` AND that ``psutil.Process(pid)
.create_time()`` matches what we recorded. Mismatch => the file is stale,
silently delete it and report ``running=False``.
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping, Optional

import psutil

from app.services.controllers.base import Controller, ServiceKind


_PID_DIR = Path("data/pids")


def _is_windows() -> bool:
    return os.name == "nt"


class ProcessController(Controller):

    def __init__(
        self,
        name: str,
        *,
        display_name: str,
        start_cmd: str,
        cwd: Optional[str] = None,
        env: Optional[Mapping[str, str]] = None,
        grace_seconds: float = 10.0,
        correlates_with: Optional[str] = None,
        pid_dir: Optional[Path] = None,
        pre_stop_cmd: Optional[str] = None,
    ) -> None:
        super().__init__(
            name, display_name=display_name, correlates_with=correlates_with,
        )
        self._start_cmd = start_cmd
        self._cwd = cwd
        self._env = dict(env or {})
        self._grace_seconds = max(0.5, float(grace_seconds))
        self._pid_dir = pid_dir or _PID_DIR
        self._pre_stop_cmd = pre_stop_cmd

    @property
    def kind(self) -> ServiceKind:
        return "process"

    def _pid_file(self) -> Path:
        return self._pid_dir / f"{self.name}.pid"

    def _read_pid_record(self) -> Optional[dict[str, Any]]:
        pid_file = self._pid_file()
        if not pid_file.exists():
            return None
        try:
            return json.loads(pid_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _write_pid_record(self, pid: int, create_time: float) -> None:
        self._pid_dir.mkdir(parents=True, exist_ok=True)
        self._pid_file().write_text(
            json.dumps({"pid": pid, "create_time": create_time, "cmd": self._start_cmd}),
            encoding="utf-8",
        )

    def _delete_pid_file(self) -> None:
        try:
            self._pid_file().unlink(missing_ok=True)
        except OSError:
            pass

    def _process_matches_record(self, record: dict[str, Any]) -> Optional[psutil.Process]:
        pid = record.get("pid")
        expected_ct = record.get("create_time")
        if not isinstance(pid, int) or not isinstance(expected_ct, (int, float)):
            return None
        if not psutil.pid_exists(pid):
            return None
        try:
            proc = psutil.Process(pid)
            actual_ct = proc.create_time()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None
        if abs(actual_ct - float(expected_ct)) > 1.0:
            return None
        return proc

    def _live_process(self) -> Optional[psutil.Process]:
        record = self._read_pid_record()
        if record is None:
            return None
        proc = self._process_matches_record(record)
        if proc is None:
            # Stale file — clean up so the next probe is fast.
            self._delete_pid_file()
            return None
        return proc

    async def is_running(self) -> bool:
        return self._live_process() is not None

    def _pid_hint(self) -> Optional[int]:
        record = self._read_pid_record()
        if record is None:
            return None
        pid = record.get("pid")
        return pid if isinstance(pid, int) else None

    async def start(self) -> None:
        if await self.is_running():
            raise RuntimeError(f"{self.name} is already running")

        merged_env = {**os.environ, **self._env}
        loop = asyncio.get_event_loop()

        def _spawn() -> subprocess.Popen:
            kwargs: dict[str, Any] = {
                "cwd": self._cwd,
                "env": merged_env,
                "shell": True,
                "close_fds": True,
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
            if _is_windows():
                kwargs["creationflags"] = (
                    subprocess.DETACHED_PROCESS
                    | subprocess.CREATE_NEW_PROCESS_GROUP
                )
            else:
                kwargs["start_new_session"] = True
            return subprocess.Popen(self._start_cmd, **kwargs)

        try:
            proc = await loop.run_in_executor(None, _spawn)
        except Exception as e:
            self._record_action("start", error=f"{type(e).__name__}: {e}")
            raise

        # The shell wrapper PID is what subprocess gives us. Track via psutil
        # so we can verify create_time on later probes.
        try:
            psproc = psutil.Process(proc.pid)
            create_time = psproc.create_time()
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            self._record_action("start", error=f"pid lookup failed: {e!r}")
            raise

        self._write_pid_record(proc.pid, create_time)
        self._record_action("start")
        print(f"[ProcessController] {self.name} spawned pid={proc.pid}")

    async def stop(self) -> None:
        live = self._live_process()
        if live is None:
            # Nothing to stop. Treat as success so the UI converges.
            self._delete_pid_file()
            self._record_action("stop")
            return

        loop = asyncio.get_event_loop()

        # Snapshot the descendant tree *now*. With shell=True on Windows, the
        # tracked PID is a cmd.exe wrapper; the real workload (npm.cmd, node,
        # wsl.exe, ...) lives below it. If the wrapper dies in Step 1, its
        # children get reparented and we lose the ability to query them by
        # walking from the wrapper. Capturing the snapshot up front lets
        # Step 3 force-kill orphans by PID regardless.
        try:
            tree_descendants = live.children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            tree_descendants = []
        full_tree: list[psutil.Process] = [live] + tree_descendants

        # Step 0: optional pre-stop. Used when CTRL_BREAK_EVENT to the shell
        # wrapper can't reach the real target — e.g. a llama-server running
        # inside WSL, where we need `wsl pkill` to deliver SIGTERM directly.
        # Best-effort: failures are logged but don't abort the stop flow.
        if self._pre_stop_cmd:
            await self._run_pre_stop()

        # Step 1: graceful — SIGTERM / CTRL_BREAK_EVENT.
        try:
            await loop.run_in_executor(None, lambda: self._send_term(live))
        except Exception as e:
            self._record_action("stop", error=f"term failed: {type(e).__name__}: {e}")
            # Continue to kill — best effort.

        # Step 2: wait up to grace_seconds for the whole tree to exit.
        def _wait_tree() -> list[psutil.Process]:
            _, still_alive = psutil.wait_procs(full_tree, timeout=self._grace_seconds)
            return still_alive

        try:
            survivors = await loop.run_in_executor(None, _wait_tree)
        except Exception as e:
            self._record_action("stop", error=f"wait failed: {type(e).__name__}: {e}")
            survivors = [p for p in full_tree if p.is_running()]

        # Step 3: SIGKILL the survivors (descendants + wrapper).
        for p in survivors:
            try:
                p.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                self._record_action("stop", error=f"kill failed pid={p.pid}: {e!r}")

        self._delete_pid_file()
        self._record_action("stop")
        print(f"[ProcessController] {self.name} stopped")

    async def _run_pre_stop(self) -> None:
        merged_env = {**os.environ, **self._env}
        loop = asyncio.get_event_loop()

        def _run() -> subprocess.CompletedProcess:
            return subprocess.run(
                self._pre_stop_cmd,
                shell=True,
                cwd=self._cwd,
                env=merged_env,
                capture_output=True,
                text=True,
                timeout=self._grace_seconds,
            )

        try:
            result = await loop.run_in_executor(None, _run)
            if result.returncode != 0:
                print(
                    f"[ProcessController] {self.name} pre_stop returned "
                    f"{result.returncode}: {result.stderr.strip()}"
                )
        except subprocess.TimeoutExpired:
            print(
                f"[ProcessController] {self.name} pre_stop timed out after "
                f"{self._grace_seconds}s"
            )
        except Exception as e:
            print(f"[ProcessController] {self.name} pre_stop failed: {e!r}")

    def _send_term(self, proc: psutil.Process) -> None:
        if _is_windows():
            try:
                os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
                return
            except (OSError, AttributeError):
                # CTRL_BREAK can't be delivered to a DETACHED_PROCESS without a
                # console. Don't `terminate()` here — that kills only the
                # cmd.exe wrapper and orphans its descendants (npm.cmd → node,
                # wsl.exe, etc.). Step 3's snapshot-based tree kill handles it.
                return
        proc.terminate()
