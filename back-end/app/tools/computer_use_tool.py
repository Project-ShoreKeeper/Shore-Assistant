"""LangChain tool for delegating GUI tasks to the EvoCUA sub-agent."""

from langchain_core.tools import tool

from app.core.auth import current_user_role
from app.core.config import settings
from app.services.cua.service import computer_use_service


@tool
async def computer_use(task: str, max_steps: int = 0) -> str:
    """Perform a task on the user's computer screen by controlling the mouse
    and keyboard (click, type, scroll). Use this when the user asks Shore to
    operate an application or the OS for them. Describe ONE concrete,
    self-contained task, e.g. "open System Settings and enable Night Shift".
    Requires the desktop app with Screen access enabled.

    Args:
        task: Concrete GUI task to perform, in plain language.
        max_steps: Optional cap on actions (defaults to the server limit).
    """
    if current_user_role.get() != "admin":
        return "Computer use is restricted to the admin user."
    if not computer_use_service.ready:
        return (
            "Computer use requires the desktop app with Screen access "
            "enabled. Ask the user to open the desktop app and enable it."
        )
    if computer_use_service.running:
        return (
            "A computer-use run is already in progress. Wait for it to finish."
        )
    steps = (
        max_steps
        if 0 < max_steps <= settings.CUA_MAX_STEPS
        else settings.CUA_MAX_STEPS
    )
    return await computer_use_service.run(task, steps)
