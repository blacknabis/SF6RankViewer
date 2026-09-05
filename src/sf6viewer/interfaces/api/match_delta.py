"""Conservative MR estimates from adjacent, compatible live replay observations."""

from typing import Literal, cast

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ColumnElement

from sf6viewer.infrastructure.db.models import (
    IngestionRunModel,
    MatchModel,
    MatchObservationModel,
    RawRecordModel,
)

MrDeltaStatus = Literal["estimated", "pending", "unavailable"]
MatchEvidenceRow = tuple[MatchModel, MatchModel | None, bool, bool]


def estimate_match_delta(
    current: MatchModel, following: MatchModel | None, *, witnessed: bool, ambiguous: bool,
) -> tuple[int | None, MrDeltaStatus]:
    """Treat replay MR as match-start MR, withholding incomplete or conflicting data."""
    if current.my_mr is None or current.result not in {"WIN", "LOSE"} or ambiguous:
        return None, "unavailable"
    if following is None:
        return None, "pending"
    if following.my_mr is None or not witnessed:
        return None, "unavailable"
    delta = following.my_mr - current.my_mr
    if (current.result == "WIN" and delta < 0) or (current.result == "LOSE" and delta > 0):
        return None, "unavailable"
    # Buckler exposes no explicit post-match MR or ranked-phase identifier here.
    return delta, "estimated"


def _same_time_peer(model: type[MatchModel]) -> ColumnElement[bool]:
    peer = aliased(MatchModel)
    return select(peer.id).where(
        peer.account_id == model.account_id,
        peer.my_character == model.my_character,
        peer.occurred_at_ms == model.occurred_at_ms,
        peer.id != model.id,
    ).correlate(model).exists()


def matches_with_mr_evidence(reset_at_ms: int) -> Select[MatchEvidenceRow]:
    """Select one row per visible match; observation multiplicity never affects paging."""
    current = aliased(MatchModel, name="current_match")
    following = aliased(MatchModel, name="following_match")
    candidate = aliased(MatchModel, name="next_candidate")
    following_id = select(candidate.id).where(
        candidate.account_id == current.account_id,
        candidate.my_character == current.my_character,
        candidate.occurred_at_ms > current.occurred_at_ms,
    ).order_by(candidate.occurred_at_ms).limit(1).correlate(current).scalar_subquery()

    current_observation = aliased(MatchObservationModel, name="current_observation")
    next_observation = aliased(MatchObservationModel, name="next_observation")
    current_raw = aliased(RawRecordModel, name="current_raw")
    next_raw = aliased(RawRecordModel, name="next_raw")
    observed_next = aliased(MatchModel, name="observed_next")
    witnesses = (
        select(observed_next.id)
        .select_from(current_observation)
        .join(current_raw, and_(
            current_raw.id == current_observation.raw_record_id,
            current_raw.ingestion_id == current_observation.ingestion_id,
        ))
        .join(IngestionRunModel, IngestionRunModel.id == current_raw.ingestion_id)
        .join(next_raw, and_(
            next_raw.ingestion_id == current_raw.ingestion_id,
            next_raw.ordinal == current_raw.ordinal - 1,
        ))
        .join(next_observation, and_(
            next_observation.raw_record_id == next_raw.id,
            next_observation.ingestion_id == next_raw.ingestion_id,
        ))
        .join(observed_next, observed_next.id == next_observation.match_id)
        .where(
            current_observation.match_id == current.id,
            current_observation.observed_content_sha256 == current.content_sha256,
            next_observation.observed_content_sha256 == observed_next.content_sha256,
            IngestionRunModel.account_id == current.account_id,
            IngestionRunModel.kind == "LIVE",
            IngestionRunModel.state.in_({"COMPLETED", "COMPLETED_WITH_WARNINGS"}),
            IngestionRunModel.parser_version == "buckler-battlelog-v3",
            current_raw.record_type == "MATCH",
            next_raw.record_type == "MATCH",
            current_raw.disposition.in_({"NORMALIZED", "DUPLICATE"}),
            next_raw.disposition.in_({"NORMALIZED", "DUPLICATE"}),
            observed_next.account_id == current.account_id,
        )
        .correlate(current, following)
    )
    # Raw ordinals retain the upstream newest-first sequence. A literal adjacent
    # pair proves co-observation; separate captures cannot bridge an unknown gap.
    witnessed = and_(
        witnesses.where(observed_next.id == following.id).exists(),
        ~witnesses.where(observed_next.id != following.id).exists(),
    )
    ambiguous = or_(_same_time_peer(current), _same_time_peer(following))
    statement = (
        select(current, following, witnessed, ambiguous)
        .outerjoin(following, following.id == following_id)
        .where(current.account_id == 1, current.occurred_at_ms > reset_at_ms)
        .order_by(current.occurred_at_ms.desc(), current.id.desc())
    )
    # SQLAlchemy types do not express that the outer-joined entity may be absent.
    return cast(Select[MatchEvidenceRow], statement)
