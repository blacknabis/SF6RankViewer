"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const controller = require("../../src/sf6viewer/interfaces/web/dashboard-controller.js");

test("normalizeTabHash accepts only viewer and manage", () => {
  assert.equal(controller.normalizeTabHash("#viewer"), "#viewer");
  assert.equal(controller.normalizeTabHash("#manage"), "#manage");
  assert.equal(controller.normalizeTabHash("viewer"), "#viewer");
  assert.equal(controller.normalizeTabHash("#unknown"), "#viewer");
  assert.equal(controller.normalizeTabHash(null), "#viewer");
});

test("refreshRegions stores every fulfilled request as fresh data", async () => {
  const previous = Object.freeze({
    regions: { obs: { value: { old: true }, stale: true } },
    feed: { items: [{ id: "kept" }], nextPage: 2, total: 3, exhausted: false, inFlight: false },
    preferences: { deltaMode: "range", chartLimit: 100 }
  });
  const next = await controller.refreshRegions({
    obs: async () => ({ status: "ok" }),
    system: Promise.resolve({ match_count: 2 })
  }, previous);

  assert.deepEqual(next, {
    regions: {
      obs: { value: { status: "ok" }, stale: false },
      system: { value: { match_count: 2 }, stale: false }
    },
    feed: { items: [{ id: "kept" }], nextPage: 2, total: 3, exhausted: false, inFlight: false },
    preferences: { deltaMode: "range", chartLimit: 100 }
  });
  assert.notEqual(next, previous);
  assert.notEqual(next.regions, previous.regions);
});

test("refreshRegions retains last-good data and marks only rejected regions stale", async () => {
  const previous = Object.freeze({
    regions: {
      obs: { value: { status: "old" }, stale: false },
      system: { value: { match_count: 1 }, stale: false }
    },
    feed: { items: [], nextPage: 1, total: 0, exhausted: false, inFlight: false },
    preferences: { deltaMode: "session", chartLimit: 50 }
  });
  const next = await controller.refreshRegions({
    obs: async () => { throw new Error("offline"); },
    system: async () => ({ match_count: 2 })
  }, previous);

  assert.deepEqual(next.regions.obs.value, { status: "old" });
  assert.equal(next.regions.obs.stale, true);
  assert.deepEqual(next.regions.system, { value: { match_count: 2 }, stale: false });
  assert.deepEqual(previous.regions.obs, { value: { status: "old" }, stale: false });
});

test("loadNextFeed merges a page and always clears inFlight on success", async () => {
  const state = {
    items: [{ id: "a", occurred_at_ms: 10 }], nextPage: 2,
    total: 3, exhausted: false, inFlight: false
  };
  let pageSeen;
  let resolvePage;
  const pageResponse = new Promise((resolve) => { resolvePage = resolve; });
  const transitions = [];
  const operation = controller.loadNextFeed(async (page) => {
    pageSeen = page;
    return pageResponse;
  }, state, (transition) => { transitions.push(transition); });

  assert.equal(transitions[0].inFlight, true);
  resolvePage({
    items: [{ id: "b", occurred_at_ms: 20 }, { id: "a", occurred_at_ms: 10 }],
    page: { page: 2, page_size: 2, total: 3 }
  });
  const next = await operation;

  assert.equal(pageSeen, 2);
  assert.deepEqual(next.items.map((item) => item.id), ["b", "a"]);
  assert.equal(next.nextPage, 3);
  assert.equal(next.exhausted, false);
  assert.equal(next.inFlight, false);
  assert.deepEqual(transitions[1], next);
  assert.deepEqual(Object.keys(next).sort(), ["exhausted", "inFlight", "items", "nextPage", "total"]);
  assert.deepEqual(state.items, [{ id: "a", occurred_at_ms: 10 }]);
});

test("loadNextFeed throws with recovered immutable state after rejection", async () => {
  const state = {
    items: [{ id: "a", occurred_at_ms: 10 }], nextPage: 2,
    total: 100, exhausted: false, inFlight: false
  };
  await assert.rejects(
    controller.loadNextFeed(async () => { throw new Error("timeout"); }, state),
    (error) => {
      assert.equal(error.message, "timeout");
      assert.notEqual(error.state, state);
      assert.notEqual(error.state.items, state.items);
      assert.deepEqual(error.state, state);
      assert.equal(error.state.inFlight, false);
      return true;
    }
  );
  assert.equal(state.inFlight, false);
});

