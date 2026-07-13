"""Ticket service - get or create ticket."""

import uuid
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.ticket import Ticket


async def get_ticket(
    session: AsyncSession,
    guild_id: int,
    channel_id: int,
    bot_id: int | None = None,
) -> Ticket | None:
    """Get existing open ticket by guild and channel.

    When bot_id is provided, match tickets owned by that bot OR tickets with no
    bot_id yet (legacy rows registered before bot isolation was enforced).
    """
    stmt = select(Ticket).where(
        Ticket.guild_id == guild_id,
        Ticket.channel_id == channel_id,
        Ticket.status == "open",
    )
    if bot_id is not None:
        stmt = stmt.where(or_(Ticket.bot_id == bot_id, Ticket.bot_id.is_(None)))
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_or_create_ticket(
    session: AsyncSession,
    guild_id: int,
    channel_id: int,
    bot_id: int | None = None,
    panel_id=None,
) -> tuple[Ticket, bool]:
    ticket = await get_ticket(session, guild_id, channel_id, bot_id=bot_id)
    if ticket:
        return ticket, False

    ticket = Ticket(
        guild_id=guild_id,
        channel_id=channel_id,
        bot_id=bot_id,
        panel_id=panel_id,
        status="open",
    )
    session.add(ticket)
    await session.flush()
    return ticket, True


async def get_ticket_by_channel(
    session: AsyncSession,
    guild_id: int,
    channel_id: int,
) -> Ticket | None:
    """Get ticket by guild and channel (any bot)."""
    result = await session.execute(
        select(Ticket).where(
            Ticket.guild_id == guild_id,
            Ticket.channel_id == channel_id,
        )
    )
    return result.scalar_one_or_none()
