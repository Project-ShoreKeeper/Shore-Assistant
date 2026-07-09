"""Shared contract for computer-use model formats."""

from dataclasses import dataclass
from typing import Callable, NamedTuple

from app.services.cua.actions import CuaCommand


class ParsedStep(NamedTuple):
    hint: str
    thought: str
    commands: list[CuaCommand]


ParseFn = Callable[[str, tuple[int, int], tuple[int, int]], ParsedStep]


def _identity(text: str) -> str:
    return text


@dataclass(frozen=True)
class CuaFormat:
    name: str
    model_label: str
    prompt_file: str
    instruction_template: str
    resize_factor: int
    wait_seconds: int
    extra_params: dict
    parse: ParseFn
    # Canonicalizes a raw model reply before it is replayed as assistant
    # history (e.g. dropping a reasoning model's <think> block).
    history_text: Callable[[str], str] = _identity
