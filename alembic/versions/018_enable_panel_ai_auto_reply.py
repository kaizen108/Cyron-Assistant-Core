"""Enable ai_auto_reply on panels that already have an AI context linked.

Revision ID: 018
Revises: 017
Create Date: 2026-07-13

Migration 011 defaulted ai_auto_reply to false for all existing panels.
Panels with a linked ai_context_id were silently blocked from bot replies.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "018"
down_revision: Union[str, None] = "017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE ticket_panels
        SET ai_auto_reply = true
        WHERE ai_context_id IS NOT NULL
          AND ai_auto_reply = false
        """
    )


def downgrade() -> None:
    pass
