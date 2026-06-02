"""LangChain tools exposing TerminalService to the agent."""

import json
from typing import Optional
from langchain_core.tools import tool

from app.services.terminal_service import terminal_service


@tool
async def run_command(
    command: str,
    shell: str = "powershell",
    cwd: Optional[str] = None,
    timeout: int = 60,
    reason: str = "",
) -> str:
    """Run a one-shot shell command and return its output.

    Args:
        command: The exact command line to run (e.g. "git status").
        shell: One of "powershell", "cmd", "bash". Defaults to powershell.
        cwd: Working directory; omit for the configured default.
        timeout: Max seconds to wait before killing the process.
        reason: Short human-readable explanation of why you want to run this (shown to user when confirmation is required).
    """
    result = await terminal_service.run_oneshot(
        command=command, shell=shell, cwd=cwd, timeout=timeout, reason=reason,
    )
    return json.dumps(result, ensure_ascii=False)


@tool
async def open_terminal(
    name: Optional[str] = None,
    shell: str = "powershell",
    cwd: Optional[str] = None,
) -> str:
    """Open a persistent interactive terminal session. Use for REPLs, SSH, or any
    command that needs ongoing interaction. Returns a session name to use with
    send_to_terminal.

    Args:
        name: Optional name; server assigns one if omitted.
        shell: powershell | cmd | bash.
        cwd: Starting directory.
    """
    result = await terminal_service.open_session(name=name, shell=shell, cwd=cwd)
    return json.dumps(result, ensure_ascii=False)


@tool
async def send_to_terminal(name: str, input: str, wait_seconds: float = 2.0) -> str:
    """Write input to an open terminal session and read the response.

    Args:
        name: Session name from open_terminal.
        input: Text to send (include "\\n" to submit a line).
        wait_seconds: How long to collect output after sending.
    """
    result = await terminal_service.send_to_session(name=name, data=input, wait_seconds=wait_seconds)
    return json.dumps(result, ensure_ascii=False)


@tool
async def list_terminals() -> str:
    """List all currently open terminal sessions."""
    return json.dumps(terminal_service.list_sessions(), ensure_ascii=False)


@tool
async def close_terminal(name: str) -> str:
    """Close an open terminal session.

    Args:
        name: Session name.
    """
    result = await terminal_service.close_session(name)
    return json.dumps(result, ensure_ascii=False)
