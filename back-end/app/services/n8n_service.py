"""
n8n workflow integration service.
Discovers active webhook-trigger workflows from n8n's REST API,
creates dynamic langchain tools for the agent, and triggers webhooks.
"""

import re
import json
import asyncio
import time
from pathlib import Path
from typing import Optional

import httpx
from langchain_core.tools import StructuredTool

from app.core.config import settings


class N8nService:
    """Discovers n8n workflows and exposes them as langchain tools."""

    def __init__(self):
        self._workflows: list[dict] = []
        self._dynamic_tools: list = []
        self._available: bool = False
        self._refresh_task: asyncio.Task | None = None
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))
        return self._client

    async def initialize(self) -> list:
        """
        Query n8n API, discover active webhook workflows, create tools.
        Returns list of langchain tool objects. Safe to call if n8n is down.
        """
        try:
            self._workflows = await self._discover_workflows()
            self._dynamic_tools = []
            for wf in self._workflows:
                tool = self._create_tool_for_workflow(wf)
                if tool:
                    self._dynamic_tools.append(tool)
            self._available = True
            print(f"[n8n] Discovered {len(self._workflows)} webhook workflows, created {len(self._dynamic_tools)} tools")
        except Exception as e:
            self._available = False
            print(f"[n8n] Failed to connect to n8n: {e}")
        return self._dynamic_tools

    async def _discover_workflows(self) -> list[dict]:
        """
        GET /api/v1/workflows from n8n, filter to active workflows
        with at least one webhook trigger node.
        """
        client = await self._get_client()
        headers = {}
        if settings.N8N_API_KEY:
            headers["X-N8N-API-KEY"] = settings.N8N_API_KEY

        response = await client.get(
            f"{settings.N8N_BASE_URL}/api/v1/workflows",
            headers=headers,
            params={"active": "true"},
        )
        response.raise_for_status()
        data = response.json()

        workflows = data.get("data", [])
        result = []

        for wf in workflows:
            nodes = wf.get("nodes", [])
            webhook_node = None
            for node in nodes:
                if node.get("type") == "n8n-nodes-base.webhook":
                    webhook_node = node
                    break

            if webhook_node is None:
                continue

            webhook_path = (
                webhook_node.get("parameters", {}).get("path", "")
            )
            if not webhook_path:
                continue

            # Extract tags as list of strings
            tags = [t.get("name", "") for t in wf.get("tags", []) if t.get("name")]

            # Try to get description from meta.notes or sticky note nodes
            description = (wf.get("meta") or {}).get("notes", "")
            if not description:
                for node in nodes:
                    if node.get("type") == "n8n-nodes-base.stickyNote":
                        content = node.get("parameters", {}).get("content", "")
                        if content:
                            # Take first 300 chars of sticky note as description
                            description = content[:300]
                            break

            result.append({
                "id": wf.get("id"),
                "name": wf.get("name", f"workflow_{wf.get('id')}"),
                "description": description,
                "webhook_path": webhook_path,
                "webhook_url": self._build_webhook_url(webhook_path),
                "tags": tags,
            })

        return result

    def _build_webhook_url(self, webhook_path: str) -> str:
        return f"{settings.N8N_BASE_URL}/webhook/{webhook_path}"

    def _sanitize_tool_name(self, name: str) -> str:
        """Convert workflow name to a valid tool name."""
        sanitized = re.sub(r"[^a-zA-Z0-9]+", "_", name.lower()).strip("_")
        return f"n8n_webhook_{sanitized}"

    def _create_tool_for_workflow(self, workflow: dict) -> Optional[StructuredTool]:
        """Create a langchain tool for a single n8n webhook workflow."""
        tool_name = self._sanitize_tool_name(workflow["name"])
        webhook_url = workflow["webhook_url"]

        # Build a rich description for embedding retrieval
        parts = [f"n8n workflow: {workflow['name']}."]
        if workflow.get("description"):
            parts.append(workflow["description"].strip())
        if workflow.get("tags"):
            parts.append(f"Tags: {', '.join(workflow['tags'])}")
        description = " ".join(parts)

        # Capture webhook_url in closure
        _webhook_url = webhook_url
        _service = self

        async def _run_workflow(payload: str = "{}") -> str:
            """Trigger the n8n workflow with a JSON payload.

            Args:
                payload: JSON string with the data to send to the workflow. Use simple, short field names like "url", "message", "query".
            """
            return await _service.trigger_workflow(_webhook_url, payload)

        try:
            tool = StructuredTool.from_function(
                coroutine=_run_workflow,
                name=tool_name,
                description=description,
            )
            return tool
        except Exception as e:
            print(f"[n8n] Failed to create tool for '{workflow['name']}': {e}")
            return None

    async def trigger_workflow(self, webhook_url: str, payload: str) -> str:
        """POST to an n8n webhook URL. Saves binary responses to disk, returns text or file path."""
        try:
            parsed = json.loads(payload) if payload.strip() else {}
        except json.JSONDecodeError:
            parsed = {"message": payload}

        try:
            client = await self._get_client()
            response = await client.post(webhook_url, json=parsed)
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")

            # Binary response — save to file
            if not content_type.startswith(("text/", "application/json")):
                downloads_dir = Path("data/n8n_downloads")
                downloads_dir.mkdir(parents=True, exist_ok=True)

                # Guess extension from content type
                ext_map = {
                    "audio/mpeg": ".mp3",
                    "audio/mp3": ".mp3",
                    "audio/wav": ".wav",
                    "audio/ogg": ".ogg",
                    "video/mp4": ".mp4",
                    "application/pdf": ".pdf",
                    "image/png": ".png",
                    "image/jpeg": ".jpg",
                    "application/zip": ".zip",
                }
                ext = ext_map.get(content_type.split(";")[0].strip(), ".bin")
                filename = f"n8n_{int(time.time())}{ext}"
                filepath = downloads_dir / filename
                filepath.write_bytes(response.content)

                return f"File saved: {filepath.resolve()}"

            return response.text[:2000]
        except httpx.ConnectError:
            return "Error: Could not connect to n8n. Is it running?"
        except httpx.TimeoutException:
            return "Error: n8n workflow timed out."
        except httpx.HTTPStatusError as e:
            return f"Error: n8n returned status {e.response.status_code}"

    async def refresh(self) -> list:
        """Re-discover workflows and recreate tools."""
        self._dynamic_tools = []
        try:
            self._workflows = await self._discover_workflows()
            for wf in self._workflows:
                tool = self._create_tool_for_workflow(wf)
                if tool:
                    self._dynamic_tools.append(tool)
            self._available = True
            print(f"[n8n] Refreshed: {len(self._dynamic_tools)} workflow tools")
        except Exception as e:
            self._available = False
            print(f"[n8n] Refresh failed: {e}")
        return self._dynamic_tools

    async def start_periodic_refresh(self):
        """Start background refresh task if interval is configured."""
        interval = settings.N8N_REFRESH_INTERVAL_MINUTES
        if interval <= 0:
            return

        async def _loop():
            while True:
                await asyncio.sleep(interval * 60)
                from app.tools import register_dynamic_tools, unregister_dynamic_tools, ALL_TOOLS
                from app.services.tool_retriever import tool_retriever

                unregister_dynamic_tools("n8n_webhook_")
                new_tools = await self.refresh()
                if new_tools:
                    register_dynamic_tools(new_tools)
                tool_retriever.reindex(ALL_TOOLS)

        self._refresh_task = asyncio.create_task(_loop())
        print(f"[n8n] Periodic refresh every {interval} minutes")

    async def shutdown(self):
        """Cancel periodic refresh and close HTTP client."""
        if self._refresh_task:
            self._refresh_task.cancel()
            self._refresh_task = None
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def dynamic_tools(self) -> list:
        return self._dynamic_tools


n8n_service = N8nService()
