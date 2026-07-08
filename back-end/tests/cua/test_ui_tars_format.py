import pytest

from app.services.cua.actions import CuaCommand, CuaParseError
from app.services.cua.formats import get_format
from app.services.cua.formats.ui_tars import parse

MODEL = (1400, 868)
SCREEN = (1440, 900)


def _resp(action, thought="I can see the OK button. I will click it."):
    return f"Thought: {thought}\nAction: {action}"


def test_registry_exposes_ui_tars():
    fmt = get_format("ui_tars")
    assert fmt.model_label == "ui-tars-1.5-7b"
    assert fmt.prompt_file == "computer_use_ui_tars.txt"
    assert fmt.resize_factor == 28
    assert fmt.wait_seconds == 5
    assert fmt.extra_params == {"frequency_penalty": 1.0}
    assert fmt.instruction_template.format(task="x").startswith(
        "## User Instruction"
    )


def test_click_point_projects_to_screen():
    step = parse(_resp("click(point='<point>700 434</point>')"), MODEL, SCREEN)
    assert step.commands == [CuaCommand(func="click", args={"x": 720, "y": 450})]


def test_hint_is_action_call_and_thought_is_captured():
    step = parse(_resp("click(point='<point>700 434</point>')"), MODEL, SCREEN)
    assert step.hint == "click(point='<point>700 434</point>')"
    assert "click it" in step.thought


def test_double_and_right_click_map():
    double = parse(_resp("left_double(point='<point>700 434</point>')"), MODEL, SCREEN)
    right = parse(_resp("right_single(point='<point>700 434</point>')"), MODEL, SCREEN)
    assert double.commands[0] == CuaCommand(func="doubleClick", args={"x": 720, "y": 450})
    assert right.commands[0] == CuaCommand(func="rightClick", args={"x": 720, "y": 450})


def test_drag_splits_into_move_and_drag():
    step = parse(
        _resp(
            "drag(start_point='<point>140 87</point>', "
            "end_point='<point>700 434</point>')"
        ),
        MODEL,
        SCREEN,
    )
    assert step.commands == [
        CuaCommand(func="moveTo", args={"x": 144, "y": 90}),
        CuaCommand(func="dragTo", args={"x": 720, "y": 450}),
    ]


def test_hotkey_splits_space_separated_keys():
    step = parse(_resp("hotkey(key='ctrl shift t')"), MODEL, SCREEN)
    assert step.commands == [
        CuaCommand(func="hotkey", args={"keys": ["ctrl", "shift", "t"]})
    ]


def test_type_writes_text():
    step = parse(_resp("type(content='hello world')"), MODEL, SCREEN)
    assert step.commands == [CuaCommand(func="write", args={"text": "hello world"})]


def test_type_trailing_newline_presses_enter():
    step = parse(_resp("type(content='hello\\n')"), MODEL, SCREEN)
    assert step.commands == [
        CuaCommand(func="write", args={"text": "hello"}),
        CuaCommand(func="press", args={"keys": ["enter"]}),
    ]


def test_type_only_newline_just_presses_enter():
    step = parse(_resp("type(content='\\n')"), MODEL, SCREEN)
    assert step.commands == [CuaCommand(func="press", args={"keys": ["enter"]})]


def test_scroll_directions():
    up = parse(_resp("scroll(point='<point>700 434</point>', direction='up')"), MODEL, SCREEN)
    down = parse(_resp("scroll(point='<point>700 434</point>', direction='down')"), MODEL, SCREEN)
    left = parse(_resp("scroll(point='<point>700 434</point>', direction='left')"), MODEL, SCREEN)
    right = parse(_resp("scroll(point='<point>700 434</point>', direction='right')"), MODEL, SCREEN)
    assert up.commands == [CuaCommand(func="scroll", args={"dy": 5, "x": 720, "y": 450})]
    assert down.commands[0].args == {"dy": -5, "x": 720, "y": 450}
    assert left.commands == [CuaCommand(func="hscroll", args={"dx": -5, "x": 720, "y": 450})]
    assert right.commands[0].args == {"dx": 5, "x": 720, "y": 450}


def test_wait_maps():
    step = parse(_resp("wait()"), MODEL, SCREEN)
    assert step.commands == [CuaCommand(func="wait", args={})]


def test_finished_terminates_success_with_answer():
    step = parse(_resp("finished(content='All set')"), MODEL, SCREEN)
    assert step.commands == [
        CuaCommand(func="terminate", args={}, status="success", answer="All set")
    ]


def test_finished_without_content():
    step = parse(_resp("finished()"), MODEL, SCREEN)
    cmd = step.commands[0]
    assert cmd.func == "terminate" and cmd.status == "success" and cmd.answer is None


def test_call_user_terminates_failure():
    step = parse(_resp("call_user()"), MODEL, SCREEN)
    cmd = step.commands[0]
    assert cmd.func == "terminate" and cmd.status == "failure"


def test_legacy_box_coordinate_form():
    step = parse(_resp("click(start_box='(700,434)')"), MODEL, SCREEN)
    assert step.commands == [CuaCommand(func="click", args={"x": 720, "y": 450})]


def test_multiple_calls_on_separate_lines():
    step = parse(_resp("click(point='<point>700 434</point>')\nwait()"), MODEL, SCREEN)
    assert [c.func for c in step.commands] == ["click", "wait"]


def test_fenced_action_block_is_unwrapped():
    text = "Thought: done thinking.\nAction: ```\nclick(point='<point>700 434</point>')\n```"
    step = parse(text, MODEL, SCREEN)
    assert step.commands[0].func == "click"


def test_missing_action_raises():
    with pytest.raises(CuaParseError):
        parse("Thought: hmm, there is no action here", MODEL, SCREEN)


def test_unknown_action_raises():
    with pytest.raises(CuaParseError):
        parse(_resp("os_system(cmd='rm -rf /')"), MODEL, SCREEN)


def test_non_literal_argument_raises():
    with pytest.raises(CuaParseError):
        parse(_resp("type(content=open('/etc/passwd').read())"), MODEL, SCREEN)


def test_click_without_coordinates_raises():
    with pytest.raises(CuaParseError):
        parse(_resp("click()"), MODEL, SCREEN)
