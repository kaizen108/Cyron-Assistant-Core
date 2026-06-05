"""Add bot_id to tickets for bot isolation

Revision ID: 007
Revises: 006
Create Date: 2026-04-21
"""
from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tickets", sa.Column("bot_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("tickets", "bot_id")
