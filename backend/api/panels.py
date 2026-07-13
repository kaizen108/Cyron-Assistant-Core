"""Ticket Panel CRUD API — /guilds/{guild_id}/panels"""

import uuid
from typing import Any
from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import get_session
from backend.dependencies import require_guild_admin, get_redis
from backend.models.guild import Guild
from backend.models.ticket_panel import TicketPanel
from backend.services.context_service import ensure_general_rules_context, is_general_rules_context

router = APIRouter(prefix="/guilds/{guild_id}/panels", tags=["panels"])


class PanelIn(BaseModel):
    name: str
    bot_id: int | None = None
    ticket_category_name: str = "Tickets"
    button_text: str = "Open Ticket"
    button_emoji: str | None = None
    welcome_message: str | None = None
    ai_context_id: uuid.UUID | None = None
    # General
    is_enabled: bool = True
    ai_auto_reply: bool = True
    support_role_ids: list | None = None
    overflow_category_ids: list | None = None
    threading_mode: bool = False
    save_transcripts: bool = True
    channel_name_format: str = "{panel.name}-{ticket.number}"
    roles_required: list | None = None
    roles_blocked: list | None = None
    limit_bypass_roles: list | None = None
    max_open_tickets_per_user: int = 1
    creation_cooldown_seconds: int = 0
    users_can_close: bool = False
    claiming_enabled: bool = True
    claiming_visibility: str = "view_only"
    footer_text: str | None = None
    # Embed
    panel_embed_author: str | None = None
    panel_embed_title: str | None = "Create a ticket"
    panel_embed_description: str | None = None
    panel_embed_footer: str | None = None
    panel_embed_color: str | None = "#5865F2"
    button_type: str = "button"
    button_color: str = "blurple"
    # Messages
    welcome_ping_ticket_creator: bool = True
    welcome_ping_support_roles: bool = True
    welcome_ping_admin_role: bool = False
    welcome_embed_author: str | None = None
    welcome_embed_title: str | None = "Ticket Created"
    welcome_embed_description: str | None = None
    welcome_embed_footer: str | None = None
    auto_pin_welcome: bool = True
    close_button_emoji: str | None = "🔒"
    close_button_label: str | None = "Close"
    close_button_color: str = "red"
    claim_button_emoji: str | None = "👤"
    claim_button_label: str | None = "Claim"
    unclaim_button_label: str | None = "Unclaim"
    claim_button_color: str = "blurple"
    # Forms
    forms_enabled: bool = False
    form_questions: list | None = None
    # Availability
    support_hours_enabled: bool = False
    support_hours_timezone: str = "UTC"
    support_hours_schedule: dict | None = None
    closed_state_logic: str = "allow_with_warning"
    msg_reduced_support: dict | None = None
    msg_emergency_only: dict | None = None
    msg_closed: dict | None = None
    # Logging
    log_channel_id: int | None = None
    send_logs_in_ticket: bool = False
    # Advanced
    sync_category_permissions: bool = False
    autoclose_hours: int | None = None
    autoclose_warning_hours: int | None = None


class PanelOut(BaseModel):
    id: uuid.UUID
    guild_id: int
    name: str
    bot_id: int | None
    ticket_category_name: str
    button_text: str
    button_emoji: str | None
    welcome_message: str | None
    ai_context_id: uuid.UUID | None
    is_enabled: bool
    ai_auto_reply: bool
    support_role_ids: Any
    overflow_category_ids: Any
    threading_mode: bool
    save_transcripts: bool
    channel_name_format: str
    roles_required: Any
    roles_blocked: Any
    limit_bypass_roles: Any
    max_open_tickets_per_user: int
    creation_cooldown_seconds: int
    users_can_close: bool
    claiming_enabled: bool
    claiming_visibility: str
    footer_text: str | None
    panel_embed_author: str | None
    panel_embed_title: str | None
    panel_embed_description: str | None
    panel_embed_footer: str | None
    panel_embed_color: str | None
    button_type: str
    button_color: str
    welcome_ping_ticket_creator: bool
    welcome_ping_support_roles: bool
    welcome_ping_admin_role: bool
    welcome_embed_author: str | None
    welcome_embed_title: str | None
    welcome_embed_description: str | None
    welcome_embed_footer: str | None
    auto_pin_welcome: bool
    close_button_emoji: str | None
    close_button_label: str | None
    close_button_color: str
    claim_button_emoji: str | None
    claim_button_label: str | None
    unclaim_button_label: str | None
    claim_button_color: str
    forms_enabled: bool
    form_questions: Any
    support_hours_enabled: bool
    support_hours_timezone: str
    support_hours_schedule: Any
    closed_state_logic: str
    msg_reduced_support: Any
    msg_emergency_only: Any
    msg_closed: Any
    log_channel_id: int | None
    send_logs_in_ticket: bool
    sync_category_permissions: bool
    autoclose_hours: int | None
    autoclose_warning_hours: int | None
    published_channel_id: int | None = None
    published_message_id: int | None = None

    class Config:
        from_attributes = True


