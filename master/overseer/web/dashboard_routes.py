from pathlib import Path
"""Web UI Routes: Defense Dashboard, Nodes, Services, Alerts, Events, and HTMX fragments."""

from datetime import datetime, timezone
import logging
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from overseer.config import get_settings
from overseer.models.alert import AlertDestination
from overseer.models.event import Event
from overseer.models.node import Node, NodeCredential, NodeMetric
from overseer.models.service import MonitoredService, ServiceCheck
from overseer.models.workspace import Workspace
from overseer.security.auth import AuthUser, get_active_workspace, get_current_user_optional
from overseer.security.credentials import encrypt_secret, generate_id
from overseer.services.alert_service import send_test_telegram_alert
from overseer.services.monitor_service import check_single_service
from overseer.services.node_service import create_node_with_activation

from zoneinfo import ZoneInfo

logger = logging.getLogger("overseer.web")
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

LONDON_TZ = ZoneInfo("Europe/London")

def format_local_time(dt, fmt="%Y-%m-%d %H:%M:%S %Z"):
    if not dt:
        return "Never"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(LONDON_TZ).strftime(fmt)

templates.env.filters["local_time"] = format_local_time
templates.env.globals["format_local_time"] = format_local_time

router = APIRouter(include_in_schema=False)


# Context helper
def get_base_context(request: Request, user: AuthUser, workspace: Workspace, active_tab: str = "dashboard"):
    settings = get_settings()
    return {
        "request": request,
        "user": user,
        "workspace": workspace,
        "active_tab": active_tab,
        "env": settings.ENV,
        "app_name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "now": datetime.now(LONDON_TZ),
        "format_local_time": format_local_time,
    }


@router.get("/", response_class=HTMLResponse)
async def dashboard_view(
    request: Request,
    user: AuthUser = Depends(get_current_user_optional),
):
    if not user:
        return RedirectResponse(url="/auth/login")

    workspace = await get_active_workspace(request, user)
    nodes = await Node.find(Node.workspace_id == workspace.id).sort(-Node.status).to_list()
    services = await MonitoredService.find(
        MonitoredService.workspace_id == workspace.id
    ).sort(-MonitoredService.starred, MonitoredService.name).to_list()
    recent_events = await Event.find(
        Event.workspace_id == workspace.id
    ).sort(-Event.created_at).limit(10).to_list()

    # Calculate system posture
    offline_nodes = [n for n in nodes if n.status in ["OFFLINE", "STALE"]]
    down_services = [s for s in services if s.status in ["OFFLINE", "DEGRADED"]]
    system_posture = "OPERATIONAL" if not (offline_nodes or down_services) else "DEGRADED"

    ctx = get_base_context(request, user, workspace, active_tab="dashboard")
    ctx.update({
        "nodes": nodes,
        "services": services,
        "recent_events": recent_events,
        "system_posture": system_posture,
        "total_nodes": len(nodes),
        "total_services": len(services),
    })
    return templates.TemplateResponse(request=request, name="dashboard.html", context=ctx)


@router.get("/partials/dashboard-grid", response_class=HTMLResponse)
async def dashboard_grid_partial(
    request: Request,
    user: AuthUser = Depends(get_current_user_optional),
):
    """HTMX polling endpoint to refresh the status grid every 10-30 seconds."""
    if not user:
        return HTMLResponse("<script>window.location.reload();</script>")

    workspace = await get_active_workspace(request, user)
    nodes = await Node.find(Node.workspace_id == workspace.id).sort(-Node.status).to_list()
    services = await MonitoredService.find(
        MonitoredService.workspace_id == workspace.id
    ).sort(-MonitoredService.starred, MonitoredService.name).to_list()
    recent_events = await Event.find(
        Event.workspace_id == workspace.id
    ).sort(-Event.created_at).limit(10).to_list()

    ctx = get_base_context(request, user, workspace, active_tab="dashboard")
    ctx.update({
        "nodes": nodes,
        "services": services,
        "recent_events": recent_events,
    })
    return templates.TemplateResponse(request=request, name="partials/dashboard_grid.html", context=ctx)


# --- Nodes Views ---

@router.get("/nodes", response_class=HTMLResponse)
async def nodes_view(
    request: Request,
    user: AuthUser = Depends(get_current_user_optional),
):
    if not user:
        return RedirectResponse(url="/auth/login")

    workspace = await get_active_workspace(request, user)
    nodes = await Node.find(Node.workspace_id == workspace.id).sort(-Node.created_at).to_list()

    ctx = get_base_context(request, user, workspace, active_tab="nodes")
    ctx.update({"nodes": nodes})
    return templates.TemplateResponse(request=request, name="nodes/index.html", context=ctx)


@router.post("/nodes/create")
async def create_node_form(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    user: AuthUser = Depends(get_current_user_optional),
):
    if not user:
        return RedirectResponse(url="/auth/login")

    workspace = await get_active_workspace(request, user)
    node, raw_token = await create_node_with_activation(
        workspace_id=workspace.id,
        name=name.strip(),
        description=description.strip() or None,
    )

    base_url = str(request.base_url).rstrip("/")
    install_cmd = f'curl -fsSL {base_url}/install.sh | sh -s -- --token "{raw_token}" --url "{base_url}"'

    # Render post-create modal view with curl command and token
    ctx = get_base_context(request, user, workspace, active_tab="nodes")
    ctx.update({
        "node": node,
        "activation_token": raw_token,
        "install_command": install_cmd,
    })
    return templates.TemplateResponse(request=request, name="nodes/activation_instructions.html", context=ctx)


