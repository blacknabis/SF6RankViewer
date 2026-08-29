# SF6Viewer In-App Viewer Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a responsive in-app match viewer tab and configurable OBS MR delta while preserving every existing management workflow and safe API projection.

**Architecture:** Extend the read API additively, keep session aggregation in a focused `viewer_projection.py` service, and compute feed MR deltas in the existing paged route. Persist display preferences through narrow pywebview bridge methods. Split DOM-free calculations/state transitions, viewer DOM/SVG rendering, and existing management coordination into separate Vanilla JavaScript files.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLAlchemy/SQLite, Alembic, pywebview, Vanilla HTML/CSS/JavaScript, SVG, pytest, Node `node:test`, Playwright, Ruff.

---

## File Structure

- Create `src/sf6viewer/infrastructure/db/migrations/versions/0006_viewer_preferences.py`: preference columns and database constraints.
- Modify `src/sf6viewer/infrastructure/db/models/settings.py`: ORM mapping and matching constraints.
- Modify `src/sf6viewer/interfaces/runtime/desktop.py`: two validated preference bridge methods.
- Create `src/sf6viewer/interfaces/api/viewer_projection.py`: viewer Pydantic submodels with their own strict `ViewerApiModel` base (avoids importing `app.py`), synchronized session tracker, profile/streak/matchup/history projection.
- Modify `src/sf6viewer/interfaces/api/app.py`: compose viewer projection into `/obs` and add feed `mr_delta` query.
- Create `src/sf6viewer/interfaces/web/viewer-metrics.js`: DOM-free formatting, metrics, query normalization, URL construction, and feed merge helpers.
- Create `src/sf6viewer/interfaces/web/dashboard-controller.js`: injected async region refresh and feed paging state transitions.
- Create `src/sf6viewer/interfaces/web/dashboard-viewer.js`: viewer DOM/SVG rendering only.
- Modify `src/sf6viewer/interfaces/web/dashboard.js`: tabs, native bridge, controller wiring, and existing management actions.
- Modify dashboard and OBS HTML/CSS/JS assets.
- Create `tests/browser/viewer_harness.py` and `tests/browser/verify_viewer.py`: isolated deterministic browser server and Playwright verifier; never open the user's database.

## Chunk 1: Durable Settings and Safe Read Projections

### Task 1: Durable Viewer Preferences

**Files:**
- Create: `src/sf6viewer/infrastructure/db/migrations/versions/0006_viewer_preferences.py`
- Modify: `src/sf6viewer/infrastructure/db/models/settings.py`
- Modify: `src/sf6viewer/interfaces/runtime/desktop.py`
- Create: `tests/unit/interfaces/test_viewer_preferences.py`

- [ ] **Step 1: Write four failing tests**

Follow the existing `NativeLoginBridge` temporary-database fixture pattern. Add exactly:

```python
def test_viewer_preferences_default_when_settings_missing() -> None: ...
def test_viewer_preferences_persist_across_bridge_instances() -> None: ...
def test_viewer_preferences_reject_invalid_values_without_mutation() -> None: ...
def test_viewer_preference_migration_and_orm_constraints_match() -> None: ...
```

