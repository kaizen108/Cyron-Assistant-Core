"""AIContext ORM model."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class AIContext(Base):
    __tablename__ = "ai_contexts"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="Default Context")
    context_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    general_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
