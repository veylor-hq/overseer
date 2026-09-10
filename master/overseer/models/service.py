"""Monitored Service and Check Beanie Document Models."""

from datetime import datetime, timezone
from typing import Optional
from beanie import Document, Indexed
from pydantic import Field
import pymongo


class MonitoredService(Document):
    id: str = Field(..., description="Service ID: svc_...")
    workspace_id: Indexed(str) = Field(...)
    name: str = Field(..., min_length=1, max_length=100)
    url: str = Field(..., description="Target URL (e.g. https://api.egarageapp.uk/health)")
    method: str = Field(default="GET")
    expected_status: int = Field(default=200)
    timeout_seconds: int = Field(default=10)
    interval_seconds: int = Field(default=60)
    enabled: bool = Field(default=True)
    starred: bool = Field(default=False)
    status: str = Field(default="UNKNOWN", description="OPERATIONAL, DEGRADED, OFFLINE, UNKNOWN")
    last_checked_at: Optional[datetime] = Field(default=None)
    last_response_time_ms: Optional[float] = Field(default=None)
    uptime_percent: float = Field(default=100.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "monitored_services"
        indexes = [
            [("workspace_id", pymongo.ASCENDING), ("id", pymongo.ASCENDING)],
            [("workspace_id", pymongo.ASCENDING), ("enabled", pymongo.ASCENDING)],
            [("starred", pymongo.DESCENDING)],
        ]


class ServiceCheck(Document):
    id: str = Field(...)
    workspace_id: Indexed(str) = Field(...)
    service_id: Indexed(str) = Field(...)
    checked_at: Indexed(datetime) = Field(...)
    status: str = Field(..., description="OPERATIONAL, DEGRADED, OFFLINE")
    response_time_ms: Optional[float] = Field(default=None)
    status_code: Optional[int] = Field(default=None)
    error: Optional[str] = Field(default=None)

    class Settings:
        name = "service_checks"
        indexes = [
            [("workspace_id", pymongo.ASCENDING), ("service_id", pymongo.ASCENDING), ("checked_at", pymongo.DESCENDING)],
            [("service_id", pymongo.ASCENDING), ("checked_at", pymongo.DESCENDING)],
        ]
