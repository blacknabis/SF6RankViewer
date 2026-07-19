"""SQLAlchemy repository for durable jobs."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from sf6viewer.application.ports.repositories import JobRecord
from sf6viewer.domain.job import JobState
from sf6viewer.infrastructure.db.models.jobs import JobModel

_READ_ONLY_MESSAGE = "read unit of work is read-only"
_TERMINAL_STATES = frozenset({
    JobState.SUCCEEDED.value,
    JobState.SUCCEEDED_WITH_WARNINGS.value,
    JobState.FAILED.value,
    JobState.CANCELLED.value,
    JobState.INTERRUPTED.value,
})


class SqlAlchemyJobRepository:
    """Persists jobs without owning the surrounding transaction."""

    def __init__(self, session: Session, *, read_only: bool = False) -> None:
        self._session = session
        self._read_only = read_only

    def add(self, job: JobRecord) -> None:
        """Add a job to the current transaction."""
        self._ensure_writable()
        self._session.add(JobModel(**_job_values(job)))

    def get(self, job_id: str) -> JobRecord | None:
        """Return a job record when present."""
        model = self._session.get(JobModel, job_id)
        return None if model is None else _to_record(model)

    def set_state(self, job_id: str, state: JobState) -> None:
        """Update a job state without committing the caller's transaction."""
        self._ensure_writable()
        model = self._session.get(JobModel, job_id)
        if model is not None:
            model.state = state.value

    def list_non_terminal(self) -> list[JobRecord]:
        """Return jobs not in a terminal lifecycle state."""
        statement = (
            select(JobModel)
            .where(JobModel.state.not_in(_TERMINAL_STATES))
            .order_by(JobModel.requested_at_ms, JobModel.id)
        )
        return [_to_record(model) for model in self._session.scalars(statement)]

    def _ensure_writable(self) -> None:
        if self._read_only:
            raise RuntimeError(_READ_ONLY_MESSAGE)


def _job_values(job: JobRecord) -> dict[str, object]:
    return {
        "id": job.id,
        "type": job.type,
        "reason": job.reason,
        "state": job.state,
        "phase": job.phase,
        "requested_at_ms": job.requested_at_ms,
        "started_at_ms": job.started_at_ms,
        "finished_at_ms": job.finished_at_ms,
        "progress_current": job.progress_current,
        "progress_total": job.progress_total,
        "error_code": job.error_code,
        "diagnostic_id": job.diagnostic_id,
        "summary_json": job.summary_json,
    }


def _to_record(model: JobModel) -> JobRecord:
    return JobRecord(
        id=model.id,
        type=model.type,
        reason=model.reason,
        state=model.state,
        phase=model.phase,
        requested_at_ms=model.requested_at_ms,
        started_at_ms=model.started_at_ms,
        finished_at_ms=model.finished_at_ms,
        progress_current=model.progress_current,
        progress_total=model.progress_total,
        error_code=model.error_code,
        diagnostic_id=model.diagnostic_id,
        summary_json=model.summary_json,
    )
