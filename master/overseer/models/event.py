"""Event Beanie Document Model for Incident and Audit Logging."""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from beanie import Document, Indexed
from pydantic import Field
import pymongo


class Event(Document):
    id: str = Field(..., description="Event ID: evt_...")
    workspace_id: Indexed(str) = Field(...)
    event_type: Indexed(str) = Field(
        ...,
        description="NODE_OFFLINE, NODE_STALE, NODE_RECOVERED, SERVICE_DOWN, SERVICE_DEGRADED, SERVICE_RECOVERED, NODE_ACTIVATED, CREDENTIAL_REVOKED",
    )
    source_type: str = Field(..., description="node, service, system")
    source_id: str = Field(...)
    severity: str = Field(default="INFO", description="INFO, WARNING, CRITICAL")
    title: str = Field(...)
    message: str = Field(...)
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
    created_at: Indexed(datetime) = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "events"
        indexes = [
            [("workspace_id", pymongo.ASCENDING), ("created_at", pymongo.DESCENDING)],
            [("workspace_id", pymongo.ASCENDING), ("event_type", pymongo.ASCENDING)],
            [("source_id", pymongo.ASCENDING)],
        ]
