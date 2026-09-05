"""Loopback-only Uvicorn and pywebview process lifecycle for SF6Viewer.

The browser window and API intentionally share one ``127.0.0.1`` origin.  No
authentication cookies are created by this host, and the mounted API exposes
only its already-sanitized read projections: raw evidence and browser auth
material never cross this boundary.
"""

from __future__ import annotations

import re
import socket
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Lock, RLock, Thread
from time import monotonic, time

import ulid
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from playwright.sync_api import Page
from sqlalchemy import Engine, and_, func, or_, select, update
from sqlalchemy.orm import Session

from sf6viewer import __version__
from sf6viewer.application.ports.repositories import IngestionRecord, JobRecord
from sf6viewer.application.services.collection_coordinator import (
    CanonicalRequestKey,
    CollectionAdmission,
    CollectionCoordinator,
    CollectionRequest,
    CollectionRequestKind,
)
from sf6viewer.application.services.login_service import LoginService
from sf6viewer.application.services.profile_collection import RawFirstProfileCollectionService
from sf6viewer.application.services.raw_collection import (
    CollectionIngestion,
    RawFirstCollectionService,
)
from sf6viewer.domain.errors import DomainError, error_from_code
from sf6viewer.domain.job import JobState
from sf6viewer.domain.value_objects import UserCode
from sf6viewer.infrastructure.auth.dpapi_vault import AuthSession, DpapiAuthVault
from sf6viewer.infrastructure.buckler.battlelog_capture import (
    BucklerBattlelogCapture,
    normalize_battlelog_match,
)
from sf6viewer.infrastructure.buckler.browser_capture import PersistentBucklerBrowser
from sf6viewer.infrastructure.buckler.playwright_auth import PlaywrightAuthBrowser
from sf6viewer.infrastructure.buckler.profile_capture import (
    BucklerProfileCapture,
    normalize_profile,
)
from sf6viewer.infrastructure.db.engine import (
    create_engine_for,
    create_session_factory,
    run_migrations,
)
from sf6viewer.infrastructure.db.models.accounts import AccountModel
from sf6viewer.infrastructure.db.models.ingestion_runs import IngestionRunModel
from sf6viewer.infrastructure.db.models.jobs import JobModel
from sf6viewer.infrastructure.db.models.matches import MatchModel
from sf6viewer.infrastructure.db.models.profile_snapshots import ProfileSnapshotModel
from sf6viewer.infrastructure.db.models.quarantine_records import QuarantineRecordModel
from sf6viewer.infrastructure.db.models.raw_records import RawRecordModel
from sf6viewer.infrastructure.db.models.settings import SettingsModel
from sf6viewer.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWorkFactory
from sf6viewer.infrastructure.logging import JsonlLogSink
from sf6viewer.infrastructure.storage.app_paths import AppPaths
from sf6viewer.interfaces.api import create_read_api

LOOPBACK_HOST = "127.0.0.1"
LOOPBACK_PORT = 8000
SERVER_START_TIMEOUT_SECONDS = 10.0
SERVER_STOP_TIMEOUT_SECONDS = 10.0
BUCKLER_KOREAN_URL = "https://www.streetfighter.com/6/buckler/ko-kr"
AUTHENTICATED_PROFILE_TIMEOUT_MS = 120_000
AUTO_COLLECTION_INTERVAL_SECONDS = 30.0
MANUAL_COLLECTION_TIMEOUT_SECONDS = 120.0
BUCKLER_BATTLELOG_PARSER_VERSION = "buckler-battlelog-v3"
STALE_BATTLELOG_PARSER_VERSION = "buckler-battlelog-v1"
_PROFILE_USER_CODE_PATTERN = re.compile(r"(?:^|/)profile/([0-9]{10})(?:/|$|[?#])")

type _AutoCollectionRequest = tuple[str, Event, dict[str, bool | str | int]]


class _AutoCollectionStateChanged:
    """Wake the scheduler after a persisted automatic-collection state change."""


_AUTO_COLLECTION_STATE_CHANGED = _AutoCollectionStateChanged()


class DesktopStartupError(RuntimeError):
    """Raised when the local desktop host cannot become ready safely."""


