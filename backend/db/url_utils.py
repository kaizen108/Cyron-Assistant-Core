"""Database URL helpers."""

from urllib.parse import urlparse


def postgres_sslmode(database_url: str, override: str | None = None) -> str:
    """Pick psycopg2 sslmode for Alembic/sync connections.

    Docker Compose Postgres (host ``postgres``) does not use TLS.
    """
    if override:
        return override.strip()
    parsed = urlparse(
        database_url.replace("postgresql+asyncpg://", "postgresql://")
    )
    host = (parsed.hostname or "").lower()
    if host in {"postgres", "localhost", "127.0.0.1"}:
        return "disable"
    return "prefer"
