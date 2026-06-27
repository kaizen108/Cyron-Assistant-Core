"""AI Context CRUD API — /guilds/{guild_id}/contexts"""

import uuid
from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import get_session
from backend.dependencies import require_guild_admin
from backend.services.context_service import (
    create_context, delete_context, get_context, list_contexts, update_context,
    sync_context_panel_links,
)

router = APIRouter(prefix="/guilds/{guild_id}/contexts", tags=["contexts"])


class ContextIn(BaseModel):
    name: str
    instructions: str | None = None
    general_info: str | None = None
    linked_panel_ids: list[uuid.UUID] | None = None


class ContextOut(BaseModel):
    id: uuid.UUID
    guild_id: int
    name: str
    context_version: int
    instructions: str | None
    general_info: str | None


@router.get("", response_model=list[ContextOut])
async def list_guild_contexts(
    guild_id: int = Depends(require_guild_admin),
    session: AsyncSession = Depends(get_session),
):
    return await list_contexts(session, guild_id)


@router.post("", response_model=ContextOut, status_code=201)
async def create_guild_context(
    body: ContextIn = Body(...),
    guild_id: int = Depends(require_guild_admin),
    session: AsyncSession = Depends(get_session),
):
    return await create_context(session, guild_id, body.name, body.instructions, body.general_info)


@router.get("/{context_id}", response_model=ContextOut)
async def get_guild_context(
    context_id: uuid.UUID,
    guild_id: int = Depends(require_guild_admin),
    session: AsyncSession = Depends(get_session),
):
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
    ctx = await update_context(session, context_id, guild_id, name=body.name, instructions=body.instructions, general_info=body.general_info)
    if not ctx:
        raise HTTPException(status_code=404, detail="Context not found")
    if body.linked_panel_ids is not None:
        await sync_context_panel_links(session, guild_id, context_id, body.linked_panel_ids)
    return ctx


@router.delete("/{context_id}", status_code=204)
async def delete_guild_context(
    context_id: uuid.UUID,
    guild_id: int = Depends(require_guild_admin),
    session: AsyncSession = Depends(get_session),
):
    deleted = await delete_context(session, context_id, guild_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Context not found")
