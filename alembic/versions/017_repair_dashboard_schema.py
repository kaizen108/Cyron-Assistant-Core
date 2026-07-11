"""Repair schema drift for dashboard guild listing.

Revision ID: 017
Revises: 016
Create Date: 2026-07-12

Ensures tables/columns required by GET /guilds exist even when earlier
migrations were skipped or user_guilds was accidentally dropped.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "017"
down_revision: Union[str, None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "user_guilds" not in tables:
        op.create_table(
            "user_guilds",
            sa.Column("user_id", sa.String(length=32), nullable=False),
            sa.Column("guild_id", sa.BigInteger(), nullable=False),
            sa.Column(
                "role",
                sa.String(length=32),
                nullable=False,
                server_default="admin",
            ),
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

    if "guilds" in tables:
        guild_columns = {col["name"] for col in inspector.get_columns("guilds")}

        if "general_ai_context_id" not in guild_columns:
            op.add_column(
                "guilds",
                sa.Column("general_ai_context_id", sa.UUID(), nullable=True),
            )
            if "ai_contexts" in tables:
                op.create_foreign_key(
                    "fk_guilds_general_ai_context_id",
                    "guilds",
                    "ai_contexts",
                    ["general_ai_context_id"],
                    ["id"],
                )

        if "general_ai_enabled" not in guild_columns:
            op.add_column(
                "guilds",
                sa.Column(
                    "general_ai_enabled",
                    sa.Boolean(),
                    nullable=False,
                    server_default="true",
                ),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "guilds" in inspector.get_table_names():
        guild_columns = {col["name"] for col in inspector.get_columns("guilds")}
        if "general_ai_enabled" in guild_columns:
            op.drop_column("guilds", "general_ai_enabled")
        if "general_ai_context_id" in guild_columns:
            op.drop_constraint(
                "fk_guilds_general_ai_context_id", "guilds", type_="foreignkey"
            )
            op.drop_column("guilds", "general_ai_context_id")

    if "user_guilds" in inspector.get_table_names():
        op.drop_table("user_guilds")
