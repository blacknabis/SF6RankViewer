# SF6Viewer In-App Viewer Design

## Summary

Add a default `#viewer` tab to the existing pywebview dashboard and move every existing login, collection, cleanup, OBS URL, run-history, and system-status control into a `#manage` tab without changing its behavior. The viewer presents the current profile, live collection state, four KPIs, an interactive MR chart, a paged match feed, and opponent-character matchup summaries. The OBS overlay gains an MR delta label integrated into the chart header and supports URL-selected delta semantics.

The implementation remains Vanilla HTML/CSS/JavaScript and extends the existing loopback-only FastAPI read projection. No raw evidence, authentication material, canonical hashes, or unbounded job summaries may enter a response.

## Decisions

- `#viewer` is the default route; `#manage` preserves all current management controls.
- The active tab is represented by the URL hash and restored on reload. Unknown hashes normalize to `#viewer`.
- Session delta has two modes:
  - `session`: latest MR minus the MR captured for that character when this app process started.
  - `range`: last MR minus first MR in the selected 20/50/100-match chart window.
- Both delta values are maintained at the same time so switching modes is immediate.
- The in-app choice is persisted through the pywebview bridge into the SQLite singleton settings row. It survives `private_mode=True` window recreation and app restarts, and does not silently alter OBS.
- OBS receives independent URL options: `delta=session|range` and `limit=20|50|100`. Invalid or absent values fall back to `delta=session` and `limit=50`.
- The Manage tab constructs and copies the complete OBS URL from those options.
- OBS places the selected delta in the MR chart header. Existing four statistic cards keep their current width.
- Matchup labels use decisive matches only: favored at 55% or above, even at 45% through below 55%, and unfavored below 45%.
- The current streak stops at a draw or at the first opposite decisive result.

## Architecture

### 1. Read projection and process session state

`src/sf6viewer/interfaces/api/app.py` keeps `/api/v1/obs` as the single aggregate projection and extends it additively. Existing fields and `schema_version: "2"` remain unchanged so deployed OBS pages continue to bind successfully.

A small process-local session tracker is created with the FastAPI app. At API creation it records `started_at_ms` and snapshots the latest known MR for each character from visible, non-reset match history. “Post-start” is determined by canonical match `occurred_at_ms`, not ingestion time: a delayed match that occurred before startup cannot change the session, while a match that occurred after startup is included whenever collected. Current MR is the newest visible, non-null MR for the active character by `(occurred_at_ms, id)`.

For a character with no startup baseline, the tracker uses the oldest visible, non-null post-start MR as baseline. If several matches arrive in one collection, the oldest becomes baseline and the newest becomes current, retaining their within-session movement. Once chosen, a baseline never moves during ordinary reloads or delayed collection. An explicit match reset is also a viewer-session boundary: when `match_reset_at_ms` advances beyond the tracker start, the tracker adopts the reset timestamp, clears its baselines, and applies the same first-observed rule to subsequent visible matches. Access is synchronized because FastAPI sync handlers may execute in multiple worker threads.

The extended safe response contains:

- `viewer_profile`: account display name plus character-aligned rank/MR/LP presentation. Character is the resolved active character. MR/LP come from its newest visible match; profile MR/LP/rank are used only when the latest profile character matches. Mismatched character-specific fields are `null`.
- `session`: effective start/reset time, active-character baseline MR, current MR, signed delta, and the number of decisive matches whose occurrence time follows that boundary.
- `streak`: `WIN` or `LOSE` and its positive count, or `null` when there is no decisive current streak.
- `matchups`: opponent character, wins, losses, and total for the active character's recent 100 decisive matches.
- enriched `mr_history` points: match ID, timestamp, MR, opponent name, opponent character, and result. These are already-public normalized match fields and contain no source evidence.

The active character continues to follow the current rule: latest match character, falling back to the latest profile character. The existing unfiltered `profile` field remains for compatibility, while the dashboard banner binds to `viewer_profile`. Viewer profile, total, recent, matchup, streak, session, and MR history therefore describe one consistent character context.

The existing `/api/v1/matches/latest` projection gains nullable `mr_delta`. It is `my_mr` minus the closest strictly older non-null MR for the same `my_character` within visible, non-reset history. The query obtains that look-behind with a correlated SQL subquery, so page boundaries, other characters, and intervening null-MR records cannot corrupt the value and no per-row N+1 query is introduced.

The response additions have this representative shape (existing fields are abbreviated):

```json
{
  "schema_version": "2",
  "profile": { "id": "...", "character": "Juri" },
  "viewer_profile": {
    "display_name": "Player",
    "character": "Juri",
    "rank_name": "Master",
    "mr": 1642,
    "lp": null
  },
  "session": {
    "started_at_ms": 1787972400000,
    "baseline_mr": 1597,
    "current_mr": 1642,
    "delta": 45,
    "decisive_matches": 8
  },
  "streak": { "result": "WIN", "count": 3 },
  "matchups": [
    { "character": "Ken", "wins": 7, "losses": 5, "total": 12 }
  ],
  "mr_history": [
    {
      "match_id": "...",
      "occurred_at_ms": 1787972500000,
      "mr": 1609,
      "opponent_name": "Rival",
      "opponent_character": "Ken",
      "result": "WIN"
    }
  ]
}
```

