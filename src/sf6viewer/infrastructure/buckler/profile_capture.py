"""Authenticated Buckler profile capture with no persistent browser files."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping

from playwright.sync_api import Browser, BrowserContext, Playwright, sync_playwright

from sf6viewer.application.services.profile_collection import (
    CollectedRawProfile,
    JsonValue,
    NormalizedProfile,
)
from sf6viewer.domain.errors import DomainError, error_from_code
from sf6viewer.infrastructure.auth.dpapi_vault import AuthSession

_PROFILE_URL = "https://www.streetfighter.com/6/buckler/ko-kr/profile/{user_code}"
_PAGE_TIMEOUT_MS = 45_000


class BucklerProfileCapture:
    """Capture one profile page using only the DPAPI-restored storage state."""

    def __init__(self, clock: Callable[[], int]) -> None:
        self._clock = clock

    def capture(self, session: AuthSession) -> CollectedRawProfile:
        """Return page-props evidence; cookies and URLs never leave this adapter."""
        if not isinstance(session, AuthSession):
            raise error_from_code("SESSION.MISSING")
        browser: Browser | None = None
        context: BrowserContext | None = None
        try:
            storage_state = _storage_state(session.storage_state)
            with sync_playwright() as playwright:
                browser = _launch_visible_system_browser(playwright)
                context = browser.new_context(
                    storage_state=storage_state,
                    locale="ko-KR",
                    timezone_id="Asia/Seoul",
                )
                page = context.new_page()
                response = page.goto(
                    _PROFILE_URL.format(user_code=session.user_code.value),
                    wait_until="domcontentloaded",
                    timeout=_PAGE_TIMEOUT_MS,
                )
                if response is None or response.status >= 500:
                    raise error_from_code("UPSTREAM.UNAVAILABLE")
                if response.status in {403, 429}:
                    raise error_from_code("UPSTREAM.RATE_LIMITED")
                if response.status >= 400:
                    raise error_from_code("UPSTREAM.UNAVAILABLE")
                next_data = page.locator("script#__NEXT_DATA__").text_content(
                    timeout=_PAGE_TIMEOUT_MS
                )
                payload = _page_props(next_data)
                return CollectedRawProfile(
                    raw_payload=payload,
                    fetched_at_ms=self._clock(),
                    source_key=f"profile:{session.user_code.value}",
                )
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


def _launch_visible_system_browser(playwright: Playwright) -> Browser:
    """Use a normal installed browser; Buckler rejects the headless profile flow."""
    for channel in ("chrome", "msedge"):
        try:
            return playwright.chromium.launch(headless=False, channel=channel)
        except Exception:
            continue
    return playwright.chromium.launch(headless=False)


def normalize_profile(payload: Mapping[str, JsonValue]) -> NormalizedProfile:
    """Interpret only the documented profile-banner fields from saved evidence."""
    banner = _mapping(payload.get("fighter_banner_info"))
    personal_info = _mapping(banner.get("personal_info"))
    league_info = _mapping(banner.get("favorite_character_league_info"))
    rank_info = _mapping(league_info.get("league_rank_info"))
    return NormalizedProfile(
        display_name=_optional_text(personal_info.get("fighter_id")),
        character=_optional_text(banner.get("favorite_character_alpha")),
        rank_name=_optional_text(rank_info.get("league_rank_name")),
        mr=_optional_nonnegative_int(league_info.get("master_rating")),
        lp=_optional_nonnegative_int(league_info.get("league_point")),
    )


def _storage_state(value: bytes) -> dict[str, object]:
    try:
        decoded = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise error_from_code("SESSION.EXPIRED") from None
    if not isinstance(decoded, dict):
        raise error_from_code("SESSION.EXPIRED")
    return decoded


def _page_props(raw: str | None) -> Mapping[str, JsonValue]:
    if not isinstance(raw, str):
        raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        raise error_from_code("UPSTREAM.CONTRACT_CHANGED") from None
    if not isinstance(decoded, Mapping):
        raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
    props = _mapping(decoded.get("props"))
    page_props = props.get("pageProps")
    if not isinstance(page_props, Mapping):
        raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
    return page_props


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
    return value


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
    return value.strip()


def _optional_nonnegative_int(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
    return value
