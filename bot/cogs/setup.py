"""Setup cog for Discord bot."""

import logging
import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.http_client import get_client
from bot.views.panel_view import PanelView, build_panel_embed, handle_panel_button

logger = logging.getLogger(__name__)


class SetupCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="setup", description="Set up the bot for this server")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return
        try:
            tickets_category = discord.utils.get(interaction.guild.categories, name="Tickets")
            if not tickets_category:
                tickets_category = await interaction.guild.create_category("Tickets")

            support_role = discord.utils.get(interaction.guild.roles, name="Support")
            if not support_role:
                support_role = await interaction.guild.create_role(name="Support", mentionable=True)

            await interaction.response.send_message(
                f"✅ Setup complete!\n- Category: {tickets_category.mention}\n- Role: {support_role.mention}",
                ephemeral=True,
            )
        except Exception as e:
            logger.error("Error during setup: %s", e, exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ An error occurred during setup.", ephemeral=True)

    @app_commands.command(name="sendpanel", description="Send a ticket panel in this channel")
    @app_commands.checks.has_permissions(administrator=True)
    async def send_panel(self, interaction: discord.Interaction) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Server only.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        client = get_client()
        panels = await client.get_panels(str(interaction.guild.id))

        if not panels:
            await interaction.followup.send(
                "No panels configured. Create one from the dashboard first.", ephemeral=True
            )
            return

        if len(panels) == 1:
            await self._send_panel_embed(interaction, panels[0]["id"])
            return

        # Multiple panels — show select menu
        options = [
            discord.SelectOption(label=p["name"][:100] or "Unnamed", value=p["id"])
            for p in panels[:25]
        ]

        class PanelSelect(discord.ui.Select):
            def __init__(self):
                super().__init__(placeholder="Choose a panel to send…", options=options)

            async def callback(self_, select_interaction: discord.Interaction):
                await select_interaction.response.defer(ephemeral=True)
                await self._send_panel_embed(select_interaction, self_.values[0])

        view = discord.ui.View(timeout=60)
        view.add_item(PanelSelect())
        await interaction.followup.send("Select a panel:", view=view, ephemeral=True)

    async def _send_panel_embed(self, interaction: discord.Interaction, panel_id: str) -> None:
        client = get_client()
        panel = await client.get_panel(str(interaction.guild.id), panel_id)
        if not panel:
            await interaction.followup.send("Panel not found.", ephemeral=True)
            return

        embed = build_panel_embed(panel)
        view = PanelView(panel)
        msg = await interaction.channel.send(embed=embed, view=view)

        await client.publish_panel(
            guild_id=str(interaction.guild.id),
            panel_id=panel_id,
            channel_id=interaction.channel.id,
            message_id=msg.id,
        )
        await interaction.followup.send("✅ Panel sent!", ephemeral=True)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction) -> None:
        """Route panel_open: button clicks."""
        if interaction.type != discord.InteractionType.component:
            return
        custom_id = (interaction.data or {}).get("custom_id", "")
        if custom_id.startswith("panel_open:"):
            await handle_panel_button(interaction)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SetupCog(bot))
    logger.info("SetupCog loaded")

