"use strict";

const POLL_INTERVAL_MS = 12_000;
const REGION_TIMEOUT_MS = 8_000;
const USER_CODE_PATTERN = /^\d{10}$/;
const LOGIN_MESSAGES = Object.freeze({
  "SESSION.ACCOUNT_MISMATCH": "기존 계정과 로그인한 계정이 다릅니다.",
  "SESSION.MISSING": "로그인 후 다시 시도하세요.",
  "SESSION.EXPIRED": "로그인 세션이 만료되었습니다. 다시 로그인하세요.",
  "UPSTREAM.TIMEOUT": "로그인 확인 시간이 초과되었습니다. 다시 시도하세요.",
  "UPSTREAM.UNAVAILABLE": "로그인 서비스를 사용할 수 없습니다. 잠시 후 다시 시도하세요.",
  "INTERNAL.UNEXPECTED": "로그인을 완료할 수 없습니다. 잠시 후 다시 시도하세요."
});
const COLLECTION_MESSAGES = Object.freeze({
  "SESSION.MISSING": "로그인 후 다시 시도하세요.",
  "SESSION.EXPIRED": "로그인 세션이 만료되었습니다. 다시 로그인하세요.",
  "SESSION.ACCOUNT_MISMATCH": "로그인 계정과 로컬 계정이 일치하지 않습니다.",
  "UPSTREAM.TIMEOUT": "Buckler 페이지 응답 시간이 초과되었습니다. 잠시 후 다시 시도하세요.",
  "UPSTREAM.UNAVAILABLE": "Buckler 프로필 페이지에 연결할 수 없습니다. 로그인 상태를 확인한 뒤 다시 시도하세요.",
  "UPSTREAM.RATE_LIMITED": "Buckler가 수집 요청을 일시적으로 차단했습니다. 잠시 후 다시 시도하세요.",
  "UPSTREAM.CONTRACT_CHANGED": "Buckler 페이지 형식이 달라 원문을 안전하게 처리할 수 없습니다.",
  "DATA.IDENTITY_GROUP_INCOMPLETE": "프로필 정보가 아직 없어 대전 기록을 정확하게 판별할 수 없습니다.",
  "INTERNAL.UNEXPECTED": "수집을 완료할 수 없습니다. 잠시 후 다시 시도하세요."
});
let refreshInFlight = false;
let refreshQueued = false;
let loginInFlight = false;
let resetInFlight = false;
let legacyCleanupInFlight = false;
let autoCollectionInFlight = false;
let autoCollectionStatusInFlight = false;
let autoCollectionEnabled = null;
let authProbeInFlight = false;
let authProbeStarted = false;
let savedSessionVerified = false;
let authStatusEpoch = 0;

