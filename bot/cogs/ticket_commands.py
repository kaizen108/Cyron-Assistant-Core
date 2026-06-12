"""Staff ticket slash commands."""

import logging
import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.utils.http_client import get_client
from bot.utils.interactions import defer_ephemeral, defer_if_needed, reply
from bot.utils.ticket_logger import log_ticket_event

logger = logging.getLogger(__name__)

PRIORITY_EMOJI = {"low": "🟢", "medium": "🟡", "high": "🟠", "urgent": "🔴"}


async def _get_ticket_channel_data(guild_id: str, channel_id: str) -> dict | None:
    client = get_client()
    return await client.get_ticket(guild_id, channel_id)


def _has_support(member: discord.Member) -> bool:
    return any(r.name.lower() == "support" for r in member.roles) or member.guild_permissions.manage_channels


async def _apply_claim_permissions(channel: discord.TextChannel, claimer: discord.Member,
                                   support_role_ids: list, visibility: str) -> None:
    if visibility == "full_access":
        return
    elif visibility == "only_claimer":
        for rid in support_role_ids:
            role = channel.guild.get_role(int(rid))
            if role:
                await channel.set_permissions(role, view_channel=False)
        await channel.set_permissions(claimer, view_channel=True, send_messages=True, read_message_history=True)
    elif visibility == "view_only":
        for rid in support_role_ids:
            role = channel.guild.get_role(int(rid))
            if role:
                await channel.set_permissions(role, view_channel=True, send_messages=False)
        await channel.set_permissions(claimer, view_channel=True, send_messages=True, read_message_history=True)


async def _revert_claim_permissions(channel: discord.TextChannel, support_role_ids: list) -> None:
    for rid in support_role_ids:
        role = channel.guild.get_role(int(rid))
        if role:
            await channel.set_permissions(role, view_channel=True, send_messages=True, read_message_history=True)


class TicketCommandsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.autoclose_task.start()

    def cog_unload(self):
        self.autoclose_task.cancel()

    ticket_group = app_commands.Group(name="ticket", description="Ticket management commands")

    @ticket_group.command(name="close", description="Close this ticket")
    @app_commands.describe(reason="Reason for closing")
    async def ticket_close(self, interaction: discord.Interaction, reason: str | None = None) -> None:
        if not interaction.guild:
            await reply(interaction, "This command can only be used in a server.")
            return

        await defer_ephemeral(interaction)

        ticket = await _get_ticket_channel_data(str(interaction.guild.id), str(interaction.channel.id))
        if not ticket:
            await reply(interaction, "This is not a registered ticket channel.")
            return

        member = interaction.user
        is_support = _has_support(member)
        is_creator = ticket.get("user_id") and int(ticket["user_id"]) == member.id

        client = get_client()
        panel = None
        if ticket.get("panel_id"):
            panel = await client.get_panel(str(interaction.guild.id), ticket["panel_id"])
        users_can_close = panel.get("users_can_close", False) if panel else False

        if not is_support and not (users_can_close and is_creator):
            await reply(interaction, "You don't have permission to close this ticket.")
            return

        from bot.views.ticket_view import _do_close_ticket
        await _do_close_ticket(interaction, interaction.channel.id, member, reason=reason)

    @ticket_group.command(name="add", description="Add a user to this ticket")
    @app_commands.describe(user="User to add")
    async def ticket_add(self, interaction: discord.Interaction, user: discord.Member) -> None:
        if not _has_support(interaction.user):
            await interaction.response.send_message("Support only.", ephemeral=True)
            return
        await interaction.channel.set_permissions(user, view_channel=True, send_messages=True, read_message_history=True)
        await interaction.response.send_message(f"Added {user.mention} to the ticket.")
        try:
            await log_ticket_event(self.bot, interaction.guild, "USER_ADDED", interaction.channel, interaction.user, extra={"User": user.mention})
        except Exception:
            pass

    @ticket_group.command(name="remove", description="Remove a user from this ticket")
    @app_commands.describe(user="User to remove")
    async def ticket_remove(self, interaction: discord.Interaction, user: discord.Member) -> None:
        if not _has_support(interaction.user):
            await interaction.response.send_message("Support only.", ephemeral=True)
            return
        await interaction.channel.set_permissions(user, view_channel=False)
        await interaction.response.send_message(f"Removed {user.mention} from the ticket.")
        try:
            await log_ticket_event(self.bot, interaction.guild, "USER_REMOVED", interaction.channel, interaction.user, extra={"User": user.mention})
        except Exception:
            pass

    @ticket_group.command(name="rename", description="Rename this ticket channel")
    @app_commands.describe(name="New channel name")
    async def ticket_rename(self, interaction: discord.Interaction, name: str) -> None:
        if not _has_support(interaction.user):
            await interaction.response.send_message("Support only.", ephemeral=True)
            return
        await interaction.channel.edit(name=name[:100])
        await interaction.response.send_message(f"Channel renamed to `{name}`.", ephemeral=True)

    @ticket_group.command(name="claim", description="Claim this ticket")
    async def ticket_claim(self, interaction: discord.Interaction) -> None:
        if not _has_support(interaction.user):
            await reply(interaction, "Support only.")
            return

        await defer_if_needed(interaction, ephemeral=False)

        client = get_client()
        ticket = await _get_ticket_channel_data(str(interaction.guild.id), str(interaction.channel.id))
        if not ticket:
            await reply(interaction, "Not a registered ticket.", ephemeral=True)
            return

        panel = None
        if ticket.get("panel_id"):
            panel = await client.get_panel(str(interaction.guild.id), ticket["panel_id"])

        support_role_ids = (panel.get("support_role_ids") or []) if panel else []
        visibility = (panel.get("claiming_visibility") or "view_only") if panel else "view_only"

        await _apply_claim_permissions(interaction.channel, interaction.user, support_role_ids, visibility)
        await client.claim_ticket(str(interaction.guild.id), str(interaction.channel.id), str(interaction.user.id))
        await reply(interaction, f"Ticket claimed by {interaction.user.mention}.", ephemeral=False)
        try:
            await log_ticket_event(self.bot, interaction.guild, "TICKET_CLAIMED", interaction.channel, interaction.user, panel=panel)
        except Exception:
            pass

    @ticket_group.command(name="unclaim", description="Unclaim this ticket")
    async def ticket_unclaim(self, interaction: discord.Interaction) -> None:
        if not _has_support(interaction.user):
            await reply(interaction, "Support only.")
            return

        await defer_if_needed(interaction, ephemeral=False)

        client = get_client()
        ticket = await _get_ticket_channel_data(str(interaction.guild.id), str(interaction.channel.id))
        panel = None
        if ticket and ticket.get("panel_id"):
            panel = await client.get_panel(str(interaction.guild.id), ticket["panel_id"])

        support_role_ids = (panel.get("support_role_ids") or []) if panel else []
        await _revert_claim_permissions(interaction.channel, support_role_ids)
        await client.unclaim_ticket(str(interaction.guild.id), str(interaction.channel.id))
        await reply(interaction, "Ticket unclaimed.", ephemeral=False)
        try:
            await log_ticket_event(self.bot, interaction.guild, "TICKET_UNCLAIMED", interaction.channel, interaction.user, panel=panel)
        except Exception:
            pass

    @ticket_group.command(name="priority", description="Set ticket priority")
    @app_commands.describe(level="Priority level")
    @app_commands.choices(level=[
        app_commands.Choice(name="Low", value="low"),
        app_commands.Choice(name="Medium", value="medium"),
        app_commands.Choice(name="High", value="high"),
        app_commands.Choice(name="Urgent", value="urgent"),
    ])
    async def ticket_priority(self, interaction: discord.Interaction, level: str) -> None:
        if not _has_support(interaction.user):
            await interaction.response.send_message("Support only.", ephemeral=True)
            return

        emoji = PRIORITY_EMOJI.get(level, "")
        new_name = f"{emoji}-{interaction.channel.name}"[:100]
        await interaction.channel.edit(name=new_name)
        await get_client().set_ticket_priority(str(interaction.guild.id), str(interaction.channel.id), level)
        await interaction.response.send_message(f"Priority set to **{level}**.")
        try:
            await log_ticket_event(self.bot, interaction.guild, "PRIORITY_CHANGED", interaction.channel, interaction.user, extra={"Priority": f"{emoji} {level}"})
        except Exception:
            pass

    @ticket_group.command(name="info", description="Show ticket information")
    async def ticket_info(self, interaction: discord.Interaction) -> None:
        await defer_ephemeral(interaction)

        ticket = await _get_ticket_channel_data(str(interaction.guild.id), str(interaction.channel.id))
        if not ticket:
            await reply(interaction, "Not a registered ticket.")
            return

        embed = discord.Embed(title="Ticket Info", color=discord.Colour.blurple())
        embed.add_field(name="ID", value=str(ticket.get("id", "—"))[:20], inline=True)
        embed.add_field(name="Status", value=ticket.get("status", "—"), inline=True)
        embed.add_field(name="Number", value=f"#{ticket.get('ticket_number', '—')}", inline=True)
        if ticket.get("user_id"):
            member = interaction.guild.get_member(int(ticket["user_id"]))
            embed.add_field(name="Creator", value=member.mention if member else str(ticket["user_id"]), inline=True)
        if ticket.get("claimed_by_user_id"):
            claimer = interaction.guild.get_member(int(ticket["claimed_by_user_id"]))
            embed.add_field(name="Claimed by", value=claimer.mention if claimer else str(ticket["claimed_by_user_id"]), inline=True)
        if ticket.get("priority"):
            embed.add_field(name="Priority", value=f"{PRIORITY_EMOJI.get(ticket['priority'], '')} {ticket['priority']}", inline=True)
        await reply(interaction, embed=embed)

    @ticket_group.command(name="requestclose", description="Ask the ticket creator to confirm closure")
    @app_commands.describe(reason="Optional reason", timeout="Minutes before auto-close (0 = no auto-close)")
    async def ticket_requestclose(self, interaction: discord.Interaction, reason: str | None = None, timeout: int = 0) -> None:
        if not _has_support(interaction.user):
            await reply(interaction, "Support only.")
            return

        await defer_if_needed(interaction, ephemeral=False)

        ticket = await _get_ticket_channel_data(str(interaction.guild.id), str(interaction.channel.id))
        if not ticket:
            await reply(interaction, "Not a registered ticket.", ephemeral=True)
            return

        embed = discord.Embed(
            title="Ticket Close Request",
            description=f"{interaction.user.mention} has requested to close this ticket.\n\nDo you want to **confirm** or **cancel**?",
            color=discord.Colour.orange(),
        )
        if reason:
            embed.add_field(name="Reason", value=reason)

        class ConfirmView(discord.ui.View):
            def __init__(self_inner):
                super().__init__(timeout=timeout * 60 if timeout > 0 else None)

            @discord.ui.button(label="✅ Confirm", style=discord.ButtonStyle.danger)
            async def confirm(self_inner, btn_interaction: discord.Interaction, button):
                if btn_interaction.user.id != int(ticket.get("user_id", 0)) and not _has_support(btn_interaction.user):
                    await btn_interaction.response.send_message("Only the ticket creator can confirm.", ephemeral=True)
                    return
                await btn_interaction.response.defer()
                from bot.views.ticket_view import _do_close_ticket
                await _do_close_ticket(btn_interaction, interaction.channel.id, btn_interaction.user, reason=reason)

            @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
            async def cancel(self_inner, btn_interaction: discord.Interaction, button):
                await btn_interaction.response.send_message("Close request cancelled.", ephemeral=False)
                self_inner.stop()

            async def on_timeout(self_inner):
                if timeout > 0:
                    try:
                        from bot.views.ticket_view import _do_close_ticket
                        channel = interaction.guild.get_channel(interaction.channel.id)
                        if channel:
                            fake_interaction = interaction
                            await get_client().close_ticket(
                                str(interaction.guild.id), str(interaction.channel.id),
                                str(interaction.user.id), reason="Auto-closed after timeout"
                            )
                            await channel.send("⏰ Ticket auto-closed after timeout.")
                            await channel.delete()
                    except Exception as e:
                        logger.warning("requestclose timeout auto-close failed: %s", e)

        await reply(interaction, embed=embed, view=ConfirmView(), ephemeral=False)

    @app_commands.command(name="new", description="Open a new support ticket")
    async def new_ticket(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await reply(interaction, "This command can only be used in a server.")
            return

        await defer_ephemeral(interaction)

        client = get_client()
        panels = await client.get_panels(str(interaction.guild.id))
        if not panels:
            await reply(interaction, "No ticket panels available.")
            return

        if len(panels) == 1:
            interaction.data = {"custom_id": f"panel_open:{panels[0]['id']}"}
            from bot.views.panel_view import handle_panel_button
            await handle_panel_button(interaction)
            return

        options = [discord.SelectOption(label=p["name"][:100], value=p["id"]) for p in panels[:25]]

        class PanelSelect(discord.ui.Select):
            def __init__(self):
                super().__init__(placeholder="Select a ticket category…", options=options)

            async def callback(self_, sel_interaction: discord.Interaction):
                await defer_ephemeral(sel_interaction)
                sel_interaction.data = {"custom_id": f"panel_open:{self_.values[0]}"}
                from bot.views.panel_view import handle_panel_button
                await handle_panel_button(sel_interaction)

        view = discord.ui.View(timeout=60)
        view.add_item(PanelSelect())
        embed = discord.Embed(title="Ticket Category", description="Select the most relevant category for your ticket.", color=discord.Colour.blurple())
        await reply(interaction, embed=embed, view=view)

    @tasks.loop(hours=1)
    async def autoclose_task(self) -> None:
        """Check for stale tickets and warn/close them."""
        try:
            client = get_client()
            stale = await client.get_stale_tickets()
            for item in stale:
                guild = self.bot.get_guild(int(item["guild_id"]))
                if not guild:
                    continue
                channel = guild.get_channel(int(item["channel_id"]))
                if not channel or not isinstance(channel, discord.TextChannel):
                    continue

                if item["action"] == "warn":
                    await channel.send(
                        f"⚠️ This ticket will be automatically closed in **{item['hours_remaining']} hours** due to inactivity. "
                        "Send a message to cancel."
                    )
                elif item["action"] == "close":
                    await client.close_ticket(
                        str(item["guild_id"]), str(item["channel_id"]),
                        closed_by_user_id=str(self.bot.user.id),
                        reason="Auto-closed due to inactivity",
                    )
                    try:
                        await channel.send("🔒 Ticket closed automatically due to inactivity.")
                        await channel.delete()
                    except Exception:
                        pass
        except Exception as e:
            logger.warning("autoclose_task error: %s", e)

    @autoclose_task.before_loop
    async def before_autoclose(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        """Close open tickets when the creator leaves the server."""
        try:
            client = get_client()
            guild_data = await client.get_guild(str(member.guild.id))
            if not guild_data or not guild_data.get("close_on_user_leave", True):
                return
            open_tickets = await client.get_open_tickets_by_user(str(member.guild.id), str(member.id))
            for ticket in open_tickets:
                channel = member.guild.get_channel(int(ticket["channel_id"]))
                if channel:
                    await client.close_ticket(str(member.guild.id), str(ticket["channel_id"]),
                                              closed_by_user_id=str(self.bot.user.id),
                                              reason="User left the server")
                    try:
                        await channel.send(f"Ticket creator {member} has left the server. Ticket closed automatically.")
                        await channel.delete()
                    except Exception:
                        pass
        except Exception as e:
            logger.warning("on_member_remove ticket close failed: %s", e)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TicketCommandsCog(bot))
    logger.info("TicketCommandsCog loaded")