@router.get("/nodes/{node_id}", response_class=HTMLResponse)
async def node_detail_view(
    node_id: str,
    request: Request,
    user: AuthUser = Depends(get_current_user_optional),
):
    if not user:
        return RedirectResponse(url="/auth/login")

    workspace = await get_active_workspace(request, user)
    node = await Node.find_one(Node.id == node_id, Node.workspace_id == workspace.id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    recent_metrics = await NodeMetric.find(
        NodeMetric.node_id == node.id
    ).sort(-NodeMetric.received_at).limit(20).to_list()

    ctx = get_base_context(request, user, workspace, active_tab="nodes")
    ctx.update({
        "node": node,
        "recent_metrics": recent_metrics,
    })
    return templates.TemplateResponse(request=request, name="nodes/detail.html", context=ctx)


# --- Services Views ---

@router.get("/services", response_class=HTMLResponse)
async def services_view(
    request: Request,
    user: AuthUser = Depends(get_current_user_optional),
):
    if not user:
        return RedirectResponse(url="/auth/login")

    workspace = await get_active_workspace(request, user)
    services = await MonitoredService.find(
        MonitoredService.workspace_id == workspace.id
    ).sort(-MonitoredService.starred, MonitoredService.name).to_list()

    ctx = get_base_context(request, user, workspace, active_tab="services")
    ctx.update({"services": services})
    return templates.TemplateResponse(request=request, name="services/index.html", context=ctx)


@router.post("/services/create")
async def create_service_form(
    request: Request,
    name: str = Form(...),
    url: str = Form(...),
    method: str = Form("GET"),
    expected_status: int = Form(200),
    interval_seconds: int = Form(60),
    timeout_seconds: int = Form(10),
    starred: bool = Form(False),
    user: AuthUser = Depends(get_current_user_optional),
):
    if not user:
        return RedirectResponse(url="/auth/login")

    workspace = await get_active_workspace(request, user)
    service = MonitoredService(
        id=generate_id("svc"),
        workspace_id=workspace.id,
        name=name.strip(),
        url=url.strip(),
        method=method.upper().strip(),
        expected_status=expected_status,
        interval_seconds=interval_seconds,
        timeout_seconds=timeout_seconds,
        starred=starred,
        status="UNKNOWN",
    )
    await service.insert()
    await check_single_service(service)
    return RedirectResponse(url="/services", status_code=status.HTTP_302_FOUND)


# --- Alerts Views ---

@router.get("/alerts", response_class=HTMLResponse)
async def alerts_view(
    request: Request,
    user: AuthUser = Depends(get_current_user_optional),
):
    if not user:
        return RedirectResponse(url="/auth/login")

    workspace = await get_active_workspace(request, user)
    destinations = await AlertDestination.find(
        AlertDestination.workspace_id == workspace.id
    ).to_list()

    ctx = get_base_context(request, user, workspace, active_tab="alerts")
    ctx.update({"destinations": destinations})
    return templates.TemplateResponse(request=request, name="alerts/index.html", context=ctx)


@router.post("/alerts/destinations/create")
async def create_alert_destination_form(
    request: Request,
    name: str = Form(...),
    bot_token: str = Form(...),
    chat_id: str = Form(...),
    topic_id: str = Form(""),
    user: AuthUser = Depends(get_current_user_optional),
):
    if not user:
        return RedirectResponse(url="/auth/login")

    workspace = await get_active_workspace(request, user)
    dest = AlertDestination(
        id=generate_id("alt"),
        workspace_id=workspace.id,
        name=name.strip(),
        channel_type="telegram",
        telegram_bot_token_encrypted=encrypt_secret(bot_token.strip()),
        telegram_chat_id=chat_id.strip(),
        telegram_topic_id=topic_id.strip() or None,
        triggers=["NODE_OFFLINE", "NODE_RECOVERED", "SERVICE_DOWN", "SERVICE_RECOVERED"],
        enabled=True,
    )
    await dest.insert()
    return RedirectResponse(url="/alerts", status_code=status.HTTP_302_FOUND)


@router.post("/alerts/destinations/{dest_id}/test")
async def test_alert_destination_web(
    dest_id: str,
    request: Request,
    user: AuthUser = Depends(get_current_user_optional),
):
    if not user:
        return RedirectResponse(url="/auth/login")

    workspace = await get_active_workspace(request, user)
    dest = await AlertDestination.find_one(
        AlertDestination.id == dest_id,
        AlertDestination.workspace_id == workspace.id,
    )
    if dest:
        await send_test_telegram_alert(dest)
    return RedirectResponse(url="/alerts", status_code=status.HTTP_302_FOUND)


# --- Events Views ---

@router.get("/events", response_class=HTMLResponse)
async def events_view(
    request: Request,
    user: AuthUser = Depends(get_current_user_optional),
):
    if not user:
        return RedirectResponse(url="/auth/login")

    workspace = await get_active_workspace(request, user)
    events = await Event.find(
        Event.workspace_id == workspace.id
    ).sort(-Event.created_at).limit(100).to_list()

    ctx = get_base_context(request, user, workspace, active_tab="events")
    ctx.update({"events": events})
    return templates.TemplateResponse(request=request, name="events/index.html", context=ctx)
