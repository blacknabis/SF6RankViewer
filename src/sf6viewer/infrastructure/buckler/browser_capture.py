"""Shared visible-browser launch and response validation for Buckler capture."""

from playwright.sync_api import Browser, Playwright, Response

from sf6viewer.domain.errors import error_from_code


def launch_visible_system_browser(playwright: Playwright) -> Browser:
    """Use a normal installed browser; Buckler rejects the headless capture flow."""
    for channel in ("chrome", "msedge"):
        try:
            return playwright.chromium.launch(headless=False, channel=channel)
        except Exception:
            continue
    return playwright.chromium.launch(headless=False)


def require_collectable_response(response: Response | None) -> None:
    """Fail closed instead of treating a Buckler error page as an empty result."""
    if response is None or response.status >= 500:
        raise error_from_code("UPSTREAM.UNAVAILABLE")
    if response.status in {403, 429}:
        raise error_from_code("UPSTREAM.RATE_LIMITED")
    if response.status >= 400:
        raise error_from_code("UPSTREAM.UNAVAILABLE")
