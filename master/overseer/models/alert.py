"""Alert Destination and Incident Beanie Document Models."""

from datetime import datetime, timezone
from typing import List, Optional
from beanie import Document, Indexed
from pydantic import Field
import pymongo


class AlertDestination(Document):
    id: str = Field(..., description="Alert Destination ID: alt_...")
    workspace_id: Indexed(str) = Field(...)
    name: str = Field(..., min_length=1, max_length=100)
    channel_type: str = Field(default="telegram", description="telegram")
    # Encrypted bot token (AES-256-GCM) - never returned unmasked in general APIs
    telegram_bot_token_encrypted: str = Field(...)
    telegram_chat_id: str = Field(...)
    telegram_topic_id: Optional[str] = Field(default=None)
    triggers: List[str] = Field(
        default_factory=lambda: [
            "NODE_OFFLINE",
            "NODE_RECOVERED",
            "SERVICE_DOWN",
            "SERVICE_RECOVERED",
        ]
    )
    enabled: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "alert_destinations"
        indexes = [
            [("workspace_id", pymongo.ASCENDING)],
            [("workspace_id", pymongo.ASCENDING), ("enabled", pymongo.ASCENDING)],
        ]


class AlertIncident(Document):
    """
    Tracks persistent failure incidents for alert throttling.
    Strict Rule: Maximum two failure notifications per persistent outage,
    followed by suppression until full recovery.
    """
    id: str = Field(...)
    workspace_id: Indexed(str) = Field(...)
    source_type: str = Field(..., description="'node' or 'service'")
    source_id: Indexed(str) = Field(...)
    failure_count: int = Field(default=0, description="Count of sent failure notifications (max 2)")
    active: bool = Field(default=True, description="True while source is failing, False once recovered")
    first_failure_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_failure_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_notified_at: Optional[datetime] = Field(default=None)
    recovered_at: Optional[datetime] = Field(default=None)

    class Settings:
        name = "alert_incidents"
        indexes = [
            [("workspace_id", pymongo.ASCENDING), ("source_id", pymongo.ASCENDING), ("active", pymongo.ASCENDING)],
            [("source_id", pymongo.ASCENDING)],
        ]
