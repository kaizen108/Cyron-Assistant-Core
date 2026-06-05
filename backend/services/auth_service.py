"""Discord OAuth and app-token helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import HTTPException, status

from backend.config import config


DISCORD_OAUTH_AUTHORIZE_URL = "https://discord.com/api/oauth2/authorize"
DISCORD_OAUTH_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_API_ME_URL = "https://discord.com/api/users/@me"
DISCORD_API_USER_GUILDS_URL = "https://discord.com/api/users/@me/guilds"


def _require_oauth_config() -> tuple[str, str]:
    if not config.discord_client_id or not config.discord_client_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Discord OAuth is not configured on the backend.",
        )
    return config.discord_client_id, config.discord_client_secret


def create_state_token(redirect_uri: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "redirect_uri": redirect_uri,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=10)).timestamp()),
        "type": "oauth_state",
    }
    return jwt.encode(
        payload,
        config.auth_jwt_secret,
        algorithm=config.auth_jwt_algorithm,
    )


def parse_state_token(state_token: str) -> str:
    try:
        payload = jwt.decode(
            state_token,
            config.auth_jwt_secret,
            algorithms=[config.auth_jwt_algorithm],
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OAuth state.",
        ) from exc

    redirect_uri = payload.get("redirect_uri")
    if not isinstance(redirect_uri, str) or not redirect_uri:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OAuth redirect URI.",
        )
    return redirect_uri


def build_discord_authorize_url(redirect_uri: str, callback_url: str) -> str:
    client_id, _ = _require_oauth_config()
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": callback_url,
        "scope": config.discord_oauth_scope,
        "state": create_state_token(redirect_uri),
        "prompt": "consent",
    }
    return f"{DISCORD_OAUTH_AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code_for_access_token(code: str, callback_url: str) -> str:
    _, client_secret = _require_oauth_config()
    client_id = config.discord_client_id  # already validated
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": callback_url,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(DISCORD_OAUTH_TOKEN_URL, data=payload, headers=headers)

    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to exchange Discord OAuth code.",
        )

    data = resp.json()
    access_token = data.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Discord did not return an access token.",
        )
    return access_token


async def fetch_discord_user(access_token: str) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(DISCORD_API_ME_URL, headers=headers)

    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch Discord user profile.",
        )
    data = resp.json()
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Invalid Discord user response.",
        )
    return data


async def fetch_user_guilds(access_token: str) -> list[dict[str, Any]]:
    """Fetch guilds for the OAuth user (used to seed dashboard guild list).

    This uses the user access token, not the bot token. We keep it best-effort:
    failures are logged but do not break login.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(DISCORD_API_USER_GUILDS_URL, headers=headers)

    if resp.status_code != 200:
        # Best-effort: just return empty; caller may log.
        return []
    data = resp.json()
    if not isinstance(data, list):
        return []
    return [g for g in data if isinstance(g, dict)]


def _avatar_url(discord_user: dict[str, Any]) -> str | None:
    user_id = discord_user.get("id")
    avatar = discord_user.get("avatar")
    if not user_id or not avatar:
        return None
    return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.png"


def issue_app_token(discord_user: dict[str, Any]) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(discord_user.get("id", "")),
        "username": str(discord_user.get("username", "Discord User")),
        "avatar_url": _avatar_url(discord_user),
        "iat": int(now.timestamp()),
        "exp": int(
            (now + timedelta(minutes=config.auth_jwt_exp_minutes)).timestamp()
        ),
        "type": "access",
    }
    return jwt.encode(
        payload,
        config.auth_jwt_secret,
        algorithm=config.auth_jwt_algorithm,
    )


def decode_app_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            config.auth_jwt_secret,
            algorithms=[config.auth_jwt_algorithm],
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        ) from exc

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type.",
        )
    return payload
