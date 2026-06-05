"""Limit service - Redis atomic limit checks."""

from datetime import datetime
from redis.asyncio import Redis

from backend.schemas.plans import PLAN_LIMITS


def _get_limits(plan: str) -> dict:
    """Get plan limits, fallback to free."""
    return PLAN_LIMITS.get(plan.lower(), PLAN_LIMITS["free"])


def _redis_key_concurrent(guild_id: int) -> str:
    return f"guild:{guild_id}:concurrent"


def _redis_key_daily_tickets(guild_id: int) -> str:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    return f"guild:{guild_id}:daily_tickets:{today}"


def _redis_key_monthly_tokens(guild_id: int) -> str:
    return f"guild:{guild_id}:monthly_tokens"


async def check_and_incr_concurrent(
    redis: Redis, guild_id: int, plan: str
) -> tuple[bool, str, int]:
    """
    Check concurrent limit and increment if OK.
    Returns (allowed, rejection_message, current_concurrent).
    """
    limits = _get_limits(plan)
    key = _redis_key_concurrent(guild_id)
    current = await redis.incr(key)
    if current > limits["concurrent_tickets"]:
        await redis.decr(key)
        return (
            False,
            "Concurrent AI ticket limit reached for "
            f"{plan.capitalize()} plan. Please wait for existing tickets to complete.",
            limits["concurrent_tickets"],
        )
    return True, "", int(current)


async def decr_concurrent(redis: Redis, guild_id: int) -> None:
    """Decrement concurrent counter after request completes."""
    key = _redis_key_concurrent(guild_id)
    current = int(await redis.get(key) or 0)
    if current <= 0:
        await redis.set(key, 0)
        return
    await redis.decr(key)


async def check_daily_ticket_limit(
    redis: Redis, guild_id: int, plan: str, is_new_ticket: bool
) -> tuple[bool, str]:
    """
    Check daily ticket limit. Only applies when creating NEW ticket.
    Returns (allowed, rejection_message).
    """
    if not is_new_ticket:
        return True, ""

    limits = _get_limits(plan)
    key = _redis_key_daily_tickets(guild_id)
    current = await redis.incr(key)
    if current > limits["daily_ticket_limit"]:
        await redis.decr(key)
        return False, f"Daily ticket limit reached ({limits['daily_ticket_limit']} per day). Please try again tomorrow."
    return True, ""


async def check_monthly_tokens(redis: Redis, guild_id: int, plan: str) -> tuple[bool, str]:
    """
    Check monthly token limit.
    Returns (allowed, rejection_message).
    """
    limits = _get_limits(plan)
    key = _redis_key_monthly_tokens(guild_id)
    current = int(await redis.get(key) or 0)
    if current >= limits["monthly_tokens"]:
        return False, "Monthly token limit exceeded. Please upgrade your plan."
    return True, ""


async def sync_monthly_tokens_from_db(redis: Redis, guild_id: int, value: int) -> None:
    """Sync monthly tokens from DB to Redis (called on reset)."""
    key = _redis_key_monthly_tokens(guild_id)
    await redis.set(key, value)


async def sync_daily_tickets_from_db(redis: Redis, guild_id: int, value: int) -> None:
    """Sync daily tickets for today from DB to Redis."""
    key = _redis_key_daily_tickets(guild_id)
    await redis.set(key, value)
