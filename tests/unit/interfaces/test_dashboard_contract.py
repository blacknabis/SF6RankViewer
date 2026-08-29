"""Structural contracts for the dependency-free dashboard shell."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath

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
    id_list = [attrs["id"] for _, attrs in dashboard.elements if "id" in attrs]
    actual_ids = set(id_list)

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

    assert len(id_list) == len(actual_ids), "dashboard IDs must be unique"
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
    for script in dashboard.scripts:
        if script.startswith("/ui/") and script.endswith(".js"):
            assert (WEB_ROOT / PurePosixPath(script).name).is_file(), script


def test_dashboard_css_defines_responsive_focus_and_reduced_motion_contracts() -> None:
    css = (WEB_ROOT / "dashboard.css").read_text(encoding="utf-8")

    assert re.search(
        r"@media\s*\(max-width:\s*900px\).*?\.viewer-primary-grid\s*"
        r"\{[^}]*grid-template-columns:\s*1fr",
        css,
        re.DOTALL,
    )
    assert re.search(
        r"@media\s*\(max-width:\s*560px\).*?\.viewer-kpi-grid.*?"
        r"\{[^}]*grid-template-columns:\s*1fr",
        css,
        re.DOTALL,
    )
    assert re.search(
        r":focus-visible[^\{]*\{[^}]*outline:\s*[^;]+;[^}]*outline-offset:",
        css,
        re.DOTALL,
    )
    assert re.search(
        r"@media\s*\(prefers-reduced-motion:\s*reduce\).*?"
        r"animation-duration:\s*0\.01ms\s*!important;.*?"
        r"transition-duration:\s*0\.01ms\s*!important;",
        css,
        re.DOTALL,
    )


def test_viewer_boundary_and_tab_entrypoint_contracts_are_present() -> None:
    viewer_path = WEB_ROOT / "dashboard-viewer.js"
    assert viewer_path.is_file()
    viewer_source = viewer_path.read_text(encoding="utf-8")
    dashboard_source = (WEB_ROOT / "dashboard.js").read_text(encoding="utf-8")

    for boundary in (
        "SF6DashboardViewer",
        "create",
        "renderAggregate",
        "renderFeed",
        "setRegionState",
        "bindInteractions",
    ):
        assert boundary in viewer_source

    for tab_contract in (
        "normalizeTabHash",
        '"#viewer"',
        '"#manage"',
        'setAttribute("aria-selected"',
        'setAttribute("tabindex"',
        ".hidden =",
        'addEventListener("click"',
        'addEventListener("hashchange"',
    ):
        assert tab_contract in dashboard_source


def test_dashboard_creates_the_exact_viewer_global_adapter_contract() -> None:
    dashboard_source = (WEB_ROOT / "dashboard.js").read_text(encoding="utf-8")
    viewer_source = (WEB_ROOT / "dashboard-viewer.js").read_text(encoding="utf-8")

    assert re.search(
        r"SF6DashboardViewer\.create\(\{\s*document,\s*metrics\s*\}\)",
        dashboard_source,
    )
    for method in (
        "renderAggregate",
        "renderFeed",
        "setRegionState",
        "bindInteractions",
    ):
        assert re.search(rf"\b{method}\s*\([^)]*\)\s*\{{", viewer_source)


def test_dashboard_uses_controller_adapters_preferences_and_settled_refresh() -> None:
    source = (WEB_ROOT / "dashboard.js").read_text(encoding="utf-8")

    for contract in (
        "applyViewerPreference",
        "applyObsOptions",
        "liveRecordingPresentation",
        "viewer_preferences",
        "set_viewer_preferences",
        "refreshRegions",
        'addEventListener("hashchange"',
    ):
        assert contract in source


def test_dashboard_refreshes_page_one_feed_and_scheduler_status_every_cycle() -> None:
    source = (WEB_ROOT / "dashboard.js").read_text(encoding="utf-8")

    assert 'getJson("/api/v1/obs")' in source
    assert 'getJson("/api/v1/matches/latest?page=1&page_size=25")' in source
    refresh_body = re.search(
        r"async function refresh\(\)\s*\{(?P<body>.*?)\n\}",
        source,
        re.DOTALL,
    )
    assert refresh_body is not None
    assert "auto_collection_status" in refresh_body.group("body")
