"""Subscription plan limits - hardcoded per spec."""

from typing import TypedDict


class PlanLimits(TypedDict):
    """Plan limit structure."""

    knowledge_entries: int
    monthly_tokens: int
    concurrent_tickets: int
    daily_ticket_limit: int


PLAN_LIMITS: dict[str, PlanLimits] = {
    "free": {
        "knowledge_entries": 2,
        "monthly_tokens": 50_000,
        "concurrent_tickets": 1,
        "daily_ticket_limit": 10,
    },
    "pro": {
        "knowledge_entries": 5,
        "monthly_tokens": 1_500_000,
        "concurrent_tickets": 3,
        "daily_ticket_limit": 50,
    },
    "business": {
        "knowledge_entries": 10,
        "monthly_tokens": 3_000_000,
        "concurrent_tickets": 3,
        "daily_ticket_limit": 100,
    },
}

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful AI support assistant for a Discord server. "
    "Answer user questions concisely and professionally based on the provided knowledge base. "
)
