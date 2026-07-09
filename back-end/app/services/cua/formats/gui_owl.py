"""GUI-Owl-1.5 format.

GUI-Owl is trained as a native GUI agent. In Shore we constrain it to the same
small Python-like action surface as UI-TARS so the desktop executor remains
unchanged and auditable. The served checkpoint is a reasoning ("Think")
variant: replies may open with a ``<think>...</think>`` block, which is
stripped both before parsing and before the reply is replayed as history.
"""

import re

from app.services.cua.formats import ui_tars
from app.services.cua.formats.base import CuaFormat, ParsedStep

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _strip_reasoning(text: str) -> str:
    return _THINK_RE.sub("", text or "").strip()


def parse(
    text: str,
    model_size: tuple[int, int],
    screen_size: tuple[int, int],
) -> ParsedStep:
    return ui_tars.parse(_strip_reasoning(text), model_size, screen_size)


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