The invalid-input test independently tries modes `"SESSION"`, `" session"`, `"invalid"` and limits `True`, `19`, `49`, `101`, asserting each rejection preserves the last valid row. The last test runs `run_migrations(database_path)`, inspects `PRAGMA table_info(settings)`, then proves direct invalid `viewer_delta_mode` and `viewer_chart_limit` updates raise `sqlite3.IntegrityError`. Repeat the invalid-row assertion against `Base.metadata.create_all()` so migration and ORM schemas cannot drift.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/unit/interfaces/test_viewer_preferences.py -q`

Expected: 4 failed; failures name missing `viewer_preferences`, `set_viewer_preferences`, and missing viewer columns/constraints.

- [ ] **Step 3: Add matching ORM and migration schema**

Add both `CheckConstraint`s to `SettingsModel.__table_args__` and fields:

```python
viewer_delta_mode: Mapped[str] = mapped_column(
    Text, nullable=False, server_default="session"
)
viewer_chart_limit: Mapped[int] = mapped_column(
    Integer, nullable=False, server_default=text("50")
)
```

Revision `0006_viewer_preferences` revises `0005_match_character_index`, adds the same non-null defaults and checks `IN ('session','range')` and `IN (20,50,100)`. Downgrade removes checks before columns.

- [ ] **Step 4: Implement the narrow bridge contract**

Add:

```python
def viewer_preferences(self) -> dict[str, bool | str | int]: ...
def set_viewer_preferences(
    self, delta_mode: str, chart_limit: int
) -> dict[str, bool | str | int]: ...
```

Accepted modes are exact strings; accepted limits are exact non-boolean integers. Return only `ok`, `delta_mode`, and `chart_limit` on success. Invalid input/exception returns only `ok=False` and `code="INTERNAL.UNEXPECTED"`. A dedicated lock guards row creation/update, and rejected writes roll back without changing prior values.

- [ ] **Step 5: Verify GREEN**

Run: `uv run pytest tests/unit/interfaces/test_viewer_preferences.py tests/unit/interfaces/test_auto_collection.py -q`

Expected: 6 passed (4 new + 2 existing), exit code 0.

- [ ] **Step 6: Commit**

```bash
git add src/sf6viewer/infrastructure/db/migrations/versions/0006_viewer_preferences.py src/sf6viewer/infrastructure/db/models/settings.py src/sf6viewer/interfaces/runtime/desktop.py tests/unit/interfaces/test_viewer_preferences.py
git commit -m "feat: persist viewer display preferences"
```

### Task 2: Viewer Response Shape and Character-Aligned Profile

**Files:**
- Create: `src/sf6viewer/interfaces/api/viewer_projection.py`
- Modify: `src/sf6viewer/interfaces/api/app.py`
- Create: `tests/unit/interfaces/test_viewer_obs.py`

- [ ] **Step 1: Write four failing shape/profile tests**

Add exactly named tests containing the selector words `shape` or `profile`: empty response nullability; profile-only projection; match-only projection; mismatched latest profile/match character. Fix precedence in assertions:

- display name always comes from latest profile when one exists;
- active character comes from latest match, else profile;
- latest same-character match owns MR/LP even when either value is null;
- rank comes from profile only when profile character equals active character;
- with no same-character match, matching profile supplies rank/MR/LP;
- tie order is `occurred_at_ms DESC, id DESC`.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/unit/interfaces/test_viewer_obs.py -q -k "shape or profile"`

Expected: 4 failed because `viewer_profile`, `session`, `streak`, and `matchups` are absent.

- [ ] **Step 3: Add strict viewer submodels and profile projector**

Create frozen models with these stable field contracts:

```python
class ObsViewerProfile(ViewerApiModel):
    display_name: str | None
    character: str | None
    rank_name: str | None
    mr: int | None
    lp: int | None

class ObsSession(ViewerApiModel):
    started_at_ms: int
    boundary_kind: Literal["APP_START", "MATCH_RESET"]
    baseline_mr: int | None
    current_mr: int | None
    delta: int | None
    decisive_matches: int = Field(ge=0)
```

Also define `ObsStreak`, `ObsMatchupSummary`, and enriched `ObsMrPoint`. Define an independent `ViewerApiModel(BaseModel)` with `ConfigDict(extra="forbid", frozen=True)` so `viewer_projection.py` never imports `app.py`; `app.py` may import these leaf models without a cycle. `build_viewer_profile()` implements the fixed precedence above. Task 2 also adds `create_read_api(..., started_at_ms: int | None = None)`, captures real wall-clock milliseconds when omitted, constructs a minimal tracker, and emits an `ObsSession` with that start, `APP_START`, zero decisive matches, and null MR/delta fields. Task 3 fills in state transitions. `app.py` keeps top-level `ObsResponse` composition and existing schema version 2.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest tests/unit/interfaces/test_viewer_obs.py -q -k "shape or profile"`

Expected: 4 passed, all other tests deselected, exit code 0.

- [ ] **Step 5: Commit**

```bash
git add src/sf6viewer/interfaces/api/viewer_projection.py src/sf6viewer/interfaces/api/app.py tests/unit/interfaces/test_viewer_obs.py
git commit -m "feat: add viewer profile projection"
```

### Task 3: Process-Session Semantics

**Files:**
- Modify: `src/sf6viewer/interfaces/api/viewer_projection.py`
- Modify: `src/sf6viewer/interfaces/api/app.py`
- Modify: `tests/unit/interfaces/test_viewer_obs.py`

- [ ] **Step 1: Write six failing session tests**

Add six exact tests whose function names contain `session`: startup baseline/delta; absent character receiving multiple matches together (oldest is baseline); delayed pre-start match excluded from both current and delta; delayed post-start match included; unbounded decisive count over 100; in-process reset returning `boundary_kind="MATCH_RESET"` and a cleared/reseeded baseline.

Inject deterministic time via `create_read_api(session_factory, started_at_ms=...)`; production default is wall-clock milliseconds.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/unit/interfaces/test_viewer_obs.py -q -k session`

