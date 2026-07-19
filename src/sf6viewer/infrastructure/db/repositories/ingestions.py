"""SQLAlchemy repository for ingestion runs."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from sf6viewer.application.ports.repositories import IngestionRecord
from sf6viewer.infrastructure.db.models.ingestion_runs import IngestionRunModel

_READ_ONLY_MESSAGE = "read unit of work is read-only"
_RECOVERABLE_STATES = ("RAW_COMMITTED", "NORMALIZING")


class SqlAlchemyIngestionRepository:
    """Persists ingestion runs without owning the surrounding transaction."""

    def __init__(self, session: Session, *, read_only: bool = False) -> None:
        self._session = session
        self._read_only = read_only

    def add(self, ingestion: IngestionRecord) -> None:
        """Add an ingestion run to the current transaction."""
        self._ensure_writable()
        self._session.add(IngestionRunModel(**_ingestion_values(ingestion)))

    def get(self, ingestion_id: str) -> IngestionRecord | None:
        """Return an ingestion record when present."""
        model = self._session.get(IngestionRunModel, ingestion_id)
        return None if model is None else _to_record(model)

    def list_recoverable(self) -> list[IngestionRecord]:
        """Return only runs with raw evidence that can still be normalized."""
        statement = (
            select(IngestionRunModel)
            .where(IngestionRunModel.state.in_(_RECOVERABLE_STATES))
            .order_by(IngestionRunModel.started_at_ms, IngestionRunModel.id)
        )
        return [_to_record(model) for model in self._session.scalars(statement)]

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
        """Persist final counts and mark the run completed in this transaction."""
        self._ensure_writable()
        ingestion = self._session.get(IngestionRunModel, ingestion_id)
        if ingestion is None:
            raise ValueError("ingestion run was not found")
        ingestion.raw_count = raw_count
        ingestion.normalized_count = normalized_count
        ingestion.duplicate_count = duplicate_count
        ingestion.quarantine_count = quarantine_count
        ingestion.finished_at_ms = finished_at_ms
        ingestion.state = "COMPLETED"

    def _ensure_writable(self) -> None:
        if self._read_only:
            raise RuntimeError(_READ_ONLY_MESSAGE)


def _ingestion_values(ingestion: IngestionRecord) -> dict[str, object]:
    return {
        "id": ingestion.id,
        "job_id": ingestion.job_id,
        "account_id": ingestion.account_id,
        "kind": ingestion.kind,
        "parser_version": ingestion.parser_version,
        "state": ingestion.state,
        "started_at_ms": ingestion.started_at_ms,
        "finished_at_ms": ingestion.finished_at_ms,
        "raw_count": ingestion.raw_count,
        "normalized_count": ingestion.normalized_count,
        "duplicate_count": ingestion.duplicate_count,
        "quarantine_count": ingestion.quarantine_count,
        "error_code": ingestion.error_code,
        "diagnostic_id": ingestion.diagnostic_id,
    }


def _to_record(model: IngestionRunModel) -> IngestionRecord:
    return IngestionRecord(
        id=model.id,
        job_id=model.job_id,
        account_id=model.account_id,
        kind=model.kind,
        parser_version=model.parser_version,
        state=model.state,
        started_at_ms=model.started_at_ms,
        finished_at_ms=model.finished_at_ms,
        raw_count=model.raw_count,
        normalized_count=model.normalized_count,
        duplicate_count=model.duplicate_count,
        quarantine_count=model.quarantine_count,
        error_code=model.error_code,
        diagnostic_id=model.diagnostic_id,
    )
