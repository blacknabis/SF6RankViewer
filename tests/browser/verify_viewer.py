"""Playwright verification for the deterministic SF6Viewer browser harness.

Run the harness separately, then execute this file with ``--base-url`` and an
artifact directory.  The verifier uses the real dashboard/OBS assets and fails
on browser errors, accessibility/state regressions, responsive overflow, or
overlapping sibling regions.
"""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path
from typing import Any, TypedDict
from urllib.parse import urljoin

from playwright.sync_api import BrowserContext, Locator, Page, expect, sync_playwright
from viewer_harness import HARNESS_NOW_MS

FROZEN_BROWSER_NOW_MS = HARNESS_NOW_MS

_FAKE_BRIDGE_SCRIPT_TEMPLATE = r"""
(() => {
  const NativeDate = window.Date;
  const frozenNow = __FROZEN_BROWSER_NOW_MS__;
  class FrozenDate extends NativeDate {
    constructor(...args) {
      super(...(args.length ? args : [frozenNow]));
    }
    static now() { return frozenNow; }
  }
  FrozenDate.parse = NativeDate.parse;
  FrozenDate.UTC = NativeDate.UTC;
  window.Date = FrozenDate;

  const calls = [];
  const holdCounts = new Map();
  const pending = new Map();
  const clone = (value) => JSON.parse(JSON.stringify(value));
  let autoStatus = {
    ok: true, enabled: true, interval_seconds: 30,
    last_attempt_at_ms: frozenNow - 5_000,
    last_success_at_ms: frozenNow - 1_000,
    last_error_code: ""
  };
  for (const method of new URLSearchParams(window.location.search).getAll("bridge_hold")) {
    holdCounts.set(method, (holdCounts.get(method) || 0) + 1);
  }

  function invoke(name, args, result) {
    calls.push({ name, args: clone(args) });
    const remaining = holdCounts.get(name) || 0;
    if (remaining > 0) {
      holdCounts.set(name, remaining - 1);
      return new Promise((resolve) => {
        const queue = pending.get(name) || [];
        queue.push(resolve);
        pending.set(name, queue);
      });
    }
    const resolved = typeof result === "function" ? result(...args) : result;
    return Promise.resolve(resolved === undefined ? undefined : clone(resolved));
  }

  const controls = {
    calls,
    setAutoStatus(status) { autoStatus = clone(status); },
    holdNext(name) {
      holdCounts.set(name, (holdCounts.get(name) || 0) + 1);
    },
    release(name, value) {
      const queue = pending.get(name) || [];
      if (!queue.length) throw new Error(`No held ${name} call to release`);
      const resolve = queue.shift();
      pending.set(name, queue);
      resolve(clone(value));
    },
    callsFor(name) {
      return calls.filter((entry) => entry.name === name).map((entry) => clone(entry.args));
    }
  };

  window.__bridgeTest = controls;
  window.confirm = () => true;
  Object.defineProperty(window.navigator, "clipboard", {
    configurable: true,
    value: {
      writeText: (...args) => invoke("clipboard_write", args, undefined)
    }
  });
  window.pywebview = {
    api: {
      auth_status: (...args) => invoke("auth_status", args, {
        ok: true, authenticated: true, user_code: "1234567890"
      }),
      auto_collection_status: (...args) => invoke("auto_collection_status", args, () => autoStatus),
      viewer_preferences: (...args) => invoke("viewer_preferences", args, {
        ok: true, delta_mode: "session", chart_limit: 50
      }),
      login: (...args) => invoke("login", args, {
        ok: true, user_code: "1234567890"
      }),
      set_auto_collection_enabled: (...args) => invoke(
        "set_auto_collection_enabled", args,
        (enabled) => ({ ...autoStatus, enabled })
      ),
      collect_matches: (...args) => invoke("collect_matches", args, {
        ok: true, status: "SUCCEEDED", normalized: 55, duplicates: 0, quarantined: 1
      }),
      clear_matches: (...args) => invoke("clear_matches", args, {
        ok: true, cleared: 55
      }),
      ignore_legacy_quarantines: (...args) => invoke("ignore_legacy_quarantines", args, {
        ok: true, ignored: 1
      }),
      set_viewer_preferences: (...args) => invoke("set_viewer_preferences", args, {
        ok: true
      })
    }
  };
})();
"""
_FAKE_BRIDGE_SCRIPT = _FAKE_BRIDGE_SCRIPT_TEMPLATE.replace(
    "__FROZEN_BROWSER_NOW_MS__", str(FROZEN_BROWSER_NOW_MS)
)

