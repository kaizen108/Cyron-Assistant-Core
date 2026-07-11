"""Staff ticket slash commands."""

import logging
import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.utils.http_client import get_client
from bot.utils.ticket_logger import log_ticket_event

logger = logging.getLogger(__name__)

PRIORITY_EMOJI = {"low": "🟢", "medium": "🟡", "high": "🟠", "urgent": "🔴"}


async def _get_ticket_channel_data(guild_id: str, channel_id: str) -> dict | None:
    client = get_client()
    return await client.get_ticket(guild_id, channel_id)


async def _has_support(member: discord.Member, panel: dict | None = None) -> bool:
    """Check if member is support staff using panel's support_role_ids.
    
    Falls back to manage_channels permission if no panel or no support_role_ids configured.
    """
    if member.guild_permissions.manage_channels or member.guild_permissions.administrator:
        return True

    # Use panel's support_role_ids if available
    support_role_ids = []
    if panel:
        support_role_ids = panel.get("support_role_ids") or []
    
    if not support_role_ids:
        # Fallback: try to get panel from ticket data
        # If still no panel, check for any role named "support" as last resort
        return any(r.name.lower() == "support" for r in member.roles)
    
    member_role_ids = {str(r.id) for r in member.roles}
    return any(str(rid) in member_role_ids for rid in support_role_ids)


