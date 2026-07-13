"""Tickets cog for Discord bot — Phase 2 AI auto-reply logic."""

import logging
import discord
from discord import app_commands, ChannelType, PermissionOverwrite
from discord.ext import commands

from bot.utils.http_client import get_client
from bot.views.ticket_view import (
    build_ticket_embed,
    handle_ticket_interaction,
    TicketView,
)

logger = logging.getLogger(__name__)


class TicketsCog(commands.Cog):
    """Cog for ticket management and message relay."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the tickets cog."""
        self.bot = bot
        self.client = get_client()
        # channel_id -> ticket data cache (populated on first message, lives for session)
        self._ticket_cache: dict[int, dict | None] = {}
        # channel_id -> panel data cache
        self._panel_cache: dict[int, dict | None] = {}

    async def _get_ticket_data(self, guild_id: str, channel_id: int) -> dict | None:
        """Get ticket data with caching."""
        if channel_id in self._ticket_cache:
            return self._ticket_cache[channel_id]
        try:
            data = await self.client.get_ticket(guild_id, str(channel_id))
        except Exception as exc:
            logger.warning(
                "get_ticket failed guild=%s channel=%s: %s",
                guild_id,
                channel_id,
                exc,
            )
            return None
        self._ticket_cache[channel_id] = data
        return data

    async def _ensure_legacy_ticket_registered(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
        user_id: int,
    ) -> dict | None:
        """Register old /create-ticket channels that predate backend sync."""
        if not channel.name.startswith("ticket-"):
            return None
        try:
            ticket_number = await self.client.next_ticket_number(str(guild.id))
            opened = await self.client.open_ticket(
                guild_id=str(guild.id),
                channel_id=channel.id,
                user_id=user_id,
                panel_id=None,
                bot_id=self.bot.user.id if self.bot.user else None,
                ticket_number=ticket_number,
                channel_name=channel.name,
            )
            if not opened.get("id"):
                return None
            self._ticket_cache.pop(channel.id, None)
            return await self._get_ticket_data(str(guild.id), channel.id)
        except Exception as exc:
            logger.warning(
                "legacy ticket auto-register failed channel=%s: %s",
                channel.id,
                exc,
            )
            return None

    def _should_ai_reply(self, ticket_data: dict, panel: dict | None) -> bool:
        """Return True when this ticket channel should relay to the AI backend."""
        if ticket_data.get("human_handoff"):
            return False
        if panel:
            if not panel.get("ai_auto_reply"):
                return False
            if not panel.get("ai_context_id") and not panel.get("general_ai_enabled"):
                return False
            return True
        # Legacy /create-ticket tickets — relay using guild general rules
        return True

    async def _get_panel_data(self, guild_id: str, panel_id: str) -> dict | None:
        """Get panel data with caching (keyed by channel for quick lookup)."""
        try:
            return await self.client.get_panel(guild_id, panel_id)
        except Exception:
            return None

    def _is_staff(self, member: discord.Member, panel: dict | None) -> bool:
        """Check if member is support staff using panel's support_role_ids.
        
        Only uses panel's configured support_role_ids.
        Falls back to 'Support' role name ONLY if no panel or no support_role_ids configured.
        Does NOT treat admins/owners as staff for AI handoff purposes.
        """
        support_role_ids = []
        if panel:
            support_role_ids = panel.get("support_role_ids") or []

        if not support_role_ids:
            # No support roles configured — fall back to role named "Support"
            return any(r.name.lower() == "support" for r in member.roles)

        member_role_ids = {str(r.id) for r in member.roles}
        return any(str(rid) in member_role_ids for rid in support_role_ids)

    @app_commands.command(
        name="create-ticket", description="Create a new support ticket"
    )
    async def create_ticket(self, interaction: discord.Interaction) -> None:
        """
        Create a new private ticket channel (legacy command).

        Creates a channel named "ticket-{user_id}" in the "Tickets" category.
        """
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.", ephemeral=True
            )
            return

        try:
            # Find or create Tickets category
            tickets_category = None
            for category in interaction.guild.categories:
                if category.name.lower() == "tickets":
                    tickets_category = category
                    break

            if not tickets_category:
                await interaction.response.send_message(
                    "❌ Please run `/setup` first to create the Tickets category.",
                    ephemeral=True,
                )
                return

            # Check if user already has an open ticket
            user_id = interaction.user.id
            ticket_channel_name = f"ticket-{user_id}"
            for channel in tickets_category.channels:
                if (
                    channel.name == ticket_channel_name
                    and channel.type == ChannelType.text
                ):
                    await interaction.response.send_message(
                        f"❌ You already have an open ticket: {channel.mention}",
                        ephemeral=True,
                    )
                    return

            # Find support role
            support_role = None
            for role in interaction.guild.roles:
                if role.name.lower() == "support":
                    support_role = role
                    break

            # Create permission overwrites
            overwrites: dict[object, PermissionOverwrite] = {
                interaction.guild.default_role: PermissionOverwrite(view_channel=False),
                interaction.user: PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                ),
            }

            # Add support role permissions if it exists
            if support_role:
                overwrites[support_role] = PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                )

            # Add bot permissions
            overwrites[interaction.guild.me] = PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
            )

            # Create ticket channel
            ticket_channel = await tickets_category.create_text_channel(
                name=ticket_channel_name,
                overwrites=overwrites,
                reason=f"Ticket created by {interaction.user}",
            )

            # Register ticket in backend so AI relay and dashboard tracking work
            try:
                ticket_number = await self.client.next_ticket_number(
                    str(interaction.guild.id)
                )
                opened = await self.client.open_ticket(
                    guild_id=str(interaction.guild.id),
                    channel_id=ticket_channel.id,
                    user_id=user_id,
                    panel_id=None,
                    bot_id=self.bot.user.id if self.bot.user else None,
                    ticket_number=ticket_number,
                    channel_name=ticket_channel_name,
                )
                if not opened.get("id"):
                    logger.warning(
                        "Legacy ticket backend registration returned no id (channel=%s)",
                        ticket_channel.id,
                    )
            except Exception as e:
                logger.warning(
                    "Failed to register legacy ticket in backend (channel=%s): %s",
                    ticket_channel.id,
                    e,
                )

            await interaction.response.send_message(
                f"✅ Ticket created: {ticket_channel.mention}", ephemeral=True
            )

            # Fetch guild settings (embed_color) from backend
            embed_color = "#00b4ff"
            try:
                guild_data = await self.client.get_guild(str(interaction.guild.id))
                if guild_data and guild_data.get("embed_color"):
                    embed_color = guild_data["embed_color"]
            except Exception as e:
                logger.debug("Could not fetch guild embed_color: %s", e)

            # Send premium welcome embed + persistent view
            embed = build_ticket_embed(
                embed_color=embed_color,
                created_by=interaction.user,
                channel_id=ticket_channel.id,
            )
            view = TicketView(ticket_channel.id, timeout=None)
            await ticket_channel.send(embed=embed, view=view)

            logger.info(
                f"Created ticket channel {ticket_channel.id} for user {user_id} "
                f"in guild {interaction.guild.id}"
            )

        except Exception as e:
            logger.error(f"Error creating ticket: {e}", exc_info=True)
            await interaction.response.send_message(
                "❌ An error occurred while creating the ticket. "
                "Please check bot permissions.",
                ephemeral=True,
            )

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction) -> None:
        """Route ticket panel button clicks (persistent across restarts via custom_id)."""
        if interaction.type != discord.InteractionType.component:
            return
        custom_id = (interaction.data or {}).get("custom_id", "")
        # Only handle ticket: prefixed buttons (not panel_open:)
        if not custom_id.startswith("ticket:"):
            return
        # Skip if already responded
        if interaction.response.is_done():
            return
        handled = await handle_ticket_interaction(interaction, self.bot)
        if handled:
            return

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """
        Phase 2 AI auto-reply logic.

        Check order:
        1. Is this a registered ticket channel?
        2. Does the panel have ai_auto_reply = True?
        3. Does the panel have ai_context_id OR General Rules enabled?
        4. Is ticket human_handoff = False?
        5. Is sender NOT staff (check support_role_ids)?
        6. All clear → relay to backend with panel_id.

        If sender IS staff → set human_handoff = True (AI permanently disabled).
        """
        # Ignore bot messages
        if message.author.bot:
            return

        # Ignore DMs
        if not message.guild or not message.channel:
            return

        # Only process text channels
        if message.channel.type != ChannelType.text:
            return

        # Get ticket data for this channel
        ticket_data = await self._get_ticket_data(str(message.guild.id), message.channel.id)

        # Auto-register legacy ticket channels created before backend sync existed
        if (
            not ticket_data
            and isinstance(message.channel, discord.TextChannel)
            and isinstance(message.author, discord.Member)
        ):
            ticket_data = await self._ensure_legacy_ticket_registered(
                message.guild,
                message.channel,
                message.author.id,
            )

        # Not a registered ticket channel — skip
        if not ticket_data:
            logger.debug(
                "on_message skip: channel %s is not a registered ticket",
                message.channel.id,
            )
            return

        # Get panel data
        panel_id = ticket_data.get("panel_id")
        panel = None
        if panel_id:
            panel = await self._get_panel_data(str(message.guild.id), panel_id)

        # Check if sender is staff
        member = message.author
        if not isinstance(member, discord.Member):
            return

        is_staff = self._is_staff(member, panel)

        # If staff sends a message → trigger human handoff
        if is_staff:
            if not ticket_data.get("human_handoff"):
                try:
                    await self.client.set_handoff(
                        str(message.guild.id), str(message.channel.id), True
                    )
                    # Invalidate cache
                    self._ticket_cache.pop(message.channel.id, None)
                    logger.info(
                        "Human handoff triggered: staff %s wrote in channel %s",
                        member.id, message.channel.id,
                    )
                except Exception as e:
                    logger.warning("Failed to set human_handoff: %s", e)
            return  # Don't relay staff messages

        if not self._should_ai_reply(ticket_data, panel):
            logger.info(
                "on_message skip: AI disabled channel=%s panel=%s handoff=%s ai_auto_reply=%s",
                message.channel.id,
                panel_id,
                ticket_data.get("human_handoff"),
                (panel or {}).get("ai_auto_reply"),
            )
            return

        # All checks passed → relay to AI backend
        try:
            logger.debug(
                "AI relay: channel=%s user=%s panel=%s",
                message.channel.id, message.author.id, panel_id,
            )

            # Show typing indicator while waiting
            async with message.channel.typing():
                response_data = await self.client.relay_message(
                    guild_id=str(message.guild.id),
                    channel_id=str(message.channel.id),
                    user_id=str(message.author.id),
                    content=message.content,
                    message_id=str(message.id),
                    bot_id=str(self.bot.user.id),
                    panel_id=panel_id,
                )

            # Check if AI response indicates low confidence → human handoff
            reply_text = response_data.get("reply", "")
            low_confidence = response_data.get("low_confidence", False)
            top_similarity = response_data.get("top_similarity", 0.0)

            # Handoff when AI truly cannot help:
            # - low_confidence AND no relevant knowledge found (similarity near zero)
            # - OR AI returned completely empty reply
            should_handoff = (
                (low_confidence and top_similarity < 0.25 and not reply_text.strip())
                or (not reply_text.strip())
            )

            if should_handoff:
                try:
                    await self.client.set_handoff(
                        str(message.guild.id), str(message.channel.id), True
                    )
                    self._ticket_cache.pop(message.channel.id, None)
                except Exception:
                    pass

                # Send handoff message and ping support roles
                handoff_msg = "I'm connecting you with a human agent. A support team member will assist you shortly."
                pings = []
                for role_id in ((panel or {}).get("support_role_ids") or []):
                    role = message.guild.get_role(int(role_id))
                    if role:
                        pings.append(role.mention)

                ping_content = " ".join(pings) if pings else ""
                if ping_content:
                    await message.channel.send(f"{handoff_msg}\n\n{ping_content}")
                else:
                    await message.channel.send(handoff_msg)

                logger.info(
                    "Low confidence AI handoff: channel=%s similarity=%.3f",
                    message.channel.id, top_similarity,
                )
                return

            # Send AI reply
            if reply_text:
                # Split long messages (Discord 2000 char limit)
                if len(reply_text) <= 2000:
                    await message.channel.send(reply_text)
                else:
                    chunks = [reply_text[i:i+1990] for i in range(0, len(reply_text), 1990)]
                    for chunk in chunks:
                        await message.channel.send(chunk)

            logger.debug(
                "AI replied in channel %s (tokens: %s)",
                message.channel.id,
                response_data.get("token_usage"),
            )

        except Exception as e:
            logger.error(
                "Error in AI relay for channel %s: %s",
                message.channel.id, e,
                exc_info=True,
            )
            err = str(e).lower()
            if "401" in err or "invalid bot credentials" in err:
                try:
                    await message.channel.send(
                        "⚠️ Bot cannot reach the AI backend (authentication error). "
                        "Please ask a server admin to verify `BOT_API_KEY` matches on both "
                        "the API and bot containers."
                    )
                except Exception:
                    pass
                return
            if "403" in err or "different bot" in err:
                logger.error(
                    "AI relay blocked by bot isolation channel=%s bot=%s",
                    message.channel.id,
                    self.bot.user.id if self.bot.user else None,
                )
                return
            # Don't spam error messages for every failure
            try:
                await message.channel.send(
                    "Sorry, I'm having trouble processing your message right now. "
                    "Please try again in a moment."
                )
            except Exception:
                logger.error("Failed to send error message to channel")


async def setup(bot: commands.Bot) -> None:
    """Add the tickets cog to the bot."""
    await bot.add_cog(TicketsCog(bot))
    logger.info("TicketsCog loaded")
