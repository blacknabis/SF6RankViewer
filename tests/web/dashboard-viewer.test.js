"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const metrics = require("../../src/sf6viewer/interfaces/web/viewer-metrics.js");
const viewerBoundary = require("../../src/sf6viewer/interfaces/web/dashboard-viewer.js");

class FakeNode {
  constructor(tagName = "div") {
    this.tagName = tagName;
    this.children = [];
    this.parentNode = null;
    this.attributes = new Map();
    this.dataset = {};
    this.style = {};
    this.hidden = false;
    this.disabled = false;
    this.value = "";
    this.className = "";
    this.listeners = new Map();
    this._text = "";
    this.textWrites = 0;
    this.innerHtmlWrites = 0;
  }

  get firstChild() { return this.children[0] || null; }
  get lastElementChild() { return this.children[this.children.length - 1] || null; }
  get textContent() { return this._text + this.children.map((child) => child.textContent).join(""); }
  set textContent(value) {
    for (const child of this.children) child.parentNode = null;
    this.children = [];
    this._text = String(value);
    this.textWrites += 1;
  }
  set innerHTML(_) { this.innerHtmlWrites += 1; }

  get classList() {
    return {
      add: (...names) => {
        const values = new Set(this.className.split(/\s+/).filter(Boolean));
        names.forEach((name) => values.add(name));
        this.className = Array.from(values).join(" ");
      },
      remove: (...names) => {
        const removed = new Set(names);
        this.className = this.className.split(/\s+/).filter((name) => name && !removed.has(name)).join(" ");
      }
    };
  }

  append(...nodes) { nodes.forEach((node) => this.appendChild(node)); }
  appendChild(node) {
    if (node.parentNode) node.parentNode.removeChild(node);
    this.children.push(node);
    node.parentNode = this;
    return node;
  }
  removeChild(node) {
    const index = this.children.indexOf(node);
    if (index >= 0) this.children.splice(index, 1);
    node.parentNode = null;
    return node;
  }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  setAttribute(name, value) {
    this.attributes.set(name, String(value));
    if (name === "class") this.className = String(value);
  }
  getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; }
  removeAttribute(name) { this.attributes.delete(name); }
  addEventListener(type, callback) {
    const callbacks = this.listeners.get(type) || [];
    callbacks.push(callback);
    this.listeners.set(type, callbacks);
  }
  dispatch(type) {
    for (const callback of this.listeners.get(type) || []) callback({ type, target: this });
  }
}

class FakeDocument {
  constructor(ids) {
    this.nodes = new Map(ids.map((id) => [id, new FakeNode()]));
  }
  getElementById(id) { return this.nodes.get(id) || null; }
  createElement(tagName) { return new FakeNode(tagName); }
  createElementNS(_, tagName) { return new FakeNode(tagName); }
}

const AGGREGATE_IDS = [
  "viewer-profile-name", "viewer-profile-character", "viewer-profile-rank",
  "viewer-profile-rating", "viewer-profile-empty", "viewer-live-badge",
  "viewer-live-status", "kpi-total-rate", "kpi-total-record", "kpi-total-progress",
  "kpi-recent-rate", "kpi-recent-record", "kpi-recent-progress",
  "kpi-session-delta", "kpi-session-context", "kpi-streak-value",
  "kpi-streak-context", "viewer-delta-mode", "chart-limit-20", "chart-limit-50",
  "chart-limit-100", "mr-chart-area", "mr-chart-line", "mr-chart-points",
  "mr-chart-data", "mr-chart-tooltip", "mr-chart-tooltip-status", "chart-empty",
  "chart-state", "matchup-grid", "matchup-empty", "matchup-state", "viewer-state",
  "viewer-error", "match-feed-load-more"
];

function aggregateDocument() {
  const document = new FakeDocument(AGGREGATE_IDS);
  const badge = document.getElementById("viewer-live-badge");
  badge.appendChild(new FakeNode("span"));
  badge.appendChild(new FakeNode("span"));
  return document;
}

test("renderFeed reuses keyed cards, writes unsafe names as text, and removes reset rows", () => {
  const document = new FakeDocument([
    "match-feed-list", "match-feed-empty", "match-feed-load-more", "match-feed-state"
  ]);
  const viewer = viewerBoundary.create({ document, metrics });
  const unsafe = '<img src=x onerror="alert(1)">';
  viewer.renderFeed({
    items: [{
      id: "match-1", occurred_at_ms: Date.now(), result: "WIN", my_character: "Juri",
      opponent_character: "Ken", opponent_name: unsafe, opponent_mr: 1500, mr_delta: 12
    }],
    nextPage: 2, total: 2, exhausted: false, inFlight: false
  });
  const list = document.getElementById("match-feed-list");
  const firstCard = list.children[0];
  assert.equal(firstCard.textContent.includes(unsafe), true);
  assert.equal(firstCard.innerHtmlWrites, 0);

  viewer.renderFeed({
    items: [{
      id: "match-1", occurred_at_ms: Date.now(), result: "LOSE", my_character: "Juri",
      opponent_character: "Cammy", opponent_name: "updated", opponent_lp: 20000, mr_delta: -8
    }],
    nextPage: 2, total: 1, exhausted: true, inFlight: false
  });
  assert.equal(list.children[0], firstCard);
  assert.equal(firstCard.textContent.includes("updated"), true);

  viewer.renderFeed({ items: [], nextPage: 1, total: 0, exhausted: false, inFlight: false });
  assert.equal(list.children.length, 0);
  assert.equal(firstCard.parentNode, null);
  assert.equal(document.getElementById("match-feed-empty").hidden, false);
  assert.equal(document.getElementById("match-feed-state").textContent.includes("updated"), false);
});

