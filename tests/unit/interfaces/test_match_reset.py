"""Regression coverage for non-destructive visible match-history reset."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import sf6viewer
from sf6viewer.infrastructure.db.engine import create_engine_for, create_session_factory
from sf6viewer.infrastructure.db.models import AccountModel, Base, MatchModel, SettingsModel
from sf6viewer.infrastructure.storage.app_paths import AppPaths
from sf6viewer.interfaces.api import create_read_api
from sf6viewer.interfaces.runtime.desktop import NativeLoginBridge


def _add_match(session: Session, *, suffix: str, occurred_at_ms: int, result: str) -> None:
    session.add(
        MatchModel(
            id=f"match-{suffix}",
            account_id=1,
            identity_key=f"source:{suffix}",
            identity_kind="SOURCE_ID",
            content_sha256="a" * 64,
            occurred_at_ms=occurred_at_ms,
            occurred_at_source="2026-07-19T00:00:00+09:00",
            my_character="RYU",
            my_mr=1500,
            my_lp=None,
            opponent_name=f"opponent-{suffix}",
            opponent_character="KEN",
            opponent_mr=1500,
            opponent_lp=None,
            result=result,
            created_at_ms=occurred_at_ms,
        )
    )


def test_reset_hides_existing_matches_and_preserves_future_matches(tmp_path: Path) -> None:
    paths = AppPaths.from_root(tmp_path.resolve())
    paths.ensure_directories()
    engine = create_engine_for(paths)
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    session = session_factory()
    try:
        session.add(
            AccountModel(
                id=1,
                user_code="1234567890",
                display_name="Player",
                main_character="RYU",
                rank_name="MASTER",
                current_mr=1500,
                current_lp=None,
                auth_state="VALID",
                created_at_ms=1,
                updated_at_ms=1,
            )
        )
        session.flush()
        _add_match(session, suffix="before-reset", occurred_at_ms=1, result="LOSE")
        session.commit()
    finally:
        session.close()

    bridge = NativeLoginBridge(paths, session_factory)
    try:
        result = bridge.clear_matches()
    finally:
        bridge.close()
    assert result == {"ok": True, "cleared": 1}

    session = session_factory()
    try:
        assert session.scalar(select(func.count()).select_from(MatchModel)) == 1
        settings = session.get(SettingsModel, 1)
        assert settings is not None
        assert settings.match_reset_at_ms is not None
        reset_at_ms = settings.match_reset_at_ms
    finally:
        session.close()

    with TestClient(create_read_api(session_factory)) as client:
        assert client.get("/api/v1/system").json()["app_version"] == sf6viewer.__version__
        assert client.get("/api/v1/system").json()["match_count"] == 0
        assert client.get("/api/v1/matches/latest").json()["page"]["total"] == 0
        assert client.get("/api/v1/obs").json()["statistics"]["total"] == {
            "wins": 0,
            "losses": 0,
        }

        session = session_factory()
        try:
            _add_match(
                session,
                suffix="after-reset",
                occurred_at_ms=reset_at_ms + 1,
                result="WIN",
            )
            session.commit()
        finally:
            session.close()

        assert client.get("/api/v1/system").json()["match_count"] == 1
        assert client.get("/api/v1/matches/latest").json()["page"]["total"] == 1
        assert client.get("/api/v1/obs").json()["statistics"]["total"] == {
            "wins": 1,
            "losses": 0,
        }

    engine.dispose()