class NativeLoginBridge:
    """Expose only a minimal, safe native sign-in operation to pywebview."""

    def __init__(self, paths: AppPaths, session_factory: Callable[[], Session]) -> None:
        self._paths = paths
        self._session_factory = session_factory
        self._log_sink = JsonlLogSink(paths.logs_dir)
        self._lock = RLock()
        self._uow_factory = SqlAlchemyUnitOfWorkFactory(
            session_factory,
            self._lock,
            _DiscardingEventPublisher(),
            _DiscardingWarningSink(),
            _new_id,
        )
        self._request_lock = Lock()
        self._settings_lock = Lock()
        self._request_handlers: dict[str, Callable[[str], dict[str, bool | str | int]]] = {}
        self._collection_results: dict[str, dict[str, bool | str | int]] = {}
        self._coordinator = CollectionCoordinator(self._run_collection_request)
        self._capture_browser = PersistentBucklerBrowser()
        self._collection_dispatcher: Callable[[str], dict[str, bool | str | int]] | None = None
        self._auto_collection_controller: Callable[[bool], None] | None = None

    def login(self) -> dict[str, bool | str]:
        """Discover and authenticate the account without exposing browser state."""
        try:
            with self._lock:
                expected = self._projected_account_user_code()
                session = self._login(expected)
                self._mark_account_valid(session.user_code)
                self._capture_browser.request_reset()
            return {"ok": True, "user_code": session.user_code.value}
        except DomainError as error:
            return {"ok": False, "code": error.code}
        except Exception:
            # The JavaScript caller must never receive exceptions, URLs, or
            # browser/authentication material.  It recognizes this catalog code.
            return {"ok": False, "code": "INTERNAL.UNEXPECTED"}

    def auth_status(self) -> dict[str, bool | str]:
        """Return only the projected account code and safe saved-session status."""
        projected_user_code: UserCode | None = None
        try:
            with self._lock:
                session = self._session_factory()
                try:
                    account = session.get(AccountModel, 1)
                    if account is None:
                        return {"ok": True, "authenticated": False}
                    projected_user_code = UserCode.parse(account.user_code)
                    auth_state = account.auth_state
                finally:
                    session.close()

                result: dict[str, bool | str] = {
                    "ok": True,
                    "authenticated": False,
                    "user_code": projected_user_code.value,
                }
                if auth_state != "VALID":
                    return result
                try:
                    saved_session = DpapiAuthVault(self._paths).load()
                    if saved_session is None or saved_session.user_code != projected_user_code:
                        return result
                    return {
                        "ok": True,
                        "authenticated": True,
                        "user_code": projected_user_code.value,
                    }
                except Exception:
                    return {
                        **result,
                        "code": "AUTH.SESSION_UNAVAILABLE",
                    }
        except Exception:
            # Auth status is a read-only UI probe.  Keep vault/database errors
            # private and make the caller fail closed without browser activity.
            result = {
                "ok": True,
                "authenticated": False,
                "code": "AUTH.SESSION_UNAVAILABLE",
            }
            if projected_user_code is not None:
                result["user_code"] = projected_user_code.value
            return result

    def _login(self, expected: UserCode | None) -> AuthSession:
        """Run the interactive browser and keep its session local to DPAPI."""
        service = LoginService(
            auth_browser=PlaywrightAuthBrowser(
                target_url=BUCKLER_KOREAN_URL,
                profile_dir=self._paths.login_browser_profile_dir,
                wait_for_authenticated=_wait_for_authenticated_profile,
                extract_user_code=_extract_profile_user_code,
            ),
            vault=DpapiAuthVault(self._paths),
        )
        return service.login(expected)

    def _projected_account_user_code(self) -> UserCode | None:
        """Return the existing single-account code, if the app already owns one."""
        session = self._session_factory()
        try:
            account = session.get(AccountModel, 1)
            return None if account is None else UserCode.parse(account.user_code)
        finally:
            session.close()

    def _mark_account_valid(self, user_code: UserCode) -> None:
        """Create or refresh the account projection only after DPAPI save succeeds."""
        session = self._session_factory()
        now_ms = int(time() * 1_000)
        try:
            account = session.get(AccountModel, 1)
            if account is None:
                session.add(
                    AccountModel(
                        id=1,
                        user_code=user_code.value,
                        display_name=None,
                        main_character=None,
                        rank_name=None,
                        current_mr=None,
                        current_lp=None,
                        auth_state="VALID",
                        created_at_ms=now_ms,
                        updated_at_ms=now_ms,
                    )
                )
            elif account.user_code == user_code.value:
                account.auth_state = "VALID"
                account.updated_at_ms = now_ms
            else:
                raise error_from_code("SESSION.ACCOUNT_MISMATCH")
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def collect_profile(self) -> dict[str, bool | str | int]:
        """Admit one profile capture into the single collection queue."""
        return self._request_collection("PROFILE")

    def auto_collection_status(self) -> dict[str, bool | str | int]:
        """Return the durable preference and safe collection outcomes."""
        try:
            enabled, interval_seconds = self._auto_collection_settings()
            return {
                "ok": True,
                "enabled": enabled,
                "interval_seconds": interval_seconds,
                **self._collection_outcomes(),
            }
        except Exception:
            return {"ok": False, "code": "INTERNAL.UNEXPECTED"}

    def set_auto_collection_enabled(self, enabled: bool) -> dict[str, bool | str | int]:
        """Persist an opt-in setting, then wake the scheduler in the same process.

        The scheduler receives the update only after SQLite commits.  If the
        app exits immediately afterward, the next startup still restores the
        user's choice rather than running with an in-memory-only state.
        """
        if not isinstance(enabled, bool):
            return {"ok": False, "code": "INTERNAL.UNEXPECTED"}

        session = self._session_factory()
        controller: Callable[[bool], None] | None = None
        interval_seconds = int(AUTO_COLLECTION_INTERVAL_SECONDS)
        try:
            # Do not take ``self._lock`` here: a live Playwright capture holds
            # it for its whole request.  Stopping automatic collection must
            # persist and wake the scheduler immediately instead of making the
            # user wait for a slow Buckler response.
            with self._settings_lock:
                settings = session.get(SettingsModel, 1)
                now_ms = _now_ms()
                if settings is None:
                    settings = SettingsModel(
                        id=1,
                        auto_collect_enabled=enabled,
                        collection_interval_seconds=interval_seconds,
                        collection_limit=20,
                        updated_at_ms=now_ms,
                    )
                    session.add(settings)
                else:
                    settings.auto_collect_enabled = enabled
                    settings.updated_at_ms = now_ms
                    interval_seconds = int(settings.collection_interval_seconds)
                session.commit()
                controller = self._auto_collection_controller
            if controller is not None:
                controller(enabled)
            return {
                "ok": True,
                "enabled": enabled,
                "interval_seconds": interval_seconds,
                **self._collection_outcomes(),
            }
        except Exception:
            session.rollback()
            return {"ok": False, "code": "INTERNAL.UNEXPECTED"}
        finally:
            session.close()

    def set_auto_collection_controller(self, controller: Callable[[bool], None]) -> None:
        """Attach the scheduler callback after it has restored durable state."""
        self._auto_collection_controller = controller

    def viewer_preferences(self) -> dict[str, bool | str | int]:
        """Return the durable viewer display preferences using safe defaults."""
        session: Session | None = None
        try:
            session = self._session_factory()
            with self._settings_lock:
                settings = session.get(SettingsModel, 1)
                if settings is None:
                    delta_mode = "session"
                    chart_limit = 50
                else:
                    delta_mode = settings.viewer_delta_mode
                    chart_limit = int(settings.viewer_chart_limit)
            return {
                "ok": True,
                "delta_mode": delta_mode,
                "chart_limit": chart_limit,
            }
        except Exception:
            if session is not None:
                with suppress(Exception):
                    session.rollback()
            return {"ok": False, "code": "INTERNAL.UNEXPECTED"}
        finally:
            if session is not None:
                with suppress(Exception):
                    session.close()

    def set_viewer_preferences(
        self, delta_mode: str, chart_limit: int
    ) -> dict[str, bool | str | int]:
        """Validate and persist the viewer's delta mode and chart range."""
        if type(delta_mode) is not str or delta_mode not in {"session", "range"}:
            return {"ok": False, "code": "INTERNAL.UNEXPECTED"}
        if type(chart_limit) is not int or chart_limit not in {20, 50, 100}:
            return {"ok": False, "code": "INTERNAL.UNEXPECTED"}

        session: Session | None = None
        try:
            session = self._session_factory()
            with self._settings_lock:
                settings = session.get(SettingsModel, 1)
                now_ms = _now_ms()
                if settings is None:
                    settings = SettingsModel(
                        id=1,
                        viewer_delta_mode=delta_mode,
                        viewer_chart_limit=chart_limit,
                        updated_at_ms=now_ms,
                    )
                    session.add(settings)
                else:
                    settings.viewer_delta_mode = delta_mode
                    settings.viewer_chart_limit = chart_limit
                    settings.updated_at_ms = now_ms
                session.commit()
            return {
                "ok": True,
                "delta_mode": delta_mode,
                "chart_limit": chart_limit,
            }
        except Exception:
            if session is not None:
                with suppress(Exception):
                    session.rollback()
            return {"ok": False, "code": "INTERNAL.UNEXPECTED"}
        finally:
            if session is not None:
                with suppress(Exception):
                    session.close()

    def _auto_collection_settings(self) -> tuple[bool, int]:
        """Load a fail-closed preference for a missing singleton settings row."""
        session = self._session_factory()
        try:
            with self._settings_lock:
                settings = session.get(SettingsModel, 1)
                if settings is None:
                    return False, int(AUTO_COLLECTION_INTERVAL_SECONDS)
                return (
                    bool(settings.auto_collect_enabled),
                    int(settings.collection_interval_seconds),
                )
        finally:
            session.close()

    def _collect_profile(
        self, job_id: str, *, collection_reason: str
    ) -> dict[str, bool | str | int]:
        """Capture, preserve, and project the authenticated profile once."""
        try:
            with self._lock, self._collection_job(job_id, "PROFILE", collection_reason):
                session = self._load_active_session()
                captured = BucklerProfileCapture(_now_ms, self._capture_browser).capture(session)
                ingestion_id = _new_id()
                with self._uow_factory.write() as uow:
                    uow.ingestions.add(
                        IngestionRecord(
                            id=ingestion_id, job_id=job_id, account_id=1, kind="LIVE",
                            parser_version="buckler-profile-v1", state="NORMALIZING",
                            started_at_ms=captured.fetched_at_ms, finished_at_ms=None,
                            raw_count=0, normalized_count=0, duplicate_count=0,
                            quarantine_count=0, error_code=None, diagnostic_id=None,
                        )
                    )
                    normalized = RawFirstProfileCollectionService(_new_id, _now_ms).persist(
                        uow,
                        ingestion_id=ingestion_id,
                        account_id=1,
                        captured=captured,
                        normalizer=normalize_profile,
                    )
                    uow.jobs.set_state(
                        job_id,
                        JobState.SUCCEEDED if normalized else JobState.SUCCEEDED_WITH_WARNINGS,
                    )
                    uow.commit()
            return {"ok": True, "status": "NORMALIZED" if normalized else "QUARANTINED"}
        except DomainError as error:
            return {"ok": False, "code": error.code}
        except Exception:
            return {"ok": False, "code": "INTERNAL.UNEXPECTED"}

    def collect_matches(self) -> dict[str, bool | str | int]:
        """Admit one ranked-battlelog capture into the single collection queue."""
        return self._request_collection("MATCHES")

    def set_collection_dispatcher(
        self, dispatcher: Callable[[str], dict[str, bool | str | int]]
    ) -> None:
        """Route browser work through the one thread that owns Playwright."""
        self._collection_dispatcher = dispatcher

    def run_scheduled_collection(
        self, key: str, *, collection_reason: str = "MANUAL"
    ) -> dict[str, bool | str | int]:
        """Run one collection request from the Playwright-owning scheduler thread."""
        if key == "PROFILE":
            return self._admit_collection(
                "PROFILE",
                lambda job_id: self._collect_profile(job_id, collection_reason=collection_reason),
            )
        if key == "MATCHES":
            return self._admit_collection(
                "MATCHES",
                lambda job_id: self._collect_matches(job_id, collection_reason=collection_reason),
            )
        return {"ok": False, "code": "INTERNAL.UNEXPECTED"}

    def _request_collection(self, key: str) -> dict[str, bool | str | int]:
        dispatcher = self._collection_dispatcher
        if dispatcher is not None:
            return dispatcher(key)
        return self.run_scheduled_collection(key)

    def clear_matches(self) -> dict[str, bool | int | str]:
        """Move the visible-history baseline without mutating immutable match evidence."""
        session = self._session_factory()
        try:
            with self._lock, self._settings_lock:
                settings = session.get(SettingsModel, 1)
                previous_reset_at_ms = (
                    settings.match_reset_at_ms
                    if settings is not None and settings.match_reset_at_ms is not None
                    else -1
                )
                visible_count = int(
                    session.scalar(
                        select(func.count())
                        .select_from(MatchModel)
                        .where(
                            MatchModel.account_id == 1,
                            MatchModel.occurred_at_ms > previous_reset_at_ms,
                        )
                    )
                    or 0
                )
                reset_at_ms = max(_now_ms(), previous_reset_at_ms + 1)
                if settings is None:
                    session.add(
                        SettingsModel(
                            id=1,
                            auto_collect_enabled=False,
                            collection_interval_seconds=int(AUTO_COLLECTION_INTERVAL_SECONDS),
                            collection_limit=20,
                            match_reset_at_ms=reset_at_ms,
                            updated_at_ms=reset_at_ms,
                        )
                    )
                else:
                    settings.match_reset_at_ms = reset_at_ms
                    settings.updated_at_ms = reset_at_ms
                session.commit()
            return {"ok": True, "cleared": visible_count}
        except Exception:
            session.rollback()
            return {"ok": False, "code": "INTERNAL.UNEXPECTED"}
        finally:
            session.close()

    def ignore_legacy_quarantines(self) -> dict[str, bool | int | str]:
        """Hide stale migration/parser quarantines while preserving their evidence."""
        session = self._session_factory()
        try:
            with self._lock:
                legacy_raw_ids = (
                    select(RawRecordModel.id)
                    .join(
                        IngestionRunModel,
                        IngestionRunModel.id == RawRecordModel.ingestion_id,
                    )
                    .where(IngestionRunModel.kind == "LEGACY_IMPORT")
                )
                stale_parser_raw_ids = (
                    select(RawRecordModel.id)
                    .join(
                        IngestionRunModel,
                        IngestionRunModel.id == RawRecordModel.ingestion_id,
                    )
                    .where(
                        IngestionRunModel.parser_version == STALE_BATTLELOG_PARSER_VERSION,
                        RawRecordModel.record_type == "MATCH",
                    )
                )
                ignored = session.execute(
                    update(QuarantineRecordModel)
                    .where(
                        QuarantineRecordModel.status == "OPEN",
                        or_(
                            QuarantineRecordModel.raw_record_id.in_(legacy_raw_ids),
                            and_(
                                QuarantineRecordModel.reason_code
                                == "DATA.IDENTITY_GROUP_INCOMPLETE",
                                QuarantineRecordModel.raw_record_id.in_(stale_parser_raw_ids),
                            ),
                        ),
                    )
                    .values(status="IGNORED", resolved_at_ms=_now_ms())
                )
                ignored_count = int(getattr(ignored, "rowcount", 0) or 0)
                session.commit()
            return {"ok": True, "ignored": ignored_count}
        except Exception:
            session.rollback()
            return {"ok": False, "code": "INTERNAL.UNEXPECTED"}
        finally:
            session.close()

    def _collect_matches(
        self, job_id: str, *, collection_reason: str
    ) -> dict[str, bool | str | int]:
        """Capture ranked matches, preserving raw entries before strict parsing."""
        try:
            with self._lock, self._collection_job(job_id, "MATCHES", collection_reason):
                try:
                    session, own_display_name = self._load_collection_context()
                except DomainError as error:
                    if error.code != "DATA.IDENTITY_GROUP_INCOMPLETE":
                        raise
                    # Already on the browser-owning thread: run the missing
                    # prerequisite directly without re-entering the coordinator.
                    profile_result = self._collect_profile(
                        _new_id(), collection_reason=collection_reason
                    )
                    if profile_result.get("ok") is not True:
                        raise error_from_code(str(profile_result["code"])) from None
                    session, own_display_name = self._load_collection_context()
                captured = BucklerBattlelogCapture(_now_ms, self._capture_browser).capture(session)
                ingestion_id = _new_id()
                with self._uow_factory.write() as uow:
                    uow.ingestions.add(
                        IngestionRecord(
                            id=ingestion_id, job_id=job_id, account_id=1, kind="LIVE",
                            parser_version=BUCKLER_BATTLELOG_PARSER_VERSION,
                            state="NORMALIZING",
                            started_at_ms=_now_ms(), finished_at_ms=None, raw_count=0,
                            normalized_count=0, duplicate_count=0, quarantine_count=0,
                            error_code=None, diagnostic_id=None,
                        )
                    )
                    result = RawFirstCollectionService(_new_id, _now_ms).persist(
                        uow,
                        uow.raw_records,
                        uow.quarantines,
                        ingestion=CollectionIngestion(ingestion_id=ingestion_id, account_id=1),
                        collected_matches=captured,
                        normalizer=lambda payload: normalize_battlelog_match(
                            payload,
                            account_user_code=session.user_code.value,
                            own_display_name=own_display_name,
                        ),
                    )
                    uow.jobs.set_state(
                        job_id,
                        JobState.SUCCEEDED_WITH_WARNINGS
                        if result.quarantine_count
                        else JobState.SUCCEEDED,
                    )
                    uow.commit()
            return {
                "ok": True,
                "normalized": result.normalized_count,
                "duplicates": result.duplicate_count,
                "quarantined": result.quarantine_count,
            }
        except DomainError as error:
            return {"ok": False, "code": error.code}
        except Exception:
            return {"ok": False, "code": "INTERNAL.UNEXPECTED"}

    @contextmanager
    def _collection_job(self, job_id: str, phase: str, reason: str) -> Iterator[None]:
        """Commit the attempt before capture; retain an outcome even on rollback."""
        started_at_ms = _now_ms()
        with self._uow_factory.write() as uow:
            uow.jobs.add(
                JobRecord(
                    id=job_id, type="COLLECT", reason=reason, state="RUNNING", phase=phase,
                    requested_at_ms=started_at_ms, started_at_ms=started_at_ms,
                    finished_at_ms=None, progress_current=0,
                    progress_total=1 if phase == "PROFILE" else None,
                    error_code=None, diagnostic_id=None, summary_json=None,
                )
            )
            uow.commit()
        error_code: str | None = None
        diagnostic_id: str | None = None
        try:
            yield
        except Exception as error:
            error_code = error.code if isinstance(error, DomainError) else "INTERNAL.UNEXPECTED"
            diagnostic_id = _new_id()
            raise
        finally:
            finished_at_ms = _now_ms()
            # The ingestion transaction owns successful state transitions.
            # Supplemental timestamps/logging must never turn committed data
            # into a failed request, nor mask the original capture error.
            with suppress(Exception):
                self._finish_collection_job(job_id, finished_at_ms, error_code, diagnostic_id)
            with suppress(Exception):
                self._log_sink.write({
                    "event": "collection_finished", "job_id": job_id, "phase": phase,
                    "reason": reason, "finished_at_ms": finished_at_ms,
                    "error_code": error_code, "diagnostic_id": diagnostic_id,
                })

    def _finish_collection_job(
        self, job_id: str, finished_at_ms: int,
        error_code: str | None, diagnostic_id: str | None,
    ) -> None:
        """Record a sanitized failure or supplement an already committed success."""
        with self._session_factory() as session:
            job = session.get(JobModel, job_id)
            if job is None:
                return
            if error_code is not None and job.state == JobState.RUNNING.value:
                job.state = JobState.FAILED.value
                job.error_code = error_code
                job.diagnostic_id = diagnostic_id
            if job.state in {JobState.SUCCEEDED.value, JobState.SUCCEEDED_WITH_WARNINGS.value}:
                ingestion = session.scalar(
                    select(IngestionRunModel).where(IngestionRunModel.job_id == job_id)
                )
                if ingestion is not None:
                    job.progress_current = ingestion.raw_count
                    job.progress_total = ingestion.raw_count
            job.finished_at_ms = finished_at_ms
            session.commit()

    def _collection_outcomes(self) -> dict[str, str | int]:
        """Read committed job state without waiting for an in-flight browser call."""
        with self._session_factory() as session:
            jobs = select(JobModel).where(
                JobModel.type == "COLLECT", JobModel.phase.in_({"PROFILE", "MATCHES"})
            )
            last_attempt = session.scalar(
                jobs.order_by(JobModel.requested_at_ms.desc(), JobModel.id.desc()).limit(1)
            )
            finished_at = func.coalesce(JobModel.finished_at_ms, JobModel.started_at_ms,
                                        JobModel.requested_at_ms)
            last_success = session.scalar(
                jobs.where(
                    JobModel.phase == "MATCHES",
                    JobModel.state.in_({"SUCCEEDED", "SUCCEEDED_WITH_WARNINGS"}),
                ).order_by(finished_at.desc(), JobModel.id.desc()).limit(1)
            )
            failures = jobs.where(JobModel.state.in_({"FAILED", "INTERRUPTED"}))
            last_success_at_ms = 0
            if last_success is not None:
                last_success_at_ms = (
                    last_success.finished_at_ms or last_success.started_at_ms
                    or last_success.requested_at_ms
                )
                failures = failures.where(or_(
                    finished_at > last_success_at_ms,
                    and_(finished_at == last_success_at_ms, JobModel.id > last_success.id),
                ))
            last_failure = session.scalar(
                failures.order_by(finished_at.desc(), JobModel.id.desc()).limit(1)
            )
            return {
                "last_attempt_at_ms": last_attempt.requested_at_ms if last_attempt else 0,
                "last_success_at_ms": last_success_at_ms,
                "last_error_code": (
                    last_failure.error_code or "INTERNAL.UNEXPECTED" if last_failure else ""
                ),
            }

    def _recover_interrupted_collections(self) -> None:
        """Reconcile orphaned attempts after startup has acquired the loopback port."""
        events: list[dict[str, object]] = []
        recovered_at_ms = _now_ms()
        with self._lock, self._session_factory() as session:
            jobs = session.scalars(select(JobModel).where(
                JobModel.type == "COLLECT",
                JobModel.phase.in_({"PROFILE", "MATCHES"}),
                JobModel.state.in_({JobState.QUEUED.value, JobState.RUNNING.value}),
            ))
            for job in jobs:
                job.state = JobState.INTERRUPTED.value
                job.error_code = job.error_code or "INTERNAL.UNEXPECTED"
                job.diagnostic_id = job.diagnostic_id or _new_id()
                if job.finished_at_ms is None:
                    job.finished_at_ms = max(
                        recovered_at_ms, job.requested_at_ms, job.started_at_ms or 0
                    )
                events.append({
                    "event": "collection_interrupted", "job_id": job.id, "phase": job.phase,
                    "finished_at_ms": job.finished_at_ms,
                    "error_code": job.error_code, "diagnostic_id": job.diagnostic_id,
                })
            session.commit()
        for event in events:
            with suppress(Exception):
                self._log_sink.write(event)

    def _admit_collection(
        self,
        key: str,
        handler: Callable[[str], dict[str, bool | str | int]],
    ) -> dict[str, bool | str | int]:
        """Start, queue, or coalesce a native collection request safely."""
        job_id = _new_id()
        with self._request_lock:
            self._request_handlers[job_id] = handler
        try:
            admission = self._coordinator.admit(
                CollectionRequest(
                    job_id=job_id,
                    kind=CollectionRequestKind.COLLECT,
                    key=CanonicalRequestKey(key),
                )
            )
        except DomainError as error:
            with self._request_lock:
                self._request_handlers.pop(job_id, None)
            return {"ok": False, "code": error.code}
        except Exception:
            with self._request_lock:
                self._request_handlers.pop(job_id, None)
            return {"ok": False, "code": "INTERNAL.UNEXPECTED"}

        if admission.admission is CollectionAdmission.COALESCED:
            with self._request_lock:
                self._request_handlers.pop(job_id, None)
            return {"ok": True, "status": "COALESCED"}
        if admission.admission is CollectionAdmission.QUEUED:
            return {"ok": True, "status": "QUEUED"}
        with self._request_lock:
            return self._collection_results.pop(
                job_id, {"ok": False, "code": "INTERNAL.UNEXPECTED"}
            )

    def _run_collection_request(self, request: CollectionRequest) -> None:
        """Execute one admitted request, retain its safe result, and promote the queue."""
        with self._request_lock:
            handler = self._request_handlers.pop(request.job_id, None)
        if handler is None:
            result: dict[str, bool | str | int] = {"ok": False, "code": "INTERNAL.UNEXPECTED"}
        else:
            try:
                result = handler(request.job_id)
            except DomainError as error:
                result = {"ok": False, "code": error.code}
            except Exception:
                result = {"ok": False, "code": "INTERNAL.UNEXPECTED"}
        with self._request_lock:
            self._collection_results[request.job_id] = result
        self._coordinator.complete(request.job_id)

    def _load_active_session(self) -> AuthSession:
        """Load DPAPI state only when it belongs to the database's one account."""
        session = self._session_factory()
        try:
            account = session.get(AccountModel, 1)
            if account is None or account.auth_state != "VALID":
                raise error_from_code("SESSION.MISSING")
            auth = DpapiAuthVault(self._paths).load()
            if auth is None:
                raise error_from_code("SESSION.MISSING")
            if auth.user_code.value != account.user_code:
                raise error_from_code("SESSION.ACCOUNT_MISMATCH")
            return auth
        finally:
            session.close()

    def _load_collection_context(self) -> tuple[AuthSession, str]:
        """Load authenticated state and the verified display name used to orient matches."""
        auth = self._load_active_session()
        session = self._session_factory()
        try:
            profile = session.scalar(
                select(ProfileSnapshotModel)
                .where(ProfileSnapshotModel.account_id == 1)
                .order_by(
                    ProfileSnapshotModel.observed_at_ms.desc(),
                    ProfileSnapshotModel.id.desc(),
                )
                .limit(1)
            )
            if (
                profile is None
                or not isinstance(profile.display_name, str)
                or not profile.display_name.strip()
            ):
                raise error_from_code("DATA.IDENTITY_GROUP_INCOMPLETE")
            return auth, profile.display_name
        finally:
            session.close()

    def close(self) -> None:
        """Close the app-owned collection browser during desktop shutdown."""
        with self._lock:
            self._capture_browser.close()


