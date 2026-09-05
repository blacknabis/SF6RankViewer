"use strict";

(function exposeDashboardController(root, factory) {
  const commonJs = typeof module === "object" && module.exports;
  const metrics = commonJs
    ? require("./viewer-metrics.js")
    : root && root.SF6ViewerMetrics;
  const api = Object.freeze(factory(metrics));
  if (commonJs) {
    module.exports = api;
  } else if (root) {
    root.SF6ViewerController = api;
  }
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

  async function applyViewerPreference({
    state,
    deltaMode,
    chartLimit,
    persist,
    render
  } = {}) {
    const preferences = metrics.normalizeObsOptions({ deltaMode, chartLimit });
    const source = state && typeof state === "object" ? state : {};
    const next = { ...source, preferences };
    if (typeof render === "function") render(next);
    if (typeof persist === "function") {
      await persist(preferences.deltaMode, preferences.chartLimit);
    }
    return next;
  }

  function applyObsOptions({ deltaMode, chartLimit, renderUrl } = {}) {
    const options = metrics.normalizeObsOptions({ deltaMode, chartLimit });
    const result = { ...options, url: metrics.buildObsUrl(options) };
    if (typeof renderUrl === "function") renderUrl(result.url);
    return result;
  }

  function autoCollectionState(autoStatus, nowMs = Date.now()) {
    const safe = autoStatus && autoStatus.ok === true
      && typeof autoStatus.enabled === "boolean"
      && Number.isInteger(autoStatus.interval_seconds)
      && autoStatus.interval_seconds >= 30
      && Number.isSafeInteger(autoStatus.interval_seconds * 3_000);
    if (!safe) return "unknown";
    if (!autoStatus.enabled) return "off";
    const validTime = (value) => Number.isSafeInteger(value)
      && value >= 0 && value <= nowMs + 5_000;
    if (!Number.isSafeInteger(nowMs) || nowMs <= 0
        || !validTime(autoStatus.last_attempt_at_ms)
        || !validTime(autoStatus.last_success_at_ms)
        || typeof autoStatus.last_error_code !== "string") return "unknown";
    if (autoStatus.last_error_code) {
      if (autoStatus.last_attempt_at_ms === 0
          || autoStatus.last_attempt_at_ms < autoStatus.last_success_at_ms) return "unknown";
      return "error";
    }
    if (autoStatus.last_success_at_ms === 0) return "pending";
    // Allow two missed checks before showing a delay; persisted success from
    // an earlier session must not keep the recording indicator live forever.
    return nowMs - autoStatus.last_success_at_ms > autoStatus.interval_seconds * 3_000
      ? "stale" : "live";
  }

  function liveRecordingPresentation(autoStatus, nowMs = Date.now()) {
    const state = autoCollectionState(autoStatus, nowMs);
    const labels = {
      unknown: "자동 수집 상태 확인 불가",
      off: "RECORDING OFF",
      pending: "첫 수집 대기 중",
      error: "수집 오류",
      stale: "수집 지연",
      live: "LIVE RECORDING"
    };
    return { live: state === "live", text: labels[state] };
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

  function applyFirstFeedPage({ state, response, session, generation } = {}) {
    const source = state && typeof state === "object" ? state : {};
    if (Number.isInteger(generation) && !isFeedGenerationCurrent(source, generation)) {
      return source;
    }
    const current = cloneFeedState(source.feed);
    const payload = pagePayload(response, 1);
    if (payload.pageSize !== 25) throw new TypeError("invalid first feed page size");

    const boundaryAtMs = session && Number.isInteger(session.started_at_ms)
      ? session.started_at_ms
      : null;
    const previousBoundaryAtMs = Number.isInteger(source.feedBoundaryAtMs)
      ? source.feedBoundaryAtMs
      : null;
    const resetBoundaryAdvanced = hasAdvancedResetBoundary(source, session);
    const existing = resetBoundaryAdvanced ? [] : current.items;
    const items = metrics.mergeFeed(existing, payload.items);
    const feed = {
      items,
      nextPage: resetBoundaryAdvanced ? 2 : Math.max(2, current.nextPage),
      total: payload.total,
      exhausted: metrics.isFeedExhausted({
        uniqueCount: items.length,
        total: payload.total,
        receivedCount: payload.items.length,
        pageSize: payload.pageSize
      }),
      inFlight: current.inFlight
    };
    return {
      ...source,
      feed,
      feedGeneration: resetBoundaryAdvanced ? feedGeneration(source) + 1 : feedGeneration(source),
      feedBoundaryAtMs: boundaryAtMs === null ? previousBoundaryAtMs : boundaryAtMs
    };
  }

  function hasAdvancedResetBoundary(state, session) {
    const boundaryAtMs = session && Number.isInteger(session.started_at_ms)
      ? session.started_at_ms
      : null;
    const previousBoundaryAtMs = state && Number.isInteger(state.feedBoundaryAtMs)
      ? state.feedBoundaryAtMs
      : null;
    return boundaryAtMs !== null && session.boundary_kind === "MATCH_RESET"
      && (previousBoundaryAtMs === null || boundaryAtMs > previousBoundaryAtMs);
  }

  function feedGeneration(state) {
    return state && Number.isInteger(state.feedGeneration) && state.feedGeneration >= 0
      ? state.feedGeneration
      : 0;
  }

  function isFeedGenerationCurrent(state, generation) {
    return Number.isInteger(generation) && feedGeneration(state) === generation;
  }

  function invalidateFeedState(state) {
    const source = state && typeof state === "object" ? state : {};
    return {
      ...source,
      feedGeneration: feedGeneration(source) + 1,
      feed: { items: [], nextPage: 1, total: 0, exhausted: false, inFlight: false }
    };
  }

  function invalidateResetSensitiveState(state) {
    const invalidated = invalidateFeedState(state);
    return {
      ...invalidated,
      regions: {
        ...(invalidated.regions || {}),
        obs: { value: null, stale: true },
        feed: { value: null, stale: true },
        manageMatches: { value: { items: [] }, stale: true },
        system: { value: null, stale: true }
      }
    };
  }

  function commitRefreshedRegions({ state, refreshed, generation } = {}) {
    const source = state && typeof state === "object" ? state : {};
    const incoming = refreshed && refreshed.regions && typeof refreshed.regions === "object"
      ? refreshed.regions
      : {};
    if (isFeedGenerationCurrent(source, generation)) {
      return { ...source, regions: incoming };
    }
    const current = source.regions && typeof source.regions === "object" ? source.regions : {};
    return {
      ...source,
      regions: {
        ...incoming,
        obs: current.obs,
        feed: current.feed,
        manageMatches: current.manageMatches,
        system: current.system
      }
    };
  }

  function commitFeedState({ state, generation, feed } = {}) {
    const source = state && typeof state === "object" ? state : {};
    if (!isFeedGenerationCurrent(source, generation)) return source;
    return { ...source, feed: cloneFeedState(feed) };
  }

  function createPreferenceWriteQueue(persist) {
    if (typeof persist !== "function") throw new TypeError("persist must be a function");
    let tail = Promise.resolve();
    return (deltaMode, chartLimit) => {
      const operation = tail.then(() => persist(deltaMode, chartLimit));
      tail = operation.catch(() => {});
      return operation;
    };
  }

  function createRevisionGuard(initialRevision = 0) {
    let revision = Number.isInteger(initialRevision) && initialRevision >= 0 ? initialRevision : 0;
    return Object.freeze({
      capture: () => revision,
      advance: () => { revision += 1; return revision; },
      isCurrent: (candidate) => Number.isInteger(candidate) && candidate === revision
    });
  }

  function applyRestoredPreference({
    state,
    preferences,
    revisionGuard,
    revision,
    render
  } = {}) {
    const source = state && typeof state === "object" ? state : {};
    if (!revisionGuard || typeof revisionGuard.isCurrent !== "function"
        || !revisionGuard.isCurrent(revision)) return source;
    const next = { ...source, preferences: metrics.normalizeObsOptions(preferences) };
    if (typeof render === "function") render(next);
    return next;
  }

  function createSingleFlight(operation) {
    if (typeof operation !== "function") throw new TypeError("operation must be a function");
    let pending = null;
    return () => {
      if (pending) return pending;
      try {
        pending = Promise.resolve(operation());
      } catch (error) {
        pending = Promise.reject(error);
      }
      const current = pending;
      current.then(
        () => { if (pending === current) pending = null; },
        () => { if (pending === current) pending = null; }
      );
      return current;
    };
  }

  async function withTimeout(operation, {
    timeoutMs,
    schedule = setTimeout,
    cancel = clearTimeout,
    createAbortController
  } = {}) {
    if (typeof operation !== "function") throw new TypeError("operation must be a function");
    if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) throw new TypeError("timeoutMs must be positive");
    const makeController = typeof createAbortController === "function"
      ? createAbortController
      : () => typeof AbortController === "function"
        ? new AbortController()
        : { signal: undefined, abort() {} };
    const abortController = makeController();
    let timer;
    const timeout = new Promise((_, reject) => {
      timer = schedule(() => {
        abortController.abort();
        const error = new Error("request timed out");
        error.code = "REQUEST_TIMEOUT";
        reject(error);
      }, timeoutMs);
    });
    try {
      return await Promise.race([
        Promise.resolve().then(() => operation({ signal: abortController.signal })),
        timeout
      ]);
    } finally {
      cancel(timer);
    }
  }

  function systemRegionPresentation(region) {
    const safeRegion = region && typeof region === "object" ? region : {};
    if (safeRegion.stale === true) {
      return safeRegion.value
        ? { state: "error", message: "시스템 현황 갱신에 실패했습니다. 마지막 정상 데이터를 표시합니다." }
        : { state: "error", message: "시스템 현황을 불러오지 못했습니다. 잠시 후 다시 시도합니다." };
    }
    const system = safeRegion.value;
    return {
      state: "ok",
      message: system && system.match_count
        ? "최신 로컬 데이터를 표시합니다."
        : "아직 수집된 데이터가 없습니다. 로그인을 완료한 뒤 수집을 시작하세요."
    };
  }

  function pagePayload(response, requestedPage) {
    if (!response || typeof response !== "object" || !Array.isArray(response.items)) {
      throw new TypeError("invalid feed page payload");
    }
    const metadata = response.page;
    if (!metadata || typeof metadata !== "object"
        || !Number.isInteger(metadata.page) || metadata.page < 1
        || !Number.isInteger(metadata.page_size) || metadata.page_size < 1
        || !Number.isInteger(metadata.total) || metadata.total < 0
        || metadata.page !== requestedPage) {
      throw new TypeError("invalid feed page metadata");
    }
    return {
      items: response.items,
      page: metadata.page,
      pageSize: metadata.page_size,
      total: metadata.total
    };
  }

  async function runTransition(transition, state) {
    if (typeof transition === "function") await transition(state);
  }

  async function loadNextFeed(fetchPage, state, transition) {
    const current = cloneFeedState(state);
    if (current.inFlight || current.exhausted) return current;

    const pending = { ...current, items: current.items.slice(), inFlight: true };
    const requestedPage = pending.nextPage;
    try {
      await runTransition(transition, pending);
      if (typeof fetchPage !== "function") throw new TypeError("fetchPage must be a function");
      const response = await fetchPage(requestedPage);
      const payload = pagePayload(response, requestedPage);
      const received = payload.items;
      const items = metrics.mergeFeed(current.items, received);
      const next = {
        items,
        nextPage: payload.page + 1,
        total: payload.total,
        exhausted: metrics.isFeedExhausted({
          uniqueCount: items.length,
          total: payload.total,
          receivedCount: received.length,
          pageSize: payload.pageSize
        }),
        inFlight: false
      };
      await runTransition(transition, next);
      return next;
    } catch (error) {
      const recoveredState = {
        ...pending,
        items: pending.items.slice(),
        inFlight: false
      };
      try {
        await runTransition(transition, recoveredState);
      } catch (_) {
        // Preserve the original failure while guaranteeing recovered state for callers.
      }
      const recoveredError = new Error(errorMessage(error));
      recoveredError.state = recoveredState;
      throw recoveredError;
    }
  }

  return {
    DEFAULT_PREFERENCES,
    applyFirstFeedPage,
    applyObsOptions,
    applyRestoredPreference,
    applyViewerPreference,
    autoCollectionState,
    commitFeedState,
    commitRefreshedRegions,
    createPreferenceWriteQueue,
    createRevisionGuard,
    createSingleFlight,
    feedGeneration,
    hasAdvancedResetBoundary,
    invalidateFeedState,
    invalidateResetSensitiveState,
    isFeedGenerationCurrent,
    liveRecordingPresentation,
    loadNextFeed,
    normalizeBridgePreferences,
    normalizeTabHash,
    refreshRegions,
    systemRegionPresentation,
    withTimeout
  };
});
