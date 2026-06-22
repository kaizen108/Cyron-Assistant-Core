"""Exact-match relay response cache keys — no embedding neighborhood matching."""

from __future__ import annotations

import hashlib
import re
import uuid

_NUMERIC_QUERY = re.compile(r"\d")
_VOLATILE_TOPIC = re.compile(
    r"\b(discount|coupon|promo|promotion|sale|code|%\s*off|rebate)\b",
    re.I,
)


def normalize_relay_query(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def relay_exact_cache_key(guild_id: int, lang: str, text: str) -> str:
    """Cache key from exact normalized query text (different wording = different key)."""
    norm = normalize_relay_query(text)
    digest = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:32]
    return f"relay:exact:{guild_id}:{lang}:{digest}"


def panel_exact_cache_key(
    panel_id: uuid.UUID, context_version: int, lang: str, text: str
) -> str:
    norm = normalize_relay_query(text)
    digest = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:32]
    return f"panel:{panel_id}:ctx:{context_version}:{lang}:{digest}"


def should_store_relay_cache(query: str) -> bool:
    """
    Do not cache price/amount or promo questions — they must not share answers.
    """
    t = normalize_relay_query(query)
    if not t:
        return False
    if _NUMERIC_QUERY.search(t):
        return False
    if _VOLATILE_TOPIC.search(t):
        return False
    return True


def should_use_compact_rag(query: str) -> bool:
    """Compact RAG is unsafe for numeric pricing questions."""
    t = normalize_relay_query(query)
    if not t:
        return False
    if _NUMERIC_QUERY.search(t):
        return False
    return True
