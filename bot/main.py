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

    def _command_tree_summary(self) -> str:
        parts: list[str] = []
        for cmd in self.tree.get_commands():
            if isinstance(cmd, app_commands.Group):
                for sub in cmd.commands:
                    parts.append(f"{cmd.name}/{sub.name}")
            else:
                parts.append(cmd.name)
        return ", ".join(parts) or "(none)"

    async def setup_hook(self) -> None:
        logger.info("Loading cogs...")
        await setup.setup(self)
        await tickets.setup(self)
        await ticket_commands.setup(self)
        logger.info(
            "Cogs loaded — %d command(s) in tree: %s",
            len(self.tree.get_commands()),
            self._command_tree_summary(),
        )

    async def _sync_slash_commands(self, guild: discord.Guild | None = None) -> None:
        """Sync slash commands to Discord (guild-scoped = instant visibility)."""
        registered = self.tree.get_commands()
        if not registered:
            logger.error(
                "No slash commands registered in the command tree — check cog loading"
            )
            return

        targets = [guild] if guild else list(self.guilds)
        total_synced = 0

        if targets:
            for g in targets:
                # Clear only the guild-local tree, then copy from the global tree.
                # Never call clear_commands(guild=None) here — that wipes the source tree.
                self.tree.clear_commands(guild=g)
                self.tree.copy_global_to(guild=g)
                synced = await self.tree.sync(guild=g)
                total_synced += len(synced)
                logger.info(
                    "Synced %d command(s) to guild %s (%s): %s",
                    len(synced),
                    g.name,
                    g.id,
                    self._format_synced_names(synced),
                )
        else:
            synced = await self.tree.sync()
            total_synced = len(synced)
            logger.info(
                "Synced %d global command(s): %s",
                len(synced),
                self._format_synced_names(synced),
            )

        if total_synced == 0:
            logger.warning(
                "Discord returned 0 synced commands — retrying global sync"
            )
            synced = await self.tree.sync()
            logger.info(
                "Global fallback synced %d command(s): %s",
                len(synced),
                self._format_synced_names(synced),
            )

    async def _wait_for_backend(self, max_attempts: int = 15, interval: float = 2.0) -> None:
        """Wait until the backend API accepts connections."""
        import aiohttp

        url = f"{config.backend_url.rstrip('/')}/health"
        for attempt in range(1, max_attempts + 1):
            try:
                async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as session:
                    async with session.get(url) as response:
                        if response.status == 200:
                            logger.info("Backend API is reachable at %s", config.backend_url)
                            return
            except Exception as exc:
                logger.warning(
                    "Backend not ready (attempt %d/%d): %s",
                    attempt,
                    max_attempts,
                    exc,
                )
            await asyncio.sleep(interval)
        logger.error(
            "Backend API still unreachable at %s — check `docker logs ai-ticket-api`",
            config.backend_url,
        )

    @staticmethod
    def _format_synced_names(synced: list) -> str:
        names: list[str] = []
        for cmd in synced:
            if isinstance(cmd, app_commands.Group):
                for sub in cmd.commands:
                    names.append(f"{cmd.name}/{sub.name}")
            else:
                names.append(cmd.name)
        return ", ".join(names) or "(none)"

    async def on_ready(self) -> None:
        """Called when the bot is ready."""
        logger.info(f"Bot logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guild(s)")

        # Sync once per process — guild-scoped sync is instant in Discord.
        if not getattr(self, "_commands_synced", False):
            try:
                await self._sync_slash_commands()
                self._commands_synced = True
            except Exception as e:
                logger.error(f"Failed to sync commands: {e}", exc_info=True)

        # Let backend know which guilds currently have the bot installed.
        await self._wait_for_backend()
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
            await self._sync_slash_commands(guild=guild)
        except Exception as e:
            logger.warning("Failed to sync commands for new guild %s: %s", guild.id, e)
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

