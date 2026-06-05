"""UsageLog ORM model."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class UsageLog(Base):
    """Usage log for token tracking."""

    __tablename__ = "usage_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    guild_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("guilds.id"), nullable=False
    )
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    request_type: Mapped[str] = mapped_column(String(50), nullable=False, default="relay")
