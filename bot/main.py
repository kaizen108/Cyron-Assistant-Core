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
from discord.ext import commands
from bot.config import config
from bot.cogs import setup, tickets
from bot.cogs import ticket_commands
from bot.utils.embed_builder import create_ticket_embed
from bot.utils.http_client import get_client
from bot.views.panel_view import PanelView

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

    async def setup_hook(self) -> None:
        logger.info("Loading cogs...")
        await setup.setup(self)
        await tickets.setup(self)
        await ticket_commands.setup(self)
        logger.info("Cogs loaded successfully")

    async def _sync_app_commands(self) -> None:
        """Register slash commands with Discord (guild sync is near-instant)."""
        guild_count = 0
        for guild in self.guilds:
            try:
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                guild_count += 1
                logger.info(
                    "Synced %s command(s) to guild %s (%s)",
                    len(synced),
                    guild.id,
                    guild.name,
                )
            except Exception as exc:
                logger.warning(
                    "Guild command sync failed for %s: %s",
                    guild.id,
                    exc,
                )

        try:
            global_synced = await self.tree.sync()
            logger.info(
                "Global command sync submitted (%s command(s)); "
                "may take up to ~1 hour to propagate everywhere.",
                len(global_synced),
            )
        except Exception as exc:
            logger.error("Global command sync failed: %s", exc, exc_info=True)

        if guild_count == 0:
            logger.warning(
                "Bot is not in any guilds yet — slash commands will sync on guild join."
            )

    async def on_ready(self) -> None:
        """Called when the bot is ready."""
        logger.info(f"Bot logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guild(s)")

        await self._sync_app_commands()

        # Re-register persistent panel button views so clicks work after restarts.
        try:
            client = get_client()
            registered = 0
            for guild in self.guilds:
                panels = await client.get_panels(str(guild.id))
                for summary in panels:
                    panel = await client.get_panel(str(guild.id), summary["id"])
                    if panel:
                        self.add_view(PanelView(panel))
                        registered += 1
            logger.info("Registered %s persistent panel view(s)", registered)
        except Exception as e:
            logger.warning("Failed to register persistent panel views: %s", e)

        # Let backend know which guilds currently have the bot installed.
        try:
            client = get_client()
            for g in self.guilds:
                await client.mark_guild_has_bot(str(g.id), name=g.name)
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

    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Called when the bot joins a new guild. Send welcome embed."""
        logger.info(f"Joined new guild: {guild.name} (ID: {guild.id})")
        try:
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            logger.info(
                "Synced %s command(s) to new guild %s",
                len(synced),
                guild.id,
            )
        except Exception as exc:
            logger.warning("Command sync failed for new guild %s: %s", guild.id, exc)

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
                    "2. Create a panel in the web dashboard (**Panels**).\n"
                    "3. Run `/sendpanel` in your support channel to post the ticket button.\n"
                    "4. Members click the button to open tickets — I'll reply with AI assistance."
                ),
                color="#00b4ff",
                footer="Use /setup then /sendpanel to publish your ticket panel.",
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