Expected: 6 failed with session values still null/default.

- [ ] **Step 3: Implement `ViewerSessionTracker`**

The tracker owns one lock, boundary time/kind, and `dict[str, int]` startup baselines. Seed once at app creation from visible latest non-null MR per character. On reset timestamp advancement, rebase, change kind, and clear. Candidate current MR is only immutable snapshot plus records strictly after boundary. An unseen character takes the oldest qualifying non-null MR by `(occurred_at_ms ASC, id ASC)`. Count decisive post-boundary matches with a separate unbounded SQL `COUNT`, never the recent-100 list.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest tests/unit/interfaces/test_viewer_obs.py -q -k session`

Expected: 6 passed, exit code 0.

- [ ] **Step 5: Commit**

```bash
git add src/sf6viewer/interfaces/api/viewer_projection.py src/sf6viewer/interfaces/api/app.py tests/unit/interfaces/test_viewer_obs.py
git commit -m "feat: track app-session MR movement"
```

### Task 4: Streak, Matchups, Enriched MR History, and Security

**Files:**
- Modify: `src/sf6viewer/interfaces/api/viewer_projection.py`
- Modify: `src/sf6viewer/interfaces/api/app.py`
- Modify: `tests/unit/interfaces/test_viewer_obs.py`
- Modify: `tests/unit/interfaces/test_obs_character_filter.py`

- [ ] **Step 1: Write five failing aggregate tests**

Add exactly five tests whose names contain at least one selected keyword `streak`, `matchup`, `history`, or `security`: winning/losing streak with draw termination; streak beyond 100; recent 100 decisive matchup window where draws do not consume slots; deterministic matchup order `total DESC, character ASC`; enriched MR history limited to newest 100 non-null points then returned chronological by `(occurred_at_ms ASC, id ASC)`, with forbidden raw/auth/hash keys recursively absent.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/unit/interfaces/test_viewer_obs.py -q -k "streak or matchup or history or security"`

Expected: 5 failed because aggregates/metadata are absent.

- [ ] **Step 3: Implement independent query scopes**

- Matchups: filter `result IN ('WIN','LOSE')` before newest-100 limit, group in memory, sort by fixed key.
- Streak: page newest active-character results in bounded chunks until draw/opposite/end; do not cap the possible count at 100.
- History: filter non-null MR, select newest 100 with timestamp/id descending, reverse for chronological response.
- Keep total/recent existing semantics unchanged and return only enumerated public normalized fields.

- [ ] **Step 4: Verify GREEN and compatibility**

Run: `uv run pytest tests/unit/interfaces/test_viewer_obs.py tests/unit/interfaces/test_obs_character_filter.py tests/unit/interfaces/test_match_reset.py -q`

Expected: 19 passed (15 new viewer tests + 3 existing character-filter tests + 1 reset test), exit code 0.

- [ ] **Step 5: Commit**

```bash
git add src/sf6viewer/interfaces/api/viewer_projection.py src/sf6viewer/interfaces/api/app.py tests/unit/interfaces/test_viewer_obs.py tests/unit/interfaces/test_obs_character_filter.py
git commit -m "feat: add viewer matchup and streak aggregates"
```

### Task 5: Same-Character Match Feed MR Delta

**Files:**
- Modify: `src/sf6viewer/interfaces/api/app.py`
- Create: `tests/unit/interfaces/test_match_mr_delta.py`

- [ ] **Step 1: Write four failing tests**

