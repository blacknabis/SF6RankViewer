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

test("applyViewerPreference persists and renders a safe preference without fetching", async () => {
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
  assert.deepEqual(calls[0], ["persist", "range", 100]);
  assert.equal(calls[1][0], "render");
  assert.equal(calls[1][1], next);
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
  }), { live: true, text: "LIVE RECORDING" });
  assert.deepEqual(controller.liveRecordingPresentation({
    ok: true, enabled: false, interval_seconds: 30
  }), { live: false, text: "RECORDING OFF" });
});
