import asyncio
import sys
import pytest
from pathlib import Path
from unittest.mock import AsyncMock

from app.services.terminal_service import TerminalService


@pytest.fixture
def svc(tmp_path: Path, monkeypatch):
    # Point service at temp dirs/files
    monkeypatch.setenv("TERMINAL_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("TERMINAL_AUDIT_LOG", str(tmp_path / "audit.log"))
    service = TerminalService(
        whitelist=None,  # no guard for these tests
        runs_dir=tmp_path / "runs",
        audit_log_path=tmp_path / "audit.log",
        default_cwd=str(tmp_path),
        oneshot_timeout=10,
        max_output_bytes=10_000,
        llm_preview_bytes=200,
    )
    service.broadcast = AsyncMock()  # capture WS sends
    return service


async def test_oneshot_echo(svc):
    cmd = f'{sys.executable} -c "print(\\"hello\\")"'
    result = await svc.run_oneshot(cmd, shell="cmd")
    assert result["exit_code"] == 0
    assert "hello" in result["stdout"]
    assert result["truncated"] is False


async def test_oneshot_nonzero_exit(svc):
    cmd = f'{sys.executable} -c "import sys; sys.exit(7)"'
    result = await svc.run_oneshot(cmd, shell="cmd")
    assert result["exit_code"] == 7


async def test_oneshot_timeout(svc):
    svc.oneshot_timeout = 1
    cmd = f'{sys.executable} -c "import time; time.sleep(5)"'
    result = await svc.run_oneshot(cmd, shell="cmd")
    assert result["exit_code"] == -1
    assert "timed out" in result["stderr"].lower()
