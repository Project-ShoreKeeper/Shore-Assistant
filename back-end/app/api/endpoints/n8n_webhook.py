"""
n8n integration endpoints.
Receives notifications from n8n workflows and provides management APIs.
"""

import time
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Header

from app.core.config import settings
from app.services.notification_service import notification_service
from app.services.connection_manager import connection_manager

router = APIRouter(prefix="/api/n8n", tags=["n8n"])


@router.post("/webhook")
async def n8n_webhook(
    request: Request,
    x_webhook_secret: Optional[str] = Header(None),
):
    """
    Receive notifications from n8n workflows.

    n8n HTTP Request node should POST JSON:
    {
        "message": "The backup completed successfully",
        "source": "Backup Workflow"  (optional)
    }
    """
    if settings.N8N_WEBHOOK_SECRET:
        if x_webhook_secret != settings.N8N_WEBHOOK_SECRET:
            raise HTTPException(status_code=401, detail="Invalid webhook secret")

    body = await request.json()
    message = body.get("message", "")
    source = body.get("source", "n8n workflow")

    if not message:
        raise HTTPException(status_code=400, detail="'message' field required")

    task = {
        "task_id": f"n8n_{int(time.time())}",
        "type": "n8n_notification",
        "message": f"[From {source}]: {message}",
    }
    await notification_service.notify(task)

    return {
        "status": "delivered" if connection_manager.is_connected else "queued",
    }


@router.post("/refresh")
async def refresh_n8n_workflows():
    """Manually re-discover n8n workflows and update tools."""
    from app.services.n8n_service import n8n_service
    from app.tools import register_dynamic_tools, unregister_dynamic_tools, ALL_TOOLS
    from app.services.tool_retriever import tool_retriever

    unregister_dynamic_tools("n8n_")
    new_tools = await n8n_service.refresh()
    if new_tools:
        register_dynamic_tools(new_tools)
    tool_retriever.reindex(ALL_TOOLS)

    return {
        "status": "refreshed",
        "workflows_discovered": len(new_tools),
        "tool_names": [t.name for t in new_tools],
    }


@router.get("/status")
async def n8n_status():
    """Check n8n connection status and list registered workflow tools."""
    from app.services.n8n_service import n8n_service

    return {
        "available": n8n_service.is_available,
        "workflow_count": len(n8n_service.dynamic_tools),
        "tools": [t.name for t in n8n_service.dynamic_tools],
    }