When unavailable, `viewer_profile`, `session.baseline_mr`, `session.current_mr`, `session.delta`, and `streak` use explicit JSON `null`; arrays remain present and empty.

### 2. Dashboard presentation

`src/sf6viewer/interfaces/web/dashboard.html` introduces an accessible tablist and two tabpanels:

- Viewer: profile/live banner, four KPI cards, MR chart/filter/tooltip, match feed/load-more control, and matchup grid.
- Manage: the existing notice, Buckler login, collection controls, reset/cleanup controls, OBS URL panel, system summaries, profile/match/job/quarantine summaries, and ingestion table. Existing element IDs remain stable.

The viewer hierarchy at 1280×800 is:

1. Profile and live-recording banner.
2. Four equal KPI cards: Total, Recent 100, Session Delta, Streak.
3. MR chart and match feed in a wide/narrow two-column grid.
4. Matchup summary grid.

At 900×600, the chart and feed stack vertically. At narrower sizes, KPI and matchup cards reduce to two columns and then one column. Panels use translucent surfaces, restrained blur, emerald/cyan accents, coral loss accents, and visible focus rings. `prefers-reduced-motion` disables the live pulse and transition motion.

`LIVE RECORDING` has one exact meaning: the durable automatic-collection scheduler preference is enabled. It does not claim a network request is active or that the last request succeeded. The dashboard re-reads `auto_collection_status()` through the bridge on every 12-second refresh and updates immediately after a successful toggle, so scheduler changes within the process reach both tabs. In a browser without the native bridge it shows a neutral unavailable/stopped state rather than claiming collection is active.

Because pywebview runs with `private_mode=True`, viewer preferences do not depend on `localStorage`. Two safe bridge methods, `viewer_preferences()` and `set_viewer_preferences(delta_mode, chart_limit)`, read and update validated `viewer_delta_mode` and `viewer_chart_limit` columns on `SettingsModel`. An Alembic migration adds defaults (`session`, `50`) and database check constraints. Invalid bridge arguments fail closed without modifying settings.

### 3. Dashboard behavior boundaries

`src/sf6viewer/interfaces/web/dashboard.js` keeps native bridge mutations separate from read rendering:

- Tab controller validates the hash, updates `aria-selected`, focusability, and panel visibility, and listens for hash changes.
- Viewer state stores the selected chart limit, selected delta mode, loaded feed pages, and last successful aggregate payload.
- Pure formatting/metric helpers calculate win rate, range delta, relative time, matchup tier, query normalization, and duplicate-free feed merging.
- SVG chart rendering maps the selected chronological points into a responsive viewBox, creates an area and line, and creates focusable point targets. Hover or keyboard focus shows timestamp, opponent, character, MR, and result.
- Feed rendering uses each public match record's projected `mr_delta`, labels a missing change as `—`, and renders relative time. The API—not page-local JavaScript—owns same-character predecessor semantics.
- Matchup rendering consumes the server aggregate so clicking “more” does not change matchup statistics.

The 12-second refresh requests management resources, `/api/v1/obs`, and match feed page 1 concurrently with settled-result handling. A failure only marks its own region stale and retains the last good data for other regions. The global connection indicator reports complete success versus partial/retry state without erasing content.

The initial feed loads 25 records. “More” requests the next offset page, merges by immutable match ID, and keeps already-expanded history when periodic page-1 refreshes introduce new matches. The button is hidden when the number of unique loaded records reaches the server total, or when the last response is empty/short; either signal may establish exhaustion when offset pages shift. It is disabled while a request is in flight.

### 4. OBS behavior

`src/sf6viewer/interfaces/web/obs.js` reads `delta` and `limit` from `URLSearchParams`, normalizes them to the supported values, and continues polling `/api/v1/obs` every 12 seconds.

- `session` displays the API-provided signed session delta.
- `range` slices the chronological MR history to the chosen limit and computes first-to-last delta.
- The chart uses the same selected 20/50/100 history.
- The delta label includes an up/down/flat symbol, signed MR value, and `APP START` or `LAST N` context.
- Missing MR data renders `— MR` without throwing or changing existing cards.

`src/sf6viewer/interfaces/web/obs.html` adds the delta label inside the chart header. `obs.css` reserves a compact header row above the existing plot while retaining the 1400×180 canvas and existing four-card geometry.

## Data and State Flow

