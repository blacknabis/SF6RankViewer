"""SQLAlchemy repository for raw-normalization quarantine records."""

from __future__ import annotations

from sqlalchemy.orm import Session

from sf6viewer.application.ports.repositories import QuarantineRecord
from sf6viewer.infrastructure.db.models.quarantine_records import QuarantineRecordModel

_READ_ONLY_MESSAGE = "read unit of work is read-only"


class SqlAlchemyQuarantineRepository:
    """Persists open quarantine records without owning a transaction."""

    def __init__(self, session: Session, *, read_only: bool = False) -> None:
        self._session = session
        self._read_only = read_only

    def add(self, quarantine: QuarantineRecord) -> None:
        """Add one open quarantine row to the caller's transaction."""
        self._ensure_writable()
        self._session.add(QuarantineRecordModel(**_quarantine_values(quarantine)))

    def _ensure_writable(self) -> None:
        if self._read_only:
            raise RuntimeError(_READ_ONLY_MESSAGE)


def _quarantine_values(quarantine: QuarantineRecord) -> dict[str, object]:
    return {
        "id": quarantine.id,
        "raw_record_id": quarantine.raw_record_id,
        "account_id": quarantine.account_id,
        "reason_code": quarantine.reason_code,
        "field_errors_json": quarantine.field_errors_json,
        "status": quarantine.status,
        "created_at_ms": quarantine.created_at_ms,
        "resolved_at_ms": quarantine.resolved_at_ms,
        "resolution_match_id": quarantine.resolution_match_id,
    }
