"""Bot configuration management."""

import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


class BotConfig:
    """Bot configuration loaded from environment variables."""

    def __init__(self) -> None:
        """Initialize configuration from environment variables."""
        self.discord_token: str = os.getenv("DISCORD_TOKEN", "")
        if not self.discord_token:
            raise ValueError("DISCORD_TOKEN environment variable is required")

        self.backend_url: str = os.getenv("BACKEND_URL", "http://localhost:8000")
        # Remove trailing slash if present
        self.backend_url = self.backend_url.rstrip("/")
        self.bot_api_key: str = os.getenv("BOT_API_KEY", "").strip()
        if not self.bot_api_key:
            raise ValueError("BOT_API_KEY environment variable is required")

        self.log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()

    def validate(self) -> bool:
        """Validate that all required configuration is present."""
        return bool(self.discord_token and self.backend_url and self.bot_api_key)


# Global config instance
config = BotConfig()

