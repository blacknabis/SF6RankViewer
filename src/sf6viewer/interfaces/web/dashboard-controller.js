"use strict";

(function exposeDashboardController(root, factory) {
  const metrics = typeof module === "object" && module.exports
    ? require("./viewer-metrics.js")
    : root && root.SF6ViewerMetrics;
  const api = Object.freeze(factory(metrics));
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.SF6ViewerController = api;
})(typeof globalThis === "object" ? globalThis : this, function createDashboardController(metrics) {
  const DEFAULT_PREFERENCES = Object.freeze({ deltaMode: "session", chartLimit: 50 });

  function normalizeTabHash(hash) {
    const normalized = typeof hash === "string" && !hash.startsWith("#") ? `#${hash}` : hash;
    return normalized === "#manage" ? "#manage" : "#viewer";
  }

  function errorMessage(reason) {
    if (reason && typeof reason.message === "string" && reason.message) return reason.message;
    return typeof reason === "string" && reason ? reason : "데이터를 불러오지 못했습니다.";
  }

  async function refreshRegions(requests, previous = {}) {
    const entries = Object.entries(requests || {});
    const operations = entries.map(([, request]) => Promise.resolve().then(() => (
      typeof request === "function" ? request() : request
    )));
    const settled = await Promise.allSettled(operations);
    const previousRegions = previous && typeof previous.regions === "object"
      ? previous.regions
      : {};
    const regions = { ...previousRegions };
    entries.forEach(([name], index) => {
      const result = settled[index];
      if (result.status === "fulfilled") {
        regions[name] = { value: result.value, stale: false };
        return;
      }
      const prior = previousRegions[name];
      regions[name] = {
        value: prior && Object.prototype.hasOwnProperty.call(prior, "value") ? prior.value : null,
        stale: true
      };
    });
    return { ...previous, regions };
  }

  function normalizeBridgePreferences(result) {
    if (!result || result.ok !== true) return { ...DEFAULT_PREFERENCES };
    if (result.delta_mode !== "session" && result.delta_mode !== "range") {
      return { ...DEFAULT_PREFERENCES };
    }
    if (typeof result.chart_limit !== "number" || !metrics.SUPPORTED_LIMITS.includes(result.chart_limit)) {
      return { ...DEFAULT_PREFERENCES };
    }
    return { deltaMode: result.delta_mode, chartLimit: result.chart_limit };
  }

  function cloneFeedState(state) {
    const source = state && typeof state === "object" ? state : {};
    return {
      items: Array.isArray(source.items) ? source.items.map((item) => ({ ...item })) : [],
      nextPage: Number.isInteger(source.nextPage) && source.nextPage >= 1 ? source.nextPage : 1,
      total: Number.isInteger(source.total) && source.total >= 0 ? source.total : 0,
      exhausted: source.exhausted === true,
      inFlight: source.inFlight === true
    };
  }

  async function loadNextFeed(fetchPage, state, transition) {
    const current = cloneFeedState(state);
    if (current.inFlight || current.exhausted) return current;

    const pending = { ...current, items: current.items.slice(), inFlight: true };
    if (typeof transition === "function") transition(pending);
    const requestedPage = pending.nextPage;
    try {
      if (typeof fetchPage !== "function") throw new TypeError("fetchPage must be a function");
      const response = await fetchPage(requestedPage);
      const received = response && Array.isArray(response.items) ? response.items : [];
      const metadata = response && response.page && typeof response.page === "object" ? response.page : {};
      const items = metrics.mergeFeed(current.items, received);
      const pageSize = Number.isInteger(metadata.page_size) && metadata.page_size > 0
        ? metadata.page_size
        : 25;
      const total = Number.isInteger(metadata.total) && metadata.total >= 0
        ? metadata.total
        : current.total;
      const next = {
        items,
        nextPage: Number.isInteger(metadata.page) && metadata.page >= 1
          ? metadata.page + 1
          : requestedPage + 1,
        total,
        exhausted: metrics.isFeedExhausted({
          uniqueCount: items.length,
          total,
          receivedCount: received.length,
          pageSize
        }),
        inFlight: false
      };
      if (typeof transition === "function") transition(next);
      return next;
    } catch (error) {
      const recoveredState = {
        ...pending,
        items: pending.items.slice(),
        inFlight: false
      };
      if (typeof transition === "function") transition(recoveredState);
      const recoveredError = new Error(errorMessage(error));
      recoveredError.state = recoveredState;
      throw recoveredError;
    }
  }

  return {
    DEFAULT_PREFERENCES,
    loadNextFeed,
    normalizeBridgePreferences,
    normalizeTabHash,
    refreshRegions
  };
});
