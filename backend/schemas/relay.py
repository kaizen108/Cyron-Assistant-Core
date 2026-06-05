"""Relay request/response schemas."""

from typing import Any
from pydantic import BaseModel, Field


class RelayRequest(BaseModel):
    """Request payload for message relay."""

    guild_id: str = Field(..., description="Discord guild (server) ID")
    channel_id: str = Field(..., description="Discord channel ID")
    user_id: str = Field(..., description="Discord user ID who sent the message")
    content: str = Field(..., description="Message content")
    message_id: str | None = Field(None, description="Discord message ID (optional)")
    bot_id: str | None = Field(None, description="Discord bot user ID (for ticket isolation)")
    panel_id: str | None = Field(None, description="Ticket panel ID (v2 architecture)")


class PromptContext(BaseModel):
    """Prompt context for AI (Phase 3)."""

    system_prompt: str = ""
    knowledge_chunks: list[dict[str, Any]] = Field(default_factory=list)
    message_history: list[dict[str, str]] = Field(default_factory=list)
    user_language: str = Field(
        default="en",
        description="Detected language code for assistant reply language",
    )
    retrieval_mode: str = Field(
        default="none",
        description="none | moderate | high — KB match tier for this turn",
    )
    compact_reply: bool = Field(
        default=False,
        description="Short Discord-optimized reply (low tokens)",
    )
    compact_user_query: str = Field(
        default="",
        description="Latest user message for compact single-shot prompts",
    )


class TokenUsage(BaseModel):
    """Token usage details for an AI call."""

    input: int = Field(..., description="Prompt/input tokens")
    output: int = Field(..., description="Completion/output tokens")


class RelayResponse(BaseModel):
    """Response payload for message relay."""

    status: str = Field(..., description="ok | limit_exceeded | error")
    reply: str = Field(..., description="AI response message")
    prompt_context: PromptContext | None = Field(
        None, description="Built prompt context"
    )
    concurrent_now: int | None = Field(
        None, description="Current concurrent AI sessions for this guild"
    )
    low_confidence: bool | None = Field(
        None, description="True if retrieval confidence is low"
    )
    injected_knowledge_chars: int | None = Field(
        None, description="Total characters of injected knowledge"
    )
    top_similarity: float | None = Field(
        None, description="Top cosine similarity score for retrieved knowledge"
    )
    token_usage: TokenUsage | None = Field(
        None, description="Token usage for this AI call"
    )
    embed_color: str | None = Field(
        None, description="Guild embed color (hex) for Discord reply embeds"
    )