Add exactly: same-character predecessor across interleaved characters; skip null-MR predecessor; predecessor across page boundary; reset-hidden predecessor excluded. Strict older ordering is `(occurred_at_ms < current) OR (occurred_at_ms == current AND id < current.id)`.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/unit/interfaces/test_match_mr_delta.py -q`

Expected: 4 failed because `mr_delta` is absent.

- [ ] **Step 3: Implement one-query correlated projection**

Add `mr_delta: int | None = None` to `MatchResponse`. Change `_match_response(model, *, previous_mr=None)` to compute delta only when both are integers. `/matches/latest` selects `(MatchModel, previous_mr)` using one correlated aliased scalar subquery with account, same character, non-null MR, reset visibility, and strict tuple ordering. `/obs.latest_match` calls the same predecessor helper and returns its real delta rather than an arbitrary null.

- [ ] **Step 4: Verify GREEN and response callers**

Run: `uv run pytest tests/unit/interfaces/test_match_mr_delta.py tests/unit/interfaces/test_match_reset.py tests/unit/interfaces/test_obs_character_filter.py -q`

Expected: 8 passed (4 new delta tests + 1 reset test + 3 character-filter tests), exit code 0.

- [ ] **Step 5: Commit**

```bash
git add src/sf6viewer/interfaces/api/app.py tests/unit/interfaces/test_match_mr_delta.py
git commit -m "feat: expose safe match MR deltas"
```

## Chunk 2: In-App Viewer and OBS Presentation

### Task 6: DOM-Free Metrics and Async Viewer State

**Files:**
- Create: `src/sf6viewer/interfaces/web/viewer-metrics.js`
- Create: `src/sf6viewer/interfaces/web/dashboard-controller.js`
- Create: `tests/web/viewer-metrics.test.js`
- Create: `tests/web/dashboard-controller.test.js`

- [ ] **Step 1: Write 14 failing metric tests**

Use `node:test`/`node:assert/strict`. Cover win rate; null/one/flat/multi-point range delta and exact context (`—`, `0 MR`, signed values); 20/50/100 slicing; Korean relative time buckets; 45/55 matchup boundaries; OBS query fallback; exact URL builder output `http://127.0.0.1:8000/ui/obs.html?delta=session&limit=50`; immutable feed dedupe/sort; exhaustion from total/empty/short page. Prove OBS URL options are independent inputs from viewer preferences.

- [ ] **Step 2: Write six failing controller tests**

Specify exported functions and exact behavior:

```javascript
normalizeTabHash(hash) // '#viewer' or '#manage', otherwise '#viewer'
refreshRegions(requests, previous) // Promise.allSettled semantics; last-good retention
loadNextFeed(fetchPage, state) // inFlight true during call, false in finally
normalizeBridgePreferences(result) // strict defaults
```

Use injected resolved/rejected promises; assert one failed region does not overwrite other successful regions, page errors preserve items, shifted pages dedupe, and flags recover after rejection.

Use this exact state boundary in assertions:

```javascript
const previous = Object.freeze({
  regions: { obs: {value: {status: 'old'}, stale: false}, system: {value: null, stale: false} },
  feed: {items: [], nextPage: 1, total: 0, exhausted: false, inFlight: false},
  preferences: {deltaMode: 'session', chartLimit: 50}
});
```

`refreshRegions()` returns `{regions}` with fulfilled values replaced and rejected values preserved with `stale:true`. `loadNextFeed()` returns a full new feed object and always ends with `inFlight:false` or throws an error carrying `state` with recovered flags.

- [ ] **Step 3: Verify RED**

Run: `node --test tests/web/viewer-metrics.test.js tests/web/dashboard-controller.test.js`

Expected: two test files fail to load with `MODULE_NOT_FOUND`; exit code 1. Individual behavior counts become visible after the modules exist.

- [ ] **Step 4: Implement UMD/CommonJS modules**

Expose frozen `SF6ViewerMetrics` and `SF6ViewerController` on `globalThis` and `module.exports`. They must not access DOM/storage/network directly; every asynchronous operation is injected. Return new state objects rather than mutating inputs.

- [ ] **Step 5: Verify GREEN**

Run: `node --test tests/web/viewer-metrics.test.js tests/web/dashboard-controller.test.js`

Expected: 20 passed, 0 failed; exit code 0.

