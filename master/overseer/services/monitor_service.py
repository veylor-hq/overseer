"""HTTP Service Health Checker & Uptime Calculation."""

import asyncio
from datetime import datetime, timezone
import logging
import time
import httpx
from overseer.models.service import MonitoredService, ServiceCheck
from overseer.security.credentials import generate_id
from overseer.services.alert_service import record_and_dispatch_event

logger = logging.getLogger("overseer.monitor")


async def check_single_service(service: MonitoredService) -> None:
    """Execute an outbound HTTP health check against a monitored endpoint."""
    now = datetime.now(timezone.utc)
    start_time = time.perf_counter()
    status_code = None
    error_str = None
    is_healthy = False

    try:
        async with httpx.AsyncClient(
            timeout=float(service.timeout_seconds),
            follow_redirects=True,
            verify=False,
        ) as client:
            res = await client.request(service.method, service.url)
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            status_code = res.status_code
            if status_code == service.expected_status:
                is_healthy = True
            else:
                error_str = f"Expected {service.expected_status}, received HTTP {status_code}"
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        error_str = str(e)
        is_healthy = False

    new_status = "OPERATIONAL" if is_healthy else "OFFLINE"
    previous_status = service.status

    # Record check
    check = ServiceCheck(
        id=generate_id("chk"),
        workspace_id=service.workspace_id,
        service_id=service.id,
        checked_at=now,
        status=new_status,
        response_time_ms=round(elapsed_ms, 2),
        status_code=status_code,
        error=error_str,
    )
    await check.insert()

    # Recalculate rolling uptime percent (last 50 checks)
    recent_checks = await ServiceCheck.find(
        ServiceCheck.service_id == service.id
    ).sort(-ServiceCheck.checked_at).limit(50).to_list()

    if recent_checks:
        healthy_count = sum(1 for c in recent_checks if c.status == "OPERATIONAL")
        service.uptime_percent = round((healthy_count / len(recent_checks)) * 100.0, 2)

    service.status = new_status
    service.last_checked_at = now
    service.last_response_time_ms = round(elapsed_ms, 2)
    service.updated_at = now
    await service.save()

    # Trigger events on state change
    if previous_status == "OPERATIONAL" and new_status == "OFFLINE":
        await record_and_dispatch_event(
            workspace_id=service.workspace_id,
            event_type="SERVICE_DOWN",
            source_type="service",
            source_id=service.id,
            severity="CRITICAL",
            title="Service Outage Detected",
            message=f"Service '{service.name}' ({service.url}) check failed: {error_str or 'HTTP error'}",
            metadata={"status_code": status_code, "error": error_str},
        )
    elif previous_status == "OFFLINE" and new_status == "OPERATIONAL":
        await record_and_dispatch_event(
            workspace_id=service.workspace_id,
            event_type="SERVICE_RECOVERED",
            source_type="service",
            source_id=service.id,
            severity="INFO",
            title="Service Recovered",
            message=f"Service '{service.name}' ({service.url}) is responding normally (HTTP {status_code}, {elapsed_ms:.1f}ms).",
            metadata={"status_code": status_code, "response_time_ms": elapsed_ms},
        )


async def run_monitoring_tick() -> None:
    """Evaluate services due for health checking."""
    now = datetime.now(timezone.utc)
    services = await MonitoredService.find(MonitoredService.enabled == True).to_list()

    tasks = []
    for s in services:
        if not s.last_checked_at:
            tasks.append(check_single_service(s))
        else:
            last_checked = s.last_checked_at if s.last_checked_at.tzinfo else s.last_checked_at.replace(tzinfo=timezone.utc)
            elapsed = (now - last_checked).total_seconds()
            if elapsed >= s.interval_seconds:
                tasks.append(check_single_service(s))

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
