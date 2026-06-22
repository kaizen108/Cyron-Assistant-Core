"""Restore user_guilds table dropped by 6f71936925f8.

Revision ID: 011
Revises: 6f71936925f8
Create Date: 2026-06-20

Migration 6f71936925f8 accidentally dropped user_guilds without recreating it,
which breaks dashboard GET /guilds (authorization mapping table missing).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "011"
down_revision: Union[str, None] = "6f71936925f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "user_guilds" in inspector.get_table_names():
        return

    op.create_table(
        "user_guilds",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "role",
            sa.String(length=32),
            server_default="admin",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id", "guild_id"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "user_guilds" not in inspector.get_table_names():
        return
    op.drop_table("user_guilds")
