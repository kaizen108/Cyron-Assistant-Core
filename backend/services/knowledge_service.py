"""Knowledge service - CRUD, limits and similarity search."""

from __future__ import annotations

import uuid
import re
from typing import Any, List, Tuple

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import MIN_SIMILARITY_THRESHOLD
from backend.models.knowledge import Knowledge
from backend.services.knowledge_structurer import (
    embedding_text_for_chunk,
    deduplicate_enriched_chunks_against_guild,
    run_smart_ingestion_pipeline,
)
from backend.services.semantic_query_expansion import (
    expand_query_for_retrieval,
    expand_storage_embedding_text,
)
from backend.schemas.knowledge import KnowledgeCreate
from backend.utils.embeddings import embed_text, cosine_similarity

logger = structlog.get_logger(__name__)

# Total knowledge character limits per plan (title + content sum)
KNOWLEDGE_CHAR_LIMITS: dict[str, int] = {
    "free": 20_000,
    "pro": 50_000,
    "business": 100_000,
}

MAX_ENTRY_CHARS = 6_000
MAX_MAIN_CONTENT_CHARS = 2_200
MAX_ADDITIONAL_CONTEXT_CHARS = 900
MAX_BEHAVIOR_NOTES_CHARS = 500

SECTION_HEADING_ALIASES: dict[str, tuple[str, ...]] = {
    "main_content": ("main", "main content", "content", "details", "information"),
    "additional_context": (
        "additional",
        "additional context",
        "context",
        "extra context",
        "more info",
    ),
    "behavior_notes": ("behavior", "behavior notes", "notes", "note", "response style"),
}


class KnowledgeLimitError(Exception):
    """Base class for knowledge limit violations."""


class EntryTooLargeError(KnowledgeLimitError):
    """Raised when a single entry exceeds per-entry character limit."""


class GuildTotalLimitError(KnowledgeLimitError):
    """Raised when guild total knowledge characters exceed plan limit."""


class IngestionDuplicateError(KnowledgeLimitError):
    """Raised when all ingested chunks match existing knowledge (near-duplicate)."""


def _format_chunk_row_content(meta: dict[str, Any], body: str) -> str:
    lines: list[str] = []
    if meta.get("topic"):
        lines.append(f"Topic: {meta['topic']}")
    if meta.get("intent"):
        lines.append(f"Intent: {meta['intent']}")
    if meta.get("context"):
        lines.append(f"Context: {meta['context']}")
    if lines:
        return "\n".join(lines) + "\n\n" + body
    return body


def _normalize_whitespace(value: str) -> str:
    compact = value.replace("\r\n", "\n").replace("\r", "\n")
    compact = re.sub(r"[ \t]+", " ", compact)
    compact = re.sub(r"\n{3,}", "\n\n", compact)
    return compact.strip()


def _remove_redundant_lines(text: str) -> str:
    seen: set[str] = set()
    cleaned: list[str] = []
    for line in text.splitlines():
        normalized = line.strip().lower()
        if not normalized:
            cleaned.append("")
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        cleaned.append(line.strip())
    return "\n".join(cleaned).strip()


def _extract_heading_key(line: str) -> str | None:
    normalized = line.strip().strip("#").strip().strip(":").lower()
    for key, aliases in SECTION_HEADING_ALIASES.items():
        if normalized in aliases:
            return key
    return None


