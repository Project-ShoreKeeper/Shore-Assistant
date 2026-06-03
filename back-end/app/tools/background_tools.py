"""LangChain tools for managing long-running background services.

Distinct from `run_command` (one-shot, finishes on its own) and `open_terminal`
(interactive PTY). Use these for things that should keep listening / watching
after the call returns: filebrowser, dev servers, watchers, daemons.
"""

import json
from typing import Optional
from langchain_core.tools import tool

from app.services.terminal_service import terminal_service
from app.services.background_service import background_service_manager


@tool
async def start_background_service(
    name: str,
    command: str,
    shell: str = "powershell",
    cwd: Optional[str] = None,
    reason: str = "",
) -> str:
    """Launch a long-running service detached and hidden (no console window pops up).
    Stdout + stderr are captured to a log file you can tail with
    get_background_service_logs.

    Use this for any process that keeps running after starting — a file browser,
    dev server, file watcher, daemon. For NON-detached one-shot commands, use
    run_command instead.

    Args:
        name: Short identifier (used by stop / list / logs). Must be unique among running services.
        command: Exact command line to launch. Example: ".\\filebrowser.exe"
        shell: powershell | pwsh | cmd | bash. Default powershell.
        cwd: Working directory the service starts in. **CRITICAL** for services that read config/db from CWD (e.g. filebrowser loads filebrowser.json / filebrowser.db there). Defaults to TERMINAL_DEFAULT_CWD.
        reason: Short user-facing explanation (shown in confirm dialog if the command needs approval).
    """
    result = await terminal_service.start_background(
        name=name, command=command, shell=shell, cwd=cwd, reason=reason,
    )
    return json.dumps(result, ensure_ascii=False)


@tool
async def list_background_services() -> str:
    """List background services currently running (started via start_background_service).
    Returns name, pid, command, cwd, uptime."""
    return json.dumps(background_service_manager.list(), ensure_ascii=False)


@tool
async def stop_background_service(name: str) -> str:
    """Stop a background service by name.

    Args:
        name: Service name from start_background_service.
    """
    result = background_service_manager.stop(name=name)
    return json.dumps(result, ensure_ascii=False)


@tool
async def get_background_service_logs(name: str, lines: int = 50) -> str:
    """Read the last N lines of a background service's combined stdout+stderr log.
    Use right after starting to confirm the service is healthy (e.g. shows
    "Listening on ..." for a web server).

    Args:
        name: Service name.
        lines: How many trailing lines to read. Default 50.
    """
    return background_service_manager.tail_log(name=name, lines=lines)
