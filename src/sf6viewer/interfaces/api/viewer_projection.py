"""Safe, character-aligned projection models for the in-app viewer and OBS."""

from collections.abc import Mapping
from threading import Lock
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from sf6viewer.infrastructure.db.models import MatchModel, ProfileSnapshotModel

MatchResult = Literal["WIN", "LOSE", "DRAW"]


class ViewerApiModel(BaseModel):
    """Strict immutable base for viewer-only response sections."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ObsViewerProfile(ViewerApiModel):
    """Display identity and rating fields aligned to one active character."""

    display_name: str | None
    character: str | None
    rank_name: str | None
    mr: int | None
    lp: int | None


class ObsSession(ViewerApiModel):
    """MR movement and decisive-match count since the effective process boundary."""

    started_at_ms: int
    boundary_kind: Literal["APP_START", "MATCH_RESET"]
    baseline_mr: int | None
    current_mr: int | None
    delta: int | None
    decisive_matches: int = Field(ge=0)


class ObsStreak(ViewerApiModel):
    """Current uninterrupted decisive result streak."""

    result: Literal["WIN", "LOSE"]
    count: int = Field(ge=1)


class ObsMatchupSummary(ViewerApiModel):
    """Decisive results grouped by opponent character."""

    character: str
    wins: int = Field(ge=0)
    losses: int = Field(ge=0)
    total: int = Field(ge=0)


class ObsMrPoint(ViewerApiModel):
    """One safe, chronological match-backed MR observation."""

    match_id: str
    occurred_at_ms: int
    mr: int = Field(ge=0)
    opponent_name: str
    opponent_character: str
    result: Literal["WIN", "LOSE", "DRAW"]


class ViewerSessionTracker:
    """Track immutable per-character MR baselines for one API process."""

    def __init__(
        self,
        *,
        started_at_ms: int,
        startup_baselines: Mapping[str, int],
    ) -> None:
        self._lock = Lock()
        self._boundary_at_ms = started_at_ms
        self._boundary_kind: Literal["APP_START", "MATCH_RESET"] = "APP_START"
        self._baselines = dict(startup_baselines)

    @classmethod
    def seeded_from(
        cls,
        session: Session,
        *,
        started_at_ms: int,
        reset_at_ms: int,
    ) -> "ViewerSessionTracker":
        """Snapshot the latest visible non-null MR for every known character."""

        recency_rank = func.row_number().over(
            partition_by=MatchModel.my_character,
            order_by=(MatchModel.occurred_at_ms.desc(), MatchModel.id.desc()),
        )
        ranked_matches = (
            select(
                MatchModel.my_character.label("character"),
                MatchModel.my_mr.label("mr"),
                recency_rank.label("recency_rank"),
            )
            .where(
                MatchModel.account_id == 1,
                MatchModel.occurred_at_ms > reset_at_ms,
                MatchModel.my_mr.is_not(None),
            )
            .subquery()
        )
        matches = session.execute(
            select(ranked_matches.c.character, ranked_matches.c.mr)
            .where(ranked_matches.c.recency_rank == 1)
            .order_by(ranked_matches.c.character.asc())
        ).all()
        baselines: dict[str, int] = {}
        for raw_character, mr in matches:
            character = _normalized_character(raw_character)
            if character is not None and character not in baselines:
                assert mr is not None
                baselines[character] = mr
        return cls(started_at_ms=started_at_ms, startup_baselines=baselines)

    def project(
        self,
        session: Session,
        *,
        active_character: str | None,
        reset_at_ms: int,
    ) -> ObsSession:
        """Project current session movement while serializing baseline transitions."""

        with self._lock:
            if reset_at_ms > self._boundary_at_ms:
                self._boundary_at_ms = reset_at_ms
                self._boundary_kind = "MATCH_RESET"
                self._baselines.clear()

            character = _normalized_character(active_character)
            if character is None:
                return self._response(
                    baseline_mr=None,
                    current_mr=None,
                    decisive_matches=0,
                )

            criteria = (
                MatchModel.account_id == 1,
                MatchModel.my_character == character,
                MatchModel.occurred_at_ms > self._boundary_at_ms,
            )
            if character not in self._baselines:
                oldest = session.scalar(
                    select(MatchModel)
                    .where(*criteria, MatchModel.my_mr.is_not(None))
                    .order_by(MatchModel.occurred_at_ms.asc(), MatchModel.id.asc())
                    .limit(1)
                )
                if oldest is not None:
                    assert oldest.my_mr is not None
                    self._baselines[character] = oldest.my_mr

            latest = session.scalar(
                select(MatchModel)
                .where(*criteria, MatchModel.my_mr.is_not(None))
                .order_by(MatchModel.occurred_at_ms.desc(), MatchModel.id.desc())
                .limit(1)
            )
            baseline_mr = self._baselines.get(character)
            current_mr = latest.my_mr if latest is not None else baseline_mr
            decisive_matches = int(
                session.scalar(
                    select(func.count())
                    .select_from(MatchModel)
                    .where(*criteria, MatchModel.result.in_(("WIN", "LOSE")))
                )
                or 0
            )
            return self._response(
                baseline_mr=baseline_mr,
                current_mr=current_mr,
                decisive_matches=decisive_matches,
            )

    def _response(
        self,
        *,
        baseline_mr: int | None,
        current_mr: int | None,
        decisive_matches: int,
    ) -> ObsSession:
        delta = (
            current_mr - baseline_mr
            if current_mr is not None and baseline_mr is not None
            else None
        )
        return ObsSession(
            started_at_ms=self._boundary_at_ms,
            boundary_kind=self._boundary_kind,
            baseline_mr=baseline_mr,
            current_mr=current_mr,
            delta=delta,
            decisive_matches=decisive_matches,
        )


def _normalized_character(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value.strip()


def build_streak(
    session: Session,
    *,
    active_character: str | None,
    reset_at_ms: int,
    chunk_size: int = 100,
) -> ObsStreak | None:
    """Read the newest uninterrupted decisive run without imposing a streak cap."""

    character = _normalized_character(active_character)
    if character is None:
        return None

    streak_result: Literal["WIN", "LOSE"] | None = None
    count = 0
    cursor: tuple[int, str] | None = None

    while True:
        statement = select(MatchModel.result, MatchModel.occurred_at_ms, MatchModel.id).where(
            MatchModel.account_id == 1,
            MatchModel.occurred_at_ms > reset_at_ms,
            MatchModel.my_character == character,
        )
        if cursor is not None:
            occurred_at_ms, match_id = cursor
            statement = statement.where(
                or_(
                    MatchModel.occurred_at_ms < occurred_at_ms,
                    and_(
                        MatchModel.occurred_at_ms == occurred_at_ms,
                        MatchModel.id < match_id,
                    ),
                )
            )
        rows = session.execute(
            statement.order_by(MatchModel.occurred_at_ms.desc(), MatchModel.id.desc()).limit(
                chunk_size
            )
        ).all()
        if not rows:
            break

        for raw_result, _, _ in rows:
            if raw_result not in ("WIN", "LOSE"):
                return (
                    ObsStreak(result=streak_result, count=count)
                    if streak_result is not None
                    else None
                )
            result = cast(Literal["WIN", "LOSE"], raw_result)
            if streak_result is None:
                streak_result = result
            elif result != streak_result:
                return ObsStreak(result=streak_result, count=count)
            count += 1

        if len(rows) < chunk_size:
            break
        cursor = (rows[-1].occurred_at_ms, rows[-1].id)

    return (
        ObsStreak(result=streak_result, count=count) if streak_result is not None else None
    )


def build_matchups(
    session: Session,
    *,
    active_character: str | None,
    reset_at_ms: int,
    limit: int = 100,
) -> tuple[ObsMatchupSummary, ...]:
    """Aggregate the newest decisive window by opponent character."""

    character = _normalized_character(active_character)
    if character is None:
        return ()

    rows = session.execute(
        select(MatchModel.opponent_character, MatchModel.result)
        .where(
            MatchModel.account_id == 1,
            MatchModel.occurred_at_ms > reset_at_ms,
            MatchModel.my_character == character,
            MatchModel.result.in_(("WIN", "LOSE")),
        )
        .order_by(MatchModel.occurred_at_ms.desc(), MatchModel.id.desc())
        .limit(limit)
    ).all()
    counts: dict[str, list[int]] = {}
    for opponent_character, result in rows:
        wins_losses = counts.setdefault(opponent_character, [0, 0])
        wins_losses[0 if result == "WIN" else 1] += 1

    summaries = (
        ObsMatchupSummary(
            character=opponent_character,
            wins=wins_losses[0],
            losses=wins_losses[1],
            total=sum(wins_losses),
        )
        for opponent_character, wins_losses in counts.items()
    )
    return tuple(sorted(summaries, key=lambda summary: (-summary.total, summary.character)))


def build_mr_history(
    session: Session,
    *,
    active_character: str | None,
    reset_at_ms: int,
    limit: int = 100,
) -> tuple[ObsMrPoint, ...]:
    """Project only safe fields from the newest non-null MR observations."""

    character = _normalized_character(active_character)
    if character is None:
        return ()

    rows = session.execute(
        select(
            MatchModel.id,
            MatchModel.occurred_at_ms,
            MatchModel.my_mr,
            MatchModel.opponent_name,
            MatchModel.opponent_character,
            MatchModel.result,
        )
        .where(
            MatchModel.account_id == 1,
            MatchModel.occurred_at_ms > reset_at_ms,
            MatchModel.my_character == character,
            MatchModel.my_mr.is_not(None),
        )
        .order_by(MatchModel.occurred_at_ms.desc(), MatchModel.id.desc())
        .limit(limit)
    ).all()
    return tuple(
        ObsMrPoint(
            match_id=match_id,
            occurred_at_ms=occurred_at_ms,
            mr=cast(int, mr),
            opponent_name=opponent_name,
            opponent_character=opponent_character,
            result=cast(MatchResult, result),
        )
        for match_id, occurred_at_ms, mr, opponent_name, opponent_character, result in reversed(
            rows
        )
    )


def build_viewer_profile(
    *,
    latest_profile: ProfileSnapshotModel | None,
    active_character: str | None,
    latest_character_match: MatchModel | None,
) -> ObsViewerProfile | None:
    """Build one profile without mixing rating fields from different characters."""

    if latest_profile is None and latest_character_match is None:
        return None

    character = _normalized_character(active_character)
    matching_profile = (
        latest_profile
        if latest_profile is not None
        and character is not None
        and _normalized_character(latest_profile.character) == character
        else None
    )

    rank_name = matching_profile.rank_name if matching_profile is not None else None
    if latest_character_match is not None:
        mr = latest_character_match.my_mr
        lp = latest_character_match.my_lp
    elif matching_profile is not None:
        mr = matching_profile.mr
        lp = matching_profile.lp
    else:
        mr = None
        lp = None

    return ObsViewerProfile(
        display_name=latest_profile.display_name if latest_profile is not None else None,
        character=character,
        rank_name=rank_name,
        mr=mr,
        lp=lp,
    )
