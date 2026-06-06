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
        shell: One of "powershell", "pwsh", "cmd", "bash", "wsl", "anaconda". Defaults to powershell.
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
        shell: powershell | pwsh | cmd | bash | wsl | anaconda.
        cwd: Starting directory.
    """
    result = await terminal_service.open_session(name=name, shell=shell, cwd=cwd)
    return json.dumps(result, ensure_ascii=False)


@tool
async def send_to_terminal(name: str, input: str, wait_seconds: float = 10.0) -> str:
    """Write input to an open terminal session and read the response.

    Output is ANSI-stripped (window-title, color codes, prompt redraws removed).
    Polling stops as soon as the shell prompt comes back, or after
    `wait_seconds` if no prompt is seen — increase it for slower commands.
    The result includes a `prompt_seen` flag; if False, the command is likely
    still running — use `read_terminal` to poll for more output.

    Args:
        name: Session name from open_terminal.
        input: Text to send. End with a real newline character (the Enter key,
            U+000A) so the shell submits the line. In JSON tool arguments this
            is the single escape `\n` — do NOT double-escape it as `\\n`.
        wait_seconds: Max seconds to wait for the next prompt before returning.
    """
    result = await terminal_service.send_to_session(name=name, data=input, wait_seconds=wait_seconds)
    return json.dumps(result, ensure_ascii=False)


@tool
async def read_terminal(name: str, tail_chars: int = 4096) -> str:
    """Read the current tail of a session's buffer without sending any input.

    Use this to poll a long-running command that didn't return a prompt within
    `send_to_terminal`'s wait window (`prompt_seen=false`). Output is
    ANSI-stripped.

    Args:
        name: Session name.
        tail_chars: How many trailing characters of the stripped buffer to return.
    """
    result = terminal_service.read_session(name=name, tail_chars=tail_chars)
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
