"""TerminalService unit tests.

The PTY execution layer lives in :class:`NodePtyBackend`, which talks to the
shore-pty-service microservice over JSON-RPC. These tests stub the JSON-RPC
client so we exercise TerminalService logic (whitelist gating, confirm flow,
audit logging, broadcasting) without depending on a real PTY or the Node
microservice.
"""

import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from app.services.terminal_service import TerminalService, strip_ansi
from app.services.terminal_whitelist import WhitelistGuard
from app.services.terminal_backend import NodePtyBackend
from app.services.node_pty_client import NodePtyClient


def _mk_svc(tmp_path: Path, mock_call, whitelist=None) -> tuple[TerminalService, NodePtyBackend, MagicMock]:
    client = MagicMock(spec=NodePtyClient)
    client.call = mock_call
    client.on_notification = MagicMock()
    client.on_disconnect = MagicMock()
    client.close = AsyncMock()
    backend = NodePtyBackend(client)
    svc = TerminalService(
        whitelist=whitelist,
        runs_dir=tmp_path / "runs",
        audit_log_path=tmp_path / "audit.log",
        default_cwd=str(tmp_path),
        backend=backend,
        oneshot_timeout=10,
        max_output_bytes=10_000,
        llm_preview_bytes=200,
    )
    svc.broadcast = AsyncMock()
    return svc, backend, client


@pytest.fixture
def gated_svc(tmp_path: Path):
    wl_data = {"allow": ["python", "py"], "deny_argpatterns": {}, "blacklist_patterns": ["format\\s+C:"]}
    wl_path = tmp_path / "wl.json"
    wl_path.write_text(json.dumps(wl_data))
    user_path = tmp_path / "uwl.json"
    guard = WhitelistGuard(str(wl_path), str(user_path))

    # Backend should never be invoked for blocked / denied commands. If a test
    # exercises the approve branch it wires its own fake_call.
    async def unexpected_call(method, params, timeout=None):
        raise AssertionError(f"backend should not be called: {method}")

    svc, _backend, _client = _mk_svc(tmp_path, AsyncMock(side_effect=unexpected_call), whitelist=guard)
    return svc


async def test_blacklist_blocks_without_confirm(gated_svc):
    result = await gated_svc.run_oneshot("format C: /q", shell="cmd")
    assert result["exit_code"] == -1
    assert "block" in result["stderr"].lower() or "blacklist" in result["stderr"].lower()


async def test_unknown_command_emits_confirm_and_denies_on_timeout(gated_svc):
    gated_svc.confirm_timeout = 0.2
    result = await gated_svc.run_oneshot("docker ps", shell="powershell")
    assert result["exit_code"] == -1
    assert "denied" in result["stderr"].lower() or "timed out" in result["stderr"].lower()
    # Expect a confirm_request was broadcast
    calls = [c.args[0] for c in gated_svc.broadcast.call_args_list]
    assert any(m.get("type") == "terminal_confirm_request" for m in calls)


async def test_confirm_approve_runs_command(tmp_path: Path):
    wl_data = {"allow": ["python", "py"], "deny_argpatterns": {}, "blacklist_patterns": []}
    wl_path = tmp_path / "wl.json"
    wl_path.write_text(json.dumps(wl_data))
    guard = WhitelistGuard(str(wl_path), str(tmp_path / "uwl.json"))

    async def fake_call(method, params, timeout=None):
        if method == "oneshot.run":
            return {"exit_code": 0, "duration_ms": 12, "timed_out": False}
        raise AssertionError(f"unexpected: {method}")

    svc, _backend, _client = _mk_svc(tmp_path, AsyncMock(side_effect=fake_call), whitelist=guard)

    async def auto_approve(msg):
        if msg.get("type") == "terminal_confirm_request":
            req_id = msg["request_id"]
            asyncio.get_running_loop().call_soon(
                lambda: svc.resolve_confirm(req_id, "approve")
            )
    svc.broadcast = AsyncMock(side_effect=auto_approve)

    # 'docker' is not in the allow list, so this exercises the confirm flow.
    result = await svc.run_oneshot("docker ps", shell="powershell")
    assert result["exit_code"] == 0


