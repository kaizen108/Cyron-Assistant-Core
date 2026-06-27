"""Ticket ORM model."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id"), nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    bot_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    panel_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("ticket_panels.id"), nullable=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="open")
    ticket_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channel_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    claimed_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    priority: Mapped[str | None] = mapped_column(String(20), nullable=True)
    form_answers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rating_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    human_handoff: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("guild_id", "channel_id", name="uq_ticket_guild_channel"),
    )
