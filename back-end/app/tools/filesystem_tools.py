"""Filesystem tools backed by the file_tool System Core (Rust binary).

Each tool POSTs to file_tool and returns the raw ToolEnvelope JSON string.
The agent's execute_tool() unwraps the envelope before handing it to the LLM,
so these wrappers stay thin — they only marshal arguments.

All paths are workspace-relative; the workspace root is fixed by the
`--workspace` flag passed when file_tool was started.
"""

import json

from langchain_core.tools import tool

from app.services.file_tool_client import file_tool_client


@tool
async def ft_read_file(path: str) -> str:
    """Read a file inside the workspace and return its content with metadata
    (size, line count, encoding, git status, whether it was truncated).

    Args:
        path: Workspace-relative path, e.g. "src/main.py".
    """
    envelope = await file_tool_client.post("/api/filesystem/read", {"path": path})
    return json.dumps(envelope, ensure_ascii=False)


@tool
async def ft_list_directory(path: str = ".") -> str:
    """List files and directories inside the workspace. Each entry includes its
    type, size, and git status.

    Args:
        path: Workspace-relative directory, e.g. "src/". Defaults to the workspace root.
    """
    envelope = await file_tool_client.post("/api/filesystem/list", {"path": path})
    return json.dumps(envelope, ensure_ascii=False)


@tool
async def ft_search_files(
    query: str,
    regex: bool = False,
    include: str = "",
    ignore_case: bool = False,
    context: int = 1,
) -> str:
    """Search file contents across the workspace. Respects .gitignore. Supports
    literal or regex matching with optional glob filtering and context lines.

    Args:
        query: Search string, or a regex pattern when regex=True.
        regex: Treat query as a regular expression.
        include: Glob filter to limit which files are searched, e.g. "*.py".
        ignore_case: Case-insensitive matching.
        context: Number of context lines to show before/after each match.
    """
    body: dict = {
        "query": query,
        "regex": regex,
        "ignore_case": ignore_case,
        "context": context,
    }
    if include:
        body["include"] = include
    envelope = await file_tool_client.post("/api/filesystem/search", body)
    return json.dumps(envelope, ensure_ascii=False)


@tool
async def ft_file_exists(path: str) -> str:
    """Check whether a file or directory exists inside the workspace.

    Args:
        path: Workspace-relative path, e.g. "src/config.json".
    """
    envelope = await file_tool_client.post("/api/filesystem/exists", {"path": path})
    return json.dumps(envelope, ensure_ascii=False)


@tool
async def ft_write_file(path: str, content: str) -> str:
    """Write content to a file inside the workspace. The previous version is
    automatically backed up to .agent_backups/ before overwriting, so this is
    reversible. Creates the file if it does not exist.

    Args:
        path: Workspace-relative path, e.g. "src/config.json".
        content: Full new content of the file.
    """
    envelope = await file_tool_client.post(
        "/api/filesystem/write", {"path": path, "content": content}
    )
    return json.dumps(envelope, ensure_ascii=False)


@tool
async def ft_create_directory(path: str) -> str:
    """Create a directory (and any missing parents) inside the workspace.

    Args:
        path: Workspace-relative directory path, e.g. "src/new_module/".
    """
    envelope = await file_tool_client.post("/api/filesystem/create-dir", {"path": path})
    return json.dumps(envelope, ensure_ascii=False)


@tool
async def ft_move_file(src: str, dst: str, force: bool = False) -> str:
    """Move or rename a file inside the workspace.

    Args:
        src: Source workspace-relative path.
        dst: Destination workspace-relative path.
        force: Overwrite the destination if it already exists.
    """
    envelope = await file_tool_client.post(
        "/api/filesystem/move", {"src": src, "dst": dst, "force": force}
    )
    return json.dumps(envelope, ensure_ascii=False)


@tool
async def ft_copy_file(src: str, dst: str, force: bool = False) -> str:
    """Copy a file inside the workspace.

    Args:
        src: Source workspace-relative path.
        dst: Destination workspace-relative path.
        force: Overwrite the destination if it already exists.
    """
    envelope = await file_tool_client.post(
        "/api/filesystem/copy", {"src": src, "dst": dst, "force": force}
    )
    return json.dumps(envelope, ensure_ascii=False)


@tool
async def ft_delete_file(path: str) -> str:
    """Soft-delete a file inside the workspace. The file is moved to .agent_trash/
    rather than permanently removed, so it stays recoverable.

    Args:
        path: Workspace-relative path to delete.
    """
    envelope = await file_tool_client.post("/api/filesystem/delete", {"path": path})
    return json.dumps(envelope, ensure_ascii=False)


@tool
async def ft_diff_files(path_a: str, path_b: str) -> str:
    """Compare two files inside the workspace and return a unified diff.

    Args:
        path_a: First workspace-relative file path.
        path_b: Second workspace-relative file path.
    """
    envelope = await file_tool_client.post(
        "/api/filesystem/diff", {"path_a": path_a, "path_b": path_b}
    )
    return json.dumps(envelope, ensure_ascii=False)


@tool
async def ft_patch_file(path: str, patch_content: str) -> str:
    """Apply a unified-diff patch to a file inside the workspace.

    Args:
        path: Workspace-relative file path to patch.
        patch_content: The unified diff text ("--- a/...\\n+++ b/...\\n@@ ...").
    """
    envelope = await file_tool_client.post(
        "/api/filesystem/patch", {"path": path, "patch_content": patch_content}
    )
    return json.dumps(envelope, ensure_ascii=False)
