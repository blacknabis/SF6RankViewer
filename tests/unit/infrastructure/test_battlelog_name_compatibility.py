"""Compatibility with immutable matches written before replay-name normalization."""

from collections.abc import Iterator, Mapping
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from sf6viewer.application.ports.unit_of_work import UnitOfWork
from sf6viewer.application.services.raw_collection import (
    CollectedRawMatch,
    CollectionIngestion,
    CollectionPersistResult,
    JsonValue,
    NormalizedMatch,
    RawFirstCollectionService,
)
from sf6viewer.domain.match import content_sha256
from sf6viewer.infrastructure.buckler.battlelog_capture import normalize_battlelog_match
from sf6viewer.infrastructure.db.engine import create_engine_for, create_session_factory
from sf6viewer.infrastructure.db.models import (
    AccountModel,
    Base,
    IngestionRunModel,
    JobModel,
    MatchModel,
    MatchObservationModel,
    ProfileSnapshotModel,
    QuarantineRecordModel,
    RawRecordModel,
)
from sf6viewer.infrastructure.db.repositories import (
    SqlAlchemyIngestionRepository,
    SqlAlchemyMatchRepository,
    SqlAlchemyProfileSnapshotRepository,
    SqlAlchemyQuarantineRepository,
    SqlAlchemyRawRecordRepository,
)
from sf6viewer.infrastructure.storage.app_paths import AppPaths


@pytest.fixture
def database(tmp_path: Path) -> Iterator[tuple[Session, UnitOfWork]]:
    paths = AppPaths.from_root(tmp_path.resolve())
    paths.ensure_directories()
    engine = create_engine_for(paths)
    Base.metadata.create_all(engine)
    with create_session_factory(engine)() as session:
        session.add(
            AccountModel(
                id=1,
                user_code="4285684297",
                display_name="NEW_PROFILE_NAME",
                auth_state="VALID",
                created_at_ms=1,
                updated_at_ms=1,
            )
        )
        session.commit()
        uow = cast(
            UnitOfWork,
            SimpleNamespace(
                matches=SqlAlchemyMatchRepository(session),
                raw_records=SqlAlchemyRawRecordRepository(session),
                quarantines=SqlAlchemyQuarantineRepository(session),
                ingestions=SqlAlchemyIngestionRepository(session),
                profile_snapshots=SqlAlchemyProfileSnapshotRepository(session),
            ),
        )
        yield session, uow
    engine.dispose()


def _payload() -> dict[str, object]:
    return {
        "replay_id": "L3EHPMYNE",
        "uploaded_at": 1_786_029_816,
        "player1_info": {
            "player": {"fighter_id": "REPLAY_NAME", "short_id": 4_285_684_297},
            "playing_character_name": "RYU",
            "master_rating": 1_500,
            "league_point": 25_000,
            "round_results": [1, 1],
        },
        "player2_info": {
            "player": {"fighter_id": "OPPONENT", "short_id": 1_234_567_890},
            "playing_character_name": "KEN",
            "master_rating": 1_600,
            "league_point": 25_001,
            "round_results": [0, 0],
        },
    }


def _ingestion(
    session: Session, suffix: str, *, parser_version: str = "buckler-battlelog-v3"
) -> None:
    session.add(
        JobModel(
            id=f"job-{suffix}",
            type="COLLECT",
            reason="MANUAL",
            state="RUNNING",
            phase="MATCHES",
            requested_at_ms=1,
            started_at_ms=1,
        )
    )
    session.flush()
    session.add(
        IngestionRunModel(
            id=suffix,
            job_id=f"job-{suffix}",
            account_id=1,
            kind="LIVE",
            parser_version=parser_version,
            state="NORMALIZING",
            started_at_ms=1,
        )
    )
    session.flush()


def _normalize(payload: Mapping[str, JsonValue]) -> NormalizedMatch:
    return normalize_battlelog_match(
        payload, account_user_code="4285684297", own_display_name="NEW_PROFILE_NAME"
    )


def _persist(
    session: Session,
    uow: UnitOfWork,
    suffix: str,
    payload: dict[str, object],
    *,
    legacy: bool = False,
    changed_fact: tuple[str, object] | None = None,
) -> CollectionPersistResult:
    _ingestion(
        session,
        suffix,
        parser_version="buckler-battlelog-v2" if legacy else "buckler-battlelog-v3",
    )

    def normalize(raw: Mapping[str, JsonValue]) -> NormalizedMatch:
        normalized = _normalize(raw)
        if legacy:
            # The v2 parser inserted the profile name, even if the replay was older.
            return replace(normalized, facts=replace(normalized.facts, my_name="OLD_PROFILE_NAME"))
        if changed_fact is not None:
            return replace(
                normalized, facts=replace(normalized.facts, **{changed_fact[0]: changed_fact[1]})
            )
        return normalized

    result = RawFirstCollectionService(lambda: uuid4().hex, lambda: 2).persist(
        uow,
        uow.raw_records,
        uow.quarantines,
        CollectionIngestion(suffix, 1),
        [CollectedRawMatch(cast(Mapping[str, JsonValue], payload), 0, 1, "L3EHPMYNE")],
        normalize,
    )
    session.commit()
    return result