async def test_node_backend_oneshot(tmp_path: Path):
    async def fake_call(method, params, timeout=None):
        if method == "oneshot.run":
            return {"exit_code": 0, "duration_ms": 42, "timed_out": False}
        raise AssertionError(f"unexpected call: {method}")
    svc, _backend, _client = _mk_svc(tmp_path, AsyncMock(side_effect=fake_call))
    result = await svc.run_oneshot("echo hi", shell="powershell")
    assert result["exit_code"] == 0
    assert result["duration_ms"] == 42


async def test_node_backend_session_lifecycle(tmp_path: Path):
    async def fake_call(method, params, timeout=None):
        if method == "session.open":
            return {"session_id": params["session_id"], "pid": 1234}
        if method == "session.send":
            return {"ok": True}
        if method == "session.close":
            return {"closed": True}
        raise AssertionError(f"unexpected call: {method}")
    svc, backend, _client = _mk_svc(tmp_path, AsyncMock(side_effect=fake_call))

    open_result = await svc.open_session("dev", shell="powershell")
    assert "session_id" in open_result
    assert "dev" in svc.sessions

    # Simulate Node sending session.output notification
    await backend._on_notification("session.output", {
        "session_id": open_result["session_id"], "data": "PS C:\\>"
    })
    assert "PS C" in svc.sessions["dev"]["_buffer_tail"]

    await svc.send_to_session("dev", "ls\r\n", wait_seconds=0)
    close_result = await svc.close_session("dev")
    assert close_result["closed"] is True


async def test_node_disconnect_broadcasts_session_closed(tmp_path: Path):
    """When Node disconnects, every tracked session must broadcast terminal_session_closed."""
    async def fake_call(method, params, timeout=None):
        if method == "session.open":
            return {"session_id": params["session_id"], "pid": 4321}
        raise AssertionError(f"unexpected: {method}")
    svc, backend, _client = _mk_svc(tmp_path, AsyncMock(side_effect=fake_call))

    # Open two sessions through the public API so backend._session_callbacks gets populated.
    await svc.open_session("dev1", shell="powershell")
    await svc.open_session("dev2", shell="powershell")
    assert "dev1" in svc.sessions and "dev2" in svc.sessions

    # Simulate Node disconnect.
    await backend._on_disconnect()

    # Both TerminalService entries removed.
    assert "dev1" not in svc.sessions
    assert "dev2" not in svc.sessions

    # Both broadcast events with reason="node_disconnect".
    broadcasts = [c.args[0] for c in svc.broadcast.call_args_list]
    closed_events = [m for m in broadcasts if m.get("type") == "terminal_session_closed"]
    assert len(closed_events) == 2
    assert all(m["reason"] == "node_disconnect" for m in closed_events)
    assert {m["name"] for m in closed_events} == {"dev1", "dev2"}


async def test_send_to_nonexistent_session_errors(tmp_path: Path):
    async def fake_call(method, params, timeout=None):
        raise AssertionError(f"backend not expected: {method}")
    svc, _backend, _client = _mk_svc(tmp_path, AsyncMock(side_effect=fake_call))
    result = await svc.send_to_session("ghost", "hi\r\n")
    assert "error" in result
    assert "ghost" in result["error"]


async def test_open_duplicate_name_errors(tmp_path: Path):
    async def fake_call(method, params, timeout=None):
        if method == "session.open":
            return {"session_id": params["session_id"], "pid": 1}
        raise AssertionError(f"unexpected: {method}")
    svc, _backend, _client = _mk_svc(tmp_path, AsyncMock(side_effect=fake_call))
    await svc.open_session(name="dup", shell="powershell")
    result = await svc.open_session(name="dup", shell="powershell")
    assert "error" in result


async def test_list_sessions_includes_opened(tmp_path: Path):
    async def fake_call(method, params, timeout=None):
        if method == "session.open":
            return {"session_id": params["session_id"], "pid": 42}
        raise AssertionError(f"unexpected: {method}")
    svc, _backend, _client = _mk_svc(tmp_path, AsyncMock(side_effect=fake_call))
    await svc.open_session(name="x", shell="powershell")
    listed = svc.list_sessions()
    names = [s["name"] for s in listed]
    assert "x" in names


