"""
Tests for terminal LangChain tool wrappers.

Heavy application dependencies (langchain_core, apscheduler, etc.) are not
installed in the test environment, so we stub them in sys.modules before any
app imports are attempted.
"""
import sys
import types
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Minimal sys.modules stubs for dependencies not present in test environment
# ---------------------------------------------------------------------------

def _make_module(name, **attrs):
    mod = types.ModuleType(name)
    mod.__path__ = []
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


def _stub_all():
    # ---- langchain_core: minimal @tool decorator ----
    if "langchain_core" not in sys.modules:
        def tool(fn=None, **kwargs):
            """Passthrough @tool decorator: attaches .name and .ainvoke."""
            def _wrap(f):
                f.name = f.__name__
                async def ainvoke(input_dict, **kw):
                    return await f(**input_dict)
                f.ainvoke = ainvoke
                return f
            return _wrap(fn) if fn is not None else _wrap

        _make_module("langchain_core")
        _make_module("langchain_core.tools", tool=tool)

    # ---- apscheduler ----
    for name in ["apscheduler", "apscheduler.schedulers"]:
        if name not in sys.modules:
            _make_module(name)
    if "apscheduler.schedulers.asyncio" not in sys.modules:
        _make_module("apscheduler.schedulers.asyncio", AsyncIOScheduler=MagicMock)
    if "apscheduler.triggers" not in sys.modules:
        _make_module("apscheduler.triggers")
    if "apscheduler.triggers.date" not in sys.modules:
        _make_module("apscheduler.triggers.date", DateTrigger=MagicMock)
    if "apscheduler.triggers.interval" not in sys.modules:
        _make_module("apscheduler.triggers.interval", IntervalTrigger=MagicMock)
    if "apscheduler.triggers.cron" not in sys.modules:
        _make_module("apscheduler.triggers.cron", CronTrigger=MagicMock)


_stub_all()

# Now we can safely import terminal_tools (app/tools/__init__.py will run,
# but all heavy deps are stubbed above).
import app.tools.terminal_tools  # noqa: F401
from app.tools.terminal_tools import (
    run_command,
    open_terminal,
    send_to_terminal,
    list_terminals,
    close_terminal,
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_run_command_calls_service():
    with patch("app.tools.terminal_tools.terminal_service.run_oneshot",
               new=AsyncMock(return_value={
                   "exit_code": 0, "stdout": "ok", "stderr": "",
                   "truncated": False, "duration_ms": 5, "log_path": "/tmp/x.log",
               })):
        result = await run_command.ainvoke({"command": "dir", "shell": "powershell", "reason": "list files"})
        assert "ok" in result


async def test_open_terminal_calls_service():
    with patch("app.tools.terminal_tools.terminal_service.open_session",
               new=AsyncMock(return_value={
                   "session_id": "abc", "name": "py",
                   "message": "Opened powershell session 'py'",
               })):
        result = await open_terminal.ainvoke({"name": "py", "shell": "powershell"})
        assert "py" in result


async def test_send_to_terminal_calls_service():
    with patch("app.tools.terminal_tools.terminal_service.send_to_session",
               new=AsyncMock(return_value={
                   "output": "raw", "ansi_stripped": "clean", "exit_code_if_dead": None,
               })):
        result = await send_to_terminal.ainvoke({"name": "py", "input": "print(1)\n"})
        assert "clean" in result or "raw" in result


async def test_list_terminals():
    with patch("app.tools.terminal_tools.terminal_service.list_sessions",
               return_value=[{
                   "name": "a", "shell": "cmd", "cwd": "/",
                   "idle_seconds": 1, "last_output_preview": "$ ", "session_id": "x",
               }]):
        result = await list_terminals.ainvoke({})
        assert "a" in result


async def test_close_terminal():
    with patch("app.tools.terminal_tools.terminal_service.close_session",
               new=AsyncMock(return_value={"closed": True, "message": "Closed 'py'"})):
        result = await close_terminal.ainvoke({"name": "py"})
        assert "Closed" in result
