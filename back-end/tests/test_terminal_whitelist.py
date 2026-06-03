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


def test_chained_all_allowed(guard):
    r = guard.check("dir && ls", shell="powershell")
    assert r.decision == "allow"


def test_chained_one_unknown_needs_confirm(guard):
    r = guard.check("dir && docker ps", shell="powershell")
    assert r.decision == "confirm"


def test_chained_one_blacklisted_blocks(guard):
    r = guard.check("dir; rm -rf /", shell="bash")
    assert r.decision == "block"


def test_unwraps_powershell_dash_c(guard):
    r = guard.check('powershell -c "git status"', shell="powershell")
    assert r.decision == "allow"


def test_unwraps_cmd_slash_c(guard):
    r = guard.check('cmd /c "dir"', shell="cmd")
    assert r.decision == "allow"


def test_unwraps_bash_dash_c(guard):
    r = guard.check('bash -c "ls -la"', shell="bash")
    assert r.decision == "allow"


def test_user_allow_persists(guard, tmp_path):
    guard.add_user_allow("docker")
    assert guard.check("docker ps", shell="powershell").decision == "allow"
    # Reload from disk
    from app.services.terminal_whitelist import WhitelistGuard
    fresh = WhitelistGuard(default_path=guard.default_path, user_path=guard.user_path)
    assert fresh.check("docker ps", shell="powershell").decision == "allow"
