"""EvoCUA-8B format: ``## Thought / ## Action / ## Code`` replies."""

from app.services.cua.actions import code_to_commands, parse_cua_response
from app.services.cua.formats.base import CuaFormat, ParsedStep

_INSTRUCTION_TEMPLATE = (
    "# Task Instruction:\n{task}\n\n"
    "Please generate the next move according to the screenshot, task "
    "instruction and previous steps (if provided).\n"
)


def _extract_thought(response: str) -> str:
    """Pull the ``## Thought:`` section from an EvoCUA response."""
    marker = "## Thought:"
    start = response.find(marker)
    if start == -1:
        return ""
    rest = response[start + len(marker):]
    end = rest.find("## Action:")
    return (rest if end == -1 else rest[:end]).strip()


def parse(
    text: str,
    model_size: tuple[int, int],
    screen_size: tuple[int, int],
) -> ParsedStep:
    hint, code = parse_cua_response(text)
    commands = code_to_commands(code, model_size, screen_size)
    return ParsedStep(
        hint=hint,
        thought=_extract_thought(text),
        commands=commands,
    )


FORMAT = CuaFormat(
    name="evocua",
    model_label="evocua-8b",
    prompt_file="computer_use.txt",
    instruction_template=_INSTRUCTION_TEMPLATE,
    resize_factor=32,
    wait_seconds=20,
    extra_params={},
    parse=parse,
)
