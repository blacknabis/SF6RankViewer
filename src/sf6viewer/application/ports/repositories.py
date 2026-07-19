"""Persistence records and repository contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from sf6viewer.domain.job import JobState


@dataclass(frozen=True, slots=True)
class JobRecord:
    """The complete durable representation of a job."""

    id: str
    type: str
    reason: str
    state: str
    phase: str | None
    requested_at_ms: int
    started_at_ms: int | None
    finished_at_ms: int | None
    progress_current: int | None
    progress_total: int | None
    error_code: str | None
    diagnostic_id: str | None
    summary_json: str | None


@dataclass(frozen=True, slots=True)
class IngestionRecord:
    """The complete durable representation of an ingestion run."""

    id: str
    job_id: str
    account_id: int | None
    kind: str
    parser_version: str
    state: str
    started_at_ms: int
    finished_at_ms: int | None
    raw_count: int
    normalized_count: int
    duplicate_count: int
    quarantine_count: int
    error_code: str | None
    diagnostic_id: str | None


@dataclass(frozen=True, slots=True)
class MatchRecord:
    """The complete immutable fact required to insert a normalized match."""

    id: str
    account_id: int
    identity_key: str
    identity_kind: str
    content_sha256: str
    occurred_at_ms: int
    occurred_at_source: str
    my_character: str
    my_mr: int | None
    my_lp: int | None
    opponent_name: str
    opponent_character: str
    opponent_mr: int | None
    opponent_lp: int | None
    result: str
    created_at_ms: int


@dataclass(frozen=True, slots=True)
class ObservationRecord:
    """One raw-source observation of an existing normalized match."""

    id: str
    match_id: str
    raw_record_id: str
    ingestion_id: str
    observed_content_sha256: str
    observed_at_ms: int


@dataclass(frozen=True, slots=True)
class RawRecord:
    """Immutable raw evidence stored before its normalized interpretation."""

    id: str
    ingestion_id: str
    ordinal: int
    record_type: str
    source_key: str | None
    payload_json: bytes
    payload_sha256: str
    fetched_at_ms: int
    disposition: str
    disposed_at_ms: int | None


@dataclass(frozen=True, slots=True)
class QuarantineRecord:
    """A safe normalization rejection linked to one raw evidence record."""

    id: str
    raw_record_id: str
    account_id: int | None
    reason_code: str
    field_errors_json: str | None
    status: str
    created_at_ms: int
    resolved_at_ms: int | None
    resolution_match_id: str | None


class InsertOutcome(str, Enum):
    """Result of inserting a match under its durable identity."""

    NEW = "NEW"
    SAME_CONTENT = "SAME_CONTENT"
    IDENTITY_COLLISION = "IDENTITY_COLLISION"


class JobRepository(Protocol):
    """Repository operations for jobs."""

    def add(self, job: JobRecord) -> None:
        """Add a job to the caller's transaction."""
        raise NotImplementedError

    def get(self, job_id: str) -> JobRecord | None:
        """Get a job by identifier."""
        raise NotImplementedError

    def set_state(self, job_id: str, state: JobState) -> None:
        """Set a job lifecycle state in the caller's transaction."""
        raise NotImplementedError

    def list_non_terminal(self) -> list[JobRecord]:
        """List jobs whose state has not reached a terminal state."""
        raise NotImplementedError


class IngestionRepository(Protocol):
    """Repository operations for ingestion runs."""

    def add(self, ingestion: IngestionRecord) -> None:
        """Add an ingestion run to the caller's transaction."""
        raise NotImplementedError

    def get(self, ingestion_id: str) -> IngestionRecord | None:
        """Get an ingestion run by identifier."""
        raise NotImplementedError

    def list_recoverable(self) -> list[IngestionRecord]:
        """List ingestion runs that have durable raw data to resume."""
        raise NotImplementedError

    def complete(
        self,
        ingestion_id: str,
        *,
        raw_count: int,
        normalized_count: int,
        duplicate_count: int,
        quarantine_count: int,
        finished_at_ms: int,
    ) -> None:
        """Persist final accounted-for counts and mark one run complete."""
        raise NotImplementedError


class MatchRepository(Protocol):
    """Repository operations for canonical matches and observations."""

    def insert_or_compare(self, match: MatchRecord) -> InsertOutcome:
        """Insert a match, or compare it with a persisted identity match."""
        raise NotImplementedError

    def add_observation(self, observation: ObservationRecord) -> None:
        """Add a raw observation only for matching persisted content."""
        raise NotImplementedError

    def get_by_identity(self, account_id: int, identity_key: str) -> MatchRecord | None:
        """Find the canonical match holding an account-scoped identity key."""
        raise NotImplementedError


class RawRecordRepository(Protocol):
    """Repository operations for immutable raw collection evidence."""

    def add(self, raw_record: RawRecord) -> None:
        """Add and flush pending raw evidence in the caller's transaction.

        The method may not invoke a parser or normalizer.  Callers can safely
        interpret the raw payload only after this method returns.
        """
        raise NotImplementedError

    def set_disposition(
        self, raw_record_id: str, disposition: str, *, disposed_at_ms: int
    ) -> None:
        """Make the raw record's one permitted disposition transition."""
        raise NotImplementedError


class QuarantineRepository(Protocol):
    """Repository operations for open raw-normalization rejections."""

    def add(self, quarantine: QuarantineRecord) -> None:
        """Add a quarantine record to the caller's transaction."""
        raise NotImplementedError
