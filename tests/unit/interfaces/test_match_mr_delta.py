"""Estimate match MR changes only from consecutive live replay observations."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from sf6viewer.infrastructure.db.engine import create_engine_for, create_session_factory
from sf6viewer.infrastructure.db.models import (
    AccountModel,
    Base,
    IngestionRunModel,
    JobModel,
    MatchModel,
    MatchObservationModel,
    RawRecordModel,
    SettingsModel,
)
from sf6viewer.infrastructure.storage.app_paths import AppPaths
from sf6viewer.interfaces.api import create_read_api


def _add_match(
    session: Session, suffix: str, occurred_at_ms: int, my_mr: int | None,
    *, character: str = "KIMBERLY", result: str = "WIN",
) -> None:
    session.add(MatchModel(
        id=suffix, account_id=1, identity_key=f"source:{suffix}", identity_kind="SOURCE_ID",
        content_sha256="d" * 64, occurred_at_ms=occurred_at_ms,
        occurred_at_source="2026-09-06T01:53:00+09:00", my_character=character,
        my_mr=my_mr, my_lp=None, opponent_name="nana", opponent_character="ALEX",
        opponent_mr=1630, opponent_lp=None, result=result, created_at_ms=10000,
    ))
    session.flush()


def _capture(
    session: Session, match_ids: list[str | None], *, capture_id: str = "capture",
    kind: str = "LIVE", parser: str = "buckler-battlelog-v3", account_id: int | None = 1,
    duplicates: set[str] | None = None,
) -> None:
    """Capture IDs in upstream newest-first ordinal order; None is quarantined."""
    session.add(JobModel(
        id=f"job-{capture_id}", type="COLLECT", reason="SCHEDULED", state="SUCCEEDED",
        phase="MATCHES", requested_at_ms=10000,
    ))
    session.flush()
    session.add(IngestionRunModel(
        id=capture_id, job_id=f"job-{capture_id}", account_id=account_id, kind=kind,
        parser_version=parser,
        state="COMPLETED_WITH_WARNINGS" if None in match_ids else "COMPLETED",
        started_at_ms=10000, finished_at_ms=10001, raw_count=len(match_ids),
        normalized_count=sum(match_id is not None for match_id in match_ids),
        duplicate_count=0, quarantine_count=match_ids.count(None),
    ))
    session.flush()
    for ordinal, match_id in enumerate(match_ids):
        raw_id = f"{capture_id}-{ordinal}"
        disposition = "NORMALIZED" if match_id else "QUARANTINED"
        if duplicates is not None and match_id in duplicates:
            disposition = "DUPLICATE"
        session.add(RawRecordModel(
            id=raw_id, ingestion_id=capture_id, ordinal=ordinal, record_type="MATCH",
            source_key=match_id, payload_json=b"{}", payload_sha256="a" * 64,
            fetched_at_ms=10000, disposed_at_ms=10001,
            disposition=disposition,
        ))
        session.flush()
        if match_id is not None:
            session.add(MatchObservationModel(
                id=f"observation-{raw_id}", match_id=match_id, raw_record_id=raw_id,
                ingestion_id=capture_id, observed_content_sha256="d" * 64,
                observed_at_ms=10000,
            ))
    session.flush()


@contextmanager
def _client(tmp_path: Path) -> Iterator[tuple[TestClient, Session]]:
    paths = AppPaths.from_root(tmp_path.resolve())
    paths.ensure_directories()
    engine = create_engine_for(paths)
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    session = session_factory()
    session.add(AccountModel(
        id=1, user_code="1234567890", display_name="Player", main_character="KIMBERLY",
        rank_name="MASTER", current_mr=1500, current_lp=None, auth_state="VALID",
        created_at_ms=1, updated_at_ms=1,
    ))
    session.commit()
    try:
        with TestClient(create_read_api(session_factory)) as client:
            yield client, session
    finally:
        session.close()
        engine.dispose()


def _estimates(client: TestClient) -> dict[str, tuple[int | None, str]]:
    return {
        item["id"]: (item["mr_delta"], item["mr_delta_status"])
        for item in client.get("/api/v1/matches/latest").json()["items"]
    }


def test_reported_loss_win_win_sequence_assigns_change_to_the_finished_match(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as (client, session):
        _add_match(session, "01:49-loss", 100, 1633, result="LOSE")
        _add_match(session, "01:53-win", 200, 1625)
        _add_match(session, "01:54-win", 300, 1633)
        _capture(session, ["01:54-win", "01:53-win", "01:49-loss"])
        session.commit()

        items = client.get("/api/v1/matches/latest").json()["items"]
        assert items[1]["mr_delta"] == 8
        assert _estimates(client) == {
            "01:54-win": (None, "pending"),
            "01:53-win": (8, "estimated"),
            "01:49-loss": (-8, "estimated"),
        }
        latest = client.get("/api/v1/obs").json()["latest_match"]
        assert (latest["mr_delta"], latest["mr_delta_status"]) == (None, "pending")
        second_page = client.get("/api/v1/matches/latest?page=2&page_size=1").json()
        assert second_page["items"][0]["mr_delta"] == 8
        assert second_page["page"] == {"page": 2, "page_size": 1, "total": 3}


def test_next_null_mr_is_not_skipped_to_manufacture_an_estimate(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, session):
        _add_match(session, "old", 100, 1600)
        _add_match(session, "unknown", 200, None)
        _add_match(session, "new", 300, 1620)
        _capture(session, ["new", "unknown", "old"])
        session.commit()
        assert _estimates(client) == {
            "new": (None, "pending"),
            "unknown": (None, "unavailable"),
            "old": (None, "unavailable"),
        }


def test_latest_match_with_unknown_mr_is_unavailable_not_pending(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, session):
        _add_match(session, "latest", 100, None)
        _capture(session, ["latest"])
        session.commit()
        assert _estimates(client) == {"latest": (None, "unavailable")}
        assert client.get("/api/v1/obs").json()["latest_match"]["mr_delta_status"] == "unavailable"


@pytest.mark.parametrize("capture_order", [None, ["new", None, "old"], ["old", "new"]])
def test_missing_quarantined_or_reversed_capture_evidence_is_unavailable(
    tmp_path: Path, capture_order: list[str | None] | None,
) -> None:
    with _client(tmp_path) as (client, session):
        _add_match(session, "old", 100, 1600)
        _add_match(session, "new", 200, 1608)
        if capture_order is None:
            _capture(session, ["old"], capture_id="old-snapshot")
            _capture(session, ["new"], capture_id="new-snapshot")
        else:
            _capture(session, capture_order)
        session.commit()
        assert _estimates(client)["old"] == (None, "unavailable")


def test_interleaved_character_is_not_treated_as_a_contiguous_pair(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, session):
        _add_match(session, "old", 100, 1600)
        _add_match(session, "other", 200, 1400, character="RYU")
        _add_match(session, "new", 300, 1608)
        _capture(session, ["new", "other", "old"])
        session.commit()
        assert _estimates(client) == {
            "new": (None, "pending"), "other": (None, "pending"),
            "old": (None, "unavailable"),
        }


@pytest.mark.parametrize("tie_time", [100, 200])
def test_equal_timestamp_order_is_unavailable_regardless_of_ids(
    tmp_path: Path, tie_time: int,
) -> None:
    with _client(tmp_path) as (client, session):
        _add_match(session, "z-old", 100, 1600)
        _add_match(session, "a-new", 200, 1608)
        _add_match(session, "tie", tie_time, 1604)
        _capture(session, ["a-new", "z-old"])
        session.commit()
        assert _estimates(client)["z-old"] == (None, "unavailable")
        assert _estimates(client)["tie"] == (None, "unavailable")


def test_conflicting_live_witnesses_are_unavailable(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, session):
        _add_match(session, "old", 100, 1600)
        _add_match(session, "next", 200, 1608)
        _add_match(session, "later", 300, 1616)
        _capture(session, ["next", "old"], capture_id="complete")
        _capture(session, ["later", "old"], capture_id="contradiction")
        session.commit()
        assert _estimates(client)["old"] == (None, "unavailable")


def test_a_later_interleaved_capture_conflicts_with_an_earlier_adjacent_pair(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as (client, session):
        _add_match(session, "old", 100, 1600)
        _add_match(session, "other", 200, 1400, character="RYU")
        _add_match(session, "new", 300, 1608)
        _capture(session, ["new", "old"], capture_id="first")
        _capture(session, ["new", "other", "old"], capture_id="later")
        session.commit()
        assert _estimates(client)["old"] == (None, "unavailable")


def test_repeated_observations_do_not_duplicate_matches_or_break_pagination(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, session):
        _add_match(session, "old", 100, 1600)
        _add_match(session, "new", 200, 1608)
        _capture(session, ["new", "old"], capture_id="first")
        _capture(session, ["new", "old"], capture_id="repeat", duplicates={"new", "old"})
        session.commit()
        assert _estimates(client)["old"] == (8, "estimated")
        payload = client.get("/api/v1/matches/latest?page=2&page_size=1").json()
        assert payload["page"]["total"] == 2
        assert [item["id"] for item in payload["items"]] == ["old"]


@pytest.mark.parametrize("both_duplicates", [False, True])
def test_a_duplicate_observation_can_supply_the_first_consecutive_pair(
    tmp_path: Path, both_duplicates: bool,
) -> None:
    with _client(tmp_path) as (client, session):
        _add_match(session, "old", 100, 1600)
        _add_match(session, "new", 200, 1608)
        _capture(session, ["old"], capture_id="old-only")
        if both_duplicates:
            _capture(session, ["new"], capture_id="new-only")
        session.commit()
        assert _estimates(client)["old"] == (None, "unavailable")
        _capture(
            session, ["new", "old"], capture_id="pair",
            duplicates={"old", "new"} if both_duplicates else {"old"},
        )
        session.commit()
        assert _estimates(client)["old"] == (8, "estimated")


@pytest.mark.parametrize("bad_evidence", ["hash", "raw-link", "account", "legacy", "parser"])
def test_untrusted_or_unrelated_observation_is_not_used_as_evidence(
    tmp_path: Path, bad_evidence: str,
) -> None:
    with _client(tmp_path) as (client, session):
        _add_match(session, "old", 100, 1600)
        _add_match(session, "new", 200, 1608)
        _capture(
            session, ["new", "old"],
            kind="LEGACY_IMPORT" if bad_evidence == "legacy" else "LIVE",
            parser="unknown-parser" if bad_evidence == "parser" else "buckler-battlelog-v3",
            account_id=None if bad_evidence == "account" else 1,
        )
        if bad_evidence == "hash":
            observation = session.get(MatchObservationModel, "observation-capture-0")
            assert observation is not None
            observation.observed_content_sha256 = "b" * 64
        if bad_evidence == "raw-link":
            _capture(session, ["new"], capture_id="unrelated")
            observation = session.get(MatchObservationModel, "observation-capture-0")
            assert observation is not None
            observation.ingestion_id = "unrelated"
        session.commit()
        assert _estimates(client)["old"] == (None, "unavailable")


@pytest.mark.parametrize("result,next_mr", [("WIN", 1592), ("LOSE", 1608), ("DRAW", 1600)])
def test_result_inconsistent_change_is_withheld_without_forcing_the_sign(
    tmp_path: Path, result: str, next_mr: int,
) -> None:
    with _client(tmp_path) as (client, session):
        _add_match(session, "old", 100, 1600, result=result)
        _add_match(session, "new", 200, next_mr)
        _capture(session, ["new", "old"])
        session.commit()
        assert _estimates(client)["old"] == (None, "unavailable")


def test_reset_hidden_matches_are_not_used_as_successors(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, session):
        _add_match(session, "hidden", 100, 1600)
        _add_match(session, "visible", 200, 1608)
        _capture(session, ["visible", "hidden"])
        session.add(SettingsModel(id=1, match_reset_at_ms=150))
        session.commit()
        assert _estimates(client) == {"visible": (None, "pending")}
        payload = client.get("/api/v1/matches/latest").json()
        assert payload["page"]["total"] == 1
