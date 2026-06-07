"""Service control endpoints — list, start, stop registered services.

Backs the Dashboard's per-service Start/Stop buttons. Writes require admin
role (when AUTH_ENABLED) plus a CSRF token; reads are open to any logged-in
user.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.deps import csrf_check, current_user, require_admin
from app.services.service_manager import (
    ServiceConflict,
    ServiceNotFound,
    service_manager,
)


router = APIRouter(prefix="/api/services", tags=["services"])


@router.get("", dependencies=[Depends(current_user)])
async def list_services() -> dict:
    states = await service_manager.list_state()
    return {"services": [s.model_dump() for s in states]}


@router.post(
    "/{name}/start",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_admin), Depends(csrf_check)],
)
async def start_service(name: str, response: Response) -> dict:
    try:
        service_manager.schedule_start(name)
    except ServiceNotFound:
        raise HTTPException(status_code=404, detail={"error": "service_not_found", "name": name})
    except ServiceConflict as e:
        raise HTTPException(status_code=409, detail={"error": "conflict", "message": str(e)})
    return {"name": name, "transitioning": True, "action": "start"}


@router.post(
    "/{name}/stop",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_admin), Depends(csrf_check)],
)
async def stop_service(name: str, response: Response) -> dict:
    try:
        service_manager.schedule_stop(name)
    except ServiceNotFound:
        raise HTTPException(status_code=404, detail={"error": "service_not_found", "name": name})
    except ServiceConflict as e:
        raise HTTPException(status_code=409, detail={"error": "conflict", "message": str(e)})
    return {"name": name, "transitioning": True, "action": "stop"}
