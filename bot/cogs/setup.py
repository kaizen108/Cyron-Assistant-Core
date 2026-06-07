"""Setup cog — server setup and ticket panel publishing."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.http_client import get_client
from bot.views.panel_view import PanelView, build_panel_embed, handle_panel_button

logger = logging.getLogger(__name__)


class SetupCog(commands.Cog):
    """Server setup and `/sendpanel` for posting ticket panels to Discord."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="setup", description="Set up the bot for this server")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup(self, interaction: discord.Interaction) -> None:
        """Create Tickets category and Support role if missing."""
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        try:
            tickets_category = discord.utils.get(
                interaction.guild.categories, name="Tickets"
            )
            if not tickets_category:
                tickets_category = await interaction.guild.create_category(
                    "Tickets",
                    reason="AI Ticket Assistant setup",
                )
                logger.info(
                    "Created 'Tickets' category in guild %s",
                    interaction.guild.id,
                )

            support_role = discord.utils.get(interaction.guild.roles, name="Support")
            if not support_role:
                support_role = await interaction.guild.create_role(
                    name="Support",
                    mentionable=True,
                    reason="Auto-created by AI Ticket Assistant bot",
                )
                logger.info(
                    "Created 'Support' role in guild %s",
                    interaction.guild.id,
                )

            await interaction.response.send_message(
                "✅ Setup complete! The bot is ready to create tickets.\n"
                f"- Tickets category: {tickets_category.mention}\n"
                f"- Support role: {support_role.mention}\n\n"
                "**Next steps:**\n"
                "1. Create a panel in the dashboard (**Panels**).\n"
                "2. Run `/sendpanel` in the channel where members should open tickets.",
                ephemeral=True,
            )
            logger.info("Setup completed for guild %s", interaction.guild.id)

        except app_commands.MissingPermissions:
            await interaction.response.send_message(
                "❌ You need administrator permissions to use this command.",
                ephemeral=True,
            )
        except Exception as exc:
            logger.error("Error during setup: %s", exc, exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ An error occurred during setup. Please check bot permissions.",
                    ephemeral=True,
                )

    @app_commands.command(
        name="sendpanel",
        description="Post a ticket panel embed with an Open Ticket button in this channel",
    )
    @app_commands.describe(
        panel="Panel to publish (optional when only one panel exists)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def send_panel(
        self,
        interaction: discord.Interaction,
        panel: str | None = None,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "Run `/sendpanel` in a text channel where members can see the panel.",
                ephemeral=True,
            )
            return

        client = get_client()
        panels = await client.get_panels(str(interaction.guild.id))

        if not panels:
            await interaction.response.send_message(
                "No enabled panels found. Create and enable a panel in the dashboard first "
                "(**Guild → Panels**).",
                ephemeral=True,
            )
            return

        panel_id: str | None = panel

        if panel_id:
            known_ids = {p["id"] for p in panels}
            if panel_id not in known_ids:
                await interaction.response.send_message(
                    "That panel was not found or is disabled. Pick a panel from the list or "
                    "enable it in the dashboard.",
                    ephemeral=True,
                )
                return
        elif len(panels) == 1:
            panel_id = panels[0]["id"]
        else:
            options = [
                discord.SelectOption(label=(p["name"] or "Panel")[:100], value=p["id"])
                for p in panels[:25]
            ]

            cog = self

            class PanelSelect(discord.ui.Select):
                def __init__(self) -> None:
                    super().__init__(
                        placeholder="Choose a panel to send…",
                        options=options,
                    )

                async def callback(self, select_interaction: discord.Interaction) -> None:
                    await select_interaction.response.defer(ephemeral=True)
                    await cog._send_panel_embed(select_interaction, self.values[0])

            view = discord.ui.View(timeout=120)
            view.add_item(PanelSelect())
            await interaction.response.send_message(
                "Select a panel to publish in this channel:",
                view=view,
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        await self._send_panel_embed(interaction, panel_id)

    @send_panel.autocomplete("panel")
    async def _panel_name_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        if not interaction.guild:
            return []
        client = get_client()
        panels = await client.get_panels(str(interaction.guild.id))
        needle = (current or "").lower()
        choices: list[app_commands.Choice[str]] = []
        for panel_row in panels:
            name = panel_row.get("name") or "Panel"
            if needle and needle not in name.lower():
                continue
            choices.append(
                app_commands.Choice(name=name[:100], value=panel_row["id"])
            )
            if len(choices) >= 25:
                break
        return choices

    async def _send_panel_embed(
        self,
        interaction: discord.Interaction,
        panel_id: str,
    ) -> None:
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.followup.send(
                "Panels can only be sent in a text channel.",
                ephemeral=True,
            )
            return

        me = interaction.guild.me
        if me is None:
            await interaction.followup.send(
                "Could not resolve bot member in this server.",
                ephemeral=True,
            )
            return

        perms = interaction.channel.permissions_for(me)
        missing: list[str] = []
        if not perms.view_channel:
            missing.append("View Channel")
        if not perms.send_messages:
            missing.append("Send Messages")
        if not perms.embed_links:
            missing.append("Embed Links")
        if missing:
            await interaction.followup.send(
                "I need these permissions in this channel: "
                + ", ".join(missing),
                ephemeral=True,
            )
            return

        client = get_client()
        panel = await client.get_panel(str(interaction.guild.id), panel_id)
        if not panel:
            await interaction.followup.send(
                "Panel not found. It may have been deleted from the dashboard.",
                ephemeral=True,
            )
            return

        if not panel.get("is_enabled", True):
            await interaction.followup.send(
                "This panel is disabled. Enable it in the dashboard before publishing.",
                ephemeral=True,
            )
            return

        embed = build_panel_embed(panel)
        view = PanelView(panel)
        self.bot.add_view(view)

        try:
            message = await interaction.channel.send(embed=embed, view=view)
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Could not send the panel. Check that my role can send messages here.",
                ephemeral=True,
            )
            return
        except Exception as exc:
            logger.error("send_panel_embed_failed: %s", exc, exc_info=True)
            await interaction.followup.send(
                "❌ Failed to send the panel. Please try again.",
                ephemeral=True,
            )
            return

        await client.publish_panel(
            guild_id=str(interaction.guild.id),
            panel_id=panel_id,
            channel_id=interaction.channel.id,
            message_id=message.id,
        )

        panel_name = panel.get("name") or "Panel"
        await interaction.followup.send(
            f"✅ **{panel_name}** panel posted in {interaction.channel.mention}.\n"
            "Members can click the button to open a ticket.\n"
            "Run `/sendpanel` again after editing panel settings to post an updated panel.",
            ephemeral=True,
        )
        logger.info(
            "panel_published guild=%s panel=%s channel=%s message=%s",
            interaction.guild.id,
            panel_id,
            interaction.channel.id,
            message.id,
        )

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction) -> None:
        """Route persistent panel button clicks after bot restarts."""
        if interaction.type != discord.InteractionType.component:
            return
        custom_id = (interaction.data or {}).get("custom_id", "")
        if custom_id.startswith("panel_open:"):
            await handle_panel_button(interaction)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SetupCog(bot))
    logger.info("SetupCog loaded")
