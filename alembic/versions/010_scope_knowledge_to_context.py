"""Scope knowledge to ai_context + backfill existing data

Revision ID: 010
Revises: 009
Create Date: 2026-05-03

Backfill logic:
  For each guild:
    1. Create one ai_context (Default Context, version=1)
    2. Create one ticket_panel pointing to that context
    3. Set knowledge.ai_context_id = that context id
    4. Set knowledge.section based on template_type
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid
from datetime import datetime, timezone

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("knowledge", sa.Column("ai_context_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ai_contexts.id"), nullable=True))
    op.add_column("knowledge", sa.Column("section", sa.String(32), nullable=True))
    op.create_index("ix_knowledge_ai_context_id", "knowledge", ["ai_context_id"])

    # Backfill
    conn = op.get_bind()
    now = datetime.now(timezone.utc)

    guilds = conn.execute(sa.text("SELECT id FROM guilds")).fetchall()
    for (guild_id,) in guilds:
        ctx_id = str(uuid.uuid4())
        conn.execute(sa.text("""
            INSERT INTO ai_contexts (id, guild_id, name, context_version, created_at, updated_at)
            VALUES (:id, :guild_id, 'Default Context', 1, :now, :now)
        """), {"id": ctx_id, "guild_id": guild_id, "now": now})

        panel_id = str(uuid.uuid4())
        conn.execute(sa.text("""
            INSERT INTO ticket_panels (id, guild_id, name, ticket_category_name, button_text, ai_context_id, created_at)
            VALUES (:id, :guild_id, 'Default Panel', 'Tickets', 'Open Ticket', :ctx_id, :now)
        """), {"id": panel_id, "guild_id": guild_id, "ctx_id": ctx_id, "now": now})

        conn.execute(sa.text("""
            UPDATE knowledge SET
                ai_context_id = :ctx_id,
                section = CASE WHEN template_type = 'problem_solution' THEN 'problems' ELSE 'knowledge' END
            WHERE guild_id = :guild_id
        """), {"ctx_id": ctx_id, "guild_id": guild_id})


def downgrade() -> None:
    op.drop_index("ix_knowledge_ai_context_id", "knowledge")
    op.drop_column("knowledge", "section")
    op.drop_column("knowledge", "ai_context_id")
