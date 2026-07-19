"""Shared visible-browser lifecycle and response validation for Buckler capture."""

from collections.abc import Callable
from contextlib import suppress
from typing import TypeVar, cast

from playwright._impl._api_structures import StorageState
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    Response,
    sync_playwright,
)

from sf6viewer.domain.errors import error_from_code

CaptureResult = TypeVar("CaptureResult")


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


class PersistentBucklerBrowser:
    """Keep one normal browser context for consecutive live collection cycles."""

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._user_code: str | None = None
        self._reset_requested = False

    def page_for(self, *, user_code: str, storage_state: dict[str, object]) -> Page:
        """Return the live page, recreating it only after account or browser changes."""
        if self._needs_restart(user_code):
            self.close()
            self._playwright = sync_playwright().start()
            self._browser = launch_visible_system_browser(self._playwright)
            self._context = self._browser.new_context(
                storage_state=cast(StorageState, storage_state),
                locale="ko-KR",
                timezone_id="Asia/Seoul",
            )
            self._page = self._context.new_page()
            self._user_code = user_code
        assert self._page is not None
        return self._page

    def run_with_recovery(
        self,
        *,
        user_code: str,
        storage_state: dict[str, object],
        operation: Callable[[Page], CaptureResult],
    ) -> CaptureResult:
        """Reopen a user-closed browser and retry the interrupted capture once."""
        for attempt in range(2):
            page = self.page_for(user_code=user_code, storage_state=storage_state)
            try:
                return operation(page)
            except Exception:
                if attempt > 0 or not self._browser_session_closed():
                    raise
                self.request_reset()
        raise RuntimeError("Browser recovery retry was exhausted.")

    def close(self) -> None:
        """Release the browser resources; repeated shutdown stays harmless."""
        for resource in (self._page, self._context, self._browser):
            if resource is None:
                continue
            with suppress(Exception):
                resource.close()
        if self._playwright is not None:
            with suppress(Exception):
                self._playwright.stop()
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._user_code = None
        self._reset_requested = False

    def request_reset(self) -> None:
        """Make the capture worker replace this context before its next request."""
        self._reset_requested = True

    def _needs_restart(self, user_code: str) -> bool:
        return (
            self._reset_requested
            or self._user_code != user_code
            or self._browser_session_closed()
        )

    def _browser_session_closed(self) -> bool:
        if self._browser is None or self._page is None:
            return True
        try:
            return not self._browser.is_connected() or self._page.is_closed()
        except Exception:
            return True
