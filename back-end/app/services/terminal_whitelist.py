"""Whitelist/blacklist guard for terminal commands."""

import json
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Decision = Literal["allow", "confirm", "block"]


@dataclass
class CheckResult:
    decision: Decision
    reason: str = ""


class WhitelistGuard:

    _CHAIN_RE = re.compile(r"\s*(?:&&|\|\||;|\|)\s*")
    _WRAPPER_RE = re.compile(
        r"""^\s*(powershell|pwsh|cmd|bash)\s+(?:-c|/c|/C)\s+(['"])(?P<inner>.+)\2\s*$""",
        re.IGNORECASE,
    )

    def __init__(self, default_path: str, user_path: str):
        self.default_path = default_path
        self.user_path = user_path
        self._load()

    def _load(self):
        with open(self.default_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.allow: set[str] = set(data.get("allow", []))
        self.deny_argpatterns: dict[str, list[re.Pattern]] = {
            cmd: [re.compile(p, re.IGNORECASE) for p in patterns]
            for cmd, patterns in data.get("deny_argpatterns", {}).items()
        }
        self.blacklist: list[re.Pattern] = [
            re.compile(p, re.IGNORECASE) for p in data.get("blacklist_patterns", [])
        ]
        # User-extended allow list
        if Path(self.user_path).exists():
            with open(self.user_path, "r", encoding="utf-8") as f:
                self.allow.update(json.load(f).get("allow", []))

    def check(self, command: str, shell: str) -> CheckResult:
        cmd_str = command.strip()
        # Unwrap shell -c "..." once
        m = self._WRAPPER_RE.match(cmd_str)
        if m:
            cmd_str = m.group("inner").strip()
        # Blacklist always wins, against the whole (unwrapped) string
        for pat in self.blacklist:
            if pat.search(cmd_str):
                return CheckResult("block", f"matches blacklist pattern: {pat.pattern}")
        segments = [s for s in self._CHAIN_RE.split(cmd_str) if s.strip()]
        decision: Decision = "allow"
        reasons: list[str] = []
        for seg in segments:
            try:
                tokens = shlex.split(seg, posix=(shell != "powershell"))
            except ValueError:
                decision = "confirm"
                reasons.append(f"could not parse: {seg}")
                continue
            if not tokens:
                continue
            head = tokens[0]
            # Re-check blacklist per segment too
            for pat in self.blacklist:
                if pat.search(seg):
                    return CheckResult("block", f"segment matches blacklist: {pat.pattern}")
            if head not in self.allow:
                decision = "confirm"
                reasons.append(f"'{head}' not in whitelist")
                continue
            if head in self.deny_argpatterns:
                rest = seg[len(head):]
                for pat in self.deny_argpatterns[head]:
                    if pat.search(rest):
                        decision = "confirm"
                        reasons.append(f"argument pattern '{pat.pattern}'")
        return CheckResult(decision, "; ".join(reasons))

    def add_user_allow(self, head_token: str) -> None:
        self.allow.add(head_token)
        existing = {}
        if Path(self.user_path).exists():
            with open(self.user_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        existing_allow = set(existing.get("allow", []))
        existing_allow.add(head_token)
        existing["allow"] = sorted(existing_allow)
        Path(self.user_path).parent.mkdir(parents=True, exist_ok=True)
        with open(self.user_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)