class AutoCollectionScheduler:
    """Run manual collection on demand and automatic collection only when enabled."""

    def __init__(
        self,
        bridge: NativeLoginBridge,
        interval_seconds: float,
        *,
        automatic_enabled: bool = False,
    ) -> None:
        self._bridge = bridge
        self._interval_seconds = interval_seconds
        self._stopped = Event()
        self._thread: Thread | None = None
        self._manual_requests: Queue[
            _AutoCollectionRequest | _AutoCollectionStateChanged | None
        ] = Queue()
        self._automatic_state_lock = Lock()
        self._automatic_enabled = automatic_enabled
        self._bridge.set_collection_dispatcher(self.request)

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("Auto collection scheduler has already been started.")
        self._thread = Thread(target=self._run, name="sf6viewer-auto-collection", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        self._manual_requests.put(None)
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5.0)

    def request(self, key: str) -> dict[str, bool | str | int]:
        """Run a manual request on the browser-owning scheduler thread."""
        if self._stopped.is_set():
            return {"ok": False, "code": "INTERNAL.UNEXPECTED"}
        completed = Event()
        result: dict[str, bool | str | int] = {}
        self._manual_requests.put((key, completed, result))
        if not completed.wait(MANUAL_COLLECTION_TIMEOUT_SECONDS):
            return {"ok": False, "code": "UPSTREAM.TIMEOUT"}
        return result

    def set_auto_collection_enabled(self, enabled: bool) -> None:
        """Wake a sleeping scheduler so a persisted toggle takes effect promptly."""
        if not isinstance(enabled, bool):
            raise TypeError("enabled must be a bool.")
        with self._automatic_state_lock:
            changed = self._automatic_enabled != enabled
            self._automatic_enabled = enabled
        if changed:
            self._manual_requests.put(_AUTO_COLLECTION_STATE_CHANGED)

    def _automatic_collection_enabled(self) -> bool:
        with self._automatic_state_lock:
            return self._automatic_enabled

    def _run(self) -> None:
        next_automatic_at = monotonic()
        profile_pending = True
        try:
            while not self._stopped.is_set():
                timeout = (
                    max(0.0, next_automatic_at - monotonic())
                    if self._automatic_collection_enabled()
                    else None
                )
                try:
                    request = self._manual_requests.get(timeout=timeout)
                except Empty:
                    request = None

                if request is _AUTO_COLLECTION_STATE_CHANGED:
                    if self._automatic_collection_enabled():
                        next_automatic_at = monotonic()
                    else:
                        # Playwright belongs to this scheduler thread.  Closing
                        # here releases the visible Chrome window without
                        # racing a current capture on another thread.
                        self._bridge.close()
                    continue

                if isinstance(request, tuple):
                    key, completed, result = request
                    result.update(self._bridge.run_scheduled_collection(key))
                    if key == "PROFILE" and result.get("ok") is True:
                        profile_pending = False
                    completed.set()
                    if self._automatic_collection_enabled():
                        next_automatic_at = monotonic() + self._interval_seconds
                    else:
                        self._bridge.close()
                    continue

                if self._stopped.is_set():
                    break
                if not self._automatic_collection_enabled():
                    continue
                if profile_pending:
                    profile_result = self._bridge.run_scheduled_collection(
                        "PROFILE", collection_reason="SCHEDULED"
                    )
                    profile_pending = profile_result.get("ok") is not True
                if not self._stopped.is_set() and self._automatic_collection_enabled():
                    match_result = self._bridge.run_scheduled_collection(
                        "MATCHES", collection_reason="SCHEDULED"
                    )
                    if match_result.get("code") in {
                        "SESSION.MISSING",
                        "SESSION.EXPIRED",
                        "SESSION.ACCOUNT_MISMATCH",
                    }:
                        profile_pending = True
                elif not self._automatic_collection_enabled():
                    self._bridge.close()
                next_automatic_at = monotonic() + self._interval_seconds
        finally:
            self._bridge.close()
            while True:
                try:
                    request = self._manual_requests.get_nowait()
                except Empty:
                    break
                if isinstance(request, tuple):
                    _, completed, result = request
                    result.update({"ok": False, "code": "INTERNAL.UNEXPECTED"})
                    completed.set()