test("loadNextFeed recovers when the pending transition throws synchronously", async () => {
  const state = {
    items: [{ id: "a", occurred_at_ms: 10 }], nextPage: 2,
    total: 100, exhausted: false, inFlight: false
  };
  const transitions = [];

  await assert.rejects(
    controller.loadNextFeed(async () => assert.fail("fetch must not run"), state, (next) => {
      transitions.push(next);
      if (next.inFlight) throw new Error("sync render failed");
    }),
    (error) => {
      assert.equal(error.message, "sync render failed");
      assert.deepEqual(error.state, state);
      return true;
    }
  );
  assert.deepEqual(transitions.map((next) => next.inFlight), [true, false]);
});

test("loadNextFeed awaits async transitions and recovers when completion rendering rejects", async () => {
  const state = {
    items: [{ id: "a", occurred_at_ms: 10 }], nextPage: 2,
    total: 2, exhausted: false, inFlight: false
  };
  const transitions = [];

  await assert.rejects(
    controller.loadNextFeed(async () => ({
      items: [{ id: "b", occurred_at_ms: 20 }],
      page: { page: 2, page_size: 1, total: 2 }
    }), state, async (next) => {
      transitions.push(next);
      if (!next.inFlight) {
        throw new Error("async render failed");
      }
    }),
    (error) => {
      assert.equal(error.message, "async render failed");
      assert.deepEqual(error.state, state);
      return true;
    }
  );
  assert.deepEqual(transitions.map((next) => next.inFlight), [true, false, false]);
});

test("loadNextFeed rejects malformed page payloads without advancing state", async () => {
  const state = {
    items: [{ id: "a", occurred_at_ms: 10 }], nextPage: 2,
    total: 100, exhausted: false, inFlight: false
  };
  const malformedPayloads = [
    null,
    { items: {}, page: { page: 2, page_size: 25, total: 100 } },
    { items: [], page: null },
    { items: [], page: { page: "2", page_size: 25, total: 100 } },
    { items: [], page: { page: 2, page_size: 0, total: 100 } },
    { items: [], page: { page: 2, page_size: 25, total: -1 } }
  ];

  for (const payload of malformedPayloads) {
    await assert.rejects(
      controller.loadNextFeed(async () => payload, state),
      (error) => {
        assert.deepEqual(error.state, state);
        return true;
      }
    );
  }
});

test("loadNextFeed rejects a mismatched response page without exhausting or advancing", async () => {
  const state = {
    items: [{ id: "a", occurred_at_ms: 10 }], nextPage: 2,
    total: 100, exhausted: false, inFlight: false
  };
  await assert.rejects(
    controller.loadNextFeed(async () => ({
      items: [], page: { page: 3, page_size: 25, total: 100 }
    }), state),
    (error) => {
      assert.deepEqual(error.state, state);
      assert.equal(error.state.nextPage, 2);
      assert.equal(error.state.exhausted, false);
      return true;
    }
  );
});

test("loadNextFeed skips fetch and transition for in-flight or exhausted state", async () => {
  let calls = 0;
  const fetchPage = async () => { calls += 1; };
  const transition = () => { calls += 1; };
  const base = { items: [], nextPage: 4, total: 75, exhausted: false, inFlight: false };

  const inFlight = await controller.loadNextFeed(fetchPage, { ...base, inFlight: true }, transition);
  const exhausted = await controller.loadNextFeed(fetchPage, { ...base, exhausted: true }, transition);

  assert.equal(calls, 0);
  assert.deepEqual(inFlight, { ...base, inFlight: true });
  assert.deepEqual(exhausted, { ...base, exhausted: true });
});