const byId = (id) => document.getElementById(id);
const text = (value, fallback = "—") => value === null || value === undefined || value === "" ? fallback : String(value);
const number = (value) => new Intl.NumberFormat("ko-KR").format(Number(value || 0));
const timestamp = (value) => {
  if (!Number.isFinite(value)) return "—";
  return new Intl.DateTimeFormat("ko-KR", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
};
const metrics = window.SF6ViewerMetrics;
const controllerAdapter = window.SF6ViewerController;
const dashboardViewer = window.SF6DashboardViewer.create({ document, metrics });
const preferenceRevision = controllerAdapter.createRevisionGuard();
const autoStatusRevision = controllerAdapter.createRevisionGuard();
const preferenceWrites = controllerAdapter.createPreferenceWriteQueue(async (deltaMode, chartLimit) => {
  const bridge = nativeLoginApi();
  if (!bridge || typeof bridge.set_viewer_preferences !== "function") return { ok: true };
  const result = await bridge.set_viewer_preferences(deltaMode, chartLimit);
  if (!result || result.ok !== true) throw new Error("viewer preference rejected");
  return result;
});
const autoStatusRequest = controllerAdapter.createSingleFlight(() => {
  const bridge = nativeLoginApi();
  const revision = autoStatusRevision.capture();
  if (!bridge || typeof bridge.auto_collection_status !== "function") {
    return Promise.resolve({ status: null, revision });
  }
  return Promise.resolve(bridge.auto_collection_status()).then((status) => ({ status, revision }));
});
let dashboardState = {
  regions: {},
  preferences: { ...controllerAdapter.DEFAULT_PREFERENCES },
  feed: { items: [], nextPage: 1, total: 0, exhausted: false, inFlight: false },
  live: controllerAdapter.liveRecordingPresentation(null)
};

function normalizeDashboardTabHash(hash) {
  const controller = window.SF6ViewerController;
  if (controller && typeof controller.normalizeTabHash === "function") {
    return controller.normalizeTabHash(hash);
  }
  return hash === "#manage" ? "#manage" : "#viewer";
}

function applyDashboardTab(rawHash, { focus = false } = {}) {
  const hash = normalizeDashboardTabHash(rawHash);
  const viewerSelected = hash === "#viewer";
  const viewerTab = byId("tab-viewer");
  const manageTab = byId("tab-manage");
  const viewerPanel = byId("panel-viewer");
  const managePanel = byId("panel-manage");

  if (window.location.hash !== hash) window.history.replaceState(null, "", hash);
  viewerTab.setAttribute("aria-selected", String(viewerSelected));
  viewerTab.setAttribute("tabindex", viewerSelected ? "0" : "-1");
  manageTab.setAttribute("aria-selected", String(!viewerSelected));
  manageTab.setAttribute("tabindex", viewerSelected ? "-1" : "0");
  viewerPanel.hidden = !viewerSelected;
  managePanel.hidden = viewerSelected;
  if (focus) (viewerSelected ? viewerTab : manageTab).focus();
}

function configureDashboardTabs() {
  const tabs = [byId("tab-viewer"), byId("tab-manage")];
  const hashes = ["#viewer", "#manage"];

  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => {
      const hash = hashes[index];
      if (window.location.hash === hash) {
        applyDashboardTab(hash, { focus: true });
      } else {
        window.location.hash = hash;
      }
    });
    tab.addEventListener("keydown", (event) => {
      let nextIndex = null;
      if (event.key === "ArrowLeft" || event.key === "ArrowUp") nextIndex = (index + tabs.length - 1) % tabs.length;
      if (event.key === "ArrowRight" || event.key === "ArrowDown") nextIndex = (index + 1) % tabs.length;
      if (event.key === "Home") nextIndex = 0;
      if (event.key === "End") nextIndex = tabs.length - 1;
      if (nextIndex === null) return;
      event.preventDefault();
      tabs[nextIndex].focus();
    });
  });

  window.addEventListener("hashchange", () => { applyDashboardTab(window.location.hash); });
  applyDashboardTab(window.location.hash);
}

async function getJson(path, { signal } = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
    signal
  });
  if (!response.ok) throw new Error(`요청 실패 (${response.status})`);
  return response.json();
}

function withRegionTimeout(operation) {
  return controllerAdapter.withTimeout(operation, { timeoutMs: REGION_TIMEOUT_MS });
}

function timedJson(path) {
  return withRegionTimeout(({ signal }) => getJson(path, { signal }));
}

function setConnection(state, message) {
  byId("connection-dot").dataset.state = state;
  byId("connection-status").textContent = message;
}

function setState(state, message) {
  const element = byId("page-state");
  element.dataset.state = state;
  element.textContent = message;
}

function setLoginStatus(message) {
  byId("login-status").textContent = message;
}

function nativeLoginApi() {
  const bridge = window.pywebview && window.pywebview.api;
  return bridge && typeof bridge.login === "function" ? bridge : null;
}

function updateLoginAvailability() {
  const submit = byId("login-submit");
  const bridge = nativeLoginApi();
  const available = bridge !== null;
  const collectionAvailable = available && !loginInFlight && !authProbeInFlight && savedSessionVerified;
  submit.disabled = !available || loginInFlight;
  byId("matches-collect").disabled = !collectionAvailable || typeof bridge.collect_matches !== "function";
  byId("matches-reset").disabled = !available || resetInFlight || typeof bridge.clear_matches !== "function";
  byId("legacy-quarantine-clear").disabled = !available || legacyCleanupInFlight
    || typeof bridge.ignore_legacy_quarantines !== "function";
  updateAutoCollectionAvailability(bridge, collectionAvailable);
  if (!available) {
    setLoginStatus("데스크톱 로그인 연결을 준비 중입니다.");
  }
}

function applyAuthenticatedSession(userCode) {
  byId("login-account").textContent = `연결된 사용자 코드: ${userCode}`;
  savedSessionVerified = true;
  byId("login-submit").textContent = "다시 로그인";
}

function applyStoredUserCode(userCode) {
  byId("login-account").textContent = `저장된 사용자 코드: ${userCode}`;
  savedSessionVerified = false;
  byId("login-submit").textContent = "다시 로그인";
}

function applyManualLoginState() {
  byId("login-account").textContent = "로그인 후 Buckler 프로필에서 사용자 코드를 자동으로 확인합니다.";
  savedSessionVerified = false;
  byId("login-submit").textContent = "로그인 시작";
}

