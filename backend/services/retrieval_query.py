"""English expansion for embedding search — KB vectors are English-centric (MiniLM)."""

from __future__ import annotations

import re

import structlog
from litellm import acompletion

from backend.config import config

logger = structlog.get_logger(__name__)

# Likely non-English user text (Spanish/French/etc.) — translate for retrieval embedding only.
_NON_ASCII_LATIN = re.compile(r"[\u0080-\u024f]")
_SPANISH_Q = re.compile(
    r"\b(cuánto|cuánta|cuántos|cuántas|cómo|dónde|qué|por\s+qué|"
    r"precio|precios|cuesta|cuanto|cuanta|gracias|hola|buenos|buenas|muchas)\b",
    re.IGNORECASE,
)


def should_expand_for_english_embedding(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if _NON_ASCII_LATIN.search(t):
        return True
    if "¿" in t or "¡" in t:
        return True
    if _SPANISH_Q.search(t):
        return True
    for c in t:
        o = ord(c)
        if (
            0x0400 <= o <= 0x04FF
            or 0x0600 <= o <= 0x06FF
            or 0x0590 <= o <= 0x05FF
            or 0x4E00 <= o <= 0x9FFF
            or 0x3040 <= o <= 0x30FF
            or 0x31F0 <= o <= 0x31FF
            or 0xAC00 <= o <= 0xD7A3
        ):
            return True
    return False


async def english_for_embedding_search(text: str) -> str:
    """
    Return English line(s) aligned to the user message for similarity search only.
    If expansion is unnecessary or API missing, returns original text.
    """
    raw = (text or "").strip()
    if not raw:
        return raw
    if not should_expand_for_english_embedding(raw):
        return raw
    if not config.openai_api_key:
        return raw

    try:
        response = await acompletion(
            model=config.openai_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Translate the user's message to clear English for document search. "
                        "Output only the English text, one short paragraph max. "
                        "Keep product names (Robux, Roblox, Discord, etc.) unchanged. "
                        "Do not answer the question — translate intent only."
                    ),
                },
                {"role": "user", "content": raw[:4000]},
            ],
            max_tokens=120,
            temperature=0.0,
            api_key=config.openai_api_key,
        )
        out = (response.choices[0].message.content or "").strip()
        return out if out else raw
    except Exception as exc:
        logger.warning("english_for_embedding_failed", error=str(exc))
        return raw