- [ ] **Step 6: Commit**

```bash
git add src/sf6viewer/interfaces/web/viewer-metrics.js src/sf6viewer/interfaces/web/dashboard-controller.js tests/web/viewer-metrics.test.js tests/web/dashboard-controller.test.js
git commit -m "feat: add viewer state and metric helpers"
```

### Task 7: Accessible Viewer/Manage Markup and Responsive CSS

**Files:**
- Modify: `src/sf6viewer/interfaces/web/dashboard.html`
- Modify: `src/sf6viewer/interfaces/web/dashboard.css`
- Create: `tests/unit/interfaces/test_dashboard_contract.py`

- [ ] **Step 1: Write four failing asset-contract tests**

Parse HTML and CSS. Add exact tests for: ARIA tab/panel relationships and default viewer; all viewer/KPI/chart/tooltip/feed/matchup IDs plus every pre-existing Manage ID; script order `viewer-metrics.js`, `dashboard-controller.js`, `dashboard-viewer.js`, `dashboard.js`; CSS presence of `@media (max-width: 900px)`, narrow fallback, `:focus-visible`, and `prefers-reduced-motion` rules.

Use these exact OBS builder IDs in Manage: `obs-delta-mode`, `obs-chart-limit`, existing `obs-url`, and existing `obs-copy`. Use separate viewer controls: `viewer-delta-mode`, `chart-limit-20`, `chart-limit-50`, `chart-limit-100`.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/unit/interfaces/test_dashboard_contract.py -q`

Expected: 4 failed naming missing tabs, viewer IDs/scripts, and responsive rules.

- [ ] **Step 3: Add semantic markup**

Add `role=tablist`, two buttons, and two labeled tabpanels. Default viewer is visible. Move existing markup byte-for-byte where practical into Manage without renaming IDs. Add live/empty regions and SVG tooltip status. Manage OBS selects default to session/50 and describe that they affect only the copied OBS URL.

- [ ] **Step 4: Add responsive glass/neon CSS**

Implement profile banner, four KPI cards, chart/feed grid, scrolling feed cards, matchup tier styles, tooltip, selected/focus tabs, 900px stacking, narrow 2/1-column fallbacks, and reduced-motion pulse/transition disabling. Keep management table overflow and button states legible.

- [ ] **Step 5: Verify GREEN**

Run: `uv run pytest tests/unit/interfaces/test_dashboard_contract.py -q`

Expected: 4 structural/style contract tests passed, exit code 0. Visual correctness is intentionally deferred to Chunk 3 Task 12, which asserts actual 1280×800 and 900×600 bounding boxes/screenshots rather than treating selector presence as visual proof.

- [ ] **Step 6: Commit**

```bash
git add src/sf6viewer/interfaces/web/dashboard.html src/sf6viewer/interfaces/web/dashboard.css tests/unit/interfaces/test_dashboard_contract.py
git commit -m "feat: add viewer and manage dashboard tabs"
```

### Task 8: Viewer Renderer and Dashboard Coordination

**Files:**
- Create: `src/sf6viewer/interfaces/web/dashboard-viewer.js`
- Modify: `src/sf6viewer/interfaces/web/dashboard.js`
- Modify: `src/sf6viewer/interfaces/web/dashboard-controller.js`
- Modify: `tests/unit/interfaces/test_dashboard_contract.py`
- Modify: `tests/web/dashboard-controller.test.js`

- [ ] **Step 1: Add three failing integration-contract tests**

Assert exact global renderer API `SF6DashboardViewer.create({document, metrics})`, and returned methods `renderAggregate`, `renderFeed`, `setRegionState`, `bindInteractions`. Assert dashboard source uses controller adapters, both preference bridge method names, hashchange, `Promise.allSettled` through controller, page size 25, and re-reads `auto_collection_status()` every refresh.

- [ ] **Step 2: Add three failing controller behavior tests**

Extend the DOM-free controller with these explicit injected APIs and test them directly:

```javascript
applyViewerPreference({state, deltaMode, chartLimit, persist, render})
applyObsOptions({deltaMode, chartLimit, renderUrl})
liveRecordingPresentation(autoStatus)
```

Assert saved viewer mode/limit calls `persist('range', 100)` and `render(newState)` without any fetch dependency; Manage OBS options call `renderUrl('http://127.0.0.1:8000/ui/obs.html?delta=range&limit=20')` and have no `persist` argument at all; absent/unsafe native status returns `{live:false, text:'자동 수집 상태 확인 불가'}` and never `LIVE RECORDING`.

- [ ] **Step 3: Verify RED in separate commands**

Run: `uv run pytest tests/unit/interfaces/test_dashboard_contract.py -q`

Expected: 3 new Python assertions fail; prior Python tests pass.

Run: `node --test tests/web/dashboard-controller.test.js`

Expected: 3 new controller assertions fail because the exported APIs are absent; prior Node tests pass.

- [ ] **Step 4: Implement viewer DOM/SVG renderer**

Render with created nodes and `textContent` only. Chart uses selected chronological points, flat-domain expansion, area/line, focusable point targets, and hover/focus tooltip containing date, opponent, character, MR, result. Exact delta text: unavailable `—`, positive `▲ +N MR`, negative `▼ -N MR`, zero `0 MR`; one-point range context is `기준 데이터 1건`. Feed uses server `mr_delta`; draw/missing use neutral styling. Matchup uses threshold helper.

- [ ] **Step 5: Wire tabs, bridge preferences, polling, paging, and OBS builder**

Normalize hash and ARIA/focus state. Restore/persist viewer preferences through bridge only. Fetch management resources, `/obs`, and feed page 1 via controller settled refresh. Preserve last-good regions. Refresh exact LIVE scheduler-enabled meaning each 12 seconds and after toggle. Load/merge next page with recovered busy state. Build Manage URL from independent selects as exact fixed-loopback URL; copying uses existing fallback.

- [ ] **Step 6: Verify GREEN and syntax**

Run: `uv run pytest tests/unit/interfaces/test_dashboard_contract.py -q`

Expected: all dashboard contract tests pass, exit code 0.

Run: `node --test tests/web/viewer-metrics.test.js tests/web/dashboard-controller.test.js`

Expected: 23 passed, 0 failed, exit code 0.

Run: `node --check src/sf6viewer/interfaces/web/dashboard.js && node --check src/sf6viewer/interfaces/web/dashboard-viewer.js && node --check src/sf6viewer/interfaces/web/dashboard-controller.js`

Expected: no output, exit code 0.

- [ ] **Step 7: Commit**

```bash
git add src/sf6viewer/interfaces/web/dashboard-viewer.js src/sf6viewer/interfaces/web/dashboard.js src/sf6viewer/interfaces/web/dashboard-controller.js tests/unit/interfaces/test_dashboard_contract.py tests/web/dashboard-controller.test.js
git commit -m "feat: render live in-app match viewer"
```

### Task 9: URL-Configured OBS Delta

**Files:**
- Modify: `src/sf6viewer/interfaces/web/obs.html`
- Modify: `src/sf6viewer/interfaces/web/obs.css`
- Modify: `src/sf6viewer/interfaces/web/obs.js`
- Create: `tests/unit/interfaces/test_obs_web_contract.py`

- [ ] **Step 1: Write five failing OBS contract tests**

Assert metrics script precedes OBS script; chart header has `obs-mr-delta` and `obs-delta-context`; source reads `delta`/`limit` through shared normalization; exact contexts include `APP START`, `SINCE RESET`, `LAST 20/50/100`, plus one-point range context `1 POINT`; CSS retains 1400×180 and four `220px` columns while reserving a chart header row.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/unit/interfaces/test_obs_web_contract.py -q`