async def _get_panel_for_ticket(guild_id: str, ticket: dict | None) -> dict | None:
    """Fetch the panel for a ticket."""
    if not ticket or not ticket.get("panel_id"):
        return None
    client = get_client()
    return await client.get_panel(guild_id, ticket["panel_id"])


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
            return
        ticket = await _get_ticket_channel_data(str(interaction.guild.id), str(interaction.channel.id))
        if not ticket:
            await interaction.response.send_message("This is not a registered ticket channel.", ephemeral=True)
            return

        panel = await _get_panel_for_ticket(str(interaction.guild.id), ticket)
        member = interaction.user
        is_support = await _has_support(member, panel)
        is_creator = ticket.get("user_id") and int(ticket["user_id"]) == member.id

        users_can_close = panel.get("users_can_close", False) if panel else False

        if not is_support and not (users_can_close and is_creator):
            await interaction.response.send_message("You don't have permission to close this ticket.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        from bot.views.ticket_view import _do_close_ticket
        await _do_close_ticket(interaction, interaction.channel.id, member, reason=reason)

    @ticket_group.command(name="add", description="Add a user to this ticket")
    @app_commands.describe(user="User to add")
    async def ticket_add(self, interaction: discord.Interaction, user: discord.Member) -> None:
        ticket = await _get_ticket_channel_data(str(interaction.guild.id), str(interaction.channel.id))
        panel = await _get_panel_for_ticket(str(interaction.guild.id), ticket)
        if not await _has_support(interaction.user, panel):
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
        ticket = await _get_ticket_channel_data(str(interaction.guild.id), str(interaction.channel.id))
        panel = await _get_panel_for_ticket(str(interaction.guild.id), ticket)
        if not await _has_support(interaction.user, panel):
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
        ticket = await _get_ticket_channel_data(str(interaction.guild.id), str(interaction.channel.id))
        panel = await _get_panel_for_ticket(str(interaction.guild.id), ticket)
        if not await _has_support(interaction.user, panel):
            await interaction.response.send_message("Support only.", ephemeral=True)
            return
        await interaction.channel.edit(name=name[:100])
        await interaction.response.send_message(f"Channel renamed to `{name}`.", ephemeral=True)

    @ticket_group.command(name="move", description="Move this ticket to a different category")
    @app_commands.describe(category="Target category name")
    async def ticket_move(self, interaction: discord.Interaction, category: str) -> None:
        """Move ticket channel to a different Discord category."""
        if not interaction.guild:
            return
        ticket = await _get_ticket_channel_data(str(interaction.guild.id), str(interaction.channel.id))
        if not ticket:
            await interaction.response.send_message("This is not a registered ticket channel.", ephemeral=True)
            return

        panel = await _get_panel_for_ticket(str(interaction.guild.id), ticket)
        if not await _has_support(interaction.user, panel):
            await interaction.response.send_message("Support only.", ephemeral=True)
            return

        # Find the target category
        target_category = None
        for cat in interaction.guild.categories:
            if cat.name.lower() == category.lower():
                target_category = cat
                break

        if not target_category:
            await interaction.response.send_message(
                f"❌ Category `{category}` not found. Available categories: "
                + ", ".join(f"`{c.name}`" for c in interaction.guild.categories[:15]),
                ephemeral=True,
            )
            return

        # Check if category is full (Discord 50-channel limit)
        if len(target_category.channels) >= 50:
            await interaction.response.send_message(
                f"❌ Category `{target_category.name}` is full (50 channels max).",
                ephemeral=True,
            )
            return

        try:
            await interaction.channel.edit(category=target_category, reason=f"Ticket moved by {interaction.user}")
            await interaction.response.send_message(
                f"✅ Ticket moved to **{target_category.name}**."
            )
            try:
                await log_ticket_event(
                    self.bot, interaction.guild, "TICKET_MOVED",
                    interaction.channel, interaction.user,
                    extra={"Category": target_category.name}, panel=panel,
                )
            except Exception:
                pass
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I don't have permission to move channels. Check my role permissions.",
                ephemeral=True,
            )
        except Exception as e:
            logger.error("Error moving ticket: %s", e)
            await interaction.response.send_message(
                "❌ An error occurred while moving the ticket.",
                ephemeral=True,
            )

    @ticket_group.command(name="claim", description="Claim this ticket")
    async def ticket_claim(self, interaction: discord.Interaction) -> None:
        ticket = await _get_ticket_channel_data(str(interaction.guild.id), str(interaction.channel.id))
        panel = await _get_panel_for_ticket(str(interaction.guild.id), ticket)
        if not await _has_support(interaction.user, panel):
            await interaction.response.send_message("Support only.", ephemeral=True)
            return

        if not ticket:
            await interaction.response.send_message("Not a registered ticket.", ephemeral=True)
            return

        client = get_client()
        support_role_ids = (panel.get("support_role_ids") or []) if panel else []
        visibility = (panel.get("claiming_visibility") or "view_only") if panel else "view_only"

        await _apply_claim_permissions(interaction.channel, interaction.user, support_role_ids, visibility)
        await client.claim_ticket(str(interaction.guild.id), str(interaction.channel.id), str(interaction.user.id))
        await interaction.response.send_message(f"Ticket claimed by {interaction.user.mention}.")
        try:
            await log_ticket_event(self.bot, interaction.guild, "TICKET_CLAIMED", interaction.channel, interaction.user, panel=panel)
        except Exception:
            pass

    @ticket_group.command(name="unclaim", description="Unclaim this ticket")
    async def ticket_unclaim(self, interaction: discord.Interaction) -> None:
        ticket = await _get_ticket_channel_data(str(interaction.guild.id), str(interaction.channel.id))
        panel = await _get_panel_for_ticket(str(interaction.guild.id), ticket)
        if not await _has_support(interaction.user, panel):
            await interaction.response.send_message("Support only.", ephemeral=True)
            return

        client = get_client()
        support_role_ids = (panel.get("support_role_ids") or []) if panel else []
        await _revert_claim_permissions(interaction.channel, support_role_ids)
        await client.unclaim_ticket(str(interaction.guild.id), str(interaction.channel.id))
        await interaction.response.send_message("Ticket unclaimed.")
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
        ticket = await _get_ticket_channel_data(str(interaction.guild.id), str(interaction.channel.id))
        panel = await _get_panel_for_ticket(str(interaction.guild.id), ticket)
        if not await _has_support(interaction.user, panel):
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
        ticket = await _get_ticket_channel_data(str(interaction.guild.id), str(interaction.channel.id))
        if not ticket:
            await interaction.response.send_message("Not a registered ticket.", ephemeral=True)
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
        embed.add_field(name="AI Active", value="❌ Handed off" if ticket.get("human_handoff") else "✅ Active", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ticket_group.command(name="ai", description="Manage AI auto-reply for this ticket")
    @app_commands.describe(action="Resume or pause AI replies")
    @app_commands.choices(action=[
        app_commands.Choice(name="Resume", value="resume"),
        app_commands.Choice(name="Pause", value="pause"),
    ])
    async def ticket_ai(self, interaction: discord.Interaction, action: str) -> None:
        """Resume or pause AI auto-reply for this ticket."""
        if not interaction.guild:
            return
        ticket = await _get_ticket_channel_data(str(interaction.guild.id), str(interaction.channel.id))
        if not ticket:
            await interaction.response.send_message("This is not a registered ticket channel.", ephemeral=True)
            return

        panel = await _get_panel_for_ticket(str(interaction.guild.id), ticket)
        if not await _has_support(interaction.user, panel):
            await interaction.response.send_message("Support only.", ephemeral=True)
            return

        client = get_client()
        if action == "resume":
            await client.set_handoff(str(interaction.guild.id), str(interaction.channel.id), False)
            await interaction.response.send_message("✅ AI auto-reply **resumed** for this ticket.")
        else:
            await client.set_handoff(str(interaction.guild.id), str(interaction.channel.id), True)
            await interaction.response.send_message("⏸️ AI auto-reply **paused** for this ticket.")

    @ticket_group.command(name="requestclose", description="Ask the ticket creator to confirm closure")
    @app_commands.describe(reason="Optional reason", timeout="Minutes before auto-close (0 = no auto-close)")
    async def ticket_requestclose(self, interaction: discord.Interaction, reason: str | None = None, timeout: int = 0) -> None:
        ticket = await _get_ticket_channel_data(str(interaction.guild.id), str(interaction.channel.id))
        panel = await _get_panel_for_ticket(str(interaction.guild.id), ticket)
        if not await _has_support(interaction.user, panel):
            await interaction.response.send_message("Support only.", ephemeral=True)
            return

        if not ticket:
            await interaction.response.send_message("Not a registered ticket.", ephemeral=True)
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
                if btn_interaction.user.id != int(ticket.get("user_id", 0)) and not await _has_support(btn_interaction.user, panel):
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
                        client = get_client()
                        await client.close_ticket(
                            str(interaction.guild.id), str(interaction.channel.id),
                            str(interaction.user.id), reason="Auto-closed after timeout"
                        )
                        channel = interaction.guild.get_channel(interaction.channel.id)
                        if channel:
                            await channel.send("⏰ Ticket auto-closed after timeout.")
                            await channel.delete()
                    except Exception as e:
                        logger.warning("requestclose timeout auto-close failed: %s", e)

        await interaction.response.send_message(embed=embed, view=ConfirmView())

    @app_commands.command(name="new", description="Open a new support ticket")
    async def new_ticket(self, interaction: discord.Interaction) -> None:
        """Open a new support ticket using panel-based creation flow."""
        if not interaction.guild:
            return
        client = get_client()
        panels = await client.get_panels(str(interaction.guild.id))
        if not panels:
            await interaction.response.send_message("No ticket panels available.", ephemeral=True)
            return

        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Could not resolve member.", ephemeral=True)
            return

        if len(panels) == 1:
            # Single panel — directly open ticket via create_ticket_channel
            panel_id = panels[0]["id"]
            panel = await client.get_panel(str(interaction.guild.id), panel_id)
            if not panel:
                await interaction.response.send_message("Panel not found.", ephemeral=True)
                return

            if not panel.get("is_enabled", True):
                await interaction.response.send_message("This panel is currently disabled.", ephemeral=True)
                return

            # Check forms
            from bot.views.panel_view import DynamicTicketModal, create_ticket_channel
            if panel.get("forms_enabled") and panel.get("form_questions"):
                modal = DynamicTicketModal(panel, member)
                await interaction.response.send_modal(modal)
                return

            # Create directly
            await interaction.response.defer(ephemeral=True)
            await create_ticket_channel(interaction, panel, member, form_answers=None)
            return

        # Multiple panels — show select menu
        options = [discord.SelectOption(label=p["name"][:100], value=p["id"]) for p in panels[:25]]

        class PanelSelect(discord.ui.Select):
            def __init__(self_inner):
                super().__init__(placeholder="Select a ticket category…", options=options)

            async def callback(self_inner, sel_interaction: discord.Interaction):
                panel_id = self_inner.values[0]
                panel = await client.get_panel(str(interaction.guild.id), panel_id)
                if not panel:
                    await sel_interaction.response.send_message("Panel not found.", ephemeral=True)
                    return

                if not panel.get("is_enabled", True):
                    await sel_interaction.response.send_message("This panel is currently disabled.", ephemeral=True)
                    return

                sel_member = sel_interaction.user
                if not isinstance(sel_member, discord.Member):
                    await sel_interaction.response.send_message("Could not resolve member.", ephemeral=True)
                    return

                from bot.views.panel_view import DynamicTicketModal, create_ticket_channel
                if panel.get("forms_enabled") and panel.get("form_questions"):
                    modal = DynamicTicketModal(panel, sel_member)
                    await sel_interaction.response.send_modal(modal)
                    return

                await sel_interaction.response.defer(ephemeral=True)
                await create_ticket_channel(sel_interaction, panel, sel_member, form_answers=None)

        view = discord.ui.View(timeout=60)
        view.add_item(PanelSelect())
        embed = discord.Embed(title="Ticket Category", description="Select the most relevant category for your ticket.", color=discord.Colour.blurple())
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

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
