"""Build Discord embeds with guild.embed_color for ticket messages."""

from typing import Any

import discord

DEFAULT_EMBED_COLOR = "#00b4ff"


def _hex_to_colour(hex_str: str | None) -> discord.Colour:
    """Convert hex string (#00b4ff) to discord.Colour."""
    s = (hex_str or DEFAULT_EMBED_COLOR).strip().lstrip("#")
    if len(s) != 6:
        return discord.Colour(0x00B4FF)
    try:
        return discord.Colour(int(s, 16))
    except ValueError:
        return discord.Colour(0x00B4FF)


def create_ticket_embed(
    *,
    title: str,
    description: str,
    color: str | None = None,
    fields: list[dict[str, Any]] | None = None,
    footer: str | None = None,
    timestamp: bool = True,
) -> discord.Embed:
    """
    Create a rich embed for ticket messages (AI replies, fallbacks, welcome).

    Args:
        title: Embed title.
        description: Embed description (main body).
        color: Hex color (e.g. guild.embed_color or "#00b4ff).
        fields: Optional list of {"name": str, "value": str, "inline": bool}.
        footer: Optional footer text (e.g. low-confidence suggestion).
        timestamp: Whether to set embed timestamp (default True).

    Returns:
        discord.Embed ready to send.
    """
    colour = _hex_to_colour(color)
    embed = discord.Embed(
        title=title,
        description=description,
        color=colour,
        timestamp=discord.utils.utcnow() if timestamp else None,
    )
    if fields:
        for f in fields:
            inline = f.get("inline", True)
            embed.add_field(
                name=str(f.get("name", "")),
                value=str(f.get("value", "")),
                inline=inline,
            )
    if footer:
        embed.set_footer(text=footer)
    return embed


def create_reply_embed(
    reply_text: str,
    *,
    embed_color: str | None = None,
    low_confidence: bool = False,
    title: str = "Support",
) -> discord.Embed:
    """
    Build embed for AI/fallback reply in tickets.
    Puts low-confidence suggestion in footer when applicable.
    """
    footer = None
    if low_confidence:
        footer = "Need more details? Click 'View Full Details' or ask support."
    return create_ticket_embed(
        title=title,
        description=reply_text,
        color=embed_color,
        footer=footer,
    )
