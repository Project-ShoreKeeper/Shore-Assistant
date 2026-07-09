"""GUI-Owl-1.5 format.

GUI-Owl is trained as a native GUI agent. In Shore we constrain it to the same
small Python-like action surface as UI-TARS so the desktop executor remains
unchanged and auditable. The served checkpoint is a reasoning ("Think")
variant with its own reply layout: an optional ``<think>...</think>`` block,
an ``Action:`` line holding a prose summary (not the call), and the actual
executable call inside ``<tool_call>...</tool_call>`` tags. The think block
is stripped before parsing and before the reply is replayed as history; the
tool-call body is parsed with the UI-TARS grammar.
"""

import re

from app.services.cua.actions import CuaParseError
from app.services.cua.formats import ui_tars
from app.services.cua.formats.base import CuaFormat, ParsedStep

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*(.*?)\s*(?:</tool_call>|\Z)", re.DOTALL
)
_SUMMARY_LABEL_RE = re.compile(r"^\s*(?:Thought|Action):\s*")


def _strip_reasoning(text: str) -> str:
    return _THINK_RE.sub("", text or "").strip()


def parse(
    text: str,
    model_size: tuple[int, int],
    screen_size: tuple[int, int],
) -> ParsedStep:
    cleaned = _strip_reasoning(text)
    match = _TOOL_CALL_RE.search(cleaned)
    if not match:
        return ui_tars.parse(cleaned, model_size, screen_size)
    calls_text = match.group(1).strip()
    if not calls_text:
        raise CuaParseError(
            "Model reply has an empty <tool_call> block. If llama-server "
            "runs with --jinja it strips the body; serve GUI-Owl without "
            "--jinja."
        )
    step = ui_tars.parse(f"Action: {calls_text}", model_size, screen_size)
    summary = _SUMMARY_LABEL_RE.sub("", cleaned[: match.start()]).strip()
    return ParsedStep(hint=step.hint, thought=summary, commands=step.commands)


FORMAT = CuaFormat(
    name="gui_owl",
    model_label="gui-owl-1.5-8b-think",
    prompt_file="computer_use_gui_owl.txt",
    instruction_template=ui_tars.FORMAT.instruction_template,
    resize_factor=28,
    wait_seconds=5,
    # temperature is already pinned to 0.0 by CuaClient; UI-TARS's
    # frequency_penalty is deliberately not carried over — a per-token
    # penalty punishes long reasoning traces.
    extra_params={},
    parse=parse,
    history_text=_strip_reasoning,
)