_CAPTURE_MOTION_CSS = """
*, *::before, *::after {
  animation-delay: 0s !important;
  animation-duration: 0s !important;
  scroll-behavior: auto !important;
  transition-delay: 0s !important;
  transition-duration: 0s !important;
}
"""


class ScreenshotCaptureContract(TypedDict):
    full_page: bool
    reset_scroll: bool
    disable_animations: bool
    landmarks: tuple[str, ...]


_SCREENSHOT_CONTRACTS: dict[str, ScreenshotCaptureContract] = {
    "viewer-1280x800.png": {
        "full_page": True,
        "reset_scroll": True,
        "disable_animations": True,
        "landmarks": (
            ".app-header",
            ".tab-navigation",
            "#viewer-profile-banner",
            "#chart-heading",
            "#match-feed-heading",
            "#matchup-heading",
        ),
    },
    "viewer-900x600.png": {
        "full_page": True,
        "reset_scroll": True,
        "disable_animations": True,
        "landmarks": (
            ".app-header",
            ".tab-navigation",
            "#viewer-profile-banner",
            "#chart-heading",
            "#match-feed-heading",
            "#matchup-heading",
        ),
    },
    "manage-900x600.png": {
        "full_page": True,
        "reset_scroll": True,
        "disable_animations": True,
        "landmarks": (
            ".app-header",
            ".tab-navigation",
            "#login-heading",
            "#obs-heading",
            ".summary-grid",
            ".table-panel",
        ),
    },
    "obs-session-1400x180.png": {
        "full_page": False,
        "reset_scroll": True,
        "disable_animations": True,
        "landmarks": (
            ".stats-overlay",
            ".stat-card-total",
            ".stat-card-recent",
            ".mr-chart",
        ),
    },
}


def screenshot_capture_contract(name: str) -> ScreenshotCaptureContract:
    """Return an immutable-by-copy capture contract for one required artifact."""

    contract = _SCREENSHOT_CONTRACTS.get(name)
    if contract is None:
        raise KeyError(f"unknown required screenshot {name}")
    return {
        "full_page": contract["full_page"],
        "reset_scroll": contract["reset_scroll"],
        "disable_animations": contract["disable_animations"],
        "landmarks": tuple(contract["landmarks"]),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="Running deterministic harness URL")
    parser.add_argument(
        "--output-dir", required=True, type=Path, help="Screenshot output directory"
    )
    return parser.parse_args()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _attach_error_capture(
    page: Page,
    console_errors: list[str],
    page_errors: list[str],
) -> None:
    page.on(
        "console",
        lambda message: console_errors.append(f"{page.url}: {message.text}")
        if message.type == "error"
        else None,
    )
    page.on("pageerror", lambda error: page_errors.append(f"{page.url}: {error}"))


def _new_page(
    context: BrowserContext,
    console_errors: list[str],
    page_errors: list[str],
) -> Page:
    page = context.new_page()
    _attach_error_capture(page, console_errors, page_errors)
    return page


def _select_state(page: Page, base_url: str, state: str) -> None:
    response = page.request.post(urljoin(base_url, f"/__test__/state/{state}"))
    _require(response.ok, f"failed to select harness state {state}: {response.status}")
    _require(response.json() == {"state": state}, f"unexpected state response for {state}")


def _assert_no_horizontal_overflow(page: Page, label: str) -> None:
    dimensions = page.evaluate(
        """() => ({
          clientWidth: document.documentElement.clientWidth,
          scrollWidth: document.documentElement.scrollWidth,
          bodyWidth: document.body.scrollWidth
        })"""
    )
    _require(
        dimensions["scrollWidth"] <= dimensions["clientWidth"] + 1
        and dimensions["bodyWidth"] <= dimensions["clientWidth"] + 1,
        f"{label} has horizontal overflow: {dimensions}",
    )


def _assert_no_overlap(first: Locator, second: Locator, label: str) -> None:
    first_box = first.bounding_box()
    second_box = second.bounding_box()
    _require(first_box is not None and second_box is not None, f"{label} elements are not visible")
    assert first_box is not None and second_box is not None
    overlap_width = min(
        first_box["x"] + first_box["width"],
        second_box["x"] + second_box["width"],
    ) - max(first_box["x"], second_box["x"])
    overlap_height = min(
        first_box["y"] + first_box["height"], second_box["y"] + second_box["height"]
    ) - max(first_box["y"], second_box["y"])
    _require(
        overlap_width <= 1 or overlap_height <= 1,
        f"{label} overlap by {overlap_width:.1f}×{overlap_height:.1f}px",
    )


def _hold(page: Page, method: str) -> None:
    page.evaluate("method => window.__bridgeTest.holdNext(method)", method)


