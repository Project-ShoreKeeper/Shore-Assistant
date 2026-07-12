import pytest

from app.services.computer_use_service import (
    ComputerUseAction, validate_action,
)
from app.services.ai_client.screenparse import ParsedElement, ParsedScreen


def _screen(n=2):
    els = [
        ParsedElement(id=i, type="icon", content=f"el{i}", interactable=True,
                      x1=0.1 * i, y1=0.1, x2=0.1 * i + 0.05, y2=0.15)
        for i in range(n)
    ]
    return ParsedScreen(elements=els, som_image_b64="", width=1920, height=1080,
                        latency_ms=1.0)


def test_action_parses_click():
    a = ComputerUseAction.model_validate(
        {"action": "click", "element_id": 1, "reason": "open menu"}
    )
    assert a.action == "click" and a.element_id == 1


def test_validate_click_ok():
    a = ComputerUseAction(action="click", element_id=1, reason="x")
    assert validate_action(a, _screen(2)) is None  # None = valid


def test_validate_click_out_of_range():
    a = ComputerUseAction(action="click", element_id=5, reason="x")
    err = validate_action(a, _screen(2))
    assert err is not None and "range" in err.lower()


def test_validate_click_missing_element():
    a = ComputerUseAction(action="click", reason="x")
    err = validate_action(a, _screen(2))
    assert err is not None and "element_id" in err


def test_validate_type_requires_text():
    a = ComputerUseAction(action="type", element_id=0, reason="x")
    err = validate_action(a, _screen(2))
    assert err is not None and "text" in err


def test_validate_hotkey_requires_keys():
    a = ComputerUseAction(action="hotkey", reason="x")
    err = validate_action(a, _screen(2))
    assert err is not None and "keys" in err


def test_validate_done_needs_nothing():
    a = ComputerUseAction(action="done", text="all done", reason="finished")
    assert validate_action(a, _screen(2)) is None


def test_validate_scroll_requires_amount():
    a = ComputerUseAction(action="scroll", reason="x")
    err = validate_action(a, _screen(2))
    assert err is not None and "scroll_amount" in err
