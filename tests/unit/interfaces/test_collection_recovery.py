"""Recover orphaned collection jobs only after owning the desktop server."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from sf6viewer.infrastructure.db.engine import create_engine_for, create_session_factory
from sf6viewer.infrastructure.db.models import Base, IngestionRunModel, JobModel
from sf6viewer.infrastructure.storage.app_paths import AppPaths
from sf6viewer.interfaces.runtime import desktop


@dataclass
class _Database:
    paths: AppPaths
    sessions: sessionmaker[Session]

    def job(self, job_id: str) -> JobModel:
        with self.sessions() as session:
            job = session.get(JobModel, job_id)
            assert job is not None
            return job


@pytest.fixture
def database(tmp_path: Path) -> Iterator[_Database]:
    paths = AppPaths.from_root(tmp_path.resolve())
    paths.ensure_directories()
    engine = create_engine_for(paths)
    Base.metadata.create_all(engine)
    try:
        yield _Database(paths, create_session_factory(engine))
    finally:
        engine.dispose()


def _job(
    job_id: str, state: str, *, phase: str = "MATCHES", job_type: str = "COLLECT",
    requested_at_ms: int = 2000, started_at_ms: int | None = 2100,
    finished_at_ms: int | None = None, error_code: str | None = None,
    diagnostic_id: str | None = None,
) -> JobModel:
    return JobModel(
        id=job_id, type=job_type, reason="SCHEDULED", phase=phase, state=state,
        requested_at_ms=requested_at_ms, started_at_ms=started_at_ms,
        finished_at_ms=finished_at_ms, error_code=error_code, diagnostic_id=diagnostic_id,
    )


def test_orphan_recovery_exposes_interruption_and_keeps_previous_success(
    database: _Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    with database.sessions() as session:
        session.add_all([
            _job("successful", "SUCCEEDED", requested_at_ms=1000,
                 started_at_ms=1100, finished_at_ms=1200),
            _job("orphan", "RUNNING"),
        ])
        session.commit()
    monkeypatch.setattr(desktop, "_now_ms", lambda: 3000)
    bridge = desktop.NativeLoginBridge(database.paths, database.sessions)
    try:
        # Merely constructing another bridge must not interrupt a live instance.
        assert database.job("orphan").state == "RUNNING"
        bridge._recover_interrupted_collections()
        status = bridge.auto_collection_status()
        assert status["last_attempt_at_ms"] == 2000
        assert status["last_success_at_ms"] == 1200
        assert status["last_error_code"] == "INTERNAL.UNEXPECTED"
        job = database.job("orphan")
        assert job.state == "INTERRUPTED"
        assert job.finished_at_ms == 3000
        assert job.error_code == "INTERNAL.UNEXPECTED"
        assert job.diagnostic_id
        events = [
            json.loads(line)
            for path in database.paths.logs_dir.glob("*.jsonl")
            for line in path.read_text(encoding="utf-8").splitlines()
        ]
        assert any(event.get("diagnostic_id") == job.diagnostic_id for event in events)
    finally:
        bridge.close()


def test_recovery_preserves_terminal_jobs_existing_diagnostics_and_is_idempotent(
    database: _Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    terminal_states = ["SUCCEEDED", "SUCCEEDED_WITH_WARNINGS", "FAILED", "CANCELLED", "INTERRUPTED"]
    with database.sessions() as session:
        session.add_all([
            *[_job(state, state, finished_at_ms=2200, diagnostic_id=f"diagnostic-{state}")
              for state in terminal_states],
            _job("committed-before-finally", "SUCCEEDED", finished_at_ms=None),
            _job("queued", "QUEUED", phase="PROFILE", started_at_ms=None),
            _job("clock-ahead", "RUNNING", started_at_ms=4000),
            _job("existing-diagnostic", "RUNNING", error_code="UPSTREAM.TIMEOUT",
                 diagnostic_id="saved-diagnostic", finished_at_ms=2500),
            _job("login", "RUNNING", job_type="LOGIN"),
            _job("different-phase", "RUNNING", phase="OTHER"),
        ])
        session.flush()
        session.add(IngestionRunModel(
            id="completed-ingestion", job_id="committed-before-finally", kind="LIVE",
            parser_version="buckler-battlelog-v3", state="COMPLETED", started_at_ms=2100,
            finished_at_ms=2200, raw_count=0, normalized_count=0, duplicate_count=0,
            quarantine_count=0,
        ))
        session.commit()
    monkeypatch.setattr(desktop, "_now_ms", lambda: 3000)
    bridge = desktop.NativeLoginBridge(database.paths, database.sessions)
    try:
        bridge._recover_interrupted_collections()
        for state in terminal_states:
            job = database.job(state)
            assert job.state == state
            assert job.finished_at_ms == 2200
            assert job.diagnostic_id == f"diagnostic-{state}"
        committed = database.job("committed-before-finally")
        assert committed.state == "SUCCEEDED"
        assert committed.finished_at_ms is None
        with database.sessions() as session:
            ingestion = session.get(IngestionRunModel, "completed-ingestion")
            assert ingestion is not None
            assert ingestion.state == "COMPLETED"
            assert ingestion.finished_at_ms == 2200
            assert ingestion.raw_count == 0
        assert database.job("queued").state == "INTERRUPTED"
        assert database.job("queued").finished_at_ms == 3000
        assert database.job("clock-ahead").finished_at_ms == 4000
        existing = database.job("existing-diagnostic")
        assert existing.state == "INTERRUPTED"
        assert existing.error_code == "UPSTREAM.TIMEOUT"
        assert existing.diagnostic_id == "saved-diagnostic"
        assert existing.finished_at_ms == 2500
        assert database.job("login").state == "RUNNING"
        assert database.job("different-phase").state == "RUNNING"
        with database.sessions() as session:
            before = list(session.execute(select(
                JobModel.id, JobModel.state, JobModel.finished_at_ms,
                JobModel.error_code, JobModel.diagnostic_id,
            )).all())
        log_before = {
            path: path.read_bytes() for path in database.paths.logs_dir.glob("*.jsonl")
        }
        monkeypatch.setattr(desktop, "_now_ms", lambda: 9000)
        bridge._recover_interrupted_collections()
        with database.sessions() as session:
            after = list(session.execute(select(
                JobModel.id, JobModel.state, JobModel.finished_at_ms,
                JobModel.error_code, JobModel.diagnostic_id,
            )).all())
        assert after == before
        assert {path: path.read_bytes() for path in database.paths.logs_dir.glob("*.jsonl")} == (
            log_before
        )
    finally:
        bridge.close()


@pytest.mark.parametrize("failure_point", [None, "bind", "server-start", "ui"])
def test_startup_reconciles_once_after_server_start_and_before_status_scheduler_and_ui(
    database: _Database, monkeypatch: pytest.MonkeyPatch, failure_point: str | None
) -> None:
    with database.sessions() as session:
        session.add(_job("active-job", "RUNNING"))
        session.commit()
    events: list[str] = []

    class Server:
        dashboard_url = "http://127.0.0.1:8000/ui/dashboard.html"

        def __init__(self, app: FastAPI) -> None:
            events.append("server-bind")
            if failure_point == "bind":
                raise OSError("address already in use")

        def start(self) -> None:
            events.append("server-start")
            if failure_point == "server-start":
                raise desktop.DesktopStartupError("server failed before becoming ready")
            assert database.job("active-job").state == "RUNNING"

        def stop(self) -> None:
            events.append("server-stop")

    class Bridge(desktop.NativeLoginBridge):
        def _recover_interrupted_collections(self) -> None:
            events.append("recovery")
            super()._recover_interrupted_collections()

        def auto_collection_status(self) -> dict[str, bool | str | int]:
            events.append("status")
            assert database.job("active-job").state == "INTERRUPTED"
            return super().auto_collection_status()

        def close(self) -> None:
            events.append("bridge-close")
            super().close()

    class Scheduler:
        def __init__(
            self, bridge: desktop.NativeLoginBridge, interval: float, *, automatic_enabled: bool
        ) -> None:
            events.append("scheduler-create")

        def start(self) -> None:
            events.append("scheduler-start")

        def stop(self) -> None:
            events.append("scheduler-stop")

        def set_auto_collection_enabled(self, enabled: bool) -> None:
            pass

    def open_window(url: str, *, js_api: object) -> None:
        events.append("ui")
        if failure_point == "ui":
            raise RuntimeError("window failed to open")

    def show_error_window() -> bool:
        events.append("error-ui")
        return True

    monkeypatch.setattr(
        AppPaths, "from_windows_local_app_data", classmethod(lambda cls: database.paths)
    )
    monkeypatch.setattr(desktop, "run_migrations", lambda path: None)
    monkeypatch.setattr(desktop, "LoopbackServer", Server)
    monkeypatch.setattr(desktop, "NativeLoginBridge", Bridge)
    monkeypatch.setattr(desktop, "AutoCollectionScheduler", Scheduler)
    monkeypatch.setattr(desktop, "_open_desktop_window", open_window)
    monkeypatch.setattr(desktop, "_show_safe_startup_error", show_error_window)

    result = desktop.run_desktop()
    if failure_point in {None, "ui"}:
        assert result == (0 if failure_point is None else 1)
        assert events[:7] == [
            "server-bind", "server-start", "recovery", "status",
            "scheduler-create", "scheduler-start", "ui",
        ]
        assert events.count("recovery") == 1
        assert events.index("scheduler-stop") < events.index("bridge-close")
        assert events.index("bridge-close") < events.index("server-stop")
        if failure_point == "ui":
            assert events.index("error-ui") < events.index("server-stop")
    else:
        assert result == 1
        assert "recovery" not in events
        assert "status" not in events
        assert "scheduler-create" not in events
        assert "ui" not in events
        assert database.job("active-job").state == "RUNNING"
