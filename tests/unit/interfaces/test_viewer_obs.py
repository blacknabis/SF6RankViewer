"""Contract tests for the character-aligned OBS viewer projection."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from sf6viewer.infrastructure.db.engine import create_engine_for, create_session_factory
from sf6viewer.infrastructure.db.models import (
    AccountModel,
    Base,
    IngestionRunModel,
    JobModel,
    MatchModel,
    ProfileSnapshotModel,
    RawRecordModel,
)
from sf6viewer.infrastructure.storage.app_paths import AppPaths
from sf6viewer.interfaces.api import create_read_api


@pytest.fixture
def viewer_database(
    tmp_path: Path,
) -> Iterator[tuple[sessionmaker[Session], Engine]]:
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
                display_name="Account Player",
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
    finally:
        session.close()
    yield session_factory, engine
    engine.dispose()


def _add_profile(
    session: Session,
    *,
    suffix: str,
    observed_at_ms: int,
    display_name: str | None,
    character: str | None,
    rank_name: str | None,
    mr: int | None,
    lp: int | None,
) -> None:
    job_id = f"job-{suffix}"
    ingestion_id = f"ingestion-{suffix}"
    raw_id = f"raw-{suffix}"
    session.add(
        JobModel(
            id=job_id,
            type="COLLECT",
            reason="MANUAL",
            state="SUCCEEDED",
            requested_at_ms=observed_at_ms,
        )
    )
    session.flush()
    session.add(
        IngestionRunModel(
            id=ingestion_id,
            job_id=job_id,
            account_id=1,
            kind="LIVE",
            parser_version="1",
            state="COMPLETED",
            started_at_ms=observed_at_ms,
            finished_at_ms=observed_at_ms,
            raw_count=1,
            normalized_count=1,
            duplicate_count=0,
            quarantine_count=0,
        )
    )
    session.flush()
    session.add(
        RawRecordModel(
            id=raw_id,
            ingestion_id=ingestion_id,
            ordinal=0,
            record_type="PROFILE",
            payload_json=b"{}",
            payload_sha256="a" * 64,
            fetched_at_ms=observed_at_ms,
            disposition="NORMALIZED",
            disposed_at_ms=observed_at_ms,
        )
    )
    session.flush()
    session.add(
        ProfileSnapshotModel(
            id=f"profile-{suffix}",
            account_id=1,
            ingestion_id=ingestion_id,
            raw_record_id=raw_id,
            display_name=display_name,
            character=character,
            rank_name=rank_name,
            mr=mr,
            lp=lp,
            observed_at_ms=observed_at_ms,
        )
    )


def _add_match(
    session: Session,
    *,
    suffix: str,
    occurred_at_ms: int,
    character: str,
    mr: int | None,
    lp: int | None,
) -> None:
    session.add(
        MatchModel(
            id=f"match-{suffix}",
            account_id=1,
            identity_key=f"source:{suffix}",
            identity_kind="SOURCE_ID",
            content_sha256="b" * 64,
            occurred_at_ms=occurred_at_ms,
            occurred_at_source="2026-08-29T00:00:00+09:00",
            my_character=character,
            my_mr=mr,
            my_lp=lp,
            opponent_name=f"Opponent {suffix}",
            opponent_character="KEN",
            opponent_mr=1500,
            opponent_lp=None,
            result="WIN",
            created_at_ms=occurred_at_ms,
        )
    )


def _obs_payload(session_factory: sessionmaker[Session]) -> dict[str, object]:
    with TestClient(create_read_api(session_factory)) as client:
        response = client.get("/api/v1/obs")
    assert response.status_code == 200
    return response.json()


def test_empty_viewer_response_shape_and_nullability(
    viewer_database: tuple[sessionmaker[Session], Engine],
) -> None:
    session_factory, _ = viewer_database

    payload = _obs_payload(session_factory)

    assert payload["schema_version"] == "2"
    assert payload["viewer_profile"] is None
    assert payload["session"]["boundary_kind"] == "APP_START"
    assert isinstance(payload["session"]["started_at_ms"], int)
    assert payload["session"] | {"started_at_ms": 0} == {
        "started_at_ms": 0,
        "boundary_kind": "APP_START",
        "baseline_mr": None,
        "current_mr": None,
        "delta": None,
        "decisive_matches": 0,
    }
    assert payload["streak"] is None
    assert payload["matchups"] == []
    assert payload["mr_history"] == []


def test_profile_only_viewer_profile_uses_latest_tie_and_profile_values(
    viewer_database: tuple[sessionmaker[Session], Engine],
) -> None:
    session_factory, _ = viewer_database
    session = session_factory()
    try:
        _add_profile(
            session,
            suffix="a",
            observed_at_ms=100,
            display_name="Older Tie",
            character="RYU",
            rank_name="DIAMOND",
            mr=1400,
            lp=20000,
        )
        _add_profile(
            session,
            suffix="b",
            observed_at_ms=100,
            display_name="Latest Profile",
            character="GUILE",
            rank_name="MASTER",
            mr=1666,
            lp=None,
        )
        session.commit()
    finally:
        session.close()

    payload = _obs_payload(session_factory)

    assert payload["profile"] == {
        "id": "profile-b",
        "display_name": "Latest Profile",
        "character": "GUILE",
        "rank_name": "MASTER",
        "mr": 1666,
        "lp": None,
        "observed_at_ms": 100,
    }
    assert payload["viewer_profile"] == {
        "display_name": "Latest Profile",
        "character": "GUILE",
        "rank_name": "MASTER",
        "mr": 1666,
        "lp": None,
    }


def test_match_only_viewer_profile_uses_latest_match_tie_even_when_values_null(
    viewer_database: tuple[sessionmaker[Session], Engine],
) -> None:
    session_factory, _ = viewer_database
    session = session_factory()
    try:
        _add_match(
            session,
            suffix="a",
            occurred_at_ms=200,
            character="RYU",
            mr=1700,
            lp=22000,
        )
        _add_match(
            session,
            suffix="b",
            occurred_at_ms=200,
            character="JURI",
            mr=None,
            lp=None,
        )
        session.commit()
    finally:
        session.close()

    payload = _obs_payload(session_factory)

    assert payload["latest_match"]["id"] == "match-b"
    assert payload["viewer_profile"] == {
        "display_name": None,
        "character": "JURI",
        "rank_name": None,
        "mr": None,
        "lp": None,
    }


def test_mismatched_latest_profile_and_match_character_profile_is_character_aligned(
    viewer_database: tuple[sessionmaker[Session], Engine],
) -> None:
    session_factory, _ = viewer_database
    session = session_factory()
    try:
        _add_profile(
            session,
            suffix="latest",
            observed_at_ms=300,
            display_name="Profile Name",
            character="RYU",
            rank_name="MASTER",
            mr=1900,
            lp=30000,
        )
        _add_match(
            session,
            suffix="older-juri",
            occurred_at_ms=400,
            character="JURI",
            mr=1600,
            lp=21000,
        )
        _add_match(
            session,
            suffix="latest-juri",
            occurred_at_ms=500,
            character="JURI",
            mr=None,
            lp=21500,
        )
        session.commit()
    finally:
        session.close()

    payload = _obs_payload(session_factory)

    assert payload["viewer_profile"] == {
        "display_name": "Profile Name",
        "character": "JURI",
        "rank_name": None,
        "mr": None,
        "lp": 21500,
    }
