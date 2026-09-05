"use strict";

const metrics = window.SF6ViewerMetrics;
const options = metrics.normalizeObsOptions(window.location.search);
const POLL_INTERVAL_MS = 12_000;
const REQUEST_TIMEOUT_MS = 8_000;
const CHART_LEFT = 4;
const CHART_RIGHT = 382;
const CHART_TOP = 12;
const CHART_BOTTOM = 148;
const EMPTY_DELTA_LABEL = "— MR";
const ZERO_DELTA_LABEL = "0 MR";
const DELTA_CONTEXTS = Object.freeze({
  APP_START: "APP START",
  MATCH_RESET: "SINCE RESET",
  20: "LAST 20",
  50: "LAST 50",
  100: "LAST 100",
  ONE_POINT: "1 POINT"
});
let refreshInFlight = false;

const byId = (id) => document.getElementById(id);
const finiteNumber = (value) => typeof value === "number" && Number.isFinite(value);

function winRate(wins, losses) {
  const decisiveMatches = wins + losses;
  return decisiveMatches > 0 ? (wins / decisiveMatches) * 100 : 0;
}

function updateCard(prefix, record) {
  if (!record || !Number.isInteger(record.wins) || !Number.isInteger(record.losses)) {
    byId(`${prefix}-win-rate`).textContent = "—";
    byId(`${prefix}-record`).textContent = "—";
    byId(`${prefix}-progress`).style.width = "0%";
    return;
  }
  const rate = winRate(record.wins, record.losses);
  byId(`${prefix}-win-rate`).textContent = `${rate.toFixed(1)}%`;
  byId(`${prefix}-record`).textContent = `${record.wins}W ${record.losses}L`;
  byId(`${prefix}-progress`).style.width = `${rate}%`;
}

function updateOpponentCard(prefix, fallbackTitle, record) {
  byId(`${prefix}-title`).textContent = record && typeof record.label === "string"
    ? `VS ${record.label}`
    : fallbackTitle;
  updateCard(prefix, record);
}

function resetMrChart() {
  byId("mr-line").setAttribute("points", "");
  byId("mr-area").setAttribute("d", "");
  for (const id of ["mr-max", "mr-mid", "mr-min"]) byId(id).textContent = "—";
}

function deltaClass(delta) {
  if (!finiteNumber(delta) || delta === 0) return "delta-neutral";
  return delta > 0 ? "delta-positive" : "delta-negative";
}

function formatDelta(delta) {
  if (!finiteNumber(delta)) return EMPTY_DELTA_LABEL;
  if (delta === 0) return ZERO_DELTA_LABEL;
  return metrics.deltaLabel(delta);
}

function updateMrDelta(payload) {
  let delta = null;
  let context = DELTA_CONTEXTS.APP_START;
  if (options.deltaMode === "range") {
    const range = metrics.rangeDelta(payload.mr_history, options.chartLimit);
    delta = range.delta;
    context = range.pointCount === 1
      ? DELTA_CONTEXTS.ONE_POINT
      : DELTA_CONTEXTS[options.chartLimit];
  } else if (payload.session) {
    delta = payload.session.delta;
    context = payload.session.boundary_kind === "MATCH_RESET"
      ? DELTA_CONTEXTS.MATCH_RESET
      : DELTA_CONTEXTS.APP_START;
  }

  const deltaElement = byId("obs-mr-delta");
  deltaElement.textContent = formatDelta(delta);
  deltaElement.classList.remove("delta-positive", "delta-negative", "delta-neutral");
  deltaElement.classList.add(deltaClass(delta));
  byId("obs-delta-context").textContent = context;
}

function updateMrChart(history) {
  const points = Array.isArray(history)
    ? history.filter((point) => point && finiteNumber(point.mr))
    : [];
  if (points.length === 0) {
    resetMrChart();
    return;
  }

  const values = points.map((point) => point.mr);
  let minimum = Math.min(...values);
  let maximum = Math.max(...values);
  if (minimum === maximum) {
    minimum = Math.max(0, minimum - 25);
    maximum += 25;
  }
  const range = maximum - minimum;
  const coordinates = values.map((value, index) => {
    const ratio = points.length === 1 ? 1 : index / (points.length - 1);
    const x = CHART_LEFT + ratio * (CHART_RIGHT - CHART_LEFT);
    const y = CHART_BOTTOM - ((value - minimum) / range) * (CHART_BOTTOM - CHART_TOP);
    return [x, y];
  });
  const line = coordinates.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
  const area = [
    `M ${coordinates[0][0].toFixed(2)} ${CHART_BOTTOM}`,
    ...coordinates.map(([x, y]) => `L ${x.toFixed(2)} ${y.toFixed(2)}`),
    `L ${coordinates[coordinates.length - 1][0].toFixed(2)} ${CHART_BOTTOM}`,
    "Z"
  ].join(" ");
  byId("mr-line").setAttribute("points", line);
  byId("mr-area").setAttribute("d", area);
  byId("mr-max").textContent = String(maximum);
  byId("mr-mid").textContent = String(Math.round((maximum + minimum) / 2));
  byId("mr-min").textContent = String(minimum);
}

async function refresh() {
  if (refreshInFlight) return;
  refreshInFlight = true;
  try {
    const payload = await window.SF6ViewerController.withTimeout(async ({ signal }) => {
      const response = await fetch("/api/v1/obs", {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
        signal
      });
      if (!response.ok) throw new Error(String(response.status));
      return response.json();
    }, { timeoutMs: REQUEST_TIMEOUT_MS });
    if (payload.status !== "ok" || payload.schema_version !== "2" || !payload.statistics) {
      throw new Error("invalid payload");
    }
    const statistics = payload.statistics;
    byId("recent-title").textContent = `RECENT ${statistics.recent_limit}`;
    updateCard("total", statistics.total);
    updateCard("recent", statistics.recent);
    updateOpponentCard("character", "VS CHAR", statistics.opponent_character);
    updateOpponentCard("player", "VS PLAYER", statistics.opponent_player);
    const selectedHistory = metrics.sliceMrHistory(payload.mr_history, options.chartLimit);
    updateMrDelta(payload);
    updateMrChart(selectedHistory);
    byId("overlay-status").textContent = "연결됨";
  } catch (_) {
    byId("overlay-status").textContent = "로컬 서비스 연결 재시도 중";
  } finally {
    refreshInFlight = false;
  }
}

void refresh();
window.setInterval(() => { void refresh(); }, POLL_INTERVAL_MS);
