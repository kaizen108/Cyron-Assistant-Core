"""Support staff role checks using panel configuration."""

from __future__ import annotations

import discord

from bot.utils.http_client import get_client


def member_has_support_roles(
    member: discord.Member,
    support_role_ids: list | None,
) -> bool:
    """True if member is staff for this ticket (panel roles or manage_channels)."""
    if member.guild_permissions.manage_channels or member.guild_permissions.administrator:
        return True

    if support_role_ids:
        member_role_ids = {r.id for r in member.roles}
        return any(int(rid) in member_role_ids for rid in support_role_ids)

    # Legacy fallback when no panel support roles are configured
    return any(r.name.lower() == "support" for r in member.roles)


async def get_support_role_ids_for_ticket(
    guild_id: str,
    ticket: dict | None,
) -> list:
    """Load support_role_ids from the ticket's panel, if any."""
    if not ticket or not ticket.get("panel_id"):
        return []
    try:
        panel = await get_client().get_panel(guild_id, ticket["panel_id"])
    except Exception:
        panel = None
    if not panel:
        return []
    return panel.get("support_role_ids") or []


async def has_support_for_channel(
    member: discord.Member,
    guild_id: str,
    channel_id: int | str,
) -> bool:
    """Check support access using the ticket channel's panel configuration."""
    try:
        ticket = await get_client().get_ticket(guild_id, str(channel_id))
    except Exception:
        ticket = None
    role_ids = await get_support_role_ids_for_ticket(guild_id, ticket)
    return member_has_support_roles(member, role_ids)
