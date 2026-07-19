"""SQLite engine, session, and Alembic entry points."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, URL, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from sf6viewer.infrastructure.storage.app_paths import AppPaths


def _require_absolute_database_path(database_path: Path) -> Path:
    """Return a resolved database path without resolving a relative input."""
    if not isinstance(database_path, Path) or not database_path.is_absolute():
        raise ValueError("Database path must be absolute.")
    return database_path.resolve(strict=False)


def _sqlite_url(database_path: Path) -> URL:
    """Build a file-backed SQLite URL from a validated absolute path."""
    return URL.create("sqlite+pysqlite", database=str(database_path))


def _configure_sqlite_connection(dbapi_connection: Any, _: Any) -> None:
    """Apply the application's required pragmas to every SQLite connection."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA temp_store=MEMORY")
    finally:
        cursor.close()


def _create_sqlite_engine(database_path: Path) -> Engine:
    """Create a configured SQLite engine for one already-validated database path."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(_sqlite_url(database_path))
    event.listen(engine, "connect", _configure_sqlite_connection)
    return engine


def create_engine_for(paths: AppPaths) -> Engine:
    """Create a configured SQLite engine for the explicitly supplied application paths."""
    database_path = _require_absolute_database_path(paths.database)
    return _create_sqlite_engine(database_path)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create application sessions with explicit flush and expiry behavior."""
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False, autoflush=False)


def run_migrations(database_path: Path, revision: str = "head") -> None:
    """Upgrade one explicit SQLite database without consulting ambient application paths."""
    resolved_database_path = _require_absolute_database_path(database_path)
    project_root = Path(__file__).resolve().parents[4]
    config = Config(str(project_root / "alembic.ini"))

    engine = _create_sqlite_engine(resolved_database_path)
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            config.attributes["database_path"] = resolved_database_path
            command.upgrade(config, revision)
    finally:
        engine.dispose()
