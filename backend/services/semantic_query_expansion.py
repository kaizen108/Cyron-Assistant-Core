"""Extra retrieval text for multilingual / paraphrase equivalence (no LLM — keeps latency low)."""

from __future__ import annotations

import re


def expand_query_for_retrieval(original: str, english_line: str) -> str:
    """
    Append synonym / equivalence phrases so embedding search links
    e.g. 'abbonamento annuale' ↔ '12 mesi', delivery time ↔ 'consegna veloce'.
    """
    base = (english_line or "").strip() or (original or "").strip()
    o = (original or "").lower()
    extras: list[str] = []

    if re.search(
        r"\b(annuale|annuo|annual|yearly|year|abbonamento|subscription|12\s*mesi|dodici|un\s*anno|1\s*anno)\b",
        o,
        re.I,
    ):
        extras.append(
            "12 mesi dodici mesi un anno 1 anno abbonamento annuale annual subscription yearly 12 month one year"
        )
    if re.search(
        r"\b(tempo|arriv|arriva|consegna|delivery|shipping|quanto|how\s+long|when|minutes|minuti)\b",
        o,
        re.I,
    ):
        extras.append(
            "consegna veloce delivery fast shipping arrival time pochi minuti minutes same day"
        )
    if re.search(r"\b(spotify|premium|paypal|crypto|mese|month)\b", o, re.I):
        extras.append("spotify premium account subscription months paypal crypto")

    if not extras:
        return base
    return base + "\n" + " ".join(extras)


def expand_storage_embedding_text(
    title: str,
    main_content: str,
    template_payload: dict | None,
) -> str:
    """Richer embedding source at save time (template fields + keywords + related_terms)."""
    parts = [title or "", main_content or ""]
    if template_payload and isinstance(template_payload, dict):
        for key in ("problem", "solution", "product_name", "summary", "rule", "details"):
            v = template_payload.get(key)
            if isinstance(v, str) and v.strip():
                parts.append(v.strip())
        # keywords and related_terms from auto_format — massively improve retrieval
        for list_key in ("keywords", "related_terms"):
            items = template_payload.get(list_key)
            if isinstance(items, list) and items:
                parts.append(" ".join(str(i) for i in items if i))
    return "\n\n".join(p for p in parts if p)