function isSafeAuthStatus(result) {
  return result && result.ok === true && typeof result.authenticated === "boolean";
}

async function restoreSavedSession() {
  if (authProbeStarted || authProbeInFlight) return;

  const bridge = nativeLoginApi();
  if (!bridge) {
    updateLoginAvailability();
    return;
  }
  if (typeof bridge.auth_status !== "function") {
    applyManualLoginState();
    setLoginStatus("저장된 로그인 상태를 확인할 수 없습니다. 로그인 시작을 선택하세요.");
    updateLoginAvailability();
    return;
  }

  authProbeStarted = true;
  authProbeInFlight = true;
  const probeEpoch = authStatusEpoch;
  updateLoginAvailability();
  try {
    const result = await bridge.auth_status();
    if (probeEpoch !== authStatusEpoch) return;

    const userCode = result && typeof result.user_code === "string" && USER_CODE_PATTERN.test(result.user_code)
      ? result.user_code
      : null;
    if (!isSafeAuthStatus(result)) {
      applyManualLoginState();
      setLoginStatus("저장된 로그인 상태를 확인할 수 없습니다. 로그인 시작을 선택하세요.");
    } else if (result.authenticated === true && userCode !== null) {
      applyAuthenticatedSession(userCode);
      setLoginStatus("저장된 로그인 세션을 사용 중입니다. 필요할 때만 다시 로그인하세요.");
    } else if (userCode !== null) {
      applyStoredUserCode(userCode);
      setLoginStatus("저장된 사용자 코드를 불러왔습니다. 다시 로그인하세요.");
    } else {
      applyManualLoginState();
      setLoginStatus("로그인하면 Buckler 프로필에서 사용자 코드를 자동으로 확인합니다.");
    }
  } catch (_) {
    if (probeEpoch === authStatusEpoch) {
      applyManualLoginState();
      setLoginStatus("저장된 로그인 상태를 확인할 수 없습니다. 로그인 시작을 선택하세요.");
    }
  } finally {
    if (probeEpoch === authStatusEpoch) authProbeInFlight = false;
    updateLoginAvailability();
  }
}

function safeLoginMessage(code) {
  return LOGIN_MESSAGES[code] || LOGIN_MESSAGES["INTERNAL.UNEXPECTED"];
}

function safeCollectionMessage(code) {
  return COLLECTION_MESSAGES[code] || COLLECTION_MESSAGES["INTERNAL.UNEXPECTED"];
}

function setAutoCollectionStatus(message) {
  byId("auto-collection-status").textContent = message;
}

function updateAutoCollectionAvailability(bridge, collectionAvailable) {
  const button = byId("auto-collection-toggle");
  const enabled = autoCollectionEnabled === true;
  const hasToggle = bridge !== null && typeof bridge.set_auto_collection_enabled === "function";
  button.textContent = enabled ? "전적 수집 중지" : "전적 수집 시작";
  button.dataset.state = enabled ? "running" : "stopped";
  // Stopping stays available even when the saved login session has expired.
  // Starting requires a verified session so it cannot open a browser to a
  // Buckler login page on a background timer.
  button.disabled = !hasToggle || autoCollectionInFlight || autoCollectionEnabled === null
    || (!enabled && !collectionAvailable);
}

function isSafeAutoCollectionStatus(result) {
  return result && result.ok === true && typeof result.enabled === "boolean"
    && Number.isInteger(result.interval_seconds) && result.interval_seconds >= 30;
}

function applyAutoCollectionStatus(result) {
  dashboardState = {
    ...dashboardState,
    live: controllerAdapter.liveRecordingPresentation(result)
  };
  if (!isSafeAutoCollectionStatus(result)) {
    autoCollectionEnabled = null;
    setAutoCollectionStatus("자동 수집 상태를 확인할 수 없습니다. 잠시 후 앱을 다시 시작하세요.");
  } else {
    autoCollectionEnabled = result.enabled;
    const interval = number(result.interval_seconds);
    setAutoCollectionStatus(result.enabled
      ? `자동 전적 수집이 실행 중입니다. 최근 대전을 ${interval}초마다 확인합니다.`
      : "자동 전적 수집이 중지되어 있습니다. 랭크 게임을 시작할 때 켜세요.");
  }
}

