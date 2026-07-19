"""Transaction boundary contracts."""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol

from sf6viewer.application.ports.repositories import (
    IngestionRepository,
    JobRepository,
    MatchRepository,
    ProfileSnapshotRepository,
    QuarantineRepository,
    RawRecordRepository,
)
from sf6viewer.domain.events import DomainEvent


class UnitOfWork(Protocol):
    """A transaction-scoped collection of repositories."""

    jobs: JobRepository
    ingestions: IngestionRepository
    matches: MatchRepository
    raw_records: RawRecordRepository
    quarantines: QuarantineRepository
    profile_snapshots: ProfileSnapshotRepository

    def queue_event(self, event: DomainEvent) -> None:
        """Queue an event for delivery after a successful commit."""
        raise NotImplementedError

    def commit(self) -> None:
        """Commit the transaction and publish queued events."""
        raise NotImplementedError

    def rollback(self) -> None:
        """Discard uncommitted work and queued events."""
        raise NotImplementedError


class UnitOfWorkFactory(Protocol):
    """Creates independent read and write unit-of-work contexts."""

    def read(self) -> AbstractContextManager[UnitOfWork]:
        """Create a read-only transaction context."""
        raise NotImplementedError

    def write(self) -> AbstractContextManager[UnitOfWork]:
        """Create a serialized write transaction context."""
        raise NotImplementedError
