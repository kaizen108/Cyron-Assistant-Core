"""Knowledge templates v2: template_type, template_payload, source.

Revision ID: 006
Revises: 005
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "knowledge",
        sa.Column("template_type", sa.String(length=64), nullable=False, server_default="general_knowledge"),
    )
    op.add_column(
        "knowledge",
        sa.Column(
            "template_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "knowledge",
        sa.Column("source", sa.String(length=500), nullable=True),
    )
    op.alter_column("knowledge", "template_type", server_default=None)


def downgrade() -> None:
    op.drop_column("knowledge", "source")
    op.drop_column("knowledge", "template_payload")
    op.drop_column("knowledge", "template_type")