async function restoreAutoCollectionStatus() {
  if (autoCollectionStatusInFlight) return;
  const bridge = nativeLoginApi();
  if (!bridge || typeof bridge.auto_collection_status !== "function") {
    updateLoginAvailability();
    return;
  }

  autoCollectionStatusInFlight = true;
  const revision = autoStatusRevision.capture();
  updateLoginAvailability();
  try {
    const result = await withRegionTimeout(() => autoStatusRequest());
    if (autoStatusRevision.isCurrent(revision) && autoStatusRevision.isCurrent(result.revision)) {
      applyAutoCollectionStatus(result.status);
    }
  } catch (_) {
    if (autoStatusRevision.isCurrent(revision)) applyAutoCollectionStatus(null);
  } finally {
    autoCollectionStatusInFlight = false;
    updateLoginAvailability();
  }
}

async function toggleAutoCollection() {
  if (autoCollectionInFlight || typeof autoCollectionEnabled !== "boolean") return;
  const bridge = nativeLoginApi();
  if (!bridge || typeof bridge.set_auto_collection_enabled !== "function") {
    setAutoCollectionStatus("데스크톱 자동 수집 연결을 준비 중입니다.");
    return;
  }

  const enabled = !autoCollectionEnabled;
  if (enabled && !savedSessionVerified) {
    setAutoCollectionStatus("자동 수집을 시작하려면 로그인 상태를 확인한 뒤 다시 시도하세요.");
    return;
  }

  autoCollectionInFlight = true;
  autoStatusRevision.advance();
  const button = byId("auto-collection-toggle");
  button.setAttribute("aria-busy", "true");
  updateLoginAvailability();
  setAutoCollectionStatus(enabled
    ? "자동 전적 수집을 시작하고 있습니다. 첫 확인을 준비합니다."
    : "자동 전적 수집 중지를 요청했습니다. 진행 중인 요청은 안전하게 마무리합니다.");
  try {
    const result = await bridge.set_auto_collection_enabled(enabled);
    if (!isSafeAutoCollectionStatus(result)) {
      setAutoCollectionStatus(safeCollectionMessage(result && typeof result.code === "string" ? result.code : "INTERNAL.UNEXPECTED"));
      return;
    }
    applyAutoCollectionStatus(result);
    renderViewerAggregate();
    const interval = number(result.interval_seconds);
    setAutoCollectionStatus(result.enabled
      ? `자동 전적 수집을 시작했습니다. 최근 대전을 한 번 확인한 뒤 ${interval}초마다 갱신합니다.`
      : "자동 전적 수집을 멈췄습니다. OBS에는 마지막으로 수집한 전적이 계속 표시됩니다.");
    await refresh();
  } catch (_) {
    setAutoCollectionStatus(COLLECTION_MESSAGES["INTERNAL.UNEXPECTED"]);
  } finally {
    autoCollectionInFlight = false;
    button.removeAttribute("aria-busy");
    updateLoginAvailability();
  }
}

function setMatchCollectionStatus(message) {
  byId("matches-collect-status").textContent = message;
}

async function collectMatches() {
  if (loginInFlight) return;
  const bridge = nativeLoginApi();
  if (!bridge || typeof bridge.collect_matches !== "function") {
    setMatchCollectionStatus("데스크톱 수집 연결을 준비 중입니다.");
    return;
  }
  const button = byId("matches-collect");
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  setMatchCollectionStatus("최근 대전 원문을 수집하고 검증하고 있습니다.");
  try {
    const result = await bridge.collect_matches();
    if (result && result.ok === true) {
      if (result.status === "QUEUED") {
        setMatchCollectionStatus("현재 수집이 끝나면 최근 대전을 수집합니다.");
      } else if (result.status === "COALESCED") {
        setMatchCollectionStatus("동일한 대전 수집 요청이 이미 진행 중입니다.");
      } else {
        const summary = `정규화 ${number(result.normalized)}건 · 중복 ${number(result.duplicates)}건 · 격리 ${number(result.quarantined)}건`;
        setMatchCollectionStatus(summary);
        await refresh();
      }
    } else {
      setMatchCollectionStatus(safeCollectionMessage(result && typeof result.code === "string" ? result.code : "INTERNAL.UNEXPECTED"));
    }
  } catch (_) {
    setMatchCollectionStatus(COLLECTION_MESSAGES["INTERNAL.UNEXPECTED"]);
  } finally {
    button.removeAttribute("aria-busy");
    updateLoginAvailability();
  }
}

function setMatchResetStatus(message) {
  byId("matches-reset-status").textContent = message;
}

