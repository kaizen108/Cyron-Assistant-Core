"""FastAPI dependencies for Redis, auth, and authorization."""

from typing import Annotated
import secrets

from fastapi import Depends, Header, HTTPException, Request, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import get_session
from backend.services.auth_service import decode_app_token
from backend.services.user_guild_service import user_has_guild
from backend.config import config


def get_redis(request: Request) -> Redis:
    """Get Redis client from app state."""
    return request.app.state.redis


async def get_current_user_id(
    authorization: str | None = Header(default=None),
) -> str:
    """Extract and validate app token, returning the Discord user ID."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
        )
    token = authorization.split(" ", 1)[1].strip()
    payload = decode_app_token(token)
    user_id = str(payload.get("sub", "")).strip()
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload.",
        )
    return user_id


async def require_guild_admin(
    guild_id: int,
    user_id: Annotated[str, Depends(get_current_user_id)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> int:
    """Authorize that the current user may manage the given guild.

    This is enforced server-side on all guild-scoped dashboard endpoints.
    """
    allowed = await user_has_guild(session, user_id=user_id, guild_id=guild_id)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to manage this guild.",
        )
    return guild_id


async def require_bot_api_key(
    x_bot_api_key: str | None = Header(default=None, alias="X-Bot-Api-Key"),
) -> None:
    """Require valid bot credential for bot-only endpoints."""
    expected = (config.bot_api_key or "").strip()
    provided = (x_bot_api_key or "").strip()

    if not expected:
        # Fail-closed to avoid accidental public exposure.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="BOT_API_KEY is not configured on server.",
        )

    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bot credentials.",
        )

