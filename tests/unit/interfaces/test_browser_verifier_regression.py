"""Regression contracts for deterministic browser screenshots and bridge calls."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BROWSER_TEST_ROOT = Path(__file__).resolve().parents[2] / "browser"
sys.path.insert(0, str(_BROWSER_TEST_ROOT))

import verify_viewer  # noqa: E402
from verify_viewer import screenshot_capture_contract  # noqa: E402


def test_dashboard_screenshot_contract_starts_at_top_and_captures_landmarks() -> None:
    viewer = screenshot_capture_contract("viewer-900x600.png")
    manage = screenshot_capture_contract("manage-900x600.png")

    assert viewer == {
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
    }
    assert manage["full_page"] is True
    assert manage["reset_scroll"] is True
    assert manage["disable_animations"] is True
    assert "#login-heading" in manage["landmarks"]
    assert "#obs-heading" in manage["landmarks"]


def test_exact_bridge_sequence_rejects_duplicates_extras_and_reordering() -> None:
    expected = [("login", []), ("collect_matches", [])]
    verify_viewer.assert_exact_call_sequence(expected, expected)

    for actual in (
        [*expected, ("collect_matches", [])],
        [("login", []), ("clear_matches", []), ("collect_matches", [])],
        list(reversed(expected)),
    ):
        with pytest.raises(AssertionError, match="bridge call sequence"):
            verify_viewer.assert_exact_call_sequence(actual, expected)


def test_browser_clock_is_frozen_relative_to_newest_fixture() -> None:
    import viewer_harness

    newest_match_ms = viewer_harness._POPULATED_MATCHES[0]["occurred_at_ms"]
    assert verify_viewer.FROZEN_BROWSER_NOW_MS - newest_match_ms == 30_000
    assert str(verify_viewer.FROZEN_BROWSER_NOW_MS) in verify_viewer._FAKE_BRIDGE_SCRIPT
