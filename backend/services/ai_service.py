"""AI service using LiteLLM — knowledge path and lightweight short replies."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import structlog
from litellm import acompletion

from backend.config import config
from backend.schemas.relay import PromptContext

logger = structlog.get_logger(__name__)

_COMPACT_MAIN_LIM = 500
_COMPACT_ADD_LIM = 120
_FULL_MAIN_LIM = 2800

_COMPACT_SYSTEM = (
    "You are a helpful Discord support assistant. Answer ONLY using the provided knowledge. "
    "Be short, natural and friendly. Reply in the same language as the user. "
    "Never add information not in the knowledge."
)

class AIServiceError(Exception):
    """Raised when the AI provider call fails."""


def _truncate_kb(s: str, lim: int) -> str:
    s = (s or "").strip()
    if len(s) <= lim:
        return s
    return s[: lim - 1].rstrip() + "…"


def _build_compact_messages(prompt_context: PromptContext) -> List[Dict[str, str]]:
    """Single user turn: minimal tokens (v2.2). No chat history."""
    parts: list[str] = []
    for ch in prompt_context.knowledge_chunks:
        title = str(ch.get("title", "")).strip()
        body = str(ch.get("main_content", ch.get("content", ""))).strip()
        if title:
            parts.append(f"{title}: {body}")
        else:
            parts.append(body)
    kb = "\n".join(p for p in parts if p).strip()[:520]
    q = str(getattr(prompt_context, "compact_user_query", "") or "").strip()[:420]
    user_block = f"Knowledge:\n{kb}\n\nUser:\n{q}\nAnswer concisely:"
    return [
        {"role": "system", "content": _COMPACT_SYSTEM},
        {"role": "user", "content": user_block},
    ]


def _build_knowledge_messages(prompt_context: PromptContext) -> List[Dict[str, str]]:
    messages: list[dict[str, str]] = [
        {"role": "system", "content": prompt_context.system_prompt},
    ]
    compact = bool(getattr(prompt_context, "compact_reply", False))
    main_lim = _COMPACT_MAIN_LIM if compact else _FULL_MAIN_LIM
    add_lim = _COMPACT_ADD_LIM if compact else 900

    parts: list[str] = []
    for idx, chunk in enumerate(prompt_context.knowledge_chunks, start=1):
        title = str(chunk.get("title", "")).strip()
        main_content = str(chunk.get("main_content", chunk.get("content", ""))).strip()
        additional_context = str(chunk.get("additional_context", "")).strip()
        behavior_notes = str(chunk.get("behavior_notes", "")).strip()
        if compact:
            main_content = _truncate_kb(main_content, main_lim)
            additional_context = _truncate_kb(additional_context, add_lim)
            behavior_notes = _truncate_kb(behavior_notes, 200)
        header = f"[{idx}] {title}" if title else f"[{idx}]"
        body_parts = [f"main_content:\n{main_content}"]
        if additional_context:
            body_parts.append(f"additional_context:\n{additional_context}")
        if behavior_notes:
            body_parts.append(f"behavior_notes:\n{behavior_notes}")
        parts.append(f"{header}\n" + "\n".join(body_parts))

    mode = getattr(prompt_context, "retrieval_mode", None) or "high"
    if compact:
        intro = (
            "Facts below only. Reply in the user's language with 1–3 short sentences. "
            "No bullet lists unless they asked. No promises not in the text.\n\n"
        )
    elif mode == "moderate":
        intro = (
            "Below are the best-matching help excerpts (partial match to the user's wording is OK). "
            "Acknowledge their intent in your reply, then answer only from this material:\n\n"
        )
    else:
        intro = "Use only these passages for facts (synthesize naturally):\n\n"

    knowledge_text = intro + "\n\n---\n\n".join(parts)
    messages.append({"role": "system", "content": knowledge_text})

    for msg in prompt_context.message_history:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if not isinstance(content, str):
            content = str(content)
        messages.append({"role": role, "content": content})

    return messages


def _extract_reply(response: Any) -> str:
    choices = getattr(response, "choices", None)
    if choices is None and isinstance(response, dict):
        choices = response.get("choices")
    if not choices:
        raise AIServiceError("AI response contained no choices.")

    first = choices[0]
    message = getattr(first, "message", None)
    if message is None and isinstance(first, dict):
        message = first.get("message")
    if message is None:
        raise AIServiceError("AI response choice contained no message.")

    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")
    if not isinstance(content, str):
        raise AIServiceError("AI response message content is missing or not a string.")

    return content


def _extract_usage(response: Any) -> Tuple[int, int]:
    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage")

    prompt_tokens = 0
    completion_tokens = 0

    if usage is not None:
        pt = getattr(usage, "prompt_tokens", None)
        if pt is None and isinstance(usage, dict):
            pt = usage.get("prompt_tokens")
        ct = getattr(usage, "completion_tokens", None)
        if ct is None and isinstance(usage, dict):
            ct = usage.get("completion_tokens")
        if isinstance(pt, int):
            prompt_tokens = pt
        if isinstance(ct, int):
            completion_tokens = ct

    return prompt_tokens, completion_tokens


_LIGHTWEIGHT_SHORT_SYSTEM = (
    "Be natural, friendly, and conversational like a helpful support agent. Use warm language. "
    "Reply in ONE short sentence in the same language as the user. No bullet lists, under 25 words."
)


def _messages_from_history(
    message_history: List[Dict[str, str]], max_messages: int = 8
) -> List[Dict[str, str]]:
    out: list[dict[str, str]] = []
    for msg in message_history[-max_messages:]:
        role = msg.get("role", "user")
        if role not in ("user", "assistant"):
            continue
        content = msg.get("content", "")
        if not isinstance(content, str):
            content = str(content)
        out.append({"role": role, "content": content})
    return out


_NATURAL_CONV_SYSTEM = (
    "Be natural, friendly, and conversational like a helpful support agent. Use warm language. "
    "You are a capable teammate for this Discord server. "
    "The user's latest message is short and interpersonal — not a detailed factual question yet.\n\n"
    "Reply in the same language as the user (BCP-47 hint: {lang}). One or two short sentences.\n\n"
    "If they ask whether you can help, say yes and invite them to describe their issue.\n"
    "Do NOT mention knowledge bases, search, or embeddings.\n\n"
    "{guild_extra}"
)

_NO_KB_GROUND_SYSTEM = (
    "Be natural, friendly, and conversational like a helpful support agent. Use warm language. "
    "You assist this Discord server. This turn has no verified excerpts to quote — "
    "do not invent prices, policies, or product facts.\n\n"
    "Reply in the same language as the user (hint: {lang}). "
    "Always start by acknowledging what they seem to want or worry about (intent), in one short phrase—"
    "then explain gently that you do not have the specific details here and invite them to share more, "
    "or offer a human teammate.\n\n"
    "Never open with a cold refusal. Avoid robotic phrases about 'knowledge bases' or 'no information'.\n\n"
    "{guild_extra}"
)


async def get_lightweight_short_reply(user_message: str) -> Tuple[str, int, int]:
    """Minimal tokens for very short non-greeting follow-ups (no RAG)."""
    api_key = config.openai_api_key
    if not api_key:
        raise AIServiceError("OPENAI_API_KEY is not configured.")
    try:
        response = await acompletion(
            model=config.openai_model,
            messages=[
                {"role": "system", "content": _LIGHTWEIGHT_SHORT_SYSTEM},
                {"role": "user", "content": (user_message or "").strip()[:300]},
            ],
            max_tokens=64,
            temperature=0.35,
            api_key=api_key,
        )
    except Exception as exc:  # pragma: no cover
        logger.error("lightweight_short_failed", error=str(exc))
        raise AIServiceError("Lightweight reply failed") from exc
    reply = _extract_reply(response)
    pt, ct = _extract_usage(response)
    logger.info(
        "ai_lightweight_short",
        prompt_tokens=pt,
        completion_tokens=ct,
        total_tokens=pt + ct,
    )
    return reply, pt, ct


def _guild_tone_block(guild_system_prompt: str) -> str:
    g = (guild_system_prompt or "").strip()
    if not g:
        return ""
    return f"Team tone and instructions (follow when compatible):\n{g}\n"


async def get_natural_conversational_reply(
    guild_system_prompt: str,
    message_history: List[Dict[str, str]],
    user_message: str,
    user_language: str,
) -> Tuple[str, int, int]:
    """Natural reply for meta/rapport messages without RAG (e.g. 'Will you help me?')."""
    api_key = config.openai_api_key
    if not api_key:
        raise AIServiceError("OPENAI_API_KEY is not configured.")
    system = _NATURAL_CONV_SYSTEM.format(
        lang=user_language or "en",
        guild_extra=_guild_tone_block(guild_system_prompt),
    )
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    messages.extend(_messages_from_history(message_history))
    messages.append(
        {"role": "user", "content": (user_message or "").strip()[:2000]}
    )
    try:
        response = await acompletion(
            model=config.openai_model,
            messages=messages,
            max_tokens=min(160, config.openai_max_tokens),
            temperature=0.42,
            api_key=api_key,
        )
    except Exception as exc:  # pragma: no cover
        logger.error("natural_conversational_failed", error=str(exc))
        raise AIServiceError("Natural conversational reply failed") from exc
    reply = _extract_reply(response)
    pt, ct = _extract_usage(response)
    logger.info(
        "ai_natural_conversational",
        prompt_tokens=pt,
        completion_tokens=ct,
        user_language=user_language,
    )
    return reply, pt, ct


async def get_support_reply_without_kb_chunks(
    guild_system_prompt: str,
    message_history: List[Dict[str, str]],
    user_message: str,
    user_language: str,
) -> Tuple[str, int, int]:
    """When retrieval finds no usable passages — human tone without robotic 'no KB' wording."""
    api_key = config.openai_api_key
    if not api_key:
        raise AIServiceError("OPENAI_API_KEY is not configured.")
    system = _NO_KB_GROUND_SYSTEM.format(
        lang=user_language or "en",
        guild_extra=_guild_tone_block(guild_system_prompt),
    )
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    messages.extend(_messages_from_history(message_history))
    messages.append(
        {"role": "user", "content": (user_message or "").strip()[:4000]}
    )
    try:
        response = await acompletion(
            model=config.openai_model,
            messages=messages,
            max_tokens=min(350, config.openai_max_tokens),
            temperature=0.36,
            api_key=api_key,
        )
    except Exception as exc:  # pragma: no cover
        logger.error("support_no_kb_failed", error=str(exc))
        raise AIServiceError("Support reply without KB failed") from exc
    reply = _extract_reply(response)
    pt, ct = _extract_usage(response)
    logger.info(
        "ai_support_no_kb",
        prompt_tokens=pt,
        completion_tokens=ct,
        user_language=user_language,
    )
    return reply, pt, ct


async def get_ai_response(
    prompt_context: PromptContext, max_tokens: int = 250
) -> Tuple[str, int, int]:
    """Knowledge-grounded completion. Caller must pass chunks only when RAG applies."""
    if not prompt_context.knowledge_chunks:
        raise AIServiceError("get_ai_response requires non-empty knowledge_chunks")

    compact = bool(getattr(prompt_context, "compact_reply", False))
    if compact:
        messages = _build_compact_messages(prompt_context)
    else:
        messages = _build_knowledge_messages(prompt_context)
    api_key = config.openai_api_key
    if not api_key:
        raise AIServiceError("OPENAI_API_KEY is not configured.")

    mode = getattr(prompt_context, "retrieval_mode", None) or "high"
    if compact:
        temp = 0.3
        cap = min(100, max_tokens)
    else:
        temp = 0.32 if mode == "moderate" else 0.26
        cap = min(250, max_tokens)

    try:
        response = await acompletion(
            model=config.openai_model,
            messages=messages,
            max_tokens=min(cap, config.openai_max_tokens, 350),
            temperature=temp,
            api_key=api_key,
        )
    except Exception as exc:  # pragma: no cover - provider-specific errors
        logger.error("ai_completion_failed", error=str(exc))
        raise AIServiceError("AI completion failed") from exc

    reply = _extract_reply(response)
    prompt_tokens, completion_tokens = _extract_usage(response)
    total = prompt_tokens + completion_tokens

    if compact:
        logger.info(
            "COMPACT_PATH_TAKEN",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total,
            knowledge_chunks=len(prompt_context.knowledge_chunks),
        )
    else:
        logger.info(
            "STANDARD_PATH",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total,
            knowledge_chunks=len(prompt_context.knowledge_chunks),
            retrieval_mode=prompt_context.retrieval_mode,
        )

    logger.info(
        "ai_completion_success",
        model=config.openai_model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total,
        knowledge_chunks=len(prompt_context.knowledge_chunks),
        user_language=prompt_context.user_language,
        retrieval_mode=prompt_context.retrieval_mode,
        compact_reply=compact,
    )

    return reply, prompt_tokens, completion_tokens
