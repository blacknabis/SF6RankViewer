"""Regression coverage for opt-in automatic ranked-match collection."""

from __future__ import annotations

from pathlib import Path
from threading import Event
from time import sleep
from typing import cast

from sf6viewer.infrastructure.db.engine import create_engine_for, create_session_factory
from sf6viewer.infrastructure.db.models import Base, SettingsModel
from sf6viewer.infrastructure.storage.app_paths import AppPaths
from sf6viewer.interfaces.runtime.desktop import AutoCollectionScheduler, NativeLoginBridge


class _SchedulerBridge:
    """Thread-safe enough test double for the browser-owning bridge boundary."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.match_collected = Event()
        self.dispatcher = None
        self.closed_count = 0

    def set_collection_dispatcher(self, dispatcher: object) -> None:
        self.dispatcher = dispatcher

    def run_scheduled_collection(
        self, key: str, *, collection_reason: str = "MANUAL"
    ) -> dict[str, bool | str | int]:
        self.calls.append((key, collection_reason))
        if key == "MATCHES":
            self.match_collected.set()
            return {"ok": True, "normalized": 0, "duplicates": 0, "quarantined": 0}
        return {"ok": True, "status": "NORMALIZED"}

    def close(self) -> None:
        self.closed_count += 1


def test_auto_collection_setting_defaults_to_off_and_persists(tmp_path: Path) -> None:
    paths = AppPaths.from_root(tmp_path.resolve())
    paths.ensure_directories()
    engine = create_engine_for(paths)
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)

    bridge = NativeLoginBridge(paths, session_factory)
    try:
        assert bridge.auto_collection_status() == {
            "ok": True,
            "enabled": False,
            "interval_seconds": 30,
            "last_attempt_at_ms": 0,
            "last_success_at_ms": 0,
            "last_error_code": "",
        }
        assert bridge.set_auto_collection_enabled(True) == {
            "ok": True,
            "enabled": True,
            "interval_seconds": 30,
            "last_attempt_at_ms": 0,
            "last_success_at_ms": 0,
            "last_error_code": "",
        }
    finally:
        bridge.close()

    session = session_factory()
    try:
        settings = session.get(SettingsModel, 1)
        assert settings is not None
        assert settings.auto_collect_enabled is True
        assert settings.collection_interval_seconds == 30
    finally:
        session.close()

    restored_bridge = NativeLoginBridge(paths, session_factory)
    try:
        assert restored_bridge.auto_collection_status()["enabled"] is True
    finally:
        restored_bridge.close()
        engine.dispose()


def test_scheduler_only_polls_when_enabled_and_keeps_manual_collection_available() -> None:
    bridge = _SchedulerBridge()
    scheduler = AutoCollectionScheduler(
        cast(NativeLoginBridge, bridge), interval_seconds=0.01, automatic_enabled=False
    )
    scheduler.start()
    try:
        sleep(0.03)
        assert bridge.calls == []

        scheduler.set_auto_collection_enabled(True)
        assert bridge.match_collected.wait(1.0)
        assert ("PROFILE", "SCHEDULED") in bridge.calls
        assert ("MATCHES", "SCHEDULED") in bridge.calls

        scheduler.set_auto_collection_enabled(False)
        scheduled_call_count = len(bridge.calls)
        sleep(0.03)
        assert len(bridge.calls) == scheduled_call_count

        assert scheduler.request("MATCHES")["ok"] is True
        assert bridge.calls[-1] == ("MATCHES", "MANUAL")
    finally:
        scheduler.stop()
