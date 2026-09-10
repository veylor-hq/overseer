"""Node business logic: Activation, Heartbeat processing, and Status Calculation."""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, Optional, Tuple
from overseer.config import get_settings
from overseer.models.node import Node, NodeActivation, NodeCredential, NodeMetric
from overseer.security.credentials import (
    generate_activation_token,
    generate_id,
    generate_node_credential,
    hash_token,
    verify_node_credential,
)
from overseer.services.alert_service import record_and_dispatch_event

logger = logging.getLogger("overseer.nodes")


async def create_node_with_activation(
    workspace_id: str,
    name: str,
    description: Optional[str] = None,
    expiry_minutes: int = 60,
) -> Tuple[Node, str]:
    """Create a new unactivated node and a single-use high-entropy activation token."""
    node_id = generate_id("node")
    node = Node(
        id=node_id,
        workspace_id=workspace_id,
        name=name,
        description=description,
        status="UNKNOWN",
        activation_status="PENDING_ACTIVATION",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await node.insert()

    raw_token, token_hash = generate_activation_token()
    now = datetime.now(timezone.utc)
    expires_at = datetime.fromtimestamp(now.timestamp() + (expiry_minutes * 60), tz=timezone.utc)

    activation = NodeActivation(
        id=generate_id("act"),
        token_hash=token_hash,
        workspace_id=workspace_id,
        node_id=node_id,
        expires_at=expires_at,
        created_at=now,
    )
    await activation.insert()

    return node, raw_token


async def activate_node_agent(
    raw_token: str,
    hostname: Optional[str] = None,
    os_name: Optional[str] = None,
    arch: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
    """
    Validate one-time activation token and return permanent node credentials.
    Returns: (success, node_id, raw_secret, error_msg)
    """
    token_hash = hash_token(raw_token)
    activation = await NodeActivation.find_one(NodeActivation.token_hash == token_hash)

    if not activation:
        return False, None, None, "Invalid or unknown activation token"

    now = datetime.now(timezone.utc)
    if activation.consumed_at is not None:
        return False, None, None, "Activation token has already been consumed"

    exp = activation.expires_at if activation.expires_at.tzinfo else activation.expires_at.replace(tzinfo=timezone.utc)
    if exp < now:
        return False, None, None, "Activation token has expired"

    node = await Node.find_one(Node.id == activation.node_id)
    if not node:
        return False, None, None, "Associated node not found"

    # Mark token consumed immediately
    activation.consumed_at = now
    await activation.save()

    # Generate permanent credential
    raw_secret, secret_hash = generate_node_credential()
    credential = NodeCredential(
        id=generate_id("cred"),
        workspace_id=node.workspace_id,
        node_id=node.id,
        secret_hash=secret_hash,
        created_at=now,
    )
    await credential.insert()

    # Update node state
    node.activation_status = "ACTIVE"
    if hostname:
        node.hostname = hostname
    if os_name:
        node.os = os_name
    if arch:
        node.arch = arch
    if ip_address:
        node.ip_address = ip_address
    node.status = "OPERATIONAL"
    node.updated_at = now
    await node.save()

    await record_and_dispatch_event(
        workspace_id=node.workspace_id,
        event_type="NODE_ACTIVATED",
        source_type="node",
        source_id=node.id,
        severity="INFO",
        title="Node Activated",
        message=f"Node '{node.name}' successfully activated by agent ({node.hostname or 'unknown'}).",
    )

    return True, node.id, raw_secret, None


async def verify_node_authentication(node_id: str, raw_secret: str) -> Optional[Node]:
    """Verify permanent node credential."""
    node = await Node.find_one(Node.id == node_id)
    if not node or not node.enabled or node.activation_status != "ACTIVE":
        return None

    credential = await NodeCredential.find_one(
        NodeCredential.node_id == node_id,
        NodeCredential.revoked == False,
    )
    if not credential:
        return None

    if verify_node_credential(raw_secret, credential.secret_hash):
        return node
    return None


async def process_heartbeat(
    node: Node,
    reported_at: datetime,
    system_metrics: Dict[str, Any],
    docker_containers: list,
    ip_address: Optional[str] = None,
) -> Node:
    """
    Process inbound heartbeat from Rust agent.
    Master generates authoritative received_at timestamp.
    """
    now = datetime.now(timezone.utc)
    previous_status = node.status

    # Record historical metric
    metric = NodeMetric(
        id=generate_id("met"),
        workspace_id=node.workspace_id,
        node_id=node.id,
        received_at=now,
        reported_at=reported_at,
        ip_address=ip_address or node.ip_address,
        cpu_usage=float(system_metrics.get("cpu_usage", 0.0)),
        memory_used=int(system_metrics.get("memory_used", 0)),
        memory_total=int(system_metrics.get("memory_total", 0)),
        disk_used=int(system_metrics.get("disk_used", 0)),
        disk_total=int(system_metrics.get("disk_total", 0)),
        uptime_seconds=int(system_metrics.get("uptime_seconds", 0)),
        docker_containers=docker_containers,
    )
    await metric.insert()

    # Update Node state
    node.last_received_at = now
    node.last_reported_at = reported_at
    node.status = "OPERATIONAL"
    if ip_address:
        node.ip_address = ip_address
    if "hostname" in system_metrics and system_metrics["hostname"]:
        node.hostname = system_metrics["hostname"]
    if "os" in system_metrics and system_metrics["os"]:
        node.os = system_metrics["os"]
    if "arch" in system_metrics and system_metrics["arch"]:
        node.arch = system_metrics["arch"]

    node.latest_metrics = system_metrics
    node.latest_docker = docker_containers
    node.updated_at = now
    await node.save()

    # Check recovery event
    if previous_status in ["OFFLINE", "STALE"]:
        await record_and_dispatch_event(
            workspace_id=node.workspace_id,
            event_type="NODE_RECOVERED",
            source_type="node",
            source_id=node.id,
            severity="INFO",
            title="Node Recovered",
            message=f"Node '{node.name}' is operational. Received heartbeat at {now.isoformat()}.",
        )

    return node


async def check_all_nodes_liveness() -> None:
    """Background worker task to evaluate node liveness based on Master's received_at."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    nodes = await Node.find(Node.enabled == True, Node.activation_status == "ACTIVE").to_list()

    for node in nodes:
        if not node.last_received_at:
            continue

        last_recv = node.last_received_at if node.last_received_at.tzinfo else node.last_received_at.replace(tzinfo=timezone.utc)
        delta = (now - last_recv).total_seconds()
        if delta > settings.NODE_OFFLINE_THRESHOLD_SECONDS and node.status != "OFFLINE":
            node.status = "OFFLINE"
            node.updated_at = now
            await node.save()
            await record_and_dispatch_event(
                workspace_id=node.workspace_id,
                event_type="NODE_OFFLINE",
                source_type="node",
                source_id=node.id,
                severity="CRITICAL",
                title="Node Offline",
                message=f"Node '{node.name}' heartbeat timeout ({int(delta // 60)} minutes without contact).",
            )
        elif (
            delta > settings.NODE_STALE_THRESHOLD_SECONDS
            and delta <= settings.NODE_OFFLINE_THRESHOLD_SECONDS
            and node.status == "OPERATIONAL"
        ):
            node.status = "STALE"
            node.updated_at = now
            await node.save()
            await record_and_dispatch_event(
                workspace_id=node.workspace_id,
                event_type="NODE_STALE",
                source_type="node",
                source_id=node.id,
                severity="WARNING",
                title="Node Stale",
                message=f"Node '{node.name}' has missed regular heartbeats ({int(delta // 60)}m elapsed).",
            )