test("normalizeBridgePreferences accepts strict safe values and otherwise uses defaults", () => {
  assert.deepEqual(controller.normalizeBridgePreferences({ ok: true, delta_mode: "range", chart_limit: 100 }), {
    deltaMode: "range", chartLimit: 100
  });
  for (const invalid of [
    null,
    { ok: false, delta_mode: "range", chart_limit: 100 },
    { ok: true, delta_mode: "RANGE", chart_limit: 100 },
    { ok: true, delta_mode: "range", chart_limit: "100" },
    { ok: true, delta_mode: "range", chart_limit: 25 }
  ]) {
    assert.deepEqual(controller.normalizeBridgePreferences(invalid), {
      deltaMode: "session", chartLimit: 50
    });
  }
});

test("CommonJS controller export does not write the Node global", () => {
  const modulePath = require.resolve("../../src/sf6viewer/interfaces/web/dashboard-controller.js");
  delete require.cache[modulePath];
  delete globalThis.SF6ViewerController;

  const commonJsController = require(modulePath);

  assert.equal(globalThis.SF6ViewerController, undefined);
  assert.equal(commonJsController.normalizeTabHash("#manage"), "#manage");
  assert.equal(Object.isFrozen(commonJsController), true);
});

test("browser UMD branch publishes the frozen controller global", () => {
  const webRoot = path.resolve(__dirname, "../../src/sf6viewer/interfaces/web");
  const context = vm.createContext({ URLSearchParams });
  vm.runInContext(fs.readFileSync(path.join(webRoot, "viewer-metrics.js"), "utf8"), context);
  vm.runInContext(fs.readFileSync(path.join(webRoot, "dashboard-controller.js"), "utf8"), context);

  assert.equal(typeof context.SF6ViewerController.normalizeTabHash, "function");
  assert.equal(Object.isFrozen(context.SF6ViewerController), true);
});

test("applyViewerPreference renders a safe preference before persisting without fetching", async () => {
  const state = Object.freeze({
    regions: { obs: { value: { marker: "last-good" }, stale: false } },
    preferences: { deltaMode: "session", chartLimit: 50 }
  });
  const calls = [];

  const next = await controller.applyViewerPreference({
    state,
    deltaMode: "range",
    chartLimit: 100,
    persist: async (deltaMode, chartLimit) => {
      calls.push(["persist", deltaMode, chartLimit]);
      return { ok: true };
    },
    render: (rendered) => { calls.push(["render", rendered]); }
  });

  assert.deepEqual(next.preferences, { deltaMode: "range", chartLimit: 100 });
  assert.equal(next.regions, state.regions);
  assert.equal(calls[0][0], "render");
  assert.equal(calls[0][1], next);
  assert.deepEqual(calls[1], ["persist", "range", 100]);
});

test("applyViewerPreference renders synchronously even when deferred persistence rejects", async () => {
  let rejectPersistence;
  const persistence = new Promise((_, reject) => { rejectPersistence = reject; });
  const rendered = [];

  const operation = controller.applyViewerPreference({
    state: { preferences: { deltaMode: "session", chartLimit: 50 } },
    deltaMode: "range",
    chartLimit: 20,
    render: (state) => { rendered.push(state.preferences); },
    persist: () => persistence
  });

  assert.deepEqual(rendered, [{ deltaMode: "range", chartLimit: 20 }]);
  rejectPersistence(new Error("disk unavailable"));
  await assert.rejects(operation, /disk unavailable/);
  assert.deepEqual(rendered, [{ deltaMode: "range", chartLimit: 20 }]);
});

test("applyFirstFeedPage preserves expanded history during polling and clears it after reset", () => {
  const expanded = {
    feedBoundaryAtMs: 1_000,
    feed: {
      items: [{ id: "expanded", occurred_at_ms: 100 }],
      nextPage: 4,
      total: 75,
      exhausted: false,
      inFlight: false
    }
  };
  const pageOne = {
    items: Array.from({ length: 25 }, (_, index) => ({
      id: index === 0 ? "new" : `page-one-${index}`,
      occurred_at_ms: 200 - index
    })),
    page: { page: 1, page_size: 25, total: 76 }
  };

  const polled = controller.applyFirstFeedPage({
    state: expanded,
    response: pageOne,
    session: { started_at_ms: 1_000, boundary_kind: "APP_START" }
  });
  assert.equal(polled.feed.items[0].id, "new");
  assert.equal(polled.feed.items.some((item) => item.id === "expanded"), true);
  assert.equal(polled.feed.items.length, 26);
  assert.equal(polled.feed.nextPage, 4);
  assert.equal(polled.feed.exhausted, false);

  const reset = controller.applyFirstFeedPage({
    state: polled,
    response: { items: [], page: { page: 1, page_size: 25, total: 0 } },
    session: { started_at_ms: 2_000, boundary_kind: "MATCH_RESET" }
  });
  assert.deepEqual(reset.feed.items, []);
  assert.equal(reset.feed.nextPage, 2);
  assert.equal(reset.feed.total, 0);
  assert.equal(reset.feed.exhausted, true);
  assert.equal(reset.feedBoundaryAtMs, 2_000);
  assert.equal(reset.feedGeneration, 1);
});

