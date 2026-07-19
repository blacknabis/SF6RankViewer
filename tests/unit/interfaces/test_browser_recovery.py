"""Regression coverage for user-closed Buckler browser recovery."""

import pytest

from sf6viewer.infrastructure.buckler.browser_capture import PersistentBucklerBrowser


class _FakeBrowser:
    def __init__(self, *, connected: bool = True) -> None:
        self.connected = connected

    def is_connected(self) -> bool:
        return self.connected


class _FakePage:
    def __init__(self) -> None:
        self.closed = False

    def is_closed(self) -> bool:
        return self.closed


def _replace_page_provider(
    monkeypatch: pytest.MonkeyPatch,
    browser: PersistentBucklerBrowser,
    pages: list[_FakePage],
    fake_browser: _FakeBrowser,
) -> list[int]:
    calls: list[int] = []

    def page_for(*, user_code: str, storage_state: dict[str, object]) -> _FakePage:
        del user_code, storage_state
        page = pages[len(calls)]
        calls.append(1)
        browser._browser = fake_browser  # type: ignore[assignment]
        browser._page = page  # type: ignore[assignment]
        return page

    monkeypatch.setattr(browser, "page_for", page_for)
    return calls


def test_closed_browser_is_recreated_and_capture_is_retried_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser = PersistentBucklerBrowser()
    fake_browser = _FakeBrowser()
    first_page = _FakePage()
    second_page = _FakePage()
    calls = _replace_page_provider(
        monkeypatch, browser, [first_page, second_page], fake_browser
    )

    def operation(page: _FakePage) -> str:
        if page is first_page:
            first_page.closed = True
            fake_browser.connected = False
            raise RuntimeError("browser closed")
        return "captured"

    result = browser.run_with_recovery(
        user_code="1234567890",
        storage_state={},
        operation=operation,  # type: ignore[arg-type]
    )

    assert result == "captured"
    assert len(calls) == 2


def test_connected_browser_failure_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    browser = PersistentBucklerBrowser()
    fake_browser = _FakeBrowser()
    page = _FakePage()
    calls = _replace_page_provider(monkeypatch, browser, [page], fake_browser)

    def operation(_: _FakePage) -> str:
        raise RuntimeError("page contract failed")

    with pytest.raises(RuntimeError, match="page contract failed"):
        browser.run_with_recovery(
            user_code="1234567890",
            storage_state={},
            operation=operation,  # type: ignore[arg-type]
        )

    assert len(calls) == 1
