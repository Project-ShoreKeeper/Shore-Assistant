"""Tool registry for the AI agent."""

from app.tools.system_tools import get_system_time, read_file, list_directory, clear_memory
from app.tools.web_tools import search_web, web_scrape
from app.tools.screen_tools import capture_screen, analyze_screen
from app.tools.scheduler_tools import set_reminder, set_scheduled_task, cancel_task, list_tasks
from app.tools.n8n_workflow_tools import (
    n8n_search_nodes,
    n8n_get_node_schema,
    n8n_search_workflow_templates,
    n8n_create_workflow,
    n8n_build_complex_workflow,
    n8n_manage_workflows,
)

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
    n8n_search_nodes,
    n8n_get_node_schema,
    n8n_search_workflow_templates,
    n8n_create_workflow,
    n8n_build_complex_workflow,
    n8n_manage_workflows,
]

# Map tool names to tool instances for dispatch
TOOL_MAP = {tool.name: tool for tool in ALL_TOOLS}


def register_dynamic_tools(tools: list):
    """Add dynamically discovered tools (e.g. n8n workflows) to the registry."""
    for tool in tools:
        if tool.name not in TOOL_MAP:
            ALL_TOOLS.append(tool)
            TOOL_MAP[tool.name] = tool


def unregister_dynamic_tools(prefix: str = "n8n_"):
    """Remove all dynamic tools with the given prefix."""
    to_remove = [t for t in ALL_TOOLS if t.name.startswith(prefix)]
    for t in to_remove:
        ALL_TOOLS.remove(t)
        TOOL_MAP.pop(t.name, None)
