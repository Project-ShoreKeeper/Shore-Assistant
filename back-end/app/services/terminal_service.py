"""Terminal service: policy + broadcast layer over a TerminalBackend."""

import asyncio
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.services.terminal_backend import (
    TerminalBackend,
    ExecResult,
    SessionHandle,
)

# Comprehensive ESC-sequence matcher covering what ConPTY / PSReadLine actually emits:
#   - CSI            ESC [ <params> <intermediates> <final 0x40-0x7E>
#   - OSC            ESC ] ... (BEL | ESC \)         e.g. window title  ESC ]0;…BEL
#   - DCS/SOS/PM/APC ESC (P|X|^|_) ... ESC \
#   - Charset desig. ESC (|)|*|+ <one byte>          e.g. ESC ( B
#   - Single-char    ESC <0x40-0x5F>                 e.g. ESC = , ESC >
# Use [\s\S] (not .) so multi-line OSC/DCS strings match without DOTALL gymnastics.
ANSI_RE = re.compile(
    r"""\x1B
    (?:
        \[ [0-?]* [ -/]* [@-~]                          # CSI
      | \] [\s\S]*? (?: \x07 | \x1B\\ )                 # OSC
      | [PX^_] [\s\S]*? \x1B\\                          # DCS / SOS / PM / APC
      | [()*+] [\s\S]                                   # charset designation
      | [@-_]                                           # single-char C1
    )""",
    re.VERBOSE,
)

# Stray single-byte control chars left over after ESC sequences are stripped.
# Keep \t and \n; drop BEL, BS, SO, SI, NUL, VT, FF, DEL.
_STRAY_CTRL_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")

# 3+ consecutive newlines (prompt redraw spam) collapse to a paragraph break.
_BLANK_RUN_RE = re.compile(r"\n{3,}")


def strip_ansi(text: str) -> str:
    """Strip ANSI escape sequences and other terminal noise from PTY output.

    Aggressive: also normalizes \\r\\n→\\n, drops bare \\r, removes stray control
    chars, and collapses long runs of blank lines that come from PSReadLine
    prompt redraws.
    """
    if not text:
        return text
    text = ANSI_RE.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "")
    text = _STRAY_CTRL_RE.sub("", text)
    text = _BLANK_RUN_RE.sub("\n\n", text)
    return text


# Per-shell prompt detectors used by send_to_session to know when a command
# finished and the shell is ready for the next input. Match against the END of
# the *stripped* buffer.
# IMPORTANT: PowerShell's `>>` continuation prompt is NOT a ready prompt —
# it means PSReadLine is waiting for more input — so do NOT match it here, or
# we will falsely return prompt_seen=True for an unfinished command.
_PROMPT_PATTERNS = {
    "powershell": re.compile(r"PS\s+[^\r\n]*?>\s*\Z"),
    "pwsh":       re.compile(r"PS\s+[^\r\n]*?>\s*\Z"),
    "cmd":        re.compile(r"[A-Za-z]:\\[^\r\n]*?>\s*\Z"),
    "bash":       re.compile(r"[\$#]\s*\Z"),
    "wsl":        re.compile(r"[\$#]\s*\Z"),
    # Anaconda runs inside cmd.exe with an "(envname) C:\path>" prompt — the
    # trailing "...>\Z" still matches the cmd pattern.
    "anaconda":   re.compile(r"[A-Za-z]:\\[^\r\n]*?>\s*\Z"),
}


def _normalize_send_data(data: str) -> str:
    """Translate text-mode line endings to the keystroke ConPTY actually wants
    for Enter. PSReadLine on ConPTY treats LF as Shift+Enter (newline-in-input,
    shows the `>>` continuation prompt) — only CR triggers VK_RETURN. PTYs on
    Linux/macOS/Git-Bash strip CR via ICRNL, so a single CR is also fine there.
    """
    if not data:
        return data
    # Collapse CRLF first so we don't end up with double Enter.
    return data.replace("\r\n", "\r").replace("\n", "\r")

