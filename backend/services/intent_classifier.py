"""Lightweight intent classifier: generic chitchat vs substantive support queries."""

from __future__ import annotations

import json
import re
from typing import Literal

import structlog
from litellm import acompletion

from backend.config import config
from backend.services.response_routing import (
    is_conversational_without_kb,
    is_greeting_or_smalltalk,
    is_very_short_ack_lightweight,
)

logger = structlog.get_logger(__name__)

_MODEL = "gpt-4o-mini"


_SUBSTANTIVE_HINT = re.compile(
    r"\b("
    r"refund|billing|payment|charge|invoice|order|ship|track|cancel|subscription|"
    r"password|login|account|error|bug|broken|not\s+working|how\s+do\s+i|why\s+is|"
    r"where\s+(is|can|do)|when\s+(does|will|can)|price|cost|policy|warranty|"
    r"ticket|ban|mute|role|discord|nitro|robux|"
    r"help\s+with|support|issue|problem|upgrade|download|install|return|deliver|"
    r"hours|verify|appeal|lost|wrong|scam|hack|staff|admin|phone|address|"
    r"not\s+received|didn'?t\s+get|charged\s+twice"
    r")\b",
    re.IGNORECASE,
)


def _heuristic_substantive(text: str) -> bool:
    t = (text or "").strip()
    if len(t) > 220:
        return True
    if _SUBSTANTIVE_HINT.search(t):
        return True
    if len(t) > 80 and ("?" in t or "¿" in t):
        return True
    return False


async def _llm_generic_classify(text: str) -> bool:
    if not config.openai_api_key:
        return False
    prompt = (
        "Decide if the user message is ONLY generic chitchat: greetings, thanks, "
        "ok/yes/no, small talk, asking if you can help, 'how are you', with NO request for "
        "specific facts about products, accounts, policies, or technical support.\n"
        'Reply JSON only: {"generic": true} or {"generic": false}'
    )
    try:
        response = await acompletion(
            model=_MODEL,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": (text or "").strip()[:1500]},
            ],
            max_tokens=40,
            temperature=0.0,
            api_key=config.openai_api_key,
        )
        raw = (response.choices[0].message.content or "").strip()
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end == -1:
            return False
        obj = json.loads(raw[start : end + 1])
        return bool(obj.get("generic"))
    except Exception as exc:
        logger.warning("intent_classifier_llm_failed", error=str(exc))
        return False


IntentKind = Literal["generic", "substantive"]


async def classify_relay_intent(text: str) -> IntentKind:
    """
    Fast path: regex/small-talk rules. Ambiguous short messages use one cheap LLM call.
    Does not run LLM when clearly substantive or clearly generic.
    """
    t = (text or "").strip()
    if not t:
        return "generic"

    if (
        is_greeting_or_smalltalk(t)
        or is_very_short_ack_lightweight(t)
        or is_conversational_without_kb(t)
    ):
        logger.info("intent_classifier", path="heuristic_generic", len=len(t))
        return "generic"

    if _heuristic_substantive(t):
        logger.info("intent_classifier", path="heuristic_substantive", len=len(t))
        return "substantive"

    generic = await _llm_generic_classify(t)
    path = "llm_generic" if generic else "llm_substantive"
    logger.info("intent_classifier", path=path, len=len(t))
    return "generic" if generic else "substantive"