def _release(page: Page, method: str, result: dict[str, Any]) -> None:
    page.evaluate(
        "([method, result]) => window.__bridgeTest.release(method, result)",
        [method, result],
    )


def _calls(page: Page, method: str) -> list[list[Any]]:
    return page.evaluate("method => window.__bridgeTest.callsFor(method)", method)


def assert_exact_call_sequence(
    actual: list[tuple[str, list[Any]]],
    expected: list[tuple[str, list[Any]]],
) -> None:
    """Reject missing, duplicate, extra, or reordered native bridge calls."""

    _require(actual == expected, f"bridge call sequence mismatch: {actual!r} != {expected!r}")


def _assert_bridge_calls(page: Page, method: str, expected: list[list[Any]]) -> None:
    actual_sequence = [(method, arguments) for arguments in _calls(page, method)]
    expected_sequence = [(method, arguments) for arguments in expected]
    assert_exact_call_sequence(actual_sequence, expected_sequence)


def _assert_action_bridge_sequence(page: Page) -> None:
    action_names = {
        "set_viewer_preferences",
        "clipboard_write",
        "login",
        "set_auto_collection_enabled",
        "collect_matches",
        "clear_matches",
        "ignore_legacy_quarantines",
    }
    call_log = page.evaluate("() => window.__bridgeTest.calls")
    actual = [
        (entry["name"], entry["args"])
        for entry in call_log
        if entry["name"] in action_names
    ]
    expected = [
        ("set_viewer_preferences", ["session", 20]),
        ("set_viewer_preferences", ["session", 100]),
        ("set_viewer_preferences", ["range", 100]),
        (
            "clipboard_write",
            ["http://127.0.0.1:8000/ui/obs.html?delta=range&limit=20"],
        ),
        ("login", []),
        ("set_auto_collection_enabled", [False]),
        ("collect_matches", []),
        ("clear_matches", []),
        ("ignore_legacy_quarantines", []),
    ]
    assert_exact_call_sequence(actual, expected)


def _exercise_tabs(
    page: Page,
    base_url: str,
    context: BrowserContext,
    errors: tuple[list[str], list[str]],
) -> None:
    expect(page.locator("#tab-viewer")).to_have_attribute("aria-selected", "true")
    expect(page.locator("#panel-viewer")).to_be_visible()
    _require(page.url.endswith("/#viewer"), f"default tab did not normalize URL hash: {page.url}")

    page.locator("#tab-viewer").focus()
    page.keyboard.press("ArrowRight")
    _require(
        page.evaluate("document.activeElement && document.activeElement.id") == "tab-manage",
        "ArrowRight did not move tab focus",
    )
    expect(page.locator("#tab-viewer")).to_have_attribute("aria-selected", "true")
    page.keyboard.press("Enter")
    expect(page.locator("#tab-manage")).to_have_attribute("aria-selected", "true")
    expect(page.locator("#panel-manage")).to_be_visible()
    page.locator("#tab-viewer").click()
    expect(page.locator("#panel-viewer")).to_be_visible()

    hash_page = _new_page(context, *errors)
    hash_page.goto(urljoin(base_url, "/#manage"), wait_until="networkidle")
    expect(hash_page.locator("#tab-manage")).to_have_attribute("aria-selected", "true")
    expect(hash_page.locator("#panel-manage")).to_be_visible()
    hash_page.close()


def _exercise_bridge_status_promises(
    context: BrowserContext,
    base_url: str,
    errors: tuple[list[str], list[str]],
) -> None:
    scenarios = (
        (
            "auth_status",
            "#login-submit",
            {"ok": True, "authenticated": True, "user_code": "1234567890"},
        ),
        (
            "auto_collection_status",
            "#auto-collection-toggle",
            {
                "ok": True, "enabled": True, "interval_seconds": 30,
                "last_attempt_at_ms": FROZEN_BROWSER_NOW_MS - 5_000,
                "last_success_at_ms": FROZEN_BROWSER_NOW_MS - 1_000,
                "last_error_code": "",
            },
        ),
        (
            "viewer_preferences",
            "#chart-limit-20",
            {"ok": True, "delta_mode": "range", "chart_limit": 20},
        ),
    )
    for method, recovery_selector, result in scenarios:
        status_page = _new_page(context, *errors)
        try:
            status_page.goto(
                urljoin(base_url, f"/?bridge_hold={method}"),
                wait_until="domcontentloaded",
            )
            status_page.wait_for_function(
                "method => window.__bridgeTest.callsFor(method).length === 1", arg=method
            )
            _assert_bridge_calls(status_page, method, [[]])
            if method == "auth_status":
                # The non-blocking saved-session probe intentionally leaves
                # manual login available.  Its visible account projection must
                # stay unresolved until the held probe settles.
                expect(status_page.locator("#login-submit")).to_be_enabled()
                expect(status_page.locator("#login-account")).to_contain_text("로그인 후")
            elif method == "auto_collection_status":
                expect(status_page.locator("#auto-collection-toggle")).to_be_disabled()
                expect(status_page.locator("#viewer-live-badge")).to_have_attribute(
                    "data-live", "false"
                )
            else:
                expect(status_page.locator("#chart-limit-50")).to_have_attribute(
                    "aria-pressed", "true"
                )
                expect(status_page.locator("#viewer-delta-mode")).to_have_value("session")

            _release(status_page, method, result)
            if method == "auth_status":
                expect(status_page.locator(recovery_selector)).to_be_enabled()
                expect(status_page.locator("#login-account")).to_contain_text("1234567890")
            elif method == "auto_collection_status":
                expect(status_page.locator(recovery_selector)).to_be_enabled()
                expect(status_page.locator("#viewer-live-badge")).to_have_attribute(
                    "data-live", "true"
                )
            else:
                expect(status_page.locator(recovery_selector)).to_have_attribute(
                    "aria-pressed", "true"
                )
                expect(status_page.locator("#viewer-delta-mode")).to_have_value("range")
                expect(status_page.locator("#mr-chart-points .chart-point")).to_have_count(20)
        finally:
            status_page.close()


