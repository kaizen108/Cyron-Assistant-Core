"""Compatibility stub — revision existed on production DB before repo sync.

Revision ID: 014
Revises: 013
Create Date: 2026-07-12
"""

from typing import Sequence, Union


revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