def _smart_parse_structured_content(
    title: str,
    content: str,
) -> tuple[str, str, str | None, str | None]:
    cleaned_title = _normalize_whitespace(title) or "Knowledge Entry"
    cleaned_content = _remove_redundant_lines(_normalize_whitespace(content))

    sections: dict[str, list[str]] = {
        "main_content": [],
        "additional_context": [],
        "behavior_notes": [],
    }
    current_key = "main_content"

    inline_patterns = {
        "additional_context": re.compile(r"^(additional|additional context|context)\s*:\s*", re.I),
        "behavior_notes": re.compile(r"^(behavior|behavior notes|note|notes)\s*:\s*", re.I),
    }

    for raw_line in cleaned_content.splitlines():
        line = raw_line.strip()
        if not line:
            sections[current_key].append("")
            continue

        heading_key = _extract_heading_key(line)
        if heading_key:
            current_key = heading_key
            continue

        switched = False
        for key, pattern in inline_patterns.items():
            if pattern.match(line):
                current_key = key
                line = pattern.sub("", line).strip()
                switched = True
                break

        if line:
            sections[current_key].append(line)
        elif switched:
            continue

    main_content = "\n".join(sections["main_content"]).strip()
    additional_context = "\n".join(sections["additional_context"]).strip() or None
    behavior_notes = "\n".join(sections["behavior_notes"]).strip() or None

    if not main_content:
        paras = [p.strip() for p in re.split(r"\n\s*\n", cleaned_content) if p.strip()]
        main_content = paras[0] if paras else cleaned_content
        additional_context = (
            "\n\n".join(paras[1:]).strip() if len(paras) > 1 and not additional_context else additional_context
        )

    return cleaned_title, main_content, additional_context, behavior_notes


def _truncate(value: str | None, limit: int) -> str | None:
    if not value:
        return None
    return value[:limit].strip()


def _compress_for_query(text: str, query: str, limit: int = 300) -> str:
    src = (text or "").strip()
    if not src:
        return ""
    if len(src) <= limit:
        return src
    q_terms = {t.lower() for t in re.findall(r"\w+", query or "") if len(t) >= 3}
    parts = re.split(r"(?<=[.!?])\s+|\n+", src)
    ranked: list[tuple[int, str]] = []
    for p in parts:
        s = p.strip()
        if not s:
            continue
        p_terms = {t.lower() for t in re.findall(r"\w+", s)}
        score = len(q_terms.intersection(p_terms))
        ranked.append((score, s))
    ranked.sort(key=lambda x: x[0], reverse=True)
    out = " ".join(x[1] for x in ranked[:2]).strip()
    if not out:
        out = src[:limit]
    return out[:limit].strip()


_COMPACT_KB_BUDGET = 400


def build_injection_chunk(
    knowledge: Knowledge,
    query: str,
    *,
    compact: bool = False,
    compact_borderline: bool = False,
) -> dict[str, str]:
    """Build minimal retrieval chunk with relevance-aware optional fields."""
    tp = knowledge.template_payload if isinstance(knowledge.template_payload, dict) else None
    if (knowledge.template_type or "") == "problem_solution" and tp:
        problem = str(tp.get("problem") or "").strip()
        solution = str(tp.get("solution") or "").strip() or (
            (knowledge.main_content or "").strip()
        )
        main_content = solution or (knowledge.main_content or knowledge.content or "").strip()
        # problem goes into behavior_notes (context for retrieval), NOT additional_context
        additional_context = (knowledge.additional_context or "").strip()
        behavior_notes = problem or (knowledge.behavior_notes or "").strip()
    else:
        _, parsed_main, parsed_additional, parsed_notes = _smart_parse_structured_content(
            knowledge.title,
            knowledge.content,
        )
        main_content = (knowledge.main_content or parsed_main or knowledge.content).strip()
        additional_context = (knowledge.additional_context or parsed_additional or "").strip()
        behavior_notes = (knowledge.behavior_notes or parsed_notes or "").strip()

    if compact:
        # v2.2: ultra-tight injection — one blob, ≤400 chars; no behavior_notes.
        if (knowledge.template_type or "") == "problem_solution" and tp:
            solution = str(tp.get("solution") or "").strip() or main_content
            sol = _compress_for_query(solution, query, limit=_COMPACT_KB_BUDGET)
            return {
                "title": (knowledge.title or "")[:60],
                "main_content": sol,
            }
        main_only = _compress_for_query(main_content, query, limit=_COMPACT_KB_BUDGET)
        if compact_borderline and additional_context:
            add = _compress_for_query(additional_context, query, limit=140)
            main_only = f"{main_only}\n{add}"[:_COMPACT_KB_BUDGET].strip()
        return {
            "title": (knowledge.title or "")[:60],
            "main_content": main_only,
        }

    chunk: dict[str, str] = {
        "title": knowledge.title,
        "main_content": _truncate(main_content, MAX_MAIN_CONTENT_CHARS) or "",
    }
    if additional_context:
        chunk["additional_context"] = _truncate(
            additional_context, MAX_ADDITIONAL_CONTEXT_CHARS
        ) or ""
    if behavior_notes:
        chunk["behavior_notes"] = _truncate(behavior_notes, MAX_BEHAVIOR_NOTES_CHARS) or ""
    return chunk


