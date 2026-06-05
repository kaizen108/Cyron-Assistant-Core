"""Reset service - daily and monthly resets."""

from datetime import datetime
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from backend.models.guild import Guild
from backend.services.limit_service import (
    _redis_key_daily_tickets,
    _redis_key_monthly_tokens,
)


async def run_daily_reset(session: AsyncSession, redis: Redis) -> None:
    """Reset daily counts for all guilds at midnight UTC."""
    now = datetime.utcnow()
    result = await session.execute(select(Guild))
    guilds = result.scalars().all()
    for guild in guilds:
        await session.execute(
            update(Guild)
            .where(Guild.id == guild.id)
            .values(daily_ticket_count=0, last_daily_reset=now)
        )
        # Reset Redis daily counter for today (will be overwritten as 0)
        key = _redis_key_daily_tickets(guild.id)
        await redis.set(key, 0)
        await redis.expire(key, 86400 * 2)  # 2 days TTL
    await session.commit()


async def run_monthly_reset(session: AsyncSession, redis: Redis) -> None:
    """Reset monthly token counts for all guilds."""
    now = datetime.utcnow()
    result = await session.execute(select(Guild))
    guilds = result.scalars().all()
    for guild in guilds:
        await session.execute(
            update(Guild)
            .where(Guild.id == guild.id)
            .values(monthly_tokens_used=0, last_monthly_reset=now)
        )
        key = _redis_key_monthly_tokens(guild.id)
        await redis.set(key, 0)
        await redis.expire(key, 86400 * 32)  # 32 days TTL
    await session.commit()
