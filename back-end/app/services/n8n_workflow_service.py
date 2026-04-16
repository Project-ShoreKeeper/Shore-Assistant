"""
n8n workflow management service.
Wraps the n8nac CLI (n8n-as-code) for node search/schema/templates,
and uses the n8n REST API directly for workflow CRUD and credential management.
"""

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Optional

import httpx

from app.core.config import settings


# Repo root: back-end/app/services/ -> back-end/app/ -> back-end/ -> repo root
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class N8nWorkflowService:
    """
    Manages n8n workflow creation, credential setup, and lifecycle via:
    - n8nac CLI (npx n8nac) for ontology search and schema inspection
    - n8n REST API for workflow CRUD, credential creation, and activation
    """

    def __init__(self):
        self._repo_root = _REPO_ROOT
        
        # Base folder from settings
        base_dir = Path(settings.N8N_WORKFLOWS_DIR)
        
        # Try to resolve full n8nac folder structure from config
        config_path = self._repo_root / "n8nac-config.json"
        if config_path.exists():
            try:
                cfg = json.loads(config_path.read_text(encoding="utf-8"))
                instance = cfg.get("instanceIdentifier", "")
                project = cfg.get("projectName", "personal").lower()
                if instance and project:
                    base_dir = self._repo_root / cfg.get("syncFolder", "data/n8n-workflows") / instance / project
            except Exception:
                pass
                
        self._workflows_dir = base_dir
        self._client: Optional[httpx.AsyncClient] = None
        self._n8nac_available: bool = False

    # ── HTTP client ──────────────────────────────────────────────────────────

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))
        return self._client

    @property
    def _auth_headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if settings.N8N_API_KEY:
            h["X-N8N-API-KEY"] = settings.N8N_API_KEY
        return h

    # ── n8nac subprocess ─────────────────────────────────────────────────────

    async def run_n8nac(self, *args: str, timeout: float = 30.0) -> tuple[str, str]:
        """
        Run `npx n8nac <args>` from the repo root via a thread executor.
        Uses subprocess.run (blocking) in a thread to avoid uvicorn's Windows
        ProactorEventLoop issues with create_subprocess_exec.
        Returns (stdout, stderr). Raises RuntimeError on non-zero exit.
        """
        import subprocess
        import concurrent.futures

        env = {**os.environ, "NO_COLOR": "1", "FORCE_COLOR": "0"}

        if sys.platform == "win32":
            cmd = ["cmd", "/c", "npx", "n8nac", *args]
        else:
            cmd = ["npx", "n8nac", *args]

        def _run() -> tuple[str, str]:
            result = subprocess.run(
                cmd,
                cwd=str(self._repo_root),
                env=env,
                capture_output=True,
                timeout=timeout,
            )
            stdout = result.stdout.decode("utf-8", errors="replace").strip()
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            if result.returncode != 0:
                raise RuntimeError(f"n8nac exited {result.returncode}: {stderr or stdout}")
            return stdout, stderr

        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(None, _run)
        except concurrent.futures.TimeoutError:
            raise RuntimeError(f"n8nac timed out after {timeout}s: {' '.join(args)}")

    async def init_n8nac(self) -> bool:
        """
        Check whether n8nac has been configured (n8nac-config.json exists at repo root).
        n8nac init is interactive-only and must be run manually once:
            npx n8nac init
        Returns True if config is present and n8nac responds, False otherwise.
        """
        if not settings.N8N_ENABLED:
            return False

        config_file = self._repo_root / "n8nac-config.json"
        if not config_file.exists():
            print(
                "[n8n-workflow] n8nac not configured — node search/schema tools will be unavailable. "
                "Run once to set up: npx n8nac init  (from repo root)"
            )
            self._n8nac_available = False
            return False

        self._n8nac_available = True
        print("[n8n-workflow] n8nac ready")
        return True

    # ── Node ontology (read from bundled assets, no subprocess needed) ──────

    _SKILLS_ASSETS = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "node_modules" / "@n8n-as-code" / "skills" / "dist" / "assets"
    )

    def _load_nodes(self) -> dict:
        """Load and cache n8n-nodes-technical.json keyed by node name."""
        if not hasattr(self, "_nodes_cache"):
            path = self._SKILLS_ASSETS / "n8n-nodes-technical.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            self._nodes_cache: dict = data.get("nodes", {})
        return self._nodes_cache

    def _load_workflows_index(self) -> list:
        """Load and cache workflows-index.json."""
        if not hasattr(self, "_workflows_cache"):
            path = self._SKILLS_ASSETS / "workflows-index.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            self._workflows_cache: list = data.get("workflows", [])
        return self._workflows_cache

    async def search_nodes(self, query: str) -> str:
        """Search n8n node ontology from bundled assets. Returns JSON string."""
        nodes = self._load_nodes()
        terms = query.lower().split()
        results = []
        for node in nodes.values():
            haystack = " ".join([
                node.get("displayName", ""),
                node.get("description", ""),
                node.get("type", ""),
                node.get("name", ""),
            ]).lower()
            if any(t in haystack for t in terms):
                results.append({
                    "name": node.get("name"),
                    "type": node.get("type"),
                    "displayName": node.get("displayName"),
                    "description": node.get("description"),
                    "version": node.get("version"),
                })
        results = results[:20]
        return json.dumps(results, indent=2) if results else f"No nodes found matching '{query}'"

    async def get_node_schema(self, node_name: str) -> str:
        """Get full schema for a node from bundled assets. Returns JSON string."""
        nodes = self._load_nodes()
        # Try exact match first, then case-insensitive
        node = nodes.get(node_name)
        if not node:
            node_name_lower = node_name.lower()
            for key, val in nodes.items():
                if key.lower() == node_name_lower or val.get("type", "").lower().endswith(node_name_lower):
                    node = val
                    break
        if not node:
            return f"Node '{node_name}' not found. Use n8n_search_nodes to find the correct name."
        return json.dumps({
            "name": node.get("name"),
            "type": node.get("type"),
            "displayName": node.get("displayName"),
            "description": node.get("description"),
            "version": node.get("version"),
            "schema": node.get("schema", {}),
        }, indent=2)

    async def search_templates(self, query: str) -> str:
        """Search community workflow templates from bundled index. Returns JSON string."""
        workflows = self._load_workflows_index()
        terms = query.lower().split()
        results = []
        for wf in workflows:
            haystack = " ".join([
                wf.get("name", ""),
                wf.get("description", "") or "",
                " ".join(wf.get("tags", [])),
                " ".join(wf.get("nodeTypes", [])),
            ]).lower()
            if any(t in haystack for t in terms):
                results.append({
                    "id": wf.get("id"),
                    "name": wf.get("name"),
                    "tags": wf.get("tags", []),
                    "description": wf.get("description"),
                    "url": wf.get("url"),
                    "nodeTypes": wf.get("nodeTypes", []),
                })
        results = results[:10]
        return json.dumps(results, indent=2) if results else f"No templates found matching '{query}'"

    # ── Workflow REST API ────────────────────────────────────────────────────

    def _normalize_connections(self, nodes: list, connections) -> dict:
        """
        Convert various connection formats to n8n's expected dict format.
        n8n expects: {"NodeName": {"main": [[{"node": "OtherNode", "type": "main", "index": 0}]]}}
        LLMs often generate arrays: [{"from": "<id>", "to": "<id>"}]
        """
        if isinstance(connections, dict):
            return connections  # Already correct

        if not isinstance(connections, list):
            return {}

        # Build ID → display name map for resolution
        id_to_name = {n.get("id", ""): n.get("name", "") for n in nodes}
        name_set = {n.get("name", "") for n in nodes}

        result: dict = {}
        for conn in connections:
            raw_from = conn.get("from") or conn.get("source") or ""
            raw_to = conn.get("to") or conn.get("target") or ""
            # Resolve ID to display name, fall back to raw value if it's already a name
            from_name = id_to_name.get(raw_from, raw_from if raw_from in name_set else raw_from)
            to_name = id_to_name.get(raw_to, raw_to if raw_to in name_set else raw_to)
            if not from_name or not to_name:
                continue
            if from_name not in result:
                result[from_name] = {"main": [[]]}
            result[from_name]["main"][0].append({"node": to_name, "type": "main", "index": 0})

        return result

    def _normalize_credentials(self, nodes: list) -> list:
        """Strip invalid credential entries (e.g. {'credentialType': ''}) from nodes."""
        for node in nodes:
            creds = node.get("credentials", {})
            node["credentials"] = {
                k: v for k, v in creds.items()
                if k != "credentialType" and k
            }
        return nodes

    async def create_workflow(self, name: str, workflow_data: dict) -> dict:
        """POST /api/v1/workflows. Returns created workflow dict."""
        nodes = workflow_data.get("nodes", [])

        # Ensure nodes have valid UUIDs
        for node in nodes:
            if not node.get("id"):
                node["id"] = str(uuid.uuid4())

        # Normalize connections and credentials from common LLM output formats
        connections = self._normalize_connections(nodes, workflow_data.get("connections", {}))
        nodes = self._normalize_credentials(nodes)

        payload = {
            "name": name,
            "nodes": nodes,
            "connections": connections,
            "settings": workflow_data.get("settings", {"executionOrder": "v1"}),
        }
        client = await self._get_client()
        response = await client.post(
            f"{settings.N8N_BASE_URL}/api/v1/workflows",
            headers=self._auth_headers,
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    async def get_workflow(self, workflow_id: str) -> dict:
        """GET /api/v1/workflows/{id}."""
        client = await self._get_client()
        response = await client.get(
            f"{settings.N8N_BASE_URL}/api/v1/workflows/{workflow_id}",
            headers=self._auth_headers,
        )
        response.raise_for_status()
        return response.json()

    async def update_workflow(self, workflow_id: str, workflow_data: dict) -> dict:
        """PUT /api/v1/workflows/{id}."""
        client = await self._get_client()
        response = await client.put(
            f"{settings.N8N_BASE_URL}/api/v1/workflows/{workflow_id}",
            headers=self._auth_headers,
            json=workflow_data,
        )
        response.raise_for_status()
        return response.json()

    async def activate_workflow(self, workflow_id: str) -> bool:
        """POST /api/v1/workflows/{id}/activate."""
        client = await self._get_client()
        response = await client.post(
            f"{settings.N8N_BASE_URL}/api/v1/workflows/{workflow_id}/activate",
            headers=self._auth_headers,
        )
        response.raise_for_status()
        return True

    async def deactivate_workflow(self, workflow_id: str) -> bool:
        """POST /api/v1/workflows/{id}/deactivate."""
        client = await self._get_client()
        response = await client.post(
            f"{settings.N8N_BASE_URL}/api/v1/workflows/{workflow_id}/deactivate",
            headers=self._auth_headers,
        )
        response.raise_for_status()
        return True

    async def delete_workflow(self, workflow_id: str) -> bool:
        """DELETE /api/v1/workflows/{id}."""
        client = await self._get_client()
        response = await client.delete(
            f"{settings.N8N_BASE_URL}/api/v1/workflows/{workflow_id}",
            headers=self._auth_headers,
        )
        response.raise_for_status()
        return True

    async def list_workflows(self) -> list[dict]:
        """GET /api/v1/workflows."""
        client = await self._get_client()
        response = await client.get(
            f"{settings.N8N_BASE_URL}/api/v1/workflows",
            headers=self._auth_headers,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("data", [])

    # ── Credential REST API ──────────────────────────────────────────────────

    async def create_credential(self, name: str, type_: str, data: dict) -> str:
        """POST /api/v1/credentials. Returns credential ID."""
        client = await self._get_client()
        response = await client.post(
            f"{settings.N8N_BASE_URL}/api/v1/credentials",
            headers=self._auth_headers,
            json={"name": name, "type": type_, "data": data},
        )
        response.raise_for_status()
        return response.json().get("id", "")

    # ── Credential detection ─────────────────────────────────────────────────

    def get_missing_credentials(self, workflow_data: dict) -> list[dict]:
        """
        Inspect workflow nodes for credential requirements with no ID assigned.
        Returns list of {node_name, credential_type} dicts.
        """
        missing = []
        for node in workflow_data.get("nodes", []):
            node_creds = node.get("credentials", {})
            for cred_type, cred_ref in node_creds.items():
                if not cred_ref.get("id"):
                    missing.append({
                        "node_name": node.get("name", node.get("type", "unknown")),
                        "credential_type": cred_type,
                    })
        return missing

    async def wire_credential(
        self, workflow_id: str, credential_type: str, credential_id: str, credential_name: str
    ) -> dict:
        """
        Update all nodes in a workflow that reference credential_type to use
        the provided credential_id. Returns updated workflow data.
        """
        workflow = await self.get_workflow(workflow_id)
        for node in workflow.get("nodes", []):
            node_creds = node.get("credentials", {})
            if credential_type in node_creds:
                node_creds[credential_type] = {"id": credential_id, "name": credential_name}
        return await self.update_workflow(workflow_id, workflow)

    # ── Webhook test ─────────────────────────────────────────────────────────

    async def test_workflow_webhook(self, workflow_data: dict) -> Optional[str]:
        """
        If the workflow has a webhook trigger, POST an empty payload to it
        and return the response. Returns None if no webhook trigger found.
        """
        for node in workflow_data.get("nodes", []):
            if node.get("type") == "n8n-nodes-base.webhook":
                path = node.get("parameters", {}).get("path", "")
                if path:
                    webhook_url = f"{settings.N8N_BASE_URL}/webhook/{path}"
                    try:
                        client = await self._get_client()
                        resp = await client.post(webhook_url, json={}, timeout=10.0)
                        return f"Webhook test: HTTP {resp.status_code} — {resp.text[:500]}"
                    except Exception as e:
                        return f"Webhook test failed: {e}"
        return None

    # ── Local file storage ───────────────────────────────────────────────────

    def save_workflow_locally(self, name: str, workflow_data: dict) -> Path:
        """Save workflow JSON to data/n8n-workflows/<name>.json."""
        self._workflows_dir.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        filepath = self._workflows_dir / f"{safe_name}.json"
        filepath.write_text(json.dumps(workflow_data, indent=2), encoding="utf-8")
        return filepath

    async def convert_ts_to_json(self, name: str, ts_content: str) -> dict:
        """Save TypeScript workflow and convert to JSON using n8nac convert."""
        import tempfile
        import shutil

        # Save to local gitops mapped directory if possible
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        
        # Determine the target directory (ideally the sync folder specified in n8nac-config)
        # We will put it in a temp processing block to cleanly handle conversion
        ts_filepath = self._workflows_dir / f"{safe_name}.workflow.ts"
        json_filepath = self._workflows_dir / f"{safe_name}.json"
        
        self._workflows_dir.mkdir(parents=True, exist_ok=True)
        ts_filepath.write_text(ts_content, encoding="utf-8")
        
        try:
            # Run n8nac convert <file> --format json --output <out_file>
            await self.run_n8nac("convert", str(ts_filepath), "--format", "json", "-o", str(json_filepath), "-f")
            
            if not json_filepath.exists():
                raise RuntimeError(f"n8nac convert did not generate {json_filepath}")
                
            json_content = json.loads(json_filepath.read_text(encoding="utf-8"))
            return json_content
        finally:
            pass # Keep both files around as per n8nac structure

    # ── Claude Code delegation ───────────────────────────────────────────────

    async def generate_workflow_with_claude(
        self, name: str, description: str, node_schemas: str
    ) -> str:
        """
        Delegate complex workflow generation to Claude Code CLI.
        Returns workflow JSON string, or raises on failure.
        """
        prompt = (
            f"You are an n8n workflow expert. Generate a complete n8n workflow JSON for the following task:\n\n"
            f"Name: {name}\n"
            f"Description: {description}\n\n"
            f"Available node schemas for reference:\n{node_schemas}\n\n"
            f"Output ONLY valid JSON in this exact format:\n"
            f"{{\n"
            f'  "name": "{name}",\n'
            f'  "nodes": [...],\n'
            f'  "connections": {{}},\n'
            f'  "settings": {{"executionOrder": "v1"}}\n'
            f"}}\n\n"
            f"Rules:\n"
            f"- Each node needs: id (UUID), name (display name), type (e.g. n8n-nodes-base.slack), "
            f"typeVersion (number), position ([x, y]), parameters (object)\n"
            f"- Nodes that require credentials must include a 'credentials' field with the credential type as key "
            f"and an empty object as value: e.g. {{\"slackApi\": {{}}}}\n"
            f"- Output ONLY the JSON, no explanation, no markdown code blocks."
        )

        import subprocess

        if sys.platform == "win32":
            claude_cmd = ["cmd", "/c", "claude", "--print", prompt]
        else:
            claude_cmd = ["claude", "--print", prompt]

        def _run_claude() -> str:
            result = subprocess.run(
                claude_cmd,
                cwd=str(self._repo_root),
                capture_output=True,
                timeout=120.0,
            )
            out = result.stdout.decode("utf-8", errors="replace").strip()
            if result.returncode != 0:
                err = result.stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(f"Claude Code failed: {err or out}")
            return out

        loop = asyncio.get_event_loop()
        output = await loop.run_in_executor(None, _run_claude)

        # Extract JSON from output (strip any surrounding text/markdown)
        import re
        json_match = re.search(r"\{[\s\S]*\}", output)
        if not json_match:
            raise RuntimeError(f"Claude Code did not return valid JSON: {output[:500]}")
        return json_match.group(0)

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def shutdown(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


n8n_workflow_service = N8nWorkflowService()