def _exercise_collection_health(
    context: BrowserContext,
    base_url: str,
    errors: tuple[list[str], list[str]],
) -> None:
    status_page = _new_page(context, *errors)
    healthy = {
        "ok": True, "enabled": True, "interval_seconds": 30,
        "last_attempt_at_ms": FROZEN_BROWSER_NOW_MS - 5_000,
        "last_success_at_ms": FROZEN_BROWSER_NOW_MS - 1_000,
        "last_error_code": "",
    }
    scenarios = (
        (
            {**healthy, "last_attempt_at_ms": 0, "last_success_at_ms": 0},
            "첫 수집 대기 중", "첫 전적 수집 결과를 기다리고 있습니다.", False,
        ),
        (
            {
                **healthy, "last_attempt_at_ms": FROZEN_BROWSER_NOW_MS,
                "last_success_at_ms": 0, "last_error_code": "SESSION.EXPIRED",
            },
            "수집 오류", "로그인 세션이 만료되었습니다.", False,
        ),
        (healthy, "LIVE RECORDING", "마지막 수집 성공:", True),
        (
            {
                **healthy, "last_attempt_at_ms": FROZEN_BROWSER_NOW_MS,
                "last_error_code": "UPSTREAM.UNAVAILABLE",
            },
            "수집 오류", "Buckler 프로필 페이지에 연결할 수 없습니다.", False,
        ),
        (healthy, "LIVE RECORDING", "자동 전적 수집이 실행 중입니다.", True),
        (
            {
                **healthy, "last_attempt_at_ms": FROZEN_BROWSER_NOW_MS - 100_000,
                "last_success_at_ms": FROZEN_BROWSER_NOW_MS - 95_000,
            },
            "수집 지연", "예정된 자동 수집이 지연되고 있습니다.", False,
        ),
        (
            {
                **healthy, "last_attempt_at_ms": FROZEN_BROWSER_NOW_MS,
                "last_error_code": "PRIVATE_ERROR_DETAIL",
            },
            "수집 오류", "수집을 완료할 수 없습니다.", False,
        ),
        (
            {**healthy, "enabled": False},
            "RECORDING OFF", "자동 전적 수집이 중지되어 있습니다.", False,
        ),
        (
            {**healthy, "last_success_at_ms": "invalid"},
            "자동 수집 상태 확인 불가", "자동 수집 결과를 확인할 수 없습니다.", False,
        ),
    )
    try:
        status_page.goto(base_url, wait_until="networkidle")
        for status, badge, message, live in scenarios:
            status_page.evaluate(
                "async status => { window.__bridgeTest.setAutoStatus(status); await refresh(); }",
                status,
            )
            expect(status_page.locator("#viewer-live-badge")).to_have_text(badge)
            expect(status_page.locator("#viewer-live-badge")).to_have_attribute(
                "data-live", str(live).lower()
            )
            expect(status_page.locator("#auto-collection-status")).to_contain_text(message)
            expect(status_page.locator("#auto-collection-status")).not_to_contain_text(
                "PRIVATE_ERROR_DETAIL"
            )

        # Losing the bridge must clear a previously healthy recording claim.
        status_page.evaluate(
            "async status => { window.__bridgeTest.setAutoStatus(status); await refresh(); }",
            healthy,
        )
        status_page.evaluate("""async () => {
          window.pywebview.api.auto_collection_status = () =>
            Promise.reject(new Error("unavailable"));
          await refresh();
        }""")
        expect(status_page.locator("#viewer-live-badge")).to_have_attribute("data-live", "false")
        expect(status_page.locator("#auto-collection-status")).to_contain_text(
            "자동 수집 상태를 확인할 수 없습니다."
        )
    finally:
        status_page.close()


