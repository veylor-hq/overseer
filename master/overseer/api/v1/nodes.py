"""Node Machine Ingestion and Admin Endpoints."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from overseer.models.node import Node, NodeCredential
from overseer.models.workspace import Workspace
from overseer.security.auth import AuthUser, get_active_workspace, get_current_user
from overseer.security.credentials import generate_id
from overseer.services.alert_service import record_and_dispatch_event
from overseer.services.node_service import (
    activate_node_agent,
    create_node_with_activation,
    process_heartbeat,
    verify_node_authentication,
)

router = APIRouter(prefix="/nodes", tags=["Nodes"])


# Schemas
class CreateNodeRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None


class CreateNodeResponse(BaseModel):
    node_id: str
    activation_token: str
    install_command: str
    expires_in_minutes: int


class ActivateNodeRequest(BaseModel):
    activation_token: str
    hostname: Optional[str] = None
    os: Optional[str] = None
    arch: Optional[str] = None
    ip_address: Optional[str] = None


class ActivateNodeResponse(BaseModel):
    status: str
    node_id: str
    node_secret: str
    message: str


class HeartbeatRequest(BaseModel):
    node_id: str
    reported_at: datetime
    ip_address: Optional[str] = None
    system: Dict[str, Any] = Field(default_factory=dict)
    docker: List[Dict[str, Any]] = Field(default_factory=list)


# --- Machine Endpoints (No Browser Session Required) ---

@router.post("/activate", response_model=ActivateNodeResponse)
async def activate_node(req: ActivateNodeRequest):
    """
    Called once by Rust child agent to exchange single-use token for permanent credentials.
    """
    success, node_id, raw_secret, err = await activate_node_agent(
        raw_token=req.activation_token,
        hostname=req.hostname,
        os_name=req.os,
        arch=req.arch,
        ip_address=req.ip_address,
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=err or "Activation failed",
        )

    return ActivateNodeResponse(
        status="ACTIVE",
        node_id=node_id,
        node_secret=raw_secret,
        message="Node successfully activated. Use permanent credentials for future heartbeats.",
    )


@router.post("/heartbeat")
async def node_heartbeat(
    req: HeartbeatRequest,
    x_node_id: Optional[str] = Header(None, alias="X-Node-ID"),
    x_node_secret: Optional[str] = Header(None, alias="X-Node-Secret"),
):
    """
    Inbound heartbeat sent periodically by the Rust child agent.
    Master verifies credentials and generates authoritative received_at.
    """
    node_id = x_node_id or req.node_id
    if not node_id or not x_node_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing node authentication headers",
        )

    node = await verify_node_authentication(node_id, x_node_secret)
    if not node:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid node credentials or node disabled",
        )

    updated_node = await process_heartbeat(
        node=node,
        reported_at=req.reported_at,
        system_metrics=req.system,
        docker_containers=req.docker,
        ip_address=req.ip_address,
    )

    return {
        "status": "ACK",
        "node_id": updated_node.id,
        "received_at": updated_node.last_received_at.isoformat() if updated_node.last_received_at else None,
    }


# --- Admin API Endpoints (Workspace Enforced) ---

@router.get("")
async def list_nodes(
    workspace: Workspace = Depends(get_active_workspace),
    user: AuthUser = Depends(get_current_user),
):
    """List all nodes in the active workspace."""
    nodes = await Node.find(Node.workspace_id == workspace.id).to_list()
    return nodes


@router.post("", response_model=CreateNodeResponse)
async def create_node(
    req: CreateNodeRequest,
    request: Request,
    workspace: Workspace = Depends(get_active_workspace),
    user: AuthUser = Depends(get_current_user),
):
    """Create a new node and issue a high-entropy one-time activation token."""
    node, raw_token = await create_node_with_activation(
        workspace_id=workspace.id,
        name=req.name,
        description=req.description,
    )

    base_url = str(request.base_url).rstrip("/")
    install_cmd = f'curl -fsSL {base_url}/install.sh | sh -s -- --token "{raw_token}" --url "{base_url}"'

    return CreateNodeResponse(
        node_id=node.id,
        activation_token=raw_token,
        install_command=install_cmd,
        expires_in_minutes=60,
    )


@router.post("/{node_id}/revoke")
async def revoke_node_credential(
    node_id: str,
    workspace: Workspace = Depends(get_active_workspace),
    user: AuthUser = Depends(get_current_user),
):
    """Revoke credentials for a node."""
    node = await Node.find_one(Node.id == node_id, Node.workspace_id == workspace.id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    creds = await NodeCredential.find(
        NodeCredential.node_id == node.id,
        NodeCredential.workspace_id == workspace.id,
    ).to_list()

    now = datetime.now(timezone.utc)
    for c in creds:
        c.revoked = True
        c.revoked_at = now
        await c.save()

    node.activation_status = "REVOKED"
    node.status = "OFFLINE"
    node.updated_at = now
    await node.save()

    await record_and_dispatch_event(
        workspace_id=workspace.id,
        event_type="CREDENTIAL_REVOKED",
        source_type="node",
        source_id=node.id,
        severity="WARNING",
        title="Node Credential Revoked",
        message=f"Credentials for node '{node.name}' revoked by {user.email}.",
    )

    return {"status": "REVOKED", "node_id": node.id}

@router.delete("/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_node(
    node_id: str,
    workspace: Workspace = Depends(get_active_workspace),
    user: AuthUser = Depends(get_current_user),
):
    """Delete a node and cleanup its credentials, activations, and historical metrics."""
    node = await Node.find_one(Node.id == node_id, Node.workspace_id == workspace.id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    from overseer.models.node import NodeActivation, NodeCredential, NodeMetric
    await NodeCredential.find(NodeCredential.node_id == node_id).delete()
    await NodeActivation.find(NodeActivation.node_id == node_id).delete()
    await NodeMetric.find(NodeMetric.node_id == node_id).delete()
    await node.delete()

    await record_and_dispatch_event(
        workspace_id=workspace.id,
        event_type="NODE_DELETED",
        source_type="node",
        source_id=node_id,
        severity="WARNING",
        title="Node Deleted",
        message=f"Node '{node.name}' and all associated telemetry were purged by {user.email}.",
    )
    return None
