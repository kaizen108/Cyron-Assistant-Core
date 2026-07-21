"""Extract recurring problems from transcripts (HTML + ticket channels)."""

from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from html.parser import HTMLParser
from typing import Any

import structlog
from litellm import acompletion
from redis.asyncio import Redis

from backend.config import config
from backend.schemas.ai_discovery import ExtractedProblem, ExtractInput, ExtractOutput
from backend.services.ai_discovery_service import queue_channel_extract

logger = structlog.get_logger(__name__)

_STRIP_MENTION = re.compile(r"<@!?\d+>|@\w+|#\w+")
_MULTI_SPACE = re.compile(r"\s+")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = False

    def handle_data(self, data: str) -> None:
        if not self._skip and data.strip():
            self._parts.append(data.strip())

    def text(self) -> str:
        return "\n".join(self._parts)


def _clean_text(text: str) -> str:
    text = _STRIP_MENTION.sub("", text or "")
    text = _MULTI_SPACE.sub(" ", text).strip()
    return text


def parse_ticket_tool_html(html: str) -> list[str]:
    """Parse Ticket Tool / similar HTML transcripts into message lines."""
    parser = _TextExtractor()
    try:
        parser.feed(html)
        raw = parser.text()
    except Exception:
        raw = re.sub(r"<[^>]+>", " ", html)
    lines: list[str] = []
    for line in raw.splitlines():
        line = _clean_text(line)
        if len(line) > 8:
            lines.append(line)
    return lines


def _heuristic_extract_from_lines(lines: list[str], max_problems: int) -> list[ExtractedProblem]:
    """Pattern-based extraction without LLM."""
    problems: list[ExtractedProblem] = []
    counter: Counter[str] = Counter()

    question_patterns = [
        re.compile(r"(?i)(how do i|how to|where is|when will|can i|why is|problem with|issue with|help with)\s+(.+)"),
        re.compile(r"(?i)(paid|payment|refund|delivery|not working|expired|broken)\b"),
    ]

    current_q: str | None = None
    for line in lines:
        is_q = any(p.search(line) for p in question_patterns)
        if is_q and "?" in line:
            current_q = line[:200]
            continue
        if current_q and len(line) > 15:
            key = current_q.lower()[:80]
            counter[key] += 1
            if counter[key] == 1:
                problems.append(
                    ExtractedProblem(
                        problem=current_q,
                        solution=line[:300],
                        frequency=1,
                    )
                )
            else:
                for p in problems:
                    if p.problem.lower()[:80] == key:
                        p.frequency += 1
                        break
            current_q = None

    problems.sort(key=lambda p: p.frequency, reverse=True)
    return problems[:max_problems]


async def _llm_extract(lines: list[str], max_problems: int) -> list[ExtractedProblem]:
    if not config.openai_api_key or not lines:
        return []

    sample = "\n".join(lines[:80])[:6000]
    prompt = (
        "Extract recurring support problems and the solutions staff actually gave. "
        "NEVER invent solutions not present in the text. "
        "Strip personal data. Return JSON array: "
        '[{"problem":"...","solution":"...","frequency":1}]\n\n'
        f"TRANSCRIPT:\n{sample}"
    )
    try:
        resp = await acompletion(
            model=config.openai_model,
            messages=[
                {"role": "system", "content": "Extract support patterns. JSON only."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=800,
            temperature=0.1,
            api_key=config.openai_api_key,
        )
        text = (resp.choices[0].message.content or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        data = json.loads(text)
        out: list[ExtractedProblem] = []
        if isinstance(data, list):
            for item in data[:max_problems]:
                if isinstance(item, dict) and item.get("problem") and item.get("solution"):
                    out.append(
                        ExtractedProblem(
                            problem=str(item["problem"]).strip(),
                            solution=str(item["solution"]).strip(),
                            frequency=int(item.get("frequency") or 1),
                        )
                    )
        return out
    except Exception as exc:
        logger.warning("extract_llm_failed", error=str(exc))
        return []


async def _wait_for_bot_extract(redis: Redis, request_id: str, wait_seconds: int) -> dict[str, Any] | None:
    key = f"bot:extract:result:{request_id}"
    for _ in range(wait_seconds * 2):
        raw = await redis.get(key)
        if raw:
            await redis.delete(key)
            await redis.delete(f"bot:extract:pending:{request_id}")
            return json.loads(raw)
        await asyncio.sleep(0.5)
    return None


async def run_discovery_extract(
    redis: Redis,
    guild_id: int,
    body: ExtractInput,
) -> ExtractOutput:
    """Extract problems from HTML uploads and/or Discord channels (via bot queue)."""
    all_lines: list[str] = []
    sources = 0

    for html in body.html_contents or []:
        if html.strip():
            all_lines.extend(parse_ticket_tool_html(html))
            sources += 1

    channel_ids = list(body.channel_ids or []) + list(body.ticket_channel_ids or [])
    if channel_ids:
        req_id = await queue_channel_extract(redis, guild_id, channel_ids)
        bot_data = await _wait_for_bot_extract(redis, req_id, body.wait_seconds)
        if bot_data:
            for html in bot_data.get("html_contents") or []:
                all_lines.extend(parse_ticket_tool_html(html))
                sources += 1
            for msg in bot_data.get("messages") or []:
                line = _clean_text(str(msg))
                if line:
                    all_lines.append(line)
            sources += len(bot_data.get("channels_processed") or [])
        else:
            return ExtractOutput(
                problems=[],
                sources_processed=sources,
                message="Channel read timed out — bot may be offline. Try uploading HTML files directly.",
            )

    if not all_lines:
        return ExtractOutput(
            problems=[],
            sources_processed=0,
            message="No transcript content found to extract from.",
        )

    problems = await _llm_extract(all_lines, body.max_problems)
    if not problems:
        problems = _heuristic_extract_from_lines(all_lines, body.max_problems)

    if not problems:
        return ExtractOutput(
            problems=[],
            sources_processed=sources,
            message="I couldn't extract enough recurring patterns — try manual entry.",
        )

    return ExtractOutput(
        problems=problems,
        sources_processed=sources,
        message=f"Extracted {len(problems)} recurring pattern(s) from {sources} source(s).",
    )
