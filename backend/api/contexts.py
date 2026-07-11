"""AI Context CRUD API — /guilds/{guild_id}/contexts"""

import uuid
from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import get_session
from backend.dependencies import require_guild_admin
from backend.models.guild import Guild
from backend.services.context_service import (
    create_context,
    delete_context,
    ensure_general_rules_context,
    get_context,
    is_general_rules_context,
    list_contexts,
    update_context,
)

router = APIRouter(prefix="/guilds/{guild_id}/contexts", tags=["contexts"])


class ContextIn(BaseModel):
    name: str
    instructions: str | None = None
    general_info: str | None = None


class ContextOut(BaseModel):
    id: uuid.UUID
    guild_id: int
    name: str
    context_version: int
    instructions: str | None
    general_info: str | None


class GeneralRulesOut(BaseModel):
    id: uuid.UUID
    name: str
    context_version: int
    instructions: str | None
    general_info: str | None
    enabled: bool


class GeneralRulesUpdate(BaseModel):
    instructions: str | None = None
    general_info: str | None = None
    enabled: bool | None = None


@router.get("", response_model=list[ContextOut])
async def list_guild_contexts(
    guild_id: int = Depends(require_guild_admin),
    session: AsyncSession = Depends(get_session),
):
    return await list_contexts(session, guild_id, exclude_general_rules=True)


@router.post("", response_model=ContextOut, status_code=201)
async def create_guild_context(
    body: ContextIn = Body(...),
    guild_id: int = Depends(require_guild_admin),
    session: AsyncSession = Depends(get_session),
):
    return await create_context(session, guild_id, body.name, body.instructions, body.general_info)


@router.get("/general", response_model=GeneralRulesOut)
async def get_general_rules(
    guild_id: int = Depends(require_guild_admin),
    session: AsyncSession = Depends(get_session),
):
    """Get or create the General Rules context for a guild."""
    result = await session.execute(select(Guild).where(Guild.id == guild_id))
    guild = result.scalar_one_or_none()
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    ctx = await ensure_general_rules_context(session, guild)

    return GeneralRulesOut(
        id=ctx.id,
        name=ctx.name,
        context_version=ctx.context_version,
        instructions=ctx.instructions,
        general_info=ctx.general_info,
        enabled=guild.general_ai_enabled,
    )


@router.put("/general", response_model=GeneralRulesOut)
async def update_general_rules(
    body: GeneralRulesUpdate = Body(...),
    guild_id: int = Depends(require_guild_admin),
    session: AsyncSession = Depends(get_session),
):
    """Update the General Rules context content and/or enabled state."""
    result = await session.execute(select(Guild).where(Guild.id == guild_id))
    guild = result.scalar_one_or_none()
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    ctx = await ensure_general_rules_context(session, guild)

    if body.instructions is not None:
        ctx.instructions = body.instructions
    if body.general_info is not None:
        ctx.general_info = body.general_info
    if body.enabled is not None:
        guild.general_ai_enabled = body.enabled

    ctx.context_version += 1
    await session.flush()

    return GeneralRulesOut(
        id=ctx.id,
        name=ctx.name,
        context_version=ctx.context_version,
        instructions=ctx.instructions,
        general_info=ctx.general_info,
        enabled=guild.general_ai_enabled,
    )


@router.get("/{context_id}", response_model=ContextOut)
async def get_guild_context(
    context_id: uuid.UUID,
    guild_id: int = Depends(require_guild_admin),
    session: AsyncSession = Depends(get_session),
):
    if await is_general_rules_context(session, guild_id, context_id):
        raise HTTPException(status_code=404, detail="Context not found")
    ctx = await get_context(session, context_id, guild_id)
    if not ctx:
        raise HTTPException(status_code=404, detail="Context not found")
    return ctx


@router.put("/{context_id}", response_model=ContextOut)
async def update_guild_context(
    context_id: uuid.UUID,
    body: ContextIn = Body(...),
    guild_id: int = Depends(require_guild_admin),
    session: AsyncSession = Depends(get_session),
):
    if await is_general_rules_context(session, guild_id, context_id):
        raise HTTPException(status_code=400, detail="Use PUT /contexts/general to edit General Rules")
    ctx = await update_context(
        session,
        context_id,
        guild_id,
        name=body.name,
        instructions=body.instructions,
        general_info=body.general_info,
    )
    if not ctx:
        raise HTTPException(status_code=404, detail="Context not found")
    return ctx


@router.delete("/{context_id}", status_code=204)
async def delete_guild_context(
    context_id: uuid.UUID,
    guild_id: int = Depends(require_guild_admin),
    session: AsyncSession = Depends(get_session),
):
    if await is_general_rules_context(session, guild_id, context_id):
        raise HTTPException(status_code=400, detail="General Rules cannot be deleted")
    deleted = await delete_context(session, context_id, guild_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Context not found")
