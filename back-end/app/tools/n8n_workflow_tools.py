"""
n8n workflow management tools for the AI agent.
Allows Shore to search n8n nodes, create workflows, manage credentials, and more.
"""

import json
import re

from langchain_core.tools import tool

from app.services.n8n_workflow_service import n8n_workflow_service


def _repair_workflow_json(raw: str) -> str:
    """Attempt to fix common LLM-generated JSON malformations.

    Known issues this handles:
    - Split arrays: `"nodes": [{...}], [{...}]` → `"nodes": [{...}, {...}]`
    - Trailing commas before closing braces/brackets
    - Duplicate keys in the same object (keeps the last one via json round-trip)
    """
    s = raw.strip()

    # ── Fix split arrays ──
    # Pattern: `}], [{` — an array closing then immediately a new array opening.
    # This happens when the LLM accidentally closes the nodes array after the
    # first node, then starts a new array for the second node.
    # We merge them by replacing `], [` with `, ` (joining the arrays).
    s = re.sub(r'\}\s*\]\s*,\s*\[\s*\{', '}, {', s)

    # ── Fix trailing commas ──
    # Trailing comma before closing bracket: [1, 2, ] → [1, 2]
    s = re.sub(r',\s*\]', ']', s)
    # Trailing comma before closing brace: {"a": 1, } → {"a": 1}
    s = re.sub(r',\s*\}', '}', s)

    return s


@tool
async def n8n_search_nodes(query: str) -> str:
    """Search n8n's library of 537 nodes to find the right ones for building a workflow.
    Returns matching node names, types, and descriptions. Call this before creating any workflow.

    Args:
        query: What the node should do, e.g. "send slack message", "http request", "google sheets"
    """
    try:
        return await n8n_workflow_service.search_nodes(query)
    except Exception as e:
        return f"Error searching nodes: {e}"


@tool
async def n8n_get_node_schema(node_name: str) -> str:
    """Get the full parameter schema for a specific n8n node type.
    Use this after n8n_search_nodes to understand exactly how to configure a node before building a workflow.

    Args:
        node_name: Node type name without package prefix, e.g. "slack", "httpRequest", "scheduleTrigger", "googleSheets"
    """
    try:
        return await n8n_workflow_service.get_node_schema(node_name)
    except Exception as e:
        return f"Error getting node schema: {e}"


@tool
async def n8n_search_workflow_templates(query: str) -> str:
    """Search 7,700+ community n8n workflow templates for inspiration or to reuse as a base.
    Returns workflow names, descriptions, and template IDs.

    Args:
        query: Description of the automation you want, e.g. "slack notification from webhook", "daily email digest"
    """
    try:
        return await n8n_workflow_service.search_templates(query)
    except Exception as e:
        return f"Error searching templates: {e}"


@tool
async def n8n_create_workflow(name: str, workflow_ts: str, credentials_json: str = "[]") -> str:
    """Create and deploy a new n8n workflow using n8n-as-code TypeScript format, with optional credentials.
    Before calling this, use n8n_search_nodes to find node types and n8n_get_node_schema for parameters.
    If a node requires a credential, YOU MUST ask the user for the authentication details first.
    Once you have them, pass them as a JSON array in `credentials_json`.

    Example `credentials_json`:
    [
      {"credential_type": "slackApi", "credential_name": "My Slack Bot", "data": {"accessToken": "xoxb-..."}}
    ]

    Args:
        name: Name of the workflow.
        workflow_ts: Complete string representation of the .workflow.ts file.
        credentials_json: JSON array of credential objects to create and inject.
    """
    try:
        creds = json.loads(credentials_json)
    except json.JSONDecodeError as e:
        return f"Error: credentials_json must be valid JSON array — {e}"

    try:
        workflow_data = await n8n_workflow_service.convert_ts_to_json(name, workflow_ts)
    except Exception as e:
        return f"Error compiling TypeScript: {e}\nPlease check your syntax."

    try:
        created = await n8n_workflow_service.create_workflow(name, workflow_data)
        workflow_id = created.get("id", "unknown")

        # Process standard credentials
        updated = created
        if creds:
            for c in creds:
                cred_type = c.get("credential_type")
                cred_name = c.get("credential_name", f"{cred_type} Credential")
                cred_data = c.get("data", {})
                if cred_type and cred_data:
                    cred_id = await n8n_workflow_service.create_credential(cred_name, cred_type, cred_data)
                    updated = await n8n_workflow_service.wire_credential(workflow_id, cred_type, cred_id, cred_name)

        # Save locally
        n8n_workflow_service.save_workflow_locally(name, updated)

        # Detect any remaining missing credentials
        missing = n8n_workflow_service.get_missing_credentials(updated)
        if missing:
            cred_list = ", ".join(f"{m['credential_type']} (on node '{m['node_name']}')" for m in missing)
            return (
                f"Workflow '{name}' created in n8n (ID: {workflow_id}) but requires credentials to activate.\n"
                f"Missing: {cred_list}.\n"
                f"Ask the user for these credentials, then call n8n_create_workflow again with the credentials_json populated."
            )

        # No missing credentials — try to activate
        try:
            await n8n_workflow_service.activate_workflow(workflow_id)
            # Test webhook if present
            test_result = await n8n_workflow_service.test_workflow_webhook(updated)
            result = f"Workflow '{name}' created and activated (ID: {workflow_id})."
            if test_result:
                result += f" {test_result}"
            return result
        except Exception as e:
            return (
                f"Workflow '{name}' created (ID: {workflow_id}) but activation failed: {e}. "
                f"You can activate it manually in the n8n UI."
            )

    except Exception as e:
        return f"Error creating workflow: {e}"


