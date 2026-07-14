"""BackgroundServiceManager unit tests — spawn real, lightweight Python
subprocesses to exercise start/list/stop/tail-log without mocking subprocess."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.services.background_service import BackgroundServiceManager


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "csv"],
            capture_output=True, text=True, check=False,
        )
        return f'"{pid}"' in result.stdout
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


@pytest.fixture
def mgr(tmp_path: Path) -> BackgroundServiceManager:
    m = BackgroundServiceManager(log_dir=tmp_path / "services")
    yield m
    m.shutdown_all()


def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_start_spawns_process_and_lists_it(mgr: BackgroundServiceManager, tmp_path: Path):
    command = f'{sys.executable} -c "import time; time.sleep(30)"'
    result = mgr.start(name="sleeper", command=command, shell="cmd", cwd=str(tmp_path))
    assert "pid" in result, result
    assert result["name"] == "sleeper"

    listed = mgr.list()
    assert len(listed) == 1
    assert listed[0]["name"] == "sleeper"
    assert listed[0]["pid"] == result["pid"]
    assert Path(result["log_path"]).is_file()


def test_duplicate_name_rejected(mgr: BackgroundServiceManager, tmp_path: Path):
    command = f'{sys.executable} -c "import time; time.sleep(30)"'
    mgr.start(name="dup", command=command, shell="cmd", cwd=str(tmp_path))
    second = mgr.start(name="dup", command=command, shell="cmd", cwd=str(tmp_path))
    assert "error" in second
    assert "already running" in second["error"]


def test_unsupported_shell_rejected(mgr: BackgroundServiceManager, tmp_path: Path):
    result = mgr.start(name="bogus", command="echo hi", shell="zsh", cwd=str(tmp_path))
    assert "error" in result
    assert "Unsupported shell" in result["error"]


def test_missing_cwd_rejected(mgr: BackgroundServiceManager, tmp_path: Path):
    result = mgr.start(
        name="bogus", command="echo hi", shell="cmd",
        cwd=str(tmp_path / "does-not-exist"),
    )
    assert "error" in result
    assert "CWD not found" in result["error"]


def test_stop_terminates_process(mgr: BackgroundServiceManager, tmp_path: Path):
    command = f'{sys.executable} -c "import time; time.sleep(30)"'
    started = mgr.start(name="killme", command=command, shell="cmd", cwd=str(tmp_path))
    pid = started["pid"]

    result = mgr.stop("killme")
    assert result["stopped"] is True
    assert "killme" not in mgr.services
    # PID should no longer be in the manager's index
    assert all(s["pid"] != pid for s in mgr.list())


def test_stop_kills_child_processes(mgr: BackgroundServiceManager, tmp_path: Path):
    """Shell wrappers spawn the real service as a child. stop() must terminate
    the whole process tree — otherwise the service (e.g. filebrowser) survives
    after the shell wrapper is killed (regression: original 'stop only removes
    from registry' bug)."""
    pidfile = tmp_path / "child_pid.txt"
    script = tmp_path / "service.py"
    script.write_text(
        "import os, time\n"
        f"open(r'{pidfile}', 'w').write(str(os.getpid()))\n"
        "time.sleep(120)\n"
    )
    # cmd.exe spawns python.exe (the "service"). The tracked Popen handle is
    # cmd.exe; the actual long-running process is the python.exe child.
    # Avoid quoting (cmd /c mangles nested quotes); rely on tmp_path having no spaces.
    if " " in str(script) or " " in sys.executable:
        pytest.skip("test command does not handle spaces in paths")
    shell_name = "cmd" if sys.platform == "win32" else "bash"
    if sys.platform == "win32":
        command = f"{sys.executable} {script}"
    else:
        # Trailing command prevents bash from optimizing with exec,
        # ensuring Python runs as a separate child process.
        command = f"{sys.executable} {script} && echo done"
    started = mgr.start(name="tree", command=command, shell=shell_name, cwd=str(tmp_path))
    parent_pid = started["pid"]

    assert _wait_until(
        lambda: pidfile.exists() and pidfile.read_text().strip().isdigit(),
        timeout=10.0,
    ), "service never wrote its pid"
    child_pid = int(pidfile.read_text().strip())
    assert child_pid != parent_pid, "child should be a separate process from the shell wrapper"
    assert _pid_alive(child_pid), "child service should be running before stop()"

    result = mgr.stop("tree")
    assert result["stopped"] is True

    assert _wait_until(lambda: not _pid_alive(child_pid), timeout=5.0), (
        f"child service pid={child_pid} survived stop() — process tree not killed"
    )


def test_stop_unknown_name_returns_message(mgr: BackgroundServiceManager):
    result = mgr.stop("ghost")
    assert result["stopped"] is False
    assert "ghost" in result["message"]


def test_self_exiting_process_reaped_from_list(mgr: BackgroundServiceManager, tmp_path: Path):
    # Process exits almost immediately.
    command = f'{sys.executable} -c "print(\\"done\\")"'
    mgr.start(name="quick", command=command, shell="cmd", cwd=str(tmp_path))

    # Poll until it disappears from list() (which calls _reap()).
    assert _wait_until(lambda: all(s["name"] != "quick" for s in mgr.list()), timeout=5.0), (
        "self-exiting process should have been reaped from list()"
    )


def test_tail_log_returns_recent_output(mgr: BackgroundServiceManager, tmp_path: Path):
    # Use the simplest cross-platform shell command for the configured shell.
    if sys.platform == "win32":
        command = "echo hello-bg-log"
        shell = "cmd"
    else:
        command = "echo hello-bg-log"
        shell = "bash"
    mgr.start(name="echoer", command=command, shell=shell, cwd=str(tmp_path))

    # Wait until log file has data.
    entry = mgr.services["echoer"]
    log_path = Path(entry.log_path)
    assert _wait_until(lambda: log_path.exists() and log_path.stat().st_size > 0, timeout=5.0), (
        "log file should have been written to"
    )

    log = mgr.tail_log("echoer", lines=10)
    assert "hello-bg-log" in log


def test_shutdown_all_kills_running_services(mgr: BackgroundServiceManager, tmp_path: Path):
    command = f'{sys.executable} -c "import time; time.sleep(30)"'
    mgr.start(name="a", command=command, shell="cmd", cwd=str(tmp_path))
    mgr.start(name="b", command=command, shell="cmd", cwd=str(tmp_path))
    assert len(mgr.list()) == 2

    mgr.shutdown_all()
    assert mgr.services == {}
