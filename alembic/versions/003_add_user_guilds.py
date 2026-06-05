"""Add user_guilds mapping table for authorization.

Revision ID: 003
Revises: 002
Create Date: 2026-03-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_guilds",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="admin"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("user_id", "guild_id"),
    )


def downgrade() -> None:
    op.drop_table("user_guilds")

