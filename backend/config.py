"""Backend configuration management."""

import os
from dotenv import load_dotenv

load_dotenv()

# Below this vs top retrieved score → low_confidence flag for UI/analytics.
MIN_SIMILARITY_THRESHOLD: float = 0.35
# Strict KB-anchored answers (high similarity).
SIMILARITY_HIGH: float = 0.55
# Minimum similarity to inject KB at all (best-effort / moderate band is [floor, high)).
SIMILARITY_MODERATE_FLOOR: float = 0.25
# Minimum score to return candidates from vector search (below → no KB injection).
MIN_SIMILARITY_RETRIEVAL: float = 0.25
# v2.2 aggressive compact path — trigger more often, earlier.
COMPACT_STRONG_MATCH: float = 0.52
COMPACT_HIGH_MATCH: float = 0.42
COMPACT_EARLY_EXIT_SIM: float = 0.50
COMPACT_MAX_QUERY_WORDS: int = 25
COMPACT_MAX_QUERY_CHARS: int = 180
# Redis cache for short-query replies (seconds).
COMPACT_CACHE_TTL_SEC: int = 604_800  # 7 days


class BackendConfig:
    """Backend configuration loaded from environment variables."""

    def __init__(self) -> None:
        """Initialize configuration from environment variables."""
        self.host: str = os.getenv("HOST", "0.0.0.0")
        self.port: int = int(os.getenv("PORT", "8000"))
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()
        self.database_url: str = os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_ticket_assistant",
        )
        self.redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        # Bot-to-backend internal auth (mandatory for /relay and /internal/bot/*).
        self.bot_api_key: str = os.getenv("BOT_API_KEY", "").strip()
        # AI provider configuration (Phase 3)
        self.openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
        self.openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.gemini_api_key: str | None = os.getenv("GEMINI_API_KEY")
        self.gemini_model: str | None = os.getenv("GEMINI_MODEL")
        self.openai_max_tokens: int = int(os.getenv("OPENAI_MAX_TOKENS", "400"))
        self.openai_temperature: float = float(
            os.getenv("OPENAI_TEMPERATURE", "0.2")
        )
        # Auth / OAuth configuration (Phase 4 dashboard login)
        self.discord_client_id: str | None = os.getenv("DISCORD_CLIENT_ID")
        self.discord_client_secret: str | None = os.getenv("DISCORD_CLIENT_SECRET")
        self.discord_oauth_scope: str = os.getenv("DISCORD_OAUTH_SCOPE", "identify guilds")
        self.auth_jwt_secret: str = os.getenv(
            "AUTH_JWT_SECRET", "change-this-in-production"
        )
        self.auth_jwt_algorithm: str = os.getenv("AUTH_JWT_ALGORITHM", "HS256")
        self.auth_jwt_exp_minutes: int = int(
            os.getenv("AUTH_JWT_EXP_MINUTES", "1440")
        )
        self.frontend_allowed_origins: list[str] = [
            origin.strip().rstrip("/")
            for origin in os.getenv(
                "FRONTEND_ALLOWED_ORIGINS", "http://localhost:5173"
            ).split(",")
            if origin.strip()
        ]
        self.frontend_public_url: str = os.getenv(
            "FRONTEND_PUBLIC_URL", self.frontend_allowed_origins[0]
        ).rstrip("/")
        self.discord_oauth_allowed_redirect_uris: list[str] = [
            uri.strip().rstrip("/")
            for uri in os.getenv(
                "DISCORD_OAUTH_ALLOWED_REDIRECT_URIS",
                "http://localhost:5173/auth/callback",
            ).split(",")
            if uri.strip()
        ]
        self.backend_public_url: str = os.getenv(
            "BACKEND_PUBLIC_URL", f"http://{self.host}:{self.port}"
        ).rstrip("/")
        self.reload: bool = os.getenv("RELOAD", "false").lower() in (
            "1",
            "true",
            "yes",
        )


# Global config instance
config = BackendConfig()