async function clearMatches() {
  if (resetInFlight) return;
  const bridge = nativeLoginApi();
  if (!bridge || typeof bridge.clear_matches !== "function") {
    setMatchResetStatus("데스크톱 초기화 연결을 준비 중입니다.");
    return;
  }
  if (!window.confirm("수집된 전적을 초기화할까요? 로그인 정보와 프로필은 유지됩니다.")) return;

  resetInFlight = true;
  updateLoginAvailability();
  const button = byId("matches-reset");
  button.setAttribute("aria-busy", "true");
  setMatchResetStatus("수집된 전적을 초기화하고 있습니다.");
  try {
    const result = await bridge.clear_matches();
    if (result && result.ok === true && Number.isInteger(result.cleared)) {
      const followUp = autoCollectionEnabled === true
        ? "자동 수집이 다음 주기에 최신 전적을 확인합니다."
        : "자동 수집이 중지되어 있습니다. 필요하면 전적 수집 시작 또는 최근 대전 수집을 선택하세요.";
      setMatchResetStatus(`전적 ${number(result.cleared)}건을 초기화했습니다. ${followUp}`);
      dashboardState = controllerAdapter.invalidateResetSensitiveState(dashboardState);
      dashboardViewer.renderFeed(dashboardState.feed);
      renderMatch(null);
      renderViewerAggregate();
      renderManagementRegions();
      await refresh();
    } else {
      setMatchResetStatus(safeCollectionMessage(result && typeof result.code === "string" ? result.code : "INTERNAL.UNEXPECTED"));
    }
  } catch (_) {
    setMatchResetStatus(COLLECTION_MESSAGES["INTERNAL.UNEXPECTED"]);
  } finally {
    resetInFlight = false;
    button.removeAttribute("aria-busy");
    updateLoginAvailability();
  }
}

function setLegacyQuarantineStatus(message) {
  byId("legacy-quarantine-status").textContent = message;
}

async function ignoreLegacyQuarantines() {
  if (legacyCleanupInFlight) return;
  const bridge = nativeLoginApi();
  if (!bridge || typeof bridge.ignore_legacy_quarantines !== "function") {
    setLegacyQuarantineStatus("데스크톱 정리 연결을 준비 중입니다.");
    return;
  }
  if (!window.confirm("이전 마이그레이션과 구형 파서의 검토 대기만 정리할까요? 원본 기록은 보존됩니다.")) return;

  legacyCleanupInFlight = true;
  updateLoginAvailability();
  const button = byId("legacy-quarantine-clear");
  button.setAttribute("aria-busy", "true");
  setLegacyQuarantineStatus("이전 마이그레이션과 구형 파서의 검토 대기를 정리하고 있습니다.");
  try {
    const result = await bridge.ignore_legacy_quarantines();
    if (result && result.ok === true && Number.isInteger(result.ignored)) {
      setLegacyQuarantineStatus(`검토 대기 ${number(result.ignored)}건을 정리했습니다. 원본 기록은 유지됩니다.`);
      await refresh();
    } else {
      setLegacyQuarantineStatus(safeCollectionMessage(result && typeof result.code === "string" ? result.code : "INTERNAL.UNEXPECTED"));
    }
  } catch (_) {
    setLegacyQuarantineStatus(COLLECTION_MESSAGES["INTERNAL.UNEXPECTED"]);
  } finally {
    legacyCleanupInFlight = false;
    button.removeAttribute("aria-busy");
    updateLoginAvailability();
  }
}

function configureObsUrl() {
  controllerAdapter.applyObsOptions({
    deltaMode: byId("obs-delta-mode").value,
    chartLimit: Number(byId("obs-chart-limit").value),
    renderUrl: (url) => { byId("obs-url").value = url; }
  });
}

async function copyObsUrl() {
  const input = byId("obs-url");
  const status = byId("obs-status");
  try {
    await navigator.clipboard.writeText(input.value);
    status.textContent = "OBS 주소를 복사했습니다.";
  } catch (_) {
    input.focus();
    input.select();
    status.textContent = "주소를 선택했습니다. Ctrl+C로 복사하세요.";
  }
}

async function beginLogin(event) {
  event.preventDefault();
  if (loginInFlight) return;

  const bridge = nativeLoginApi();
  if (!bridge) {
    updateLoginAvailability();
    return;
  }

  loginInFlight = true;
  authStatusEpoch += 1;
  authProbeInFlight = false;
  savedSessionVerified = false;
  updateLoginAvailability();
  const form = byId("login-form");
  const submit = byId("login-submit");
  submit.disabled = true;
  form.setAttribute("aria-busy", "true");
  setLoginStatus("브라우저에서 로그인을 완료하세요. 로그인 확인 중에는 이 화면을 유지합니다.");

  try {
    const result = await bridge.login();
    const userCode = result && typeof result.user_code === "string" && USER_CODE_PATTERN.test(result.user_code)
      ? result.user_code
      : null;
    if (result && result.ok === true && userCode !== null) {
      applyAuthenticatedSession(userCode);
      setLoginStatus("로그인이 완료되었습니다. 인증 정보는 이 Windows 사용자 계정에 안전하게 저장되었습니다.");
    } else {
      setLoginStatus(safeLoginMessage(result && typeof result.code === "string" ? result.code : "INTERNAL.UNEXPECTED"));
    }
  } catch (_) {
    setLoginStatus(LOGIN_MESSAGES["INTERNAL.UNEXPECTED"]);
  } finally {
    loginInFlight = false;
    form.removeAttribute("aria-busy");
    updateLoginAvailability();
  }
}

