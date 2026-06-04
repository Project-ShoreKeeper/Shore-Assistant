"""Unit tests for prune_profile — drops least-recently-updated top-level keys."""

import json

from app.services.memory.pruning import prune_profile


def _size(d: dict) -> int:
    return len(json.dumps(d, ensure_ascii=False).encode("utf-8"))


def test_empty_dict_returned_unchanged():
    assert prune_profile({}, {}, max_bytes=2048) == {}


def test_under_cap_returned_unchanged():
    data = {"name": "Luna"}
    out = prune_profile(data, {"name": 100.0}, max_bytes=2048)
    assert out == data


def test_drops_oldest_keys_until_under_cap():
    big = "x" * 800
    data = {"k1": big, "k2": big, "k3": big}
    ts_map = {"k1": 300.0, "k2": 200.0, "k3": 100.0}  # k3 oldest
    out = prune_profile(data, ts_map, max_bytes=2048)
    assert _size(out) <= 2048
    # Oldest keys should be dropped first
    assert "k1" in out  # newest survives


def test_nested_key_path_scores_under_top_level():
    big = "x" * 1500
    data = {"projects": {"shore": {"status": big}}, "tiny": "ok"}
    ts_map = {
        "projects.shore.status": 500.0,
        "tiny": 100.0,
    }
    # tiny is older, so it should be dropped first; projects should stay.
    out = prune_profile(data, ts_map, max_bytes=1540)
    assert "projects" in out
    assert "tiny" not in out


def test_keys_with_no_history_score_zero():
    big = "x" * 800
    data = {"old_no_history": big, "fresh": big}
    ts_map = {"fresh": 500.0}
    out = prune_profile(data, ts_map, max_bytes=1200)
    assert "fresh" in out
    assert "old_no_history" not in out


def test_single_huge_key_returns_empty_dict():
    """When the only top-level key alone exceeds the cap, return {} rather than blow the budget."""
    data = {"only": "x" * 5000}
    out = prune_profile(data, {"only": 100.0}, max_bytes=2048)
    assert out == {}
