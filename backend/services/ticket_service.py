"""Ticket service - get or create ticket."""

import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.ticket import Ticket


async def get_ticket(
    session: AsyncSession,
    guild_id: int,
    channel_id: int,
    bot_id: int | None = None,
) -> Ticket | None:
    """Get existing open ticket by guild and channel.

    When bot_id is provided, returns tickets owned by that bot or with no bot_id yet
    (legacy rows). Strict ownership is enforced separately before relay.
    """
    stmt = select(Ticket).where(
        Ticket.guild_id == guild_id,
        Ticket.channel_id == channel_id,
        Ticket.status == "open",
    )
    if bot_id is not None:
        stmt = stmt.where((Ticket.bot_id == bot_id) | (Ticket.bot_id.is_(None)))
    result = await session.execute(stmt)
    ticket = result.scalar_one_or_none()
    if ticket and bot_id is not None and ticket.bot_id is None:
        ticket.bot_id = bot_id
        await session.flush()
    return ticket


async def get_or_create_ticket(
    session: AsyncSession,
    guild_id: int,
    channel_id: int,
    bot_id: int | None = None,
    panel_id=None,
) -> tuple[Ticket, bool]:
    existing = await get_ticket_by_channel(session, guild_id, channel_id)
    if existing:
        if existing.status != "open":
            return existing, False
        if bot_id is not None and existing.bot_id is not None and existing.bot_id != bot_id:
            return existing, False
        if bot_id is not None and existing.bot_id is None:
            existing.bot_id = bot_id
        if panel_id and not existing.panel_id:
            existing.panel_id = panel_id
        await session.flush()
        return existing, False

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
