"""Level 1–2 heuristics for AI discovery scan (Phase 1)."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.guild import Guild
from backend.models.ticket_panel import TicketPanel
from backend.schemas.ai_discovery import (
    AiDiscoveryScanResult,
    CategoryScores,
    ClassifiedChannel,
    ClassifiedChannels,
    PanelSummary,
    RoleCandidate,
    VoiceTextRatio,
)

# Category labels for UI
CATEGORY_LABELS = {
    "selling": "Selling / Reselling",
    "saas": "Product / SaaS",
    "community": "Community",
    "other": "Other / Custom",
}

# --- Pattern groups (multilingual it/en per spec) ---
_PAT = {
    "selling": re.compile(
        r"prezzi|listino|prices|pricing|shop|store|drop|buy|purchase|robux|"
        r"vouch|feedback|recensioni|reviews|testimonials|sell|resell|"
        r"🛒|💰|💎|merchant|checkout|order",
        re.I,
    ),
    "community": re.compile(
        r"regolamento|regole|rules|welcome|community|general|chat|lounge|"
        r"meme|social|verify|introductions|"
        r"🎮|🎯|👥",
        re.I,
    ),
    "saas": re.compile(
        r"bug|changelog|status|updates|docs|api|dev|support|ticket|"
        r"roadmap|feature|saas|software|product|"
        r"🐛|⚙️|💻",
        re.I,
    ),
    "knowledge": re.compile(
        r"faq|come-acquistare|how-to-buy|info|help|guide|wiki|kb|"
        r"knowledge|documentation",
        re.I,
    ),
    "announcements": re.compile(r"annunci|announcements|news|updates|broadcast", re.I),
    "partnership": re.compile(r"partnership|partner|collab|affiliate|sponsor", re.I),
    "transcript": re.compile(r"transcript|logs|archivio|archive|ticket-log", re.I),
    "ticket_history": re.compile(r"^ticket-\d+$", re.I),
}

_STAFF_ROLE = re.compile(r"staff|support|admin|mod|moderator|helper|manager|owner", re.I)


def _channels_key(guild_id: int) -> str:
    return f"bot:guild:{guild_id}:channels"


def _discovery_key(guild_id: int) -> str:
    return f"bot:guild:{guild_id}:discovery"


def _score_text(text: str, weight: float = 1.0) -> dict[str, float]:
    scores = {"selling": 0.0, "saas": 0.0, "community": 0.0, "other": 0.0}
    if not text:
        return scores
    for cat in ("selling", "saas", "community"):
        if _PAT[cat].search(text):
            scores[cat] += 2.0 * weight
    # Weak other signal for generic support servers
    if _PAT["knowledge"].search(text):
        scores["community"] += 0.5 * weight
        scores["saas"] += 0.3 * weight
    return scores


def _merge_scores(base: dict[str, float], extra: dict[str, float]) -> None:
    for k, v in extra.items():
        base[k] = base.get(k, 0.0) + v


def _classify_channel(ch: dict[str, Any]) -> tuple[list[str], str | None]:
    name = ch.get("name") or ""
    cat = ch.get("category_name") or ""
    combined = f"{cat} {name}"
    tags: list[str] = []
    reason_parts: list[str] = []

    for tag in ("knowledge", "announcements", "partnership", "transcript", "selling"):
        if _PAT[tag].search(combined):
            tags.append(tag)
            reason_parts.append(tag)

    if _PAT["ticket_history"].search(name):
        tags.append("ticket_history")
        reason_parts.append("closed ticket channel pattern")

    reason = f"Matched: {', '.join(reason_parts)}" if reason_parts else None
    return tags, reason


def _confidence_tier(conf: float) -> str:
    if conf >= 0.7:
        return "high"
    if conf >= 0.4:
        return "medium"
    return "low"


def _build_description_draft(
    guild_name: str,
    description: str,
    panels: list[TicketPanel],
    category: str,
) -> str:
    parts: list[str] = []
    if description:
        parts.append(description.strip())
    elif guild_name:
        label = CATEGORY_LABELS.get(category, category)
        parts.append(f"{guild_name} — detected as a {label} server.")
    if panels:
        names = ", ".join(p.name for p in panels[:3])
        parts.append(f"Support panels configured: {names}.")
    return " ".join(parts).strip()[:500]


async def run_discovery_scan(
    session: AsyncSession,
    redis: Redis,
    guild_id: int,
) -> AiDiscoveryScanResult:
    """Full Level 1–2 heuristic scan."""
    result = await session.execute(select(Guild).where(Guild.id == guild_id))
    guild = result.scalar_one_or_none()
    guild_name = (guild.name if guild else "") or ""

    raw_discovery = await redis.get(_discovery_key(guild_id))
    if not raw_discovery:
        # Ask bot to refresh on next poll
        await redis.set(f"bot:guild:{guild_id}:sync_channels", "1", ex=300)

    discovery: dict[str, Any] = json.loads(raw_discovery) if raw_discovery else {}

    raw_channels = await redis.get(_channels_key(guild_id))
    channels: list[dict[str, Any]] = discovery.get("channels") or (
        json.loads(raw_channels) if raw_channels else []
    )

    # Normalize legacy channel cache {id, name} → full shape
    for ch in channels:
        ch.setdefault("type", "text")
        ch.setdefault("category_name", None)

    scores: dict[str, float] = {"selling": 0.0, "saas": 0.0, "community": 0.0, "other": 0.0}
    rationale: list[str] = []
    signals: list[str] = []
    classified = ClassifiedChannels()
    partnership_detected = False

    # Server name & description
    server_desc = (discovery.get("description") or "").strip()
    if guild_name:
        name_scores = _score_text(guild_name, weight=1.5)
        _merge_scores(scores, name_scores)
        if any(name_scores[c] > 0 for c in ("selling", "saas", "community")):
            rationale.append(f"Server name “{guild_name}” matches category keywords")
            signals.append(f"Server name: {guild_name}")

    if server_desc:
        desc_scores = _score_text(server_desc, weight=1.2)
        _merge_scores(scores, desc_scores)
        if any(desc_scores[c] > 0 for c in ("selling", "saas", "community")):
            rationale.append("Server description contains category signals")

    # Community server feature
    is_community = bool(discovery.get("is_community"))
    features = discovery.get("features") or []
    if is_community or "COMMUNITY" in features:
        scores["community"] += 3.0
        rationale.append("Discord Community server features detected")
        signals.append("Discord Community enabled")

    # Voice / text ratio
    text_count = int(discovery.get("text_channel_count") or 0)
    voice_count = int(discovery.get("voice_channel_count") or 0)
    if not text_count and not voice_count:
        text_count = sum(1 for c in channels if c.get("type", "text") == "text")
        voice_count = sum(1 for c in channels if c.get("type") == "voice")

    ratio = VoiceTextRatio(text=text_count, voice=voice_count)
    if text_count > 0 and voice_count / max(text_count, 1) >= 1.5:
        ratio.ratio_voice_heavy = True
        scores["community"] += 2.5
        rationale.append(
            f"Voice-heavy server ({voice_count} voice / {text_count} text channels) — community signal"
        )

    # Categories (stronger weight than loose channels)
    for cat in discovery.get("categories") or []:
        cat_name = cat.get("name") or ""
        cat_scores = _score_text(cat_name, weight=2.0)
        _merge_scores(scores, cat_scores)
        if any(cat_scores[c] > 0 for c in ("selling", "saas", "community")):
            rationale.append(f"Category “{cat_name}” suggests server type")
            signals.append(f"Category: {cat_name}")

    # Channels
    for ch in channels:
        name = ch.get("name") or ""
        cat_name = ch.get("category_name") or ""
        combined = f"{cat_name} {name}"

        ch_scores = _score_text(combined, weight=1.0)
        _merge_scores(scores, ch_scores)

        tags, reason = _classify_channel(ch)
        cc = ClassifiedChannel(
            id=str(ch.get("id", "")),
            name=name,
            category_name=cat_name or None,
            tags=tags,
            reason=reason,
        )
        if "knowledge" in tags:
            classified.knowledge.append(cc)
        if "announcements" in tags:
            classified.announcements.append(cc)
        if "transcript" in tags:
            classified.transcript.append(cc)
        if "ticket_history" in tags:
            classified.ticket_history.append(cc)
        if "partnership" in tags:
            classified.partnership.append(cc)
            partnership_detected = True
        if "selling" in tags:
            classified.selling.append(cc)

        if _PAT["selling"].search(combined):
            signals.append(f"Channel #{name} → selling/commerce")
        elif _PAT["saas"].search(combined):
            signals.append(f"Channel #{name} → SaaS/support")

    # Roles → escalation candidates
    role_candidates: list[RoleCandidate] = []
    roles = discovery.get("roles") or []
    for role in sorted(roles, key=lambda r: r.get("position", 0), reverse=True):
        rname = role.get("name") or ""
        if not _STAFF_ROLE.search(rname):
            continue
        score = 0.5
        if role.get("is_admin"):
            score += 0.3
        if role.get("manage_guild") or role.get("manage_channels"):
            score += 0.2
        role_candidates.append(
            RoleCandidate(
                id=str(role.get("id", "")),
                name=rname,
                score=round(min(score, 1.0), 2),
                reason="Staff/support role name pattern",
            )
        )
    role_candidates.sort(key=lambda r: r.score, reverse=True)

    if role_candidates:
        rationale.append(
            f"Staff roles found: {', '.join(r.name for r in role_candidates[:3])}"
        )

    # Level 2 — panels
    panels_result = await session.execute(
        select(TicketPanel).where(TicketPanel.guild_id == guild_id)
    )
    panels = list(panels_result.scalars().all())
    panel_summaries: list[PanelSummary] = []

    for panel in panels:
        panel_text = f"{panel.name} {panel.button_text or ''} {panel.button_emoji or ''}"
        p_scores = _score_text(panel_text, weight=2.5)
        _merge_scores(scores, p_scores)

        hint = None
        if p_scores["selling"] >= p_scores["saas"] and p_scores["selling"] >= p_scores["community"]:
            hint = "selling"
        elif p_scores["saas"] >= p_scores["community"]:
            hint = "saas"
        elif p_scores["community"] > 0:
            hint = "community"

        panel_summaries.append(
            PanelSummary(
                id=str(panel.id),
                name=panel.name,
                button_text=panel.button_text,
                button_emoji=panel.button_emoji,
                support_hours_enabled=bool(panel.support_hours_enabled),
                category_hint=hint,
            )
        )
        if hint:
            rationale.append(f"Panel “{panel.name}” suggests {CATEGORY_LABELS.get(hint, hint)}")
            signals.append(f"Panel: {panel.name}")

    # Determine category
    total_signal = sum(scores.values())
    if total_signal < 1.0 and not panels and not channels:
        proposed = "other"
        confidence = 0.2
        summary = (
            "Not enough data yet — invite the bot and sync channels, or configure General Rules manually."
        )
        rationale.append("Insufficient channel, role, and panel data")
    else:
        proposed = max(scores, key=scores.get)
        if scores[proposed] < 0.5:
            proposed = "other"
            scores["other"] = max(scores["other"], 1.0)

        best = scores[proposed]
        confidence = min(0.95, best / max(total_signal, 4.0))
        if panels:
            confidence = min(0.95, confidence + 0.1)
        if is_community and proposed == "community":
            confidence = min(0.95, confidence + 0.05)

        label = CATEGORY_LABELS.get(proposed, proposed)
        summary = (
            f"Likely a {label} server ({int(confidence * 100)}% confidence) based on "
            f"{len(channels)} channels, {len(roles)} roles, and {len(panels)} panels."
        )

    tier = _confidence_tier(confidence)
    if tier == "low":
        rationale.append("Low confidence — manual category selection recommended")
    elif tier == "medium":
        rationale.append("Medium confidence — review the proposal before continuing")

    description_draft = _build_description_draft(
        guild_name, server_desc, panels, proposed
    )

    return AiDiscoveryScanResult(
        proposed_category=proposed,
        confidence=round(confidence, 2),
        confidence_tier=tier,
        method="heuristics",
        summary=summary,
        rationale=rationale[:12],
        signals=signals[:15],
        category_scores=CategoryScores(
            selling=round(scores["selling"], 2),
            saas=round(scores["saas"], 2),
            community=round(scores["community"], 2),
            other=round(scores["other"], 2),
        ),
        classified_channels=classified,
        role_candidates=role_candidates[:8],
        panels_found=panel_summaries,
        description_draft=description_draft or None,
        partnership_detected=partnership_detected,
        is_community_server=is_community,
        voice_text_ratio=ratio,
        channel_count=len(channels),
        panel_count=len(panels),
    )


async def queue_channel_extract(
    redis: Redis,
    guild_id: int,
    channel_ids: list[str],
    request_id: str | None = None,
) -> str:
    """Queue a bot job to read channel history + HTML attachments."""
    req_id = request_id or str(uuid.uuid4())
    payload = {
        "request_id": req_id,
        "guild_id": str(guild_id),
        "channel_ids": channel_ids,
    }
    await redis.lpush("bot:pending_extracts", json.dumps(payload))
    await redis.set(f"bot:extract:pending:{req_id}", "1", ex=120)
    return req_id