function clear(element) { while (element.firstChild) element.removeChild(element.firstChild); }
function addDetail(container, label, value) {
  const term = document.createElement("dt");
  term.textContent = label;
  const definition = document.createElement("dd");
  definition.textContent = text(value);
  container.append(term, definition);
}

function renderProfile(profile) {
  const details = byId("profile-detail"); clear(details);
  byId("profile-empty").hidden = Boolean(profile);
  if (!profile) return;
  addDetail(details, "표시 이름", profile.display_name);
  addDetail(details, "캐릭터", profile.character);
  addDetail(details, "등급", profile.rank_name);
  addDetail(details, "MR / LP", `${text(profile.mr)} / ${text(profile.lp)}`);
  addDetail(details, "관측 시각", timestamp(profile.observed_at_ms));
}

function renderMatch(match) {
  const details = byId("match-detail"); clear(details);
  byId("match-empty").hidden = Boolean(match);
  if (!match) return;
  addDetail(details, "결과", match.result);
  addDetail(details, "내 캐릭터", match.my_character);
  addDetail(details, "상대", `${text(match.opponent_name)} · ${text(match.opponent_character)}`);
  addDetail(details, "상대 MR / LP", `${text(match.opponent_mr)} / ${text(match.opponent_lp)}`);
  addDetail(details, "대전 시각", timestamp(match.occurred_at_ms));
}

function renderJob(job) {
  const details = byId("job-detail"); clear(details);
  byId("job-empty").hidden = Boolean(job);
  if (!job) return;
  addDetail(details, "유형", job.type);
  addDetail(details, "상태", job.state);
  addDetail(details, "단계", job.phase);
  addDetail(details, "진행", job.progress_total ? `${number(job.progress_current)} / ${number(job.progress_total)}` : "—");
  addDetail(details, "요청 시각", timestamp(job.requested_at_ms));
}

function renderQuarantine(items) {
  const list = byId("quarantine-list"); clear(list);
  byId("quarantine-empty").hidden = items.length > 0;
  for (const item of items) {
    const entry = document.createElement("li");
    entry.textContent = `${text(item.reason_code)} · ${text(item.status)} · ${timestamp(item.created_at_ms)}`;
    list.appendChild(entry);
  }
}

function renderIngestions(items) {
  const body = byId("ingestion-rows"); clear(body);
  byId("ingestion-empty").hidden = items.length > 0;
  for (const ingestion of items) {
    const row = document.createElement("tr");
    for (const value of [ingestion.state, ingestion.raw_count, ingestion.normalized_count, ingestion.duplicate_count, ingestion.quarantine_count]) {
      const cell = document.createElement("td");
      cell.textContent = typeof value === "number" ? number(value) : text(value);
      row.appendChild(cell);
    }
    body.appendChild(row);
  }
}

function renderViewerAggregate() {
  const aggregate = dashboardState.regions.obs;
  dashboardViewer.renderAggregate({
    payload: aggregate && aggregate.value,
    preferences: dashboardState.preferences,
    live: dashboardState.live
  });
  dashboardViewer.setRegionState("aggregate", aggregate && aggregate.stale
    ? { stale: true, message: "실시간 집계 갱신에 실패했습니다. 마지막 정상 데이터를 표시합니다." }
    : { stale: false, message: "실시간 집계가 최신 상태입니다." });
}

