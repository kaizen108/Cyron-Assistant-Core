"""Tickets cog for Discord bot."""

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
        # channel_id -> panel_id string cache (populated on first message, lives for session)
        self._panel_id_cache: dict[int, str | None] = {}

    @app_commands.command(
        name="create-ticket", description="Create a new support ticket"
    )
    async def create_ticket(self, interaction: discord.Interaction) -> None:
        """
        Create a new private ticket channel.

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

            await interaction.response.defer(ephemeral=True)

            # Check if user already has an open ticket
            user_id = interaction.user.id
            ticket_channel_name = f"ticket-{user_id}"
            for channel in tickets_category.channels:
                if (
                    channel.name == ticket_channel_name
                    and channel.type == ChannelType.text
                ):
                    await interaction.followup.send(
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

            await interaction.followup.send(
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
            if interaction.response.is_done():
                await interaction.followup.send(
                    "❌ An error occurred while creating the ticket. "
                    "Please check bot permissions.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "❌ An error occurred while creating the ticket. "
                    "Please check bot permissions.",
                    ephemeral=True,
                )

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction) -> None:
        """Route ticket panel button clicks (persistent across restarts via custom_id)."""
        handled = await handle_ticket_interaction(interaction, self.bot)
        if handled:
            return

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """
        Listen for messages in ticket channels and relay them to backend.

        Only processes messages in channels starting with "ticket-".
        Ignores bot messages.
        """
        # Ignore bot messages
        if message.author.bot:
            return

        # Ignore DMs
        if not message.guild or not message.channel:
            return

        # Only process messages in ticket channels
        if not message.channel.name.startswith("ticket-"):
            return

        # Only process text channels
        if message.channel.type != ChannelType.text:
            return

        try:
            logger.debug(
                f"Processing message in ticket channel {message.channel.id} "
                f"from user {message.author.id}"
            )

            # Resolve panel_id for this channel (Option B: from ticket DB row via backend)
            if message.channel.id not in self._panel_id_cache:
                try:
                    ticket_data = await self.client.get_ticket(
                        str(message.guild.id), str(message.channel.id)
                    )
                    self._panel_id_cache[message.channel.id] = (
                        ticket_data.get("panel_id") if ticket_data else None
                    )
                except Exception:
                    self._panel_id_cache[message.channel.id] = None

            # Show "Cyron Assistant is typing..." while waiting for the backend
            async with message.channel.typing():
                response_data = await self.client.relay_message(
                    guild_id=str(message.guild.id),
                    channel_id=str(message.channel.id),
                    user_id=str(message.author.id),
                    content=message.content,
                    message_id=str(message.id),
                    bot_id=str(self.bot.user.id),
                    panel_id=self._panel_id_cache.get(message.channel.id),
                )

            # Send response as plain text (like a normal user message)
            reply_text = response_data.get("reply", "AI is thinking...")
            await message.channel.send(reply_text)

            logger.debug(
                f"Successfully relayed and responded to message in "
                f"channel {message.channel.id}"
            )

        except Exception as e:
            logger.error(
                f"Error relaying message from channel {message.channel.id}: {e}",
                exc_info=True,
            )
            # Don't send error message if backend rejected due to bot isolation (403)
            if "403" in str(e) or "different bot" in str(e).lower():
                return
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

