"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const metrics = require("../../src/sf6viewer/interfaces/web/viewer-metrics.js");

test("winRate uses decisive wins and losses only", () => {
  assert.equal(metrics.winRate({ wins: 3, losses: 1, draws: 99 }), 75);
  assert.equal(metrics.winRate({ wins: 0, losses: 0 }), 0);
});

test("rangeDelta reports unavailable history with exact context", () => {
  assert.deepEqual(metrics.rangeDelta(null, 20), {
    delta: null,
    label: "—",
    context: "LAST 20",
    pointCount: 0
  });
});

test("rangeDelta treats one point as zero with insufficient-history context", () => {
  assert.deepEqual(metrics.rangeDelta([{ mr: 1500 }], 50), {
    delta: 0,
    label: "0 MR",
    context: "1 POINT",
    pointCount: 1
  });
});

test("rangeDelta reports a flat range as zero in the selected window", () => {
  assert.deepEqual(metrics.rangeDelta([{ mr: 1500 }, { mr: 1500 }], 100), {
    delta: 0,
    label: "0 MR",
    context: "LAST 100",
    pointCount: 2
  });
});

test("rangeDelta formats positive and negative movement with signed context", () => {
  assert.deepEqual(metrics.rangeDelta([{ mr: 1500 }, { mr: 1545 }], 20), {
    delta: 45,
    label: "▲ +45 MR",
    context: "LAST 20",
    pointCount: 2
  });
  assert.deepEqual(metrics.rangeDelta([{ mr: 1500 }, { mr: 1470 }], 50), {
    delta: -30,
    label: "▼ -30 MR",
    context: "LAST 50",
    pointCount: 2
  });
});

test("sliceMrHistory keeps the newest 20, 50, or 100 chronological MR points", () => {
  const history = Array.from({ length: 125 }, (_, index) => ({ match_id: String(index), mr: 1400 + index }));
  assert.equal(metrics.sliceMrHistory(history, 20)[0].match_id, "105");
  assert.equal(metrics.sliceMrHistory(history, 50)[0].match_id, "75");
  assert.equal(metrics.sliceMrHistory(history, 100)[0].match_id, "25");
  assert.deepEqual(metrics.sliceMrHistory([{ mr: null }, { mr: 1510 }], 20), [{ mr: 1510 }]);
});

test("relativeTimeKo formats now and elapsed minutes", () => {
  const now = Date.UTC(2026, 7, 29, 12, 0, 0);
  assert.equal(metrics.relativeTimeKo(now - 20_000, now), "방금 전");
  assert.equal(metrics.relativeTimeKo(now - 5 * 60_000, now), "5분 전");
  assert.equal(metrics.relativeTimeKo(now + 60_000, now), "방금 전");
});

test("relativeTimeKo formats hours, yesterday, and older days", () => {
  const now = Date.UTC(2026, 7, 29, 12, 0, 0);
  assert.equal(metrics.relativeTimeKo(now - 3 * 3_600_000, now), "3시간 전");
  assert.equal(metrics.relativeTimeKo(now - 25 * 3_600_000, now), "어제");
  assert.equal(metrics.relativeTimeKo(now - 3 * 86_400_000, now), "3일 전");
  assert.equal(metrics.relativeTimeKo(null, now), "—");
});

test("matchupTier applies the exact 45 and 55 percent boundaries", () => {
  assert.deepEqual(metrics.matchupTier(44, 56), { key: "unfavored", label: "열세", rate: 44 });
  assert.deepEqual(metrics.matchupTier(45, 55), { key: "even", label: "호각", rate: 45 });
  assert.deepEqual(metrics.matchupTier(55, 45), { key: "favored", label: "우세", rate: 55 });
});

test("normalizeObsOptions rejects unsupported query values with documented fallbacks", () => {
  assert.deepEqual(metrics.normalizeObsOptions("?delta=nope&limit=21"), {
    deltaMode: "session",
    chartLimit: 50
  });
  assert.deepEqual(metrics.normalizeObsOptions("?delta=range&limit=100"), {
    deltaMode: "range",
    chartLimit: 100
  });
});

test("buildObsUrl emits the exact fixed loopback URL", () => {
  assert.equal(
    metrics.buildObsUrl({ deltaMode: "session", chartLimit: 50 }),
    "http://127.0.0.1:8000/ui/obs.html?delta=session&limit=50"
  );
});

test("mergeFeed returns a new deduplicated newest-first array without mutating inputs", () => {
  const existing = [{ id: "a", occurred_at_ms: 10 }, { id: "b", occurred_at_ms: 20, result: "LOSE" }];
  const incoming = [{ id: "c", occurred_at_ms: 30 }, { id: "b", occurred_at_ms: 20, result: "WIN" }];
  const existingSnapshot = JSON.stringify(existing);
  const incomingSnapshot = JSON.stringify(incoming);
  const merged = metrics.mergeFeed(existing, incoming);

  assert.deepEqual(merged.map((item) => item.id), ["c", "b", "a"]);
  assert.equal(merged[1].result, "WIN");
  assert.notEqual(merged, existing);
  assert.equal(JSON.stringify(existing), existingSnapshot);
  assert.equal(JSON.stringify(incoming), incomingSnapshot);
});

test("isFeedExhausted accepts total, empty-page, or short-page exhaustion signals", () => {
  assert.equal(metrics.isFeedExhausted({ uniqueCount: 50, total: 50, receivedCount: 25, pageSize: 25 }), true);
  assert.equal(metrics.isFeedExhausted({ uniqueCount: 25, total: 100, receivedCount: 0, pageSize: 25 }), true);
  assert.equal(metrics.isFeedExhausted({ uniqueCount: 30, total: 100, receivedCount: 5, pageSize: 25 }), true);
  assert.equal(metrics.isFeedExhausted({ uniqueCount: 25, total: 100, receivedCount: 25, pageSize: 25 }), false);
});

test("OBS options are normalized independently from viewer preferences", () => {
  const viewerPreferences = Object.freeze({ deltaMode: "range", chartLimit: 100 });
  const obsOptions = metrics.normalizeObsOptions("");

  assert.deepEqual(obsOptions, { deltaMode: "session", chartLimit: 50 });
  assert.deepEqual(viewerPreferences, { deltaMode: "range", chartLimit: 100 });
  assert.equal(metrics.buildObsUrl(obsOptions), "http://127.0.0.1:8000/ui/obs.html?delta=session&limit=50");
});
