"""TicketPanel ORM model."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class TicketPanel(Base):
    __tablename__ = "ticket_panels"

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="Default Panel")
    bot_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ticket_category_name: Mapped[str] = mapped_column(String(255), nullable=False, default="Tickets")
    button_text: Mapped[str] = mapped_column(String(80), nullable=False, default="Open Ticket")
    button_emoji: Mapped[str | None] = mapped_column(String(32), nullable=True)
    welcome_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_context_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("ai_contexts.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    # General
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    support_role_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    overflow_category_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    threading_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    save_transcripts: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    channel_name_format: Mapped[str] = mapped_column(String(100), nullable=False, default="{panel.name}-{ticket.number}")
    roles_required: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    roles_blocked: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    limit_bypass_roles: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    max_open_tickets_per_user: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    creation_cooldown_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    users_can_close: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    claiming_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    claiming_visibility: Mapped[str] = mapped_column(String(50), nullable=False, default="view_only")
    footer_text: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Embed
    panel_embed_author: Mapped[str | None] = mapped_column(String(256), nullable=True)
    panel_embed_title: Mapped[str | None] = mapped_column(String(256), nullable=True, default="Create a ticket")
    panel_embed_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    panel_embed_footer: Mapped[str | None] = mapped_column(String(256), nullable=True)
    panel_embed_color: Mapped[str | None] = mapped_column(String(10), nullable=True, default="#5865F2")
    button_type: Mapped[str] = mapped_column(String(20), nullable=False, default="button")
    button_color: Mapped[str] = mapped_column(String(20), nullable=False, default="blurple")

    # Messages
    welcome_ping_ticket_creator: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    welcome_ping_support_roles: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    welcome_ping_admin_role: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    welcome_embed_author: Mapped[str | None] = mapped_column(String(256), nullable=True)
    welcome_embed_title: Mapped[str | None] = mapped_column(String(256), nullable=True, default="Ticket Created")
    welcome_embed_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    welcome_embed_footer: Mapped[str | None] = mapped_column(String(256), nullable=True)
    auto_pin_welcome: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    close_button_emoji: Mapped[str | None] = mapped_column(String(32), nullable=True, default="🔒")
    close_button_label: Mapped[str | None] = mapped_column(String(80), nullable=True, default="Close")
    close_button_color: Mapped[str] = mapped_column(String(20), nullable=False, default="red")
    claim_button_emoji: Mapped[str | None] = mapped_column(String(32), nullable=True, default="👤")
    claim_button_label: Mapped[str | None] = mapped_column(String(80), nullable=True, default="Claim")
    unclaim_button_label: Mapped[str | None] = mapped_column(String(80), nullable=True, default="Unclaim")
    claim_button_color: Mapped[str] = mapped_column(String(20), nullable=False, default="blurple")

    # Forms
    forms_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    form_questions: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # Availability
    support_hours_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    support_hours_timezone: Mapped[str] = mapped_column(String(50), nullable=False, default="UTC")
    support_hours_schedule: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    closed_state_logic: Mapped[str] = mapped_column(String(30), nullable=False, default="allow_with_warning")
    msg_reduced_support: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    msg_emergency_only: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    msg_closed: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Logging
    log_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    send_logs_in_ticket: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Advanced
    sync_category_permissions: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    autoclose_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    autoclose_warning_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # AI
    ai_auto_reply: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Publish location
    published_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    published_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
