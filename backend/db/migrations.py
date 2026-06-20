"""Alembic migration runner."""

from pathlib import Path

from alembic import command
from alembic.config import Config


def run_migrations() -> None:
    """Apply all pending Alembic migrations."""
    project_root = Path(__file__).resolve().parent.parent.parent
    alembic_cfg = Config(str(project_root / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")