async def get_knowledge_count(session: AsyncSession, guild_id: int) -> int:
    """Count knowledge entries for guild."""
    result = await session.execute(
        select(func.count(Knowledge.id)).where(Knowledge.guild_id == guild_id)
    )
    return int(result.scalar_one())


async def get_knowledge_total_chars(session: AsyncSession, guild_id: int) -> int:
    """Get total characters (title + content) for all knowledge entries in a guild."""
    result = await session.execute(
        select(
            func.coalesce(func.sum(func.length(Knowledge.title) + func.length(Knowledge.content)), 0)
        ).where(Knowledge.guild_id == guild_id)
    )
    return int(result.scalar_one() or 0)


def _plan_total_limit(plan: str) -> int:
    plan_key = (plan or "free").lower()
    return KNOWLEDGE_CHAR_LIMITS.get(plan_key, KNOWLEDGE_CHAR_LIMITS["free"])


async def create_structured_knowledge(
    session: AsyncSession,
    guild_id: int,
    body: KnowledgeCreate,
    plan: str = "free",
) -> List[Knowledge]:
    """
    Persist dashboard-structured rows without the smart-ingestion pipeline.
    No raw_content — embeddings use title + main + template_payload expansion.
    """
    title = (body.title or "").strip() or "Knowledge Entry"
    template_type = (body.template_type or "general_knowledge").strip()
    main_body = (body.main_content or "").strip()
    content_display = (body.content or "").strip()
    if not main_body and content_display:
        main_body = _normalize_whitespace(content_display)
    if not content_display and main_body:
        content_display = main_body

    tp = body.template_payload if isinstance(body.template_payload, dict) else None
    additional_ctx = body.additional_context
    if template_type == "problem_solution" and tp:
        prob = str(tp.get("problem") or "").strip()
        sol = str(tp.get("solution") or "").strip()
        if sol:
            main_body = sol
        if prob and not (additional_ctx or "").strip():
            additional_ctx = prob
        if not content_display:
            content_display = f"## Problem\n{prob}\n\n## Solution\n{main_body}"

    if not main_body.strip():
        raise EntryTooLargeError("Structured knowledge requires main content (or solution).")

    entry_len = len(title) + len(content_display or main_body)
    if entry_len > MAX_ENTRY_CHARS:
        raise EntryTooLargeError(
            "Knowledge entry exceeds 6000 characters. Please shorten or split."
        )

    total_limit = _plan_total_limit(plan)
    current_total = await get_knowledge_total_chars(session, guild_id)
    new_chars = len(title) + len(content_display or main_body) + 32
    if current_total + new_chars > total_limit:
        raise GuildTotalLimitError(
            "Guild has reached total knowledge limit for your plan. Upgrade or remove entries."
        )

    emb_line = expand_storage_embedding_text(title, main_body, tp)
    if not emb_line.strip():
        emb_line = f"{title}\n{main_body}"

    dedup_chunk = {
        "text": main_body,
        "topic": title[:200],
        "intent": "inform",
        "context": "",
    }
    kept, _warnings = await deduplicate_enriched_chunks_against_guild(
        session, guild_id, [dedup_chunk]
    )
    if not kept:
        raise IngestionDuplicateError(
            "This content matches existing knowledge too closely (duplicate)."
        )

    vec = embed_text(emb_line)
    structured_chunks: list[dict[str, Any]] = [
        {
            "text": main_body,
            "topic": "",
            "intent": "inform",
            "context": "",
            "index": 0,
        }
    ]

    # Derive section from template_type if not explicitly provided
    section = (body.section or "").strip() or (
        "problems" if template_type == "problem_solution" else "knowledge"
    )

    # Entry count limit per plan
    from backend.schemas.plans import PLAN_LIMITS
    plan_limits = PLAN_LIMITS.get(plan.lower(), PLAN_LIMITS["free"])
    current_count = await get_knowledge_count(session, guild_id)
    if current_count >= plan_limits["knowledge_entries"]:
        raise GuildTotalLimitError(
            f"Knowledge entry limit reached ({plan_limits['knowledge_entries']} entries for {plan} plan). "
            "Upgrade or delete existing entries."
        )

    row = Knowledge(
        guild_id=guild_id,
        title=title,
        content=content_display or main_body,
        main_content=main_body,
        additional_context=additional_ctx,
        behavior_notes=body.behavior_notes,
        template_type=template_type,
        template_payload=tp,
        source=(body.source or "").strip() or None,
        raw_content=None,
        structured_chunks=structured_chunks,
        chunk_index=0,
        embedding=vec,
        ai_context_id=body.ai_context_id,
        section=section,
    )
    session.add(row)
    await session.flush()

    logger.info(
        "knowledge_created_structured",
        guild_id=guild_id,
        template_type=template_type,
    )
    return [row]