Expected: 5 failed naming missing delta assets/logic.

- [ ] **Step 3: Implement OBS header and behavior**

Normalize URL once. Range mode slices MR history and uses range delta; session mode uses API session delta. Map boundary kind to accurate context. One range point renders `0 MR` with `1 POINT`, while no points render `— MR`. Render the same arrow/sign strings as the dashboard. Preserve four existing card bindings and 12-second polling.

- [ ] **Step 4: Verify GREEN and syntax**

Run: `uv run pytest tests/unit/interfaces/test_obs_web_contract.py -q`

Expected: 5 passed, exit code 0.

Run: `node --check src/sf6viewer/interfaces/web/obs.js && node --test tests/web/viewer-metrics.test.js`

Expected: syntax command emits no output; 14 metric tests pass; both exit 0.

- [ ] **Step 5: Commit**

```bash
git add src/sf6viewer/interfaces/web/obs.html src/sf6viewer/interfaces/web/obs.css src/sf6viewer/interfaces/web/obs.js tests/unit/interfaces/test_obs_web_contract.py
git commit -m "feat: add configurable OBS MR delta"
```

## Chunk 3: Isolated Browser and Full Regression Verification

### Task 10: Deterministic Browser Harness

**Files:**
- Create: `tests/browser/viewer_harness.py`
- Create: `tests/browser/verify_viewer.py`

