"""Alert Dispatcher with 2-failure limit suppression and recovery notification."""

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import httpx

LONDON_TZ = ZoneInfo("Europe/London")
from overseer.models.alert import AlertDestination, AlertIncident
from overseer.models.event import Event
from overseer.security.credentials import decrypt_secret, generate_id

logger = logging.getLogger("overseer.alert")


async def record_and_dispatch_event(
    workspace_id: str,
    event_type: str,
    source_type: str,
    source_id: str,
    severity: str,
    title: str,
    message: str,
    metadata: dict = None,
) -> Event:
    """Record event to MongoDB and check alert incident suppression rules."""
    event = Event(
        id=generate_id("evt"),
        workspace_id=workspace_id,
        event_type=event_type,
        source_type=source_type,
        source_id=source_id,
        severity=severity,
        title=title,
        message=message,
        metadata=metadata or {},
        created_at=datetime.now(timezone.utc),
    )
    await event.insert()

    # Process incident suppression logic
    await process_alert_for_event(event)
    return event


async def process_alert_for_event(event: Event) -> None:
    """
    Alert incident state machine:
    - Failure event (e.g. NODE_OFFLINE, SERVICE_DOWN):
      * If failure_count == 0 -> Send Notification #1, failure_count = 1
      * If failure_count == 1 -> Send Notification #2, failure_count = 2
      * If failure_count >= 2 -> SUPPRESS (no more alerts)
    - Recovery event (e.g. NODE_RECOVERED, SERVICE_RECOVERED):
      * If active incident exists -> Send Recovery Alert, reset failure_count = 0, mark inactive
    """
    now = datetime.now(timezone.utc)
    is_failure = event.event_type in ["NODE_OFFLINE", "NODE_STALE", "SERVICE_DOWN", "SERVICE_DEGRADED"]
    is_recovery = event.event_type in ["NODE_RECOVERED", "SERVICE_RECOVERED"]

    incident = await AlertIncident.find_one(
        AlertIncident.workspace_id == event.workspace_id,
        AlertIncident.source_id == event.source_id,
        AlertIncident.active == True,
    )

    should_notify = False
    notification_tag = ""

    if is_failure:
        if not incident:
            incident = AlertIncident(
                id=generate_id("inc"),
                workspace_id=event.workspace_id,
                source_type=event.source_type,
                source_id=event.source_id,
                failure_count=1,
                active=True,
                first_failure_at=now,
                last_failure_at=now,
                last_notified_at=now,
            )
            await incident.insert()
            should_notify = True
            notification_tag = "[FAILURE #1]"
        else:
            incident.last_failure_at = now
            if incident.failure_count < 2:
                incident.failure_count += 1
                incident.last_notified_at = now
                await incident.save()
                should_notify = True
                notification_tag = f"[FAILURE #{incident.failure_count}]"
            else:
                # Suppressed: Already sent 2 notifications
                await incident.save()
                logger.info(
                    f"Alert suppressed for {event.source_id}: reached 2 failure limit"
                )
                should_notify = False

    elif is_recovery:
        if incident and incident.active:
            incident.active = False
            incident.recovered_at = now
            incident.failure_count = 0
            await incident.save()
            should_notify = True
            notification_tag = "[RECOVERED]"

    if should_notify:
        await dispatch_telegram_alerts(event, notification_tag)


async def dispatch_telegram_alerts(event: Event, tag: str) -> None:
    """Send formatted defense-grade Telegram message to configured destinations."""
    destinations = await AlertDestination.find(
        AlertDestination.workspace_id == event.workspace_id,
        AlertDestination.enabled == True,
    ).to_list()

    for dest in destinations:
        if event.event_type not in dest.triggers:
            continue

        raw_token = decrypt_secret(dest.telegram_bot_token_encrypted)
        if not raw_token:
            continue

        event_time_local = event.created_at.replace(tzinfo=timezone.utc).astimezone(LONDON_TZ) if event.created_at.tzinfo is None else event.created_at.astimezone(LONDON_TZ)
        text = (
            f"🚨 <b>OVERSEER ALERT: {event.title}</b> {tag}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Type:</b> <code>{event.event_type}</code>\n"
            f"<b>Severity:</b> {event.severity}\n"
            f"<b>Target:</b> <code>{event.source_id}</code>\n"
            f"<b>Details:</b> {event.message}\n"
            f"<b>Timestamp:</b> <code>{event_time_local.strftime('%Y-%m-%d %H:%M:%S %Z')}</code>"
        )

        telegram_url = f"https://api.telegram.org/bot{raw_token}/sendMessage"
        payload = {
            "chat_id": dest.telegram_chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        if dest.telegram_topic_id:
            payload["message_thread_id"] = dest.telegram_topic_id

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(telegram_url, json=payload)
                if res.status_code != 200:
                    logger.error(f"Telegram dispatch failed: {res.text}")
                else:
                    logger.info(f"Dispatched Telegram alert to chat {dest.telegram_chat_id}")
        except Exception as e:
            logger.error(f"Error dispatching Telegram alert: {e}")


async def send_test_telegram_alert(dest: AlertDestination) -> bool:
    """Dispatch an immediate test alert to verify Telegram credentials."""
    raw_token = decrypt_secret(dest.telegram_bot_token_encrypted)
    if not raw_token:
        return False

    now_local = datetime.now(LONDON_TZ)
    text = (
        f"🛡️ <b>OVERSEER // TELEGRAM TEST DISPATCH</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>Status:</b> SECURE CHANNEL CONFIRMED\n"
        f"<b>Destination:</b> {dest.name}\n"
        f"<b>Timestamp:</b> <code>{now_local.strftime('%Y-%m-%d %H:%M:%S %Z')}</code>\n"
        f"Veylor Overseer alert infrastructure is operational."
    )
    url = f"https://api.telegram.org/bot{raw_token}/sendMessage"
    payload = {
        "chat_id": dest.telegram_chat_id,
        "text": text,
        "parse_mode": "HTML",
    }
    if dest.telegram_topic_id:
        payload["message_thread_id"] = dest.telegram_topic_id

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(url, json=payload)
            return res.status_code == 200
    except Exception as e:
        logger.error(f"Telegram test error: {e}")
        return False
