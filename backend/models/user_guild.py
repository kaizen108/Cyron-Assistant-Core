"""User ↔ Guild mapping for authorization."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class UserGuild(Base):
    """Mapping of a Discord user to a guild they can manage."""

    __tablename__ = "user_guilds"

    user_id: Mapped[str] = mapped_column(
        String(32), primary_key=True, nullable=False
    )  # Discord user ID as string
    guild_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, nullable=False
    )
    role: Mapped[str] = mapped_column(
        String(32), nullable=False, default="admin"
    )  # e.g. admin/mod in this guild
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

