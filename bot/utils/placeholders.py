"""Placeholder resolution for ticket messages."""


def resolve_placeholders(text: str, context: dict) -> str:
    if not text:
        return text

    replacements = {
        "{ticket.creator}": context.get("creator_mention", ""),
        "{ticket.creator.mention}": context.get("creator_mention", ""),
        "{ticket.creator.username}": context.get("creator_username", ""),
        "{ticket.number}": str(context.get("ticket_number", "")),
        "{ticket.channel}": context.get("channel_mention", ""),
        "{panel.name}": context.get("panel_name", ""),
        "{guild.name}": context.get("guild_name", ""),
        "{ticket.closer.mention}": context.get("closer_mention", ""),
        "{ticket.closer.username}": context.get("closer_username", ""),
        "{ticket.closeReason}": context.get("close_reason", ""),
        "{ticket.close_reason}": context.get("close_reason", ""),
    }

    for key, value in replacements.items():
        text = text.replace(key, str(value))

    return text


def build_channel_name(format_str: str, context: dict) -> str:
    """Resolve panel channel name format and sanitize for Discord."""
    slug_ctx = {
        **context,
        "panel_name": context.get(
            "panel_name_slug",
            (context.get("panel_name") or "ticket").lower().replace(" ", "-"),
        ),
    }
    name = resolve_placeholders(format_str or "{panel.name}-{ticket.number}", slug_ctx)
    name = name.lower().replace(" ", "-")
    cleaned = "".join(
        ch if ch.isalnum() or ch in "-_" else "-"
        for ch in name
    ).strip("-")
    return (cleaned[:100] or "ticket")
