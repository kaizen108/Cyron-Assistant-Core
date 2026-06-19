"""Discord OAuth endpoints for dashboard authentication."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from backend.config import config
from backend.services.auth_service import (
    build_discord_authorize_url,
    decode_app_token,
    exchange_code_for_access_token,
    fetch_discord_user,
    fetch_user_guilds,
    issue_app_token,
    parse_state_token,
)
from backend.db.session import get_session
from backend.dependencies import get_redis
from backend.services.guild_service import upsert_guild
from backend.services.user_guild_service import upsert_user_guilds

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


ALLOWED_REDIRECT_URIS: list[str] = [
    "https://cyron-assistant.vercel.app/auth/callback",
    "http://localhost:5173/auth/callback",
]


def _is_allowed_redirect_uri(redirect_uri: str) -> bool:
    return any(redirect_uri.startswith(uri) for uri in ALLOWED_REDIRECT_URIS)


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

    # We now use the frontend callback URL directly as Discord redirect_uri.
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
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
):
    """Legacy handler (no longer used by frontend)."""
    redirect_uri = parse_state_token(state)
    if not _is_allowed_redirect_uri(redirect_uri):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="redirect_uri is not allowed.",
        )

    callback_url = redirect_uri
    access_token = await exchange_code_for_access_token(code, callback_url)
    discord_user = await fetch_discord_user(access_token)

    # Best-effort: sync user's admin/mod guilds into DB so dashboard can list servers.
    try:
        user_guilds = await fetch_user_guilds(access_token)

        def _has_admin_or_manage(perms: object, owner: object) -> bool:
            if owner:
                return True
            try:
                value = int(perms) if perms is not None else 0
            except (TypeError, ValueError):
                value = 0
            # ADMINISTRATOR (0x8) or MANAGE_GUILD (0x20)
            return bool(value & (0x8 | 0x20))

        admin_guilds = [
            g
            for g in user_guilds
            if _has_admin_or_manage(g.get("permissions"), g.get("owner"))
        ]

        # Persist guilds and user↔guild mappings for authorization
        user_id = str(discord_user.get("id", ""))
        admin_guild_ids: list[int] = []

        for g in admin_guilds:
            gid = g.get("id")
            name = g.get("name") or ""
            if not gid:
                continue
            try:
                gid_int = int(gid)
            except (TypeError, ValueError):
                continue

            await upsert_guild(session, gid_int, name=name)
            admin_guild_ids.append(gid_int)

            icon_hash = g.get("icon")
            if icon_hash:
                icon_url = (
                    f"https://cdn.discordapp.com/icons/{gid_int}/{icon_hash}.png"
                )
                await redis.set(f"guild:{gid_int}:icon_url", icon_url)

        # Record which guilds this user may manage.
        if user_id and admin_guild_ids:
            await upsert_user_guilds(session, user_id, admin_guild_ids, role="admin")

        await session.commit()
        logger.info(
            "auth_discord_sync_guilds",
            guild_count=len(admin_guild_ids),
            user_id=user_id,
        )
    except Exception as exc:  # pragma: no cover - non-critical
        logger.warning("auth_discord_sync_guilds_failed", error=str(exc))

    app_token = issue_app_token(discord_user)
    final_url = _append_query_param(redirect_uri, "token", app_token)
    logger.info("auth_discord_success_legacy", discord_user_id=discord_user.get("id"))
    return RedirectResponse(url=final_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.post("/callback")
async def discord_oauth_callback_json(
    code: str = Query(...),
    state: str = Query(...),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
):
    """Handle Discord callback for frontend, issue app token, and return JSON."""
    redirect_uri = parse_state_token(state)
    if not _is_allowed_redirect_uri(redirect_uri):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="redirect_uri is not allowed.",
        )

    callback_url = redirect_uri
    access_token = await exchange_code_for_access_token(code, callback_url)
    discord_user = await fetch_discord_user(access_token)

    # Same guild sync logic as legacy handler
    try:
        user_guilds = await fetch_user_guilds(access_token)

        def _has_admin_or_manage(perms: object, owner: object) -> bool:
            if owner:
                return True
            try:
                value = int(perms) if perms is not None else 0
            except (TypeError, ValueError):
                value = 0
            # ADMINISTRATOR (0x8) or MANAGE_GUILD (0x20)
            return bool(value & (0x8 | 0x20))

        admin_guilds = [
            g
            for g in user_guilds
            if _has_admin_or_manage(g.get("permissions"), g.get("owner"))
        ]

        # Persist guilds and user↔guild mappings for authorization
        user_id = str(discord_user.get("id", ""))
        admin_guild_ids: list[int] = []

        for g in admin_guilds:
            gid = g.get("id")
            name = g.get("name") or ""
            if not gid:
                continue
            try:
                gid_int = int(gid)
            except (TypeError, ValueError):
                continue

            await upsert_guild(session, gid_int, name=name)
            admin_guild_ids.append(gid_int)

            icon_hash = g.get("icon")
            if icon_hash:
                icon_url = (
                    f"https://cdn.discordapp.com/icons/{gid_int}/{icon_hash}.png"
                )
                await redis.set(f"guild:{gid_int}:icon_url", icon_url)

        if user_id and admin_guild_ids:
            await upsert_user_guilds(session, user_id, admin_guild_ids, role="admin")

        await session.commit()
        logger.info(
            "auth_discord_sync_guilds_json",
            guild_count=len(admin_guild_ids),
            user_id=user_id,
        )
    except Exception as exc:  # pragma: no cover - non-critical
        logger.warning("auth_discord_sync_guilds_failed", error=str(exc))

    app_token = issue_app_token(discord_user)
    logger.info("auth_discord_success_json", discord_user_id=discord_user.get("id"))
    return JSONResponse(
        {
            "token": app_token,
            "redirect": "https://cyron-assistant.vercel.app/",
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