async def _get_panel(session: AsyncSession, panel_id: uuid.UUID, guild_id: int) -> TicketPanel | None:
    result = await session.execute(
        select(TicketPanel).where(TicketPanel.id == panel_id, TicketPanel.guild_id == guild_id)
    )
    return result.scalar_one_or_none()


async def _validate_panel_ai_context(
    session: AsyncSession,
    guild_id: int,
    ai_context_id: uuid.UUID | None,
) -> None:
    if not ai_context_id:
        return
    if await is_general_rules_context(session, guild_id, ai_context_id):
        raise HTTPException(
            status_code=400,
            detail="General Rules cannot be linked to a panel. Use the AI tab to select a panel-specific context.",
        )


@router.get("", response_model=list[PanelOut])
async def list_panels(
    guild_id: int = Depends(require_guild_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(TicketPanel).where(TicketPanel.guild_id == guild_id).order_by(TicketPanel.created_at)
    )
    return list(result.scalars().all())


@router.post("", response_model=PanelOut, status_code=201)
async def create_panel(
    body: PanelIn = Body(...),
    guild_id: int = Depends(require_guild_admin),
    session: AsyncSession = Depends(get_session),
):
    await _validate_panel_ai_context(session, guild_id, body.ai_context_id)
    if body.ai_auto_reply:
        guild_result = await session.execute(select(Guild).where(Guild.id == guild_id))
        guild = guild_result.scalar_one_or_none()
        if guild:
            await ensure_general_rules_context(session, guild)
    panel = TicketPanel(guild_id=guild_id, **body.model_dump())
    session.add(panel)
    await session.flush()
    return panel


@router.get("/{panel_id}", response_model=PanelOut)
async def get_panel(
    panel_id: uuid.UUID,
    guild_id: int = Depends(require_guild_admin),
    session: AsyncSession = Depends(get_session),
):
    panel = await _get_panel(session, panel_id, guild_id)
    if not panel:
        raise HTTPException(status_code=404, detail="Panel not found")
    return panel


@router.put("/{panel_id}", response_model=PanelOut)
async def update_panel(
    panel_id: uuid.UUID,
    body: PanelIn = Body(...),
    guild_id: int = Depends(require_guild_admin),
    session: AsyncSession = Depends(get_session),
):
    panel = await _get_panel(session, panel_id, guild_id)
    if not panel:
        raise HTTPException(status_code=404, detail="Panel not found")
    await _validate_panel_ai_context(session, guild_id, body.ai_context_id)
    if body.ai_auto_reply:
        guild_result = await session.execute(select(Guild).where(Guild.id == guild_id))
        guild = guild_result.scalar_one_or_none()
        if guild:
            await ensure_general_rules_context(session, guild)
    for k, v in body.model_dump().items():
        setattr(panel, k, v)
    await session.flush()
    return panel


@router.delete("/{panel_id}", status_code=204)
async def delete_panel(
    panel_id: uuid.UUID,
    guild_id: int = Depends(require_guild_admin),
    session: AsyncSession = Depends(get_session),
):
    panel = await _get_panel(session, panel_id, guild_id)
    if not panel:
        raise HTTPException(status_code=404, detail="Panel not found")
    await session.delete(panel)


class SendPanelRequest(BaseModel):
    channel_id: str  # Discord snowflake — string to preserve precision from JS clients


@router.post("/{panel_id}/send")
async def send_panel_to_channel(
    panel_id: uuid.UUID,
    body: SendPanelRequest,
    guild_id: int = Depends(require_guild_admin),
    session: AsyncSession = Depends(get_session),
    redis=Depends(get_redis),
):
    """Queue a panel send to a Discord channel via Redis."""
    import json

    channel_id = body.channel_id.strip()
    if not channel_id.isdigit():
        raise HTTPException(status_code=400, detail="Invalid channel_id format")

    panel = await _get_panel(session, panel_id, guild_id)
    if not panel:
        raise HTTPException(status_code=404, detail="Panel not found")

    task = {
        "guild_id": str(guild_id),
        "panel_id": str(panel_id),
        "channel_id": channel_id,
    }
    await redis.lpush("bot:pending_panel_sends", json.dumps(task))
    return {"status": "queued"}
