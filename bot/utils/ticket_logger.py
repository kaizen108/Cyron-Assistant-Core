"""Structured ticket event logger."""

import logging
import discord

logger = logging.getLogger(__name__)

EVENTS = {
    "TICKET_OPENED":        ("🟢", 0x57F287),
    "TICKET_CLOSED":        ("🔴", 0xED4245),
    "TICKET_CLAIMED":       ("🔵", 0x5865F2),
    "TICKET_UNCLAIMED":     ("⚪", 0x95A5A6),
    "TRANSCRIPT_GENERATED": ("📜", 0xFEE75C),
    "USER_ADDED":           ("➕", 0x57F287),
    "USER_REMOVED":         ("➖", 0xE67E22),
    "PRIORITY_CHANGED":     ("⚡", 0xE67E22),
    "TICKET_MOVED":         ("📁", 0x3498DB),
}

READABLE = {
    "TICKET_OPENED": "Ticket Opened",
    "TICKET_CLOSED": "Ticket Closed",
    "TICKET_CLAIMED": "Ticket Claimed",
    "TICKET_UNCLAIMED": "Ticket Unclaimed",
    "TRANSCRIPT_GENERATED": "Transcript Generated",
    "USER_ADDED": "User Added",
    "USER_REMOVED": "User Removed",
    "PRIORITY_CHANGED": "Priority Changed",
    "TICKET_MOVED": "Ticket Moved",
}


def _build_embed(event_type: str, channel: discord.TextChannel, actor: discord.Member,
                 panel: dict | None, extra: dict | None) -> discord.Embed:
    emoji, color = EVENTS.get(event_type, ("📋", 0x95A5A6))
    title = f"{emoji} {READABLE.get(event_type, event_type)}"
    embed = discord.Embed(title=title, color=color, timestamp=discord.utils.utcnow())
    embed.add_field(name="Ticket", value=channel.mention, inline=True)
    embed.add_field(name="By", value=actor.mention, inline=True)
    if panel:
        embed.add_field(name="Panel", value=panel.get("name", "—"), inline=True)
    if extra:
        for k, v in extra.items():
            embed.add_field(name=k, value=str(v), inline=True)
    return embed


async def log_ticket_event(
    bot: discord.Client,
    guild: discord.Guild,
    event_type: str,
    channel: discord.TextChannel,
    actor: discord.Member,
    panel: dict | None = None,
    extra: dict | None = None,
) -> None:
    embed = _build_embed(event_type, channel, actor, panel, extra)

    if panel and panel.get("log_channel_id"):
        log_ch = guild.get_channel(int(panel["log_channel_id"]))
        if log_ch and isinstance(log_ch, discord.TextChannel):
            try:
                await log_ch.send(embed=embed)
            except Exception as e:
                logger.warning("Failed to send log to log_channel: %s", e)

    if panel and panel.get("send_logs_in_ticket") and channel:
        try:
            await channel.send(embed=embed)
        except Exception as e:
            logger.warning("Failed to send log in ticket channel: %s", e)
