"""Initial schema - Guild, Knowledge, Ticket, UsageLog, Message

Revision ID: 001
Revises:
Create Date: 2025-02-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "guilds",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False, server_default=""),
        sa.Column("plan", sa.String(50), nullable=False, server_default="free"),
        sa.Column("monthly_tokens_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("daily_ticket_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("concurrent_ai_sessions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_daily_reset", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_monthly_reset", sa.DateTime(timezone=True), nullable=True),
        sa.Column("system_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "tickets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("guild_id", "channel_id", name="uq_ticket_guild_channel"),
    )

    op.create_table(
        "knowledge",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", postgresql.ARRAY(sa.Float()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "usage_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("request_type", sa.String(50), nullable=False, server_default="relay"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("messages")
    op.drop_table("usage_logs")
    op.drop_table("knowledge")
    op.drop_table("tickets")
    op.drop_table("guilds")
