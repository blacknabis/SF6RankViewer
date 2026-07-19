"""Regression coverage for stale review-backlog cleanup."""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from sf6viewer.infrastructure.db.engine import create_engine_for, create_session_factory
from sf6viewer.infrastructure.db.models import (
    Base,
    IngestionRunModel,
    JobModel,
    QuarantineRecordModel,
    RawRecordModel,
)
from sf6viewer.infrastructure.storage.app_paths import AppPaths
from sf6viewer.interfaces.runtime.desktop import NativeLoginBridge


def _add_quarantine(
    session: Session,
    *,
    suffix: str,
    kind: str,
    parser_version: str,
    reason_code: str,
) -> None:
    session.add(
        JobModel(
            id=f"job-{suffix}",
            type="COLLECT",
            reason="MANUAL",
            state="SUCCEEDED_WITH_WARNINGS",
            phase="MATCHES",
            requested_at_ms=1,
            started_at_ms=1,
            finished_at_ms=2,
            progress_current=1,
            progress_total=1,
            error_code=None,
            diagnostic_id=None,
            summary_json=None,
        )
    )
    session.flush()
    session.add(
        IngestionRunModel(
            id=f"ingestion-{suffix}",
            job_id=f"job-{suffix}",
            account_id=None,
            kind=kind,
            parser_version=parser_version,
            state="COMPLETED_WITH_WARNINGS",
            started_at_ms=1,
            finished_at_ms=2,
            raw_count=1,
            normalized_count=0,
            duplicate_count=0,
            quarantine_count=1,
            error_code=None,
            diagnostic_id=None,
        )
    )
    session.flush()
    session.add(
        RawRecordModel(
            id=f"raw-{suffix}",
            ingestion_id=f"ingestion-{suffix}",
            ordinal=0,
            record_type="MATCH",
            source_key=None,
            payload_json=b"{}",
            payload_sha256="a" * 64,
            fetched_at_ms=1,
            disposition="QUARANTINED",
            disposed_at_ms=2,
        )
    )
    session.flush()
    session.add(
        QuarantineRecordModel(
            id=f"quarantine-{suffix}",
            raw_record_id=f"raw-{suffix}",
            account_id=None,
            reason_code=reason_code,
            field_errors_json=None,
            status="OPEN",
            created_at_ms=2,
            resolved_at_ms=None,
            resolution_match_id=None,
        )
    )


def test_cleanup_ignores_legacy_and_stale_parser_failures_only(tmp_path: Path) -> None:
    paths = AppPaths.from_root(tmp_path.resolve())
    paths.ensure_directories()
    engine = create_engine_for(paths)
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    session = session_factory()
    try:
        _add_quarantine(
            session,
            suffix="legacy-import",
            kind="LEGACY_IMPORT",
            parser_version="legacy-v1",
            reason_code="UPSTREAM.CONTRACT_CHANGED",
        )
        _add_quarantine(
            session,
            suffix="stale-parser",
            kind="LIVE",
            parser_version="buckler-battlelog-v1",
            reason_code="DATA.IDENTITY_GROUP_INCOMPLETE",
        )
        _add_quarantine(
            session,
            suffix="current-parser",
            kind="LIVE",
            parser_version="buckler-battlelog-v2",
            reason_code="DATA.IDENTITY_GROUP_INCOMPLETE",
        )
        _add_quarantine(
            session,
            suffix="different-failure",
            kind="LIVE",
            parser_version="buckler-battlelog-v1",
            reason_code="UPSTREAM.CONTRACT_CHANGED",
        )
        session.commit()
    finally:
        session.close()

    bridge = NativeLoginBridge(paths, session_factory)
    try:
        result = bridge.ignore_legacy_quarantines()
    finally:
        bridge.close()

    assert result == {"ok": True, "ignored": 2}
    session = session_factory()
    try:
        statuses = dict(
            session.execute(
                select(QuarantineRecordModel.id, QuarantineRecordModel.status)
            ).all()
        )
    finally:
        session.close()
        engine.dispose()
    assert statuses == {
        "quarantine-legacy-import": "IGNORED",
        "quarantine-stale-parser": "IGNORED",
        "quarantine-current-parser": "OPEN",
        "quarantine-different-failure": "OPEN",
    }
