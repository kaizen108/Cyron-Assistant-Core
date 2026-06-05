"""AI-assisted knowledge structuring service — decomposition, enrichment, deduplication."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog
from litellm import acompletion
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import config
from backend.models.knowledge import Knowledge
from backend.utils.embeddings import cosine_similarity, embed_text

logger = structlog.get_logger(__name__)

STRUCTURE_MODEL = "gpt-4o-mini"


def _get_structure_model() -> tuple[str, str | None]:
    """Returns (model_name, api_key) — prefers Gemini if configured."""
    if config.gemini_api_key and config.gemini_model:
        return config.gemini_model, config.gemini_api_key
    return STRUCTURE_MODEL, config.openai_api_key
DEDUP_SIMILARITY_THRESHOLD = 0.92
# Coherent dashboard rows: at most 2 stored segments; prefer large meaningful blocks.
MAX_LOGICAL_CHUNKS: int = 2
MAX_UNIT_CHARS: int = 1100


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


def _heuristic_structure(
    title: str,
    content: str,
    main_content: str | None = None,
    additional_context: str | None = None,
    behavior_notes: str | None = None,
) -> dict[str, str | None]:
    cleaned_title = _normalize_whitespace(title) or "Knowledge Entry"
    composed = "\n\n".join(
        x.strip() for x in (main_content or "", additional_context or "", behavior_notes or "", content or "") if x and x.strip()
    )
    cleaned_content = _remove_redundant_lines(_normalize_whitespace(composed))

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

        normalized = line.strip("# ").strip(":").lower()
        if normalized in {"main", "main content", "content", "details", "information"}:
            current_key = "main_content"
            continue
        if normalized in {"additional", "additional context", "context", "extra context", "more info"}:
            current_key = "additional_context"
            continue
        if normalized in {"behavior", "behavior notes", "notes", "note", "response style"}:
            current_key = "behavior_notes"
            continue

        for key, pattern in inline_patterns.items():
            if pattern.match(line):
                current_key = key
                line = pattern.sub("", line).strip()
                break
        if line:
            sections[current_key].append(line)

    main = "\n".join(sections["main_content"]).strip()
    additional = "\n".join(sections["additional_context"]).strip() or None
    behavior = "\n".join(sections["behavior_notes"]).strip() or None

    if not main:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", cleaned_content) if p.strip()]
        main = paragraphs[0] if paragraphs else cleaned_content
        if not additional and len(paragraphs) > 1:
            additional = "\n\n".join(paragraphs[1:]).strip()

    return {
        "title": cleaned_title,
        "main_content": main,
        "additional_context": additional,
        "behavior_notes": behavior,
    }


def _extract_json_object(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


async def structure_knowledge_entry(
    title: str,
    content: str = "",
    main_content: str | None = None,
    additional_context: str | None = None,
    behavior_notes: str | None = None,
) -> dict[str, str | None]:
    """Structure input into title/main/additional/behavior with AI + heuristic fallback."""
    baseline = _heuristic_structure(
        title=title,
        content=content,
        main_content=main_content,
        additional_context=additional_context,
        behavior_notes=behavior_notes,
    )

    if not config.openai_api_key:
        return baseline

    user_payload = {
        "title": title,
        "content": content,
        "main_content": main_content,
        "additional_context": additional_context,
        "behavior_notes": behavior_notes,
    }

    prompt = (
        "Clean and structure this knowledge entry for a generic assistant. "
        "Return strict JSON only with keys: title, main_content, additional_context, behavior_notes. "
        "Keep text factual, deduplicated, and concise. "
        "main_content must capture core facts first. "
        "Preserve the original language of the source (do not translate unless asked). "
        "additional_context and behavior_notes are optional and can be null.\n\n"
        f"INPUT:\n{json.dumps(user_payload, ensure_ascii=True)}"
    )

    try:
        response = await acompletion(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a precise data structuring assistant. Output JSON only."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=450,
            temperature=0.0,
            api_key=config.openai_api_key,
        )
        content_text = response.choices[0].message.content if response and response.choices else ""
        parsed = _extract_json_object(content_text or "")
        if not parsed:
            return baseline
        title_out = _normalize_whitespace(str(parsed.get("title") or baseline["title"]))
        main_out = _normalize_whitespace(str(parsed.get("main_content") or baseline["main_content"] or ""))
        additional_out = _normalize_whitespace(str(parsed.get("additional_context") or "")).strip() or None
        behavior_out = _normalize_whitespace(str(parsed.get("behavior_notes") or "")).strip() or None
        return {
            "title": title_out or baseline["title"],
            "main_content": main_out or baseline["main_content"],
            "additional_context": additional_out,
            "behavior_notes": behavior_out,
        }
    except Exception as exc:
        logger.warning("knowledge_structurer_fallback", error=str(exc))
        return baseline


def _extract_json_array(text: str, key: str) -> list[Any] | None:
    obj = _extract_json_object(text or "")
    if not obj:
        return None
    v = obj.get(key)
    return v if isinstance(v, list) else None


def _find_break_near(text: str, target: int) -> int:
    """Prefer splitting at paragraph, then line, then sentence; fallback to target."""
    n = len(text)
    if n <= 1:
        return n
    lo = max(1, min(target, n - 1))
    search_range = range(lo, max(0, lo - 800), -1)
    for i in search_range:
        if i < n - 1 and text[i : i + 2] == "\n\n":
            return i + 2
    for i in search_range:
        if i < n and text[i] == "\n":
            return i + 1
    for sep in (". ", "! ", "? "):
        pos = text.rfind(sep, max(0, lo - 400), lo + 200)
        if pos != -1:
            return pos + len(sep)
    return lo


def split_into_at_most_two(text: str, max_chars: int = MAX_UNIT_CHARS) -> list[str]:
    """Split only when a single block exceeds max_chars; at most two parts; prefer natural breaks."""
    t = _normalize_whitespace(text)
    if not t:
        return []
    if len(t) <= max_chars:
        return [t]
    mid = len(t) // 2
    br = _find_break_near(t, mid)
    br = max(1, min(br, len(t) - 1))
    a, b = t[:br].strip(), t[br:].strip()
    if not a:
        return [b] if b else []
    if not b:
        return [a]
    return [a, b]


def collapse_units_to_max_two(
    units: list[str],
    *,
    max_chunks: int = MAX_LOGICAL_CHUNKS,
    max_chars: int = MAX_UNIT_CHARS,
) -> list[str]:
    """
    Merge over-fragmented segments into at most `max_chunks` coherent blocks.
    Respects paragraph boundaries when merging; only splits when a block exceeds max_chars.
    """
    cleaned = [_normalize_whitespace(str(u)) for u in units if str(u).strip()]
    if not cleaned:
        return []
    while len(cleaned) > max_chunks:
        best_i = 0
        best_score = len(cleaned[0]) + len(cleaned[1])
        for i in range(len(cleaned) - 1):
            s = len(cleaned[i]) + len(cleaned[i + 1])
            if s < best_score:
                best_score = s
                best_i = i
        merged = cleaned[best_i] + "\n\n" + cleaned[best_i + 1]
        cleaned = cleaned[:best_i] + [merged] + cleaned[best_i + 2 :]

    final: list[str] = []
    for block in cleaned:
        if len(block) <= max_chars:
            final.append(block)
        else:
            final.extend(split_into_at_most_two(block, max_chars))
    while len(final) > max_chunks:
        final = [final[0], "\n\n".join(final[1:])]
    return [x for x in final if x][:max_chunks]


def _heuristic_logical_units(raw: str, title: str) -> list[str]:
    """Paragraph-first segmentation; no sentence-level fragmentation."""
    cleaned = _normalize_whitespace(raw)
    if not cleaned:
        return [_normalize_whitespace(title)[:4000]]
    paras = [p.strip() for p in re.split(r"\n\s*\n+", cleaned) if p.strip()]
    if not paras:
        return collapse_units_to_max_two([cleaned])
    return collapse_units_to_max_two(paras)


async def decompose_raw_to_logical_units(raw_composite: str, title: str) -> list[str]:
    """
    Split into at most two coherent logical units for dashboard + retrieval.
    Prefer one unit; split only for length or clearly separate topics. Paragraph-aware.
    """
    raw_composite = _normalize_whitespace(raw_composite)
    if not raw_composite:
        return [_normalize_whitespace(title)]

    if not config.openai_api_key:
        units = _heuristic_logical_units(raw_composite, title)
        logger.info("ingest_decompose", path="heuristic", units=len(units))
        return units

    prompt = (
        f"Divide the text into at most {MAX_LOGICAL_CHUNKS} sections for a knowledge base dashboard. "
        "PREFER A SINGLE SECTION if the text is one topic (even several paragraphs). "
        f"Only use two sections if (a) there are clearly unrelated topics, OR (b) a single section would "
        f"exceed ~{MAX_UNIT_CHARS} characters. "
        "Respect paragraph and heading boundaries — never split mid-sentence for no reason. "
        "Do not produce many tiny fragments. Preserve original language. "
        f'Return strict JSON only: {{"units": ["...", ...]}} with 1–{MAX_LOGICAL_CHUNKS} strings.'
    )
    try:
        _model, _api_key = _get_structure_model()
        response = await acompletion(
            model=_model,
            messages=[
                {
                    "role": "system",
                    "content": "You output JSON only. No markdown.",
                },
                {"role": "user", "content": f"{prompt}\n\nTITLE:\n{title}\n\nTEXT:\n{raw_composite[:12000]}"},
            ],
            max_tokens=800,
            temperature=0.0,
            api_key=_api_key,
        )
        text = response.choices[0].message.content if response and response.choices else ""
        units = _extract_json_array(text or "", "units")
        if not units:
            parsed = _extract_json_object(text or "")
            if isinstance(parsed, list):
                units = parsed
        cleaned = [_normalize_whitespace(str(u)) for u in (units or []) if str(u).strip()]
        if not cleaned:
            cleaned = _heuristic_logical_units(raw_composite, title)
            logger.info("ingest_decompose", path="llm_empty_fallback", units=len(cleaned))
        else:
            cleaned = collapse_units_to_max_two(cleaned)
            logger.info("ingest_decompose", path="llm", units=len(cleaned))
        return cleaned
    except Exception as exc:
        logger.warning("ingest_decompose_failed", error=str(exc))
        out = _heuristic_logical_units(raw_composite, title)
        logger.info("ingest_decompose", path="exception_heuristic", units=len(out))
        return out


async def enrich_atomic_chunks(units: list[str], title: str) -> list[dict[str, str]]:
    """
    For each atomic unit add topic, intent, context metadata (gpt-4o-mini).
    """
    if not units:
        return []
    if not config.openai_api_key:
        return [
            {
                "text": u,
                "topic": "",
                "intent": "inform",
                "context": "",
            }
            for u in units
        ]

    payload = {"title": title, "units": units}
    prompt = (
        "For each unit, add metadata for RAG. Return strict JSON only:\n"
        '{"chunks":[{"text":"same as input unit text (verbatim)","topic":"short topical label",'
        '"intent":"user intent this answers (e.g. pricing, hours, policy)","context":"when to use this snippet"}], ...}\n'
        "Keep the same number and order of chunks as input units."
    )
    try:
        _model, _api_key = _get_structure_model()
        response = await acompletion(
            model=_model,
            messages=[
                {"role": "system", "content": "You output JSON only."},
                {"role": "user", "content": f"{prompt}\n\nINPUT:\n{json.dumps(payload, ensure_ascii=False)[:14000]}"},
            ],
            max_tokens=2000,
            temperature=0.0,
            api_key=_api_key,
        )
        text = response.choices[0].message.content if response and response.choices else ""
        parsed = _extract_json_object(text or "")
        chunks = (parsed or {}).get("chunks") if isinstance(parsed, dict) else None
        if not isinstance(chunks, list) or len(chunks) != len(units):
            logger.warning(
                "ingest_enrich_mismatch",
                expected=len(units),
                got=len(chunks) if isinstance(chunks, list) else 0,
            )
            return [
                {
                    "text": u,
                    "topic": "",
                    "intent": "inform",
                    "context": "",
                }
                for u in units
            ]
        out: list[dict[str, str]] = []
        for i, u in enumerate(units):
            c = chunks[i] if i < len(chunks) else {}
            if not isinstance(c, dict):
                c = {}
            out.append(
                {
                    "text": _normalize_whitespace(str(c.get("text") or u)),
                    "topic": _normalize_whitespace(str(c.get("topic") or ""))[:200],
                    "intent": _normalize_whitespace(str(c.get("intent") or "inform"))[:200],
                    "context": _normalize_whitespace(str(c.get("context") or ""))[:500],
                }
            )
        logger.info("ingest_enrich", path="llm", chunks=len(out))
        return out
    except Exception as exc:
        logger.warning("ingest_enrich_failed", error=str(exc))
        return [
            {"text": u, "topic": "", "intent": "inform", "context": ""}
            for u in units
        ]


def embedding_text_for_chunk(chunk: dict[str, str]) -> str:
    parts = [
        chunk.get("topic") or "",
        chunk.get("text") or "",
        chunk.get("intent") or "",
        chunk.get("context") or "",
    ]
    return _normalize_whitespace("\n".join(p for p in parts if p))


async def deduplicate_enriched_chunks_against_guild(
    session: AsyncSession,
    guild_id: int,
    enriched_chunks: list[dict[str, str]],
    *,
    exclude_knowledge_ids: set[uuid.UUID] | None = None,
) -> tuple[list[dict[str, str]], list[str]]:
    """
    Cosine similarity vs existing row embeddings in the same guild.
    Returns (chunks_to_keep, warning_messages). Drops chunks above threshold (flagged duplicates).
    """
    exclude = exclude_knowledge_ids or set()
    result = await session.execute(
        select(Knowledge).where(Knowledge.guild_id == guild_id)
    )
    existing = list(result.scalars().all())
    warnings: list[str] = []
    kept: list[dict[str, str]] = []
    batch_vecs: list[list[float]] = []

    for idx, chunk in enumerate(enriched_chunks):
        text = embedding_text_for_chunk(chunk)
        if not text:
            kept.append(chunk)
            continue
        new_vec = embed_text(text)
        intra_dup = False
        for bv in batch_vecs:
            if cosine_similarity(new_vec, bv) > DEDUP_SIMILARITY_THRESHOLD:
                msg = f"chunk[{idx}] near-duplicate within same ingestion batch"
                logger.warning("ingest_dedup_intra_batch", guild_id=guild_id, detail=msg)
                warnings.append(msg)
                intra_dup = True
                break
        if intra_dup:
            continue

        dup_of: str | None = None
        hit_sim = 0.0
        for row in existing:
            if row.id in exclude:
                continue
            if not row.embedding:
                continue
            sim = cosine_similarity(new_vec, row.embedding)
            if sim > DEDUP_SIMILARITY_THRESHOLD:
                dup_of = str(row.id)
                hit_sim = sim
                break
        if dup_of:
            msg = (
                f"chunk[{idx}] duplicate of existing knowledge id={dup_of} "
                f"(similarity {hit_sim:.3f} > {DEDUP_SIMILARITY_THRESHOLD})"
            )
            logger.warning("ingest_dedup_flag", guild_id=guild_id, detail=msg)
            warnings.append(msg)
            continue
        batch_vecs.append(new_vec)
        kept.append(chunk)

    logger.info(
        "ingest_dedup",
        guild_id=guild_id,
        input_chunks=len(enriched_chunks),
        kept=len(kept),
        dropped=len(enriched_chunks) - len(kept),
    )
    return kept, warnings


@dataclass
class IngestionPipelineResult:
    raw_content: str
    structured_chunks: list[dict[str, Any]]
    structured_for_legacy: dict[str, str | None]
    warnings: list[str] = field(default_factory=list)


async def run_smart_ingestion_pipeline(
    session: AsyncSession,
    guild_id: int,
    title: str,
    content: str = "",
    main_content: str | None = None,
    additional_context: str | None = None,
    behavior_notes: str | None = None,
    *,
    exclude_knowledge_ids: set[uuid.UUID] | None = None,
) -> IngestionPipelineResult:
    """
    Full pipeline: legacy structure pass → decompose → enrich → dedup.
    Returns data for persistence + legacy fields compatible with existing columns.
    """
    raw_content = _normalize_whitespace(
        "\n\n".join(
            p
            for p in (
                title,
                content or "",
                main_content or "",
                additional_context or "",
                behavior_notes or "",
            )
            if p
        )
    )
    logger.info("ingest_pipeline_start", guild_id=guild_id, raw_len=len(raw_content))

    legacy = await structure_knowledge_entry(
        title=title,
        content=content,
        main_content=main_content,
        additional_context=additional_context,
        behavior_notes=behavior_notes,
    )

    composite_for_decomp = raw_content or _normalize_whitespace(
        "\n\n".join(
            x
            for x in (
                legacy.get("title") or "",
                legacy.get("main_content") or "",
                legacy.get("additional_context") or "",
                legacy.get("behavior_notes") or "",
            )
            if x
        )
    )

    units = await decompose_raw_to_logical_units(composite_for_decomp, legacy.get("title") or title)
    enriched = await enrich_atomic_chunks(units, legacy.get("title") or title)

    kept, dedup_warnings = await deduplicate_enriched_chunks_against_guild(
        session,
        guild_id,
        enriched,
        exclude_knowledge_ids=exclude_knowledge_ids,
    )

    structured_chunks: list[dict[str, Any]] = []
    for i, ch in enumerate(kept):
        structured_chunks.append(
            {
                "text": ch.get("text", ""),
                "topic": ch.get("topic", ""),
                "intent": ch.get("intent", ""),
                "context": ch.get("context", ""),
                "index": i,
            }
        )

    main_joined = "\n\n".join(c.get("text", "") for c in kept if c.get("text"))
    if not main_joined.strip():
        main_joined = legacy.get("main_content") or ""

    structured_for_legacy = {
        "title": legacy.get("title"),
        "main_content": main_joined,
        "additional_context": legacy.get("additional_context"),
        "behavior_notes": legacy.get("behavior_notes"),
    }

    logger.info(
        "ingest_pipeline_done",
        guild_id=guild_id,
        atomic=len(structured_chunks),
        warnings=len(dedup_warnings),
    )

    return IngestionPipelineResult(
        raw_content=raw_content,
        structured_chunks=structured_chunks,
        structured_for_legacy=structured_for_legacy,
        warnings=dedup_warnings,
    )


# Supported dashboard templates (extend DB enum / UI together).
TEMPLATE_TYPES_KNOWN = frozenset(
    {
        "general_knowledge",
        "problem_solution",
        "product_info",
        "behavior_rule",
    }
)


async def auto_format_knowledge(
    raw_text: str,
    template_type: str,
    title_hint: str = "",
) -> dict[str, Any]:
    """
    Turn noisy pasted text into retrieval-optimized structured fields.
    Used by POST /knowledge/format — caller persists via structured ingest.
    """
    raw = _normalize_whitespace(raw_text or "")
    if not raw:
        return {
            "title": (title_hint or "Knowledge Entry").strip() or "Knowledge Entry",
            "template_type": template_type,
            "main_content": "",
            "additional_context": None,
            "behavior_notes": None,
            "template_payload": None,
            "content_markdown": "",
        }

    tt = (template_type or "problem_solution").strip()
    if tt not in TEMPLATE_TYPES_KNOWN:
        tt = "problem_solution"

    if not config.openai_api_key:
        if tt == "problem_solution":
            title = (title_hint or "Support topic").strip() or "Support topic"
            return {
                "title": title,
                "template_type": "problem_solution",
                "main_content": raw[:2200],
                "additional_context": None,
                "behavior_notes": None,
                "template_payload": {"problem": "Customer question (refine manually)", "solution": raw[:2200], "keywords": [], "related_terms": []},
                "content_markdown": f"## Problem\nCustomer question (refine manually)\n\n## Solution\n{raw[:2200]}",
            }
        return {
            "title": (title_hint or "Knowledge Entry").strip() or "Knowledge Entry",
            "template_type": "general_knowledge",
            "main_content": raw[:4000],
            "additional_context": None,
            "behavior_notes": None,
            "template_payload": None,
            "content_markdown": raw[:4000],
        }

    if tt == "problem_solution":
        prompt = (
            "You are a support knowledge engineer building a retrieval-optimized knowledge base for a Discord ticket bot.\n\n"
            "From the RAW text, extract:\n"
            "1. title: short dashboard label (3-6 words, same language as source)\n"
            "2. problem: a natural customer-style question that this answers (same language as source, 1-2 sentences)\n"
            "3. solution: the complete, factual answer the support agent would send (same language, all relevant details — prices, steps, durations, links)\n"
            "4. keywords: 3-8 short terms a user might type to find this (same language + English variants)\n"
            "5. related_terms: 2-5 synonyms or related phrases that should also match this entry\n"
            "6. behavior_notes: optional — how the bot should present this answer (tone, caveats, when to escalate). null if not needed.\n\n"
            "Rules:\n"
            "- Never invent facts not present in the source text\n"
            "- Preserve all numbers, prices, dates exactly\n"
            "- solution must be self-contained (readable without the problem)\n"
            "- keywords and related_terms dramatically improve retrieval — be thorough\n\n"
            "Return strict JSON only:\n"
            '{"title":"...","problem":"...","solution":"...","keywords":["..."],"related_terms":["..."],"behavior_notes":null|"..."}'
        )
    elif tt == "general_knowledge":
        prompt = (
            "You are a support knowledge engineer building a retrieval-optimized knowledge base.\n\n"
            "From the RAW text, extract:\n"
            "1. title: short dashboard label (same language as source)\n"
            "2. main_content: core facts, complete and self-contained\n"
            "3. additional_context: supplementary details, examples, or edge cases (null if none)\n"
            "4. behavior_notes: how the bot should use this info — tone, caveats, escalation triggers (null if none)\n"
            "5. keywords: 3-8 terms users might search for (same language + English)\n\n"
            "Rules: preserve source language, never invent facts, keep all numbers/prices exact.\n\n"
            "Return strict JSON only:\n"
            '{"title":"...","main_content":"...","additional_context":null|"...","behavior_notes":null|"...","keywords":["..."]}'
        )
    elif tt == "product_info":
        prompt = (
            "Extract product facts for a support knowledge base. Return strict JSON:\n"
            '{"title":"...","main_content":"complete product summary","template_payload":{"product_name":"","summary":"","details":"","price":"","availability":""},"keywords":["..."]}.\n'
            "Only facts from the text. Preserve source language."
        )
    else:  # behavior_rule
        prompt = (
            "Extract behavior/policy rules for a support bot. Return strict JSON:\n"
            '{"title":"...","main_content":"what the bot should do","template_payload":{"rule":"","conditions":"","exceptions":""},"keywords":["..."]}.\n'
            "Preserve source language."
        )

    try:
        _model, _api_key = _get_structure_model()
        response = await acompletion(
            model=_model,
            messages=[
                {"role": "system", "content": "You output JSON only. No markdown fences. No extra text."},
                {
                    "role": "user",
                    "content": f"{prompt}\n\nTITLE_HINT:\n{title_hint}\n\nRAW:\n{raw[:14000]}",
                },
            ],
            max_tokens=1200,
            temperature=0.0,
            api_key=_api_key,
        )
        text = response.choices[0].message.content if response and response.choices else ""
        parsed = _extract_json_object(text or "")
        if not isinstance(parsed, dict):
            parsed = {}
    except Exception as exc:
        logger.warning("auto_format_failed", error=str(exc))
        parsed = {}

    if tt == "problem_solution":
        title = _normalize_whitespace(str(parsed.get("title") or title_hint or "Support topic")) or "Support topic"
        problem = _normalize_whitespace(str(parsed.get("problem") or ""))
        solution = _normalize_whitespace(str(parsed.get("solution") or ""))
        keywords = parsed.get("keywords") if isinstance(parsed.get("keywords"), list) else []
        related_terms = parsed.get("related_terms") if isinstance(parsed.get("related_terms"), list) else []
        behavior_notes = _normalize_whitespace(str(parsed.get("behavior_notes") or "")) or None

        if not solution:
            solution = raw[:2200]
        if not problem:
            problem = title_hint or title

        # Build retrieval-rich behavior_notes that includes keywords + related terms
        retrieval_hints: list[str] = []
        if keywords:
            retrieval_hints.append("Keywords: " + ", ".join(str(k) for k in keywords[:8]))
        if related_terms:
            retrieval_hints.append("Related: " + ", ".join(str(r) for r in related_terms[:5]))
        if behavior_notes:
            retrieval_hints.append(behavior_notes)
        final_behavior_notes = "\n".join(retrieval_hints) or None

        md = f"## Problem\n{problem}\n\n## Solution\n{solution}"
        if final_behavior_notes:
            md += f"\n\n## Notes\n{final_behavior_notes}"

        return {
            "title": title,
            "template_type": "problem_solution",
            "main_content": solution,
            "additional_context": None,
            "behavior_notes": final_behavior_notes,
            "template_payload": {
                "problem": problem,
                "solution": solution,
                "keywords": keywords,
                "related_terms": related_terms,
            },
            "content_markdown": md,
        }

    if tt == "general_knowledge":
        title = _normalize_whitespace(str(parsed.get("title") or title_hint or "Knowledge Entry")) or "Knowledge Entry"
        main_c = _normalize_whitespace(str(parsed.get("main_content") or raw))
        add_c = parsed.get("additional_context")
        beh = parsed.get("behavior_notes")
        keywords = parsed.get("keywords") if isinstance(parsed.get("keywords"), list) else []
        add_s = _normalize_whitespace(str(add_c)) if add_c else None
        beh_s = _normalize_whitespace(str(beh)) if beh else None

        # Append keywords to behavior_notes for retrieval
        if keywords:
            kw_line = "Keywords: " + ", ".join(str(k) for k in keywords[:8])
            beh_s = (beh_s + "\n" + kw_line) if beh_s else kw_line

        parts = [main_c]
        if add_s:
            parts.append(f"Additional Context:\n{add_s}")
        if beh_s:
            parts.append(f"Behavior Notes:\n{beh_s}")
        return {
            "title": title,
            "template_type": "general_knowledge",
            "main_content": main_c,
            "additional_context": add_s,
            "behavior_notes": beh_s,
            "template_payload": None,
            "content_markdown": "\n\n".join(parts),
        }

    # product_info / behavior_rule
    title = _normalize_whitespace(str(parsed.get("title") or title_hint or "Entry"))
    main_c = _normalize_whitespace(str(parsed.get("main_content") or raw))
    tp = parsed.get("template_payload")
    if not isinstance(tp, dict):
        tp = {}
    keywords = parsed.get("keywords") if isinstance(parsed.get("keywords"), list) else []
    if keywords:
        tp["keywords"] = keywords
    return {
        "title": title,
        "template_type": tt,
        "main_content": main_c,
        "additional_context": None,
        "behavior_notes": None,
        "template_payload": tp,
        "content_markdown": main_c,
    }
