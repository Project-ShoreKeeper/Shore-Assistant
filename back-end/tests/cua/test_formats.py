import pytest

from app.services.cua.actions import CuaCommand
from app.services.cua.formats import get_format

EVOCUA_RESPONSE = """# Step: 3
## Thought:
I can see the Settings window. I should click the search field.
## Action:
Click the search field at the top of System Settings.
## Code:
```python
pyautogui.click(x=512, y=320)
```"""


def test_get_format_evocua():
    fmt = get_format("evocua")
    assert fmt.name == "evocua"
    assert fmt.model_label == "evocua-8b"
    assert fmt.prompt_file == "computer_use.txt"
    assert fmt.resize_factor == 32
    assert fmt.wait_seconds == 20
    assert fmt.extra_params == {}
    assert "# Task Instruction:" in fmt.instruction_template.format(task="x")


def test_get_format_unknown_raises():
    with pytest.raises(ValueError, match="Unknown CUA_MODEL_FORMAT"):
        get_format("bogus")


def test_get_format_gui_owl():
    fmt = get_format("gui_owl")
    assert fmt.name == "gui_owl"
    assert fmt.model_label == "gui-owl-1.5-8b-think"
    assert fmt.prompt_file == "computer_use_gui_owl.txt"
    assert fmt.resize_factor == 28
    assert fmt.wait_seconds == 5
    assert fmt.extra_params == {}
    assert fmt.instruction_template.format(task="x").startswith(
        "## User Instruction"
    )


def test_evocua_parse_returns_hint_thought_commands():
    fmt = get_format("evocua")
    step = fmt.parse(EVOCUA_RESPONSE, (1024, 640), (1440, 900))
    assert step.hint == "Click the search field at the top of System Settings."
    assert "Settings window" in step.thought
    assert step.commands == [CuaCommand(func="click", args={"x": 720, "y": 450})]


def test_settings_default_format():
    from app.core.config import settings

    assert settings.CUA_MODEL_FORMAT == "evocua"
