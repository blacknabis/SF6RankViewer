"""Durable collection outcomes and first-use scheduler regressions."""

from __future__ import annotations

import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from itertools import count
from pathlib import Path
from threading import Event, current_thread

import pytest
import ulid
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from ulid.providers.default import Provider

from sf6viewer.application.services.profile_collection import CollectedRawProfile
from sf6viewer.application.services.raw_collection import RawFirstCollectionService
from sf6viewer.domain.errors import error_from_code
from sf6viewer.domain.value_objects import UserCode
from sf6viewer.infrastructure.auth.dpapi_vault import AuthSession
from sf6viewer.infrastructure.buckler.battlelog_capture import BucklerBattlelogCapture
from sf6viewer.infrastructure.buckler.profile_capture import BucklerProfileCapture
from sf6viewer.infrastructure.db.engine import create_engine_for, create_session_factory
from sf6viewer.infrastructure.db.models import Base, IngestionRunModel, JobModel
from sf6viewer.infrastructure.logging import JsonlLogSink
from sf6viewer.infrastructure.storage.app_paths import AppPaths
from sf6viewer.interfaces.runtime import desktop


@dataclass
class _Runtime:
    paths: AppPaths
    sessions: sessionmaker[Session]
    bridge: desktop.NativeLoginBridge
    calls: list[tuple[str, str]] = field(default_factory=list)

    def profile(self, auth: AuthSession) -> CollectedRawProfile:
        self.calls.append(("PROFILE", current_thread().name))
        return CollectedRawProfile(
            raw_payload={
                "fighter_banner_info": {
                    "personal_info": {"fighter_id": "Player"},
                    "favorite_character_alpha": "GUILE",
                    "favorite_character_league_info": {
                        "league_rank_info": {"league_rank_name": "MASTER"},
                        "master_rating": 1500,
                    },
                }
            },
            fetched_at_ms=desktop._now_ms(),
            source_key=f"profile:{auth.user_code.value}",
        )

    def jobs(self) -> list[JobModel]:
        with self.sessions() as session:
            return list(session.scalars(select(JobModel).order_by(JobModel.id)))


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[_Runtime]:
    paths = AppPaths.from_root(tmp_path.resolve())
    paths.ensure_directories()
    engine = create_engine_for(paths)
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    bridge = desktop.NativeLoginBridge(paths, sessions)
    auth = AuthSession(UserCode.parse("1234567890"), b'{"cookie":"auth-secret"}')
    bridge._mark_account_valid(auth.user_code)
    runtime = _Runtime(paths, sessions, bridge)
    monkeypatch.setattr(bridge, "_load_active_session", lambda: auth)
    monkeypatch.setattr(
        BucklerProfileCapture, "capture", lambda self, auth: runtime.profile(auth)
    )

    def capture_matches(self: object, auth: AuthSession) -> list[object]:
        runtime.calls.append(("MATCHES", current_thread().name))
        return []

    monkeypatch.setattr(BucklerBattlelogCapture, "capture", capture_matches)
    try:
        yield runtime
    finally:
        bridge.close()
        engine.dispose()


