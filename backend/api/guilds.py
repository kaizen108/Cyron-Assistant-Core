"""Guild management API."""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from redis.asyncio import Redis
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import get_session
from backend.dependencies import get_redis, get_current_user_id, require_guild_admin
from backend.services.user_guild_service import list_user_guild_ids
from backend.schemas.guild import GuildResponse, GuildUpdate, GuildCloseSettings, GuildCloseSettingsResponse
from backend.schemas.plans import PLAN_LIMITS
from backend.services.guild_service import get_guild, list_guilds, upsert_guild
from backend.services.usage_service import get_usage_history, get_recent_usage_logs
from backend.models.ticket import Ticket
from backend.models.ticket_panel import TicketPanel

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["guilds"])


def _icon_key(guild_id: int) -> str:
    return f"guild:{guild_id}:icon_url"


def _bot_guild_key(guild_id: int) -> str:
    return f"bot:guild:{guild_id}:installed"


def _channels_key(guild_id: int) -> str:
    return f"bot:guild:{guild_id}:channels"


def _channels_sync_key(guild_id: int) -> str:
    return f"bot:guild:{guild_id}:sync_channels"


@router.get("/guilds", response_model=list[GuildResponse])
async def get_all_guilds(
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    user_id: str = Depends(get_current_user_id),
) -> list[GuildResponse]:
    """Return all guilds known to the backend.

    For now this is filtered only by whether the guild has ever been synced
    (typically when an admin/mod logs into the dashboard).
    """
    # Only return guilds the current user is authorized to manage.
    user_guild_ids = set(await list_user_guild_ids(session, user_id))
    if not user_guild_ids:
        return []

    guilds = await list_guilds(session)
    responses: list[GuildResponse] = []
    for g in guilds:
        if g.id not in user_guild_ids:
            continue
        # Skip placeholder/internal guilds that don't have a human-readable name.
        # However, if the bot has reported that it is installed, we still include
        # the guild and rely on the dashboard to show a generic label.
        name_clean = (g.name or "").strip()
        icon_url = await redis.get(_icon_key(g.id))
        has_bot_raw = await redis.get(_bot_guild_key(g.id))
        has_bot = bool(has_bot_raw == "1")
        if not name_clean and not has_bot:
            # Pure placeholder guild with no name and no bot installed: hide it.
            continue
        responses.append(
            GuildResponse(
                id=g.id,
                name=name_clean or f"Server {g.id}",
                icon_url=icon_url,
                plan=g.plan,
                monthly_tokens_used=g.monthly_tokens_used,
                daily_ticket_count=g.daily_ticket_count,
                concurrent_ai_sessions=g.concurrent_ai_sessions,
                last_daily_reset=g.last_daily_reset,
                last_monthly_reset=g.last_monthly_reset,
                system_prompt=g.system_prompt,
                embed_color=g.embed_color or "#00b4ff",
                has_bot=has_bot,
            )
        )
    return responses


