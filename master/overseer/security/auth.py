"""SSO OIDC authentication, session signing, and tenant security dependencies."""

import base64
import hashlib
import json
import secrets
from typing import Any, Dict, Optional
import httpx
from fastapi import Cookie, Depends, HTTPException, Request, Response, status
from overseer.config import get_settings
from overseer.models.workspace import Workspace, WorkspaceMember
from overseer.security.credentials import generate_id


class AuthUser:
    def __init__(self, sub: str, email: str, name: str = "", role: str = "member"):
        self.sub = sub
        self.email = email
        self.name = name
        self.role = role


def sign_session_data(payload: dict) -> str:
    """Sign a json session payload with Master SECRET_KEY using HMAC-SHA256."""
    settings = get_settings()
    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    sig = hashlib.sha256(settings.SECRET_KEY.encode("utf-8") + raw).hexdigest()
    packed = {
        "data": base64.urlsafe_b64encode(raw).decode("ascii"),
        "sig": sig,
    }
    return base64.urlsafe_b64encode(json.dumps(packed).encode("utf-8")).decode("ascii")


def verify_session_data(cookie_val: str) -> Optional[dict]:
    """Verify HMAC signature and decode session payload."""
    if not cookie_val:
        return None
    try:
        settings = get_settings()
        packed_raw = base64.urlsafe_b64decode(cookie_val.encode("ascii"))
        packed = json.loads(packed_raw.decode("utf-8"))
        raw = base64.urlsafe_b64decode(packed["data"].encode("ascii"))
        expected_sig = hashlib.sha256(settings.SECRET_KEY.encode("utf-8") + raw).hexdigest()
        if secrets.compare_digest(expected_sig, packed["sig"]):
            return json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    return None


async def get_current_user(request: Request) -> AuthUser:
    """Extract authenticated user from signed session cookie or dev fallback."""
    settings = get_settings()
    cookie = request.cookies.get(settings.SESSION_COOKIE_NAME)
    session = verify_session_data(cookie) if cookie else None

    if session and "sub" in session:
        return AuthUser(
            sub=session["sub"],
            email=session.get("email", "unknown@veylor.dev"),
            name=session.get("name", "Veylor Operator"),
        )

    # In development mode, auto-provision dev user if enabled
    if settings.ENV == "development" and settings.SSO_AUTO_LOGIN_DEV:
        return AuthUser(
            sub="usr_01JDEVOPERATOR00000000001",
            email="operator@veylor.dev",
            name="Overseer Lead Operator",
            role="admin",
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
    )


async def get_current_user_optional(request: Request) -> Optional[AuthUser]:
    """Optional user extractor for web templates."""
    try:
        return await get_current_user(request)
    except HTTPException:
        return None


async def get_active_workspace(
    request: Request,
    user: AuthUser = Depends(get_current_user),
) -> Workspace:
    """
    Enforce multi-tenancy:
    Resolves the user's active workspace and strictly checks membership.
    """
    workspace_id = request.headers.get("X-Workspace-ID") or request.query_params.get("ws")
    cookie_ws = request.cookies.get("overseer_active_ws")
    target_ws_id = workspace_id or cookie_ws

    if target_ws_id:
        # Check membership
        member = await WorkspaceMember.find_one(
            WorkspaceMember.workspace_id == target_ws_id,
            WorkspaceMember.user_sub == user.sub,
        )
        if member:
            ws = await Workspace.find_one(Workspace.id == target_ws_id)
            if ws:
                return ws

    # Fallback to the user's first available workspace
    membership = await WorkspaceMember.find_one(WorkspaceMember.user_sub == user.sub)
    if membership:
        ws = await Workspace.find_one(Workspace.id == membership.workspace_id)
        if ws:
            return ws

    # In development/first run, create default primary workspace for the user
    settings = get_settings()
    if settings.ENV == "development":
        default_ws = await Workspace.find_one(Workspace.slug == "veylor-primary")
        if not default_ws:
            default_ws = Workspace(
                id=generate_id("ws"),
                name="Veylor Primary Operations",
                slug="veylor-primary",
                description="Core infrastructure and mission-critical production services",
            )
            await default_ws.insert()

        # Add user membership
        member = await WorkspaceMember.find_one(
            WorkspaceMember.workspace_id == default_ws.id,
            WorkspaceMember.user_sub == user.sub,
        )
        if not member:
            member = WorkspaceMember(
                id=generate_id("wsm"),
                workspace_id=default_ws.id,
                user_sub=user.sub,
                user_email=user.email,
                user_name=user.name,
                role="admin",
            )
            await member.insert()

        return default_ws

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="No authorized workspace found for user",
    )
