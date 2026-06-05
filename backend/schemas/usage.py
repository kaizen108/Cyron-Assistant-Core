"""Usage schemas."""

from pydantic import BaseModel, Field


class UsageResponse(BaseModel):
    """Guild usage statistics."""

    guild_id: int
    plan: str
    monthly_tokens_used: int
    monthly_tokens_limit: int
    daily_ticket_count: int
    daily_ticket_limit: int
    concurrent_ai_sessions: int
    concurrent_limit: int