function renderManagementRegions() {
  const regions = dashboardState.regions;
  const system = regions.system && regions.system.value;
  const systemPresentation = controllerAdapter.systemRegionPresentation(regions.system);
  setState(systemPresentation.state, systemPresentation.message);
  if (system) {
    byId("app-version").textContent = typeof system.app_version === "string" ? `v${system.app_version}` : "버전 정보 없음";
    byId("match-count").textContent = number(system.match_count);
    byId("profile-count").textContent = number(system.profile_snapshot_count);
    byId("running-job-count").textContent = number(system.running_job_count);
    byId("quarantine-count").textContent = number(system.open_quarantine_count);
  } else {
    byId("app-version").textContent = "버전 정보 없음";
    byId("match-count").textContent = "—";
    byId("profile-count").textContent = "—";
    byId("running-job-count").textContent = "—";
    byId("quarantine-count").textContent = "—";
  }
  const profiles = regions.profiles && regions.profiles.value;
  const matches = regions.manageMatches && regions.manageMatches.value;
  const jobs = regions.jobs && regions.jobs.value;
  const quarantines = regions.quarantines && regions.quarantines.value;
  const ingestions = regions.ingestions && regions.ingestions.value;
  if (profiles && Array.isArray(profiles.items)) renderProfile(profiles.items[0] || null);
  if (matches && Array.isArray(matches.items)) renderMatch(matches.items[0] || null);
  if (jobs && Array.isArray(jobs.items)) renderJob(jobs.items[0] || null);
  if (quarantines && Array.isArray(quarantines.items)) renderQuarantine(quarantines.items);
  if (ingestions && Array.isArray(ingestions.items)) renderIngestions(ingestions.items);
  byId("last-refresh").textContent = `마지막 갱신: ${timestamp(Date.now())}`;
}

async function restoreViewerPreferences() {
  const bridge = nativeLoginApi();
  const revision = preferenceRevision.capture();
  let preferences = { ...controllerAdapter.DEFAULT_PREFERENCES };
  if (bridge && typeof bridge.viewer_preferences === "function") {
    try {
      preferences = controllerAdapter.normalizeBridgePreferences(await bridge.viewer_preferences());
    } catch (_) {
      preferences = { ...controllerAdapter.DEFAULT_PREFERENCES };
    }
  }
  dashboardState = controllerAdapter.applyRestoredPreference({
    state: dashboardState,
    preferences,
    revisionGuard: preferenceRevision,
    revision,
    render: (next) => {
      dashboardState = next;
      renderViewerAggregate();
    }
  });
}

async function changeViewerPreference(changes) {
  const requested = { ...dashboardState.preferences, ...changes };
  const revision = preferenceRevision.advance();
  try {
    const next = await controllerAdapter.applyViewerPreference({
      state: dashboardState,
      deltaMode: requested.deltaMode,
      chartLimit: requested.chartLimit,
      persist: preferenceWrites,
      render: (next) => {
        dashboardState = next;
        renderViewerAggregate();
      }
    });
    if (preferenceRevision.isCurrent(revision)) dashboardState = next;
  } catch (_) {
    if (preferenceRevision.isCurrent(revision)) {
      dashboardViewer.setRegionState("aggregate", {
        stale: true,
        message: "화면에는 적용했지만 뷰어 설정을 저장하지 못했습니다."
      });
    }
  }
}

async function loadMoreFeed() {
  const generation = controllerAdapter.feedGeneration(dashboardState);
  try {
    const feed = await controllerAdapter.loadNextFeed(
      (page) => timedJson(`/api/v1/matches/latest?page=${page}&page_size=25`),
      dashboardState.feed,
      (transition) => {
        const next = controllerAdapter.commitFeedState({ state: dashboardState, generation, feed: transition });
        if (next !== dashboardState) {
          dashboardState = next;
          dashboardViewer.renderFeed(dashboardState.feed);
        }
      }
    );
    dashboardState = controllerAdapter.commitFeedState({ state: dashboardState, generation, feed });
  } catch (error) {
    if (!controllerAdapter.isFeedGenerationCurrent(dashboardState, generation)) return;
    if (error && error.state) {
      dashboardState = controllerAdapter.commitFeedState({
        state: dashboardState, generation, feed: error.state
      });
    }
    dashboardViewer.renderFeed(dashboardState.feed);
    dashboardViewer.setRegionState("feed", {
      stale: true,
      message: "추가 대전 기록을 불러오지 못했습니다. 다시 시도할 수 있습니다."
    });
  }
}

