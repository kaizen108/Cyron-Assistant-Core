"""Internal endpoints used by the Discord bot.

These are called from the bot process to let the backend know which guilds
currently have the bot installed, so the dashboard can show accurate status.
"""

import structlog
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import get_session
from backend.dependencies import get_redis, require_bot_api_key
from backend.services.guild_service import upsert_guild
from backend.services.ticket_service import get_ticket_by_channel
from backend.models.ticket import Ticket
from backend.models.ticket_panel import TicketPanel
from backend.models.guild import Guild

logger = structlog.get_logger()
router = APIRouter(prefix="/internal/bot", tags=["internal-bot"])


def _bot_guild_key(guild_id: int) -> str:
    return f"bot:guild:{guild_id}:installed"


def _channels_key(guild_id: int) -> str:
    return f"bot:guild:{guild_id}:channels"


class ChannelListPayload(BaseModel):
    channels: list[dict]  # [{id, name, type}]


@router.post("/guilds/{guild_id}/channels")
async def push_guild_channels(
    guild_id: str,
    body: ChannelListPayload,
    _: None = Depends(require_bot_api_key),
    redis: Redis = Depends(get_redis),
) -> dict:
    """Bot pushes text channel list so dashboard can show channel selector."""
    import json
    try:
        gid = int(guild_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid guild_id")
    await redis.set(_channels_key(gid), json.dumps(body.channels), ex=24 * 60 * 60)
    return {"status": "ok"}


@router.get("/guilds/{guild_id}/channels")
async def get_guild_channels(
    guild_id: str,
    _: None = Depends(require_bot_api_key),
    redis: Redis = Depends(get_redis),
) -> list:
    """Return cached text channels for a guild."""
    import json
    try:
        gid = int(guild_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid guild_id")
    raw = await redis.get(_channels_key(gid))
    return json.loads(raw) if raw else []


class BotGuildPayload(BaseModel):
    """Payload sent from the bot when marking a guild."""

    name: str | None = None


@router.post("/guilds/{guild_id}/installed")
async def mark_guild_has_bot(
    guild_id: str,
    body: BotGuildPayload | None = None,
    _: None = Depends(require_bot_api_key),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> dict:
    """Mark that the bot is installed in the given guild.

    Called from the Discord bot when it joins (or starts up already in) a guild.
    """
    try:
        gid = int(guild_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid guild_id format")

    name = (body.name or "").strip() if body else ""
    guild = await upsert_guild(session, gid, name=name)
    # Mark in Redis that this guild currently has the bot installed.
    # We keep a generous TTL; the bot periodically refreshes this flag while
    # it is present in the guild, and on_guild_remove clears it explicitly.
    # If the bot is removed while offline and never sends a "removed" event,
    # the flag will eventually expire.
    await redis.set(_bot_guild_key(gid), "1", ex=24 * 60 * 60)
    logger.info("bot_mark_installed", guild_id=gid, name=guild.name)
    return {"status": "ok"}


@router.post("/guilds/{guild_id}/removed")
async def mark_guild_bot_removed(
    guild_id: str,
    _: None = Depends(require_bot_api_key),
    redis: Redis = Depends(get_redis),
) -> dict:
    """Mark that the bot has been removed from the given guild."""
    try:
        gid = int(guild_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid guild_id format")

    await redis.delete(_bot_guild_key(gid))
    logger.info("bot_mark_removed", guild_id=gid)
    return {"status": "ok"}


@router.get("/guilds/{guild_id}/tickets/{channel_id}")
async def get_ticket_for_channel(
    guild_id: str,
    channel_id: str,
    _: None = Depends(require_bot_api_key),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Return ticket row (including panel_id) for a channel."""
    try:
        gid = int(guild_id)
        cid = int(channel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid guild_id or channel_id")

    ticket = await get_ticket_by_channel(session, gid, cid)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return {
        "id": str(ticket.id),
        "guild_id": ticket.guild_id,
        "channel_id": ticket.channel_id,
        "bot_id": ticket.bot_id,
        "panel_id": str(ticket.panel_id) if ticket.panel_id else None,
        "status": ticket.status,
        "ticket_number": ticket.ticket_number,
        "user_id": ticket.user_id,
        "claimed_by_user_id": ticket.claimed_by_user_id,
        "priority": ticket.priority,
        "human_handoff": ticket.human_handoff,
    }


class OpenTicketPayload(BaseModel):
    channel_id: int
    user_id: int
    panel_id: str | None = None
    bot_id: int | None = None
    ticket_number: int | None = None
    channel_name: str | None = None
    form_answers: dict | None = None


@router.post("/guilds/{guild_id}/tickets/open")
async def open_ticket(
    guild_id: str,
    body: OpenTicketPayload,
    _: None = Depends(require_bot_api_key),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Register a newly opened ticket."""
    import uuid as _uuid
    try:
        gid = int(guild_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid guild_id")

    panel_uuid = None
    if body.panel_id:
        try:
            panel_uuid = _uuid.UUID(body.panel_id)
        except ValueError:
            pass

    # Upsert to handle race conditions
    existing = await get_ticket_by_channel(session, gid, body.channel_id)
    if existing:
        return {"id": str(existing.id), "ticket_number": existing.ticket_number}

    ticket = Ticket(
        guild_id=gid,
        channel_id=body.channel_id,
        user_id=body.user_id,
        panel_id=panel_uuid,
        bot_id=body.bot_id,
        ticket_number=body.ticket_number,
        channel_name=body.channel_name,
        form_answers=body.form_answers,
        status="open",
    )
    session.add(ticket)
    await session.flush()
    logger.info("ticket_opened", guild_id=gid, ticket_id=str(ticket.id))
    return {"id": str(ticket.id), "ticket_number": ticket.ticket_number}


@router.post("/guilds/{guild_id}/tickets/next-number")
async def next_ticket_number(
    guild_id: str,
    _: None = Depends(require_bot_api_key),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Atomically increment and return the next ticket number for a guild."""
    try:
        gid = int(guild_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid guild_id")

    result = await session.execute(
        select(Guild).where(Guild.id == gid)
    )
    guild = result.scalar_one_or_none()
    if not guild:
        guild = await upsert_guild(session, gid)
        await session.flush()

    guild.ticket_counter = (guild.ticket_counter or 0) + 1
    await session.flush()
    return {"ticket_number": guild.ticket_counter}


class CloseTicketPayload(BaseModel):
    closed_by_user_id: int
    reason: str | None = None


@router.post("/guilds/{guild_id}/tickets/{channel_id}/close")
async def close_ticket(
    guild_id: str,
    channel_id: str,
    body: CloseTicketPayload,
    _: None = Depends(require_bot_api_key),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Mark a ticket as closed in the DB."""
    try:
        gid = int(guild_id)
        cid = int(channel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ids")

    ticket = await get_ticket_by_channel(session, gid, cid)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    ticket.status = "closed"
    ticket.closed_at = datetime.now(timezone.utc)
    ticket.closed_by_user_id = body.closed_by_user_id
    ticket.close_reason = body.reason
    await session.flush()
    logger.info("ticket_closed", guild_id=gid, ticket_id=str(ticket.id))
    return {"ticket_id": str(ticket.id), "status": "closed"}


class ClaimTicketPayload(BaseModel):
    claimed_by_user_id: int


@router.post("/guilds/{guild_id}/tickets/{channel_id}/claim")
async def claim_ticket(
    guild_id: str,
    channel_id: str,
    body: ClaimTicketPayload,
    _: None = Depends(require_bot_api_key),
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        gid = int(guild_id)
        cid = int(channel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ids")

    ticket = await get_ticket_by_channel(session, gid, cid)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    ticket.claimed_by_user_id = body.claimed_by_user_id
    await session.flush()
    return {"ticket_id": str(ticket.id), "claimed_by": body.claimed_by_user_id}


@router.post("/guilds/{guild_id}/tickets/{channel_id}/unclaim")
async def unclaim_ticket(
    guild_id: str,
    channel_id: str,
    _: None = Depends(require_bot_api_key),
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        gid = int(guild_id)
        cid = int(channel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ids")

    ticket = await get_ticket_by_channel(session, gid, cid)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    ticket.claimed_by_user_id = None
    await session.flush()
    return {"ticket_id": str(ticket.id), "claimed_by": None}


class PriorityPayload(BaseModel):
    priority: str  # low | medium | high | urgent


@router.post("/guilds/{guild_id}/tickets/{channel_id}/priority")
async def set_priority(
    guild_id: str,
    channel_id: str,
    body: PriorityPayload,
    _: None = Depends(require_bot_api_key),
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        gid = int(guild_id)
        cid = int(channel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ids")

    ticket = await get_ticket_by_channel(session, gid, cid)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    ticket.priority = body.priority
    await session.flush()
    return {"ticket_id": str(ticket.id), "priority": body.priority}


class HandoffPayload(BaseModel):
    human_handoff: bool


@router.post("/guilds/{guild_id}/tickets/{channel_id}/handoff")
async def set_ticket_handoff(
    guild_id: str,
    channel_id: str,
    body: HandoffPayload,
    _: None = Depends(require_bot_api_key),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Set or clear human handoff on a ticket (blocks AI auto-reply when True)."""
    try:
        gid = int(guild_id)
        cid = int(channel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ids")

    ticket = await get_ticket_by_channel(session, gid, cid)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    ticket.human_handoff = body.human_handoff
    await session.flush()
    return {"ticket_id": str(ticket.id), "human_handoff": ticket.human_handoff}


class PublishPanelPayload(BaseModel):
    channel_id: int
    message_id: int


@router.post("/guilds/{guild_id}/panels/{panel_id}/publish")
async def publish_panel(
    guild_id: str,
    panel_id: str,
    body: PublishPanelPayload,
    _: None = Depends(require_bot_api_key),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Save where a panel embed was published."""
    import uuid as _uuid
    try:
        gid = int(guild_id)
        pid = _uuid.UUID(panel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ids")

    result = await session.execute(
        select(TicketPanel).where(TicketPanel.id == pid, TicketPanel.guild_id == gid)
    )
    panel = result.scalar_one_or_none()
    if not panel:
        raise HTTPException(status_code=404, detail="Panel not found")

    panel.published_channel_id = body.channel_id
    panel.published_message_id = body.message_id
    await session.flush()
    return {"status": "ok"}


@router.get("/guilds/{guild_id}/panels/list/public")
async def list_panels_public(
    guild_id: str,
    _: None = Depends(require_bot_api_key),
    session: AsyncSession = Depends(get_session),
) -> list:
    """List enabled panels for a guild (bot use)."""
    try:
        gid = int(guild_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid guild_id")

    result = await session.execute(
        select(TicketPanel).where(
            TicketPanel.guild_id == gid,
            TicketPanel.is_enabled == True,
        ).order_by(TicketPanel.created_at)
    )
    panels = result.scalars().all()
    return [{"id": str(p.id), "name": p.name} for p in panels]


@router.post("/guilds/{guild_id}/panels/{panel_id}/send-to-channel")
async def send_panel_to_channel(
    guild_id: str,
    panel_id: str,
    body: PublishPanelPayload,
    _: None = Depends(require_bot_api_key),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> dict:
    """Queue a panel send for the bot (same Redis queue as dashboard send)."""
    import json
    import uuid as _uuid

    try:
        gid = int(guild_id)
        pid = _uuid.UUID(panel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ids")

    result = await session.execute(
        select(TicketPanel).where(TicketPanel.id == pid, TicketPanel.guild_id == gid)
    )
    panel = result.scalar_one_or_none()
    if not panel:
        raise HTTPException(status_code=404, detail="Panel not found")

    task = {
        "guild_id": gid,
        "panel_id": str(pid),
        "channel_id": body.channel_id,
    }
    await redis.lpush("bot:pending_panel_sends", json.dumps(task))
    return {"status": "queued", **task}


@router.get("/guilds/{guild_id}/panels/{panel_id}/public")
async def get_panel_public(
    guild_id: str,
    panel_id: str,
    _: None = Depends(require_bot_api_key),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Fetch panel data for bot use (no auth token needed, uses bot API key)."""
    import uuid as _uuid
    try:
        gid = int(guild_id)
        pid = _uuid.UUID(panel_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ids")

    result = await session.execute(
        select(TicketPanel).where(TicketPanel.id == pid, TicketPanel.guild_id == gid)
    )
    panel = result.scalar_one_or_none()
    if not panel:
        raise HTTPException(status_code=404, detail="Panel not found")

    # Return all fields the bot needs
    return {
        "id": str(panel.id),
        "guild_id": panel.guild_id,
        "name": panel.name,
        "ai_context_id": str(panel.ai_context_id) if panel.ai_context_id else None,
        "ai_auto_reply": panel.ai_auto_reply,
        "is_enabled": panel.is_enabled,
        "ticket_category_name": panel.ticket_category_name,
        "button_text": panel.button_text,
        "button_emoji": panel.button_emoji,
        "button_color": panel.button_color,
        "panel_embed_title": panel.panel_embed_title,
        "panel_embed_description": panel.panel_embed_description,
        "panel_embed_color": panel.panel_embed_color,
        "panel_embed_author": panel.panel_embed_author,
        "panel_embed_footer": panel.panel_embed_footer,
        "welcome_embed_title": panel.welcome_embed_title,
        "welcome_embed_description": panel.welcome_embed_description,
        "welcome_embed_footer": panel.welcome_embed_footer,
        "welcome_embed_author": panel.welcome_embed_author,
        "welcome_ping_ticket_creator": panel.welcome_ping_ticket_creator,
        "welcome_ping_support_roles": panel.welcome_ping_support_roles,
        "auto_pin_welcome": panel.auto_pin_welcome,
        "support_role_ids": panel.support_role_ids or [],
        "overflow_category_ids": panel.overflow_category_ids or [],
        "channel_name_format": panel.channel_name_format,
        "roles_required": panel.roles_required or [],
        "roles_blocked": panel.roles_blocked or [],
        "max_open_tickets_per_user": panel.max_open_tickets_per_user,
        "creation_cooldown_seconds": panel.creation_cooldown_seconds,
        "users_can_close": panel.users_can_close,
        "claiming_enabled": panel.claiming_enabled,
        "claiming_visibility": panel.claiming_visibility,
        "forms_enabled": panel.forms_enabled,
        "form_questions": panel.form_questions or [],
        "support_hours_enabled": panel.support_hours_enabled,
        "support_hours_timezone": panel.support_hours_timezone,
        "support_hours_schedule": panel.support_hours_schedule or {},
        "closed_state_logic": panel.closed_state_logic,
        "msg_closed": panel.msg_closed,
        "log_channel_id": panel.log_channel_id,
        "send_logs_in_ticket": panel.send_logs_in_ticket,
        "sync_category_permissions": panel.sync_category_permissions,
        "close_button_emoji": panel.close_button_emoji,
        "close_button_label": panel.close_button_label,
        "close_button_color": panel.close_button_color,
        "claim_button_emoji": panel.claim_button_emoji,
        "claim_button_label": panel.claim_button_label,
        "unclaim_button_label": panel.unclaim_button_label,
        "claim_button_color": panel.claim_button_color,
        "footer_text": panel.footer_text,
        "autoclose_hours": panel.autoclose_hours,
        "autoclose_warning_hours": panel.autoclose_warning_hours,
    }



@router.get("/guilds/{guild_id}/tickets/open")
async def get_open_tickets_by_user(
    guild_id: str,
    user_id: str | None = Query(default=None),
    panel_id: str | None = Query(default=None),
    _: None = Depends(require_bot_api_key),
    session: AsyncSession = Depends(get_session),
) -> list:
    """Get open tickets, optionally filtered by user_id and/or panel_id."""
    import uuid as _uuid

    try:
        gid = int(guild_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid guild_id")

    stmt = select(Ticket).where(Ticket.guild_id == gid, Ticket.status == "open")
    if user_id:
        try:
            stmt = stmt.where(Ticket.user_id == int(user_id))
        except ValueError:
            pass
    if panel_id:
        try:
            pid = _uuid.UUID(panel_id)
            stmt = stmt.where(Ticket.panel_id == pid)
        except ValueError:
            pass

    result = await session.execute(stmt)
    tickets = result.scalars().all()
    return [
        {
            "id": str(t.id),
            "channel_id": t.channel_id,
            "user_id": t.user_id,
            "panel_id": str(t.panel_id) if t.panel_id else None,
            "ticket_number": t.ticket_number,
            "channel_name": t.channel_name,
        }
        for t in tickets
    ]


@router.get("/tickets/stale")
async def get_stale_tickets(
    _: None = Depends(require_bot_api_key),
    session: AsyncSession = Depends(get_session),
) -> list:
    """Return tickets that need autoclose warning or closure."""
    from sqlalchemy import and_
    from backend.models.message import Message

    now = datetime.now(timezone.utc)

    result = await session.execute(
        select(Ticket, TicketPanel).join(
            TicketPanel, Ticket.panel_id == TicketPanel.id, isouter=True
        ).where(
            Ticket.status == "open",
            TicketPanel.autoclose_hours.isnot(None),
        )
    )
    rows = result.all()

    stale = []
    for ticket, panel in rows:
        if not panel or not panel.autoclose_hours:
            continue
        # Get last message time
        msg_result = await session.execute(
            select(Message.created_at).where(Message.ticket_id == ticket.id)
            .order_by(Message.created_at.desc()).limit(1)
        )
        last_msg_at = msg_result.scalar_one_or_none() or ticket.created_at
        if last_msg_at.tzinfo is None:
            from datetime import timezone as tz
            last_msg_at = last_msg_at.replace(tzinfo=tz.utc)

        idle_hours = (now - last_msg_at).total_seconds() / 3600

        if idle_hours >= panel.autoclose_hours:
            stale.append({
                "guild_id": ticket.guild_id,
                "channel_id": ticket.channel_id,
                "ticket_id": str(ticket.id),
                "action": "close",
                "hours_remaining": 0,
            })
        elif panel.autoclose_warning_hours and idle_hours >= (panel.autoclose_hours - panel.autoclose_warning_hours):
            hours_remaining = panel.autoclose_hours - idle_hours
            stale.append({
                "guild_id": ticket.guild_id,
                "channel_id": ticket.channel_id,
                "ticket_id": str(ticket.id),
                "action": "warn",
                "hours_remaining": round(hours_remaining, 1),
            })

    return stale

