"""AI discovery endpoints — server scan and transcript extract (Phase 1)."""

from fastapi import APIRouter, Body, Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import get_session
from backend.dependencies import get_redis, require_guild_admin
from backend.schemas.ai_discovery import (
    AiDiscoveryScanResult,
    ExtractInput,
    ExtractOutput,
)
from backend.services.ai_discovery_service import run_discovery_scan
from backend.services.ai_extraction_service import run_discovery_extract

router = APIRouter(prefix="/guilds/{guild_id}/ai/discovery", tags=["ai-discovery"])


@router.post("/scan", response_model=AiDiscoveryScanResult)
async def scan_guild_for_ai_setup(
    guild_id: int = Depends(require_guild_admin),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> AiDiscoveryScanResult:
    """Level 1–2 heuristic scan: channels, roles, panels, community features."""
    return await run_discovery_scan(session, redis, guild_id)


@router.post("/extract", response_model=ExtractOutput)
async def extract_discovery_patterns(
    body: ExtractInput = Body(...),
    guild_id: int = Depends(require_guild_admin),
    redis: Redis = Depends(get_redis),
) -> ExtractOutput:
    """Extract recurring problems from HTML transcripts and/or Discord channels."""
    return await run_discovery_extract(redis, guild_id, body)
