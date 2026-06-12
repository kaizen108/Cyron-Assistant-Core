"""Async HTTP client for backend communication."""

import asyncio
import logging
from typing import Any
import aiohttp
from bot.config import config

logger = logging.getLogger(__name__)


class BackendClient:
    """Async HTTP client for communicating with the backend API."""

    def __init__(self, base_url: str, timeout: int = 8) -> None:
        """
        Initialize the backend client.

        Args:
            base_url: Base URL of the backend API
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: aiohttp.ClientSession | None = None
        self._bot_headers = {
            "Content-Type": "application/json",
            "X-Bot-Api-Key": config.bot_api_key,
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self._session

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def get_guild(self, guild_id: str) -> dict[str, Any] | None:
        """Fetch guild settings from the backend."""
        url = f"{self.base_url}/guilds/{guild_id}"
        session = await self._get_session()
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.json()
                return None
        except Exception as e:
            logger.warning(f"Failed to fetch guild {guild_id}: {e}")
            return None

    async def get_ticket(self, guild_id: str, channel_id: str) -> dict[str, Any] | None:
        """Fetch ticket row (includes panel_id) for a channel."""
        url = f"{self.base_url}/internal/bot/guilds/{guild_id}/tickets/{channel_id}"
        session = await self._get_session()
        try:
            async with session.get(url, headers=self._bot_headers) as response:
                if response.status == 200:
                    return await response.json()
                return None
        except Exception as e:
            logger.warning(f"Failed to fetch ticket {guild_id}/{channel_id}: {e}")
            return None

    async def mark_guild_has_bot(self, guild_id: str, name: str | None = None) -> None:
        """Notify backend that the bot is installed in this guild."""
        url = f"{self.base_url}/internal/bot/guilds/{guild_id}/installed"
        session = await self._get_session()
        try:
            payload: dict[str, Any] = {}
            if name:
                payload["name"] = name
            async with session.post(
                url,
                json=payload or None,
                headers=self._bot_headers,
            ) as response:
                if response.status != 200:
                    text = await response.text()
                    logger.warning(
                        "mark_guild_has_bot_failed",
                        extra={"status": response.status, "body": text},
                    )
        except Exception as e:
            logger.warning(f"Failed to mark guild {guild_id} has bot: {e}")

    async def mark_guild_bot_removed(self, guild_id: str) -> None:
        """Notify backend that the bot has been removed from this guild."""
        url = f"{self.base_url}/internal/bot/guilds/{guild_id}/removed"
        session = await self._get_session()
        try:
            async with session.post(url, headers=self._bot_headers) as response:
                if response.status != 200:
                    text = await response.text()
                    logger.warning(
                        "mark_guild_bot_removed_failed",
                        extra={"status": response.status, "body": text},
                    )
        except Exception as e:
            logger.warning(f"Failed to mark guild {guild_id} bot removed: {e}")

    async def get_panels(self, guild_id: str) -> list:
        url = f"{self.base_url}/internal/bot/guilds/{guild_id}/panels/list/public"
        session = await self._get_session()
        try:
            async with session.get(url, headers=self._bot_headers) as r:
                return await r.json() if r.status == 200 else []
        except Exception as e:
            logger.warning("get_panels failed: %s", e)
            return []

    async def get_panel(self, guild_id: str, panel_id: str) -> dict | None:
        url = f"{self.base_url}/internal/bot/guilds/{guild_id}/panels/{panel_id}/public"
        session = await self._get_session()
        try:
            async with session.get(url, headers=self._bot_headers) as r:
                return await r.json() if r.status == 200 else None
        except Exception as e:
            logger.warning("get_panel failed: %s", e)
            return None

    async def next_ticket_number(self, guild_id: str) -> int:
        url = f"{self.base_url}/internal/bot/guilds/{guild_id}/tickets/next-number"
        session = await self._get_session()
        try:
            async with session.post(url, headers=self._bot_headers) as r:
                data = await r.json()
                return data.get("ticket_number", 1)
        except Exception as e:
            logger.warning("next_ticket_number failed: %s", e)
            return 1

    async def open_ticket(self, guild_id: str, channel_id: int, user_id: int,
                          panel_id: str | None = None, bot_id: int | None = None,
                          ticket_number: int | None = None, channel_name: str | None = None,
                          form_answers: dict | None = None) -> dict:
        url = f"{self.base_url}/internal/bot/guilds/{guild_id}/tickets/open"
        payload: dict = {"channel_id": channel_id, "user_id": user_id}
        if panel_id: payload["panel_id"] = panel_id
        if bot_id: payload["bot_id"] = bot_id
        if ticket_number: payload["ticket_number"] = ticket_number
        if channel_name: payload["channel_name"] = channel_name
        if form_answers: payload["form_answers"] = form_answers
        session = await self._get_session()
        try:
            async with session.post(url, json=payload, headers=self._bot_headers) as r:
                return await r.json() if r.status == 200 else {}
        except Exception as e:
            logger.warning("open_ticket failed: %s", e)
            return {}

    async def close_ticket(self, guild_id: str, channel_id: str,
                           closed_by_user_id: str, reason: str | None = None) -> None:
        url = f"{self.base_url}/internal/bot/guilds/{guild_id}/tickets/{channel_id}/close"
        payload: dict = {"closed_by_user_id": int(closed_by_user_id)}
        if reason: payload["reason"] = reason
        session = await self._get_session()
        try:
            async with session.post(url, json=payload, headers=self._bot_headers) as r:
                if r.status not in (200, 404):
                    logger.warning("close_ticket returned %s", r.status)
        except Exception as e:
            logger.warning("close_ticket failed: %s", e)

    async def claim_ticket(self, guild_id: str, channel_id: str, claimed_by_user_id: str) -> None:
        url = f"{self.base_url}/internal/bot/guilds/{guild_id}/tickets/{channel_id}/claim"
        session = await self._get_session()
        try:
            async with session.post(url, json={"claimed_by_user_id": int(claimed_by_user_id)}, headers=self._bot_headers) as r:
                pass
        except Exception as e:
            logger.warning("claim_ticket failed: %s", e)

    async def unclaim_ticket(self, guild_id: str, channel_id: str) -> None:
        url = f"{self.base_url}/internal/bot/guilds/{guild_id}/tickets/{channel_id}/unclaim"
        session = await self._get_session()
        try:
            async with session.post(url, headers=self._bot_headers) as r:
                pass
        except Exception as e:
            logger.warning("unclaim_ticket failed: %s", e)

    async def set_ticket_priority(self, guild_id: str, channel_id: str, priority: str) -> None:
        url = f"{self.base_url}/internal/bot/guilds/{guild_id}/tickets/{channel_id}/priority"
        session = await self._get_session()
        try:
            async with session.post(url, json={"priority": priority}, headers=self._bot_headers) as r:
                pass
        except Exception as e:
            logger.warning("set_ticket_priority failed: %s", e)

    async def publish_panel(self, guild_id: str, panel_id: str, channel_id: int, message_id: int) -> None:
        url = f"{self.base_url}/internal/bot/guilds/{guild_id}/panels/{panel_id}/publish"
        session = await self._get_session()
        try:
            async with session.post(url, json={"channel_id": channel_id, "message_id": message_id}, headers=self._bot_headers) as r:
                pass
        except Exception as e:
            logger.warning("publish_panel failed: %s", e)

    async def get_open_tickets_by_user(self, guild_id: str, user_id: str) -> list:
        url = f"{self.base_url}/internal/bot/guilds/{guild_id}/tickets/open?user_id={user_id}"
        session = await self._get_session()
        try:
            async with session.get(url, headers=self._bot_headers) as r:
                return await r.json() if r.status == 200 else []
        except Exception as e:
            logger.warning("get_open_tickets_by_user failed: %s", e)
            return []

    async def get_stale_tickets(self) -> list:
        url = f"{self.base_url}/internal/bot/tickets/stale"
        session = await self._get_session()
        try:
            async with session.get(url, headers=self._bot_headers) as r:
                return await r.json() if r.status == 200 else []
        except Exception as e:
            logger.warning("get_stale_tickets failed: %s", e)
            return []

    async def push_guild_channels(self, guild_id: str, channels: list) -> None:
        url = f"{self.base_url}/internal/bot/guilds/{guild_id}/channels"
        session = await self._get_session()
        try:
            async with session.post(url, json={"channels": channels}, headers=self._bot_headers) as r:
                pass
        except Exception as e:
            logger.warning("push_guild_channels failed: %s", e)

    async def relay_message(
        self,
        guild_id: str,
        channel_id: str,
        user_id: str,
        content: str,
        message_id: str | None = None,
        bot_id: str | None = None,
        panel_id: str | None = None,
        max_retries: int = 2,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/relay"
        payload = {
            "guild_id": str(guild_id),
            "channel_id": str(channel_id),
            "user_id": str(user_id),
            "content": content,
        }
        if message_id:
            payload["message_id"] = str(message_id)
        if bot_id:
            payload["bot_id"] = str(bot_id)
        if panel_id:
            payload["panel_id"] = str(panel_id)

        session = await self._get_session()
        last_error: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                logger.debug(
                    f"Relaying message to backend (attempt {attempt + 1}/{max_retries + 1})"
                )
                async with session.post(
                    url, json=payload, headers=self._bot_headers
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        logger.debug("Successfully received response from backend")
                        return data
                    else:
                        error_text = await response.text()
                        raise Exception(
                            f"Backend returned status {response.status}: {error_text}"
                        )

            except asyncio.TimeoutError as e:
                last_error = e
                logger.warning(f"Request timeout (attempt {attempt + 1}/{max_retries + 1})")
                if attempt < max_retries:
                    await asyncio.sleep(2**attempt)  # Exponential backoff

            except Exception as e:
                last_error = e
                logger.error(f"Error relaying message: {e}")
                if attempt < max_retries:
                    await asyncio.sleep(2**attempt)  # Exponential backoff

        # All retries failed
        if last_error:
            raise Exception(f"Failed to relay message after {max_retries + 1} attempts") from last_error
        raise Exception("Failed to relay message: unknown error")


# Global client instance
_client: BackendClient | None = None


def get_client() -> BackendClient:
    """Get or create the global backend client instance."""
    global _client
    if _client is None:
        _client = BackendClient(config.backend_url)
    return _client

