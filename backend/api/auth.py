"""Discord OAuth endpoints for dashboard authentication."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, status
from fastapi.responses import RedirectResponse, JSONResponse
from redis.asyncio import Redis

from backend.config import config
from backend.services.auth_service import (
    build_discord_authorize_url,
    decode_app_token,
    exchange_code_for_access_token,
    fetch_discord_user,
    issue_app_token,
    parse_state_token,
)
from backend.services.auth_guild_sync import sync_user_guilds_background
from backend.dependencies import get_redis

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


def _allowed_redirect_uris() -> list[str]:
    return config.discord_oauth_allowed_redirect_uris


def _is_allowed_redirect_uri(redirect_uri: str) -> bool:
    normalized = redirect_uri.rstrip("/")
    return any(
        normalized == allowed or normalized.startswith(f"{allowed}?")
        for allowed in _allowed_redirect_uris()
    )


def _append_query_param(url: str, key: str, value: str) -> str:
    parsed = urlparse(url)
    q = dict(parse_qsl(parsed.query, keep_blank_values=True))
    q[key] = value
    return urlunparse(parsed._replace(query=urlencode(q)))


@router.get("/discord")
async def start_discord_oauth(
    redirect_uri: str = Query(..., description="Frontend callback URL"),
):
    """Start Discord OAuth flow and redirect user to Discord authorize page."""
    if not _is_allowed_redirect_uri(redirect_uri):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="redirect_uri is not allowed.",
        )

    discord_url = build_discord_authorize_url(
        redirect_uri=redirect_uri,
        callback_url=redirect_uri,
    )
    logger.info(
        "auth_discord_start",
        redirect_uri=redirect_uri,
    )
    return RedirectResponse(url=discord_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get("/callback")
async def discord_oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
    background_tasks: BackgroundTasks,
    redis: Redis = Depends(get_redis),
):
    """Legacy handler (browser redirect flow)."""
    redirect_uri = parse_state_token(state)
    if not _is_allowed_redirect_uri(redirect_uri):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="redirect_uri is not allowed.",
        )

    callback_url = redirect_uri
    access_token = await exchange_code_for_access_token(code, callback_url)
    discord_user = await fetch_discord_user(access_token)

    user_id = str(discord_user.get("id", ""))
    background_tasks.add_task(
        sync_user_guilds_background, access_token, user_id, redis
    )

    app_token = issue_app_token(discord_user)
    final_url = _append_query_param(redirect_uri, "token", app_token)
    logger.info("auth_discord_success_legacy", discord_user_id=discord_user.get("id"))
    return RedirectResponse(url=final_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.post("/callback")
async def discord_oauth_callback_json(
    code: str = Query(...),
    state: str = Query(...),
    background_tasks: BackgroundTasks,
    redis: Redis = Depends(get_redis),
):
    """Handle Discord callback for frontend — return token quickly, sync guilds in background."""
    redirect_uri = parse_state_token(state)
    if not _is_allowed_redirect_uri(redirect_uri):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="redirect_uri is not allowed.",
        )

    callback_url = redirect_uri
    access_token = await exchange_code_for_access_token(code, callback_url)
    discord_user = await fetch_discord_user(access_token)

    user_id = str(discord_user.get("id", ""))
    background_tasks.add_task(
        sync_user_guilds_background, access_token, user_id, redis
    )

    app_token = issue_app_token(discord_user)
    logger.info("auth_discord_success_json", discord_user_id=discord_user.get("id"))
    return JSONResponse(
        {
            "token": app_token,
            "redirect": "/dashboard",
        }
    )


@router.get("/me")
async def get_me(authorization: str | None = Header(default=None)):
    """Return user profile from app Bearer token."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
        )

    token = authorization.split(" ", 1)[1].strip()
    payload = decode_app_token(token)
    return {
        "id": str(payload.get("sub", "")),
        "username": str(payload.get("username", "Discord User")),
        "avatar_url": payload.get("avatar_url"),
    }
