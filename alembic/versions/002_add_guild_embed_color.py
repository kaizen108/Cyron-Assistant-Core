"""Add embed_color to guilds for premium ticket UI.

Revision ID: 002
Revises: 001
Create Date: 2026-02-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "guilds",
        sa.Column(
            "embed_color",
            sa.String(7),
            nullable=True,
            server_default=sa.text("'#00b4ff'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("guilds", "embed_color")
