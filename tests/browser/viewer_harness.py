"""Deterministic, database-free browser harness for the real SF6Viewer UI assets.

This module is intentionally test-only.  It never imports application paths,
runs migrations, or opens a database; all selectable scenarios live in process
memory and expose only the same review-safe projections as the local read API.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from threading import Lock
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

HarnessState = Literal["empty", "populated", "partial-error", "post-reset"]

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_WEB_ROOT = _PROJECT_ROOT / "src" / "sf6viewer" / "interfaces" / "web"
_VALID_STATES: frozenset[str] = frozenset(
    {"empty", "populated", "partial-error", "post-reset"}
)
_state_lock = Lock()
_selected_state: HarnessState = "populated"

app = FastAPI(
    title="SF6Viewer deterministic browser harness",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.mount("/ui", StaticFiles(directory=_WEB_ROOT), name="ui")


def _match(index: int) -> dict[str, Any]:
    """Return one deterministic, safe match projection, newest index first."""

    characters = ("Ryu", "Ken", "Chun-Li", "Juri", "Cammy")
    opponent_character = characters[index % len(characters)]
    result = "WIN" if index % 3 else "LOSE"
    my_mr = 1_655 - index + (2 if result == "WIN" else -1)
    return {
        "id": f"browser-match-{index:03d}",
        "occurred_at_ms": 1_777_632_000_000 - index * 180_000,
        "occurred_at_source": "BUCKLER",
        "my_character": "Juri",
        "my_mr": my_mr,
        "my_lp": 25_000 + index,
        "opponent_name": f"Opponent {index:02d}",
        "opponent_character": opponent_character,
        "opponent_mr": 1_500 + (index % 100),
        "opponent_lp": 20_000 + index * 10,
        "result": result,
        "mr_delta": 12 if result == "WIN" else -9,
    }


_POPULATED_MATCHES = tuple(_match(index) for index in range(55))


def _mr_history() -> list[dict[str, Any]]:
    base = 1_500
    start_ms = 1_777_614_180_000
    history: list[dict[str, Any]] = []
    for index in range(100):
        result = "WIN" if index % 4 != 0 else "LOSE"
        history.append(
            {
                "match_id": f"history-{index:03d}",
                "occurred_at_ms": start_ms + index * 180_000,
                "mr": base + index,
                "opponent_name": f"History Rival {index:02d}",
                "opponent_character": ("Ryu", "Ken", "Juri", "Cammy")[index % 4],
                "result": result,
            }
        )
    return history


def _profile() -> dict[str, Any]:
    return {
        "id": "browser-profile-001",
        "display_name": "Harness Fighter",
        "character": "Juri",
        "rank_name": "Master",
        "mr": 1_655,
        "lp": 25_000,
        "observed_at_ms": 1_777_632_060_000,
    }


def _job() -> dict[str, Any]:
    return {
        "id": "browser-job-001",
        "type": "COLLECT",
        "reason": "SCHEDULED",
        "state": "SUCCEEDED",
        "phase": "COMPLETE",
        "requested_at_ms": 1_777_632_000_000,
        "started_at_ms": 1_777_632_001_000,
        "finished_at_ms": 1_777_632_003_000,
        "progress_current": 55,
        "progress_total": 55,
        "error_code": None,
        "diagnostic_id": None,
    }


def _populated_obs() -> dict[str, Any]:
    latest_match = deepcopy(_POPULATED_MATCHES[0])
    profile = _profile()
    return {
        "schema_version": "2",
        "status": "ok",
        "profile": profile,
        "viewer_profile": {
            "display_name": profile["display_name"],
            "character": profile["character"],
            "rank_name": profile["rank_name"],
            "mr": profile["mr"],
            "lp": profile["lp"],
        },
        "latest_match": latest_match,
        "latest_job": _job(),
        "statistics": {
            "recent_limit": 100,
            "total": {"wins": 120, "losses": 56},
            "recent": {"wins": 72, "losses": 28},
            "opponent_character": {"label": "Ryu", "wins": 7, "losses": 3},
            "opponent_player": {"label": "Opponent 00", "wins": 3, "losses": 2},
        },
        "session": {
            "started_at_ms": 1_777_620_000_000,
            "boundary_kind": "APP_START",
            "baseline_mr": 1_610,
            "current_mr": 1_655,
            "delta": 45,
            "decisive_matches": 12,
        },
        "streak": {"result": "WIN", "count": 3},
        "matchups": [
            {"character": "Ryu", "wins": 6, "losses": 4, "total": 10},
            {"character": "Ken", "wins": 5, "losses": 5, "total": 10},
            {"character": "Cammy", "wins": 4, "losses": 6, "total": 10},
        ],
        "mr_history": _mr_history(),
    }


def _empty_obs(*, reset: bool = False) -> dict[str, Any]:
    boundary_kind = "MATCH_RESET" if reset else "APP_START"
    return {
        "schema_version": "2",
        "status": "ok",
        "profile": None,
        "viewer_profile": None,
        "latest_match": None,
        "latest_job": None,
        "statistics": {
            "recent_limit": 100,
            "total": {"wins": 0, "losses": 0},
            "recent": {"wins": 0, "losses": 0},
            "opponent_character": None,
            "opponent_player": None,
        },
        "session": {
            "started_at_ms": 1_777_631_000_000 if reset else 1_777_620_000_000,
            "boundary_kind": boundary_kind,
            "baseline_mr": None,
            "current_mr": None,
            "delta": None,
            "decisive_matches": 0,
        },
        "streak": None,
        "matchups": [],
        "mr_history": [],
    }


def _post_reset_obs() -> dict[str, Any]:
    payload = _populated_obs()
    point = {
        "match_id": "post-reset-001",
        "occurred_at_ms": 1_777_632_000_000,
        "mr": 1_667,
        "opponent_name": "Reset Rival",
        "opponent_character": "Akuma",
        "result": "WIN",
    }
    payload["session"] = {
        "started_at_ms": 1_777_631_000_000,
        "boundary_kind": "MATCH_RESET",
        "baseline_mr": 1_655,
        "current_mr": 1_667,
        "delta": 12,
        "decisive_matches": 1,
    }
    payload["mr_history"] = [point]
    payload["matchups"] = [{"character": "Akuma", "wins": 1, "losses": 0, "total": 1}]
    payload["streak"] = {"result": "WIN", "count": 1}
    return payload


def _state() -> HarnessState:
    with _state_lock:
        return _selected_state


def _is_empty(state: HarnessState) -> bool:
    return state == "empty"


def _page(items: list[dict[str, Any]], page: int, page_size: int, total: int) -> dict[str, Any]:
    return {
        "items": deepcopy(items),
        "page": {"page": page, "page_size": page_size, "total": total},
    }


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(_WEB_ROOT / "dashboard.html")


@app.get("/obs", include_in_schema=False)
def obs_shortcut() -> FileResponse:
    return FileResponse(_WEB_ROOT / "obs.html")


@app.post("/__test__/state/{name}")
def select_state(name: str) -> dict[str, str]:
    if name not in _VALID_STATES:
        raise HTTPException(status_code=404, detail="unknown deterministic state")
    global _selected_state
    with _state_lock:
        _selected_state = name  # type: ignore[assignment]
    return {"state": name}


@app.get("/__test__/state")
def selected_state() -> dict[str, str]:
    return {"state": _state()}


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "sf6viewer"}


@app.get("/api/v1/system")
def system() -> dict[str, Any]:
    state = _state()
    count = 0 if _is_empty(state) else (1 if state == "post-reset" else 55)
    return {
        "status": "ok",
        "app_version": "browser-harness",
        "match_count": count,
        "profile_snapshot_count": 0 if _is_empty(state) else 1,
        "open_quarantine_count": 0 if _is_empty(state) else 1,
        "running_job_count": 0,
    }


@app.get("/api/v1/matches/latest")
def latest_matches(
    page: int = Query(default=1, ge=1, le=1_000),
    page_size: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    state = _state()
    if _is_empty(state):
        return _page([], page, page_size, 0)
    source = list(_POPULATED_MATCHES[:1] if state == "post-reset" else _POPULATED_MATCHES)
    start = (page - 1) * page_size
    items = source[start : start + page_size]
    # Page two intentionally repeats the page-one boundary record.  The extra
    # item proves the UI de-duplicates by stable id without reducing coverage of
    # the 55 distinct deterministic matches.
    if state != "post-reset" and page == 2 and page_size == 25:
        items = [source[24], *items]
    return _page(items, page, page_size, len(source))


@app.get("/api/v1/profile-snapshots")
def profiles(
    page: int = Query(default=1, ge=1, le=1_000),
    page_size: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    items = [] if _is_empty(_state()) else [_profile()]
    return _page(items, page, page_size, len(items))


@app.get("/api/v1/jobs")
def jobs(
    page: int = Query(default=1, ge=1, le=1_000),
    page_size: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    items = [] if _is_empty(_state()) else [_job()]
    return _page(items, page, page_size, len(items))


@app.get("/api/v1/quarantine")
def quarantines(
    page: int = Query(default=1, ge=1, le=1_000),
    page_size: int = Query(default=25, ge=1, le=100),
    status: str | None = None,
) -> dict[str, Any]:
    del status
    items = [] if _is_empty(_state()) else [
        {
            "id": "browser-quarantine-001",
            "reason_code": "PARSER.UNSUPPORTED_RECORD",
            "status": "OPEN",
            "created_at_ms": 1_777_631_900_000,
            "resolved_at_ms": None,
            "resolution_match_id": None,
        }
    ]
    return _page(items[:page_size], page, page_size, len(items))


@app.get("/api/v1/ingestion-runs")
def ingestions(
    page: int = Query(default=1, ge=1, le=1_000),
    page_size: int = Query(default=25, ge=1, le=100),
) -> dict[str, Any]:
    items = [] if _is_empty(_state()) else [
        {
            "id": "browser-ingestion-001",
            "job_id": "browser-job-001",
            "kind": "LIVE",
            "parser_version": "browser-harness",
            "state": "COMPLETED",
            "started_at_ms": 1_777_632_001_000,
            "finished_at_ms": 1_777_632_003_000,
            "raw_count": 55,
            "normalized_count": 55,
            "duplicate_count": 0,
            "quarantine_count": 1,
            "error_code": None,
            "diagnostic_id": None,
        }
    ]
    return _page(items[:page_size], page, page_size, len(items))


@app.get("/api/v1/obs", response_model=None)
def obs() -> dict[str, Any] | PlainTextResponse:
    state = _state()
    if state == "partial-error":
        # An intentionally malformed JSON body makes only the OBS projection
        # reject while avoiding a noisy failed-resource console error.  The UI
        # must retain its last-good aggregate just as it would on a transport
        # failure.
        return PlainTextResponse(
            "{",
            status_code=200,
            media_type="application/json",
        )
    if state == "empty":
        return _empty_obs()
    if state == "post-reset":
        return _post_reset_obs()
    return _populated_obs()
