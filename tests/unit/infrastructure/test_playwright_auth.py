"""Regression coverage for the packaged interactive-login browser launcher."""

from __future__ import annotations

import pytest

import sf6viewer.infrastructure.buckler.playwright_auth as playwright_auth
from sf6viewer.infrastructure.buckler.playwright_auth import PlaywrightAuthBrowser


class _FakePage:
    def __init__(self) -> None:
        self.visited_urls: list[str] = []

    def goto(self, url: str) -> None:
        self.visited_urls.append(url)


class _FakeContext:
    def __init__(self, page: _FakePage) -> None:
        self.page = page
        self.closed = False

    def new_page(self) -> _FakePage:
        return self.page

    def storage_state(self) -> dict[str, list[object]]:
        return {"cookies": [], "origins": []}

    def close(self) -> None:
        self.closed = True


class _FakeBrowser:
    def __init__(self, context: _FakeContext) -> None:
        self.context = context
        self.closed = False

    def new_context(self) -> _FakeContext:
        return self.context

    def close(self) -> None:
        self.closed = True


class _FakePlaywrightManager:
    def __init__(self, playwright: object) -> None:
        self.playwright = playwright

    def __enter__(self) -> object:
        return self.playwright

    def __exit__(self, *_: object) -> None:
        return None


def test_interactive_login_uses_shared_system_browser_launcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _FakePage()
    context = _FakeContext(page)
    browser = _FakeBrowser(context)
    fake_playwright = object()
    launch_calls: list[object] = []
    authenticated_pages: list[_FakePage] = []

    def launch_visible_browser(playwright: object) -> _FakeBrowser:
        launch_calls.append(playwright)
        return browser

    monkeypatch.setattr(
        playwright_auth,
        "sync_playwright",
        lambda: _FakePlaywrightManager(fake_playwright),
    )
    monkeypatch.setattr(playwright_auth, "launch_visible_system_browser", launch_visible_browser)

    auth_browser = PlaywrightAuthBrowser(
        target_url="https://example.test/buckler",
        wait_for_authenticated=lambda candidate: authenticated_pages.append(candidate),
        extract_user_code=lambda _: "1234567890",
    )

    session = auth_browser.login_interactively()

    assert launch_calls == [fake_playwright]
    assert page.visited_urls == ["https://example.test/buckler"]
    assert authenticated_pages == [page]
    assert session.user_code.value == "1234567890"
    assert context.closed is True
    assert browser.closed is True