class _DiscardingEventPublisher:
    """The desktop bridge has no live event stream; API polling observes commits."""

    def publish(self, events: object) -> None:
        """Discard post-commit events without changing durable collection data."""


class _DiscardingWarningSink:
    """Avoid exposing post-commit internals through the native bridge."""

    def warn(self, code: str, *, diagnostic_id: str) -> None:
        """Ignore non-fatal event delivery warnings in the initial desktop host."""


def _now_ms() -> int:
    """Return the current Unix timestamp in milliseconds."""
    return int(time() * 1_000)


def _new_id() -> str:
    """Create opaque ULIDs whose ordering is stable within the same millisecond."""
    return str(ulid.monotonic.new())


def _wait_for_authenticated_profile(page: Page) -> None:
    """Wait a finite time for an authenticated Buckler profile link to appear."""
    page.wait_for_function(
        """() => Array.from(document.querySelectorAll('a[href]')).some((link) =>
        /(?:^|\\/)profile\\/[0-9]{10}(?:\\/|$|[?#])/.test(link.getAttribute('href') || '')
        )""",
        timeout=AUTHENTICATED_PROFILE_TIMEOUT_MS,
    )


def _extract_profile_user_code(page: Page) -> str:
    """Return the exact ten-digit account code from an authenticated profile href."""
    profile_hrefs = page.locator("a[href*='/profile/']").evaluate_all(
        "(links) => links.map((link) => link.getAttribute('href'))"
    )
    if not isinstance(profile_hrefs, list):
        raise RuntimeError("Authenticated profile is unavailable.")

    for href in profile_hrefs:
        if not isinstance(href, str):
            continue
        matched = _PROFILE_USER_CODE_PATTERN.search(href)
        if matched is not None:
            return matched.group(1)

    raise RuntimeError("Authenticated profile is unavailable.")


