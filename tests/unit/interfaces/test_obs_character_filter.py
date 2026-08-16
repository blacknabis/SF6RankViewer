"""Tests for character-based filtering in OBS read API."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

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


def _add_match(
    session: Session,
    *,
    suffix: str,
    occurred_at_ms: int,
    my_character: str,
    opponent_name: str = "Opponent",
    opponent_character: str = "KEN",
    result: str = "WIN",
    my_mr: int | None = 1500,
) -> None:
    session.add(
        MatchModel(
            id=f"match-{suffix}",
            account_id=1,
            identity_key=f"source:{suffix}",
            identity_kind="SOURCE_ID",
            content_sha256="b" * 64,
            occurred_at_ms=occurred_at_ms,
            occurred_at_source="2026-08-16T00:00:00+09:00",
            my_character=my_character,
            my_mr=my_mr,
            my_lp=None,
            opponent_name=opponent_name,
            opponent_character=opponent_character,
            opponent_mr=1500,
            opponent_lp=None,
            result=result,
            created_at_ms=occurred_at_ms,
        )
    )


def test_obs_overlay_filters_by_last_played_character(tmp_path: Path) -> None:
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
        # Add 3 matches:
        # Match 1: RYU, LOSE vs Rival (KEN)
        # Match 2: RYU, WIN vs Rival (KEN)
        # Match 3: CHUN-LI, WIN vs Rival (KEN) -> Last played character is CHUN-LI
        _add_match(
            session,
            suffix="1",
            occurred_at_ms=100,
            my_character="RYU",
            opponent_name="Rival",
            opponent_character="KEN",
            result="LOSE",
            my_mr=1480,
        )
        _add_match(
            session,
            suffix="2",
            occurred_at_ms=200,
            my_character="RYU",
            opponent_name="Rival",
            opponent_character="KEN",
            result="WIN",
            my_mr=1500,
        )
        _add_match(
            session,
            suffix="3",
            occurred_at_ms=300,
            my_character="CHUN-LI",
            opponent_name="Rival",
            opponent_character="KEN",
            result="WIN",
            my_mr=1550,
        )
        session.commit()
    finally:
        session.close()

    with TestClient(create_read_api(session_factory)) as client:
        res = client.get("/api/v1/obs")
        assert res.status_code == 200
        payload = res.json()

        # Last match is CHUN-LI
        assert payload["latest_match"]["my_character"] == "CHUN-LI"

        # Total and Recent should only count CHUN-LI's matches (1 win, 0 loss)
        assert payload["statistics"]["total"] == {"wins": 1, "losses": 0}
        assert payload["statistics"]["recent"] == {"wins": 1, "losses": 0}

        # Opponent stats against 'Rival' while playing CHUN-LI is 1W 0L
        assert payload["statistics"]["opponent_player"]["wins"] == 1
        assert payload["statistics"]["opponent_player"]["losses"] == 0

        # MR history should only contain CHUN-LI's MR point
        assert len(payload["mr_history"]) == 1
        assert payload["mr_history"][0]["mr"] == 1550

        # Now add a new match playing RYU (occurred at 400) -> Last played character becomes RYU
        session = session_factory()
        try:
            _add_match(
                session,
                suffix="4",
                occurred_at_ms=400,
                my_character="RYU",
                opponent_name="Rival",
                opponent_character="KEN",
                result="WIN",
                my_mr=1520,
            )
            session.commit()
        finally:
            session.close()

        res2 = client.get("/api/v1/obs")
        assert res2.status_code == 200
        payload2 = res2.json()

        # Last match is now RYU
        assert payload2["latest_match"]["my_character"] == "RYU"

        # Total and Recent should now count RYU's matches only (2 wins, 1 loss)
        assert payload2["statistics"]["total"] == {"wins": 2, "losses": 1}
        assert payload2["statistics"]["recent"] == {"wins": 2, "losses": 1}

        # Opponent stats against 'Rival' while playing RYU is 2W 1L
        assert payload2["statistics"]["opponent_player"]["wins"] == 2
        assert payload2["statistics"]["opponent_player"]["losses"] == 1

        # MR history should contain 3 points for RYU (1480, 1500, 1520)
        assert len(payload2["mr_history"]) == 3
        assert [p["mr"] for p in payload2["mr_history"]] == [1480, 1500, 1520]

    engine.dispose()


def test_obs_overlay_fallback_to_profile_when_no_matches(tmp_path: Path) -> None:
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
                main_character="GUILE",
                rank_name="MASTER",
                current_mr=1500,
                current_lp=None,
                auth_state="VALID",
                created_at_ms=1,
                updated_at_ms=1,
            )
        )
        session.add(
            JobModel(
                id="job-1",
                type="COLLECT",
                reason="MANUAL",
                state="SUCCEEDED",
                requested_at_ms=1,
            )
        )
        session.flush()
        session.add(
            IngestionRunModel(
                id="ingest-1",
                job_id="job-1",
                account_id=1,
                kind="LIVE",
                parser_version="1",
                state="COMPLETED",
                started_at_ms=1,
                finished_at_ms=2,
                raw_count=1,
                normalized_count=1,
                duplicate_count=0,
                quarantine_count=0,
            )
        )
        session.flush()
        session.add(
            RawRecordModel(
                id="raw-1",
                ingestion_id="ingest-1",
                ordinal=0,
                record_type="PROFILE",
                payload_json=b"{}",
                payload_sha256="c" * 64,
                fetched_at_ms=1,
                disposition="NORMALIZED",
                disposed_at_ms=1,
            )
        )
        session.flush()
        session.add(
            ProfileSnapshotModel(
                id="profile-1",
                account_id=1,
                ingestion_id="ingest-1",
                raw_record_id="raw-1",
                display_name="Player",
                character="GUILE",
                rank_name="MASTER",
                mr=1500,
                lp=None,
                observed_at_ms=1,
            )
        )
        session.commit()
    finally:
        session.close()

    with TestClient(create_read_api(session_factory)) as client:
        res = client.get("/api/v1/obs")
        assert res.status_code == 200
        payload = res.json()
        assert payload["profile"]["character"] == "GUILE"
        assert payload["latest_match"] is None
        assert payload["statistics"]["total"] == {"wins": 0, "losses": 0}
        assert payload["mr_history"] == []

    engine.dispose()


def test_obs_overlay_handles_none_mr_and_100_limit(tmp_path: Path) -> None:
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
                main_character="LUKE",
                rank_name="PLATINUM",
                current_mr=None,
                current_lp=12000,
                auth_state="VALID",
                created_at_ms=1,
                updated_at_ms=1,
            )
        )
        # Add 105 LUKE matches with alternating WIN/LOSE and None MR
        for i in range(1, 106):
            _add_match(
                session,
                suffix=f"luke-{i}",
                occurred_at_ms=1000 + i,
                my_character="LUKE",
                result="WIN" if i % 2 == 1 else "LOSE",
                my_mr=None,
            )
        session.commit()
    finally:
        session.close()

    with TestClient(create_read_api(session_factory)) as client:
        res = client.get("/api/v1/obs")
        assert res.status_code == 200
        payload = res.json()

        # Total games = 105 (53 wins, 52 losses)
        assert payload["statistics"]["total"]["wins"] == 53
        assert payload["statistics"]["total"]["losses"] == 52

        # Recent games = 100 (50 wins, 50 losses)
        assert payload["statistics"]["recent"]["wins"] == 50
        assert payload["statistics"]["recent"]["losses"] == 50

        # No MR values present
        assert payload["mr_history"] == []

    engine.dispose()