def _exercise_chart_and_feed(page: Page) -> None:
    expect(page.locator("#viewer-profile-name")).to_have_text("Harness Fighter")
    expect(page.locator("#kpi-session-delta")).to_have_text("▲ +45 MR")
    expect(page.locator("#kpi-session-context")).to_have_text("앱 시작 기준")
    expect(page.locator("#mr-chart-points .chart-point")).to_have_count(50)
    expect(
        page.locator("#match-feed-list .match-card").first.locator(".match-card-meta .muted").first
    ).to_have_text("방금 전")

    first_point = page.locator("#mr-chart-points .chart-point").first
    first_point.hover(force=True)
    expect(page.locator("#mr-chart-tooltip")).to_be_visible()
    expect(page.locator("#mr-chart-tooltip")).to_contain_text("History Rival")
    first_point.dispatch_event("mouseleave")
    expect(page.locator("#mr-chart-tooltip")).to_be_hidden()
    first_point.focus()
    expect(page.locator("#mr-chart-tooltip")).to_be_visible()
    expect(page.locator("#mr-chart-tooltip")).to_contain_text("History Rival")
    expect(page.locator("#mr-chart-tooltip-status")).to_contain_text("MR")

    _hold(page, "set_viewer_preferences")
    page.locator("#chart-limit-20").click()
    expect(page.locator("#chart-limit-20")).to_have_attribute("aria-pressed", "true")
    # Preference persistence is deliberately optimistic and serialized: there
    # is no blocking spinner, so the visible selected chip remains interactive
    # while the native write is pending and after it settles.
    expect(page.locator("#chart-limit-20")).to_be_enabled()
    expect(page.locator("#chart-limit-20")).not_to_have_attribute("aria-busy", "true")
    expect(page.locator("#mr-chart-points .chart-point")).to_have_count(20)
    _release(page, "set_viewer_preferences", {"ok": True})
    expect(page.locator("#chart-limit-20")).to_be_enabled()
    expect(page.locator("#chart-limit-20")).not_to_have_attribute("aria-busy", "true")
    _assert_bridge_calls(page, "set_viewer_preferences", [["session", 20]])

    page.locator("#chart-limit-100").click()
    expect(page.locator("#mr-chart-points .chart-point")).to_have_count(100)
    _assert_bridge_calls(
        page,
        "set_viewer_preferences",
        [["session", 20], ["session", 100]],
    )

    _hold(page, "set_viewer_preferences")
    page.locator("#viewer-delta-mode").select_option("range")
    expect(page.locator("#kpi-session-delta")).to_have_text("▲ +99 MR")
    expect(page.locator("#kpi-session-context")).to_have_text("표시 구간 최근 100전")
    _release(page, "set_viewer_preferences", {"ok": True})
    _assert_bridge_calls(
        page,
        "set_viewer_preferences",
        [["session", 20], ["session", 100], ["range", 100]],
    )

    expect(page.locator("#match-feed-list .match-card")).to_have_count(25)
    expect(page.locator("#match-feed-load-more")).to_be_visible()
    page.locator("#match-feed-load-more").click()
    expect(page.locator("#match-feed-list .match-card")).to_have_count(50)
    page.locator("#match-feed-load-more").click()
    expect(page.locator("#match-feed-list .match-card")).to_have_count(55)
    expect(page.locator("#match-feed-load-more")).to_be_hidden()
    expect(page.locator("#match-feed-state")).to_have_text("모든 대전 기록을 표시했습니다.")

    expect(page.locator('#matchup-grid .matchup-card[data-tier="favored"]')).to_contain_text("우세")
    expect(page.locator('#matchup-grid .matchup-card[data-tier="even"]')).to_contain_text("호각")
    expect(
        page.locator('#matchup-grid .matchup-card[data-tier="unfavored"]')
    ).to_contain_text("열세")


