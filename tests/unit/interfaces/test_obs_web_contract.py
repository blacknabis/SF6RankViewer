"""Structural contracts for the URL-configured OBS overlay."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

WEB_ROOT = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "sf6viewer"
    / "interfaces"
    / "web"
)


class _ObsParser(HTMLParser):
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


def _obs() -> _ObsParser:
    parser = _ObsParser()
    parser.feed((WEB_ROOT / "obs.html").read_text(encoding="utf-8"))
    return parser


def test_obs_loads_shared_metrics_before_overlay_entrypoint() -> None:
    obs = _obs()

    assert obs.scripts == [
        "/ui/viewer-metrics.js", "/ui/dashboard-controller.js", "/ui/obs.js"
    ]


def test_obs_chart_header_exposes_delta_and_context_bindings() -> None:
    obs = _obs()

    delta_tag, delta = obs.element("obs-mr-delta")
    context_tag, context = obs.element("obs-delta-context")
    assert delta_tag == "strong"
    assert context_tag == "span"
    assert delta.get("aria-label") == "MR 변동"
    assert context.get("aria-label") == "MR 변동 기준"


def test_obs_normalizes_delta_mode_and_chart_limit_once_with_shared_metrics() -> None:
    source = (WEB_ROOT / "obs.js").read_text(encoding="utf-8")

    assert "SF6ViewerMetrics" in source
    assert len(re.findall(r"normalizeObsOptions\s*\(", source)) == 1
    assert "window.location.search" in source
    assert "options.deltaMode" in source
    assert "options.chartLimit" in source
    assert "sliceMrHistory" in source
    assert "rangeDelta" in source


def test_obs_declares_exact_session_range_and_one_point_contexts() -> None:
    source = (WEB_ROOT / "obs.js").read_text(encoding="utf-8")

    for label in (
        '"APP START"',
        '"SINCE RESET"',
        '"LAST 20"',
        '"LAST 50"',
        '"LAST 100"',
        '"1 POINT"',
        '"— MR"',
        '"0 MR"',
    ):
        assert label in source


def test_obs_layout_keeps_canvas_cards_and_reserves_compact_chart_header() -> None:
    css = (WEB_ROOT / "obs.css").read_text(encoding="utf-8")

    assert re.search(r"html,\s*body\s*\{[^}]*width:\s*1400px;[^}]*height:\s*180px", css)
    assert re.search(
        r"\.stats-row\s*\{[^}]*grid-template-columns:\s*repeat\(4,\s*220px\)",
        css,
    )
    assert re.search(r"\.mr-chart\s*\{[^}]*display:\s*flex;[^}]*flex-direction:\s*column", css)
    assert re.search(r"\.mr-chart-header\s*\{[^}]*display:\s*flex", css)
    assert re.search(r"\.mr-chart-plot\s*\{[^}]*flex:\s*1", css)
