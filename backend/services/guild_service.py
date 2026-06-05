"""Guild service - upsert and retrieve guilds."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.guild import Guild
from backend.schemas.plans import DEFAULT_SYSTEM_PROMPT


async def upsert_guild(
    session: AsyncSession,
    guild_id: int,
    name: str = "",
) -> Guild:
    """Create or update guild. Returns the guild."""
    result = await session.execute(select(Guild).where(Guild.id == guild_id))
    guild = result.scalar_one_or_none()

    if guild is None:
        guild = Guild(
            id=guild_id,
            name=name,
            plan="free",
            system_prompt=DEFAULT_SYSTEM_PROMPT,
            embed_color="#00b4ff",
        )
        session.add(guild)
        await session.flush()
    else:
        # If we receive a non-empty name and the stored name is blank/placeholder,
        # update it so the dashboard can display this guild correctly.
        cleaned = (name or "").strip()
        if cleaned and not (guild.name or "").strip():
            guild.name = cleaned
            await session.flush()
    return guild


async def get_guild(session: AsyncSession, guild_id: int) -> Guild | None:
    """Get guild by ID."""
    result = await session.execute(select(Guild).where(Guild.id == guild_id))
    return result.scalar_one_or_none()


async def list_guilds(session: AsyncSession) -> list[Guild]:
    """Return all guilds known to the system."""
    result = await session.execute(select(Guild))
    return list(result.scalars().all())
