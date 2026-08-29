"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

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

  assert.equal(pageSeen, 2);
  assert.equal(transitions[0].inFlight, true);
  resolvePage({
    items: [{ id: "b", occurred_at_ms: 20 }, { id: "a", occurred_at_ms: 10 }],
    page: { page: 2, page_size: 2, total: 3 }
  });
  const next = await operation;

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
