"""Message service - store and retrieve conversation history."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.message import Message


async def add_message(
    session: AsyncSession,
    ticket_id: uuid.UUID,
    role: str,
    content: str,
) -> Message:
    """Add message to ticket."""
    msg = Message(ticket_id=ticket_id, role=role, content=content)
    session.add(msg)
    await session.flush()
    return msg


async def get_last_messages(
    session: AsyncSession,
    ticket_id: uuid.UUID,
    limit: int = 8,
) -> list[Message]:
    """Get last N messages for ticket."""
    result = await session.execute(
        select(Message)
        .where(Message.ticket_id == ticket_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    return list(reversed(list(result.scalars().all())))
