"""Add ai_contexts table

Revision ID: 008
Revises: 007
Create Date: 2026-05-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_contexts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("guild_id", sa.BigInteger(), sa.ForeignKey("guilds.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False, server_default="Default Context"),
        sa.Column("context_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("general_info", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ai_contexts_guild_id", "ai_contexts", ["guild_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_contexts_guild_id", "ai_contexts")
    op.drop_table("ai_contexts")
