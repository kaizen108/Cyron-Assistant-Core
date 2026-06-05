"""Services for managing user ↔ guild authorization mappings."""

from __future__ import annotations

from typing import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.user_guild import UserGuild


async def upsert_user_guilds(
    session: AsyncSession,
    user_id: str,
    guild_ids: Iterable[int],
    role: str = "admin",
) -> None:
    """Ensure UserGuild rows exist for the given user and guild IDs.

    Called during OAuth login when we fetch the user's admin/mod guilds.
    """
    gids: list[int] = list({int(gid) for gid in guild_ids})
    if not gids:
        return

    result = await session.execute(
        select(UserGuild).where(
            UserGuild.user_id == user_id, UserGuild.guild_id.in_(gids)
        )
    )
    existing: dict[int, UserGuild] = {
        row.guild_id: row for row in result.scalars().all()
    }

    for gid in gids:
        if gid in existing:
            # Update role if it changed
            if existing[gid].role != role:
                existing[gid].role = role
        else:
            session.add(
                UserGuild(
                    user_id=user_id,
                    guild_id=gid,
                    role=role,
                )
            )


async def user_has_guild(
    session: AsyncSession,
    user_id: str,
    guild_id: int,
) -> bool:
    """Return True if the user is authorized to manage the given guild."""
    result = await session.execute(
        select(UserGuild).where(
            UserGuild.user_id == user_id, UserGuild.guild_id == guild_id
        )
    )
    return result.scalar_one_or_none() is not None


async def list_user_guild_ids(
    session: AsyncSession,
    user_id: str,
) -> Sequence[int]:
    """List all guild IDs the user is allowed to manage."""
    result = await session.execute(
        select(UserGuild.guild_id).where(UserGuild.user_id == user_id)
    )
    return [int(row[0]) for row in result.all()]

