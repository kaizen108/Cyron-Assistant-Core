"""Add ai_auto_reply to ticket_panels and human_handoff to tickets

Revision ID: 011
Revises: 6f71936925f8
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa

revision = "011"
down_revision = "6f71936925f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Phase 2: AI auto-reply toggle per panel
    op.add_column("ticket_panels", sa.Column("ai_auto_reply", sa.Boolean(), nullable=False, server_default="false"))

    # Phase 2: Human handoff flag per ticket
    op.add_column("tickets", sa.Column("human_handoff", sa.Boolean(), nullable=False, server_default="false"))


def downgrade() -> None:
    op.drop_column("tickets", "human_handoff")
    op.drop_column("ticket_panels", "ai_auto_reply")
