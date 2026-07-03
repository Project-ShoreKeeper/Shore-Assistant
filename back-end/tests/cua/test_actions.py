import pytest

from app.services.cua.actions import (
    CuaCommand,
    CuaParseError,
    code_to_commands,
    parse_cua_response,
    smart_resize,
)

RESPONSE = """# Step: 3
## Thought:
I can see the Settings window. I should click the search field.
## Action:
Click the search field at the top of System Settings.
## Code:
```python
pyautogui.click(x=412, y=88)
```"""


def test_parse_cua_response_extracts_hint_and_code():
    hint, code = parse_cua_response(RESPONSE)
    assert hint == "Click the search field at the top of System Settings."
    assert code == "pyautogui.click(x=412, y=88)"


def test_parse_cua_response_uses_last_code_block():
    text = RESPONSE + '\n```code\ncomputer.terminate(status="success")\n```'
    _, code = parse_cua_response(text)
    assert code == 'computer.terminate(status="success")'


def test_parse_cua_response_without_code_raises():
    with pytest.raises(CuaParseError):
        parse_cua_response("## Thought:\nno code here")


def test_smart_resize_bounds():
    h, w = smart_resize(900, 1440, factor=32)
    assert h % 32 == 0 and w % 32 == 0
    assert 3136 <= h * w <= 12845056


def test_click_projects_model_coords_to_screen():
    model_h, model_w = smart_resize(900, 1440, factor=32)
    cmds = code_to_commands(
        f"pyautogui.click(x={model_w}, y={model_h})",
        model_size=(model_w, model_h),
        screen_size=(1440, 900),
    )
    assert cmds == [CuaCommand(func="click", args={"x": 1440, "y": 900})]


def test_normalized_coords_scale_by_screen():
    cmds = code_to_commands(
        "pyautogui.click(x=0.5, y=0.5)",
        model_size=(1024, 640),
        screen_size=(1440, 900),
    )
    assert cmds[0].args == {"x": 720, "y": 450}


def test_write_press_hotkey_scroll():
    code = "\n".join(
        [
            "pyautogui.write('hello')",
            "pyautogui.press('enter')",
            "pyautogui.hotkey('command', 'c')",
            "pyautogui.scroll(-3)",
        ]
    )
    cmds = code_to_commands(
        code,
        model_size=(1024, 640),
        screen_size=(1440, 900),
    )
    assert [c.func for c in cmds] == ["write", "press", "hotkey", "scroll"]
    assert cmds[0].args == {"text": "hello"}
    assert cmds[1].args == {"keys": ["enter"]}
    assert cmds[2].args == {"keys": ["command", "c"]}
    assert cmds[3].args == {"dy": -3}


def test_terminate_and_wait():
    cmds = code_to_commands(
        'computer.terminate(status="failure", answer="Dialog blocked")',
        model_size=(1024, 640),
        screen_size=(1440, 900),
    )
    assert cmds == [
        CuaCommand(
            func="terminate",
            args={},
            status="failure",
            answer="Dialog blocked",
        )
    ]
    cmds = code_to_commands(
        "computer.wait()",
        model_size=(1024, 640),
        screen_size=(1440, 900),
    )
    assert cmds == [CuaCommand(func="wait", args={})]


def test_disallowed_call_raises():
    with pytest.raises(CuaParseError):
        code_to_commands(
            "import os; os.system('rm -rf /')",
            model_size=(1024, 640),
            screen_size=(1440, 900),
        )
    with pytest.raises(CuaParseError):
        code_to_commands(
            "pyautogui.screenshot()",
            model_size=(1024, 640),
            screen_size=(1440, 900),
        )
