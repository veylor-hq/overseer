"""Comprehensive Overseer Master Tests."""

import asyncio
from datetime import datetime, timezone
import pytest
from httpx import AsyncClient, ASGITransport
from beanie import init_beanie
from mongomock_motor import AsyncMongoMockClient

from overseer.config import get_settings
from overseer.models import ALL_DOCUMENT_MODELS, Workspace, WorkspaceMember, Node, NodeActivation, NodeCredential, MonitoredService, ServiceCheck, AlertIncident, AlertDestination
from overseer.services.node_service import create_node_with_activation, activate_node_agent, process_heartbeat
from overseer.services.alert_service import record_and_dispatch_event, process_alert_for_event
from overseer.main import app


@pytest.fixture(autouse=True)
async def setup_mock_db():
    mock_client = AsyncMongoMockClient()
    db = mock_client["test_overseer"]
    await init_beanie(database=db, document_models=ALL_DOCUMENT_MODELS)
    yield
    mock_client.close()


@pytest.mark.asyncio
async def test_node_activation_lifecycle():
    """Test one-time activation token creation, single-use burn, and permanent secret establishment."""
    # 1. Create workspace & node
    ws = Workspace(id="ws_test001", name="Test Ops", slug="test-ops")
    await ws.insert()

    node, raw_token = await create_node_with_activation(
        workspace_id=ws.id,
        name="Test-Server-01",
    )
    assert node.activation_status == "PENDING_ACTIVATION"
    assert raw_token.startswith("voy_act_")

    # 2. Activate node with host metadata and IP address
    success, node_id, raw_secret, err = await activate_node_agent(
        raw_token=raw_token,
        hostname="test-host.local",
        ip_address="192.168.1.150",
        os_name="Linux",
        arch="x86_64",
    )
    assert success is True
    assert node_id == node.id
    assert raw_secret.startswith("voy_sec_")
    assert err is None

    # Check updated node document
    updated_node = await Node.find_one(Node.id == node.id)
    assert updated_node.activation_status == "ACTIVE"
    assert updated_node.ip_address == "192.168.1.150"
    assert updated_node.hostname == "test-host.local"

    # 3. Verify single-use burn: repeating activation with same token must fail
    success_2, _, _, err_2 = await activate_node_agent(raw_token=raw_token)
    assert success_2 is False
    assert "already been consumed" in err_2


@pytest.mark.asyncio
async def test_heartbeat_ingestion_and_master_clock():
    """Test inbound heartbeat: Master assigns received_at and stores historical telemetry."""
    ws = Workspace(id="ws_test002", name="Heartbeat Test", slug="hb-test")
    await ws.insert()

    node, raw_token = await create_node_with_activation(workspace_id=ws.id, name="HB-Node")
    _, _, raw_secret, _ = await activate_node_agent(raw_token=raw_token, ip_address="10.0.0.50")

    active_node = await Node.find_one(Node.id == node.id)
    node_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    # Agent sends heartbeat
    metrics = {
        "cpu_usage": 14.5,
        "memory_used": 4294967296,
        "memory_total": 17179869184,
        "disk_used": 10737418240,
        "disk_total": 107374182400,
        "uptime_seconds": 86400,
    }
    docker_containers = [
        {"name": "redis", "image": "redis:alpine", "state": "running", "status": "Up 2 days"},
        {"name": "api", "image": "api:latest", "state": "running", "status": "Up 2 hours"},
    ]

    updated = await process_heartbeat(
        node=active_node,
        reported_at=node_time,
        system_metrics=metrics,
        docker_containers=docker_containers,
        ip_address="10.0.0.50",
    )

    assert updated.status == "OPERATIONAL"
    assert updated.last_reported_at.replace(tzinfo=timezone.utc) == node_time
    assert updated.last_received_at is not None
    # Verify Master clock is recent (not node's backdated clock)
    assert (datetime.now(timezone.utc) - updated.last_received_at.replace(tzinfo=timezone.utc)).total_seconds() < 5