async def create_knowledge_with_chunking(
    session: AsyncSession,
    guild_id: int,
    title: str,
    content: str = "",
    main_content: str | None = None,
    additional_context: str | None = None,
    behavior_notes: str | None = None,
    plan: str = "free",
    ai_context_id=None,
    section: str | None = None,
) -> List[Knowledge]:
    """
    Create knowledge via smart ingestion (decompose → enrich → dedup) and persist rows.

    Returns list of created Knowledge rows (one per stored segment).
    Raises KnowledgeLimitError subclasses if limits are violated.
    """
    raw_text = "\n\n".join(
        p for p in (main_content or "", additional_context or "", behavior_notes or "", content) if p
    )
    entry_len = len(title) + len(raw_text)
    if entry_len > MAX_ENTRY_CHARS:
        raise EntryTooLargeError(
            "Knowledge entry exceeds 6000 characters. Please shorten or split."
        )

    plan_key = plan.lower()
    total_limit = _plan_total_limit(plan)

    current_total = await get_knowledge_total_chars(session, guild_id)

    # Entry count limit
    from backend.schemas.plans import PLAN_LIMITS
    plan_limits = PLAN_LIMITS.get(plan_key, PLAN_LIMITS["free"])
    current_count = await get_knowledge_count(session, guild_id)
    if current_count >= plan_limits["knowledge_entries"]:
        raise GuildTotalLimitError(
            f"Knowledge entry limit reached ({plan_limits['knowledge_entries']} entries for {plan} plan). "
            "Upgrade or delete existing entries."
        )

    logger.info("knowledge_ingest_invoke", guild_id=guild_id, entry_len=entry_len)

    pipeline = await run_smart_ingestion_pipeline(
        session,
        guild_id,
        title,
        content=content,
        main_content=main_content,
        additional_context=additional_context,
        behavior_notes=behavior_notes,
        exclude_knowledge_ids=None,
    )

    if not pipeline.structured_chunks:
        raise IngestionDuplicateError(
            "All segments matched existing knowledge too closely (duplicate). "
            "Edit the text or remove overlapping entries."
        )

    legacy = pipeline.structured_for_legacy
    cleaned_title = (legacy.get("title") or "Knowledge Entry").strip()
    main_body = (legacy.get("main_content") or "").strip()
    additional_context = legacy.get("additional_context")
    behavior_notes = legacy.get("behavior_notes")

    serializable_chunks: list[dict[str, Any]] = [
        dict(c) for c in pipeline.structured_chunks if isinstance(c, dict)
    ]

    # One dashboard row per logical chunk (pipeline caps at 2); no aggressive re-splitting.
    flat_parts: list[tuple[dict[str, Any], str]] = []
    for sc in serializable_chunks:
        text = (sc.get("text") or "").strip()
        if not text:
            continue
        flat_parts.append((sc, text))

    if not flat_parts:
        raise IngestionDuplicateError(
            "No storable segments after ingestion. Try different wording."
        )

    new_chars = sum(
        len(cleaned_title) + len(sp) + 32 for _, sp in flat_parts
    )

    if current_total + new_chars > total_limit:
        limits_str = {
            "free": "Free: 20k chars",
            "pro": "Pro: 50k chars",
            "business": "Business: 100k chars",
        }.get(plan_key, "Free: 20k chars")
        raise GuildTotalLimitError(
            f"Guild has reached total knowledge limit for your plan ({limits_str}). "
            "Upgrade or remove entries."
        )

    created: list[Knowledge] = []
    for idx, (meta, sp) in enumerate(flat_parts):
        row_title = cleaned_title if idx == 0 else f"{cleaned_title} – Part {idx + 1}"
        row_content = _format_chunk_row_content(meta, sp)
        clean_meta = {k: str(v) for k, v in meta.items() if k not in ("index", "text")}
        emb_in = embedding_text_for_chunk({**clean_meta, "text": sp})
        rich = expand_storage_embedding_text(row_title, sp, None)
        embedding = embed_text(f"{rich}\n\n{emb_in}".strip())
        knowledge = Knowledge(
            guild_id=guild_id,
            title=row_title,
            content=row_content,
            main_content=sp,
            additional_context=additional_context,
            behavior_notes=behavior_notes,
            template_type="general_knowledge",
            template_payload=None,
            source=None,
            raw_content=None,
            structured_chunks=serializable_chunks,
            chunk_index=idx,
            embedding=embedding,
            ai_context_id=ai_context_id,
            section=section or "knowledge",
        )
        session.add(knowledge)
        created.append(knowledge)

    await session.flush()

    logger.info(
        "knowledge_created_with_chunking",
        guild_id=guild_id,
        plan=plan_key,
        rows=len(created),
        entry_len=entry_len,
        new_chars=new_chars,
        total_after=current_total + new_chars,
        has_additional_context=bool(additional_context),
        has_behavior_notes=bool(behavior_notes),
        ingest_warnings=len(pipeline.warnings),
    )

    return created


