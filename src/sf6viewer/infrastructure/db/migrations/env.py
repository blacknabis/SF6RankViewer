"""Alembic environment with explicit database-path handling."""

from __future__ import annotations

from logging.config import fileConfig
from pathlib import Path
from typing import Any

from alembic import context
from sqlalchemy import URL, create_engine, pool
from sqlalchemy.engine import Connection

from sf6viewer.infrastructure.db.models.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _sqlite_url(database_path: Path) -> URL:
    """Build a file-backed SQLite URL from a validated absolute path."""
    return URL.create("sqlite+pysqlite", database=str(database_path))


def _required_database_path() -> Path:
    """Get an injected or CLI-provided absolute database path, never a default."""
    configured_path: Any = config.attributes.get("database_path")
    if configured_path is None:
        configured_path = context.get_x_argument(as_dictionary=True).get("db_path")
    if configured_path is None:
        raise RuntimeError("Database path is required.")

    try:
        database_path = Path(configured_path)
    except TypeError as error:
        raise ValueError("Database path must be absolute.") from error
    if not database_path.is_absolute():
        raise ValueError("Database path must be absolute.")
    return database_path.resolve(strict=False)


def _configure_context(connection: Connection | None = None, *, url: URL | None = None) -> None:
    """Configure Alembic against either a supplied connection or a validated URL."""
    options: dict[str, Any] = {
        "target_metadata": target_metadata,
        "compare_type": True,
        "compare_server_default": True,
    }
    if connection is not None:
        options["connection"] = connection
    elif url is not None:
        options.update(
            {"url": str(url), "literal_binds": True, "dialect_opts": {"paramstyle": "named"}}
        )
    else:
        raise RuntimeError("Migration connection is required.")
    context.configure(**options)


def run_migrations_offline() -> None:
    """Run migrations in SQL-rendering mode for an explicit absolute database path."""
    _configure_context(url=_sqlite_url(_required_database_path()))

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations using a caller-supplied connection or explicit CLI path."""
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        _configure_context(connection=supplied_connection)
        with context.begin_transaction():
            context.run_migrations()
        return

    connectable = create_engine(_sqlite_url(_required_database_path()), poolclass=pool.NullPool)
    try:
        with connectable.connect() as connection:
            _configure_context(connection=connection)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