- [ ] **Step 1: Create a test-only FastAPI harness**

Mount the real web assets and return fixed safe JSON for every dashboard read route. Include populated 55-match feed fixtures, MR history, all matchup tiers, session state, and existing management resources. Add harness-only `/__test__/state/{name}` to select `empty`, `populated`, `partial-error`, or `post-reset`. Store state in process memory only. Never import `AppPaths`, never call `run_migrations`, and never open a filesystem database.

- [ ] **Step 2: Create the Playwright verifier using `@playwright` guidance**

The repository already depends on Python Playwright, so this test-only Python harness is the explicit project-standard exception to terminal `playwright-cli`; before implementation, read the `@playwright` skill and retain its browser lifecycle, locator, screenshot, and console-error practices. `verify_viewer.py` accepts `--base-url` and `--output-dir`, launches installed Chromium, records every console error/page error, and performs exact assertions for:

- default/hash/keyboard tabs and ARIA state;
- chart 20/50/100, tooltip hover/focus, session/range delta, one-point/empty state;
- feed More/dedupe/exhaustion and matchup text/classes;
- partial-error last-good retention;
- Manage control presence and exact OBS URL output independence;
- a page `add_init_script` fake `window.pywebview.api` that records `login`, `set_auto_collection_enabled`, `collect_matches`, `clear_matches`, `ignore_legacy_quarantines`, preference, and status calls; override confirmation to accept, hold each returned promise once to assert busy/disabled state, then resolve and assert `finally` recovery and exact method arguments;
- OBS session/range/post-reset context.

Capture `viewer-1280x800.png`, `viewer-900x600.png`, `manage-900x600.png`, and `obs-session-1400x180.png`. Fail if any screenshot has horizontal document overflow, if required elements overlap by bounding-box assertions, or if console/page error arrays are non-empty.

- [ ] **Step 3: Syntax-check the harness**

Run: `uv run python -m py_compile tests/browser/viewer_harness.py tests/browser/verify_viewer.py`

Expected: no output, exit code 0.

- [ ] **Step 4: Commit the harness**

```bash
git add tests/browser/viewer_harness.py tests/browser/verify_viewer.py
git commit -m "test: add isolated viewer browser verification"
```

### Task 11: Automated Regression Commands

**Files:**
- Test only; production changes require a focused RED/GREEN regression before continuation.

- [ ] **Step 1: Run unit suite**

Run: `uv run pytest tests/unit`

Expected: exit code 0 and pytest summary contains only passed tests (no failed/error).

- [ ] **Step 2: Run Ruff**

Run: `uv run ruff check src tests`

Expected: `All checks passed!`, exit code 0.

- [ ] **Step 3: Run JavaScript tests**

Run: `node --test tests/web/viewer-metrics.test.js tests/web/dashboard-controller.test.js`

Expected: 23 passed, 0 failed, exit code 0.

- [ ] **Step 4: Run JavaScript syntax checks**

Run: `node --check src/sf6viewer/interfaces/web/dashboard.js && node --check src/sf6viewer/interfaces/web/dashboard-viewer.js && node --check src/sf6viewer/interfaces/web/dashboard-controller.js && node --check src/sf6viewer/interfaces/web/obs.js`

Expected: no output, exit code 0.

### Task 12: Responsive and Interaction Verification

**Files:**
- Read: browser assets and screenshots.
- Temporary artifacts: `%TEMP%\sf6viewer-browser-artifacts\*.png`

- [ ] **Step 0: Provision the declared browser prerequisite**

Run: `uv run playwright install chromium`

Expected: exit code 0; Chromium is reported installed or already present with no installation error.

