"""Safe, character-aligned projection models for the in-app viewer and OBS."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sf6viewer.infrastructure.db.models import MatchModel, ProfileSnapshotModel


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


def _normalized_character(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value.strip()


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