test("systemRegionPresentation reports a localized retry state without cached data", () => {
  assert.deepEqual(controller.systemRegionPresentation({ stale: true, value: null }), {
    state: "error",
    message: "시스템 현황을 불러오지 못했습니다. 잠시 후 다시 시도합니다."
  });
});

test("feed generation discards poll and more completions that started before reset", async () => {
  let resolvePoll;
  let resolveMore;
  let state = {
    feedGeneration: 0,
    feedBoundaryAtMs: 1_000,
    feed: {
      items: [{ id: "old", occurred_at_ms: 100 }],
      nextPage: 2,
      total: 50,
      exhausted: false,
      inFlight: false
    }
  };
  const pollGeneration = controller.feedGeneration(state);
  const moreGeneration = controller.feedGeneration(state);
  const poll = new Promise((resolve) => { resolvePoll = resolve; }).then((response) => {
    state = controller.applyFirstFeedPage({
      state,
      response,
      generation: pollGeneration,
      session: { started_at_ms: 1_000, boundary_kind: "APP_START" }
    });
  });
  const more = controller.loadNextFeed(
    () => new Promise((resolve) => { resolveMore = resolve; }),
    state.feed
  ).then((feed) => {
    state = controller.commitFeedState({ state, generation: moreGeneration, feed });
  });

  await Promise.resolve();
  state = controller.invalidateFeedState(state);
  resolvePoll({
    items: [{ id: "poll-old", occurred_at_ms: 200 }],
    page: { page: 1, page_size: 25, total: 1 }
  });
  resolveMore({
    items: [{ id: "more-old", occurred_at_ms: 50 }],
    page: { page: 2, page_size: 25, total: 50 }
  });
  await Promise.all([poll, more]);

  assert.equal(state.feedGeneration, 1);
  assert.deepEqual(state.feed.items, []);
  assert.equal(state.feed.nextPage, 1);
});

test("preference writes serialize and a late startup restore cannot overwrite user revision", async () => {
  const pending = [];
  const calls = [];
  const writes = controller.createPreferenceWriteQueue((deltaMode, chartLimit) => {
    calls.push([deltaMode, chartLimit]);
    return new Promise((resolve) => { pending.push(resolve); });
  });
  const first = writes("range", 20);
  const second = writes("session", 100);
  await Promise.resolve();
  assert.deepEqual(calls, [["range", 20]]);
  pending[0]();
  await first;
  await Promise.resolve();
  assert.deepEqual(calls, [["range", 20], ["session", 100]]);
  pending[1]();
  await second;

  const guard = controller.createRevisionGuard();
  const restoreRevision = guard.capture();
  guard.advance();
  let rendered = false;
  const state = { preferences: { deltaMode: "range", chartLimit: 20 } };
  const restored = controller.applyRestoredPreference({
    state,
    preferences: { deltaMode: "session", chartLimit: 50 },
    revisionGuard: guard,
    revision: restoreRevision,
    render: () => { rendered = true; }
  });
  assert.equal(restored, state);
  assert.equal(rendered, false);
});

