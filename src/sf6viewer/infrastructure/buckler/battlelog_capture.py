"""Buckler ranked replay capture from stable Next.js page data."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import cast
from zoneinfo import ZoneInfo

from playwright.sync_api import Page

from sf6viewer.application.services.raw_collection import (
    CollectedRawMatch,
    JsonValue,
    NormalizedMatch,
)
from sf6viewer.domain.errors import DomainError, error_from_code
from sf6viewer.domain.match import MatchFacts
from sf6viewer.infrastructure.auth.dpapi_vault import AuthSession
from sf6viewer.infrastructure.buckler.browser_capture import (
    PersistentBucklerBrowser,
    require_collectable_response,
)

_BATTLELOG_URL = "https://www.streetfighter.com/6/buckler/ko-kr/profile/{user_code}/battlelog/rank"
_PAGE_TIMEOUT_MS = 45_000
_KST = ZoneInfo("Asia/Seoul")
_SOURCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")


class BucklerBattlelogCapture:
    """Capture exact replay objects before interpreting any match fields."""

    def __init__(self, clock: Callable[[], int], browser: PersistentBucklerBrowser) -> None:
        self._clock = clock
        self._browser = browser

    def capture(self, session: AuthSession, *, limit: int = 20) -> list[CollectedRawMatch]:
        if not isinstance(session, AuthSession):
            raise error_from_code("SESSION.MISSING")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise error_from_code("VALIDATION.LIMIT")
        try:
            storage_state = _storage_state(session.storage_state)
            user_code = session.user_code.value

            def capture_page(page: Page) -> list[CollectedRawMatch]:
                response = page.goto(
                    _BATTLELOG_URL.format(user_code=user_code),
                    wait_until="domcontentloaded",
                    timeout=_PAGE_TIMEOUT_MS,
                )
                require_collectable_response(response)
                raw_next_data = page.locator("script#__NEXT_DATA__").text_content(
                    timeout=_PAGE_TIMEOUT_MS
                )
                replay_entries = _replay_entries(raw_next_data)
                fetched_at_ms = self._clock()
                return [
                    CollectedRawMatch(
                        raw_payload=entry,
                        ordinal=ordinal,
                        fetched_at_ms=fetched_at_ms,
                        source_key=_optional_source_id(entry.get("replay_id")),
                    )
                    for ordinal, entry in enumerate(replay_entries[:limit])
                ]

            return self._browser.run_with_recovery(
                user_code=user_code,
                storage_state=storage_state,
                operation=capture_page,
            )
        except Exception as error:
            if isinstance(error, DomainError):
                raise error
            raise error_from_code("UPSTREAM.UNAVAILABLE") from None


def normalize_battlelog_match(
    payload: Mapping[str, JsonValue], *, account_user_code: str, own_display_name: str
) -> NormalizedMatch:
    """Normalize one replay using its stable ID, timestamp, and player objects."""
    if not isinstance(account_user_code, str) or not account_user_code.strip():
        raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
    if not isinstance(own_display_name, str) or not own_display_name.strip():
        raise error_from_code("DATA.IDENTITY_GROUP_INCOMPLETE")

    source_id = _required_source_id(payload.get("replay_id"))
    player1 = _replay_player(payload.get("player1_info"))
    player2 = _replay_player(payload.get("player2_info"))
    mine, opponent = _assign_players(
        player1, player2, account_user_code.strip(), own_display_name.strip()
    )
    result = _result_for_mine(mine, opponent)
    occurred_at_ms, original_date = _uploaded_at(payload.get("uploaded_at"))
    my_mr, my_lp = _rating(mine)
    opponent_mr, opponent_lp = _rating(opponent)
    return NormalizedMatch(
        facts=MatchFacts(
            account_user_code=account_user_code.strip(),
            original_date=original_date,
            occurred_at_ms=occurred_at_ms,
            my_name=_required_text(mine["name"]),
            my_character=_required_text(mine["character"]),
            opponent_name=_required_text(opponent["name"]),
            opponent_character=_required_text(opponent["character"]),
            result=result,
            my_mr=my_mr,
            my_lp=my_lp,
            opponent_mr=opponent_mr,
            opponent_lp=opponent_lp,
        ),
        source_id=source_id,
        allow_legacy_profile_name=True,
    )


def _replay_entries(raw: str | None) -> list[Mapping[str, JsonValue]]:
    if not isinstance(raw, str):
        raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        raise error_from_code("UPSTREAM.CONTRACT_CHANGED") from None
    page_props = _mapping(_mapping(decoded).get("props")).get("pageProps")
    replay_list = _mapping(page_props).get("replay_list")
    if not isinstance(replay_list, Sequence) or isinstance(replay_list, (str, bytes)):
        raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
    return [_json_mapping(item) for item in replay_list]


def _replay_player(value: object) -> dict[str, object]:
    info = _mapping(value)
    player = _mapping(info.get("player"))
    return {
        "name": _required_text(player.get("fighter_id")),
        "short_id": _required_nonnegative_int(player.get("short_id")),
        "character": _required_text(
            info.get("playing_character_name") or info.get("character_name")
        ),
        "master_rating": _required_rating_int(info.get("master_rating")),
        "league_point": _required_rating_int(info.get("league_point")),
        "round_results": _round_results(info.get("round_results")),
    }


def _assign_players(
    player1: dict[str, object],
    player2: dict[str, object],
    account_user_code: str,
    own_display_name: str,
) -> tuple[dict[str, object], dict[str, object]]:
    first_is_mine = str(player1["short_id"]).zfill(10) == account_user_code
    second_is_mine = str(player2["short_id"]).zfill(10) == account_user_code
    if first_is_mine != second_is_mine:
        return (player1, player2) if first_is_mine else (player2, player1)

    first_name_matches = player1["name"] == own_display_name
    second_name_matches = player2["name"] == own_display_name
    if first_name_matches == second_name_matches:
        raise error_from_code("DATA.IDENTITY_GROUP_INCOMPLETE")
    return (player1, player2) if first_name_matches else (player2, player1)


def _result_for_mine(mine: Mapping[str, object], opponent: Mapping[str, object]) -> str:
    mine_rounds = _round_results(mine.get("round_results"))
    opponent_rounds = _round_results(opponent.get("round_results"))
    # Buckler uses zero for a lost round and positive codes for win variants
    # (for example, normal and perfect wins use different positive codes).
    mine_wins = sum(result > 0 for result in mine_rounds)
    opponent_wins = sum(result > 0 for result in opponent_rounds)
    if mine_wins > opponent_wins:
        return "WIN"
    if mine_wins < opponent_wins:
        return "LOSE"
    if mine_wins > 0:
        return "DRAW"
    raise error_from_code("UPSTREAM.CONTRACT_CHANGED")


def _rating(player: Mapping[str, object]) -> tuple[int | None, int | None]:
    master_rating = _optional_nonnegative_int(player.get("master_rating"))
    league_point = _optional_nonnegative_int(player.get("league_point"))
    return (
        (master_rating, None)
        if master_rating is not None and master_rating > 0
        else (None, league_point)
    )


def _uploaded_at(value: object) -> tuple[int, str]:
    timestamp_seconds = _required_nonnegative_int(value)
    observed = datetime.fromtimestamp(timestamp_seconds, tz=_KST)
    return timestamp_seconds * 1_000, observed.isoformat()


def _storage_state(value: bytes) -> dict[str, object]:
    try:
        decoded = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise error_from_code("SESSION.EXPIRED") from None
    if not isinstance(decoded, dict):
        raise error_from_code("SESSION.EXPIRED")
    return decoded


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
    return value


def _json_mapping(value: object) -> Mapping[str, JsonValue]:
    mapping = _mapping(value)
    # CollectedRawMatch recursively validates and freezes every nested JSON value.
    return cast(Mapping[str, JsonValue], dict(mapping))


def _round_results(value: object) -> tuple[int, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
    results = tuple(value)
    if not results or any(type(item) is not int or item < 0 for item in results):
        raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
    return results


def _optional_source_id(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _required_source_id(value: object) -> str:
    if not isinstance(value, str) or _SOURCE_ID_PATTERN.fullmatch(value.strip()) is None:
        raise error_from_code("DATA.IDENTITY_GROUP_INCOMPLETE")
    return value.strip()


def _required_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
    return value.strip()


def _required_nonnegative_int(value: object) -> int:
    if type(value) is not int or value < 0:
        raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
    return value


def _required_rating_int(value: object) -> int | None:
    if type(value) is not int or value < -1:
        raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
    return None if value == -1 else value


def _optional_nonnegative_int(value: object) -> int | None:
    if value is None:
        return None
    return _required_nonnegative_int(value)
