"""Workspace Management API Endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from overseer.models.workspace import Workspace, WorkspaceMember
from overseer.security.auth import AuthUser, get_active_workspace, get_current_user
from overseer.security.credentials import generate_id

router = APIRouter(prefix="/workspaces", tags=["Workspaces"])


class CreateWorkspaceRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    slug: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="")


@router.get("")
async def list_user_workspaces(user: AuthUser = Depends(get_current_user)):
    memberships = await WorkspaceMember.find(WorkspaceMember.user_sub == user.sub).to_list()
    ws_ids = [m.workspace_id for m in memberships]
    workspaces = await Workspace.find({"_id": {"$in": ws_ids}}).to_list()
    return workspaces


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_workspace(
    req: CreateWorkspaceRequest,
    user: AuthUser = Depends(get_current_user),
):
    existing = await Workspace.find_one(Workspace.slug == req.slug)
    if existing:
        raise HTTPException(status_code=400, detail="Workspace slug already taken")

    ws = Workspace(
        id=generate_id("ws"),
        name=req.name,
        slug=req.slug,
        description=req.description,
    )
    await ws.insert()

    member = WorkspaceMember(
        id=generate_id("wsm"),
        workspace_id=ws.id,
        user_sub=user.sub,
        user_email=user.email,
        user_name=user.name,
        role="admin",
    )
    await member.insert()
    return ws
