"""Events and Situational Audit Log API Endpoints."""

from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from overseer.models.event import Event
from overseer.models.workspace import Workspace
from overseer.security.auth import AuthUser, get_active_workspace, get_current_user

router = APIRouter(prefix="/events", tags=["Events"])


@router.get("")
async def list_events(
    limit: int = Query(default=50, ge=1, le=200),
    severity: Optional[str] = None,
    event_type: Optional[str] = None,
    workspace: Workspace = Depends(get_active_workspace),
    user: AuthUser = Depends(get_current_user),
):
    query = [Event.workspace_id == workspace.id]
    if severity:
        query.append(Event.severity == severity.upper())
    if event_type:
        query.append(Event.event_type == event_type.upper())

    events = await Event.find(*query).sort(-Event.created_at).limit(limit).to_list()
    return events