@router.get("/guilds/{guild_id}", response_model=GuildResponse)
async def get_or_create_guild(
    guild_id: str,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
    user_id: str = Depends(get_current_user_id),
) -> GuildResponse:
    """
    Get a guild by ID, creating a default one if it does not exist.

    - Plan defaults to "free"
    - System prompt defaults to DEFAULT_SYSTEM_PROMPT
    """
    try:
        gid = int(guild_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid guild_id format")

    guild = await upsert_guild(session, gid)
    logger.info("guild_get_or_create", guild_id=gid, plan=guild.plan)
    icon_url = await redis.get(_icon_key(guild.id))
    has_bot_raw = await redis.get(_bot_guild_key(guild.id))
    has_bot = bool(has_bot_raw == "1")
    return GuildResponse(
        id=guild.id,
        name=guild.name,
        icon_url=icon_url,
        plan=guild.plan,
        monthly_tokens_used=guild.monthly_tokens_used,
        daily_ticket_count=guild.daily_ticket_count,
        concurrent_ai_sessions=guild.concurrent_ai_sessions,
        last_daily_reset=guild.last_daily_reset,
        last_monthly_reset=guild.last_monthly_reset,
        system_prompt=guild.system_prompt,
        embed_color=guild.embed_color or "#00b4ff",
        has_bot=has_bot,
    )


@router.patch("/guilds/{guild_id}", response_model=GuildResponse)
async def update_guild(
    guild_id: str,
    body: GuildUpdate,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> GuildResponse:
    """Update mutable guild fields: name, plan, system_prompt."""
    try:
        gid = int(guild_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid guild_id format")

    guild = await get_guild(session, gid)
    if not guild:
        # Auto-create if not found, then update
        guild = await upsert_guild(session, gid)

    if body.name is not None:
        guild.name = body.name

    if body.plan is not None:
        plan = body.plan.lower()
        if plan not in PLAN_LIMITS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid plan '{body.plan}'. Valid values: free, pro, business.",
            )
        guild.plan = plan

    if body.system_prompt is not None:
        guild.system_prompt = body.system_prompt

    if body.embed_color is not None:
        if guild.plan.lower() not in ("pro", "business"):
            raise HTTPException(
                status_code=403,
                detail="Embed color customization is available for Pro and Business plans only.",
            )
        guild.embed_color = body.embed_color

    logger.info("guild_updated", guild_id=gid, plan=guild.plan)
    has_bot_raw = await redis.get(_bot_guild_key(guild.id))
    has_bot = bool(has_bot_raw == "1")
    return GuildResponse(
        id=guild.id,
        name=guild.name,
        plan=guild.plan,
        monthly_tokens_used=guild.monthly_tokens_used,
        daily_ticket_count=guild.daily_ticket_count,
        concurrent_ai_sessions=guild.concurrent_ai_sessions,
        last_daily_reset=guild.last_daily_reset,
        last_monthly_reset=guild.last_monthly_reset,
        system_prompt=guild.system_prompt,
        embed_color=guild.embed_color or "#00b4ff",
        has_bot=has_bot,
    )


@router.get("/guilds/{guild_id}/usage/history")
async def get_guild_usage_history(
    guild_id: int = Depends(require_guild_admin),
    days: int = 7,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    """Return per-day token usage history for the given guild."""
    if days <= 0:
        raise HTTPException(status_code=400, detail="days must be positive")
    days = min(days, 30)
    history = await get_usage_history(session, guild_id=guild_id, days=days)
    return history


@router.get("/guilds/{guild_id}/usage/logs")
async def get_guild_usage_logs(
    guild_id: int = Depends(require_guild_admin),
    limit: int = 10,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    """Return recent usage logs for the given guild."""
    if limit <= 0:
        raise HTTPException(status_code=400, detail="limit must be positive")
    limit = min(limit, 100)
    logs = await get_recent_usage_logs(session, guild_id=guild_id, limit=limit)
    return logs


@router.get("/guilds/{guild_id}/tickets")
async def get_guild_tickets(
    guild_id: int = Depends(require_guild_admin),
    status: str = Query(default="all"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    search: str = Query(default=""),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Ticket management — list + stats."""
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    seven_days_ago = now - timedelta(days=7)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Stats
    def _count(stmt): return session.execute(stmt)

    open_count_r = await session.execute(select(func.count(Ticket.id)).where(Ticket.guild_id == guild_id, Ticket.status == "open"))
    open_count = open_count_r.scalar_one()

    created_7d_r = await session.execute(select(func.count(Ticket.id)).where(Ticket.guild_id == guild_id, Ticket.created_at >= seven_days_ago))
    created_7d = created_7d_r.scalar_one()

    closed_7d_r = await session.execute(select(func.count(Ticket.id)).where(Ticket.guild_id == guild_id, Ticket.status == "closed", Ticket.closed_at >= seven_days_ago))
    closed_7d = closed_7d_r.scalar_one()

    today_created_r = await session.execute(select(func.count(Ticket.id)).where(Ticket.guild_id == guild_id, Ticket.created_at >= today_start))
    today_created = today_created_r.scalar_one()

    today_closed_r = await session.execute(select(func.count(Ticket.id)).where(Ticket.guild_id == guild_id, Ticket.status == "closed", Ticket.closed_at >= today_start))
    today_closed = today_closed_r.scalar_one()

    all_time_r = await session.execute(select(func.count(Ticket.id)).where(Ticket.guild_id == guild_id))
    all_time = all_time_r.scalar_one()

    claimed_r = await session.execute(select(func.count(Ticket.id)).where(Ticket.guild_id == guild_id, Ticket.claimed_by_user_id.isnot(None)))
    claimed = claimed_r.scalar_one()

    # Ticket list
    stmt = select(Ticket, TicketPanel.name.label("panel_name")).outerjoin(
        TicketPanel, Ticket.panel_id == TicketPanel.id
    ).where(Ticket.guild_id == guild_id)

    if status != "all":
        stmt = stmt.where(Ticket.status == status)
    if search:
        stmt = stmt.where(Ticket.channel_name.ilike(f"%{search}%"))

    total_r = await session.execute(select(func.count()).select_from(stmt.subquery()))
    total = total_r.scalar_one()

    stmt = stmt.order_by(Ticket.created_at.desc()).offset((page - 1) * limit).limit(limit)
    rows = (await session.execute(stmt)).all()

    tickets = []
    for ticket, panel_name in rows:
        tickets.append({
            "id": str(ticket.id),
            "panel_name": panel_name or "—",
            "status": ticket.status,
            "channel_name": ticket.channel_name,
            "ticket_number": ticket.ticket_number,
            "user_id": ticket.user_id,
            "claimed_by_user_id": ticket.claimed_by_user_id,
            "priority": ticket.priority,
            "close_reason": ticket.close_reason,
            "rating": ticket.rating,
            "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
            "closed_at": ticket.closed_at.isoformat() if ticket.closed_at else None,
        })

    return {
        "stats": {
            "open_queue": open_count,
            "created_7d": created_7d,
            "closed_7d": closed_7d,
            "today_created": today_created,
            "today_closed": today_closed,
            "all_time": all_time,
            "claimed": claimed,
        },
        "tickets": tickets,
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.get("/guilds/{guild_id}/tickets/{ticket_id}")
async def get_guild_ticket_detail(
    ticket_id: str,
    guild_id: int = Depends(require_guild_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Ticket detail with message history."""
    import uuid as _uuid
    from backend.models.message import Message

    try:
        tid = _uuid.UUID(ticket_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ticket_id")

    result = await session.execute(
        select(Ticket, TicketPanel.name.label("panel_name")).outerjoin(
            TicketPanel, Ticket.panel_id == TicketPanel.id
        ).where(Ticket.id == tid, Ticket.guild_id == guild_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Ticket not found")

    ticket, panel_name = row

    msgs_result = await session.execute(
        select(Message).where(Message.ticket_id == ticket.id).order_by(Message.created_at)
    )
    messages = [
        {
            "role": m.role,
            "content": m.content,
            "timestamp": m.created_at.isoformat() if m.created_at else None,
        }
        for m in msgs_result.scalars().all()
    ]

    return {
        "ticket": {
            "id": str(ticket.id),
            "panel_name": panel_name or "—",
            "status": ticket.status,
            "channel_name": ticket.channel_name,
            "ticket_number": ticket.ticket_number,
            "user_id": ticket.user_id,
            "claimed_by_user_id": ticket.claimed_by_user_id,
            "closed_by_user_id": ticket.closed_by_user_id,
            "priority": ticket.priority,
            "close_reason": ticket.close_reason,
            "rating": ticket.rating,
            "form_answers": ticket.form_answers,
            "ai_summary": None,  # Phase 2
            "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
            "closed_at": ticket.closed_at.isoformat() if ticket.closed_at else None,
        },
        "messages": messages,
    }


@router.get("/guilds/{guild_id}/channels")
async def get_guild_channels_dashboard(
    guild_id: int = Depends(require_guild_admin),
    redis: Redis = Depends(get_redis),
) -> list:
    """Return cached text channels for dashboard channel selector."""
    import json
    raw = await redis.get(_channels_key(guild_id))
    return json.loads(raw) if raw else []


@router.post("/guilds/{guild_id}/channels/refresh")
async def refresh_guild_channels_dashboard(
    guild_id: int = Depends(require_guild_admin),
    redis: Redis = Depends(get_redis),
) -> dict:
    """Ask the Discord bot to re-sync this guild's channel list into Redis."""
    await redis.set(_channels_sync_key(guild_id), "1", ex=300)
    logger.info("guild_channels_sync_requested", guild_id=guild_id)
    return {"status": "queued"}


@router.get("/guilds/{guild_id}/close-settings")
async def get_close_settings(
    guild_id: int = Depends(require_guild_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    guild = await get_guild(session, guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")
    return GuildCloseSettingsResponse.model_validate(guild).model_dump()


@router.patch("/guilds/{guild_id}/close-settings")
async def update_close_settings(
    body: GuildCloseSettings,
    guild_id: int = Depends(require_guild_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    guild = await get_guild(session, guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(guild, field, value)
    await session.flush()
    return GuildCloseSettingsResponse.model_validate(guild).model_dump()