@pytest.mark.parametrize("phase", ["PROFILE", "MATCHES"])
def test_capture_failure_is_durable_and_private(
    runtime: _Runtime, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    if phase == "MATCHES":
        assert runtime.bridge.collect_profile()["ok"] is True
    capture_type = (
        BucklerProfileCapture if phase == "PROFILE" else BucklerBattlelogCapture
    )

    def fail(self: object, auth: AuthSession) -> None:
        raise RuntimeError("cookie=auth-secret https://private.example/profile/raw-secret")

    monkeypatch.setattr(capture_type, "capture", fail)
    result = runtime.bridge.run_scheduled_collection(phase, collection_reason="SCHEDULED")

    assert result == {"ok": False, "code": "INTERNAL.UNEXPECTED"}
    job = runtime.jobs()[-1]
    assert job.phase == phase
    assert job.reason == "SCHEDULED"
    assert job.state == "FAILED"
    assert job.error_code == "INTERNAL.UNEXPECTED"
    assert job.started_at_ms is not None
    assert job.finished_at_ms is not None
    assert job.requested_at_ms <= job.started_at_ms <= job.finished_at_ms
    assert job.diagnostic_id
    logs = list(runtime.paths.logs_dir.glob("*.jsonl"))
    assert logs
    text = "\n".join(path.read_text(encoding="utf-8") for path in logs)
    assert "auth-secret" not in text
    assert "raw-secret" not in text
    assert "https://" not in text
    events = [json.loads(line) for line in text.splitlines()]
    failure = next(event for event in events if event.get("diagnostic_id") == job.diagnostic_id)
    assert failure["error_code"] == "INTERNAL.UNEXPECTED"
    assert failure["job_id"] == job.id


def test_status_survives_restart_and_retains_match_success_after_failure(
    runtime: _Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(desktop, "_now_ms", lambda: 1000)
    assert runtime.bridge.collect_profile()["ok"] is True
    assert runtime.bridge.auto_collection_status()["last_success_at_ms"] == 0
    assert runtime.bridge.collect_matches()["ok"] is True
    successful = runtime.bridge.auto_collection_status()
    assert successful["last_attempt_at_ms"] == 1000
    assert successful["last_success_at_ms"] == 1000
    assert successful["last_error_code"] == ""
    original_capture = BucklerBattlelogCapture.capture

    def fail(self: object, auth: AuthSession) -> None:
        raise error_from_code("UPSTREAM.UNAVAILABLE")

    monkeypatch.setattr(desktop, "_now_ms", lambda: 2000)
    monkeypatch.setattr(BucklerBattlelogCapture, "capture", fail)
    assert runtime.bridge.collect_matches() == {"ok": False, "code": "UPSTREAM.UNAVAILABLE"}
    restarted = desktop.NativeLoginBridge(runtime.paths, runtime.sessions)
    try:
        status = restarted.auto_collection_status()
        assert status["last_attempt_at_ms"] == 2000
        assert status["last_success_at_ms"] == 1000
        assert status["last_error_code"] == "UPSTREAM.UNAVAILABLE"
    finally:
        restarted.close()
    toggled = runtime.bridge.set_auto_collection_enabled(True)
    assert toggled["last_attempt_at_ms"] == 2000
    assert toggled["last_success_at_ms"] == 1000
    assert toggled["last_error_code"] == "UPSTREAM.UNAVAILABLE"

    monkeypatch.setattr(desktop, "_now_ms", lambda: 3000)
    assert runtime.bridge.collect_profile()["ok"] is True
    assert runtime.bridge.auto_collection_status()["last_error_code"] == "UPSTREAM.UNAVAILABLE"
    monkeypatch.setattr(BucklerBattlelogCapture, "capture", original_capture)
    assert runtime.bridge.collect_matches()["ok"] is True
    assert runtime.bridge.auto_collection_status()["last_error_code"] == ""
    assert runtime.bridge.auto_collection_status()["last_success_at_ms"] == 3000


def test_first_manual_matches_collects_profile_on_scheduler_thread(runtime: _Runtime) -> None:
    scheduler = desktop.AutoCollectionScheduler(runtime.bridge, 30, automatic_enabled=False)
    scheduler.start()
    try:
        assert runtime.bridge.collect_matches() == {
            "ok": True, "normalized": 0, "duplicates": 0, "quarantined": 0
        }
        assert runtime.calls == [
            ("PROFILE", "sf6viewer-auto-collection"),
            ("MATCHES", "sf6viewer-auto-collection"),
        ]
        assert runtime.bridge.collect_matches()["ok"] is True
        assert [phase for phase, _ in runtime.calls] == ["PROFILE", "MATCHES", "MATCHES"]
        assert all(job.state == "SUCCEEDED" for job in runtime.jobs())
    finally:
        scheduler.stop()


def test_same_millisecond_failure_and_recovery_keep_execution_order(
    runtime: _Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    timestamp = ulid.new().timestamp().bytes
    decreasing_randomness = count(100_000, -1)
    monkeypatch.setattr(Provider, "timestamp", lambda self: timestamp)
    monkeypatch.setattr(
        Provider, "randomness",
        lambda self, timestamp: next(decreasing_randomness).to_bytes(10, "big"),
    )
    monkeypatch.setattr(desktop, "_now_ms", lambda: 1000)
    assert runtime.bridge.collect_profile()["ok"] is True
    assert runtime.bridge.collect_matches()["ok"] is True
    original_capture = BucklerBattlelogCapture.capture

    def fail(self: object, auth: AuthSession) -> None:
        raise error_from_code("UPSTREAM.UNAVAILABLE")

    monkeypatch.setattr(BucklerBattlelogCapture, "capture", fail)
    assert runtime.bridge.collect_matches()["ok"] is False
    assert runtime.bridge.auto_collection_status()["last_error_code"] == "UPSTREAM.UNAVAILABLE"
    monkeypatch.setattr(BucklerBattlelogCapture, "capture", original_capture)
    assert runtime.bridge.collect_matches()["ok"] is True
    assert runtime.bridge.auto_collection_status()["last_error_code"] == ""


def test_first_manual_profile_failure_stops_before_battlelog(
    runtime: _Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(self: object, auth: AuthSession) -> None:
        raise error_from_code("UPSTREAM.UNAVAILABLE")

    monkeypatch.setattr(BucklerProfileCapture, "capture", fail)
    assert runtime.bridge.collect_matches() == {"ok": False, "code": "UPSTREAM.UNAVAILABLE"}
    assert runtime.calls == []
    assert all(job.state == "FAILED" for job in runtime.jobs())


def test_running_capture_persists_attempt_without_blocking_status_or_stop(
    runtime: _Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert runtime.bridge.collect_profile()["ok"] is True
    capture_started = Event()
    release_capture = Event()

    def capture(self: object, auth: AuthSession) -> list[object]:
        capture_started.set()
        assert release_capture.wait(3)
        return []

    monkeypatch.setattr(BucklerBattlelogCapture, "capture", capture)
    runtime.bridge.set_auto_collection_enabled(True)
    with ThreadPoolExecutor(max_workers=2) as executor:
        collection = executor.submit(runtime.bridge.collect_matches)
        try:
            assert capture_started.wait(1)
            job = runtime.jobs()[-1]
            assert job.state == "RUNNING"
            status = executor.submit(runtime.bridge.auto_collection_status).result(timeout=1)
            assert status["last_attempt_at_ms"] == job.requested_at_ms
            stopped = executor.submit(
                runtime.bridge.set_auto_collection_enabled, False
            ).result(timeout=1)
            assert stopped["enabled"] is False
        finally:
            release_capture.set()
        assert collection.result(timeout=2)["ok"] is True


def test_ingestion_rollback_leaves_failed_job_without_partial_data(
    runtime: _Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert runtime.bridge.collect_profile()["ok"] is True
    original_persist = RawFirstCollectionService.persist

    def fail_after_persist(
        self: RawFirstCollectionService, *args: object, **kwargs: object
    ) -> None:
        original_persist(self, *args, **kwargs)  # type: ignore[arg-type]
        raise RuntimeError("cannot commit this ingestion")

    monkeypatch.setattr(RawFirstCollectionService, "persist", fail_after_persist)
    assert runtime.bridge.collect_matches() == {"ok": False, "code": "INTERNAL.UNEXPECTED"}
    failed = runtime.jobs()[-1]
    assert failed.state == "FAILED"
    with runtime.sessions() as session:
        assert session.scalar(
            select(func.count()).select_from(IngestionRunModel)
            .where(IngestionRunModel.job_id == failed.id)
        ) == 0


def test_log_failure_does_not_change_collection_outcome(
    runtime: _Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert runtime.bridge.collect_profile()["ok"] is True

    def unavailable_log(self: JsonlLogSink, event: object) -> None:
        raise OSError("log disk unavailable")

    monkeypatch.setattr(JsonlLogSink, "write", unavailable_log)
    assert runtime.bridge.collect_matches()["ok"] is True

    def unavailable_capture(self: object, auth: AuthSession) -> None:
        raise error_from_code("UPSTREAM.UNAVAILABLE")

    monkeypatch.setattr(BucklerBattlelogCapture, "capture", unavailable_capture)
    assert runtime.bridge.collect_matches() == {"ok": False, "code": "UPSTREAM.UNAVAILABLE"}
    assert runtime.jobs()[-1].state == "FAILED"
