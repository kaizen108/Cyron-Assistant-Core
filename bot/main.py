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

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.log_level),
    format="[BOT] %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def _collect_sendable_text_channels(guild: discord.Guild) -> list[dict[str, str]]:
    """Text channels where the bot can post panel embeds."""
    me = guild.me
    if me is None and guild._state.user:
        me = guild.get_member(guild._state.user.id)
    if me is None:
        return []
    channels: list[dict[str, str]] = []
    for ch in guild.text_channels:
        perms = ch.permissions_for(me)
        if perms.view_channel and perms.send_messages:
            channels.append({"id": str(ch.id), "name": ch.name})
    channels.sort(key=lambda c: c["name"].lower())
    return channels


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

    async def _sync_guild_channels(self, guild: discord.Guild) -> None:
        """Push sendable text channels to backend for dashboard selectors."""
        client = get_client()
        channels = _collect_sendable_text_channels(guild)
        ok = await client.push_guild_channels(str(guild.id), channels)
        if ok:
            logger.info(
                "Synced %d channel(s) for guild %s (%s)",
                len(channels),
                guild.id,
                guild.name,
            )
        else:
            logger.warning(
                "Channel sync failed for guild %s (%s)", guild.id, guild.name
            )

    async def on_ready(self) -> None:
        """Called when the bot is ready."""
        logger.info(f"Bot logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guild(s)")

        # Sync slash commands to each guild explicitly
        try:
            synced_count = 0
            for g in self.guilds:
                guild_obj = discord.Object(id=g.id)
                self.tree.copy_global_to(guild=guild_obj)
                cmds = await self.tree.sync(guild=guild_obj)
                synced_count += len(cmds)
                logger.info(f"Synced {len(cmds)} commands to guild {g.id}")
            logger.info(f"Total synced: {synced_count} commands across {len(self.guilds)} guild(s)")
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}", exc_info=True)

        # Let backend know which guilds currently have the bot installed.
        try:
            client = get_client()
            for g in self.guilds:
                await client.mark_guild_has_bot(str(g.id), name=g.name)
                await self._sync_guild_channels(g)
        except Exception as e:
            logger.warning(f"Failed to sync bot-installed guilds to backend: {e}")

        # Periodically refresh installed flags and channel lists.
        async def _refresh_installed_flags() -> None:
            while not self.is_closed():
                try:
                    client_inner = get_client()
                    for g in self.guilds:
                        await client_inner.mark_guild_has_bot(str(g.id), name=g.name)
                        await self._sync_guild_channels(g)
                except Exception as exc:  # pragma: no cover - best-effort
                    logger.warning("refresh_installed_flags_failed: %s", exc)
                await asyncio.sleep(5 * 60)

        # Start background task once
        if not hasattr(self, "_refresh_task"):
            self._refresh_task = asyncio.create_task(_refresh_installed_flags())

        # Poll Redis for pending panel sends
        if not hasattr(self, "_panel_send_task"):
            self._panel_send_task = asyncio.create_task(self._poll_panel_sends())

    async def _execute_panel_send(self, task: dict) -> bool:
        """Send a queued panel embed to Discord. Returns True on success."""
        from bot.views.panel_view import PanelView, build_panel_embed
        from bot.utils.http_client import get_client

        guild_id = int(task["guild_id"])
        channel_id = int(task["channel_id"])
        panel_id = task["panel_id"]

        guild = self.get_guild(guild_id)
        if guild is None:
            try:
                guild = await self.fetch_guild(guild_id)
            except discord.NotFound:
                logger.warning("panel_send: guild %s not found", guild_id)
                return False

        channel = guild.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.fetch_channel(channel_id)
            except discord.NotFound:
                logger.warning(
                    "panel_send: channel %s not found in guild %s",
                    channel_id,
                    guild_id,
                )
                return False

        if not isinstance(channel, discord.TextChannel):
            logger.warning(
                "panel_send: channel %s is not a text channel (type=%s)",
                channel_id,
                type(channel).__name__,
            )
            return False

        client = get_client()
        panel = await client.get_panel(str(guild_id), panel_id)
        if not panel:
            logger.warning(
                "panel_send: panel %s not found for guild %s", panel_id, guild_id
            )
            return False

        embed = build_panel_embed(panel)
        view = PanelView(panel)
        msg = await channel.send(embed=embed, view=view)
        await client.publish_panel(
            guild_id=str(guild_id),
            panel_id=panel_id,
            channel_id=channel.id,
            message_id=msg.id,
        )
        logger.info(
            "panel_sent guild=%s panel=%s channel=%s message=%s",
            guild_id,
            panel_id,
            channel.id,
            msg.id,
        )
        return True

    async def _poll_panel_sends(self) -> None:
        """Poll Redis queue for pending panel send tasks."""
        import json
        from redis.asyncio import Redis as ARedis

        redis = None

        while not self.is_closed():
            if redis is None:
                try:
                    redis = ARedis.from_url(config.redis_url, decode_responses=True)
                    await redis.ping()
                    logger.info("panel_send_poll connected to Redis at %s", config.redis_url)
                except Exception as e:
                    logger.warning("panel_send_poll: Redis unavailable: %s", e)
                    redis = None
                    await asyncio.sleep(5)
                    continue

            try:
                # On-demand channel sync requests from dashboard
                for g in self.guilds:
                    sync_key = f"bot:guild:{g.id}:sync_channels"
                    if await redis.get(sync_key):
                        await self._sync_guild_channels(g)
                        await redis.delete(sync_key)

                item = await redis.rpop("bot:pending_panel_sends")
                if item:
                    task = json.loads(item)
                    retries = int(task.get("_retries", 0))
                    try:
                        ok = await self._execute_panel_send(task)
                    except discord.Forbidden:
                        logger.warning(
                            "panel_send: missing permissions guild=%s channel=%s",
                            task.get("guild_id"),
                            task.get("channel_id"),
                        )
                        ok = False
                    except Exception as exc:
                        logger.warning("panel_send failed: %s", exc, exc_info=True)
                        ok = False

                    if not ok and retries < 3:
                        task["_retries"] = retries + 1
                        await redis.lpush("bot:pending_panel_sends", json.dumps(task))
                        logger.info(
                            "panel_send re-queued (attempt %d/3) guild=%s channel=%s",
                            retries + 1,
                            task.get("guild_id"),
                            task.get("channel_id"),
                        )
            except Exception as e:
                logger.warning("panel_send_poll error: %s", e)
                try:
                    await redis.ping()
                except Exception:
                    logger.warning("panel_send_poll: Redis connection lost, reconnecting")
                    redis = None
            await asyncio.sleep(2)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Called when the bot joins a new guild. Send welcome embed."""
        logger.info(f"Joined new guild: {guild.name} (ID: {guild.id})")
        try:
            # Mark in backend that this guild has the bot installed
            try:
                client = get_client()
                await client.mark_guild_has_bot(str(guild.id), name=guild.name)
                await self._sync_guild_channels(guild)
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

