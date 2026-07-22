"""Discord OAuth endpoints for dashboard authentication."""

from __future__ import annotations

import hashlib
import json
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, status
from fastapi.responses import RedirectResponse, JSONResponse
from redis.asyncio import Redis

from backend.config import config
from backend.db.session import async_session_factory
from backend.dependencies import get_redis
from backend.services.auth_service import (
    build_discord_authorize_url,
    decode_app_token,
    exchange_code_for_access_token,
    fetch_discord_user,
    fetch_user_guilds,
    issue_app_token,
    parse_state_token,
)
from backend.services.guild_service import upsert_guild
from backend.services.user_guild_service import upsert_user_guilds

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

_OAUTH_CODE_CACHE_TTL_SEC = 300


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


def _oauth_code_cache_key(code: str, redirect_uri: str) -> str:
    digest = hashlib.sha256(f"{code}:{redirect_uri}".encode()).hexdigest()[:32]
    return f"oauth:code:{digest}"


def _has_admin_or_manage(perms: object, owner: object) -> bool:
    if owner:
        return True
    try:
        value = int(perms) if perms is not None else 0
    except (TypeError, ValueError):
        value = 0
    return bool(value & (0x8 | 0x20))


async def _sync_user_guilds_background(
    access_token: str,
    user_id: str,
    redis: Redis,
) -> None:
    """Best-effort guild sync after login — runs in background so OAuth responds fast."""
    if not user_id:
        return
    try:
        user_guilds = await fetch_user_guilds(access_token)
        admin_guilds = [
            g
            for g in user_guilds
            if _has_admin_or_manage(g.get("permissions"), g.get("owner"))
        ]
        admin_guild_ids: list[int] = []

        async with async_session_factory() as session:
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
                    icon_url = f"https://cdn.discordapp.com/icons/{gid_int}/{icon_hash}.png"
                    await redis.set(f"guild:{gid_int}:icon_url", icon_url)

            if admin_guild_ids:
                await upsert_user_guilds(session, user_id, admin_guild_ids, role="admin")

            await session.commit()

        logger.info(
            "auth_discord_sync_guilds_background",
            guild_count=len(admin_guild_ids),
            user_id=user_id,
        )
    except Exception as exc:
        logger.warning("auth_discord_sync_guilds_failed", error=str(exc))


async def _complete_oauth_login(
    code: str,
    state: str,
    redis: Redis,
    background_tasks: BackgroundTasks,
) -> dict[str, str]:
    """Exchange code, issue token, cache response, queue guild sync."""
    redirect_uri = parse_state_token(state)
    if not _is_allowed_redirect_uri(redirect_uri):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="redirect_uri is not allowed.",
        )

    cache_key = _oauth_code_cache_key(code, redirect_uri)
    cached = await redis.get(cache_key)
    if cached:
        logger.info("auth_discord_code_cache_hit")
        return json.loads(cached)

    access_token = await exchange_code_for_access_token(code, redirect_uri)
    discord_user = await fetch_discord_user(access_token)
    user_id = str(discord_user.get("id", ""))

    app_token = issue_app_token(discord_user)
    response_data = {
        "token": app_token,
        "redirect": f"{config.frontend_public_url}/dashboard",
    }

    await redis.setex(cache_key, _OAUTH_CODE_CACHE_TTL_SEC, json.dumps(response_data))

    background_tasks.add_task(
        _sync_user_guilds_background,
        access_token,
        user_id,
        redis,
    )

    return response_data


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
    logger.info("auth_discord_start", redirect_uri=redirect_uri)
    return RedirectResponse(url=discord_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get("/callback")
async def discord_oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    redis: Redis = Depends(get_redis),
):
    """Legacy handler — redirect to frontend with token."""
    redirect_uri = parse_state_token(state)
    if not _is_allowed_redirect_uri(redirect_uri):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="redirect_uri is not allowed.",
        )

    response_data = await _complete_oauth_login(code, state, redis, background_tasks)
    final_url = _append_query_param(redirect_uri, "token", response_data["token"])
    logger.info("auth_discord_success_legacy")
    return RedirectResponse(url=final_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.post("/callback")
async def discord_oauth_callback_json(
    code: str = Query(...),
    state: str = Query(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    redis: Redis = Depends(get_redis),
):
    """Handle Discord callback for frontend — return token immediately, sync guilds in background."""
    response_data = await _complete_oauth_login(code, state, redis, background_tasks)
    logger.info("auth_discord_success_json")
    return JSONResponse(response_data)


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
