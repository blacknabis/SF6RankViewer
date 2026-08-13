"""Regression coverage for the packaged interactive-login browser launcher."""

from __future__ import annotations

from pathlib import Path

import pytest

import sf6viewer.infrastructure.buckler.playwright_auth as playwright_auth
from sf6viewer.infrastructure.buckler.native_login_browser import _browser_command
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

    @property
    def pages(self) -> list[_FakePage]:
        return [self.page]

    def storage_state(self) -> dict[str, list[object]]:
        return {"cookies": [], "origins": []}

    def close(self) -> None:
        self.closed = True


class _FakeBrowser:
    def __init__(self, context: _FakeContext) -> None:
        self.context = context
        self.closed = False

    @property
    def contexts(self) -> list[_FakeContext]:
        return [self.context]

    def close(self) -> None:
        self.closed = True


class _FakePlaywrightManager:
    def __init__(self, playwright: object) -> None:
        self.playwright = playwright

    def __enter__(self) -> object:
        return self.playwright

    def __exit__(self, *_: object) -> None:
        return None


class _FakeChromium:
    def __init__(self, browser: _FakeBrowser) -> None:
        self.browser = browser
        self.endpoints: list[str] = []

    def connect_over_cdp(self, endpoint: str) -> _FakeBrowser:
        self.endpoints.append(endpoint)
        return self.browser


class _FakePlaywright:
    def __init__(self, chromium: _FakeChromium) -> None:
        self.chromium = chromium


class _FakeNativeBrowser:
    endpoint_url = "http://127.0.0.1:49152"

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_interactive_login_connects_to_native_browser_with_durable_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _FakePage()
    context = _FakeContext(page)
    browser = _FakeBrowser(context)
    chromium = _FakeChromium(browser)
    fake_playwright = _FakePlaywright(chromium)
    native_browser = _FakeNativeBrowser()
    profile_dir = tmp_path / "browser" / "login"
    launch_calls: list[tuple[Path, str]] = []
    authenticated_pages: list[object] = []

    def launch_native_browser(candidate_profile: Path, target_url: str) -> _FakeNativeBrowser:
        launch_calls.append((candidate_profile, target_url))
        return native_browser

    monkeypatch.setattr(
        playwright_auth,
        "sync_playwright",
        lambda: _FakePlaywrightManager(fake_playwright),
    )
    monkeypatch.setattr(playwright_auth, "launch_native_login_browser", launch_native_browser)

    auth_browser = PlaywrightAuthBrowser(
        target_url="https://example.test/buckler",
        profile_dir=profile_dir,
        wait_for_authenticated=lambda candidate: authenticated_pages.append(candidate),
        extract_user_code=lambda _: "1234567890",
    )

    session = auth_browser.login_interactively()

    assert launch_calls == [(profile_dir, "https://example.test/buckler")]
    assert chromium.endpoints == [native_browser.endpoint_url]
    assert page.visited_urls == []
    assert authenticated_pages == [page]
    assert session.user_code.value == "1234567890"
    assert context.closed is True
    assert browser.closed is True
    assert native_browser.closed is True


def test_native_browser_command_avoids_playwright_automation_flags(tmp_path: Path) -> None:
    profile_dir = tmp_path / "browser" / "login"

    command = _browser_command(
        executable=Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        profile_dir=profile_dir,
        debugging_port=49_152,
        target_url="https://www.streetfighter.com/6/buckler/ko-kr",
    )

    assert command == [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        f"--user-data-dir={profile_dir}",
        "--remote-debugging-address=127.0.0.1",
        "--remote-debugging-port=49152",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        "https://www.streetfighter.com/6/buckler/ko-kr",
    ]
    assert not any("automation" in argument for argument in command)
    assert "--remote-debugging-pipe" not in command