- [ ] **Step 1: Start isolated harness in a dedicated terminal session**

Run: `uv run uvicorn tests.browser.viewer_harness:app --host 127.0.0.1 --port 8765`

Expected: Uvicorn reports listening on `http://127.0.0.1:8765`; retain the returned terminal session ID.

- [ ] **Step 2: Confirm readiness without touching user data**

Run: `Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8765/api/v1/health | Select-Object -ExpandProperty StatusCode`

Expected: `200`.

- [ ] **Step 3: Run deterministic Playwright verification and screenshots**

Run: `uv run python tests/browser/verify_viewer.py --base-url http://127.0.0.1:8765 --output-dir "$env:TEMP\sf6viewer-browser-artifacts"`

Expected: prints `viewer browser verification passed`, creates the four named PNGs, exits 0.

- [ ] **Step 4: Stop the exact harness terminal session**

Send Ctrl+C to the session returned by Step 1 and wait for exit.

Expected: Uvicorn shutdown completes and port 8765 no longer listens.

- [ ] **Step 5: Inspect responsive artifacts**

Open each of the four named PNGs. Acceptance: no clipped text/control, no horizontal overflow, KPI cards remain readable, chart/feed stack at 900×600, focus/active states are visible, OBS remains within 1400×180.

- [ ] **Step 6: Handle any discovered defect with exact TDD loop**

Stop execution before editing and append a concrete numbered sub-step to this tracked plan naming the fully resolved test path, fully resolved production path, exact RED/GREEN command, named expected RED assertion, expected GREEN count, and a fully literal `git add --` command covering this plan plus those two resolved paths. The appended command must contain no variables, wildcards, angle-bracket tokens, or unresolved names. Only then add the failing test, observe RED, patch the named production file, observe GREEN, stage those exact files, commit the fix together with the execution-note amendment, and repeat Tasks 11 and 12 from Step 0. This rule forbids unplanned defect edits.

1. **Step 6.1 — Screenshot determinism regression:** Add the focused regression at `tests/unit/interfaces/test_browser_verifier_regression.py`; patch the resolved browser-verifier paths `tests/browser/verify_viewer.py` and `tests/browser/viewer_harness.py`. If the required 1400×180 landmark containment assertion proves the existing overlay itself exceeds its declared viewport, patch the thereby resolved production layout path `src/sf6viewer/interfaces/web/obs.css`. RED command: `uv run pytest tests/unit/interfaces/test_browser_verifier_regression.py -q`. Expected RED assertion: collection fails with `ImportError: cannot import name 'screenshot_capture_contract' from 'verify_viewer'`. GREEN command: `uv run pytest tests/unit/interfaces/test_browser_verifier_regression.py -q`. Expected GREEN count: `3 passed`. Stage only the execution note, resolved regression, resolved verifier/harness paths, and proven OBS layout path with `git add -- docs/superpowers/plans/2026-08-29-in-app-viewer.md tests/unit/interfaces/test_browser_verifier_regression.py tests/browser/verify_viewer.py tests/browser/viewer_harness.py src/sf6viewer/interfaces/web/obs.css`, then commit them together before repeating the complete browser verification.

### Task 13: Final Diff and Completion Evidence

**Files:**
- Inspect all paths listed in this plan.

- [ ] **Step 1: Check committed and working-tree whitespace**

The fixed pre-implementation base commit is `c430b5e`. Run:

```powershell
git diff --check "c430b5e...HEAD"
git diff --check
```

Expected: both commands emit no output and exit 0.

- [ ] **Step 2: Check worktree scope**

Run: `git status --short`

Expected: empty after planned commits, or only explicitly named TDD defect files awaiting the next exact commit.

- [ ] **Step 3: Review safe projection and preserved controls**

Inspect the final diff from `c430b5e`. Confirm response models enumerate only normalized public fields, no raw/auth/hash/source-reference data was added, all original management IDs/native method calls remain, and no generated cache/screenshot/database is staged.

- [ ] **Step 4: Confirm defect fixes were already committed exactly once**

If Task 12 Step 6 was used, confirm its concrete sub-step already committed the plan amendment, named regression test, and named production fix together. Run `git status --short` and require empty output. Do not issue another commit command and never create an empty commit.
