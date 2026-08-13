"""Playwright-backed, user-driven authentication browser."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from sf6viewer.domain.errors import DomainError
from sf6viewer.domain.value_objects import UserCode
from sf6viewer.infrastructure.auth.dpapi_vault import AuthSession
from sf6viewer.infrastructure.buckler.native_login_browser import (
    NativeLoginBrowser,
    launch_native_login_browser,
)

_INTERACTIVE_LOGIN_FAILED = "Interactive sign-in could not be completed."


class PlaywrightAuthBrowser:
    """Complete sign-in in a visible browser controlled by the host UI."""

    def __init__(
        self,
        target_url: str,
        profile_dir: Path,
        wait_for_authenticated: Callable[[Page], None],
        extract_user_code: Callable[[Page], str],
    ) -> None:
        self._target_url = target_url
        self._profile_dir = profile_dir
        self._wait_for_authenticated = wait_for_authenticated
        self._extract_user_code = extract_user_code

    def login_interactively(self) -> AuthSession:
        """Run an interactive sign-in and return opaque authenticated state."""
        browser: Browser | None = None
        context: BrowserContext | None = None
        native_browser: NativeLoginBrowser | None = None

        try:
            with sync_playwright() as playwright:
                try:
                    native_browser = launch_native_login_browser(
                        self._profile_dir, self._target_url
                    )
                    browser = playwright.chromium.connect_over_cdp(native_browser.endpoint_url)
                    if len(browser.contexts) != 1:
                        raise RuntimeError(_INTERACTIVE_LOGIN_FAILED)
                    context = browser.contexts[0]
                    page = context.pages[-1] if context.pages else context.new_page()

                    self._wait_for_authenticated(page)
                    user_code = UserCode.parse(self._extract_user_code(page))
                    storage_state = json.dumps(
                        context.storage_state(), separators=(",", ":"), sort_keys=True
                    ).encode("utf-8")
                    return AuthSession(user_code=user_code, storage_state=storage_state)
                finally:
                    _close_quietly(context)
                    _close_quietly(browser)
                    _close_quietly(native_browser)
        except DomainError:
            raise
        except Exception:
            raise RuntimeError(_INTERACTIVE_LOGIN_FAILED) from None


def _close_quietly(resource: BrowserContext | Browser | NativeLoginBrowser | None) -> None:
    """Close browser resources without replacing a safe public failure."""
    if resource is None:
        return
    with suppress(Exception):
        resource.close()
