"""Panel-aware relay helpers (status questions without LLM)."""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.ticket_panel import TicketPanel

_PANEL_RE = re.compile(r"\b(panel|ticket\s*panel)\b", re.I)
_STATUS_HINT = re.compile(
    r"\b("
    r"enabled?|disabled?|active|still|working|accepting|"
    r"turned\s+off|available|open|closed|on|off"
    r")\b",
    re.I,
)


def is_panel_status_query(text: str) -> bool:
    """User is asking whether the ticket panel is on/off — answer from DB, not KB."""
    t = (text or "").strip()
    if not t or not _PANEL_RE.search(t):
        return False
    return bool(_STATUS_HINT.search(t))


async def panel_status_reply(
    session: AsyncSession,
    panel_id: uuid.UUID,
    guild_id: int,
) -> str | None:
    result = await session.execute(
        select(TicketPanel).where(
            TicketPanel.id == panel_id,
            TicketPanel.guild_id == guild_id,
        )
    )
    panel = result.scalar_one_or_none()
    if not panel:
        return None

    name = (panel.name or "").strip() or "ticket panel"
    if panel.is_enabled:
        return (
            f"Yes — the \"{name}\" panel is currently enabled. "
            "Users can open new tickets through it."
        )
    return (
        f"The \"{name}\" panel is currently disabled. "
        "New tickets cannot be opened from it right now."
    )
