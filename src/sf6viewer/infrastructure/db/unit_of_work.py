"""SQLAlchemy implementation of explicit read and write transaction boundaries."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from types import TracebackType
from typing import Protocol, cast

from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, sessionmaker

from sf6viewer.application.ports.event_publisher import (
    DiagnosticIdFactory,
    EventPublisher,
    WarningSink,
)
from sf6viewer.application.ports.repositories import (
    IngestionRepository,
    JobRepository,
    MatchRepository,
    ProfileSnapshotRepository,
    QuarantineRepository,
    RawRecordRepository,
)
from sf6viewer.application.ports.unit_of_work import UnitOfWork
from sf6viewer.domain.events import DomainEvent
from sf6viewer.infrastructure.db.repositories.ingestions import SqlAlchemyIngestionRepository
from sf6viewer.infrastructure.db.repositories.jobs import SqlAlchemyJobRepository
from sf6viewer.infrastructure.db.repositories.matches import SqlAlchemyMatchRepository
from sf6viewer.infrastructure.db.repositories.quarantines import SqlAlchemyQuarantineRepository
from sf6viewer.infrastructure.db.repositories.raw_records import SqlAlchemyRawRecordRepository
from sf6viewer.infrastructure.db.repositories.profiles import SqlAlchemyProfileSnapshotRepository

_READ_ONLY_MESSAGE = "read unit of work is read-only"


class _ProcessLock(Protocol):
    """The minimal synchronization interface used to serialize writers."""

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        """Acquire the process-local writer lock."""
        raise NotImplementedError

    def release(self) -> None:
        """Release the process-local writer lock."""
        raise NotImplementedError


SessionFactory = Callable[[], Session]


class SqlAlchemyUnitOfWorkFactory:
    """Creates fresh read or serialized-write SQLAlchemy units of work."""

    def __init__(
        self,
        session_factory: sessionmaker[Session] | SessionFactory,
        write_lock: _ProcessLock,
        publisher: EventPublisher,
        warning_sink: WarningSink,
        diagnostic_id_factory: DiagnosticIdFactory,
    ) -> None:
        self._session_factory = session_factory
        self._write_lock = write_lock
        self._publisher = publisher
        self._warning_sink = warning_sink
        self._diagnostic_id_factory = diagnostic_id_factory

    def read(self) -> AbstractContextManager[UnitOfWork]:
        """Create an independent, SQLite-enforced read-only context."""
        return SqlAlchemyUnitOfWork(
            session=self._session_factory(),
            publisher=self._publisher,
            warning_sink=self._warning_sink,
            diagnostic_id_factory=self._diagnostic_id_factory,
            write_lock=None,
            read_only=True,
        )

    def write(self) -> AbstractContextManager[UnitOfWork]:
        """Create an independent context serialized by the process writer lock."""
        return SqlAlchemyUnitOfWork(
            session=self._session_factory(),
            publisher=self._publisher,
            warning_sink=self._warning_sink,
            diagnostic_id_factory=self._diagnostic_id_factory,
            write_lock=self._write_lock,
            read_only=False,
        )


class SqlAlchemyUnitOfWork:
    """A Session lifecycle that commits only when explicitly requested."""

    def __init__(
        self,
        session: Session,
        publisher: EventPublisher,
        warning_sink: WarningSink,
        diagnostic_id_factory: DiagnosticIdFactory,
        write_lock: _ProcessLock | None,
        read_only: bool,
    ) -> None:
        self._session = session
        self._publisher = publisher
        self._warning_sink = warning_sink
        self._diagnostic_id_factory = diagnostic_id_factory
        self._write_lock = write_lock
        self._read_only = read_only
        self._connection: Connection | None = None
        self._events: list[DomainEvent] = []
        self._committed = False
        self._entered = False
        self._lock_acquired = False
        self.jobs: JobRepository
        self.ingestions: IngestionRepository
        self.matches: MatchRepository
        self.raw_records: RawRecordRepository
        self.quarantines: QuarantineRepository
        self.profile_snapshots: ProfileSnapshotRepository

    def __enter__(self) -> SqlAlchemyUnitOfWork:
        """Configure the connection and construct transaction-scoped repositories."""
        if self._entered:
            raise RuntimeError("unit of work cannot be entered more than once")
        self._entered = True
        try:
            self._connection = self._session.connection()
            if self._read_only:
                self._connection.exec_driver_sql("PRAGMA query_only=ON")
            else:
                # A connection returned after a failed read cleanup must never remain read-only.
                self._connection.exec_driver_sql("PRAGMA query_only=OFF")
                if self._write_lock is None:
                    raise RuntimeError("write unit of work requires a write lock")
                self._write_lock.acquire()
                self._lock_acquired = True

            self.jobs = SqlAlchemyJobRepository(self._session, read_only=self._read_only)
            self.ingestions = SqlAlchemyIngestionRepository(
                self._session, read_only=self._read_only
            )
            self.matches = SqlAlchemyMatchRepository(self._session, read_only=self._read_only)
            self.raw_records = SqlAlchemyRawRecordRepository(
                self._session, read_only=self._read_only
            )
            self.quarantines = SqlAlchemyQuarantineRepository(
                self._session, read_only=self._read_only
            )
            self.profile_snapshots = SqlAlchemyProfileSnapshotRepository(
                self._session, read_only=self._read_only
            )
            return self
        except BaseException:
            self._close_after_failed_enter()
            raise

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Rollback unfinished work, reset read state, release resources, and never suppress."""
        del exc_type, exc_value, traceback
        try:
            if self._read_only or not self._committed or self._session.in_transaction():
                self.rollback()
            if self._read_only:
                self._reset_read_connection()
        finally:
            self._events.clear()
            self._session.close()
            self._release_write_lock()

    def queue_event(self, event: DomainEvent) -> None:
        """Queue an event for publication only after a successful explicit commit."""
        self._ensure_writable()
        if self._committed:
            raise RuntimeError("cannot queue events after commit")
        self._events.append(event)

    def commit(self) -> None:
        """Commit once, then attempt to publish every queued event."""
        self._ensure_writable()
        if self._committed:
            raise RuntimeError("unit of work has already committed")

        self._session.commit()
        self._committed = True
        try:
            self._publisher.publish(tuple(self._events))
        except Exception:
            try:
                self._warning_sink.warn(
                    "EVENT_PUBLISH_FAILED",
                    diagnostic_id=self._diagnostic_id_factory(),
                )
            except Exception:
                # A post-commit warning mechanism must not alter committed data or escape it.
                pass
        finally:
            self._events.clear()

    def rollback(self) -> None:
        """Discard all uncommitted database work and queued events."""
        self._session.rollback()
        self._events.clear()

    def _ensure_writable(self) -> None:
        if self._read_only:
            raise RuntimeError(_READ_ONLY_MESSAGE)

    def _reset_read_connection(self) -> None:
        """Disable SQLite query-only mode, invalidating the connection if that fails."""
        try:
            connection = self._connection or self._session.connection()
            connection.exec_driver_sql("PRAGMA query_only=OFF")
        except Exception:
            if self._connection is not None:
                self._connection.invalidate()
            else:
                self._session.invalidate()

    def _close_after_failed_enter(self) -> None:
        """Clean up a partially entered context before propagating its failure."""
        try:
            self._session.rollback()
        finally:
            if self._read_only:
                self._reset_read_connection()
            self._events.clear()
            self._session.close()
            self._release_write_lock()

    def _release_write_lock(self) -> None:
        if self._lock_acquired:
            write_lock = cast(_ProcessLock, self._write_lock)
            self._lock_acquired = False
            write_lock.release()


__all__ = ["SqlAlchemyUnitOfWork", "SqlAlchemyUnitOfWorkFactory"]