@tool
async def n8n_build_complex_workflow(name: str, description: str) -> str:
    """Build an n8n workflow using Claude AI — only use this when the user explicitly asks to
    'use Claude' or 'use AI' to build the workflow. For all normal workflow creation, use
    n8n_create_workflow instead. This tool shells out to the Claude Code CLI and takes longer.

    Args:
        name: Workflow name
        description: Detailed plain-English description of what the workflow should do
    """
    try:
        # Gather node schemas for context by searching relevant keywords from description
        keywords = description.split()[:5]
        search_query = " ".join(keywords)
        try:
            node_schemas = await n8n_workflow_service.search_nodes(search_query)
        except Exception:
            node_schemas = "(node search unavailable)"

        # Delegate to Claude Code
        workflow_json_str = await n8n_workflow_service.generate_workflow_with_claude(
            name, description, node_schemas
        )
        workflow_data = json.loads(workflow_json_str)

        # Create in n8n
        created = await n8n_workflow_service.create_workflow(name, workflow_data)
        workflow_id = created.get("id", "unknown")

        # Save locally
        n8n_workflow_service.save_workflow_locally(name, created)

        # Detect missing credentials
        missing = n8n_workflow_service.get_missing_credentials(created)

        if missing:
            cred_list = ", ".join(
                f"{m['credential_type']} (on node '{m['node_name']}')" for m in missing
            )
            return (
                f"Workflow '{name}' created by Claude Code (ID: {workflow_id}). "
                f"Not yet active — missing credentials: {cred_list}. "
                f"Ask the user for each credential, then call n8n_set_workflow_credential."
            )

        try:
            await n8n_workflow_service.activate_workflow(workflow_id)
            return f"Workflow '{name}' created by Claude Code and activated (ID: {workflow_id})."
        except Exception as e:
            return (
                f"Workflow '{name}' created by Claude Code (ID: {workflow_id}) "
                f"but activation failed: {e}. Activate manually in the n8n UI."
            )

    except Exception as e:
        return f"Error building complex workflow: {e}"





@tool
async def n8n_manage_workflows(action: str, workflow_id: str = "") -> str:
    """List, activate, deactivate, or delete n8n workflows.

    Args:
        action: One of "list", "activate", "deactivate", "delete"
        workflow_id: Required for activate, deactivate, and delete actions
    """
    action = action.strip().lower()

    if action == "list":
        try:
            workflows = await n8n_workflow_service.list_workflows()
            if not workflows:
                return "No workflows found in n8n."
            lines = []
            for wf in workflows:
                status = "active" if wf.get("active") else "inactive"
                lines.append(f"- [{status}] {wf.get('name', 'Unnamed')} (ID: {wf.get('id')})")
            return "\n".join(lines)
        except Exception as e:
            return f"Error listing workflows: {e}"

    if not workflow_id:
        return f"Error: workflow_id is required for action '{action}'"

    try:
        if action == "activate":
            await n8n_workflow_service.activate_workflow(workflow_id)
            return f"Workflow {workflow_id} activated."

        elif action == "deactivate":
            await n8n_workflow_service.deactivate_workflow(workflow_id)
            return f"Workflow {workflow_id} deactivated."

        elif action == "delete":
            await n8n_workflow_service.delete_workflow(workflow_id)
            return f"Workflow {workflow_id} deleted."

        else:
            return f"Error: Unknown action '{action}'. Use list, activate, deactivate, or delete."

    except Exception as e:
        return f"Error performing '{action}' on workflow {workflow_id}: {e}"
