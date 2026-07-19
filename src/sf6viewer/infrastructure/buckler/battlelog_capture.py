"""Buckler ranked-battlelog capture and strict raw-payload normalization."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from datetime import datetime
from zoneinfo import ZoneInfo

from playwright.sync_api import Browser, BrowserContext, sync_playwright

from sf6viewer.application.services.raw_collection import (
    CollectedRawMatch,
    JsonValue,
    NormalizedMatch,
)
from sf6viewer.domain.errors import DomainError, error_from_code
from sf6viewer.domain.match import MatchFacts
from sf6viewer.infrastructure.auth.dpapi_vault import AuthSession
from sf6viewer.infrastructure.buckler.browser_capture import (
    launch_visible_system_browser,
    require_collectable_response,
)

_BATTLELOG_URL = "https://www.streetfighter.com/6/buckler/ko-kr/profile/{user_code}/battlelog/rank"
_PAGE_TIMEOUT_MS = 45_000
_KST = ZoneInfo("Asia/Seoul")
_RATING_PATTERN = re.compile(r"^([0-9][0-9,]*)\s*(MR|LP)$")
_SOURCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")


class BucklerBattlelogCapture:
    """Capture battle-log DOM evidence from a DPAPI-restored session."""

    def __init__(self, clock: Callable[[], int]) -> None:
        self._clock = clock

    def capture(self, session: AuthSession, *, limit: int = 20) -> list[CollectedRawMatch]:
        """Return raw immutable entries without parsing dates, ratings, or results."""
        if not isinstance(session, AuthSession):
            raise error_from_code("SESSION.MISSING")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise error_from_code("VALIDATION.LIMIT")
        browser: Browser | None = None
        context: BrowserContext | None = None
        try:
            storage_state = _storage_state(session.storage_state)
            with sync_playwright() as playwright:
                browser = launch_visible_system_browser(playwright)
                context = browser.new_context(
                    storage_state=storage_state,
                    locale="ko-KR",
                    timezone_id="Asia/Seoul",
                )
                page = context.new_page()
                response = page.goto(
                    _BATTLELOG_URL.format(user_code=session.user_code.value),
                    wait_until="domcontentloaded",
                    timeout=_PAGE_TIMEOUT_MS,
                )
                require_collectable_response(response)
                entries = page.locator("[class*='battle_data_battlelog__list'] > li").evaluate_all(
                    _ENTRY_EXTRACTION_SCRIPT
                )
                if not isinstance(entries, list):
                    raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
                fetched_at_ms = self._clock()
                return [
                    _collected_entry(entry, ordinal, fetched_at_ms)
                    for ordinal, entry in enumerate(entries[:limit])
                ]
        except Exception as error:
            if isinstance(error, DomainError):
                raise error
            raise error_from_code("UPSTREAM.UNAVAILABLE") from None
        finally:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass


def normalize_battlelog_match(
    payload: Mapping[str, JsonValue], *, account_user_code: str, own_display_name: str
) -> NormalizedMatch:
    """Strictly interpret one stored battle-log entry only after raw insertion."""
    if not isinstance(account_user_code, str) or not account_user_code.strip():
        raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
    if not isinstance(own_display_name, str) or not own_display_name.strip():
        raise error_from_code("DATA.IDENTITY_GROUP_INCOMPLETE")
    source_id = _required_source_id(payload.get("source_id"))
    player1 = _player(payload.get("player1"))
    player2 = _player(payload.get("player2"))
    mine, opponent = _assign_players(player1, player2, own_display_name)
    result = _result_for_mine(mine, opponent)
    original_date = _required_text(payload.get("date_text"))
    occurred_at_ms = _occurred_at_ms(payload.get("date_datetime"), original_date)
    my_mr, my_lp = _rating(mine["rating"])
    opponent_mr, opponent_lp = _rating(opponent["rating"])
    return NormalizedMatch(
        facts=MatchFacts(
            account_user_code=account_user_code,
            original_date=original_date,
            occurred_at_ms=occurred_at_ms,
            my_name=own_display_name,
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
    )


def _collected_entry(entry: object, ordinal: int, fetched_at_ms: int) -> CollectedRawMatch:
    if not isinstance(entry, Mapping) or any(not isinstance(key, str) for key in entry):
        raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
    source_id = entry.get("source_id")
    raw_payload = dict(entry)
    return CollectedRawMatch(
        raw_payload=raw_payload,
        ordinal=ordinal,
        fetched_at_ms=fetched_at_ms,
        source_key=source_id if isinstance(source_id, str) and source_id.strip() else None,
    )


def _storage_state(value: bytes) -> dict[str, object]:
    try:
        decoded = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise error_from_code("SESSION.EXPIRED") from None
    if not isinstance(decoded, dict):
        raise error_from_code("SESSION.EXPIRED")
    return decoded


def _required_source_id(value: object) -> str:
    if not isinstance(value, str) or _SOURCE_ID_PATTERN.fullmatch(value.strip()) is None:
        raise error_from_code("DATA.IDENTITY_GROUP_INCOMPLETE")
    return value.strip()


def _player(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
    required = {"name", "character", "rating", "class_name"}
    if set(value) != required or any(not isinstance(key, str) for key in value):
        raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
    return dict(value)


def _assign_players(
    player1: dict[str, object], player2: dict[str, object], own_display_name: str
) -> tuple[dict[str, object], dict[str, object]]:
    first_is_mine = player1["name"] == own_display_name
    second_is_mine = player2["name"] == own_display_name
    if first_is_mine == second_is_mine:
        raise error_from_code("DATA.IDENTITY_GROUP_INCOMPLETE")
    return (player1, player2) if first_is_mine else (player2, player1)


def _result_for_mine(mine: Mapping[str, object], opponent: Mapping[str, object]) -> str:
    mine_class = _required_text(mine["class_name"])
    opponent_class = _required_text(opponent["class_name"])
    if "battle_data_win" in mine_class and "battle_data_lose" in opponent_class:
        return "WIN"
    if "battle_data_lose" in mine_class and "battle_data_win" in opponent_class:
        return "LOSE"
    if "battle_data_draw" in mine_class or "battle_data_draw" in opponent_class:
        return "DRAW"
    raise error_from_code("UPSTREAM.CONTRACT_CHANGED")


def _rating(value: object) -> tuple[int | None, int | None]:
    text = _required_text(value)
    matched = _RATING_PATTERN.fullmatch(text)
    if matched is None:
        raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
    rating = int(matched.group(1).replace(",", ""))
    return (rating, None) if matched.group(2) == "MR" else (None, rating)


def _occurred_at_ms(datetime_value: object, original_date: str) -> int:
    if not isinstance(datetime_value, str) or not datetime_value.strip():
        raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
    source = datetime_value.strip()
    try:
        parsed = datetime.fromisoformat(source.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_KST)
    except ValueError:
        raise error_from_code("UPSTREAM.CONTRACT_CHANGED") from None
    if not original_date:
        raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
    return int(parsed.timestamp() * 1_000)


def _required_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
    return value.strip()


_ENTRY_EXTRACTION_SCRIPT = """
(entries) => entries.map((entry) => {
  const text = (root, selector) => root.querySelector(selector)?.textContent?.trim() || null;
  const player = (selector) => {
    const root = entry.querySelector(selector);
    return {
      name: text(root || entry, '[class*="battle_data_name"]'),
      character: root?.querySelector('[class*="battle_data_character"] img')?.getAttribute('alt') || null,
      rating: text(root || entry, '[class*="battle_data_lp"]'),
      class_name: root?.getAttribute('class') || null,
    };
  };
  const date = entry.querySelector('[class*="battle_data_date"]');
  return {
    source_id: entry.getAttribute('data-battle-id') || entry.getAttribute('data-match-id') || entry.getAttribute('data-id'),
    date_text: date?.textContent?.trim() || null,
    date_datetime: date?.querySelector('time')?.getAttribute('datetime') || date?.getAttribute('datetime') || null,
    player1: player('[class*="battle_data_player1"]'),
    player2: player('[class*="battle_data_player2"]'),
    outer_html: entry.outerHTML,
  };
})
"""
