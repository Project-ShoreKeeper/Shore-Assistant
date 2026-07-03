"""Pure parsing/projection helpers for the EvoCUA computer-use loop.

Ported from meituan/EvoCUA ``mm_agents/evocua/`` (Apache-2.0). The model
answers in ``## Thought / ## Action / ## Code`` sections; the last fenced
code block carries a constrained PyAutoGUI subset or a ``computer.*`` control
call. Coordinates are relative to the smart-resized model image (factor 32)
or normalized 0..1; both project onto the client's logical screen size.
"""

import ast
import base64
import io
import math
import re
from dataclasses import dataclass, field

from PIL import Image


class CuaParseError(Exception):
    """Raised when an EvoCUA response cannot be safely executed."""


@dataclass(frozen=True)
class CuaCommand:
    func: str
    args: dict = field(default_factory=dict)
    status: str | None = None
    answer: str | None = None


_CODE_BLOCK_RE = re.compile(
    r"```(?:code|python)?\s*(.*?)\s*```",
    re.DOTALL | re.IGNORECASE,
)
_ACTION_RE = re.compile(r"##\s*Action:\s*\n(.+?)(?:\n##|\Z)", re.DOTALL)

# pyautogui verb -> positional parameter names (subset we execute)
_PARAMS: dict[str, list[str]] = {
    "click": ["x", "y"],
    "doubleClick": ["x", "y"],
    "tripleClick": ["x", "y"],
    "rightClick": ["x", "y"],
    "middleClick": ["x", "y"],
    "moveTo": ["x", "y"],
    "dragTo": ["x", "y"],
    "scroll": ["clicks"],
    "hscroll": ["clicks"],
    "write": ["message"],
    "press": ["keys"],
    "hotkey": [],  # varargs
    "keyDown": ["key"],
    "keyUp": ["key"],
}
_COORD_FUNCS = {
    "click",
    "doubleClick",
    "tripleClick",
    "rightClick",
    "middleClick",
    "moveTo",
    "dragTo",
}


def smart_resize(
    height: int,
    width: int,
    factor: int = 32,
    min_pixels: int = 3136,
    max_pixels: int = 12845056,
) -> tuple[int, int]:
    """Round dimensions to ``factor`` and clamp their total pixel count."""
    h_bar = max(factor, round(height / factor) * factor)
    w_bar = max(factor, round(width / factor) * factor)
    if h_bar * w_bar > max_pixels:
        beta = math.sqrt((height * width) / max_pixels)
        h_bar = math.floor(height / beta / factor) * factor
        w_bar = math.floor(width / beta / factor) * factor
    elif h_bar * w_bar < min_pixels:
        beta = math.sqrt(min_pixels / (height * width))
        h_bar = math.ceil(height * beta / factor) * factor
        w_bar = math.ceil(width * beta / factor) * factor
    return h_bar, w_bar


def process_screenshot(
    data_url: str,
    factor: int = 32,
) -> tuple[str, int, int]:
    """Resize a captured frame and return a JPEG data URL plus width/height."""
    payload = data_url.split(",", 1)[1] if "," in data_url else data_url
    img = Image.open(io.BytesIO(base64.b64decode(payload))).convert("RGB")
    height, width = smart_resize(img.height, img.width, factor=factor)
    img = img.resize((width, height))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}", width, height


def parse_cua_response(text: str) -> tuple[str, str]:
    """Extract the human-readable action hint and last fenced code block."""
    blocks = _CODE_BLOCK_RE.findall(text or "")
    if not blocks:
        raise CuaParseError("Model response contains no code block.")
    action = _ACTION_RE.search(text or "")
    hint = action.group(1).strip().splitlines()[0].strip() if action else ""
    return hint, blocks[-1].strip()


def _project(
    x: float,
    y: float,
    model_size: tuple[int, int],
    screen_size: tuple[int, int],
) -> tuple[int, int]:
    model_width, model_height = model_size
    screen_width, screen_height = screen_size
    if 0 <= x <= 1 and 0 <= y <= 1:
        return round(x * screen_width), round(y * screen_height)
    return (
        round(x / model_width * screen_width),
        round(y / model_height * screen_height),
    )


def _literal(node: ast.expr):
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError) as exc:
        raise CuaParseError(
            f"Non-literal argument in action code: {ast.dump(node)}"
        ) from exc


def code_to_commands(
    code: str,
    model_size: tuple[int, int],
    screen_size: tuple[int, int],
) -> list[CuaCommand]:
    """Parse the allowed call subset without evaluating model-authored code."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise CuaParseError(f"Action code is not valid Python: {exc}") from exc

    commands: list[CuaCommand] = []
    for node in tree.body:
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            raise CuaParseError(
                f"Only bare calls are allowed, got: {ast.dump(node)[:80]}"
            )
        call = node.value
        target = ast.unparse(call.func)

        if target in ("computer.wait", "computer.terminate", "computer.answer"):
            kwargs = {
                keyword.arg: _literal(keyword.value)
                for keyword in call.keywords
                if keyword.arg
            }
            if target == "computer.wait":
                commands.append(CuaCommand(func="wait"))
            else:
                commands.append(
                    CuaCommand(
                        func="terminate",
                        status=str(kwargs.get("status", "success")),
                        answer=(
                            str(kwargs["answer"]) if "answer" in kwargs else None
                        ),
                    )
                )
            continue

        if not target.startswith("pyautogui."):
            raise CuaParseError(f"Disallowed call: {target}")
        func = target.split(".", 1)[1]
        if func not in _PARAMS:
            raise CuaParseError(f"Disallowed call: {target}")

        names = _PARAMS[func]
        kwargs: dict = {}
        for index, arg in enumerate(call.args):
            if func == "hotkey":
                kwargs.setdefault("keys", []).append(str(_literal(arg)))
            elif index < len(names):
                kwargs[names[index]] = _literal(arg)
        for keyword in call.keywords:
            if keyword.arg:
                kwargs[keyword.arg] = _literal(keyword.value)

        if func in _COORD_FUNCS:
            if "x" not in kwargs or "y" not in kwargs:
                raise CuaParseError(f"{func} requires x and y.")
            x, y = _project(
                float(kwargs["x"]),
                float(kwargs["y"]),
                model_size,
                screen_size,
            )
            commands.append(CuaCommand(func=func, args={"x": x, "y": y}))
        elif func in ("scroll", "hscroll"):
            clicks = int(kwargs.get("clicks", 0))
            key = "dy" if func == "scroll" else "dx"
            commands.append(CuaCommand(func=func, args={key: clicks}))
        elif func == "write":
            commands.append(
                CuaCommand(
                    func="write",
                    args={"text": str(kwargs.get("message", ""))},
                )
            )
        elif func == "press":
            keys = kwargs.get("keys", "")
            key_list = [keys] if isinstance(keys, str) else [str(k) for k in keys]
            presses = int(kwargs.get("presses", 1))
            commands.append(
                CuaCommand(func="press", args={"keys": key_list * presses})
            )
        elif func == "hotkey":
            commands.append(
                CuaCommand(func="hotkey", args={"keys": kwargs.get("keys", [])})
            )
        elif func in ("keyDown", "keyUp"):
            commands.append(
                CuaCommand(
                    func=func,
                    args={"keys": [str(kwargs.get("key", ""))]},
                )
            )

    if not commands:
        raise CuaParseError("Action code contained no executable call.")
    return commands
