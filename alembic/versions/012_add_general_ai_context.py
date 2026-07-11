"""add general ai context

Revision ID: 012
Revises: 011
Create Date: 2025-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '012'
down_revision: Union[str, None] = '011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'guilds',
        sa.Column('general_ai_context_id', sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        'fk_guilds_general_ai_context_id',
        'guilds',
        'ai_contexts',
        ['general_ai_context_id'],
        ['id'],
    )
    op.add_column(
        'guilds',
        sa.Column('general_ai_enabled', sa.Boolean(), nullable=False, server_default='true'),
    )


def downgrade() -> None:
    op.drop_constraint('fk_guilds_general_ai_context_id', 'guilds', type_='foreignkey')
    op.drop_column('guilds', 'general_ai_enabled')
    op.drop_column('guilds', 'general_ai_context_id')
