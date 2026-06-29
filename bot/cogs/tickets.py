"""Tickets cog for Discord bot."""

import logging
import discord
from discord import app_commands, ChannelType, PermissionOverwrite
from discord.ext import commands

from bot.utils.http_client import get_client
from bot.utils.support_roles import member_has_support_roles
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

HANDOFF_MESSAGE = "I'm connecting you with a human agent."


class TicketsCog(commands.Cog):
    """Cog for ticket management and message relay."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.client = get_client()

    async def _try_register_orphan_ticket(
        self,
        message: discord.Message,
        guild_id: str,
        channel_id: int,
    ) -> dict | None:
        """Register a ticket channel that exists in Discord but not in the DB."""
        channel = message.channel
        if not isinstance(channel, discord.TextChannel):
            return None

        name = channel.name
        user_id = message.author.id

        if name.startswith("ticket-"):
            suffix = name.split("ticket-", 1)[1]
            try:
                user_id = int(suffix)
            except ValueError:
                pass
        elif channel.category and channel.category.name.lower() == "tickets":
            pass
        else:
            return None

        me = message.guild.me if message.guild else None
        result = await self.client.open_ticket(
            guild_id=guild_id,
            channel_id=channel_id,
            user_id=user_id,
            bot_id=me.id if me else None,
            channel_name=name,
        )
        if not result.get("id"):
            logger.warning(
                "orphan ticket registration failed guild=%s channel=%s",
                guild_id,
                channel_id,
            )
            return None

        logger.info("auto-registered orphan ticket guild=%s channel=%s", guild_id, channel_id)
        return await self.client.get_ticket(guild_id, str(channel_id))

    async def _fetch_open_ticket(
        self,
        guild_id: str,
        channel_id: int,
        message: discord.Message | None = None,
    ) -> dict | None:
        try:
            ticket_data = await self.client.get_ticket(guild_id, str(channel_id))
            if ticket_data and ticket_data.get("status") == "open":
                register_ticket_channel(
                    channel_id, ticket_data.get("panel_id")
                )
                return ticket_data

            if message is not None:
                ticket_data = await self._try_register_orphan_ticket(
                    message, guild_id, channel_id
                )
                if ticket_data and ticket_data.get("status") == "open":
                    register_ticket_channel(
                        channel_id, ticket_data.get("panel_id")
                    )
                    return ticket_data

            return None
        except Exception as exc:
            logger.warning("get_ticket failed for channel %s: %s", channel_id, exc)
            return None

    async def _resolve_ai_relay(
        self,
        message: discord.Message,
        ticket_data: dict,
        guild_id: str,
        channel_id: int,
    ) -> tuple[bool, dict | None, str | None]:
        """
        Decide whether to relay this message to AI.
        Returns (should_relay, panel_dict_or_none, panel_id_or_none).
        """
        if ticket_data.get("human_handoff", False):
            logger.debug("ai_skip channel=%s reason=human_handoff", channel_id)
            return False, None, None

        member = message.author if isinstance(message.author, discord.Member) else None
        panel_id = ticket_data.get("panel_id")

        # Legacy tickets (/create-ticket) have no panel — use guild-level AI relay.
        if not panel_id:
            if member and member_has_support_roles(member, None):
                try:
                    await self.client.set_ticket_handoff(guild_id, channel_id, True)
                except Exception as e:
                    logger.warning("staff handoff set failed for %s: %s", channel_id, e)
                logger.debug("ai_skip channel=%s reason=staff_legacy", channel_id)
                return False, None, None
            return True, None, None

        try:
            panel = await self.client.get_panel(guild_id, panel_id)
        except Exception as e:
            logger.warning("get_panel failed for AI relay %s: %s", panel_id, e)
            return False, None, None
        if not panel:
            logger.debug("ai_skip channel=%s reason=panel_not_found", channel_id)
            return False, None, None

        if not panel.get("ai_auto_reply"):
            logger.debug("ai_skip channel=%s reason=ai_auto_reply_off panel=%s", channel_id, panel_id)
            return False, None, None

        if not panel.get("ai_context_id"):
            logger.debug("ai_skip channel=%s reason=no_ai_context panel=%s", channel_id, panel_id)
            return False, None, None

        support_role_ids = panel.get("support_role_ids") or []
        if member and member_has_support_roles(member, support_role_ids):
            try:
                await self.client.set_ticket_handoff(guild_id, channel_id, True)
            except Exception as e:
                logger.warning("staff handoff set failed for %s: %s", channel_id, e)
            logger.debug("ai_skip channel=%s reason=staff", channel_id)
            return False, None, None

        return True, panel, panel_id

    async def _trigger_human_handoff(
        self,
        message: discord.Message,
        panel: dict | None,
    ) -> None:
        """Ping support roles and permanently disable AI for this ticket."""
        guild_id = str(message.guild.id)
        channel_id = message.channel.id
        try:
            await self.client.set_ticket_handoff(guild_id, channel_id, True)
        except Exception as e:
            logger.warning("set_ticket_handoff failed for %s: %s", channel_id, e)

        pings: list[str] = []
        for role_id in (panel or {}).get("support_role_ids") or []:
            role = message.guild.get_role(int(role_id))
            if role:
                pings.append(role.mention)
        if not pings:
            support_role = discord.utils.get(message.guild.roles, name="Support")
            if support_role:
                pings.append(support_role.mention)
        if pings:
            try:
                await message.channel.send(" ".join(pings))
            except Exception as e:
                logger.warning("Failed to ping support roles in %s: %s", channel_id, e)

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
            opened = await self.client.get_ticket(
                str(interaction.guild.id), str(ticket_channel.id)
            )
            if not opened:
                logger.error(
                    "Ticket channel %s created but backend registration failed",
                    ticket_channel.id,
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
        """Relay user messages in AI-enabled ticket channels to the backend."""
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

        # 1. Registered open ticket channel?
        ticket_data = await self._fetch_open_ticket(guild_id, channel_id, message)
        if not ticket_data:
            logger.debug("no open ticket for channel %s — skipping relay", channel_id)
            return

        should_relay, panel, panel_id = await self._resolve_ai_relay(
            message, ticket_data, guild_id, channel_id
        )
        if not should_relay:
            return

        try:
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

            low_confidence = bool(response_data.get("low_confidence"))
            if low_confidence:
                await message.channel.send(HANDOFF_MESSAGE)
                await self._trigger_human_handoff(message, panel)
            else:
                reply_text = response_data.get("reply", "")
                if reply_text:
                    await message.channel.send(reply_text)
                elif not panel_id:
                    logger.warning(
                        "relay_empty_reply guild=%s channel=%s (legacy ticket)",
                        guild_id,
                        channel_id,
                    )

            logger.info(
                "relay_ok guild=%s channel=%s panel_id=%s low_confidence=%s",
                guild_id,
                channel_id,
                panel_id,
                low_confidence,
            )

        except Exception as e:
            logger.error(
                "Error relaying message from channel %s: %s",
                channel_id,
                e,
                exc_info=True,
            )
            err = str(e).lower()
            if "403" in err or "different bot" in err:
                logger.warning(
                    "relay blocked for channel %s (ownership): %s",
                    channel_id,
                    e,
                )
                try:
                    await message.channel.send(
                        "This ticket could not be processed (bot ownership mismatch). "
                        "Please ask staff to run `/ticket ai resume` or open a new ticket."
                    )
                except Exception:
                    pass
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
