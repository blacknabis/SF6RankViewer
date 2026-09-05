"""SQLAlchemy repository for immutable profile snapshots."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from sf6viewer.application.ports.repositories import ProfileSnapshotRecord
from sf6viewer.infrastructure.db.models.profile_snapshots import ProfileSnapshotModel

_READ_ONLY_MESSAGE = "read unit of work is read-only"


class SqlAlchemyProfileSnapshotRepository:
    """Persists profile projections without owning the surrounding transaction."""

    def __init__(self, session: Session, *, read_only: bool = False) -> None:
        self._session = session
        self._read_only = read_only

    def list_display_names(self, account_id: int) -> list[str]:
        """Return only distinct, nonempty names from this account's history."""
        names = self._session.scalars(
            select(ProfileSnapshotModel.display_name)
            .where(ProfileSnapshotModel.account_id == account_id)
            .distinct()
        )
        return [name for name in names if isinstance(name, str) and name.strip()]

    def add(self, snapshot: ProfileSnapshotRecord) -> None:
        """Add one profile observation linked to immutable raw evidence."""
        if self._read_only:
            raise RuntimeError(_READ_ONLY_MESSAGE)
        self._session.add(
            ProfileSnapshotModel(
                id=snapshot.id,
                account_id=snapshot.account_id,
                ingestion_id=snapshot.ingestion_id,
                raw_record_id=snapshot.raw_record_id,
                display_name=snapshot.display_name,
                character=snapshot.character,
                rank_name=snapshot.rank_name,
                mr=snapshot.mr,
                lp=snapshot.lp,
                observed_at_ms=snapshot.observed_at_ms,
            )
        )