test("revision guard rejects an auto-status poll resolved after a toggle", async () => {
  const guard = controller.createRevisionGuard();
  const pollRevision = guard.capture();
  let resolvePoll;
  let presentation = { live: false, text: "RECORDING OFF" };
  const poll = new Promise((resolve) => { resolvePoll = resolve; }).then((status) => {
    if (guard.isCurrent(pollRevision)) {
      presentation = controller.liveRecordingPresentation(status);
    }
  });

  guard.advance();
  presentation = controller.liveRecordingPresentation({
    ok: true, enabled: true, interval_seconds: 30,
    last_attempt_at_ms: Date.now() - 1_000,
    last_success_at_ms: Date.now(), last_error_code: ""
  });
  resolvePoll({ ok: true, enabled: false, interval_seconds: 30 });
  await poll;
  assert.deepEqual(presentation, { live: true, text: "LIVE RECORDING" });
});

test("timed regions settle independently and single-flight native requests are reused", async () => {
  const scheduled = [];
  let aborted = false;
  let nativeCalls = 0;
  let resolveNative;
  const nativePending = new Promise((resolve) => { resolveNative = resolve; });
  const singleFlight = controller.createSingleFlight(() => {
    nativeCalls += 1;
    return nativePending;
  });
  assert.equal(singleFlight(), singleFlight());
  assert.equal(nativeCalls, 1);

  const timed = controller.withTimeout(
    () => singleFlight(),
    {
      timeoutMs: 8_000,
      schedule: (callback) => { scheduled.push(callback); return scheduled.length; },
      cancel: () => {},
      createAbortController: () => ({ signal: {}, abort: () => { aborted = true; } })
    }
  );
  const refreshed = controller.refreshRegions({
    auto: timed,
    system: Promise.resolve({ status: "ok" })
  }, { regions: { auto: { value: { enabled: false }, stale: false } } });
  scheduled[0]();
  const state = await refreshed;
  assert.equal(aborted, true);
  assert.deepEqual(state.regions.auto, { value: { enabled: false }, stale: true });
  assert.deepEqual(state.regions.system, { value: { status: "ok" }, stale: false });
  assert.equal(singleFlight(), nativePending);
  assert.equal(nativeCalls, 1);
  resolveNative({ ok: true });
});

test("reset invalidation rejects old region completions and failed refresh keeps sensitive caches empty", async () => {
  let resolveOldObs;
  let resolveOldSystem;
  let state = {
    feedGeneration: 0,
    feed: {
      items: [{ id: "old-match", occurred_at_ms: 10 }], nextPage: 2,
      total: 1, exhausted: true, inFlight: false
    },
    regions: {
      obs: { value: { statistics: { total: { wins: 99, losses: 1 } } }, stale: false },
      feed: { value: { items: [{ id: "old-match" }] }, stale: false },
      manageMatches: { value: { items: [{ id: "old-match" }] }, stale: false },
      system: { value: { match_count: 100 }, stale: false }
    }
  };
  const oldGeneration = controller.feedGeneration(state);
  const oldRefresh = controller.refreshRegions({
    obs: new Promise((resolve) => { resolveOldObs = resolve; }),
    system: new Promise((resolve) => { resolveOldSystem = resolve; })
  }, state);

  state = controller.invalidateResetSensitiveState(state);
  resolveOldObs({ statistics: { total: { wins: 100, losses: 1 } } });
  resolveOldSystem({ match_count: 101 });
  const oldResult = await oldRefresh;
  state = controller.commitRefreshedRegions({
    state, refreshed: oldResult, generation: oldGeneration
  });
  assert.deepEqual(state.feed.items, []);
  assert.deepEqual(state.regions.obs, { value: null, stale: true });
  assert.deepEqual(state.regions.system, { value: null, stale: true });
  assert.deepEqual(state.regions.manageMatches, { value: { items: [] }, stale: true });

  const currentGeneration = controller.feedGeneration(state);
  const failed = await controller.refreshRegions({
    obs: Promise.reject(new Error("post-reset obs failed")),
    system: Promise.reject(new Error("post-reset system failed"))
  }, state);
  state = controller.commitRefreshedRegions({
    state, refreshed: failed, generation: currentGeneration
  });
  assert.deepEqual(state.feed.items, []);
  assert.deepEqual(state.regions.obs, { value: null, stale: true });
  assert.deepEqual(state.regions.system, { value: null, stale: true });
});

