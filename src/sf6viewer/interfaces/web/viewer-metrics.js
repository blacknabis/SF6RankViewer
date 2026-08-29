"use strict";

(function exposeViewerMetrics(root, factory) {
  const api = Object.freeze(factory());
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.SF6ViewerMetrics = api;
})(typeof globalThis === "object" ? globalThis : this, function createViewerMetrics() {
  const SUPPORTED_LIMITS = Object.freeze([20, 50, 100]);
  const DEFAULT_OPTIONS = Object.freeze({ deltaMode: "session", chartLimit: 50 });
  const OBS_BASE_URL = "http://127.0.0.1:8000/ui/obs.html";

  function finiteNumber(value) {
    return typeof value === "number" && Number.isFinite(value);
  }

  function normalizedLimit(value) {
    const numeric = typeof value === "string" && /^\d+$/.test(value)
      ? Number(value)
      : value;
    return SUPPORTED_LIMITS.includes(numeric) ? numeric : DEFAULT_OPTIONS.chartLimit;
  }

  function winRate(recordOrWins, possibleLosses) {
    const wins = typeof recordOrWins === "object" && recordOrWins !== null
      ? recordOrWins.wins
      : recordOrWins;
    const losses = typeof recordOrWins === "object" && recordOrWins !== null
      ? recordOrWins.losses
      : possibleLosses;
    if (!finiteNumber(wins) || !finiteNumber(losses) || wins < 0 || losses < 0) return 0;
    const decisive = wins + losses;
    return decisive > 0 ? Number(((wins / decisive) * 100).toFixed(10)) : 0;
  }

  function sliceMrHistory(history, limit) {
    const selectedLimit = normalizedLimit(limit);
    if (!Array.isArray(history)) return [];
    return history
      .filter((point) => point && finiteNumber(point.mr))
      .slice(-selectedLimit);
  }

  function deltaLabel(delta) {
    if (!finiteNumber(delta)) return "—";
    if (delta === 0) return "0 MR";
    return delta > 0 ? `▲ +${delta} MR` : `▼ ${delta} MR`;
  }

  function rangeDelta(history, limit) {
    const selectedLimit = normalizedLimit(limit);
    const points = sliceMrHistory(history, selectedLimit);
    const context = points.length === 1 ? "1 POINT" : `LAST ${selectedLimit}`;
    const delta = points.length === 0 ? null : points.length === 1
      ? 0
      : points[points.length - 1].mr - points[0].mr;
    return {
      delta,
      label: deltaLabel(delta),
      context,
      pointCount: points.length
    };
  }

  function relativeTimeKo(occurredAtMs, nowMs = Date.now()) {
    if (!finiteNumber(occurredAtMs) || !finiteNumber(nowMs)) return "—";
    const elapsed = Math.max(0, nowMs - occurredAtMs);
    if (elapsed < 60_000) return "방금 전";
    if (elapsed < 3_600_000) return `${Math.floor(elapsed / 60_000)}분 전`;
    if (elapsed < 86_400_000) return `${Math.floor(elapsed / 3_600_000)}시간 전`;
    if (elapsed < 2 * 86_400_000) return "어제";
    return `${Math.floor(elapsed / 86_400_000)}일 전`;
  }

  function matchupTier(recordOrWins, possibleLosses) {
    const rate = winRate(recordOrWins, possibleLosses);
    if (rate >= 55) return { key: "favored", label: "우세", rate };
    if (rate >= 45) return { key: "even", label: "호각", rate };
    return { key: "unfavored", label: "열세", rate };
  }

  function queryValues(input) {
    if (input && typeof input.get === "function") return input;
    if (typeof input === "string") {
      const query = input.includes("?") ? input.slice(input.indexOf("?") + 1) : input;
      return new URLSearchParams(query);
    }
    if (input && typeof input === "object") {
      return {
        get(name) {
          if (name === "delta") return input.delta ?? input.deltaMode ?? input.delta_mode;
          if (name === "limit") return input.limit ?? input.chartLimit ?? input.chart_limit;
          return undefined;
        }
      };
    }
    return new URLSearchParams();
  }

  function normalizeObsOptions(input) {
    const values = queryValues(input);
    const delta = values.get("delta");
    const rawLimit = values.get("limit");
    return {
      deltaMode: delta === "range" || delta === "session" ? delta : DEFAULT_OPTIONS.deltaMode,
      chartLimit: normalizedLimit(rawLimit)
    };
  }

  function buildObsUrl(options) {
    const normalized = normalizeObsOptions(options);
    return `${OBS_BASE_URL}?delta=${normalized.deltaMode}&limit=${normalized.chartLimit}`;
  }

  function mergeFeed(existing, incoming) {
    const records = new Map();
    let anonymousId = 0;
    for (const item of [...(Array.isArray(existing) ? existing : []), ...(Array.isArray(incoming) ? incoming : [])]) {
      if (!item || typeof item !== "object") continue;
      const key = typeof item.id === "string" && item.id ? `id:${item.id}` : `anonymous:${anonymousId++}`;
      records.set(key, { ...item });
    }
    return Array.from(records.values()).sort((left, right) => {
      const timeDifference = (finiteNumber(right.occurred_at_ms) ? right.occurred_at_ms : 0)
        - (finiteNumber(left.occurred_at_ms) ? left.occurred_at_ms : 0);
      if (timeDifference !== 0) return timeDifference;
      return String(right.id || "").localeCompare(String(left.id || ""));
    });
  }

  function isFeedExhausted({ uniqueCount, total, receivedCount, pageSize }) {
    const reachedTotal = Number.isInteger(total) && total >= 0
      && Number.isInteger(uniqueCount) && uniqueCount >= total;
    const shortPage = Number.isInteger(receivedCount) && Number.isInteger(pageSize)
      && pageSize > 0 && receivedCount < pageSize;
    return reachedTotal || shortPage;
  }

  return {
    DEFAULT_OPTIONS,
    SUPPORTED_LIMITS,
    buildObsUrl,
    deltaLabel,
    isFeedExhausted,
    matchupTier,
    mergeFeed,
    normalizeObsOptions,
    rangeDelta,
    relativeTimeKo,
    sliceMrHistory,
    winRate
  };
});
