"""Context service — AIContext CRUD, version bumping, cache key helpers."""

from __future__ import annotations

import uuid

import structlog
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.ai_context import AIContext

logger = structlog.get_logger(__name__)

CACHE_TTL_SEC = 604_800  # 7 days


# ---------------------------------------------------------------------------
# Cache key
# ---------------------------------------------------------------------------

def panel_cache_key(panel_id: uuid.UUID, context_version: int, lang: str, text: str) -> str:
    """Versioned cache key from exact query text (no embedding fuzzy buckets)."""
    from backend.services.relay_cache import panel_exact_cache_key

    return panel_exact_cache_key(panel_id, context_version, lang, text)


async def cache_get(redis: Redis, key: str) -> str | None:
    return await redis.get(key)


async def cache_set(redis: Redis, key: str, value: str) -> None:
    await redis.setex(key, CACHE_TTL_SEC, value)


# ---------------------------------------------------------------------------
# AIContext CRUD
# ---------------------------------------------------------------------------

async def get_context(session: AsyncSession, context_id: uuid.UUID, guild_id: int) -> AIContext | None:
    result = await session.execute(
        select(AIContext).where(AIContext.id == context_id, AIContext.guild_id == guild_id)
    )
    return result.scalar_one_or_none()


async def list_contexts(session: AsyncSession, guild_id: int) -> list[AIContext]:
    result = await session.execute(
        select(AIContext).where(AIContext.guild_id == guild_id).order_by(AIContext.created_at)
    )
    return list(result.scalars().all())


async def create_context(
    session: AsyncSession,
    guild_id: int,
    name: str,
    instructions: str | None = None,
    general_info: str | None = None,
) -> AIContext:
    ctx = AIContext(
        guild_id=guild_id,
        name=name,
        instructions=instructions,
        general_info=general_info,
    )
    session.add(ctx)
    await session.flush()
    return ctx


async def update_context(
    session: AsyncSession,
    context_id: uuid.UUID,
    guild_id: int,
    *,
    name: str | None = None,
    instructions: str | None = None,
    general_info: str | None = None,
) -> AIContext | None:
    ctx = await get_context(session, context_id, guild_id)
    if not ctx:
        return None
    if name is not None:
        ctx.name = name
    if instructions is not None:
        ctx.instructions = instructions
    if general_info is not None:
        ctx.general_info = general_info
    await session.flush()
    return ctx


async def delete_context(session: AsyncSession, context_id: uuid.UUID, guild_id: int) -> bool:
    ctx = await get_context(session, context_id, guild_id)
    if not ctx:
        return False
    await session.delete(ctx)
    await session.flush()
    return True


async def bump_context_version(session: AsyncSession, context_id: uuid.UUID) -> int:
    """Increment context_version. Old cache keys become unreachable automatically."""
    result = await session.execute(
        select(AIContext).where(AIContext.id == context_id)
    )
    ctx = result.scalar_one_or_none()
    if not ctx:
        return 0
    ctx.context_version += 1
    await session.flush()
    logger.info("context_version_bumped", context_id=str(context_id), new_version=ctx.context_version)
    return ctx.context_version


async def get_context_by_panel(session: AsyncSession, panel_id: uuid.UUID) -> AIContext | None:
    """Load the AIContext linked to a panel in one join."""
    from backend.models.ticket_panel import TicketPanel
    result = await session.execute(
        select(AIContext)
        .join(TicketPanel, TicketPanel.ai_context_id == AIContext.id)
        .where(TicketPanel.id == panel_id)
    )
    return result.scalar_one_or_none()