async function refresh() {
  if (refreshInFlight) {
    refreshQueued = true;
    return;
  }
  refreshInFlight = true;
  const refreshFeedGeneration = controllerAdapter.feedGeneration(dashboardState);
  const refreshAutoRevision = autoStatusRevision.capture();
  const refreshDuringAutoMutation = autoCollectionInFlight;
  try {
    const bridge = nativeLoginApi();
    const refreshed = await controllerAdapter.refreshRegions({
      health: async () => {
        const value = await timedJson("/api/v1/health");
        if (value.status !== "ok") throw new Error("health unavailable");
        return value;
      },
      system: async () => {
        const value = await timedJson("/api/v1/system");
        if (value.status !== "ok") throw new Error("system unavailable");
        return value;
      },
      profiles: () => timedJson("/api/v1/profile-snapshots?page_size=1"),
      manageMatches: () => timedJson("/api/v1/matches/latest?page_size=1"),
      jobs: () => timedJson("/api/v1/jobs?page_size=1"),
      quarantines: () => timedJson("/api/v1/quarantine?page_size=5&status=OPEN"),
      ingestions: () => timedJson("/api/v1/ingestion-runs?page_size=5"),
      obs: () => timedJson("/api/v1/obs"),
      feed: () => timedJson("/api/v1/matches/latest?page=1&page_size=25"),
      auto: bridge && typeof bridge.auto_collection_status === "function"
        ? () => withRegionTimeout(() => autoStatusRequest())
        : Promise.resolve(null)
    }, dashboardState);
    // Preferences and feed paging can change while the settled refresh is in
    // progress. Only the independently refreshed regions are replaced here.
    dashboardState = controllerAdapter.commitRefreshedRegions({
      state: dashboardState,
      refreshed,
      generation: refreshFeedGeneration
    });

    const feedRegion = dashboardState.regions.feed;
    const aggregate = dashboardState.regions.obs;
    const aggregateSession = aggregate && aggregate.value && aggregate.value.session;
    const resetBoundaryAdvanced = controllerAdapter.hasAdvancedResetBoundary(
      dashboardState, aggregateSession
    );
    if (feedRegion && !feedRegion.stale
        && (!dashboardState.feed.inFlight || resetBoundaryAdvanced)) {
      dashboardState = controllerAdapter.applyFirstFeedPage({
        state: dashboardState,
        response: feedRegion.value,
        generation: refreshFeedGeneration,
        session: aggregateSession
      });
    }
    dashboardViewer.renderFeed(dashboardState.feed);
    if (feedRegion && feedRegion.stale) {
      dashboardViewer.setRegionState("feed", {
        stale: true,
        message: dashboardState.feed.items.length
          ? "대전 피드 갱신에 실패했습니다. 마지막 정상 데이터를 표시합니다."
          : "대전 피드를 불러오지 못했습니다. 잠시 후 다시 시도합니다."
      });
    }

    const autoRegion = dashboardState.regions.auto;
    const autoResult = autoRegion && !autoRegion.stale ? autoRegion.value : null;
    if (!refreshDuringAutoMutation && autoStatusRevision.isCurrent(refreshAutoRevision)
        && (!autoRegion || !autoRegion.stale)
        && (!autoResult || autoStatusRevision.isCurrent(autoResult.revision))) {
      applyAutoCollectionStatus(autoResult ? autoResult.status : null);
    }
    renderViewerAggregate();
    renderManagementRegions();

    const stale = Object.values(dashboardState.regions).some((region) => region && region.stale);
    setConnection(stale ? "error" : "ok", stale ? "일부 데이터를 다시 시도하는 중" : "로컬 서비스 연결됨");
  } catch (_) {
    setConnection("error", "로컬 서비스에 연결할 수 없음");
    setState("error", "데이터를 불러오지 못했습니다. 잠시 후 다시 시도합니다.");
  } finally {
    refreshInFlight = false;
    updateLoginAvailability();
    if (refreshQueued) {
      refreshQueued = false;
      void refresh();
    }
  }
}

configureDashboardTabs();
dashboardViewer.bindInteractions({
  onDeltaMode: (deltaMode) => changeViewerPreference({ deltaMode }),
  onChartLimit: (chartLimit) => changeViewerPreference({ chartLimit }),
  onLoadMore: () => loadMoreFeed()
});
byId("login-form").addEventListener("submit", (event) => { void beginLogin(event); });
byId("obs-copy").addEventListener("click", () => { void copyObsUrl(); });
byId("obs-delta-mode").addEventListener("change", configureObsUrl);
byId("obs-chart-limit").addEventListener("change", configureObsUrl);
byId("auto-collection-toggle").addEventListener("click", () => { void toggleAutoCollection(); });
byId("matches-collect").addEventListener("click", () => { void collectMatches(); });
byId("matches-reset").addEventListener("click", () => { void clearMatches(); });
byId("legacy-quarantine-clear").addEventListener("click", () => { void ignoreLegacyQuarantines(); });
configureObsUrl();
window.addEventListener("pywebviewready", () => {
  void restoreSavedSession();
  void restoreAutoCollectionStatus();
  void restoreViewerPreferences();
  void refresh();
});
window.setTimeout(() => {
  void restoreSavedSession();
  void restoreAutoCollectionStatus();
  void restoreViewerPreferences();
}, 0);
void refresh();
window.setInterval(() => { void refresh(); }, POLL_INTERVAL_MS);
