"""Structural contracts for the dependency-free dashboard shell."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

WEB_ROOT = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "sf6viewer"
    / "interfaces"
    / "web"
)


class _DashboardParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.elements: list[tuple[str, dict[str, str | None]]] = []
        self.scripts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = dict(attrs)
        self.elements.append((tag, attributes))
        if tag == "script" and attributes.get("src"):
            self.scripts.append(str(attributes["src"]))

    def element(self, element_id: str) -> tuple[str, dict[str, str | None]]:
        return next(
            element
            for element in self.elements
            if element[1].get("id") == element_id
        )


def _dashboard() -> _DashboardParser:
    parser = _DashboardParser()
    parser.feed((WEB_ROOT / "dashboard.html").read_text(encoding="utf-8"))
    return parser


def test_tabs_have_accessible_relationships_and_default_to_viewer() -> None:
    dashboard = _dashboard()
    assert any(attrs.get("role") == "tablist" for _, attrs in dashboard.elements)

    _, viewer_tab = dashboard.element("tab-viewer")
    _, manage_tab = dashboard.element("tab-manage")
    _, viewer_panel = dashboard.element("panel-viewer")
    _, manage_panel = dashboard.element("panel-manage")

    assert viewer_tab | {
        "role": "tab",
        "aria-controls": "panel-viewer",
        "aria-selected": "true",
        "tabindex": "0",
    } == viewer_tab
    assert manage_tab | {
        "role": "tab",
        "aria-controls": "panel-manage",
        "aria-selected": "false",
        "tabindex": "-1",
    } == manage_tab
    assert viewer_panel["role"] == "tabpanel"
    assert viewer_panel["aria-labelledby"] == "tab-viewer"
    assert "hidden" not in viewer_panel
    assert manage_panel["role"] == "tabpanel"
    assert manage_panel["aria-labelledby"] == "tab-manage"
    assert "hidden" in manage_panel


def test_viewer_and_existing_manage_element_ids_are_preserved() -> None:
    dashboard = _dashboard()
    actual_ids = {attrs["id"] for _, attrs in dashboard.elements if "id" in attrs}

    manage_ids = {
        "app-version",
        "auto-collection-status",
        "auto-collection-toggle",
        "connection-dot",
        "connection-status",
        "content",
        "ingestion-empty",
        "ingestion-rows",
        "job-detail",
        "job-empty",
        "last-refresh",
        "legacy-quarantine-clear",
        "legacy-quarantine-status",
        "login-account",
        "login-form",
        "login-heading",
        "login-status",
        "login-submit",
        "match-count",
        "match-detail",
        "match-empty",
        "matches-collect",
        "matches-collect-status",
        "matches-reset",
        "matches-reset-status",
        "obs-chart-limit",
        "obs-copy",
        "obs-delta-mode",
        "obs-heading",
        "obs-help",
        "obs-status",
        "obs-url",
        "page-state",
        "profile-count",
        "profile-detail",
        "profile-empty",
        "quarantine-count",
        "quarantine-empty",
        "quarantine-list",
        "running-job-count",
    }
    viewer_ids = {
        "panel-viewer",
        "tab-viewer",
        "viewer-state",
        "viewer-error",
        "viewer-profile-banner",
        "viewer-profile-name",
        "viewer-profile-character",
        "viewer-profile-rank",
        "viewer-profile-rating",
        "viewer-profile-empty",
        "viewer-live-badge",
        "viewer-live-status",
        "kpi-total",
        "kpi-total-rate",
        "kpi-total-record",
        "kpi-total-progress",
        "kpi-recent",
        "kpi-recent-rate",
        "kpi-recent-record",
        "kpi-recent-progress",
        "kpi-session",
        "kpi-session-delta",
        "kpi-session-context",
        "viewer-delta-mode",
        "kpi-streak",
        "kpi-streak-value",
        "kpi-streak-context",
        "chart-limit-20",
        "chart-limit-50",
        "chart-limit-100",
        "mr-chart",
        "mr-chart-area",
        "mr-chart-line",
        "mr-chart-points",
        "mr-chart-tooltip",
        "mr-chart-tooltip-status",
        "chart-state",
        "chart-empty",
        "match-feed",
        "match-feed-list",
        "match-feed-load-more",
        "match-feed-state",
        "match-feed-empty",
        "matchup-grid",
        "matchup-state",
        "matchup-empty",
    }

    assert manage_ids | viewer_ids <= actual_ids


def test_dashboard_scripts_load_helpers_controller_renderer_then_entrypoint() -> None:
    dashboard = _dashboard()
    expected = [
        "/ui/viewer-metrics.js",
        "/ui/dashboard-controller.js",
        "/ui/dashboard-viewer.js",
        "/ui/dashboard.js",
    ]
    assert [script for script in dashboard.scripts if script in expected] == expected


def test_dashboard_css_defines_responsive_focus_and_reduced_motion_contracts() -> None:
    css = (WEB_ROOT / "dashboard.css").read_text(encoding="utf-8")

    assert "@media (max-width: 900px)" in css
    assert "@media (max-width: 560px)" in css
    assert ":focus-visible" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