def _exercise_manage_bridge(page: Page) -> None:
    page.locator("#tab-manage").click()
    expect(page.locator("#panel-manage")).to_be_visible()
    for selector in (
        "#login-submit",
        "#auto-collection-toggle",
        "#matches-collect",
        "#matches-reset",
        "#legacy-quarantine-clear",
        "#obs-url",
        "#obs-copy",
    ):
        expect(page.locator(selector)).to_be_visible()

    expect(page.locator("#login-submit")).to_be_enabled()
    expect(page.locator("#matches-collect")).to_be_enabled()
    _assert_bridge_calls(page, "auth_status", [[]])
    _assert_bridge_calls(page, "auto_collection_status", [[], []])
    _assert_bridge_calls(page, "viewer_preferences", [[]])

    page.locator("#obs-delta-mode").select_option("range")
    page.locator("#obs-chart-limit").select_option("20")
    expect(page.locator("#obs-url")).to_have_value(
        "http://127.0.0.1:8000/ui/obs.html?delta=range&limit=20"
    )
    page.locator("#obs-copy").click()
    expect(page.locator("#obs-status")).to_have_text("OBS 주소를 복사했습니다.")
    _assert_bridge_calls(
        page,
        "clipboard_write",
        [["http://127.0.0.1:8000/ui/obs.html?delta=range&limit=20"]],
    )
    expect(page.locator("#viewer-delta-mode")).to_have_value("range")
    expect(page.locator("#chart-limit-100")).to_have_attribute("aria-pressed", "true")

    _hold(page, "login")
    page.locator("#login-submit").click()
    expect(page.locator("#login-form")).to_have_attribute("aria-busy", "true")
    expect(page.locator("#login-submit")).to_be_disabled()
    _release(page, "login", {"ok": True, "user_code": "1234567890"})
    expect(page.locator("#login-form")).not_to_have_attribute("aria-busy", "true")
    expect(page.locator("#login-submit")).to_be_enabled()
    _assert_bridge_calls(page, "login", [[]])

    _hold(page, "set_auto_collection_enabled")
    page.locator("#auto-collection-toggle").click()
    expect(page.locator("#auto-collection-toggle")).to_have_attribute("aria-busy", "true")
    expect(page.locator("#auto-collection-toggle")).to_be_disabled()
    _release(
        page,
        "set_auto_collection_enabled",
        {"ok": True, "enabled": False, "interval_seconds": 30},
    )
    expect(page.locator("#auto-collection-toggle")).not_to_have_attribute("aria-busy", "true")
    expect(page.locator("#auto-collection-toggle")).to_be_enabled()
    _assert_bridge_calls(page, "set_auto_collection_enabled", [[False]])

    _hold(page, "collect_matches")
    page.locator("#matches-collect").click()
    expect(page.locator("#matches-collect")).to_have_attribute("aria-busy", "true")
    expect(page.locator("#matches-collect")).to_be_disabled()
    # A refresh completion recomputes management availability while the native
    # collection promise is still pending.  It must not re-enable the action or
    # allow a second direct invocation to cross the bridge.
    page.evaluate("refresh()")
    expect(page.locator("#matches-collect")).to_be_disabled()
    page.evaluate("void collectMatches()")
    _assert_bridge_calls(page, "collect_matches", [[]])
    _release(
        page,
        "collect_matches",
        {"ok": True, "status": "SUCCEEDED", "normalized": 55, "duplicates": 0, "quarantined": 1},
    )
    expect(page.locator("#matches-collect")).not_to_have_attribute("aria-busy", "true")
    expect(page.locator("#matches-collect")).to_be_enabled()
    _assert_bridge_calls(page, "collect_matches", [[]])

    _hold(page, "clear_matches")
    page.locator("#matches-reset").click()
    expect(page.locator("#matches-reset")).to_have_attribute("aria-busy", "true")
    expect(page.locator("#matches-reset")).to_be_disabled()
    _release(page, "clear_matches", {"ok": True, "cleared": 55})
    expect(page.locator("#matches-reset")).not_to_have_attribute("aria-busy", "true")
    expect(page.locator("#matches-reset")).to_be_enabled()
    _assert_bridge_calls(page, "clear_matches", [[]])

    _hold(page, "ignore_legacy_quarantines")
    page.locator("#legacy-quarantine-clear").click()
    expect(page.locator("#legacy-quarantine-clear")).to_have_attribute("aria-busy", "true")
    expect(page.locator("#legacy-quarantine-clear")).to_be_disabled()
    _release(page, "ignore_legacy_quarantines", {"ok": True, "ignored": 1})
    expect(page.locator("#legacy-quarantine-clear")).not_to_have_attribute("aria-busy", "true")
    expect(page.locator("#legacy-quarantine-clear")).to_be_enabled()
    _assert_bridge_calls(page, "ignore_legacy_quarantines", [[]])
    _assert_action_bridge_sequence(page)


