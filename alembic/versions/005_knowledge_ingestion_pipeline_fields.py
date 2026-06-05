"""Knowledge ingestion: raw_content, structured_chunks, chunk_index.

Revision ID: 005
Revises: 004
Create Date: 2026-04-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "knowledge",
        sa.Column("raw_content", sa.Text(), nullable=True),
    )
    op.add_column(
        "knowledge",
        sa.Column(
            "structured_chunks",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "knowledge",
        sa.Column("chunk_index", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("knowledge", "chunk_index")
    op.drop_column("knowledge", "structured_chunks")
    op.drop_column("knowledge", "raw_content")
