"""Unit tests for the pure co-pilot gating helpers."""
import numpy as np

from app.services.copilot_service import NOOP_SENTINEL, norm_abs_diff, should_trigger


def test_norm_abs_diff_identical_is_zero():
    a = np.zeros((4, 4), dtype=np.uint8)
    assert norm_abs_diff(a, a) == 0.0


def test_norm_abs_diff_full_swing_is_one():
    a = np.zeros((2, 2), dtype=np.uint8)
    b = np.full((2, 2), 255, dtype=np.uint8)
    assert norm_abs_diff(a, b) == 1.0


def test_norm_abs_diff_none_baseline_is_one():
    a = np.zeros((2, 2), dtype=np.uint8)
    assert norm_abs_diff(a, None) == 1.0
    assert norm_abs_diff(None, a) == 1.0


def test_norm_abs_diff_shape_mismatch_is_one():
    a = np.zeros((2, 2), dtype=np.uint8)
    b = np.zeros((3, 3), dtype=np.uint8)
    assert norm_abs_diff(a, b) == 1.0


_GATE = dict(change_threshold=0.06, idle_threshold=3.0, cooldown=45.0)


def test_should_trigger_all_gates_pass():
    assert should_trigger(0.2, 5.0, 100.0, busy=False, **_GATE) is True


def test_should_trigger_busy_blocks():
    assert should_trigger(0.2, 5.0, 100.0, busy=True, **_GATE) is False


def test_should_trigger_cooldown_blocks():
    assert should_trigger(0.2, 5.0, 10.0, busy=False, **_GATE) is False


def test_should_trigger_static_screen_blocks():
    assert should_trigger(0.01, 5.0, 100.0, busy=False, **_GATE) is False


def test_should_trigger_still_typing_blocks():
    assert should_trigger(0.2, 1.0, 100.0, busy=False, **_GATE) is False


def test_should_trigger_idle_unknown_skips_idle_gate():
    assert should_trigger(0.2, None, 100.0, busy=False, **_GATE) is True


def test_noop_sentinel_value():
    assert NOOP_SENTINEL == "__NOOP__"