def _exercise_states(page: Page, base_url: str) -> None:
    page.locator("#tab-viewer").click()
    expect(page.locator("#viewer-profile-name")).to_have_text("Harness Fighter")

    _select_state(page, base_url, "partial-error")
    page.evaluate("refresh()")
    expect(page.locator("#viewer-error")).to_be_visible()
    expect(page.locator("#viewer-error")).to_contain_text("마지막 정상 데이터")
    expect(page.locator("#viewer-profile-name")).to_have_text("Harness Fighter")
    expect(page.locator("#mr-chart-points .chart-point")).to_have_count(100)

    _select_state(page, base_url, "empty")
    # Empty is a first-run scenario.  Reloading gives it a fresh client state;
    # a normal refresh intentionally merges newer feed items into last-good
    # history unless a reset boundary advances.
    page.reload(wait_until="networkidle")
    expect(page.locator("#viewer-error")).to_be_hidden()
    expect(page.locator("#mr-chart-points .chart-point")).to_have_count(0)
    expect(page.locator("#chart-empty")).to_be_visible()
    expect(page.locator("#match-feed-empty")).to_be_visible()
    expect(page.locator("#matchup-empty")).to_be_visible()

    _select_state(page, base_url, "post-reset")
    page.evaluate("refresh()")
    expect(page.locator("#mr-chart-points .chart-point")).to_have_count(1)
    page.locator("#viewer-delta-mode").select_option("session")
    expect(page.locator("#kpi-session-delta")).to_have_text("▲ +12 MR")
    expect(page.locator("#kpi-session-context")).to_have_text("전적 초기화 이후")
    page.locator("#viewer-delta-mode").select_option("range")
    expect(page.locator("#kpi-session-delta")).to_have_text("0 MR")
    expect(page.locator("#kpi-session-context")).to_have_text("기준 데이터 1건")

    _select_state(page, base_url, "populated")
    page.evaluate("refresh()")
    expect(page.locator("#viewer-profile-name")).to_have_text("Harness Fighter")


def _disable_capture_motion(page: Page) -> None:
    page.add_style_tag(content=_CAPTURE_MOTION_CSS)
    page.evaluate(
        """async () => {
          for (const animation of document.getAnimations()) animation.cancel();
          await new Promise((resolve) =>
            requestAnimationFrame(() => requestAnimationFrame(resolve))
          );
        }"""
    )


def _prepare_required_screenshot(
    page: Page, name: str
) -> tuple[ScreenshotCaptureContract, float]:
    contract = screenshot_capture_contract(name)
    if contract["disable_animations"]:
        _disable_capture_motion(page)
    if contract["reset_scroll"]:
        scroll = page.evaluate(
            """async () => {
              window.scrollTo(0, 0);
              await new Promise((resolve) =>
                requestAnimationFrame(() => requestAnimationFrame(resolve))
              );
              return { x: window.scrollX, y: window.scrollY };
            }"""
        )
        _require(scroll == {"x": 0, "y": 0}, f"{name} capture did not reset scroll: {scroll}")

    landmark_bottom = 0.0
    for selector in contract["landmarks"]:
        landmark = page.locator(selector).first
        expect(landmark).to_be_visible()
        box = landmark.bounding_box()
        _require(box is not None, f"{name} landmark has no layout box: {selector}")
        assert box is not None
        landmark_bottom = max(landmark_bottom, box["y"] + box["height"])
    return contract, landmark_bottom


def _capture_required_screenshot(page: Page, output_dir: Path, name: str) -> None:
    contract, landmark_bottom = _prepare_required_screenshot(page, name)
    target = output_dir / name
    page.screenshot(
        path=target,
        full_page=contract["full_page"],
        animations="disabled",
        caret="hide",
    )
    data = target.read_bytes()
    _require(data[:8] == b"\x89PNG\r\n\x1a\n", f"{name} is not a PNG")
    width, height = struct.unpack(">II", data[16:24])
    viewport = page.viewport_size
    _require(viewport is not None, f"{name} page has no viewport")
    assert viewport is not None
    _require(width == viewport["width"], f"{name} width {width} != {viewport['width']}")
    _require(
        height + 1 >= landmark_bottom,
        f"{name} height {height} clips required landmark bottom {landmark_bottom:.1f}",
    )
    if contract["full_page"]:
        _require(
            height >= viewport["height"],
            f"{name} full-page height {height} is below viewport {viewport['height']}",
        )