def _legacy_record(session: Session, uow: UnitOfWork, *, profile_evidence: bool = True) -> None:
    if profile_evidence:
        _ingestion(session, "profile")
        session.add(
            RawRecordModel(
                id="profile-raw",
                ingestion_id="profile",
                ordinal=0,
                record_type="PROFILE",
                source_key="4285684297",
                payload_json=b"profile evidence",
                payload_sha256="a" * 64,
                fetched_at_ms=1,
                disposition="NORMALIZED",
                disposed_at_ms=1,
            )
        )
        session.flush()
        session.add(
            ProfileSnapshotModel(
                id="profile",
                account_id=1,
                ingestion_id="profile",
                raw_record_id="profile-raw",
                display_name="OLD_PROFILE_NAME",
                observed_at_ms=1,
            )
        )
        session.commit()
    result = _persist(session, uow, "legacy", _payload(), legacy=True)
    assert result.normalized_count == 1


def test_legacy_profile_hash_is_duplicate_with_exact_original_raw_evidence(
    database: tuple[Session, UnitOfWork],
) -> None:
    session, uow = database
    _legacy_record(session, uow)
    before_match = uow.matches.get_by_identity(1, "src:L3EHPMYNE")
    before_raw = session.scalar(
        select(RawRecordModel).where(RawRecordModel.ingestion_id == "legacy")
    )
    assert before_match is not None and before_raw is not None
    original_bytes, original_hash = before_raw.payload_json, before_raw.payload_sha256
    assert before_match.content_sha256 != content_sha256(
        _normalize(cast(Mapping[str, JsonValue], _payload())).facts
    )

    result = _persist(session, uow, "renamed", _payload())
    repeated = _persist(session, uow, "renamed-again", _payload())

    assert result == CollectionPersistResult(1, 0, 1, 0)
    assert repeated == result
    assert uow.matches.get_by_identity(1, "src:L3EHPMYNE") == before_match
    assert (before_raw.payload_json, before_raw.payload_sha256) == (original_bytes, original_hash)
    assert len(session.scalars(select(MatchModel)).all()) == 1
    observations = session.scalars(select(MatchObservationModel)).all()
    assert len(observations) == 3
    assert {item.observed_content_sha256 for item in observations} == {before_match.content_sha256}
    assert session.scalars(select(QuarantineRecordModel)).all() == []


@pytest.mark.parametrize(
    "changed_fact",
    [
        ("account_user_code", "0000000001"),
        ("original_date", "changed date"),
        ("occurred_at_ms", 1),
        ("my_character", "KEN"),
        ("opponent_name", "CHANGED"),
        ("opponent_character", "RYU"),
        ("result", "LOSE"),
        ("my_mr", 1_501),
        ("my_lp", 25_001),
        ("opponent_mr", 1_601),
        ("opponent_lp", 25_002),
    ],
)
def test_legacy_name_compatibility_keeps_every_other_fact_protected(
    database: tuple[Session, UnitOfWork],
    changed_fact: tuple[str, object],
) -> None:
    session, uow = database
    _legacy_record(session, uow)

    result = _persist(session, uow, "changed", _payload(), changed_fact=changed_fact)

    assert result == CollectionPersistResult(1, 0, 0, 1)
    assert session.scalar(select(QuarantineRecordModel.reason_code)) == "DATA.IDENTITY_COLLISION"
    assert len(session.scalars(select(MatchObservationModel)).all()) == 1


@pytest.mark.parametrize("change", ["unknown_field", "rating", "result", "replay_name"])
def test_legacy_name_compatibility_requires_the_same_complete_raw_payload(
    database: tuple[Session, UnitOfWork],
    change: str,
) -> None:
    session, uow = database
    _legacy_record(session, uow)
    changed = deepcopy(_payload())
    player = cast(dict[str, object], changed["player1_info"])
    if change == "unknown_field":
        changed["unknown_upstream_field"] = "changed without affecting normalized fields"
    elif change == "rating":
        player["master_rating"] = 1_501
    elif change == "result":
        player["round_results"] = [0, 0]
        cast(dict[str, object], changed["player2_info"])["round_results"] = [1, 1]
    else:
        cast(dict[str, object], player["player"])["fighter_id"] = "CHANGED_REPLAY_NAME"

    result = _persist(session, uow, "changed-raw", changed)

    assert result == CollectionPersistResult(1, 0, 0, 1)


@pytest.mark.parametrize("corruption", ["compressed_payload", "payload_hash"])
def test_legacy_name_compatibility_rejects_corrupted_original_evidence(
    database: tuple[Session, UnitOfWork],
    corruption: str,
) -> None:
    session, uow = database
    _legacy_record(session, uow)
    original = session.scalar(select(RawRecordModel).where(RawRecordModel.ingestion_id == "legacy"))
    assert original is not None
    if corruption == "compressed_payload":
        original.payload_json = b"corrupt compressed evidence"
    else:
        original.payload_sha256 = "0" * 64
    session.commit()

    result = _persist(session, uow, "corrupt-evidence", _payload())

    assert result == CollectionPersistResult(1, 0, 0, 1)


@pytest.mark.parametrize("missing_evidence", ["profile", "original_observation"])
def test_legacy_name_compatibility_requires_preserved_evidence(
    database: tuple[Session, UnitOfWork],
    missing_evidence: str,
) -> None:
    session, uow = database
    _legacy_record(session, uow, profile_evidence=missing_evidence != "profile")
    if missing_evidence == "original_observation":
        session.execute(delete(MatchObservationModel))
        session.commit()

    result = _persist(session, uow, "missing-evidence", _payload())

    assert result == CollectionPersistResult(1, 0, 0, 1)
