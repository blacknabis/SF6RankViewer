"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const webRoot = path.join(__dirname, "../../src/sf6viewer/interfaces/web");
const flush = () => new Promise(setImmediate);

function overlayHarness() {
  const elements = new Map();
  const timers = new Map();
  const requests = [];
  let nextTimer = 0;
  let nextFetch;
  let poll;
  const node = (id) => {
    if (!elements.has(id)) elements.set(id, {
      textContent: "", style: {}, attributes: {},
      setAttribute(name, value) { this.attributes[name] = value; },
      classList: { add() {}, remove() {} }
    });
    return elements.get(id);
  };
  const payload = (wins = 3) => ({
    status: "ok", schema_version: "2",
    statistics: { recent_limit: 100, total: { wins, losses: 1 }, recent: { wins, losses: 1 } },
    session: { delta: 10 }, mr_history: [{ mr: 1500 }, { mr: 1510 }]
  });
  const good = (wins = 3) => ({ ok: true, json: async () => payload(wins) });
  nextFetch = async () => good();
  const context = vm.createContext({
    AbortController, URLSearchParams,
    document: { getElementById: node }, location: { search: "" },
    setTimeout(callback, ms) {
      const id = ++nextTimer;
      timers.set(id, { callback, ms });
      return id;
    },
    clearTimeout(id) { timers.delete(id); },
    setInterval(callback, ms) { poll = callback; assert.equal(ms, 12_000); },
    fetch(url, options) {
      assert.equal(url, "/api/v1/obs");
      requests.push(options);
      return nextFetch(options);
    }
  });
  context.window = context;
  for (const script of ["viewer-metrics.js", "dashboard-controller.js", "obs.js"]) {
    vm.runInContext(fs.readFileSync(path.join(webRoot, script), "utf8"), context);
  }
  return {
    node, timers, requests, good,
    setFetch: (fetcher) => { nextFetch = fetcher; },
    poll: () => poll(),
    expire() {
      assert.equal(timers.size, 1, "one request deadline must remain active through body reading");
      const { callback, ms } = timers.values().next().value;
      assert.equal(ms, 8_000);
      callback();
    }
  };
}

for (const phase of ["request", "body"]) {
  test(`OBS aborts a hanging ${phase}, keeps the last display, and polls successfully again`, async () => {
    const overlay = overlayHarness();
    await flush();
    assert.equal(overlay.node("total-record").textContent, "3W 1L");
    assert.equal(overlay.timers.size, 0);
    let aborts = 0;
    let resolvePending;
    overlay.setFetch(({ signal }) => {
      // Keep this promise pending even on abort to verify the deadline also
      // releases the polling lock when a transport fails to settle promptly.
      if (signal) signal.addEventListener("abort", () => { aborts += 1; });
      const pending = new Promise((resolve) => { resolvePending = resolve; });
      return phase === "request" ? pending : Promise.resolve({ ok: true, json: () => pending });
    });
    overlay.poll();
    await flush();
    overlay.poll();
    await flush();
    assert.equal(overlay.requests.length, 2, "polling must not overlap an active request");
    overlay.expire();
    await flush();
    assert.equal(aborts, 1);
    assert.equal(overlay.requests[1].signal.aborted, true);
    assert.equal(overlay.node("overlay-status").textContent, "로컬 서비스 연결 재시도 중");
    assert.equal(overlay.node("total-record").textContent, "3W 1L");
    assert.equal(overlay.timers.size, 0);

    overlay.setFetch(async () => overlay.good(4));
    overlay.poll();
    await flush();
    assert.equal(overlay.requests.length, 3);
    assert.equal(overlay.requests[2].signal.aborted, false);
    assert.equal(overlay.node("total-record").textContent, "4W 1L");
    assert.equal(overlay.node("overlay-status").textContent, "연결됨");
    assert.equal(overlay.timers.size, 0);

    resolvePending(phase === "request" ? overlay.good(99) : await overlay.good(99).json());
    await flush();
    assert.equal(overlay.node("total-record").textContent, "4W 1L", "expired responses cannot overwrite recovery");
    assert.equal(overlay.node("overlay-status").textContent, "연결됨");
  });
}