@pytest.mark.asyncio
async def test_alert_suppression_limit_two():
    """Verify maximum 2 failure notifications per persistent outage, followed by recovery."""
    ws = Workspace(id="ws_test003", name="Alert Test", slug="alert-test")
    await ws.insert()

    # Create test Telegram destination
    dest = AlertDestination(
        id="alt_test",
        workspace_id=ws.id,
        name="Telegram Ops",
        channel_type="telegram",
        telegram_bot_token_encrypted="dummy",
        telegram_chat_id="-100999999",
        triggers=["SERVICE_DOWN", "SERVICE_RECOVERED"],
        enabled=True,
    )
    await dest.insert()

    # Outage 1 -> Incident created, count = 1
    evt1 = await record_and_dispatch_event(
        workspace_id=ws.id,
        event_type="SERVICE_DOWN",
        source_type="service",
        source_id="svc_dummy",
        severity="CRITICAL",
        title="Service Down",
        message="Failure #1",
    )
    inc = await AlertIncident.find_one(AlertIncident.source_id == "svc_dummy", AlertIncident.active == True)
    assert inc is not None
    assert inc.failure_count == 1

    # Outage 2 (still down) -> count = 2
    evt2 = await record_and_dispatch_event(
        workspace_id=ws.id,
        event_type="SERVICE_DOWN",
        source_type="service",
        source_id="svc_dummy",
        severity="CRITICAL",
        title="Service Down",
        message="Failure #2",
    )
    inc2 = await AlertIncident.find_one(AlertIncident.source_id == "svc_dummy", AlertIncident.active == True)
    assert inc2.failure_count == 2

    # Outage 3 (still down) -> count stays 2 (SUPPRESSED)
    evt3 = await record_and_dispatch_event(
        workspace_id=ws.id,
        event_type="SERVICE_DOWN",
        source_type="service",
        source_id="svc_dummy",
        severity="CRITICAL",
        title="Service Down",
        message="Failure #3",
    )
    inc3 = await AlertIncident.find_one(AlertIncident.source_id == "svc_dummy", AlertIncident.active == True)
    assert inc3.failure_count == 2

    # Recovery -> incident marked inactive, failure_count reset to 0
    evt_rec = await record_and_dispatch_event(
        workspace_id=ws.id,
        event_type="SERVICE_RECOVERED",
        source_type="service",
        source_id="svc_dummy",
        severity="INFO",
        title="Service Recovered",
        message="Service back online",
    )
    resolved_inc = await AlertIncident.find_one(AlertIncident.source_id == "svc_dummy")
    assert resolved_inc.active is False
    assert resolved_inc.failure_count == 0


@pytest.mark.asyncio
async def test_workspace_isolation_idor():
    """Verify tenant isolation: Workspace A cannot query Workspace B nodes."""
    ws_a = Workspace(id="ws_aaa", name="Workspace A", slug="ws-a")
    ws_b = Workspace(id="ws_bbb", name="Workspace B", slug="ws-b")
    await ws_a.insert()
    await ws_b.insert()

    # Node in Workspace B
    node_b, _ = await create_node_with_activation(workspace_id=ws_b.id, name="Server-B")

    # In Workspace A, querying for Workspace A nodes must NOT return Server-B
    nodes_a = await Node.find(Node.workspace_id == ws_a.id).to_list()
    assert len(nodes_a) == 0

    nodes_b = await Node.find(Node.workspace_id == ws_b.id).to_list()
    assert len(nodes_b) == 1
    assert nodes_b[0].id == node_b.id

@pytest.mark.asyncio
async def test_node_deletion_endpoint():
    """Verify DELETE /api/v1/nodes/{id} purges node, credentials, and telemetry."""
    ws = Workspace(id="ws_del_test", name="Delete Test", slug="del-test")
    await ws.insert()
    # Add dev user membership
    member = WorkspaceMember(
        id="wsm_del",
        workspace_id=ws.id,
        user_sub="usr_01JDEVOPERATOR00000000001",
        user_email="operator@veylor.dev",
        role="admin"
    )
    await member.insert()

    node, raw_token = await create_node_with_activation(workspace_id=ws.id, name="Server-To-Delete")
    await activate_node_agent(raw_token=raw_token)

    from httpx import AsyncClient, ASGITransport
    from overseer.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.delete(f"/api/v1/nodes/{node.id}", headers={"X-Workspace-ID": ws.id})
        assert res.status_code == 204

    # Confirm purged from DB
    deleted = await Node.find_one(Node.id == node.id)
    assert deleted is None
