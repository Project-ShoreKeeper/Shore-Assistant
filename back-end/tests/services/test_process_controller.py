"""Tests for ProcessController — spawn, stop, stale-PID handling."""
import os
import sys
import time
from pathlib import Path

import pytest

from app.services.controllers.process import ProcessController


@pytest.fixture
def pid_dir(tmp_path: Path) -> Path:
    d = tmp_path / "pids"
    d.mkdir()
    return d


def _python_sleep_cmd(seconds: int = 30) -> str:
    """A start_cmd that spawns a long-lived Python process we can SIGTERM."""
    return f'"{sys.executable}" -c "import time; time.sleep({seconds})"'


@pytest.mark.asyncio
async def test_start_writes_pid_file_and_is_running_true(pid_dir):
    ctrl = ProcessController(
        "test-sleeper",
        display_name="test-sleeper",
        start_cmd=_python_sleep_cmd(20),
        pid_dir=pid_dir,
    )
    try:
        await ctrl.start()
        assert (pid_dir / "test-sleeper.pid").exists()
        assert await ctrl.is_running() is True
        assert ctrl.last_action == "start"
        assert ctrl.last_error is None
    finally:
        await ctrl.stop()


@pytest.mark.asyncio
async def test_start_when_already_running_raises(pid_dir):
    ctrl = ProcessController(
        "dup", display_name="dup",
        start_cmd=_python_sleep_cmd(15), pid_dir=pid_dir,
    )
    try:
        await ctrl.start()
        with pytest.raises(RuntimeError):
            await ctrl.start()
    finally:
        await ctrl.stop()


@pytest.mark.asyncio
async def test_stop_kills_process_and_clears_pid_file(pid_dir):
    ctrl = ProcessController(
        "killable", display_name="killable",
        start_cmd=_python_sleep_cmd(60),
        grace_seconds=2.0,
        pid_dir=pid_dir,
    )
    await ctrl.start()
    pid_file = pid_dir / "killable.pid"
    assert pid_file.exists()

    t0 = time.time()
    await ctrl.stop()
    elapsed = time.time() - t0

    assert not pid_file.exists()
    assert await ctrl.is_running() is False
    # grace + 2s slack
    assert elapsed < 6.0


@pytest.mark.asyncio
async def test_stop_when_not_running_is_noop(pid_dir):
    ctrl = ProcessController(
        "phantom", display_name="phantom",
        start_cmd=_python_sleep_cmd(5), pid_dir=pid_dir,
    )
    await ctrl.stop()  # nothing was started
    assert await ctrl.is_running() is False
    assert ctrl.last_action == "stop"


@pytest.mark.asyncio
async def test_stale_pid_file_is_cleaned_on_is_running_check(pid_dir):
    """If create_time mismatches, the file is treated as stale."""
    import json
    pid_file = pid_dir / "stale.pid"
    # Fake record: a real PID (our own) but wrong create_time.
    pid_file.write_text(json.dumps({
        "pid": os.getpid(),
        "create_time": 1.0,  # epoch 1970 — clearly mismatched
        "cmd": "fake",
    }))
    ctrl = ProcessController(
        "stale", display_name="stale",
        start_cmd="echo never", pid_dir=pid_dir,
    )
    assert await ctrl.is_running() is False
    assert not pid_file.exists()


@pytest.mark.asyncio
async def test_pid_hint_returns_recorded_pid(pid_dir):
    ctrl = ProcessController(
        "hinted", display_name="hinted",
        start_cmd=_python_sleep_cmd(10), pid_dir=pid_dir,
    )
    try:
        await ctrl.start()
        hint = ctrl._pid_hint()
        assert isinstance(hint, int)
        assert hint > 0
    finally:
        await ctrl.stop()
