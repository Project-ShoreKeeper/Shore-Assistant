"""UI-TARS-1.5 format: ``Thought: ... / Action: call(...)`` replies."""

import ast
import re

from app.services.cua.actions import CuaCommand, CuaParseError, _project
from app.services.cua.formats.base import CuaFormat, ParsedStep

# Anchored to line starts so a "Thought:"/"Action:" mention inside the
# model's prose cannot hijack the section split.
_THOUGHT_RE = re.compile(
    r"^[ \t]*Thought:\s*(.+?)(?=\n[ \t]*Action:|\Z)", re.DOTALL | re.MULTILINE
)
_ACTION_RE = re.compile(r"^[ \t]*Action:\s*(.+)\Z", re.DOTALL | re.MULTILINE)
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")

_SCROLL_CLICKS = 5


def _coords(value) -> tuple[float, float]:
    numbers = _NUMBER_RE.findall(str(value))
    if len(numbers) < 2:
        raise CuaParseError(f"Cannot read coordinates from {value!r}.")
    return float(numbers[0]), float(numbers[1])


def _point(kwargs: dict, *names: str) -> tuple[float, float]:
    for name in names:
        if name in kwargs:
            return _coords(kwargs[name])
    raise CuaParseError(
        f"Action is missing a coordinate argument ({'/'.join(names)})."
    )


def _literal_kwargs(call: ast.Call) -> dict:
    kwargs: dict = {}
    for arg in call.args:
        raise CuaParseError(
            f"Positional arguments are not allowed in actions: {ast.dump(arg)}"
        )
    for keyword in call.keywords:
        if not keyword.arg:
            raise CuaParseError("**kwargs are not allowed in actions.")
        try:
            kwargs[keyword.arg] = ast.literal_eval(keyword.value)
        except (ValueError, SyntaxError) as exc:
            raise CuaParseError(
                f"Non-literal argument in action: {ast.dump(keyword.value)}"
            ) from exc
    return kwargs


def _clean_action(action_text: str) -> str:
    return _FENCE_RE.sub("", action_text.strip()).strip()


def _action_calls(action_text: str) -> list[ast.Call]:
    cleaned = _clean_action(action_text)
    try:
        tree = ast.parse(cleaned)
    except SyntaxError as exc:
        raise CuaParseError(f"Action is not a valid call: {exc}") from exc
    calls: list[ast.Call] = []
    for node in tree.body:
        if (
            not isinstance(node, ast.Expr)
            or not isinstance(node.value, ast.Call)
            or not isinstance(node.value.func, ast.Name)
        ):
            raise CuaParseError(
                f"Only bare action calls are allowed, got: {ast.dump(node)[:80]}"
            )
        calls.append(node.value)
    if not calls:
        raise CuaParseError("Action section contained no call.")
    return calls


def parse(
    text: str,
    model_size: tuple[int, int],
    screen_size: tuple[int, int],
) -> ParsedStep:
    action_match = _ACTION_RE.search(text or "")
    if not action_match:
        raise CuaParseError("Model response has no Action section.")
    thought_match = _THOUGHT_RE.search(text or "")
    thought = thought_match.group(1).strip() if thought_match else ""
    action_text = action_match.group(1).strip()
    hint = _clean_action(action_text).splitlines()[0].strip()

    commands: list[CuaCommand] = []
    for call in _action_calls(action_text):
        name = call.func.id
        kwargs = _literal_kwargs(call)

        if name in ("click", "left_double", "right_single"):
            func = {
                "click": "click",
                "left_double": "doubleClick",
                "right_single": "rightClick",
            }[name]
            x, y = _project(
                *_point(kwargs, "point", "start_box"), model_size, screen_size
            )
            commands.append(CuaCommand(func=func, args={"x": x, "y": y}))
        elif name == "drag":
            start = _project(
                *_point(kwargs, "start_point", "start_box"),
                model_size,
                screen_size,
            )
            end = _project(
                *_point(kwargs, "end_point", "end_box"),
                model_size,
                screen_size,
            )
            commands.append(
                CuaCommand(func="moveTo", args={"x": start[0], "y": start[1]})
            )
            commands.append(
                CuaCommand(func="dragTo", args={"x": end[0], "y": end[1]})
            )
        elif name == "hotkey":
            keys = str(kwargs.get("key", "")).split()
            if not keys:
                raise CuaParseError("hotkey requires a key argument.")
            commands.append(CuaCommand(func="hotkey", args={"keys": keys}))
        elif name == "type":
            content = str(kwargs.get("content", ""))
            if not content:
                raise CuaParseError("type requires non-empty content.")
            stripped = content.rstrip("\n")
            if stripped:
                commands.append(CuaCommand(func="write", args={"text": stripped}))
            if content != stripped:
                commands.append(CuaCommand(func="press", args={"keys": ["enter"]}))
        elif name == "scroll":
            direction = str(kwargs.get("direction", "")).lower()
            if direction not in ("up", "down", "left", "right"):
                raise CuaParseError(
                    "scroll direction must be up/down/left/right, "
                    f"got {direction!r}."
                )
            args: dict = (
                {"dy": _SCROLL_CLICKS if direction == "up" else -_SCROLL_CLICKS}
                if direction in ("up", "down")
                else {"dx": _SCROLL_CLICKS if direction == "right" else -_SCROLL_CLICKS}
            )
            func = "scroll" if direction in ("up", "down") else "hscroll"
            if "point" in kwargs or "start_box" in kwargs:
                x, y = _project(
                    *_point(kwargs, "point", "start_box"),
                    model_size,
                    screen_size,
                )
                args["x"] = x
                args["y"] = y
            commands.append(CuaCommand(func=func, args=args))
        elif name == "wait":
            commands.append(CuaCommand(func="wait", args={}))
        elif name == "finished":
            answer = kwargs.get("content")
            commands.append(
                CuaCommand(
                    func="terminate",
                    args={},
                    status="success",
                    answer=str(answer) if answer is not None else None,
                )
            )
        elif name == "call_user":
            commands.append(
                CuaCommand(
                    func="terminate",
                    args={},
                    status="failure",
                    answer="the model asked for user help",
                )
            )
        else:
            raise CuaParseError(f"Disallowed action: {name}")

    return ParsedStep(hint=hint, thought=thought, commands=commands)


FORMAT = CuaFormat(
    name="ui_tars",
    model_label="ui-tars-1.5-7b",
    prompt_file="computer_use_ui_tars.txt",
    instruction_template="## User Instruction\n{task}\n",
    resize_factor=28,
    wait_seconds=5,
    extra_params={"frequency_penalty": 1.0},
    parse=parse,
)
