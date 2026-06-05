"""Knowledge CRUD API - /guilds/{guild_id}/knowledge."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Body
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import get_session
from backend.dependencies import require_guild_admin, get_redis
from backend.schemas.knowledge import (
    KnowledgeCreate,
    KnowledgeFormatRequest,
    KnowledgeFormatResponse,
    KnowledgeUpdate,
    KnowledgeResponse,
)
from backend.services.guild_service import get_guild
from backend.services.knowledge_structurer import auto_format_knowledge
from backend.services.knowledge_service import (
    GuildTotalLimitError,
    EntryTooLargeError,
    IngestionDuplicateError,
    create_knowledge_with_chunking,
    create_structured_knowledge,
    get_knowledge_by_id,
    list_knowledge,
    update_knowledge,
    delete_knowledge,
    invalidate_guild_relay_cache,
)
from backend.services.context_service import bump_context_version

router = APIRouter(prefix="/guilds/{guild_id}/knowledge", tags=["knowledge"])


def _knowledge_response_row(k) -> KnowledgeResponse:
    return KnowledgeResponse(
        id=k.id,
        guild_id=k.guild_id,
        title=k.title,
        content=k.content,
        main_content=k.main_content,
        additional_context=k.additional_context,
        behavior_notes=k.behavior_notes,
        template_type=getattr(k, "template_type", None) or "general_knowledge",
        template_payload=k.template_payload if isinstance(k.template_payload, dict) else None,
        source=k.source,
        raw_content=k.raw_content,
        structured_chunks=k.structured_chunks,
        chunk_index=k.chunk_index,
        ai_context_id=k.ai_context_id,
        section=k.section,
        created_at=k.created_at.isoformat() if k.created_at else "",
    )


@router.get("", response_model=list[KnowledgeResponse])
async def list_guild_knowledge(
    guild_id: int = Depends(require_guild_admin),
    session: AsyncSession = Depends(get_session),
):
    """List all knowledge entries for a guild."""
    guild = await get_guild(session, guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    items = await list_knowledge(session, guild_id)
    return [_knowledge_response_row(k) for k in items]


@router.post("/format", response_model=KnowledgeFormatResponse)
async def format_knowledge_draft(
    guild_id: int = Depends(require_guild_admin),
    body: KnowledgeFormatRequest = Body(...),
    session: AsyncSession = Depends(get_session),
):
    """AUTO FORMAT — structure raw text for a template (no DB write)."""
    guild = await get_guild(session, guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    out = await auto_format_knowledge(
        body.raw_text,
        body.template_type,
        title_hint=body.title_hint or "",
    )
    return KnowledgeFormatResponse(
        title=out["title"],
        template_type=out["template_type"],
        main_content=out["main_content"],
        additional_context=out.get("additional_context"),
        behavior_notes=out.get("behavior_notes"),
        template_payload=out.get("template_payload"),
        content_markdown=out.get("content_markdown") or out["main_content"],
    )


@router.post("", response_model=KnowledgeResponse)
async def create_guild_knowledge(
    guild_id: int = Depends(require_guild_admin),
    body: KnowledgeCreate = Body(...),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
):
    """Create knowledge entry with validation and chunking or structured ingest."""
    guild = await get_guild(session, guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    try:
        if body.persist_mode == "structured":
            created = await create_structured_knowledge(
                session, guild_id, body, plan=guild.plan or "free"
            )
        else:
            created = await create_knowledge_with_chunking(
                session,
                guild_id,
                body.title,
                body.content,
                main_content=body.main_content,
                additional_context=body.additional_context,
                behavior_notes=body.behavior_notes,
                plan=guild.plan,
                ai_context_id=body.ai_context_id,
                section=body.section,
            )
    except EntryTooLargeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except GuildTotalLimitError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except IngestionDuplicateError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    await invalidate_guild_relay_cache(redis, guild_id)
    knowledge = created[0]
    if knowledge.ai_context_id:
        await bump_context_version(session, knowledge.ai_context_id)
    return _knowledge_response_row(knowledge)


@router.get("/{knowledge_id}", response_model=KnowledgeResponse)
async def get_guild_knowledge(
    knowledge_id: UUID,
    guild_id: int = Depends(require_guild_admin),
    session: AsyncSession = Depends(get_session),
):
    """Get knowledge entry by ID."""
    guild = await get_guild(session, guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    knowledge = await get_knowledge_by_id(session, knowledge_id, guild_id)
    if not knowledge:
        raise HTTPException(status_code=404, detail="Knowledge not found")
    return _knowledge_response_row(knowledge)


@router.put("/{knowledge_id}", response_model=KnowledgeResponse)
async def update_guild_knowledge(
    knowledge_id: UUID,
    body: KnowledgeUpdate = Body(...),
    guild_id: int = Depends(require_guild_admin),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
):
    """Update knowledge entry with validation."""
    guild = await get_guild(session, guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    try:
        knowledge = await update_knowledge(
            session,
            knowledge_id,
            guild_id,
            title=body.title,
            content=body.content,
            main_content=body.main_content,
            additional_context=body.additional_context,
            behavior_notes=body.behavior_notes,
            template_type=body.template_type,
            template_payload=body.template_payload,
            source=body.source,
            persist_mode=body.persist_mode,
            plan=guild.plan or "free",
            ai_context_id=body.ai_context_id,
            section=body.section,
        )
    except EntryTooLargeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except GuildTotalLimitError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except IngestionDuplicateError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    if not knowledge:
        raise HTTPException(status_code=404, detail="Knowledge not found")

    await invalidate_guild_relay_cache(redis, guild_id)
    if knowledge.ai_context_id:
        await bump_context_version(session, knowledge.ai_context_id)
    return _knowledge_response_row(knowledge)


@router.delete("/{knowledge_id}", status_code=204)
async def delete_guild_knowledge(
    knowledge_id: UUID,
    guild_id: int = Depends(require_guild_admin),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
):
    """Delete knowledge entry."""
    guild = await get_guild(session, guild_id)
    if not guild:
        raise HTTPException(status_code=404, detail="Guild not found")

    # Load before delete to get ai_context_id
    entry = await get_knowledge_by_id(session, knowledge_id, guild_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Knowledge not found")
    ctx_id = entry.ai_context_id

    deleted = await delete_knowledge(session, knowledge_id, guild_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Knowledge not found")

    await invalidate_guild_relay_cache(redis, guild_id)
    if ctx_id:
        await bump_context_version(session, ctx_id)
