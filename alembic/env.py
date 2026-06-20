"""Alembic async environment."""

from logging.config import fileConfig

from sqlalchemy import create_engine, pool
from sqlalchemy.engine import Connection

from alembic import context

# Import models and config
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from backend.config import config as backend_config
from backend.db.base import Base
from backend.models import Guild, Knowledge, Ticket, UsageLog, Message  # noqa: F401
from backend.models.ai_context import AIContext  # noqa: F401
from backend.models.ticket_panel import TicketPanel  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
config.set_main_option("sqlalchemy.url", backend_config.database_url.replace("+asyncpg", ""))


def _sync_url_and_connect_args(url: str) -> tuple[str, dict]:
    """Convert async URL to psycopg2 sync URL and choose SSL mode."""
    sync_url = url.replace("postgresql+asyncpg://", "postgresql://")
    connect_args: dict = {}
    ssl_required = False

    if "?" in sync_url:
        base, params = sync_url.split("?", 1)
        sync_url = base
        lowered = params.lower()
        if "ssl=require" in lowered or "sslmode=require" in lowered:
            ssl_required = True

    host_part = sync_url.split("@")[-1] if "@" in sync_url else sync_url
    if any(
        marker in host_part
        for marker in ("neon.tech", "amazonaws.com", "supabase.co", "render.com")
    ):
        ssl_required = True

    if ssl_required:
        connect_args["sslmode"] = "require"
    elif any(marker in host_part for marker in ("localhost", "127.0.0.1", "postgres:")):
        connect_args["sslmode"] = "prefer"

    return sync_url, connect_args


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    url = url.replace("postgresql://", "postgresql+asyncpg://")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    sync_url, connect_args = _sync_url_and_connect_args(backend_config.database_url)
    connectable = create_engine(
        sync_url,
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )

    with connectable.connect() as connection:
        do_run_migrations(connection)

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