test("feed distinguishes pending, estimated, and unavailable MR without retaining old deltas", () => {
  const document = new FakeDocument([
    "match-feed-list", "match-feed-empty", "match-feed-load-more", "match-feed-state"
  ]);
  const viewer = viewerBoundary.create({ document, metrics });
  const match = {
    id: "reported-win", occurred_at_ms: Date.now(), result: "WIN", my_character: "Kimberly",
    opponent_character: "Alex", opponent_name: "Rival", opponent_mr: 1630
  };
  const render = (mr_delta, mr_delta_status) => viewer.renderFeed({
    items: [{ ...match, mr_delta, mr_delta_status }], exhausted: true, total: 1
  });

  render(null, "pending");
  const card = document.getElementById("match-feed-list").children[0];
  const delta = card.children[0].children[1];
  assert.equal(delta.textContent, "MR 확인 중");
  assert.equal(delta.className, "match-delta-neutral");
  assert.match(delta.getAttribute("title"), /다음 경기/);

  render(8, "estimated");
  assert.equal(document.getElementById("match-feed-list").children[0], card);
  assert.equal(delta.textContent, "추정 ▲ +8 MR");
  assert.equal(delta.className, "match-delta-positive");
  assert.match(delta.getAttribute("aria-label"), /추정/);
  assert.match(delta.getAttribute("title"), /시작 MR/);

  render(null, "unavailable");
  assert.equal(delta.textContent, "MR 확인 불가");
  assert.equal(delta.className, "match-delta-neutral");
  assert.equal(delta.getAttribute("aria-label").includes("+8"), false);

  // An older server or an inconsistent payload must not revive the previous-match delta.
  for (const state of [undefined, "unknown", "pending", "unavailable"]) {
    render(-8, state);
    assert.equal(delta.textContent.includes("-8"), false);
    assert.equal(delta.className, "match-delta-neutral");
  }
  render(null, "estimated");
  assert.equal(delta.textContent, "MR 확인 불가");
});

test("chart points expose non-action focus tooltips and adjacent accessible data", () => {
  const document = aggregateDocument();
  const viewer = viewerBoundary.create({ document, metrics });
  viewer.renderAggregate({
    payload: {
      viewer_profile: null,
      statistics: { total: { wins: 1, losses: 0 }, recent: { wins: 1, losses: 0 } },
      session: { boundary_kind: "APP_START", delta: 12 },
      streak: { result: "WIN", count: 1 },
      matchups: [],
      mr_history: [{
        match_id: "m1", occurred_at_ms: Date.now(), mr: 1512,
        opponent_name: "Rival <script>", opponent_character: "Ken", result: "WIN"
      }]
    },
    preferences: { deltaMode: "session", chartLimit: 20 },
    live: { live: false, text: "RECORDING OFF" }
  });

  const point = document.getElementById("mr-chart-points").children[0];
  assert.equal(point.getAttribute("tabindex"), "0");
  assert.equal(point.getAttribute("role"), null);
  assert.equal(document.getElementById("mr-chart-data").children.length, 1);
  assert.equal(document.getElementById("mr-chart-data").textContent.includes("Rival <script>"), true);
  point.dispatch("focus");
  assert.equal(document.getElementById("mr-chart-tooltip").hidden, false);
  assert.equal(
    document.getElementById("mr-chart-tooltip").textContent.replace(/,/g, "").includes("1512 MR"),
    true
  );

  viewer.setRegionState("aggregate", { stale: true, message: "마지막 정상 데이터" });
  assert.equal(document.getElementById("viewer-error").hidden, false);
  viewer.renderAggregate({ payload: {}, preferences: {}, live: null });
  assert.equal(document.getElementById("chart-empty").hidden, false);
  assert.equal(document.getElementById("mr-chart-data").children.length, 0);
});

test("bindInteractions forwards delta, chart, and feed actions once", () => {
  const document = aggregateDocument();
  const viewer = viewerBoundary.create({ document, metrics });
  const calls = [];
  viewer.bindInteractions({
    onDeltaMode: (value) => { calls.push(["delta", value]); },
    onChartLimit: (value) => { calls.push(["limit", value]); },
    onLoadMore: () => { calls.push(["more"]); }
  });
  document.getElementById("viewer-delta-mode").value = "range";
  document.getElementById("viewer-delta-mode").dispatch("change");
  document.getElementById("chart-limit-100").dispatch("click");
  document.getElementById("match-feed-load-more").dispatch("click");
  assert.deepEqual(calls, [["delta", "range"], ["limit", 100], ["more"]]);
});

test("unchanged feed polling does not repeat the aria-live state announcement", () => {
  const document = new FakeDocument([
    "match-feed-list", "match-feed-empty", "match-feed-load-more", "match-feed-state"
  ]);
  const viewer = viewerBoundary.create({ document, metrics });
  const state = {
    items: [{
      id: "stable", occurred_at_ms: Date.now(), result: "WIN", my_character: "Juri",
      opponent_character: "Ken", opponent_name: "Rival", opponent_mr: 1500, mr_delta: 1
    }],
    nextPage: 2, total: 2, exhausted: false, inFlight: false
  };
  viewer.renderFeed(state);
  const liveState = document.getElementById("match-feed-state");
  const writes = liveState.textWrites;
  viewer.renderFeed(state);
  assert.equal(liveState.textWrites, writes);
  assert.equal(liveState.textContent, "1건 표시 중");
});