async def get_knowledge_by_id(
    session: AsyncSession,
    knowledge_id: uuid.UUID,
    guild_id: int,
) -> Knowledge | None:
    """Get knowledge entry by ID and guild."""
    result = await session.execute(
        select(Knowledge).where(
            Knowledge.id == knowledge_id,
            Knowledge.guild_id == guild_id,
        )
    )
    return result.scalar_one_or_none()


async def list_knowledge(session: AsyncSession, guild_id: int) -> list[Knowledge]:
    """List all knowledge entries for guild."""
    result = await session.execute(
        select(Knowledge).where(Knowledge.guild_id == guild_id).order_by(Knowledge.created_at)
    )
    return list(result.scalars().all())


async def update_knowledge(
    session: AsyncSession,
    knowledge_id: uuid.UUID,
    guild_id: int,
    title: str | None = None,
    content: str | None = None,
    main_content: str | None = None,
    additional_context: str | None = None,
    behavior_notes: str | None = None,
    template_type: str | None = None,
    template_payload: dict[str, Any] | None = None,
    source: str | None = None,
    persist_mode: str | None = None,
    plan: str = "free",
    ai_context_id=None,
    section: str | None = None,
) -> Knowledge | None:
    """Update knowledge — smart pipeline or structured row (no duplicate raw_content)."""
    k = await get_knowledge_by_id(session, knowledge_id, guild_id)
    if not k:
        return None

    mode = persist_mode or "pipeline"
    if mode == "structured":
        new_title = (title if title is not None else k.title or "Knowledge Entry").strip()
        new_main = (main_content if main_content is not None else k.main_content or "").strip()
        new_content = (content if content is not None else k.content or "").strip()
        if not new_main and new_content:
            new_main = new_content
        if not new_content and new_main:
            new_content = new_main
        add_ctx = additional_context if additional_context is not None else k.additional_context
        beh = behavior_notes if behavior_notes is not None else k.behavior_notes
        tt = (template_type or k.template_type or "general_knowledge").strip()
        tp = template_payload if template_payload is not None else k.template_payload
        if not isinstance(tp, dict):
            tp = None
        src = source if source is not None else k.source

        if tt == "problem_solution" and tp:
            prob = str(tp.get("problem") or "").strip()
            sol = str(tp.get("solution") or "").strip()
            if sol:
                new_main = sol
            if prob and not (add_ctx or "").strip():
                add_ctx = prob
            if not new_content:
                new_content = f"## Problem\n{prob}\n\n## Solution\n{new_main}"

        if not new_main.strip():
            raise EntryTooLargeError("Structured update requires main content.")

        entry_len = len(new_title) + len(new_content or new_main)
        if entry_len > MAX_ENTRY_CHARS:
            raise EntryTooLargeError(
                "Knowledge entry exceeds 6000 characters. Please shorten or split."
            )

        current_total = await get_knowledge_total_chars(session, guild_id)
        old_len = len(k.title) + len(k.content)
        delta = entry_len - old_len
        total_limit = _plan_total_limit(plan)
        if current_total + delta > total_limit:
            raise GuildTotalLimitError(
                "Guild has reached total knowledge limit for your plan. Upgrade or remove entries."
            )

        emb_line = expand_storage_embedding_text(new_title, new_main, tp)
        if not emb_line.strip():
            emb_line = f"{new_title}\n{new_main}"

        k.title = new_title
        k.content = new_content or new_main
        k.main_content = new_main
        k.additional_context = add_ctx
        k.behavior_notes = beh
        k.template_type = tt
        k.template_payload = tp
        k.source = (src or "").strip() or None
        k.raw_content = None
        k.structured_chunks = [
            {
                "text": new_main,
                "topic": "",
                "intent": "inform",
                "context": "",
                "index": 0,
            }
        ]
        k.chunk_index = 0
        k.embedding = embed_text(emb_line)
        if ai_context_id is not None:
            k.ai_context_id = ai_context_id
        if section is not None:
            k.section = section
        await session.flush()
        return k

    incoming_title = title if title is not None else (k.title or "Knowledge Entry")
    incoming_content = content if content is not None else (k.content or "")

    logger.info("knowledge_ingest_update", guild_id=guild_id, knowledge_id=str(knowledge_id))

    pipeline = await run_smart_ingestion_pipeline(
        session,
        guild_id,
        incoming_title,
        content=incoming_content,
        main_content=main_content if main_content is not None else k.main_content,
        additional_context=additional_context if additional_context is not None else k.additional_context,
        behavior_notes=behavior_notes if behavior_notes is not None else k.behavior_notes,
        exclude_knowledge_ids={knowledge_id},
    )

    if not pipeline.structured_chunks:
        raise IngestionDuplicateError(
            "All segments matched existing knowledge too closely (duplicate). "
            "Edit the text or remove overlapping entries."
        )

    legacy = pipeline.structured_for_legacy
    new_title = (legacy.get("title") or "Knowledge Entry").strip()
    main_body = (legacy.get("main_content") or "").strip()
    additional_context = legacy.get("additional_context")
    behavior_notes = legacy.get("behavior_notes")

    new_content = "\n\n".join(
        part
        for part in (
            main_body,
            f"Additional Context:\n{additional_context}" if additional_context else "",
            f"Behavior Notes:\n{behavior_notes}" if behavior_notes else "",
        )
        if part
    )

    entry_len = len(new_title) + len(new_content)
    if entry_len > MAX_ENTRY_CHARS:
        raise EntryTooLargeError(
            "Knowledge entry exceeds 6000 characters. Please shorten or split."
        )

    current_total = await get_knowledge_total_chars(session, guild_id)
    old_len = len(k.title) + len(k.content)
    delta = entry_len - old_len

    total_limit = _plan_total_limit(plan)
    if current_total + delta > total_limit:
        raise GuildTotalLimitError(
            "Guild has reached total knowledge limit for your plan. Upgrade or remove entries."
        )

    emb_parts: list[str] = []
    for c in pipeline.structured_chunks:
        if not isinstance(c, dict):
            continue
        ct = str(c.get("text") or "")
        meta = {x: str(y) for x, y in c.items() if x not in ("index",)}
        meta["text"] = ct
        emb_parts.append(embedding_text_for_chunk(meta))
    combined_emb = "\n\n".join(emb_parts) if emb_parts else new_title + "\n" + main_body
    rich = expand_storage_embedding_text(new_title, main_body, None)
    combined_emb = f"{rich}\n\n{combined_emb}".strip()

    k.title = new_title
    k.content = new_content
    k.main_content = main_body
    k.additional_context = additional_context
    k.behavior_notes = behavior_notes
    k.template_type = template_type or k.template_type or "general_knowledge"
    if template_payload is not None:
        k.template_payload = template_payload
    if source is not None:
        k.source = (source or "").strip() or None
    k.raw_content = None
    k.structured_chunks = [dict(x) for x in pipeline.structured_chunks if isinstance(x, dict)]
    k.chunk_index = 0
    k.embedding = embed_text(combined_emb)
    await session.flush()
    return k


