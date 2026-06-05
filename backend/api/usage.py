"""Usage API - GET /guilds/{guild_id}/usage."""

from fastapi import APIRouter, Depends, HTTPException
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from backend.dependencies import get_redis, require_guild_admin
from backend.db.session import get_session
from backend.schemas.plans import PLAN_LIMITS
from backend.schemas.usage import UsageResponse
from backend.services.guild_service import get_guild
from backend.services.limit_service import (
    _redis_key_concurrent,
    _redis_key_daily_tickets,
    _redis_key_monthly_tokens,
)

router = APIRouter(prefix="/guilds/{guild_id}/usage", tags=["usage"])


@router.get("", response_model=UsageResponse)
async def get_guild_usage(
    guild_id: int = Depends(require_guild_admin),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
):
    """Get guild usage statistics."""
    guild = await get_guild(session, guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    limits = PLAN_LIMITS.get(guild.plan.lower(), PLAN_LIMITS["free"])
    concurrent = int(await redis.get(_redis_key_concurrent(guild_id)) or 0)
    monthly = int(await redis.get(_redis_key_monthly_tokens(guild_id)) or 0)
    daily_key = _redis_key_daily_tickets(guild_id)
    daily = int(await redis.get(daily_key) or 0)

    return UsageResponse(
        guild_id=guild_id,
        plan=guild.plan,
        monthly_tokens_used=monthly,
        monthly_tokens_limit=limits["monthly_tokens"],
        daily_ticket_count=daily,
        daily_ticket_limit=limits["daily_ticket_limit"],
        concurrent_ai_sessions=concurrent,
        concurrent_limit=limits["concurrent_tickets"],
    )
