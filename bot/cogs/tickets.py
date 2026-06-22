"""Tickets cog for Discord bot."""

import logging
import discord
from discord import app_commands, ChannelType, PermissionOverwrite
from discord.ext import commands

from bot.utils.http_client import get_client
from bot.utils.ticket_registry import (
    register_ticket_channel,
)
from bot.views.panel_view import handle_panel_button
from bot.views.ticket_view import (
    build_ticket_embed,
    handle_ticket_interaction,
    TicketView,
)

logger = logging.getLogger(__name__)


class TicketsCog(commands.Cog):
    """Cog for ticket management and message relay."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.client = get_client()

    async def _fetch_open_ticket(self, guild_id: str, channel_id: int) -> dict | None:
        try:
            ticket_data = await self.client.get_ticket(guild_id, str(channel_id))
            if ticket_data and ticket_data.get("status") == "open":
                register_ticket_channel(
                    channel_id, ticket_data.get("panel_id")
                )
                return ticket_data
            return None
        except Exception as exc:
            logger.debug("get_ticket failed for channel %s: %s", channel_id, exc)
            return None

    @app_commands.command(
        name="create-ticket", description="Create a new support ticket"
    )
    async def create_ticket(self, interaction: discord.Interaction) -> None:
        """Legacy ticket flow (ticket-{user_id} naming)."""
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.", ephemeral=True
            )
            return

        try:
            tickets_category = discord.utils.get(
                interaction.guild.categories, name="Tickets"
            )
            if not tickets_category:
                await interaction.response.send_message(
                    "❌ Please run `/setup` first to create the Tickets category.",
                    ephemeral=True,
                )
                return

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

            support_role = discord.utils.get(interaction.guild.roles, name="Support")

            overwrites: dict[object, PermissionOverwrite] = {
                interaction.guild.default_role: PermissionOverwrite(view_channel=False),
                interaction.user: PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                ),
            }
            if support_role:
                overwrites[support_role] = PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                )
            overwrites[interaction.guild.me] = PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
            )

            ticket_channel = await tickets_category.create_text_channel(
                name=ticket_channel_name,
                overwrites=overwrites,
                reason=f"Ticket created by {interaction.user}",
            )

            ticket_number = await self.client.next_ticket_number(
                str(interaction.guild.id)
            )
            await self.client.open_ticket(
                guild_id=str(interaction.guild.id),
                channel_id=ticket_channel.id,
                user_id=user_id,
                bot_id=interaction.guild.me.id if interaction.guild.me else None,
                ticket_number=ticket_number,
                channel_name=ticket_channel_name,
            )
            register_ticket_channel(ticket_channel.id, None)

            await interaction.response.send_message(
                f"✅ Ticket created: {ticket_channel.mention}", ephemeral=True
            )

            embed_color = "#00b4ff"
            try:
                guild_data = await self.client.get_guild(str(interaction.guild.id))
                if guild_data and guild_data.get("embed_color"):
                    embed_color = guild_data["embed_color"]
            except Exception as e:
                logger.debug("Could not fetch guild embed_color: %s", e)

            embed = build_ticket_embed(
                embed_color=embed_color,
                created_by=interaction.user,
                channel_id=ticket_channel.id,
            )
            view = TicketView(ticket_channel.id, timeout=None)
            await ticket_channel.send(embed=embed, view=view)

            logger.info(
                "Created legacy ticket channel %s for user %s in guild %s",
                ticket_channel.id,
                user_id,
                interaction.guild.id,
            )

        except Exception as e:
            logger.error("Error creating ticket: %s", e, exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ An error occurred while creating the ticket.",
                    ephemeral=True,
                )

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction) -> None:
        """Route ticket panel buttons and ticket action buttons."""
        if interaction.type == discord.InteractionType.component:
            custom_id = (interaction.data or {}).get("custom_id", "")
            if custom_id.startswith("panel_open:"):
                await handle_panel_button(interaction)
                return

        handled = await handle_ticket_interaction(interaction, self.bot)
        if handled:
            return

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Relay user messages in registered ticket channels to the backend AI."""
        if message.author.bot:
            return
        if not message.guild or not message.channel:
            return
        if message.channel.type != ChannelType.text:
            return
        if not (message.content or "").strip():
            return

        guild_id = str(message.guild.id)
        channel_id = message.channel.id

        ticket_data = await self._fetch_open_ticket(guild_id, channel_id)
        if not ticket_data:
            return

        try:
            panel_id = ticket_data.get("panel_id")

            async with message.channel.typing():
                response_data = await self.client.relay_message(
                    guild_id=guild_id,
                    channel_id=str(channel_id),
                    user_id=str(message.author.id),
                    content=message.content,
                    message_id=str(message.id),
                    bot_id=str(self.bot.user.id),
                    panel_id=panel_id,
                )

            reply_text = response_data.get("reply", "AI is thinking...")
            await message.channel.send(reply_text)

            logger.info(
                "relay_ok guild=%s channel=%s panel_id=%s",
                guild_id,
                channel_id,
                panel_id,
            )

        except Exception as e:
            logger.error(
                "Error relaying message from channel %s: %s",
                channel_id,
                e,
                exc_info=True,
            )
            if "403" in str(e) or "different bot" in str(e).lower():
                return
            try:
                await message.channel.send(
                    "Sorry, I'm having trouble processing your message right now. "
                    "Please try again in a moment."
                )
            except Exception:
                logger.error("Failed to send error message to channel %s", channel_id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TicketsCog(bot))
    logger.info("TicketsCog loaded")