# Capacity for the sliding output buffer kept per interactive session.
_SESSION_BUFFER_CAP = 65536


class TerminalService:

    def __init__(
        self,
        whitelist,
        runs_dir: Path,
        audit_log_path: Path,
        default_cwd: str,
        backend: TerminalBackend,
        oneshot_timeout: int = 60,
        max_output_bytes: int = 1_048_576,
        llm_preview_bytes: int = 8192,
    ):
        self.whitelist = whitelist
        self.runs_dir = Path(runs_dir)
        self.audit_log_path = Path(audit_log_path)
        self.default_cwd = default_cwd
        self.oneshot_timeout = oneshot_timeout
        self.max_output_bytes = max_output_bytes
        self.llm_preview_bytes = llm_preview_bytes
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        # Hook set by chat_ws to broadcast WS messages
        self.broadcast = None  # async callable(dict)
        self.confirm_timeout = 60
        self._pending_confirms: dict[str, asyncio.Future] = {}
        self.sessions: dict[str, dict] = {}
        self.session_idle_seconds = 30 * 60
        self.backend: TerminalBackend = backend
        # Optional startup hook (e.g. for NodePtyBackend: start reconnect + heartbeat tasks)
        self._startup_hook: Optional[callable] = None

    async def startup(self):
        """Call during app lifespan startup (event loop must be running)."""
        if self._startup_hook:
            await self._startup_hook()

    async def _broadcast(self, msg: dict):
        if self.broadcast:
            try:
                await self.broadcast(msg)
            except Exception:
                pass

    def _audit(self, entry: dict):
        entry["ts"] = datetime.now(timezone.utc).isoformat()
        with open(self.audit_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def resolve_confirm(self, request_id: str, decision: str) -> bool:
        fut = self._pending_confirms.pop(request_id, None)
        pending_ids = list(self._pending_confirms.keys())
        import sys
        if fut and not fut.done():
            sys.stderr.write(f"[confirm] resolved request_id={request_id} decision={decision}\n")
            sys.stderr.flush()
            fut.set_result(decision)
            return True
        sys.stderr.write(f"[confirm] STALE click request_id={request_id} decision={decision} pending={pending_ids}\n")
        sys.stderr.flush()
        return False

    async def _request_confirm(self, command: str, shell: str, cwd: str, reason: str) -> str:
        request_id = uuid.uuid4().hex[:12]
        fut = asyncio.get_running_loop().create_future()
        self._pending_confirms[request_id] = fut
        await self._broadcast({
            "type": "terminal_confirm_request",
            "request_id": request_id,
            "command": command,
            "shell": shell,
            "cwd": cwd,
            "reason": reason,
        })
        try:
            decision = await asyncio.wait_for(fut, timeout=self.confirm_timeout)
        except asyncio.TimeoutError:
            self._pending_confirms.pop(request_id, None)
            decision = "timeout"
        await self._broadcast({
            "type": "terminal_confirm_resolved",
            "request_id": request_id,
            "decision": decision,
        })
        return decision

    async def _gate(self, kind: str, command: str, shell: str, cwd: str, reason: str) -> Optional[str]:
        """Run command through whitelist + confirm flow. Returns None if execution
        is permitted, or an error string (already audited) if blocked/denied/timed out."""
        if not self.whitelist:
            return None
        check = self.whitelist.check(command, shell)
        if check.decision == "block":
            self._audit({"kind": kind, "command": command, "shell": shell, "cwd": cwd,
                         "decision": "blocked", "reason": check.reason})
            return f"Blocked: {check.reason}"
        if check.decision == "confirm":
            response = await self._request_confirm(command, shell, cwd, reason or check.reason)
            if response == "always_allow":
                head = command.strip().split()[0] if command.strip() else ""
                if head:
                    self.whitelist.add_user_allow(head)
                return None
            if response == "approve":
                return None
            audit_decision = "timed_out" if response == "timeout" else "denied"
            self._audit({"kind": kind, "command": command, "shell": shell, "cwd": cwd,
                         "decision": audit_decision})
            return ("Confirmation timed out; ask user to retry"
                    if response == "timeout" else "User denied execution")
        return None

    async def run_oneshot(
        self,
        command: str,
        shell: str = "powershell",
        cwd: Optional[str] = None,
        timeout: Optional[int] = None,
        reason: str = "",
    ) -> dict:
        run_id = uuid.uuid4().hex[:12]
        cwd = cwd or self.default_cwd or os.getcwd()
        timeout = timeout or self.oneshot_timeout
        if not Path(cwd).is_dir():
            return {"exit_code": -1, "stdout": "", "stderr": f"CWD not found: {cwd}",
                    "truncated": False, "duration_ms": 0, "log_path": ""}

        gate_error = await self._gate("oneshot", command, shell, cwd, reason)
        if gate_error is not None:
            return {"exit_code": -1, "stdout": "", "stderr": gate_error,
                    "truncated": False, "duration_ms": 0, "log_path": ""}

        await self._broadcast({"type": "terminal_oneshot_start", "run_id": run_id,
                               "command": command, "shell": shell, "cwd": cwd})

        log_path = self.runs_dir / f"{run_id}.log"

        async def on_output(stream: str, data: str):
            with open(log_path, "ab") as f:
                f.write(data.encode("utf-8", errors="replace"))
            await self._broadcast({"type": "terminal_oneshot_output", "run_id": run_id,
                                   "stream": stream, "data": strip_ansi(data)})

        try:
            result: ExecResult = await self.backend.run_oneshot_exec(
                run_id=run_id, command=command, shell=shell, cwd=cwd,
                timeout=timeout, on_output=on_output,
            )
        except Exception as e:
            self._audit({"kind": "oneshot", "command": command, "shell": shell, "cwd": cwd,
                         "decision": "backend_error", "error": str(e)})
            return {"exit_code": -1, "stdout": "", "stderr": f"Backend error: {e}",
                    "truncated": False, "duration_ms": 0, "log_path": str(log_path)}

        stdout = strip_ansi(result.stdout)
        stderr = strip_ansi(result.stderr)
        truncated = result.truncated or len(stdout) > self.llm_preview_bytes or len(stderr) > self.llm_preview_bytes

        await self._broadcast({"type": "terminal_oneshot_end", "run_id": run_id,
                               "exit_code": result.exit_code, "duration_ms": result.duration_ms,
                               "truncated": truncated})
        self._audit({"kind": "oneshot", "run_id": run_id, "command": command, "shell": shell, "cwd": cwd,
                     "decision": "executed", "exit_code": result.exit_code,
                     "duration_ms": result.duration_ms, "reason": reason})
        return {
            "exit_code": result.exit_code,
            "stdout": stdout[: self.llm_preview_bytes],
            "stderr": stderr[: self.llm_preview_bytes],
            "truncated": truncated,
            "duration_ms": result.duration_ms,
            "log_path": str(log_path),
        }

    async def open_session(self, name: Optional[str], shell: str = "powershell", cwd: Optional[str] = None) -> dict:
        cwd = cwd or self.default_cwd or os.getcwd()
        if not Path(cwd).is_dir():
            return {"error": f"CWD not found: {cwd}"}
        name = name or f"session-{len(self.sessions) + 1}"
        if name in self.sessions:
            return {"error": f"Session '{name}' already exists"}
        session_id = uuid.uuid4().hex[:12]

        async def on_output(sid: str, data: str):
            entry = self.sessions.get(name)
            if entry:
                entry["last_activity"] = time.time()
                entry["_buffer_tail"] = (entry.get("_buffer_tail", "") + data)[-_SESSION_BUFFER_CAP:]
                entry["_total_bytes"] = entry.get("_total_bytes", 0) + len(data)
            await self._broadcast({"type": "terminal_session_output", "session_id": sid, "data": data})

        async def on_exit(sid: str, exit_code, reason: str):
            entry = self.sessions.pop(name, None)
            if entry:
                await self._broadcast({
                    "type": "terminal_session_closed",
                    "session_id": sid, "name": name,
                    "reason": reason, "exit_code": exit_code,
                })
                self._audit({"kind": "session_closed", "name": name,
                             "reason": reason, "exit_code": exit_code})

        try:
            handle: SessionHandle = await self.backend.open_session_exec(
                session_id=session_id, name=name, shell=shell, cwd=cwd,
                cols=80, rows=24, on_output=on_output, on_exit=on_exit,
            )
        except Exception as e:
            return {"error": f"Failed to open: {e}"}

        self.sessions[name] = {
            "session_id": handle.session_id,
            "shell": shell,
            "cwd": cwd,
            "pid": handle.pid,
            "last_activity": time.time(),
            "_buffer_tail": "",
            "_total_bytes": 0,
            "_prompt_pattern": _PROMPT_PATTERNS.get(shell),
        }

        await self._broadcast({"type": "terminal_session_opened",
                               "session_id": handle.session_id, "name": name,
                               "shell": shell, "cwd": cwd, "pid": handle.pid})
        self._audit({"kind": "session_opened", "name": name, "shell": shell, "cwd": cwd, "pid": handle.pid})
        return {"session_id": handle.session_id, "name": name, "message": f"Opened {shell} session '{name}'"}

    async def send_to_session(self, name: str, data: str, wait_seconds: float = 10.0) -> dict:
        """Send keystrokes to a session, then collect output until the shell
        prompt comes back (or `wait_seconds` elapses). Output is always
        ANSI-stripped — raw bytes are not returned.
        """
        entry = self.sessions.get(name)
        if not entry:
            return {"error": f"No terminal named '{name}'. Open one first.",
                    "available": list(self.sessions.keys())}
        before_bytes = entry.get("_total_bytes", 0)
        prompt_re: Optional[re.Pattern] = entry.get("_prompt_pattern")
        normalized = _normalize_send_data(data)
        try:
            await self.backend.send_to_session_exec(entry["session_id"], normalized)
        except Exception as e:
            return {"error": str(e)}

        poll_interval = 0.1
        deadline = time.time() + max(0.0, wait_seconds)
        prompt_seen = False
        while True:
            await asyncio.sleep(poll_interval)
            advanced = entry.get("_total_bytes", 0) - before_bytes
            if advanced > 0 and prompt_re is not None:
                stripped_now = strip_ansi(entry.get("_buffer_tail", ""))
                if prompt_re.search(stripped_now):
                    prompt_seen = True
                    break
            if time.time() >= deadline:
                break

        new_bytes = entry.get("_total_bytes", 0) - before_bytes
        tail = entry.get("_buffer_tail", "")
        if new_bytes <= 0:
            delta = ""
            truncated = False
        elif new_bytes <= len(tail):
            delta = tail[-new_bytes:]
            truncated = False
        else:
            delta = tail
            truncated = True

        return {
            "output": strip_ansi(delta),
            "prompt_seen": prompt_seen,
            "truncated": truncated,
            "exit_code_if_dead": None,
        }

    def read_session(self, name: str, tail_chars: int = 4096) -> dict:
        """Return the current tail of a session's buffer without sending input.
        Intended for polling long-running commands that didn't return a prompt
        within `send_to_terminal`'s wait window.
        """
        entry = self.sessions.get(name)
        if not entry:
            return {"error": f"No terminal named '{name}'.",
                    "available": list(self.sessions.keys())}
        stripped = strip_ansi(entry.get("_buffer_tail", ""))
        prompt_re: Optional[re.Pattern] = entry.get("_prompt_pattern")
        prompt_seen = bool(prompt_re and prompt_re.search(stripped))
        tail = stripped[-max(1, int(tail_chars)):]
        return {
            "output": tail,
            "prompt_seen": prompt_seen,
            "truncated": len(stripped) > len(tail),
        }

    def list_sessions(self) -> list:
        now = time.time()
        result = []
        for name, e in self.sessions.items():
            result.append({
                "name": name,
                "session_id": e["session_id"],
                "shell": e["shell"],
                "cwd": e["cwd"],
                "idle_seconds": int(now - e["last_activity"]),
                "last_output_preview": strip_ansi(e.get("_buffer_tail", ""))[-200:],
            })
        return result

    async def close_session(self, name: str) -> dict:
        entry = self.sessions.get(name)
        if not entry:
            return {"closed": False, "message": f"No session named '{name}'"}
        await self.backend.close_session_exec(entry["session_id"])
        return {"closed": True, "message": f"Closed '{name}'"}

    async def start_background(
        self,
        name: str,
        command: str,
        shell: str = "powershell",
        cwd: Optional[str] = None,
        reason: str = "",
    ) -> dict:
        """Launch a long-running service detached, hidden (no console window),
        with combined stdout/stderr captured to a log file. Goes through the same
        whitelist + confirm flow as run_oneshot."""
        cwd = cwd or self.default_cwd or os.getcwd()
        if not Path(cwd).is_dir():
            return {"error": f"CWD not found: {cwd}"}

        gate_error = await self._gate("bg_service", command, shell, cwd, reason)
        if gate_error is not None:
            return {"error": gate_error}

        from app.services.background_service import background_service_manager
        result = background_service_manager.start(
            name=name, command=command, shell=shell, cwd=cwd,
        )
        self._audit({
            "kind": "bg_service_start", "name": name, "command": command,
            "shell": shell, "cwd": cwd, "pid": result.get("pid"),
            "decision": "executed" if "pid" in result else "error",
            "reason": reason, "error": result.get("error"),
        })
        return result

    async def shutdown_all(self):
        from app.services.background_service import background_service_manager
        background_service_manager.shutdown_all()
        await self.backend.shutdown()


async def _idle_reaper(service: "TerminalService"):
    while True:
        await asyncio.sleep(60)
        now = time.time()
        for name, e in list(service.sessions.items()):
            if now - e["last_activity"] > service.session_idle_seconds:
                try:
                    await service.close_session(name)
                except Exception:
                    pass


def _build_service() -> TerminalService:
    from app.core.config import settings
    from app.services.terminal_whitelist import WhitelistGuard
    from app.services.node_pty_client import NodePtyClient
    from app.services.terminal_backend import NodePtyBackend

    default_cwd = settings.TERMINAL_DEFAULT_CWD or os.getcwd()
    guard = WhitelistGuard(
        default_path=settings.TERMINAL_WHITELIST_FILE,
        user_path=settings.TERMINAL_USER_WHITELIST_FILE,
    )

    client = NodePtyClient(
        url=settings.NODE_PTY_WS_URL,
        auth_token=settings.NODE_PTY_AUTH_TOKEN,
        ping_interval=settings.NODE_PTY_PING_INTERVAL_SECONDS,
        ping_timeout=settings.NODE_PTY_PING_TIMEOUT_SECONDS,
        reconnect_base_ms=settings.NODE_PTY_RECONNECT_BASE_MS,
        reconnect_max_ms=settings.NODE_PTY_RECONNECT_MAX_MS,
    )
    backend = NodePtyBackend(client)

    async def _node_startup():
        # asyncio tasks — must be created from a running event loop
        client.start_auto_reconnect()
        client.start_heartbeat()

    svc = TerminalService(
        whitelist=guard,
        runs_dir=Path(settings.TERMINAL_RUNS_DIR),
        audit_log_path=Path(settings.TERMINAL_AUDIT_LOG),
        default_cwd=default_cwd,
        backend=backend,
        oneshot_timeout=settings.TERMINAL_ONESHOT_TIMEOUT_SECONDS,
        max_output_bytes=settings.TERMINAL_MAX_OUTPUT_BYTES,
        llm_preview_bytes=settings.TERMINAL_LLM_OUTPUT_PREVIEW_BYTES,
    )
    svc.confirm_timeout = settings.TERMINAL_CONFIRM_TIMEOUT_SECONDS
    svc.session_idle_seconds = settings.TERMINAL_SESSION_IDLE_MINUTES * 60
    svc._startup_hook = _node_startup
    return svc


terminal_service = _build_service()
