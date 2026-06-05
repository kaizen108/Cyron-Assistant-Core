"""Guild schemas."""

import re
from datetime import datetime

from pydantic import BaseModel, Field, ConfigDict, field_validator, field_serializer


HEX_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")


class GuildResponse(BaseModel):
    """API response model for a guild.

    id is serialized as string in JSON so JavaScript clients do not lose
    precision (Discord snowflake IDs exceed Number.MAX_SAFE_INTEGER).
    """

    id: int = Field(..., description="Discord guild ID")
    name: str
    icon_url: str | None = Field(
        default=None, description="Discord guild icon URL (if available)"
    )
    plan: str
    has_bot: bool = Field(
        default=False,
        description="True if the Cyron Assistant bot is currently installed in this guild",
    )
    monthly_tokens_used: int
    daily_ticket_count: int
    concurrent_ai_sessions: int
    last_daily_reset: datetime | None
    last_monthly_reset: datetime | None
    system_prompt: str
    embed_color: str | None = Field(
        default="#00b4ff",
        description="Hex color for ticket embeds, default light blue",
    )

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("id")
    @classmethod
    def serialize_id(cls, v: int) -> str:
        """Emit guild ID as string so JS clients preserve full precision."""
        return str(v)


class GuildCloseSettings(BaseModel):
    """Guild-level close/rating settings."""
    close_embed_title: str | None = None
    close_embed_description: str | None = None
    close_embed_footer: str | None = None
    dm_user_on_close: bool | None = None
    show_transcript_button: bool | None = None
    default_close_reason: str | None = None
    require_reason_to_close: bool | None = None
    confirm_close_check: bool | None = None
    rating_system_enabled: bool | None = None
    rating_log_channel_id: int | None = None
    close_on_user_leave: bool | None = None


class GuildCloseSettingsResponse(BaseModel):
    close_embed_title: str | None
    close_embed_description: str | None
    close_embed_footer: str | None
    dm_user_on_close: bool
    show_transcript_button: bool
    default_close_reason: str | None
    require_reason_to_close: bool
    confirm_close_check: bool
    rating_system_enabled: bool
    rating_log_channel_id: int | None
    close_on_user_leave: bool

    model_config = ConfigDict(from_attributes=True)


class GuildUpdate(BaseModel):
    """Fields that can be updated on a guild."""

    name: str | None = None
    plan: str | None = Field(
        default=None, description="free | pro | business (case-insensitive)"
    )
    system_prompt: str | None = None
    embed_color: str | None = Field(
        default=None,
        description="Hex color for ticket embeds (Pro/Business only)",
    )

    @field_validator("embed_color")
    @classmethod
    def validate_embed_color(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not HEX_COLOR_PATTERN.match(v):
            raise ValueError("embed_color must be a 6-digit hex color, e.g. #00b4ff")
        return v


