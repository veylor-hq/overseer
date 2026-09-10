"""Workspace and WorkspaceMember Beanie Document Models."""

from datetime import datetime, timezone
from typing import Optional
from beanie import Document, Indexed
from pydantic import Field
import pymongo


class Workspace(Document):
    id: str = Field(..., description="Unique workspace ID: ws_...")
    name: str = Field(..., min_length=1, max_length=100)
    slug: Indexed(str, unique=True) = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "workspaces"
        indexes = [
            [("slug", pymongo.ASCENDING)],
            [("created_at", pymongo.DESCENDING)],
        ]


class WorkspaceMember(Document):
    id: str = Field(...)
    workspace_id: Indexed(str) = Field(...)
    user_sub: Indexed(str) = Field(..., description="Immutable Veylor SSO sub (usr_01J...)")
    user_email: str = Field(...)
    user_name: str = Field(default="")
    role: str = Field(default="admin", description="'admin' or 'member'")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "workspace_members"
        indexes = [
            [("workspace_id", pymongo.ASCENDING), ("user_sub", pymongo.ASCENDING)],
            [("user_sub", pymongo.ASCENDING)],
        ]