class LoopbackServer:
    """A Uvicorn server that owns one already-bound IPv4 loopback socket."""

    def __init__(self, app: FastAPI) -> None:
        self._socket = _bind_loopback_socket()
        self._server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=LOOPBACK_HOST,
                port=LOOPBACK_PORT,
                access_log=False,
                log_config=None,
                log_level="warning",
            )
        )
        self._thread: Thread | None = None
        self._failure: BaseException | None = None
        self._stopped = Event()
        self._lifecycle_lock = Lock()

    @property
    def url(self) -> str:
        """Return the only origin made available to the desktop webview."""
        return f"http://{LOOPBACK_HOST}:{LOOPBACK_PORT}/"

    @property
    def dashboard_url(self) -> str:
        """Return the package dashboard URL on the same loopback origin."""
        return f"{self.url}ui/dashboard.html"

    def start(self, timeout_seconds: float = SERVER_START_TIMEOUT_SECONDS) -> None:
        """Run Uvicorn in the background and wait only for its lifespan startup."""
        with self._lifecycle_lock:
            if self._thread is not None:
                raise RuntimeError("Loopback server has already been started.")
            self._thread = Thread(target=self._serve, name="sf6viewer-loopback", daemon=True)
            self._thread.start()

        deadline = monotonic() + timeout_seconds
        while monotonic() < deadline:
            if self._server.started:
                return
            if self._failure is not None or self._stopped.is_set():
                break
            self._stopped.wait(timeout=0.05)

        self.stop()
        raise DesktopStartupError("The local application server did not start.")

    def stop(self, timeout_seconds: float = SERVER_STOP_TIMEOUT_SECONDS) -> None:
        """Request Uvicorn shutdown and wait a bounded time for the server thread."""
        self._server.should_exit = True
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout_seconds)
        _close_socket(self._socket)

    def _serve(self) -> None:
        try:
            self._server.run(sockets=[self._socket])
        except Exception as error:  # Captured only to turn startup into one safe error.
            self._failure = error
        finally:
            _close_socket(self._socket)
            self._stopped.set()