def _capture_dashboard_screenshots(page: Page, output_dir: Path) -> None:
    _disable_capture_motion(page)
    page.locator("#tab-viewer").click()
    expect(page.locator("#panel-viewer")).to_be_visible()
    page.set_viewport_size({"width": 1280, "height": 800})
    _assert_no_horizontal_overflow(page, "viewer 1280×800")
    _assert_no_overlap(page.locator("#kpi-total"), page.locator("#kpi-recent"), "viewer KPI cards")
    _assert_no_overlap(
        page.locator(".chart-panel"), page.locator("#match-feed"), "viewer primary regions"
    )
    _capture_required_screenshot(page, output_dir, "viewer-1280x800.png")

    page.set_viewport_size({"width": 900, "height": 600})
    _assert_no_horizontal_overflow(page, "viewer 900×600")
    _assert_no_overlap(
        page.locator("#kpi-total"), page.locator("#kpi-recent"), "responsive KPI cards"
    )
    _assert_no_overlap(
        page.locator(".chart-panel"), page.locator("#match-feed"), "responsive viewer regions"
    )
    _capture_required_screenshot(page, output_dir, "viewer-900x600.png")

    page.locator("#tab-manage").click()
    expect(page.locator("#panel-manage")).to_be_visible()
    _assert_no_horizontal_overflow(page, "manage 900×600")
    _assert_no_overlap(
        page.locator("#login-heading").locator(".."),
        page.locator("#obs-heading").locator(".."),
        "manage login and OBS panels",
    )
    _capture_required_screenshot(page, output_dir, "manage-900x600.png")


def _exercise_obs(
    page: Page,
    base_url: str,
    output_dir: Path,
) -> None:
    _select_state(page, base_url, "populated")
    page.set_viewport_size({"width": 1400, "height": 180})
    page.goto(urljoin(base_url, "/ui/obs.html?delta=session&limit=50"), wait_until="networkidle")
    expect(page.locator("#overlay-status")).to_have_text("연결됨")
    expect(page.locator("#obs-mr-delta")).to_have_text("▲ +45 MR")
    expect(page.locator("#obs-delta-context")).to_have_text("APP START")
    _require(len(page.locator("#mr-line").get_attribute("points") or "") > 0, "OBS chart is empty")
    _assert_no_horizontal_overflow(page, "OBS session 1400×180")
    _assert_no_overlap(
        page.locator(".stat-card-total"),
        page.locator(".stat-card-recent"),
        "OBS total/recent cards",
    )
    _capture_required_screenshot(page, output_dir, "obs-session-1400x180.png")

    page.goto(urljoin(base_url, "/ui/obs.html?delta=range&limit=20"), wait_until="networkidle")
    expect(page.locator("#obs-mr-delta")).to_have_text("▲ +19 MR")
    expect(page.locator("#obs-delta-context")).to_have_text("LAST 20")

    _select_state(page, base_url, "post-reset")
    page.goto(urljoin(base_url, "/ui/obs.html?delta=session&limit=50"), wait_until="networkidle")
    expect(page.locator("#obs-mr-delta")).to_have_text("▲ +12 MR")
    expect(page.locator("#obs-delta-context")).to_have_text("SINCE RESET")


def run(base_url: str, output_dir: Path) -> None:
    base_url = base_url.rstrip("/") + "/"
    output_dir.mkdir(parents=True, exist_ok=True)
    console_errors: list[str] = []
    page_errors: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        context.add_init_script(_FAKE_BRIDGE_SCRIPT)
        page = _new_page(context, console_errors, page_errors)
        try:
            _select_state(page, base_url, "populated")
            page.goto(base_url, wait_until="networkidle")
            expect(page.locator("#connection-status")).to_have_text("로컬 서비스 연결됨")

            _exercise_tabs(page, base_url, context, (console_errors, page_errors))
            _exercise_bridge_status_promises(
                context, base_url, (console_errors, page_errors)
            )
            _exercise_collection_health(
                context, base_url, (console_errors, page_errors)
            )
            _exercise_chart_and_feed(page)
            _exercise_manage_bridge(page)
            _exercise_states(page, base_url)
            _capture_dashboard_screenshots(page, output_dir)

            obs_page = _new_page(context, console_errors, page_errors)
            try:
                _exercise_obs(obs_page, base_url, output_dir)
            finally:
                obs_page.close()
        finally:
            context.close()
            browser.close()

    _require(not console_errors, "browser console errors:\n" + "\n".join(console_errors))
    _require(not page_errors, "browser page errors:\n" + "\n".join(page_errors))
    expected = {
        "viewer-1280x800.png",
        "viewer-900x600.png",
        "manage-900x600.png",
        "obs-session-1400x180.png",
    }
    actual = {path.name for path in output_dir.glob("*.png")}
    _require(expected <= actual, f"missing screenshots: {sorted(expected - actual)}")
    print(
        json.dumps(
            {
                "status": "ok",
                "screenshots": sorted(expected),
                "console_errors": console_errors,
                "page_errors": page_errors,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    arguments = _parse_args()
    run(arguments.base_url, arguments.output_dir.resolve())
