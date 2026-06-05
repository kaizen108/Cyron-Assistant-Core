"""Guild ORM model."""

from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from backend.db.base import Base


class Guild(Base):
    """Guild (Discord server) model."""

    __tablename__ = "guilds"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    plan: Mapped[str] = mapped_column(String(50), nullable=False, default="free")
    monthly_tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    daily_ticket_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    concurrent_ai_sessions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_daily_reset: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_monthly_reset: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    embed_color: Mapped[str | None] = mapped_column(
        String(7), nullable=True, default="#00b4ff"
    )
    ticket_counter: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    close_embed_title: Mapped[str | None] = mapped_column(String(256), nullable=True, default="Ticket Closed")
    close_embed_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    close_embed_footer: Mapped[str | None] = mapped_column(String(256), nullable=True)
    dm_user_on_close: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_transcript_button: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    default_close_reason: Mapped[str | None] = mapped_column(String(200), nullable=True, default="No further action required.")
    require_reason_to_close: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confirm_close_check: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    rating_system_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rating_log_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    close_on_user_leave: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
