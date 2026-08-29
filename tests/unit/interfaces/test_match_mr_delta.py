"""Regression coverage for safe per-character match MR deltas."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from sf6viewer.infrastructure.db.engine import create_engine_for, create_session_factory
from sf6viewer.infrastructure.db.models import AccountModel, Base, MatchModel, SettingsModel
from sf6viewer.infrastructure.storage.app_paths import AppPaths
from sf6viewer.interfaces.api import create_read_api


def _add_match(
    session: Session,
    *,
    suffix: str,
    occurred_at_ms: int,
    my_character: str,
    my_mr: int | None,
) -> None:
    session.add(
        MatchModel(
            id=f"match-{suffix}",
            account_id=1,
            identity_key=f"source:{suffix}",
            identity_kind="SOURCE_ID",
            content_sha256="d" * 64,
            occurred_at_ms=occurred_at_ms,
            occurred_at_source="2026-08-29T00:00:00+09:00",
            my_character=my_character,
            my_mr=my_mr,
            my_lp=None,
            opponent_name=f"opponent-{suffix}",
            opponent_character="KEN",
            opponent_mr=1500,
            opponent_lp=None,
            result="WIN",
            created_at_ms=occurred_at_ms,
        )
    )


@contextmanager
def _client(tmp_path: Path) -> Iterator[tuple[TestClient, Session]]:
    paths = AppPaths.from_root(tmp_path.resolve())
    paths.ensure_directories()
    engine = create_engine_for(paths)
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    session = session_factory()
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
    session.commit()
    try:
        with TestClient(create_read_api(session_factory)) as client:
            yield client, session
    finally:
        session.close()
        engine.dispose()


def test_mr_delta_uses_same_character_predecessor_across_interleaved_characters(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as (client, session):
        _add_match(session, suffix="ryu-old", occurred_at_ms=100, my_character="RYU", my_mr=1500)
        _add_match(
            session,
            suffix="chun-li",
            occurred_at_ms=200,
            my_character="CHUN-LI",
            my_mr=1600,
        )
        _add_match(session, suffix="ryu-new", occurred_at_ms=300, my_character="RYU", my_mr=1520)
        session.commit()

        items = client.get("/api/v1/matches/latest").json()["items"]

        assert items[0]["id"] == "match-ryu-new"
        assert items[0]["mr_delta"] == 20
        assert client.get("/api/v1/obs").json()["latest_match"]["mr_delta"] == 20


def test_mr_delta_skips_null_mr_predecessor(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, session):
        _add_match(session, suffix="known-old", occurred_at_ms=100, my_character="RYU", my_mr=1400)
        _add_match(session, suffix="unknown", occurred_at_ms=200, my_character="RYU", my_mr=None)
        _add_match(session, suffix="known-new", occurred_at_ms=300, my_character="RYU", my_mr=1430)
        session.commit()

        items = client.get("/api/v1/matches/latest").json()["items"]

        assert items[0]["mr_delta"] == 30
        assert items[1]["mr_delta"] is None


def test_mr_delta_finds_predecessor_across_pagination_boundary(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, session):
        _add_match(session, suffix="old", occurred_at_ms=100, my_character="RYU", my_mr=1500)
        _add_match(session, suffix="new", occurred_at_ms=200, my_character="RYU", my_mr=1512)
        session.commit()

        payload = client.get("/api/v1/matches/latest?page=1&page_size=1").json()

        assert payload["page"] == {"page": 1, "page_size": 1, "total": 2}
        assert payload["items"][0]["id"] == "match-new"
        assert payload["items"][0]["mr_delta"] == 12


def test_mr_delta_excludes_reset_hidden_predecessor(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, session):
        _add_match(session, suffix="hidden", occurred_at_ms=100, my_character="RYU", my_mr=1400)
        session.add(SettingsModel(id=1, match_reset_at_ms=150))
        _add_match(session, suffix="visible", occurred_at_ms=200, my_character="RYU", my_mr=1450)
        session.commit()

        payload = client.get("/api/v1/matches/latest").json()

        assert payload["page"]["total"] == 1
        assert payload["items"][0]["id"] == "match-visible"
        assert payload["items"][0]["mr_delta"] is None
        assert client.get("/api/v1/obs").json()["latest_match"]["mr_delta"] is None