# ---------------------------------------------------------------------------
# strip_ansi: the aggressive cleaner used on tool results sent to the LLM
# ---------------------------------------------------------------------------

def test_strip_ansi_csi_color_codes():
    assert strip_ansi("\x1b[31mred\x1b[0m") == "red"


def test_strip_ansi_osc_window_title_bel():
    # PowerShell sets the window title each prompt redraw with OSC + BEL.
    s = "\x1b]0;PS C:\\Users\\foo\x07PS C:\\> "
    assert strip_ansi(s) == "PS C:\\> "


def test_strip_ansi_osc_st_terminated():
    s = "before\x1b]2;Title\x1b\\after"
    assert strip_ansi(s) == "beforeafter"


def test_strip_ansi_charset_designator():
    # ESC ( B selects ASCII G0 — emitted on ConPTY init.
    assert strip_ansi("\x1b(Bhello") == "hello"


def test_strip_ansi_dcs():
    assert strip_ansi("\x1bPpayload\x1b\\done") == "done"


def test_strip_ansi_bracketed_paste_markers():
    assert strip_ansi("\x1b[?2004hcmd\x1b[?2004l") == "cmd"


def test_strip_ansi_crlf_normalized_and_bare_cr_dropped():
    # CRLF → \n, bare \r (used for redraws) → dropped entirely.
    assert strip_ansi("line1\r\nline2\rredraw") == "line1\nline2redraw"


def test_strip_ansi_blank_run_collapsed():
    assert strip_ansi("a\n\n\n\n\nb") == "a\n\nb"


def test_strip_ansi_bel_and_backspace_stripped():
    assert strip_ansi("hi\x07\x08there") == "hithere"


# ---------------------------------------------------------------------------
# send_to_session: prompt detection + dropped raw_output
# ---------------------------------------------------------------------------

async def test_send_to_session_detects_powershell_prompt_and_returns_early(tmp_path: Path):
    """When session output ends with a PowerShell prompt, send_to_session returns
    quickly with prompt_seen=True, without waiting the full wait_seconds."""
    async def fake_call(method, params, timeout=None):
        if method == "session.open":
            return {"session_id": params["session_id"], "pid": 1}
        if method == "session.send":
            return {"ok": True}
        raise AssertionError(f"unexpected: {method}")
    svc, backend, _client = _mk_svc(tmp_path, AsyncMock(side_effect=fake_call))
    await svc.open_session("dev", shell="powershell")
    sid = svc.sessions["dev"]["session_id"]

    async def feed_output_after_send():
        await asyncio.sleep(0.05)
        await backend._on_notification("session.output", {
            "session_id": sid,
            "data": "ls\r\nfile1.txt\r\nfile2.txt\r\nPS D:\\Jupiter> ",
        })

    asyncio.create_task(feed_output_after_send())

    import time as _t
    start = _t.time()
    # Generous wait — we expect the early exit on prompt match, not the timeout.
    result = await svc.send_to_session("dev", "ls\n", wait_seconds=5.0)
    elapsed = _t.time() - start

    assert result["prompt_seen"] is True
    assert "file1.txt" in result["output"]
    assert "file2.txt" in result["output"]
    assert "raw_output" not in result          # raw_output dropped on purpose
    assert elapsed < 2.0                       # didn't wait the full 5s


async def test_send_to_session_times_out_with_prompt_seen_false(tmp_path: Path):
    async def fake_call(method, params, timeout=None):
        if method == "session.open":
            return {"session_id": params["session_id"], "pid": 1}
        if method == "session.send":
            return {"ok": True}
        raise AssertionError(f"unexpected: {method}")
    svc, _backend, _client = _mk_svc(tmp_path, AsyncMock(side_effect=fake_call))
    await svc.open_session("dev", shell="powershell")

    result = await svc.send_to_session("dev", "long-running\n", wait_seconds=0.3)
    assert result["prompt_seen"] is False
    assert result["output"] == ""


