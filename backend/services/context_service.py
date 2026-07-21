"""Context service — AIContext CRUD, version bumping, cache key helpers."""

from __future__ import annotations

import hashlib
import uuid

import structlog
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.ai_context import AIContext
from backend.models.guild import Guild

logger = structlog.get_logger(__name__)

CACHE_TTL_SEC = 604_800  # 7 days

GENERAL_RULES_DEFAULT_INSTRUCTIONS = (
    "# General Rules\n\n"
    "These rules apply to ALL AI-enabled panels on this server.\n\n"
    "## Tone & Style\n"
    "- Be friendly, professional, and concise (2-4 sentences)\n"
    "- Always reply in the user's language\n"
    "- Never use robotic phrases like \"I am an AI assistant\"\n\n"
    "## Safety Rules\n"
    "- Never promise refunds, discounts, or compensation without explicit approval\n"
    "- Never share internal staff information or private data\n"
    "- Never make legal, medical, or financial claims\n\n"
    "## Escalation\n"
    "- If the user is frustrated or angry, acknowledge their feelings and offer human help\n"
    "- If the question requires account-specific actions (password resets, billing changes), escalate\n"
    "- If you're unsure about the answer, say so honestly and offer to connect with staff"
)

GENERAL_RULES_DEFAULT_GENERAL_INFO = (
    "## Company / Server Info\n"
    "Company: Your Company Name\n"
    "Support hours: Mon–Fri 9am–6pm UTC\n"
    "Website: https://example.com\n"
    "Contact: support@example.com\n\n"
    "## Common Situations\n"
    "- Order status: ask for order number before looking up\n"
    "- Refunds: never promise — escalate to staff\n"
    "- Account issues: verify identity before sharing account-specific info"
)


# ---------------------------------------------------------------------------
# Cache key
# ---------------------------------------------------------------------------

def panel_cache_key(panel_id: uuid.UUID, context_version: int, lang: str, text: str) -> str:
    """Versioned cache key — exact normalized query text prevents amount collisions."""
    norm = " ".join((text or "").strip().lower().split())
    digest = hashlib.sha256(norm.encode()).hexdigest()[:24]
    return f"panel:{panel_id}:ctx:{context_version}:{lang}:{digest}"


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


async def get_context_by_id(session: AsyncSession, context_id: uuid.UUID) -> AIContext | None:
    """Get context by ID only (no guild filter). Used for General Rules lookup."""
    result = await session.execute(
        select(AIContext).where(AIContext.id == context_id)
    )
    return result.scalar_one_or_none()


async def list_contexts(
    session: AsyncSession,
    guild_id: int,
    *,
    exclude_general_rules: bool = False,
) -> list[AIContext]:
    result = await session.execute(
        select(AIContext).where(AIContext.guild_id == guild_id).order_by(AIContext.created_at)
    )
    contexts = list(result.scalars().all())
    if not exclude_general_rules:
        return contexts

    guild_result = await session.execute(select(Guild).where(Guild.id == guild_id))
    guild = guild_result.scalar_one_or_none()
    if not guild or not guild.general_ai_context_id:
        return contexts
    return [ctx for ctx in contexts if ctx.id != guild.general_ai_context_id]


async def ensure_general_rules_context(session: AsyncSession, guild: Guild) -> AIContext:
    """Lazily create the General Rules context for a guild."""
    if guild.general_ai_context_id:
        result = await session.execute(
            select(AIContext).where(AIContext.id == guild.general_ai_context_id)
        )
        ctx = result.scalar_one_or_none()
        if ctx:
            return ctx

    ctx = AIContext(
        guild_id=guild.id,
        name="General Rules",
        context_version=1,
        instructions=GENERAL_RULES_DEFAULT_INSTRUCTIONS,
        general_info=GENERAL_RULES_DEFAULT_GENERAL_INFO,
    )
    session.add(ctx)
    await session.flush()
    guild.general_ai_context_id = ctx.id
    await session.flush()
    logger.info("general_rules_context_created", guild_id=guild.id, context_id=str(ctx.id))
    return ctx


async def is_general_rules_context(
    session: AsyncSession, guild_id: int, context_id: uuid.UUID
) -> bool:
    result = await session.execute(select(Guild).where(Guild.id == guild_id))
    guild = result.scalar_one_or_none()
    return bool(guild and guild.general_ai_context_id == context_id)


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
    ctx.context_version += 1
    await session.flush()
    return ctx


async def delete_context(session: AsyncSession, context_id: uuid.UUID, guild_id: int) -> bool:
    if await is_general_rules_context(session, guild_id, context_id):
        return False
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
