"""Discord bot entry point."""

import asyncio
import logging
import sys
import os
from pathlib import Path

# Add project root to Python path to allow imports
# This ensures imports work when running: python bot/main.py
project_root = Path(__file__).parent.parent.absolute()
project_root_str = str(project_root)

# Add to sys.path if not already there (must be first!)
if project_root_str not in sys.path:
    sys.path.insert(0, project_root_str)

# Also set PYTHONPATH environment variable as fallback
os.environ["PYTHONPATH"] = project_root_str

# Change to project root directory to ensure relative paths work
os.chdir(project_root_str)

# Now import bot modules
import discord
from discord import app_commands
from discord.ext import commands
from bot.config import config
from bot.cogs import setup, tickets
from bot.cogs import ticket_commands
from bot.utils.embed_builder import create_ticket_embed
from bot.utils.http_client import get_client

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.log_level),
    format="[BOT] %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


class AITicketBot(commands.Bot):
    """Main bot class."""

    def __init__(self) -> None:
        """Initialize the bot with intents and command prefix."""
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.messages = True

        super().__init__(
            command_prefix="!",  # Not used for slash commands, but required
            intents=intents,
            help_command=None,  # Disable default help command
        )
        self._commands_synced = False

    async def setup_hook(self) -> None:
        logger.info("Loading cogs...")
        await setup.setup(self)
        await tickets.setup(self)
        await ticket_commands.setup(self)
        logger.info("Cogs loaded successfully")

    async def _sync_commands(self, guild: discord.Guild | None = None) -> None:
        """Sync guild slash commands and clear stale global duplicates."""
        try:
            # Remove global commands so Discord doesn't show duplicates
            # alongside guild-scoped commands.
            self.tree.clear_commands(guild=None)
            await self.tree.sync()

            targets = [guild] if guild else list(self.guilds)
            synced_count = 0
            for g in targets:
                guild_obj = discord.Object(id=g.id)
                self.tree.copy_global_to(guild=guild_obj)
                cmds = await self.tree.sync(guild=guild_obj)
                synced_count += len(cmds)
                logger.info("Synced %s commands to guild %s", len(cmds), g.id)
            logger.info(
                "Total synced: %s commands across %s guild(s)",
                synced_count,
                len(targets),
            )
        except Exception as e:
            logger.error("Failed to sync commands: %s", e, exc_info=True)

    async def on_ready(self) -> None:
        """Called when the bot is ready."""
        logger.info(f"Bot logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guild(s)")

        if not self._commands_synced:
            await self._sync_commands()
            self._commands_synced = True

        # Let backend know which guilds currently have the bot installed.
        try:
            client = get_client()
            for g in self.guilds:
                await client.mark_guild_has_bot(str(g.id), name=g.name)
                text_channels = [
                    {"id": str(ch.id), "name": ch.name}
                    for ch in g.text_channels
                ]
                await client.push_guild_channels(str(g.id), text_channels)
        except Exception as e:
            logger.warning(f"Failed to sync bot-installed guilds to backend: {e}")

        # Periodically refresh installed flags so the dashboard stays accurate
        # even after long uptimes.
        async def _refresh_installed_flags() -> None:
            while not self.is_closed():
                try:
                    client_inner = get_client()
                    for g in self.guilds:
                        await client_inner.mark_guild_has_bot(str(g.id), name=g.name)
                except Exception as exc:  # pragma: no cover - best-effort
                    logger.warning("refresh_installed_flags_failed: %s", exc)
                await asyncio.sleep(5 * 60)

        # Start background task once
        if not hasattr(self, "_refresh_task"):
            self._refresh_task = asyncio.create_task(_refresh_installed_flags())

        # Poll Redis for pending panel sends
        if not hasattr(self, "_panel_send_task"):
            self._panel_send_task = asyncio.create_task(self._poll_panel_sends())

    async def _poll_panel_sends(self) -> None:
        """Poll Redis queue for pending panel send tasks."""
        import json
        import aiohttp
        from bot.views.panel_view import PanelView, build_panel_embed
        from bot.utils.http_client import get_client

        redis_url = __import__('os').environ.get("REDIS_URL", "redis://localhost:6379/0")
        try:
            from redis.asyncio import Redis as ARedis
            redis = ARedis.from_url(redis_url, decode_responses=True)
        except Exception as e:
            logger.warning("panel_send_poll: could not connect to Redis: %s", e)
            return

        while not self.is_closed():
            try:
                item = await redis.rpop("bot:pending_panel_sends")
                if item:
                    task = json.loads(item)
                    guild = self.get_guild(int(task["guild_id"]))
                    channel = guild.get_channel(int(task["channel_id"])) if guild else None
                    if guild and channel and isinstance(channel, discord.TextChannel):
                        client = get_client()
                        panel = await client.get_panel(str(task["guild_id"]), task["panel_id"])
                        if panel:
                            embed = build_panel_embed(panel)
                            view = PanelView(panel)
                            msg = await channel.send(embed=embed, view=view)
                            await client.publish_panel(
                                guild_id=str(task["guild_id"]),
                                panel_id=task["panel_id"],
                                channel_id=channel.id,
                                message_id=msg.id,
                            )
                            logger.info("panel_sent guild=%s panel=%s channel=%s", task["guild_id"], task["panel_id"], channel.id)
            except Exception as e:
                logger.warning("panel_send_poll error: %s", e)
            await asyncio.sleep(2)

    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        """Surface permission/check failures instead of silent Discord errors."""
        if isinstance(error, app_commands.MissingPermissions):
            message = "You don't have permission to run this command."
        elif isinstance(error, app_commands.CheckFailure):
            message = "You are not allowed to run this command."
        else:
            logger.error("app_command_error: %s", error, exc_info=error)
            message = "Something went wrong while running that command."

        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except Exception as exc:
            logger.warning("Failed to send app command error: %s", exc)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Called when the bot joins a new guild. Send welcome embed."""
        logger.info(f"Joined new guild: {guild.name} (ID: {guild.id})")
        await self._sync_commands(guild=guild)
        try:
            # Mark in backend that this guild has the bot installed
            try:
                client = get_client()
                await client.mark_guild_has_bot(str(guild.id), name=guild.name)
            except Exception as e:
                logger.warning("Failed to notify backend of new guild %s: %s", guild.id, e)

            embed = create_ticket_embed(
                title="AI Ticket Assistant",
                description=(
                    "Thanks for adding me! I provide AI-powered support in ticket channels.\n\n"
                    "**Getting started:**\n"
                    "1. Run `/setup` to create the Tickets category and Support role.\n"
                    "2. Run `/create-ticket` to open a support ticket.\n"
                    "3. Send messages in the ticket channel — I'll reply with AI assistance."
                ),
                color="#00b4ff",
                footer="Use /setup then /create-ticket to begin.",
            )
            channel = guild.system_channel
            if channel is None:
                for ch in guild.text_channels:
                    if ch.permissions_for(guild.me).send_messages:
                        channel = ch
                        break
            if channel:
                await channel.send(embed=embed)
        except Exception as e:
            logger.warning("Could not send welcome embed to guild %s: %s", guild.id, e)

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        """Called when the bot leaves a guild."""
        logger.info(f"Left guild: {guild.name} (ID: {guild.id})")
        try:
            client = get_client()
            await client.mark_guild_bot_removed(str(guild.id))
        except Exception as e:
            logger.warning("Failed to notify backend of guild removal %s: %s", guild.id, e)

    async def close(self) -> None:
        """Called when the bot is shutting down."""
        logger.info("Bot shutting down...")
        # Close HTTP client session
        try:
            client = get_client()
            await client.close()
        except Exception as e:
            logger.warning(f"Error closing HTTP client: {e}")
        await super().close()


async def main() -> None:
    """Main entry point."""
    bot: AITicketBot | None = None
    try:
        # Validate configuration
        if not config.validate():
            logger.error("Invalid bot configuration")
            sys.exit(1)

        # Create and run bot
        bot = AITicketBot()
        await bot.start(config.discord_token)

    except discord.errors.PrivilegedIntentsRequired:
        logger.error("=" * 70)
        logger.error("PRIVILEGED INTENTS REQUIRED")
        logger.error("=" * 70)
        logger.error("")
        logger.error("The bot requires privileged intents that must be enabled")
        logger.error("in the Discord Developer Portal.")
        logger.error("")
        logger.error("To fix this:")
        logger.error("1. Go to: https://discord.com/developers/applications/")
        logger.error("2. Select your application")
        logger.error("3. Go to 'Bot' section in the left sidebar")
        logger.error("4. Scroll down to 'Privileged Gateway Intents'")
        logger.error("5. Enable the following intents:")
        logger.error("   - MESSAGE CONTENT INTENT (Required)")
        logger.error("   - SERVER MEMBERS INTENT (Optional, for future features)")
        logger.error("6. Save changes")
        logger.error("7. Restart the bot")
        logger.error("")
        logger.error("Note: It may take a few minutes for changes to take effect.")
        logger.error("")
        logger.error("See SETUP_INTENTS.md for detailed instructions.")
        logger.error("=" * 70)
        # Clean up HTTP client before exiting
        try:
            client = get_client()
            await client.close()
        except Exception:
            pass
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        # Clean up HTTP client before exiting
        try:
            client = get_client()
            await client.close()
        except Exception:
            pass
        sys.exit(1)
    finally:
        # Ensure bot is properly closed
        if bot:
            try:
                await bot.close()
            except Exception:
                pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

