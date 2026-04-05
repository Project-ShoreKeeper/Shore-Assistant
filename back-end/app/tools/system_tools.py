"""System-level tools for the AI agent."""

import os
from datetime import datetime
from langchain_core.tools import tool


@tool
def get_system_time() -> str:
    """Get the current system date and time."""
    now = datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S (%A)")


@tool
def read_file(file_path: str) -> str:
    """Read the contents of a file on the local system.

    Args:
        file_path: Absolute or relative path to the file to read.
    """
    path = os.path.expanduser(file_path)
    if not os.path.isfile(path):
        return f"Error: File not found: {path}"
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(10000)  # Limit to 10KB
        if len(content) == 10000:
            content += "\n... (truncated)"
        return content
    except Exception as e:
        return f"Error reading file: {e}"


@tool
def list_directory(directory_path: str = ".") -> str:
    """List files and directories in a given path.

    Args:
        directory_path: Path to the directory to list. Defaults to current directory.
    """
    path = os.path.expanduser(directory_path)
    if not os.path.isdir(path):
        return f"Error: Directory not found: {path}"
    try:
        entries = os.listdir(path)
        entries.sort()
        result = []
        for entry in entries[:50]:  # Limit to 50 entries
            full_path = os.path.join(path, entry)
            prefix = "[DIR] " if os.path.isdir(full_path) else "      "
            result.append(f"{prefix}{entry}")
        if len(entries) > 50:
            result.append(f"... and {len(entries) - 50} more")
        return "\n".join(result)
    except Exception as e:
        return f"Error listing directory: {e}"
