"""Tool registry for the AI agent."""

from app.tools.system_tools import get_system_time, read_file, list_directory, clear_memory
from app.tools.web_tools import search_web, web_scrape
from app.tools.screen_tools import capture_screen, analyze_screen
from app.tools.scheduler_tools import set_reminder, set_scheduled_task, cancel_task, list_tasks

# All available tools, registered for use by the agent
ALL_TOOLS = [
    get_system_time,
    read_file,
    list_directory,
    clear_memory,
    search_web,
    web_scrape,
    capture_screen,
    analyze_screen,
    set_reminder,
    set_scheduled_task,
    cancel_task,
    list_tasks,
]

# Map tool names to tool instances for dispatch
TOOL_MAP = {tool.name: tool for tool in ALL_TOOLS}
