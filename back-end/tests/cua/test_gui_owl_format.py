import pytest

from app.services.cua.actions import CuaCommand, CuaParseError
from app.services.cua.formats import get_format
from app.services.cua.formats.gui_owl import parse

MODEL = (1400, 868)
SCREEN = (1440, 900)

THINK_REPLY = (
    "<think>The user wants the dialog closed. The right Action: click the OK "
    "button near the bottom.</think>\n"
    "Thought: I will click the OK button.\n"
    "Action: click(point='<point>700 434</point>')"
)


def test_parse_strips_think_block():
    step = parse(THINK_REPLY, MODEL, SCREEN)
    assert step.commands == [CuaCommand(func="click", args={"x": 720, "y": 450})]
    assert step.thought == "I will click the OK button."


def test_parse_plain_reply_unchanged():
    step = parse(
        "Thought: click it.\nAction: click(point='<point>700 434</point>')",
        MODEL,
        SCREEN,
    )
    assert step.commands == [CuaCommand(func="click", args={"x": 720, "y": 450})]


def test_parse_think_only_reply_raises():
    with pytest.raises(CuaParseError):
        parse("<think>still mulling it over</think>", MODEL, SCREEN)


def test_history_text_strips_think_block():
    fmt = get_format("gui_owl")
    assert fmt.history_text(THINK_REPLY) == (
        "Thought: I will click the OK button.\n"
        "Action: click(point='<point>700 434</point>')"
    )


def test_history_text_defaults_to_identity_for_other_formats():
    assert get_format("ui_tars").history_text("abc") == "abc"
    assert get_format("evocua").history_text("abc") == "abc"


def test_instruction_template_shared_with_ui_tars():
    gui_owl = get_format("gui_owl")
    ui_tars = get_format("ui_tars")
    assert gui_owl.instruction_template is ui_tars.instruction_template
