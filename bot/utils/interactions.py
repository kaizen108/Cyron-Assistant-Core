"""Helpers for safe Discord interaction responses."""

from __future__ import annotations

import discord


async def reply(
    interaction: discord.Interaction,
    content: str | None = None,
    *,
    embed: discord.Embed | None = None,
    ephemeral: bool = True,
    view: discord.ui.View | None = None,
) -> None:
    """Send via interaction.response or followup depending on state."""
    kwargs: dict = {"ephemeral": ephemeral}
    if embed is not None:
        kwargs["embed"] = embed
    if view is not None:
        kwargs["view"] = view

    if interaction.response.is_done():
        await interaction.followup.send(content, **kwargs)
    else:
        await interaction.response.send_message(content, **kwargs)


async def defer_ephemeral(interaction: discord.Interaction) -> None:
    """Defer if the interaction has not been acknowledged yet."""
    await defer_if_needed(interaction, ephemeral=True)


async def defer_if_needed(
    interaction: discord.Interaction,
    *,
    ephemeral: bool = False,
) -> None:
    """Defer if the interaction has not been acknowledged yet."""
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=ephemeral)
