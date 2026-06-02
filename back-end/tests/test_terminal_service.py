import asyncio
import json
import sys
import pytest
from pathlib import Path
from unittest.mock import AsyncMock

from app.services.terminal_service import TerminalService
from app.services.terminal_whitelist import WhitelistGuard


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


@pytest.fixture
def gated_svc(tmp_path: Path):
    wl_data = {"allow": ["python", "py"], "deny_argpatterns": {}, "blacklist_patterns": ["format\\s+C:"]}
    wl_path = tmp_path / "wl.json"
    wl_path.write_text(json.dumps(wl_data))
    user_path = tmp_path / "uwl.json"
    guard = WhitelistGuard(str(wl_path), str(user_path))
    svc = TerminalService(
        whitelist=guard,
        runs_dir=tmp_path / "runs",
        audit_log_path=tmp_path / "audit.log",
        default_cwd=str(tmp_path),
        oneshot_timeout=10,
        max_output_bytes=10_000,
        llm_preview_bytes=200,
    )
    svc.broadcast = AsyncMock()
    return svc


async def test_blacklist_blocks_without_confirm(gated_svc):
    result = await gated_svc.run_oneshot("format C: /q", shell="cmd")
    assert result["exit_code"] == -1
    assert "block" in result["stderr"].lower() or "blacklist" in result["stderr"].lower()


async def test_unknown_command_emits_confirm_and_denies_on_timeout(gated_svc):
    gated_svc.confirm_timeout = 0.2
    result = await gated_svc.run_oneshot("docker ps", shell="powershell")
    assert result["exit_code"] == -1
    assert "denied" in result["stderr"].lower() or "timeout" in result["stderr"].lower()
    # Expect a confirm_request was broadcast
    calls = [c.args[0] for c in gated_svc.broadcast.call_args_list]
    assert any(m.get("type") == "terminal_confirm_request" for m in calls)


async def test_confirm_approve_runs_command(gated_svc):
    # Pre-resolve the confirm future to "approve" before run_oneshot awaits it
    async def auto_approve(msg):
        if msg.get("type") == "terminal_confirm_request":
            req_id = msg["request_id"]
            asyncio.get_running_loop().call_soon(
                lambda: gated_svc.resolve_confirm(req_id, "approve")
            )
    gated_svc.broadcast = AsyncMock(side_effect=auto_approve)
    cmd = f'{sys.executable} -c "print(42)"'
    result = await gated_svc.run_oneshot(cmd, shell="cmd")
    # Note: sys.executable's binary name (python.exe) is in allow list
    assert result["exit_code"] == 0
    assert "42" in result["stdout"]