async def test_send_to_session_converts_lf_to_cr_for_conpty(tmp_path: Path):
    """ConPTY on Windows turns LF into Ctrl+J (Shift+Enter in PSReadLine), which
    causes the `>>` continuation prompt instead of submitting the command. The
    service must normalize \\n and \\r\\n to a single \\r before sending."""
    sent: list[str] = []

    async def fake_call(method, params, timeout=None):
        if method == "session.open":
            return {"session_id": params["session_id"], "pid": 1}
        if method == "session.send":
            sent.append(params["data"])
            return {"ok": True}
        raise AssertionError(f"unexpected: {method}")

    svc, _backend, _client = _mk_svc(tmp_path, AsyncMock(side_effect=fake_call))
    await svc.open_session("dev", shell="powershell")

    await svc.send_to_session("dev", "ls\n", wait_seconds=0)
    await svc.send_to_session("dev", "git status\r\n", wait_seconds=0)
    await svc.send_to_session("dev", "echo a\nline2\n", wait_seconds=0)

    assert sent == ["ls\r", "git status\r", "echo a\rline2\r"]


async def test_send_to_session_salvages_double_escaped_newline_from_llm(tmp_path: Path):
    """Smaller local LLMs sometimes double-escape the newline in their JSON
    tool args — emitting `\\n` (backslash + n, 2 chars) instead of a real LF.
    Without defensive translation, the shell would type the literal string `\\n`
    and never press Enter, piling subsequent commands onto the same input line.
    """
    sent: list[str] = []

    async def fake_call(method, params, timeout=None):
        if method == "session.open":
            return {"session_id": params["session_id"], "pid": 1}
        if method == "session.send":
            sent.append(params["data"])
            return {"ok": True}
        raise AssertionError(f"unexpected: {method}")

    svc, _backend, _client = _mk_svc(tmp_path, AsyncMock(side_effect=fake_call))
    await svc.open_session("dev", shell="powershell")

    # These are what arrives if the LLM emitted `{"input": "claude\\n"}` (JSON
    # double-escape) — Python sees 2 literal chars: backslash + n.
    await svc.send_to_session("dev", "claude\\n", wait_seconds=0)
    await svc.send_to_session("dev", "git status\\r\\n", wait_seconds=0)
    await svc.send_to_session("dev", "echo a\\nline2\\n", wait_seconds=0)

    assert sent == ["claude\r", "git status\r", "echo a\rline2\r"]


async def test_send_to_session_does_not_treat_continuation_prompt_as_ready(tmp_path: Path):
    """`>>` is PSReadLine's continuation prompt (input incomplete), not the
    ready prompt — prompt_seen must stay False when the buffer ends with `>>`."""
    async def fake_call(method, params, timeout=None):
        if method == "session.open":
            return {"session_id": params["session_id"], "pid": 1}
        if method == "session.send":
            return {"ok": True}
        raise AssertionError(f"unexpected: {method}")
    svc, backend, _client = _mk_svc(tmp_path, AsyncMock(side_effect=fake_call))
    await svc.open_session("dev", shell="powershell")
    sid = svc.sessions["dev"]["session_id"]

    async def feed_continuation_prompt():
        await asyncio.sleep(0.05)
        # PSReadLine showed the continuation prompt because of incomplete input.
        await backend._on_notification("session.output", {
            "session_id": sid, "data": "ls\r\n>> ",
        })

    asyncio.create_task(feed_continuation_prompt())
    result = await svc.send_to_session("dev", "ls\n", wait_seconds=0.5)
    assert result["prompt_seen"] is False


async def test_read_session_returns_stripped_tail(tmp_path: Path):
    async def fake_call(method, params, timeout=None):
        if method == "session.open":
            return {"session_id": params["session_id"], "pid": 1}
        raise AssertionError(f"unexpected: {method}")
    svc, backend, _client = _mk_svc(tmp_path, AsyncMock(side_effect=fake_call))
    await svc.open_session("dev", shell="powershell")
    sid = svc.sessions["dev"]["session_id"]

    # Output with ANSI color + OSC title + a powershell prompt at end.
    await backend._on_notification("session.output", {
        "session_id": sid,
        "data": "\x1b[32mok\x1b[0m\r\n\x1b]0;Title\x07PS D:\\> ",
    })
    result = svc.read_session("dev", tail_chars=100)
    assert "ok" in result["output"]
    assert "\x1b" not in result["output"]
    assert "Title" not in result["output"]
    assert result["prompt_seen"] is True
