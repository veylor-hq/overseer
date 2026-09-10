"""SSO OIDC Web Routes: Login, Callback, Dev Login, and Logout."""

import base64
import hashlib
import json
import re
import secrets
import urllib.parse
from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
import httpx
from overseer.config import get_settings
from overseer.models.workspace import Workspace, WorkspaceMember
from overseer.security.auth import sign_session_data
from overseer.security.credentials import generate_id

router = APIRouter(prefix="/auth", tags=["Web Auth"])


def generate_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    verifier = re.sub(r"[^A-Za-z0-9\-._~]", "", verifier)[:64]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


@router.get("/login")
async def sso_login(request: Request):
    """Initiate OIDC Authorization Code Flow with PKCE."""
    settings = get_settings()

    # Try connecting to SSO; if unreachable in dev mode, provide direct local operator login
    state = secrets.token_urlsafe(24)
    verifier, challenge = generate_pkce()

    params = {
        "response_type": "code",
        "client_id": settings.SSO_CLIENT_ID,
        "redirect_uri": settings.SSO_REDIRECT_URI,
        "scope": "openid profile email",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    auth_url = f"{settings.SSO_ISSUER}/authorize?{urllib.parse.urlencode(params)}"

    response = RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)
    # Store PKCE verifier and state in temporary cookie
    temp_auth = json.dumps({"state": state, "verifier": verifier})
    response.set_cookie(
        "overseer_oidc_state",
        temp_auth,
        max_age=300,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/callback")
async def sso_callback(
    request: Request,
    code: str = None,
    state: str = None,
    error: str = None,
):
    """Handle OIDC authorization code exchange."""
    settings = get_settings()
    if error:
        return RedirectResponse(f"/?auth_error={urllib.parse.quote(error)}")

    cookie_val = request.cookies.get("overseer_oidc_state")
    if not cookie_val:
        # Fallback to dev login if state cookie missing in development
        if settings.ENV == "development":
            return await dev_login_action(request)
        raise HTTPException(status_code=400, detail="Missing OIDC state cookie")

    try:
        stored = json.loads(cookie_val)
        if stored.get("state") != state:
            raise HTTPException(status_code=400, detail="Mismatched OIDC state")
        verifier = stored.get("verifier")
    except Exception:
        raise HTTPException(status_code=400, detail="Corrupt OIDC state")

    # Exchange authorization code at SSO /token endpoint
    token_url = f"{settings.SSO_ISSUER}/token"
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.post(
                token_url,
                data={
                    "grant_type": "authorization_code",
                    "client_id": settings.SSO_CLIENT_ID,
                    "code": code,
                    "redirect_uri": settings.SSO_REDIRECT_URI,
                    "code_verifier": verifier,
                },
            )
            tokens = res.json()
        except Exception:
            # If SSO is not running locally, graceful fallback in dev
            if settings.ENV == "development":
                return await dev_login_action(request)
            raise HTTPException(status_code=502, detail="Failed to communicate with Veylor SSO")

    # Extract user claims (UserInfo or ID token)
    userinfo_url = f"{settings.SSO_ISSUER}/userinfo"
    async with httpx.AsyncClient(timeout=10.0) as client:
        res = await client.get(
            userinfo_url,
            headers={"Authorization": f"Bearer {tokens.get('access_token')}"},
        )
        userinfo = res.json()

    user_sub = userinfo.get("sub")
    user_email = userinfo.get("email")
    user_name = userinfo.get("name", "Operator")

    return await establish_user_session(request, user_sub, user_email, user_name)


@router.get("/dev-login")
async def dev_login(request: Request):
    """Quick dev login for testing without local SSO daemon."""
    settings = get_settings()
    if settings.ENV != "development":
        raise HTTPException(status_code=403, detail="Dev login disabled in production")
    return await dev_login_action(request)


async def dev_login_action(request: Request):
    return await establish_user_session(
        request=request,
        user_sub="usr_01JDEVOPERATOR00000000001",
        user_email="operator@veylor.dev",
        user_name="Overseer Lead Operator",
    )


async def establish_user_session(request: Request, user_sub: str, user_email: str, user_name: str):
    settings = get_settings()

    # Ensure default workspace membership
    default_ws = await Workspace.find_one(Workspace.slug == "veylor-primary")
    if not default_ws:
        default_ws = Workspace(
            id=generate_id("ws"),
            name="Veylor Primary Operations",
            slug="veylor-primary",
            description="Core infrastructure and mission-critical production services",
        )
        await default_ws.insert()

    member = await WorkspaceMember.find_one(
        WorkspaceMember.workspace_id == default_ws.id,
        WorkspaceMember.user_sub == user_sub,
    )
    if not member:
        member = WorkspaceMember(
            id=generate_id("wsm"),
            workspace_id=default_ws.id,
            user_sub=user_sub,
            user_email=user_email,
            user_name=user_name,
            role="admin",
        )
        await member.insert()

    session_data = {
        "sub": user_sub,
        "email": user_email,
        "name": user_name,
    }
    signed_cookie = sign_session_data(session_data)

    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        settings.SESSION_COOKIE_NAME,
        signed_cookie,
        max_age=settings.SESSION_TTL_SECONDS,
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite="lax",
    )
    response.set_cookie("overseer_active_ws", default_ws.id, max_age=settings.SESSION_TTL_SECONDS)
    response.delete_cookie("overseer_oidc_state")
    return response


@router.get("/logout")
async def logout(request: Request):
    settings = get_settings()
    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(settings.SESSION_COOKIE_NAME)
    response.delete_cookie("overseer_active_ws")
    return response
