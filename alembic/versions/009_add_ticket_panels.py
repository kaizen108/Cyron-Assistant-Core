"""Add ticket_panels table and panel_id to tickets

Revision ID: 009
Revises: 008
Create Date: 2026-05-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ticket_panels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("guild_id", sa.BigInteger(), sa.ForeignKey("guilds.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False, server_default="Default Panel"),
        sa.Column("bot_id", sa.BigInteger(), nullable=True),
        sa.Column("ticket_category_name", sa.String(255), nullable=False, server_default="Tickets"),
        sa.Column("button_text", sa.String(80), nullable=False, server_default="Open Ticket"),
        sa.Column("button_emoji", sa.String(32), nullable=True),
        sa.Column("welcome_message", sa.Text(), nullable=True),
        sa.Column("ai_context_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ai_contexts.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ticket_panels_guild_id", "ticket_panels", ["guild_id"])

    op.add_column("tickets", sa.Column("panel_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ticket_panels.id"), nullable=True))


def downgrade() -> None:
    op.drop_column("tickets", "panel_id")
    op.drop_index("ix_ticket_panels_guild_id", "ticket_panels")
    op.drop_table("ticket_panels")
