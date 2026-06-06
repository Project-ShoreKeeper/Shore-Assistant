"""Unit tests for the allowlist parser + role resolver."""

import pytest

from app.core.allowlist import resolve_role, parse_allowlist


def test_first_email_is_admin():
    al = parse_allowlist("luna@x.com,bob@y.com")
    assert resolve_role("luna@x.com", al) == "admin"
    assert resolve_role("bob@y.com", al) == "user"


def test_case_insensitive_match():
    al = parse_allowlist("Luna@X.com")
    assert resolve_role("LUNA@x.COM", al) == "admin"


def test_whitespace_trimmed():
    al = parse_allowlist(" luna@x.com ,  bob@y.com  ")
    assert resolve_role("bob@y.com", al) == "user"


def test_empty_list_denies_everyone():
    al = parse_allowlist("")
    assert resolve_role("anyone@x.com", al) is None


def test_unknown_email_denied():
    al = parse_allowlist("luna@x.com")
    assert resolve_role("stranger@x.com", al) is None


def test_blank_entries_ignored():
    al = parse_allowlist("luna@x.com,, ,bob@y.com")
    assert len(al) == 2
    assert resolve_role("luna@x.com", al) == "admin"
    assert resolve_role("bob@y.com", al) == "user"