1. Desktop startup builds the read API and captures immutable per-character MR baselines.
2. Dashboard startup normalizes the hash, restores viewer preferences through the bridge, probes authentication/auto-collection state, and runs the first refresh.
3. `/api/v1/obs` produces one active-character aggregate payload. `/api/v1/matches/latest` supplies feed cards.
4. Viewer rendering derives display-only values from safe payloads and updates both hidden and visible tabs so tab switches are instant.
5. A viewer option change re-renders from the last payload without a network request.
6. A Manage-tab OBS option change only rebuilds the URL. OBS behavior changes when that URL is used or its source is refreshed.
7. Periodic refresh replaces aggregate state, merges the newest feed page, and leaves selected options intact.

## Empty, Error, and Edge States

- No profile and no matches: show a first-run empty state in the profile banner, zero W/L rates, no delta, no streak, empty chart/feed/matchups.
- Profile but no matches: show the profile character/rank/MR/LP when present; match-derived components remain empty.
- Null MR/LP: never coerce to zero. Render `—` and exclude null MR points from delta/chart arithmetic.
- Flat MR range: expand the SVG y-domain visually so a valid horizontal line is still visible; numerical delta remains zero.
- One MR point: render a point, but range delta is zero with an explicit insufficient-history context.
- Draw: display it in the feed with neutral styling; exclude it from W/L rates and stop streak traversal.
- Partial API failure: keep last good content and show a localized retry message. Controls recover after `finally` cleanup.
- Duplicate or shifting offset pages: de-duplicate by match ID. Page totals only control whether more data may exist.
- Match reset while the app is running: clear viewer history on the next refresh and rebase the process-local tracker to the reset timestamp; new character baselines follow the first-observed rule.
- Unsupported OBS parameters: use documented defaults and never surface raw input in the DOM.
- Tooltip accessibility: SVG targets are keyboard focusable and tooltip content is mirrored through an ARIA live/status region.

## Security and Compatibility

- The API remains loopback-only, read-only, without CORS, docs, auth mutation, or raw-evidence routes.
- Response models remain strict and enumerate every new field.
- Existing `/api/v1/obs` fields and schema version remain valid; additions are backward-compatible.
- Rendering uses `textContent` and created DOM nodes, not API-derived `innerHTML`.
- Existing management IDs, event listeners, native bridge method names, and confirmation flows remain unchanged.
- New preference bridge methods validate exact enums/integers and expose no generic settings or database access.
- The OBS URL builder only emits the fixed current loopback origin, `/ui/obs.html`, and normalized known query values.

## Test Strategy

Implementation follows red-green-refactor for each behavior.

### API unit tests

- Empty database response shape and null session values.
- Startup baseline capture and immutability across later refreshes.
- First-observed baseline for a character absent at startup, including multiple matches arriving together.
- Occurrence-time semantics for delayed pre-start and post-start ingestion.
- In-process match reset rebasing.
- Active-character filtering shared by totals, recent, session, streak, history, and matchups.
- Character-aligned viewer profile behavior when the latest profile and match characters differ.
- Current winning and losing streaks, including draw termination.
- Matchup aggregation and decisive-match semantics.
- Enriched history order and 100-point bound.
- Same-character `mr_delta` look-behind across page boundaries, other characters, and null MR records.
- Strict projection check proving auth material, raw evidence, source references, and hashes are absent.
- Existing OBS compatibility assertions continue to pass.

### Frontend logic and DOM contract tests

- Win-rate, range-delta, relative-time, matchup-tier, query-normalization, and feed-merge/exhaustion edge cases.
- Required tab roles, panels, chart controls, tooltip status, feed control, and all existing Manage IDs.
- OBS chart header/delta elements and the supported parameter contract.
- Preference bridge validation, durable SQLite round-trip, and safe defaults.

Pure JavaScript helpers are isolated from DOM mutation in `viewer-metrics.js` and tested with Node's built-in `node:test` runner via `node --test tests/web/viewer-metrics.test.js`; no frontend framework or npm dependency is introduced. Markup and bridge contracts remain under `tests/unit/interfaces` and run with the required pytest suite.

### Browser verification

- No console errors during initial load, polling, tab changes, filter changes, tooltip hover/focus, and load more.
- 1280×800 and 900×600 screenshots confirm no clipping or overlap.
- Hash reload restores the selected tab.
- Session/range switching is immediate and preserves the app-session value.
- OBS URLs for both modes render the correct delta label and history window.
- Login, auto-collection toggle, manual collection, reset, cleanup, and OBS copy retain their prior bridge calls and busy-state behavior.

### Regression commands

- `uv run pytest tests/unit`
- `uv run ruff check src tests`
- `node --test tests/web/viewer-metrics.test.js`

## Out of Scope

- Character portrait/image asset acquisition.
- Persistent cross-process session history.
- New write endpoints or remote access.
- Changing the OBS canvas size.
- Replacing offset pagination with a cursor API.
- Refactoring unrelated dashboard management or collection code.
