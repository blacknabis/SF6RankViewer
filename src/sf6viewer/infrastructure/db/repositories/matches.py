"""SQLAlchemy repository for immutable normalized matches."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from sf6viewer.application.ports.repositories import (
    InsertOutcome,
    MatchRecord,
    ObservationRecord,
)
from sf6viewer.infrastructure.db.models.match_observations import MatchObservationModel
from sf6viewer.infrastructure.db.models.matches import MatchModel

_READ_ONLY_MESSAGE = "read unit of work is read-only"


class SqlAlchemyMatchRepository:
    """Persists immutable matches and only compatible observations."""

    def __init__(self, session: Session, *, read_only: bool = False) -> None:
        self._session = session
        self._read_only = read_only

    def insert_or_compare(self, match: MatchRecord) -> InsertOutcome:
        """Insert, or compare against, the durable row for one identity key."""
        self._ensure_writable()
        statement = insert(MatchModel).values(**_match_values(match)).on_conflict_do_nothing(
            index_elements=["account_id", "identity_key"]
        )
        result = self._session.execute(statement)
        if result.rowcount == 1:
            return InsertOutcome.NEW

        existing = self._session.scalar(
            select(MatchModel).where(
                MatchModel.account_id == match.account_id,
                MatchModel.identity_key == match.identity_key,
            )
        )
        if existing is None:
            raise RuntimeError("match identity conflict did not expose a persisted match")
        if existing.content_sha256 == match.content_sha256:
            return InsertOutcome.SAME_CONTENT
        return InsertOutcome.IDENTITY_COLLISION

    def add_observation(self, observation: ObservationRecord) -> None:
        """Add an observation only when its hash matches the persisted match."""
        self._ensure_writable()
        match = self._session.get(MatchModel, observation.match_id)
        if match is None or match.content_sha256 != observation.observed_content_sha256:
            raise ValueError("observation content does not match a persisted match")
        self._session.add(MatchObservationModel(**_observation_values(observation)))

    def get_by_identity(self, account_id: int, identity_key: str) -> MatchRecord | None:
        """Return the canonical match record for an account-scoped identity key."""
        model = self._session.scalar(
            select(MatchModel).where(
                MatchModel.account_id == account_id,
                MatchModel.identity_key == identity_key,
            )
        )
        return None if model is None else _to_record(model)

    def _ensure_writable(self) -> None:
        if self._read_only:
            raise RuntimeError(_READ_ONLY_MESSAGE)


def _match_values(match: MatchRecord) -> dict[str, object]:
    return {
        "id": match.id,
        "account_id": match.account_id,
        "identity_key": match.identity_key,
        "identity_kind": match.identity_kind,
        "content_sha256": match.content_sha256,
        "occurred_at_ms": match.occurred_at_ms,
        "occurred_at_source": match.occurred_at_source,
        "my_character": match.my_character,
        "my_mr": match.my_mr,
        "my_lp": match.my_lp,
        "opponent_name": match.opponent_name,
        "opponent_character": match.opponent_character,
        "opponent_mr": match.opponent_mr,
        "opponent_lp": match.opponent_lp,
        "result": match.result,
        "created_at_ms": match.created_at_ms,
    }


def _observation_values(observation: ObservationRecord) -> dict[str, object]:
    return {
        "id": observation.id,
        "match_id": observation.match_id,
        "raw_record_id": observation.raw_record_id,
        "ingestion_id": observation.ingestion_id,
        "observed_content_sha256": observation.observed_content_sha256,
        "observed_at_ms": observation.observed_at_ms,
    }


def _to_record(model: MatchModel) -> MatchRecord:
    return MatchRecord(
        id=model.id,
        account_id=model.account_id,
        identity_key=model.identity_key,
        identity_kind=model.identity_kind,
        content_sha256=model.content_sha256,
        occurred_at_ms=model.occurred_at_ms,
        occurred_at_source=model.occurred_at_source,
        my_character=model.my_character,
        my_mr=model.my_mr,
        my_lp=model.my_lp,
        opponent_name=model.opponent_name,
        opponent_character=model.opponent_character,
        opponent_mr=model.opponent_mr,
        opponent_lp=model.opponent_lp,
        result=model.result,
        created_at_ms=model.created_at_ms,
    )
