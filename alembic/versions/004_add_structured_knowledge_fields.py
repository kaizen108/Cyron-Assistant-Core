"""Add structured knowledge fields.

Revision ID: 004
Revises: 003
Create Date: 2026-04-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("knowledge", sa.Column("main_content", sa.Text(), nullable=True))
    op.add_column("knowledge", sa.Column("additional_context", sa.Text(), nullable=True))
    op.add_column("knowledge", sa.Column("behavior_notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("knowledge", "behavior_notes")
    op.drop_column("knowledge", "additional_context")
    op.drop_column("knowledge", "main_content")
