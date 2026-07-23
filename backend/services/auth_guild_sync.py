"""Background guild sync after OAuth login (keeps callback response fast)."""

from __future__ import annotations

import structlog
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import async_session_factory
from backend.services.auth_service import fetch_user_guilds
from backend.services.guild_service import upsert_guild
from backend.services.user_guild_service import upsert_user_guilds

logger = structlog.get_logger(__name__)


def _has_admin_or_manage(perms: object, owner: object) -> bool:
    if owner:
        return True
    try:
        value = int(perms) if perms is not None else 0
    except (TypeError, ValueError):
        value = 0
    return bool(value & (0x8 | 0x20))


async def sync_user_guilds_from_discord(
    session: AsyncSession,
    redis: Redis,
    access_token: str,
    user_id: str,
) -> int:
    """Fetch Discord guilds and upsert admin guild mappings. Returns count synced."""
    user_guilds = await fetch_user_guilds(access_token)
    admin_guilds = [
        g
        for g in user_guilds
        if _has_admin_or_manage(g.get("permissions"), g.get("owner"))
    ]

    admin_guild_ids: list[int] = []
    for g in admin_guilds:
        gid = g.get("id")
        name = g.get("name") or ""
        if not gid:
            continue
        try:
            gid_int = int(gid)
        except (TypeError, ValueError):
            continue

        await upsert_guild(session, gid_int, name=name)
        admin_guild_ids.append(gid_int)

        icon_hash = g.get("icon")
        if icon_hash:
            icon_url = f"https://cdn.discordapp.com/icons/{gid_int}/{icon_hash}.png"
            await redis.set(f"guild:{gid_int}:icon_url", icon_url)

    if user_id and admin_guild_ids:
        await upsert_user_guilds(session, user_id, admin_guild_ids, role="admin")

    await session.commit()
    return len(admin_guild_ids)


async def sync_user_guilds_background(
    access_token: str,
    user_id: str,
    redis: Redis,
) -> None:
    """Run guild sync in a background task so OAuth callback returns immediately."""
    if not user_id:
        return
    try:
        async with async_session_factory() as session:
            count = await sync_user_guilds_from_discord(
                session, redis, access_token, user_id
            )
        logger.info(
            "auth_discord_sync_guilds_background",
            guild_count=count,
            user_id=user_id,
        )
    except Exception as exc:
        logger.warning(
            "auth_discord_sync_guilds_background_failed",
            user_id=user_id,
            error=str(exc),
        )
