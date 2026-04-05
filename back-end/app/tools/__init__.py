"""Tool registry for the AI agent."""

from app.tools.system_tools import get_system_time, read_file, list_directory
from app.tools.web_tools import search_web, web_scrape
from app.tools.screen_tools import capture_screen, analyze_screen

# All available tools, registered for use by the agent
ALL_TOOLS = [
    get_system_time,
    read_file,
    list_directory,
    search_web,
    web_scrape,
    capture_screen,
    analyze_screen,
]

# Map tool names to tool instances for dispatch
TOOL_MAP = {tool.name: tool for tool in ALL_TOOLS}
