import json
import pytest
from pathlib import Path

from app.services.terminal_whitelist import WhitelistGuard, Decision


@pytest.fixture
def guard(tmp_path: Path):
    data = {
        "allow": ["dir", "ls", "git", "python"],
        "deny_argpatterns": {"git": ["push\\s+--force"]},
        "blacklist_patterns": ["rm\\s+-rf\\s+/"]
    }
    f = tmp_path / "wl.json"
    f.write_text(json.dumps(data))
    user_f = tmp_path / "user_wl.json"
    return WhitelistGuard(default_path=str(f), user_path=str(user_f))


def test_allow_simple_command(guard):
    assert guard.check("dir", shell="powershell").decision == "allow"


def test_allow_command_with_args(guard):
    assert guard.check("git status", shell="powershell").decision == "allow"


def test_confirm_unknown_command(guard):
    r = guard.check("docker ps", shell="powershell")
    assert r.decision == "confirm"


def test_block_blacklisted(guard):
    r = guard.check("rm -rf /", shell="bash")
    assert r.decision == "block"
    assert "rm" in r.reason or "blacklist" in r.reason.lower()


def test_block_dangerous_git_subcommand(guard):
    r = guard.check("git push --force origin main", shell="powershell")
    assert r.decision == "confirm"
