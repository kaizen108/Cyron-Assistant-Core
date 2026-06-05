"""Placeholder resolution for ticket messages."""


def resolve_placeholders(text: str, context: dict) -> str:
    if not text:
        return text
    replacements = {
        "{ticket.creator}":          context.get("creator_mention", ""),
        "{ticket.creator.mention}":  context.get("creator_mention", ""),
        "{ticket.creator.username}": context.get("creator_username", ""),
        "{ticket.number}":           str(context.get("ticket_number", "")),
        "{ticket.channel}":          context.get("channel_mention", ""),
        "{panel.name}":              context.get("panel_name", ""),
        "{guild.name}":              context.get("guild_name", ""),
        "{ticket.closer.mention}":   context.get("closer_mention", ""),
        "{ticket.closeReason}":      context.get("close_reason", ""),
    }
    for key, value in replacements.items():
        text = text.replace(key, str(value))
    return text