async def delete_knowledge(
    session: AsyncSession,
    knowledge_id: uuid.UUID,
    guild_id: int,
) -> bool:
    """Delete knowledge entry. Returns True if deleted."""
    k = await get_knowledge_by_id(session, knowledge_id, guild_id)
    if not k:
        return False
    await session.delete(k)
    await session.flush()
    return True


async def invalidate_guild_relay_cache(redis, guild_id: int) -> None:
    """Delete all relay response cache keys for a guild."""
    try:
        patterns = [
            f"relay:short:{guild_id}:*",
            f"relay:shortf:{guild_id}:*",
        ]
        for pattern in patterns:
            cursor = 0
            while True:
                cursor, keys = await redis.scan(cursor, match=pattern, count=100)
                if keys:
                    await redis.delete(*keys)
                if cursor == 0:
                    break
        logger.info("relay_cache_invalidated", guild_id=guild_id)
    except Exception as e:
        logger.warning("relay_cache_invalidation_failed", guild_id=guild_id, error=str(e))


async def search_knowledge(
    session: AsyncSession,
    guild_id: int,
    query: str,
    top_k: int = 4,
    min_score: float = MIN_SIMILARITY_THRESHOLD,
    embedding_query: str | None = None,
    *,
    ai_context_id=None,
    skip_expansion: bool = False,
    early_exit_similarity: float | None = None,
) -> Tuple[list[Knowledge], float]:
    """
    Search knowledge by cosine similarity.
    If ai_context_id is provided, restricts search to that context only.
    """
    import uuid as _uuid
    stmt = select(Knowledge).where(Knowledge.guild_id == guild_id)
    if ai_context_id is not None:
        if not isinstance(ai_context_id, _uuid.UUID):
            try:
                ai_context_id = _uuid.UUID(str(ai_context_id))
            except Exception:
                ai_context_id = None
    if ai_context_id is not None:
        stmt = stmt.where(Knowledge.ai_context_id == ai_context_id)

    result = await session.execute(stmt)
    all_k = list(result.scalars().all())
    if not all_k:
        return [], 0.0

    q1 = embed_text(query)
    q2: list[float] | None = None
    eq = (embedding_query or "").strip()
    if eq and eq != query.strip():
        q2 = embed_text(eq)
    if skip_expansion:
        q3 = None
    else:
        expanded_line = expand_query_for_retrieval(query, eq or query)
        q3 = embed_text(expanded_line) if expanded_line.strip() else None

    scored = []
    for k in all_k:
        if k.embedding:
            sim = cosine_similarity(q1, k.embedding)
            if q2 is not None:
                sim = max(sim, cosine_similarity(q2, k.embedding))
            if q3 is not None:
                sim = max(sim, cosine_similarity(q3, k.embedding))
            scored.append((sim, k))
    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        return [], 0.0

    top_raw_similarity = float(scored[0][0])
    if (
        early_exit_similarity is not None
        and scored
        and float(scored[0][0]) >= float(early_exit_similarity)
    ):
        s0, k0 = scored[0]
        if float(s0) >= min_score:
            logger.debug(
                "search_knowledge_early_exit",
                guild_id=guild_id,
                similarity=float(s0),
                threshold=float(early_exit_similarity),
            )
            return [k0], float(s0)

    logger.debug(
        "search_knowledge_scores",
        guild_id=guild_id,
        top_raw_similarity=top_raw_similarity,
        min_score=min_score,
        candidates=len(scored),
    )

    filtered = [(s, k) for s, k in scored if s >= min_score]
    if filtered:
        top_items = filtered[:top_k]
        top_sim = top_items[0][0]
        return [k for _, k in top_items], float(top_sim)

    return [], top_raw_similarity