test("applyObsOptions renders the exact fixed loopback URL without persistence", () => {
  let renderedUrl = null;

  const result = controller.applyObsOptions({
    deltaMode: "range",
    chartLimit: 20,
    renderUrl: (url) => { renderedUrl = url; }
  });

  assert.deepEqual(result, {
    deltaMode: "range",
    chartLimit: 20,
    url: "http://127.0.0.1:8000/ui/obs.html?delta=range&limit=20"
  });
  assert.equal(renderedUrl, result.url);
});

test("liveRecordingPresentation fails closed for absent or unsafe bridge status", () => {
  assert.deepEqual(controller.liveRecordingPresentation(null), {
    live: false,
    text: "자동 수집 상태 확인 불가"
  });
  assert.deepEqual(controller.liveRecordingPresentation({ ok: true, enabled: "yes" }), {
    live: false,
    text: "자동 수집 상태 확인 불가"
  });
  assert.deepEqual(controller.liveRecordingPresentation({
    ok: true, enabled: true, interval_seconds: 30
  }), { live: false, text: "자동 수집 상태 확인 불가" });
  assert.deepEqual(controller.liveRecordingPresentation({
    ok: true, enabled: false, interval_seconds: 30
  }), { live: false, text: "RECORDING OFF" });
});

const COLLECTION_NOW = 1_777_632_030_000;
const successfulCollection = (overrides = {}) => ({
  ok: true, enabled: true, interval_seconds: 30,
  last_attempt_at_ms: COLLECTION_NOW - 5_000,
  last_success_at_ms: COLLECTION_NOW - 1_000,
  last_error_code: "",
  ...overrides
});

test("recording waits for the first successful match collection", () => {
  const status = successfulCollection({ last_attempt_at_ms: 0, last_success_at_ms: 0 });
  assert.deepEqual(controller.liveRecordingPresentation(status, COLLECTION_NOW), {
    live: false, text: "첫 수집 대기 중"
  });
});

test("recording reports the latest failure and recovers after a successful collection", () => {
  const failed = successfulCollection({
    last_attempt_at_ms: COLLECTION_NOW,
    last_error_code: "UPSTREAM.UNAVAILABLE"
  });
  assert.deepEqual(controller.liveRecordingPresentation(failed, COLLECTION_NOW), {
    live: false, text: "수집 오류"
  });
  assert.deepEqual(controller.liveRecordingPresentation(successfulCollection(), COLLECTION_NOW), {
    live: true, text: "LIVE RECORDING"
  });
  assert.deepEqual(controller.liveRecordingPresentation({ ...failed, enabled: false }, COLLECTION_NOW), {
    live: false, text: "RECORDING OFF"
  });
});

test("recording stops claiming live when success is older than three polling intervals", () => {
  const status = successfulCollection({
    last_attempt_at_ms: COLLECTION_NOW - 91_000,
    last_success_at_ms: COLLECTION_NOW - 90_000
  });
  assert.equal(controller.liveRecordingPresentation(status, COLLECTION_NOW).live, true);
  assert.deepEqual(controller.liveRecordingPresentation(status, COLLECTION_NOW + 1), {
    live: false, text: "수집 지연"
  });
  assert.equal(controller.liveRecordingPresentation({ ...status, interval_seconds: 60 }, COLLECTION_NOW + 1).live, true);
  assert.equal(controller.liveRecordingPresentation(status, COLLECTION_NOW + 86_400_000).live, false);
});

test("recording fails closed for malformed activity and impossible future timestamps", () => {
  for (const overrides of [
    { last_success_at_ms: "1777632030000" },
    { last_success_at_ms: -1 },
    { last_success_at_ms: Number.NaN },
    { last_success_at_ms: COLLECTION_NOW + 6_000 },
    { last_attempt_at_ms: null },
    { last_attempt_at_ms: COLLECTION_NOW + 6_000 },
    { last_error_code: null },
    { last_error_code: "UPSTREAM.TIMEOUT" },
    { interval_seconds: Number.MAX_SAFE_INTEGER }
  ]) {
    assert.deepEqual(controller.liveRecordingPresentation(successfulCollection(overrides), COLLECTION_NOW), {
      live: false, text: "자동 수집 상태 확인 불가"
    });
  }
});