def _bind_loopback_socket() -> socket.socket:
    """Bind and listen on the stable OBS loopback port before Uvicorn starts.

    The pre-bound socket is passed directly to Uvicorn.  This removes the
    bind-after-selection race, while the literal IPv4 loopback address prevents
    LAN exposure. A port conflict fails startup instead of silently changing the
    saved OBS browser-source URL.
    """
    bound_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        exclusive_address_use = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive_address_use is not None:
            bound_socket.setsockopt(socket.SOL_SOCKET, exclusive_address_use, 1)
        bound_socket.bind((LOOPBACK_HOST, LOOPBACK_PORT))
        bound_socket.listen(socket.SOMAXCONN)
        bound_socket.setblocking(False)
        return bound_socket
    except Exception:
        _close_socket(bound_socket)
        raise


def _close_socket(bound_socket: socket.socket) -> None:
    """Close a socket once; repeated cleanup remains harmless."""
    with suppress(OSError):
        bound_socket.close()


def _web_assets_directory() -> Path:
    """Locate package-owned web assets without consulting the process CWD."""
    return Path(__file__).resolve().parents[1] / "web"


def _compose_application(session_factory: Callable[[], Session]) -> FastAPI:
    """Compose committed API routes with the concurrent package web bundle."""
    assets_directory = _web_assets_directory()
    if not assets_directory.is_dir() or not (assets_directory / "dashboard.html").is_file():
        raise DesktopStartupError("The desktop application bundle is unavailable.")

    app = create_read_api(session_factory)
    app.mount(
        "/ui",
        StaticFiles(directory=str(assets_directory), html=False, check_dir=True),
        name="desktop-web",
    )
    return app


