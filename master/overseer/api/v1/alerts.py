"""Alerts and Telegram Destination API Endpoints."""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from overseer.models.alert import AlertDestination
from overseer.models.workspace import Workspace
from overseer.security.auth import AuthUser, get_active_workspace, get_current_user
from overseer.security.credentials import encrypt_secret, generate_id
from overseer.services.alert_service import send_test_telegram_alert

router = APIRouter(prefix="/alerts", tags=["Alerts"])


class CreateTelegramDestinationRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    telegram_bot_token: str = Field(..., min_length=10)
    telegram_chat_id: str = Field(..., min_length=1)
    telegram_topic_id: Optional[str] = None
    triggers: List[str] = Field(default_factory=lambda: ["NODE_OFFLINE", "NODE_RECOVERED", "SERVICE_DOWN", "SERVICE_RECOVERED"])


@router.get("/destinations")
async def list_destinations(
    workspace: Workspace = Depends(get_active_workspace),
    user: AuthUser = Depends(get_current_user),
):
    destinations = await AlertDestination.find(
        AlertDestination.workspace_id == workspace.id
    ).to_list()

    # Never expose unencrypted bot tokens
    return [
        {
            "id": d.id,
            "name": d.name,
            "channel_type": d.channel_type,
            "telegram_chat_id": d.telegram_chat_id,
            "telegram_topic_id": d.telegram_topic_id,
            "triggers": d.triggers,
            "enabled": d.enabled,
            "created_at": d.created_at,
        }
        for d in destinations
    ]


@router.post("/destinations", status_code=status.HTTP_201_CREATED)
async def create_destination(
    req: CreateTelegramDestinationRequest,
    workspace: Workspace = Depends(get_active_workspace),
    user: AuthUser = Depends(get_current_user),
):
    encrypted_token = encrypt_secret(req.telegram_bot_token)
    dest = AlertDestination(
        id=generate_id("alt"),
        workspace_id=workspace.id,
        name=req.name,
        channel_type="telegram",
        telegram_bot_token_encrypted=encrypted_token,
        telegram_chat_id=req.telegram_chat_id,
        telegram_topic_id=req.telegram_topic_id,
        triggers=req.triggers,
        enabled=True,
    )
    await dest.insert()
    return {"id": dest.id, "name": dest.name, "status": "CREATED"}


@router.post("/destinations/{dest_id}/test")
async def test_destination(
    dest_id: str,
    workspace: Workspace = Depends(get_active_workspace),
    user: AuthUser = Depends(get_current_user),
):
    dest = await AlertDestination.find_one(
        AlertDestination.id == dest_id,
        AlertDestination.workspace_id == workspace.id,
    )
    if not dest:
        raise HTTPException(status_code=404, detail="Destination not found")

    success = await send_test_telegram_alert(dest)
    if not success:
        raise HTTPException(status_code=400, detail="Telegram dispatch failed. Check bot token and chat ID.")

    return {"status": "SUCCESS", "message": "Test alert successfully transmitted to Telegram."}
