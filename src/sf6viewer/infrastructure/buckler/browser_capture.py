"""Shared visible-browser lifecycle and response validation for Buckler capture."""

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, Response, sync_playwright

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


class PersistentBucklerBrowser:
    """Keep one normal browser context for consecutive live collection cycles."""

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._user_code: str | None = None

    def page_for(self, *, user_code: str, storage_state: dict[str, object]) -> Page:
        """Return the live page, recreating it only after account or browser changes."""
        if self._needs_restart(user_code):
            self.close()
            self._playwright = sync_playwright().start()
            self._browser = launch_visible_system_browser(self._playwright)
            self._context = self._browser.new_context(
                storage_state=storage_state,
                locale="ko-KR",
                timezone_id="Asia/Seoul",
            )
            self._page = self._context.new_page()
            self._user_code = user_code
        assert self._page is not None
        return self._page

    def close(self) -> None:
        """Release the browser resources; repeated shutdown stays harmless."""
        for resource in (self._page, self._context, self._browser):
            if resource is None:
                continue
            try:
                resource.close()
            except Exception:
                pass
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._user_code = None

    def _needs_restart(self, user_code: str) -> bool:
        return (
            self._user_code != user_code
            or self._browser is None
            or not self._browser.is_connected()
            or self._page is None
            or self._page.is_closed()
        )
