"""SQLAlchemy repository for immutable raw collection evidence."""

from __future__ import annotations

from sqlalchemy import CursorResult, select, update
from sqlalchemy.orm import Session

from sf6viewer.application.ports.repositories import RawRecord
from sf6viewer.infrastructure.db.models.match_observations import MatchObservationModel
from sf6viewer.infrastructure.db.models.matches import MatchModel
from sf6viewer.infrastructure.db.models.raw_records import RawRecordModel

_READ_ONLY_MESSAGE = "read unit of work is read-only"


class SqlAlchemyRawRecordRepository:
    """Persists raw evidence and its single terminal disposition."""

    def __init__(self, session: Session, *, read_only: bool = False) -> None:
        self._session = session
        self._read_only = read_only

    def add(self, raw_record: RawRecord) -> None:
        """Add a pending raw record without committing the caller's transaction."""
        self._ensure_writable()
        self._session.add(RawRecordModel(**_raw_values(raw_record)))
        # Evidence must exist as PENDING before the caller attempts normalization.
        self._session.flush()

    def get_original_for_match(self, match_id: str) -> RawRecord | None:
        """Return original evidence whose observation still agrees with the match."""
        model = self._session.scalar(
            select(RawRecordModel)
            .join(MatchObservationModel, MatchObservationModel.raw_record_id == RawRecordModel.id)
            .join(MatchModel, MatchModel.id == MatchObservationModel.match_id)
            .where(
                MatchModel.id == match_id,
                MatchObservationModel.observed_content_sha256 == MatchModel.content_sha256,
                MatchObservationModel.ingestion_id == RawRecordModel.ingestion_id,
                RawRecordModel.record_type == "MATCH",
                RawRecordModel.disposition == "NORMALIZED",
            )
            .order_by(RawRecordModel.fetched_at_ms, RawRecordModel.id)
            .limit(1)
        )
        if model is None:
            return None
        return RawRecord(
            id=model.id,
            ingestion_id=model.ingestion_id,
            ordinal=model.ordinal,
            record_type=model.record_type,
            source_key=model.source_key,
            payload_json=model.payload_json,
            payload_sha256=model.payload_sha256,
            fetched_at_ms=model.fetched_at_ms,
            disposition=model.disposition,
            disposed_at_ms=model.disposed_at_ms,
        )

    def set_disposition(self, raw_record_id: str, disposition: str, *, disposed_at_ms: int) -> None:
        """Apply the database-guarded terminal disposition transition."""
        self._ensure_writable()
        statement = (
            update(RawRecordModel)
            .where(RawRecordModel.id == raw_record_id)
            .values(disposition=disposition, disposed_at_ms=disposed_at_ms)
        )
        result = self._session.execute(statement)
        if not isinstance(result, CursorResult) or result.rowcount != 1:
            raise ValueError("raw record was not found")

    def _ensure_writable(self) -> None:
        if self._read_only:
            raise RuntimeError(_READ_ONLY_MESSAGE)


def _raw_values(raw_record: RawRecord) -> dict[str, object]:
    return {
        "id": raw_record.id,
        "ingestion_id": raw_record.ingestion_id,
        "ordinal": raw_record.ordinal,
        "record_type": raw_record.record_type,
        "source_key": raw_record.source_key,
        "payload_json": raw_record.payload_json,
        "payload_sha256": raw_record.payload_sha256,
        "fetched_at_ms": raw_record.fetched_at_ms,
        "disposition": raw_record.disposition,
        "disposed_at_ms": raw_record.disposed_at_ms,
    }
