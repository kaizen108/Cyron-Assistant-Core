"""Alembic async environment."""

import asyncio
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
from backend.models import (  # noqa: F401
    Guild,
    Knowledge,
    Ticket,
    UsageLog,
    Message,
    AIContext,
    TicketPanel,
    UserGuild,
)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
config.set_main_option("sqlalchemy.url", backend_config.database_url.replace("+asyncpg", ""))


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
    url = backend_config.database_url
    # Convert asyncpg URL to psycopg2 sync URL and strip SSL query params
    sync_url = url.replace("postgresql+asyncpg://", "postgresql://")
    # Remove ?ssl=require and similar params psycopg2 doesn't accept
    if "?" in sync_url:
        base, params = sync_url.split("?", 1)
        # Keep only params psycopg2 understands (none of the asyncpg-specific ones)
        sync_url = base
    from sqlalchemy import create_engine
    connectable = create_engine(sync_url, poolclass=pool.NullPool, connect_args={"sslmode": "require"})

    with connectable.connect() as connection:
        do_run_migrations(connection)

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