def _open_desktop_window(url: str, *, js_api: object) -> None:
    """Open the same-origin dashboard and block until its pywebview window closes."""
    import webview

    webview.create_window(
        f"SF6Viewer v{__version__}",
        url=url,
        width=1280,
        height=800,
        min_size=(900, 600),
        js_api=js_api,
    )
    webview.start(debug=False, http_server=False, private_mode=True)


def _show_safe_startup_error() -> bool:
    """Show a generic pywebview error window without exposing exception details."""
    try:
        import webview

        if webview.windows:
            return False
        webview.create_window(
            f"SF6Viewer v{__version__}",
            html=(
                "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
                "<title>SF6Viewer</title></head><body>"
                "<h1>SF6Viewer could not start.</h1>"
                "<p>Restart the app. If the problem continues, check the installation.</p>"
                "</body></html>"
            ),
            width=520,
            height=220,
            resizable=False,
        )
        webview.start(debug=False, http_server=False, private_mode=True)
        return True
    except Exception:
        return False


def run_desktop() -> int:
    """Start, host, and cleanly stop the v2 desktop process.

    Database migrations target only ``%LOCALAPPDATA%\\SF6Viewer``'s v2 file.
    Startup failures are rendered as a generic native webview window when that
    facility is usable; no exception text or private state is placed in a UI.
    """
    engine: Engine | None = None
    server: LoopbackServer | None = None
    bridge: NativeLoginBridge | None = None
    scheduler: AutoCollectionScheduler | None = None

    try:
        paths = AppPaths.from_windows_local_app_data()
        paths.ensure_directories()
        run_migrations(paths.database)
        engine = create_engine_for(paths)
        session_factory = create_session_factory(engine)
        application = _compose_application(session_factory)
        server = LoopbackServer(application)
        server.start()
        bridge = NativeLoginBridge(paths, session_factory)
        # Only the process owning the fixed loopback port may reconcile jobs.
        # Keep this out of bridge construction and before starting new work.
        bridge._recover_interrupted_collections()
        auto_collection_status = bridge.auto_collection_status()
        initial_auto_collection_enabled = auto_collection_status.get("enabled") is True
        initial_interval_seconds = auto_collection_status.get("interval_seconds")
        if not isinstance(initial_interval_seconds, int) or isinstance(
            initial_interval_seconds, bool
        ):
            initial_interval_seconds = int(AUTO_COLLECTION_INTERVAL_SECONDS)
        scheduler = AutoCollectionScheduler(
            bridge,
            float(initial_interval_seconds),
            automatic_enabled=initial_auto_collection_enabled,
        )
        bridge.set_auto_collection_controller(scheduler.set_auto_collection_enabled)
        scheduler.start()
        _open_desktop_window(
            server.dashboard_url,
            js_api=bridge,
        )
        return 0
    except Exception:
        # Retain port ownership until finally has stopped collection work.
        # A second process must not recover jobs still owned by this scheduler.
        if _show_safe_startup_error():
            return 1
        raise
    finally:
        if scheduler is not None:
            scheduler.stop()
        if bridge is not None:
            bridge.close()
        if server is not None:
            server.stop()
        if engine is not None:
            engine.dispose()
