"""Behavioral coverage for durable in-app viewer display preferences."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sf6viewer.infrastructure.db.engine import (
    create_engine_for,
    create_session_factory,
    run_migrations,
)
from sf6viewer.infrastructure.db.models import Base, SettingsModel
from sf6viewer.infrastructure.storage.app_paths import AppPaths
from sf6viewer.interfaces.runtime.desktop import NativeLoginBridge


def _database(tmp_path: Path) -> tuple[AppPaths, Engine, Callable[[], Session]]:
    paths = AppPaths.from_root(tmp_path.resolve())
    paths.ensure_directories()
    engine = create_engine_for(paths)
    Base.metadata.create_all(engine)
    return paths, engine, create_session_factory(engine)


def _assert_direct_preference_constraints(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO settings (id) VALUES (1)"))

    for delta_mode in ("SESSION", " session", "invalid"):
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text("UPDATE settings SET viewer_delta_mode = :mode WHERE id = 1"),
                {"mode": delta_mode},
            )

    for chart_limit in (True, 19, 49, 101):
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text("UPDATE settings SET viewer_chart_limit = :limit WHERE id = 1"),
                {"limit": chart_limit},
            )


def test_viewer_preferences_default_when_settings_row_is_missing(tmp_path: Path) -> None:
    paths, engine, session_factory = _database(tmp_path)
    bridge = NativeLoginBridge(paths, session_factory)
    try:
        assert bridge.viewer_preferences() == {
            "ok": True,
            "delta_mode": "session",
            "chart_limit": 50,
        }
    finally:
        bridge.close()
        engine.dispose()


def test_valid_viewer_preferences_persist_across_bridge_instances(tmp_path: Path) -> None:
    paths, engine, session_factory = _database(tmp_path)
    bridge = NativeLoginBridge(paths, session_factory)
    try:
        assert bridge.set_viewer_preferences("range", 100) == {
            "ok": True,
            "delta_mode": "range",
            "chart_limit": 100,
        }
    finally:
        bridge.close()

    restored_bridge = NativeLoginBridge(paths, session_factory)
    try:
        assert restored_bridge.viewer_preferences() == {
            "ok": True,
            "delta_mode": "range",
            "chart_limit": 100,
        }
    finally:
        restored_bridge.close()
        engine.dispose()


def test_invalid_viewer_preferences_are_rejected_without_mutation(tmp_path: Path) -> None:
    paths, engine, session_factory = _database(tmp_path)
    bridge = NativeLoginBridge(paths, session_factory)
    valid = {"ok": True, "delta_mode": "range", "chart_limit": 20}
    rejected = {"ok": False, "code": "INTERNAL.UNEXPECTED"}
    try:
        assert bridge.set_viewer_preferences("range", 20) == valid

        for delta_mode in ("SESSION", " session", "invalid"):
            assert bridge.set_viewer_preferences(delta_mode, 20) == rejected
            assert bridge.viewer_preferences() == valid

        for chart_limit in (True, 19, 49, 101):
            assert bridge.set_viewer_preferences("range", chart_limit) == rejected
            assert bridge.viewer_preferences() == valid
    finally:
        bridge.close()
        engine.dispose()


def test_alembic_migration_and_orm_constraints_match(tmp_path: Path) -> None:
    migrated_paths = AppPaths.from_root((tmp_path / "migrated-app").resolve())
    migrated_paths.ensure_directories()
    run_migrations(migrated_paths.database)

    # Inspect and exercise the exact database Alembic produced.
    migrated_engine = create_engine_for(migrated_paths)
    try:
        columns = {
            column["name"]: column
            for column in inspect(migrated_engine).get_columns("settings")
        }
        assert columns["viewer_delta_mode"]["nullable"] is False
        assert str(columns["viewer_delta_mode"]["default"]).strip("'\"") == "session"
        assert columns["viewer_chart_limit"]["nullable"] is False
        assert str(columns["viewer_chart_limit"]["default"]).strip("'\"") == "50"
        _assert_direct_preference_constraints(migrated_engine)
    finally:
        migrated_engine.dispose()

    orm_paths = AppPaths.from_root((tmp_path / "orm-app").resolve())
    orm_paths.ensure_directories()
    orm_engine = create_engine_for(orm_paths)
    try:
        Base.metadata.create_all(orm_engine)
        constraint_names = {
            constraint.name for constraint in SettingsModel.__table__.constraints
        }
        assert "ck_settings_viewer_delta_mode" in constraint_names
        assert "ck_settings_viewer_chart_limit" in constraint_names
        _assert_direct_preference_constraints(orm_engine)
    finally:
        orm_engine.dispose()
