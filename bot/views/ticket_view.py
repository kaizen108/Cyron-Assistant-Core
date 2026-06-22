"""Persistent ticket panel view with Close, Claim, Add User, Remove User, Transcript."""

import io
import logging
import re
from typing import Any

import discord
from discord import ui

logger = logging.getLogger(__name__)

PREFIX = "ticket"
MODAL_PREFIX = "ticket_modal"


def _color_from_hex(hex_str: str) -> discord.Colour:
    """Convert hex string (#00b4ff) to discord.Colour."""
    s = (hex_str or "#00b4ff").strip().lstrip("#")
    if len(s) != 6:
        return discord.Colour(0x00B4FF)
    try:
        return discord.Colour(int(s, 16))
    except ValueError:
        return discord.Colour(0x00B4FF)


def build_ticket_embed(
    *,
    embed_color: str = "#00b4ff",
    created_by: discord.Member | discord.User,
    channel_id: int,
    claimed_by: str | None = None,
) -> discord.Embed:
    """Build the premium ticket welcome embed."""
    color = _color_from_hex(embed_color)
    embed = discord.Embed(
        title="Support Ticket",
        description=(
            "Hello! Our AI assistant and support team are here to help.\n\n"
            "Please describe your issue below."
        ),
        color=color,
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(
        name="Status",
        value="Claimed" if claimed_by else "Open",
        inline=True,
    )
    embed.add_field(
        name="Created by",
        value=created_by.mention,
        inline=True,
    )
    embed.add_field(
        name="Channel",
        value=f"<#{channel_id}>",
        inline=False,
    )
    footer = "Use the buttons below to manage this ticket."
    if claimed_by:
        footer = f"Claimed by {claimed_by}"
    embed.set_footer(text=footer)
    if created_by.display_avatar:
        embed.set_thumbnail(url=created_by.display_avatar.url)
    return embed


def parse_custom_id(custom_id: str) -> tuple[str, int] | None:
    """Parse custom_id 'ticket:action:channel_id' -> (action, channel_id)."""
    if not custom_id or not custom_id.startswith(f"{PREFIX}:"):
        return None
    parts = custom_id.split(":", 2)
    if len(parts) != 3:
        return None
    try:
        return parts[1], int(parts[2])
    except ValueError:
        return None


def parse_modal_custom_id(custom_id: str) -> tuple[str, int] | None:
    """Parse modal custom_id 'ticket_modal:action:channel_id' -> (action, channel_id)."""
    if not custom_id or not custom_id.startswith(f"{MODAL_PREFIX}:"):
        return None
    parts = custom_id.split(":", 2)
    if len(parts) != 3:
        return None
    try:
        return parts[1], int(parts[2])
    except ValueError:
        return None


async def _fetch_ticket_row(guild_id: int, channel_id: int) -> dict | None:
    from bot.utils.http_client import get_client

    try:
        return await get_client().get_ticket(str(guild_id), str(channel_id))
    except Exception:
        return None


async def _ticket_creator_id(guild_id: int, channel_id: int) -> int | None:
    row = await _fetch_ticket_row(guild_id, channel_id)
    if row and row.get("user_id") is not None:
        try:
            return int(row["user_id"])
        except (TypeError, ValueError):
            return None
    return None


def _resolve_member_from_input(guild: discord.Guild, value: str) -> discord.Member | None:
    """Resolve member from 'User ID' or '<@123>'-style mention."""
    value = (value or "").strip()
    # Mention pattern <@!?id>
    match = re.match(r"<@!?(\d+)>", value)
    if match:
        uid = int(match.group(1))
        return guild.get_member(uid)
    try:
        uid = int(value)
        return guild.get_member(uid)
    except ValueError:
        return None


# --- Modals ---


async def _do_close_ticket(
    interaction: discord.Interaction,
    channel_id: int,
    closed_by: discord.Member,
    reason: str | None = None,
) -> None:
    """Close ticket: notify backend, send close message, delete channel."""
    from bot.utils.http_client import get_client
    from bot.utils.ticket_logger import log_ticket_event
    from bot.utils.ticket_registry import clear_ticket_channel

    channel = interaction.guild and interaction.client.get_channel(channel_id)
    if not channel or not isinstance(channel, discord.TextChannel):
        await interaction.followup.send("This ticket channel no longer exists.", ephemeral=True)
        return

    # Notify backend BEFORE deleting (best-effort — never block on failure)
    try:
        client = get_client()
        await client.close_ticket(
            guild_id=str(interaction.guild.id),
            channel_id=str(channel_id),
            closed_by_user_id=str(closed_by.id),
            reason=reason,
        )
    except Exception as e:
        logger.warning("Could not update ticket status in backend: %s", e)

    clear_ticket_channel(channel_id)

    try:
        close_msg = f"Ticket closed by {closed_by.mention}."
        if reason:
            close_msg += f" Reason: {reason}"
        close_msg += "\nThis channel will be deleted in a few seconds."
        await channel.send(close_msg)

        # Log event
        try:
            await log_ticket_event(
                bot=interaction.client,
                guild=interaction.guild,
                event_type="TICKET_CLOSED",
                channel=channel,
                actor=closed_by,
                extra={"Reason": reason or "—"},
            )
        except Exception:
            pass

        await interaction.followup.send("Ticket closed.", ephemeral=True)
        await channel.delete(reason=f"Ticket closed by {closed_by}")
    except discord.Forbidden:
        try:
            await channel.set_permissions(interaction.guild.default_role, view_channel=False)
            await interaction.followup.send("Ticket locked (could not delete channel).", ephemeral=True)
        except Exception:
            await interaction.followup.send("Could not close or lock the channel.", ephemeral=True)
    except Exception as e:
        logger.exception("Error closing ticket %s: %s", channel_id, e)
        await interaction.followup.send("An error occurred while closing the ticket.", ephemeral=True)



class CloseConfirmModal(ui.Modal, title="Close Ticket"):
    """Confirmation modal for closing a ticket. Actual close is handled in handle_ticket_interaction (modal submit)."""

    confirm_input = ui.TextInput(
        label="Confirmation",
        placeholder="Type YES to confirm closing this ticket",
        required=True,
        max_length=10,
        style=discord.TextStyle.short,
    )

    def __init__(self, channel_id: int, closed_by: discord.Member) -> None:
        super().__init__(custom_id=f"{MODAL_PREFIX}:close:{channel_id}")
        self.channel_id = channel_id
        self.closed_by = closed_by

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if self.confirm_input.value.strip().upper() != "YES":
            await interaction.response.send_message(
                "Close cancelled. You must type **YES** to confirm.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        await _do_close_ticket(interaction, self.channel_id, self.closed_by)


class AddUserModal(ui.Modal, title="Add User to Ticket"):
    """Modal to add a user by ID or mention."""

    user_input = ui.TextInput(
        label="User ID or @mention",
        placeholder="Paste user ID or @mention the user",
        required=True,
        max_length=100,
        style=discord.TextStyle.short,
    )

    def __init__(self, channel_id: int) -> None:
        super().__init__(custom_id=f"{MODAL_PREFIX}:add_user:{channel_id}")
        self.channel_id = channel_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message(
                "Guild not found.", ephemeral=True
            )
            return
        channel = interaction.client.get_channel(self.channel_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Ticket channel no longer exists.", ephemeral=True
            )
            return
        member = _resolve_member_from_input(interaction.guild, self.user_input.value)
        if not member:
            await interaction.response.send_message(
                "Could not find that user. Use a valid user ID or @mention.",
                ephemeral=True,
            )
            return
        try:
            await channel.set_permissions(
                member,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            )
            await interaction.response.send_message(
                f"Added {member.mention} to this ticket.",
                ephemeral=False,
            )
            logger.info("Added user %s to ticket channel %s", member.id, self.channel_id)
        except discord.Forbidden as e:
            logger.warning("Forbidden adding user to ticket: %s", e)
            await interaction.response.send_message(
                "I don't have permission to add that user to this channel.",
                ephemeral=True,
            )
        except Exception as e:
            logger.exception("Error adding user to ticket: %s", e)
            await interaction.response.send_message(
                "An error occurred while adding the user.",
                ephemeral=True,
            )


class RemoveUserModal(ui.Modal, title="Remove User from Ticket"):
    """Modal to remove a user by ID or mention."""

    user_input = ui.TextInput(
        label="User ID or @mention",
        placeholder="Paste user ID or @mention the user to remove",
        required=True,
        max_length=100,
        style=discord.TextStyle.short,
    )

    def __init__(self, channel_id: int) -> None:
        super().__init__(custom_id=f"{MODAL_PREFIX}:remove_user:{channel_id}")
        self.channel_id = channel_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message(
                "Guild not found.", ephemeral=True
            )
            return
        channel = interaction.client.get_channel(self.channel_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Ticket channel no longer exists.", ephemeral=True
            )
            return
        member = _resolve_member_from_input(interaction.guild, self.user_input.value)
        if not member:
            await interaction.response.send_message(
                "Could not find that user. Use a valid user ID or @mention.",
                ephemeral=True,
            )
            return
        try:
            await channel.set_permissions(member, view_channel=False)
            await interaction.response.send_message(
                f"Removed {member.mention} from this ticket.",
                ephemeral=False,
            )
            logger.info(
                "Removed user %s from ticket channel %s", member.id, self.channel_id
            )
        except discord.Forbidden as e:
            logger.warning("Forbidden removing user from ticket: %s", e)
            await interaction.response.send_message(
                "I don't have permission to remove that user from this channel.",
                ephemeral=True,
            )
        except Exception as e:
            logger.exception("Error removing user from ticket: %s", e)
            await interaction.response.send_message(
                "An error occurred while removing the user.",
                ephemeral=True,
            )


# --- View ---


class TicketView(ui.View):
    """Persistent view for ticket panel buttons."""

    def __init__(self, channel_id: int, *, timeout: float | None = None,
                 close_label: str = "Close", close_emoji: str = "🔒",
                 claim_label: str = "Claim", claim_emoji: str = "👤",
                 claiming_enabled: bool = True) -> None:
        super().__init__(timeout=timeout)
        self._channel_id = channel_id

        from bot.views.panel_view import BUTTON_STYLES
        self.add_item(ui.Button(
            label=close_label, emoji=close_emoji,
            style=discord.ButtonStyle.danger,
            custom_id=f"{PREFIX}:close:{channel_id}",
        ))
        if claiming_enabled:
            self.add_item(ui.Button(
                label=claim_label, emoji=claim_emoji,
                style=discord.ButtonStyle.primary,
                custom_id=f"{PREFIX}:claim:{channel_id}",
            ))
        self.add_item(ui.Button(
            label="Add User", emoji="➕",
            style=discord.ButtonStyle.secondary,
            custom_id=f"{PREFIX}:add_user:{channel_id}",
        ))
        self.add_item(ui.Button(
            label="Remove User", emoji="➖",
            style=discord.ButtonStyle.secondary,
            custom_id=f"{PREFIX}:remove_user:{channel_id}",
        ))
        self.add_item(ui.Button(
            label="Transcript", emoji="📜",
            style=discord.ButtonStyle.secondary,
            custom_id=f"{PREFIX}:transcript:{channel_id}",
        ))


# --- Interaction handler (persistent via custom_id) ---


async def handle_ticket_interaction(
    interaction: discord.Interaction,
    bot: discord.Client,
) -> bool:
    """
    Handle ticket button interactions. Modal submits are handled by each Modal's on_submit.
    Returns True if the interaction was handled.
    """
    if interaction.type != discord.InteractionType.component:
        return False

    custom_id = (interaction.data or {}).get("custom_id", "")
    parsed = parse_custom_id(str(custom_id))
    if not parsed:
        return False

    action, channel_id = parsed
    channel = bot.get_channel(channel_id)
    if not channel or not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            "This ticket channel no longer exists.",
            ephemeral=True,
        )
        return True

    guild = channel.guild
    if not guild:
        await interaction.response.send_message(
            "Guild not found.",
            ephemeral=True,
        )
        return True

    member = interaction.user
    if not isinstance(member, discord.Member):
        await interaction.response.send_message(
            "Could not resolve member.",
            ephemeral=True,
        )
        return True

    support_role = discord.utils.get(guild.roles, name="Support")
    has_support = support_role and support_role in member.roles
    can_manage = channel.permissions_for(member).manage_channels

    # --- Close: show confirmation modal ---
    if action == "close":
        creator_id = await _ticket_creator_id(guild.id, channel_id)
        is_creator = creator_id is not None and member.id == creator_id
        users_can_close = True
        ticket_row = await _fetch_ticket_row(guild.id, channel_id)
        if ticket_row and ticket_row.get("panel_id"):
            from bot.utils.http_client import get_client
            panel = await get_client().get_panel(
                str(guild.id), ticket_row["panel_id"]
            )
            if panel is not None:
                users_can_close = panel.get("users_can_close", False)
        if not (has_support or can_manage or (is_creator and users_can_close)):
            await interaction.response.send_message(
                "Only support staff or the ticket creator can close this ticket.",
                ephemeral=True,
            )
            return True
        modal = CloseConfirmModal(channel_id=channel_id, closed_by=member)
        await interaction.response.send_modal(modal)
        return True

    # --- Claim: add staff to channel + update embed footer ---
    if action == "claim":
        if not (has_support or can_manage):
            await interaction.response.send_message(
                "Only support staff can claim tickets.",
                ephemeral=True,
            )
            return True
        await interaction.response.defer(ephemeral=False)
        try:
            # Ensure support role can see the channel (may already be set at creation)
            if support_role:
                await channel.set_permissions(
                    support_role,
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                )
            # Find welcome embed message and update footer
            async for msg in channel.history(limit=50, oldest_first=True):
                if msg.embeds and msg.author == bot.user:
                    emb = msg.embeds[0]
                    if emb.title == "Support Ticket":
                        emb.set_footer(text=f"Claimed by {member.display_name}")
                        if emb.fields:
                            for i, f in enumerate(emb.fields):
                                if f.name == "Status":
                                    emb.set_field_at(
                                        i, name="Status", value="Claimed", inline=True
                                    )
                                    break
                        await msg.edit(embed=emb)
                        break
            await interaction.followup.send(
                f"Ticket claimed by {member.mention}. They will assist you shortly.",
                ephemeral=False,
            )
            logger.info("Ticket %s claimed by %s", channel_id, member.id)
        except Exception as e:
            logger.exception("Error claiming ticket %s: %s", channel_id, e)
            await interaction.followup.send(
                "Ticket claimed, but I couldn't update the embed.",
                ephemeral=False,
            )
        return True

    # --- Add User: show modal ---
    if action == "add_user":
        if not (has_support or can_manage):
            await interaction.response.send_message(
                "Only support staff can add users to this ticket.",
                ephemeral=True,
            )
            return True
        modal = AddUserModal(channel_id=channel_id)
        await interaction.response.send_modal(modal)
        return True

    # --- Remove User: show modal ---
    if action == "remove_user":
        if not (has_support or can_manage):
            await interaction.response.send_message(
                "Only support staff can remove users from this ticket.",
                ephemeral=True,
            )
            return True
        modal = RemoveUserModal(channel_id=channel_id)
        await interaction.response.send_modal(modal)
        return True

    # --- Transcript: log messages, send file to creator + admin ---
    if action == "transcript":
        await interaction.response.defer(ephemeral=True)
        try:
            lines: list[str] = []
            lines.append(f"Transcript for #{channel.name}")
            lines.append("=" * 50)
            async for msg in channel.history(limit=500, oldest_first=True):
                ts = msg.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
                author = msg.author.display_name if msg.author else "Unknown"
                content = (msg.content or "(no text)").replace("\n", "\n  ")
                lines.append(f"[{ts}] {author}: {content}")
                if msg.attachments:
                    for a in msg.attachments:
                        lines.append(f"  [Attachment: {a.filename}]")

            content = "\n".join(lines)
            if len(content) > 800_000:
                content = content[:800_000] + "\n\n... (truncated)"
            buf = io.BytesIO(content.encode("utf-8"))
            buf.seek(0)
            file = discord.File(buf, filename=f"transcript-{channel.name}.txt")

            # Send to ticket creator (DM)
            creator_id = await _ticket_creator_id(guild.id, channel_id)
            sent_creator = False
            if creator_id:
                creator = guild.get_member(creator_id)
                if creator:
                    try:
                        await creator.send(
                            f"Transcript for your ticket **#{channel.name}**:",
                            file=discord.File(
                                io.BytesIO(content.encode("utf-8")),
                                filename=f"transcript-{channel.name}.txt",
                            ),
                        )
                        sent_creator = True
                    except discord.Forbidden:
                        logger.debug("Could not DM transcript to creator %s", creator_id)

            # Send to requester (staff)
            try:
                await member.send(
                    f"Transcript for ticket **#{channel.name}**:",
                    file=discord.File(
                        io.BytesIO(content.encode("utf-8")),
                        filename=f"transcript-{channel.name}.txt",
                    ),
                )
            except discord.Forbidden:
                pass

            # Optional: send to ticket-logs channel
            ticket_logs = discord.utils.get(guild.text_channels, name="ticket-logs")
            if ticket_logs:
                try:
                    await ticket_logs.send(
                        f"Transcript for **#{channel.name}** (requested by {member.mention}):",
                        file=file,
                    )
                except discord.Forbidden:
                    logger.warning("Could not send transcript to ticket-logs")

            reply = "Transcript generated and sent to your DMs."
            if sent_creator:
                reply += " The ticket creator was also sent a copy."
            await interaction.followup.send(reply, ephemeral=True)
            logger.info("Transcript generated for ticket %s", channel_id)
        except Exception as e:
            logger.exception("Error generating transcript for %s: %s", channel_id, e)
            await interaction.followup.send(
                "Failed to generate transcript.",
                ephemeral=True,
            )
        return True

    return False
