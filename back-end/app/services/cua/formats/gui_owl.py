"""GUI-Owl-1.5 format.

GUI-Owl is trained as a native GUI agent. In Shore we constrain it to the same
small Python-like action surface as UI-TARS so the desktop executor remains
unchanged and auditable.
"""

from app.services.cua.formats.base import CuaFormat, ParsedStep
from app.services.cua.formats import ui_tars

_INSTRUCTION_TEMPLATE = "## User Instruction\n{task}\n"


def parse(
    text: str,
    model_size: tuple[int, int],
    screen_size: tuple[int, int],
) -> ParsedStep:
    return ui_tars.parse(text, model_size, screen_size)


FORMAT = CuaFormat(
    name="gui_owl",
    model_label="gui-owl-1.5-8b-think",
    prompt_file="computer_use_gui_owl.txt",
    instruction_template=_INSTRUCTION_TEMPLATE,
    resize_factor=28,
    wait_seconds=5,
    extra_params={"temperature": 0.0},
    parse=parse,
)
