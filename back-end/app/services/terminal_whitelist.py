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
        # Blacklist always wins
        for pat in self.blacklist:
            if pat.search(cmd_str):
                return CheckResult("block", f"matches blacklist pattern: {pat.pattern}")
        # Get head token
        try:
            tokens = shlex.split(cmd_str, posix=(shell != "powershell"))
        except ValueError:
            return CheckResult("confirm", "could not parse command")
        if not tokens:
            return CheckResult("block", "empty command")
        head = tokens[0]
        if head not in self.allow:
            return CheckResult("confirm", f"'{head}' not in whitelist")
        # Allowed head — check arg-pattern denies
        if head in self.deny_argpatterns:
            rest = cmd_str[len(head):]
            for pat in self.deny_argpatterns[head]:
                if pat.search(rest):
                    return CheckResult("confirm", f"argument pattern '{pat.pattern}' requires confirm")
        return CheckResult("allow", "")

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
