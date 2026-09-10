"""Monitored Services API Endpoints."""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, HttpUrl
from overseer.models.service import MonitoredService, ServiceCheck
from overseer.models.workspace import Workspace
from overseer.security.auth import AuthUser, get_active_workspace, get_current_user
from overseer.security.credentials import generate_id
from overseer.services.monitor_service import check_single_service

router = APIRouter(prefix="/services", tags=["Services"])


class CreateServiceRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    url: str = Field(...)
    method: str = Field(default="GET")
    expected_status: int = Field(default=200)
    interval_seconds: int = Field(default=60, ge=10, le=86400)
    timeout_seconds: int = Field(default=10, ge=1, le=60)
    starred: bool = Field(default=False)


class UpdateServiceRequest(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    method: Optional[str] = None
    expected_status: Optional[int] = None
    interval_seconds: Optional[int] = None
    timeout_seconds: Optional[int] = None
    enabled: Optional[bool] = None
    starred: Optional[bool] = None


@router.get("")
async def list_services(
    workspace: Workspace = Depends(get_active_workspace),
    user: AuthUser = Depends(get_current_user),
):
    services = await MonitoredService.find(
        MonitoredService.workspace_id == workspace.id
    ).sort(-MonitoredService.starred, MonitoredService.name).to_list()
    return services


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_service(
    req: CreateServiceRequest,
    workspace: Workspace = Depends(get_active_workspace),
    user: AuthUser = Depends(get_current_user),
):
    service = MonitoredService(
        id=generate_id("svc"),
        workspace_id=workspace.id,
        name=req.name,
        url=req.url,
        method=req.method.upper(),
        expected_status=req.expected_status,
        interval_seconds=req.interval_seconds,
        timeout_seconds=req.timeout_seconds,
        starred=req.starred,
        status="UNKNOWN",
    )
    await service.insert()
    # Trigger initial check asynchronously
    await check_single_service(service)
    return service


@router.delete("/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_service(
    service_id: str,
    workspace: Workspace = Depends(get_active_workspace),
    user: AuthUser = Depends(get_current_user),
):
    service = await MonitoredService.find_one(
        MonitoredService.id == service_id,
        MonitoredService.workspace_id == workspace.id,
    )
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")

    await service.delete()
    # Also delete associated historical checks
    await ServiceCheck.find(ServiceCheck.service_id == service_id).delete()
    return None
