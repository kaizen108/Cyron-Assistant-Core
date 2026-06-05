"""Usage logging service."""

from datetime import datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.usage_log import UsageLog
from backend.services.limit_service import _redis_key_monthly_tokens


async def log_usage(
    session: AsyncSession,
    redis: Redis,
    guild_id: int,
    tokens_used: int,
    request_type: str = "relay",
) -> None:
    """Persist usage log and synchronize monthly token counter."""
    log = UsageLog(
        guild_id=guild_id,
        tokens_used=tokens_used,
        request_type=request_type,
        timestamp=datetime.utcnow(),
    )
    session.add(log)
    await session.flush()

    # Phase 2 uses placeholder reply, so tokens_used may be 0.
    # We still keep Redis and DB in sync for Phase 3 readiness.
    key = _redis_key_monthly_tokens(guild_id)
    if tokens_used > 0:
        await redis.incrby(key, tokens_used)


async def get_usage_history(
    session: AsyncSession,
    guild_id: int,
    days: int = 7,
) -> list[dict[str, object]]:
    """Return per-day token usage for the last N days."""
    now = datetime.utcnow()
    since = now - timedelta(days=days)

    stmt = (
        select(
            func.date_trunc("day", UsageLog.timestamp).label("day"),
            func.coalesce(func.sum(UsageLog.tokens_used), 0).label("tokens"),
        )
        .where(
            UsageLog.guild_id == guild_id,
            UsageLog.timestamp >= since,
        )
        .group_by("day")
        .order_by("day")
    )
    result = await session.execute(stmt)
    rows = result.all()

    history: list[dict[str, object]] = []
    for day, tokens in rows:
        # day is a datetime; normalize to YYYY-MM-DD string
        history.append(
            {
                "date": day.date().isoformat(),
                "tokens_used": int(tokens or 0),
            }
        )
    return history


async def get_recent_usage_logs(
    session: AsyncSession,
    guild_id: int,
    limit: int = 10,
) -> list[dict[str, object]]:
    """Return recent usage logs for a guild."""
    stmt = (
        select(UsageLog)
        .where(UsageLog.guild_id == guild_id)
        .order_by(UsageLog.timestamp.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    logs = list(result.scalars().all())

    items: list[dict[str, object]] = []
    for log in logs:
        items.append(
            {
                "timestamp": log.timestamp.isoformat(),
                "tokens_used": int(log.tokens_used or 0),
                # low_confidence flag not stored yet; default False for now
                "low_confidence": False,
            }
        )
    return items
