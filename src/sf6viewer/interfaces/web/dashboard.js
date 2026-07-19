"use strict";

const POLL_INTERVAL_MS = 12_000;
const USER_CODE_PATTERN = /^\d{10}$/;
const LOGIN_MESSAGES = Object.freeze({
  "VALIDATION.USER_CODE": "10자리 사용자 코드를 확인하세요.",
  "SESSION.ACCOUNT_MISMATCH": "입력한 사용자 코드와 로그인한 계정이 다릅니다.",
  "UPSTREAM.TIMEOUT": "로그인 확인 시간이 초과되었습니다. 다시 시도하세요.",
  "UPSTREAM.UNAVAILABLE": "로그인 서비스를 사용할 수 없습니다. 잠시 후 다시 시도하세요.",
  "INTERNAL.UNEXPECTED": "로그인을 완료할 수 없습니다. 잠시 후 다시 시도하세요."
});
let refreshInFlight = false;
let loginInFlight = false;

const byId = (id) => document.getElementById(id);
const text = (value, fallback = "—") => value === null || value === undefined || value === "" ? fallback : String(value);
const number = (value) => new Intl.NumberFormat("ko-KR").format(Number(value || 0));
const timestamp = (value) => {
  if (!Number.isFinite(value)) return "—";
  return new Intl.DateTimeFormat("ko-KR", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
};

async function getJson(path) {
  const response = await fetch(path, { credentials: "same-origin", headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`요청 실패 (${response.status})`);
  return response.json();
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
  if (loginInFlight) return;
  const submit = byId("login-submit");
  const wasDisabled = submit.disabled;
  const available = nativeLoginApi() !== null;
  submit.disabled = !available;
  if (!available) {
    setLoginStatus("데스크톱 로그인 연결을 준비 중입니다.");
  } else if (wasDisabled) {
    setLoginStatus("내 계정의 10자리 사용자 코드를 입력한 뒤 로그인하세요.");
  }
}

function safeLoginMessage(code) {
  return LOGIN_MESSAGES[code] || LOGIN_MESSAGES["INTERNAL.UNEXPECTED"];
}

function configureObsUrl() {
  const input = byId("obs-url");
  input.value = `${window.location.origin}/ui/obs.html`;
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

  const input = byId("expected-user-code");
  const expectedUserCode = input.value.trim();
  if (!USER_CODE_PATTERN.test(expectedUserCode)) {
    setLoginStatus(LOGIN_MESSAGES["VALIDATION.USER_CODE"]);
    input.focus();
    return;
  }

  const bridge = nativeLoginApi();
  if (!bridge) {
    updateLoginAvailability();
    return;
  }

  loginInFlight = true;
  const form = byId("login-form");
  const submit = byId("login-submit");
  input.disabled = true;
  submit.disabled = true;
  form.setAttribute("aria-busy", "true");
  setLoginStatus("브라우저에서 로그인을 완료하세요. 로그인 확인 중에는 이 화면을 유지합니다.");

  try {
    const result = await bridge.login(expectedUserCode);
    if (result && result.ok === true && result.user_code === expectedUserCode) {
      setLoginStatus("로그인이 완료되었습니다. 인증 정보는 이 Windows 사용자 계정에 안전하게 저장되었습니다.");
    } else {
      setLoginStatus(safeLoginMessage(result && typeof result.code === "string" ? result.code : "INTERNAL.UNEXPECTED"));
    }
  } catch (_) {
    setLoginStatus(LOGIN_MESSAGES["INTERNAL.UNEXPECTED"]);
  } finally {
    loginInFlight = false;
    input.disabled = false;
    form.removeAttribute("aria-busy");
    submit.disabled = nativeLoginApi() === null;
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

async function refresh() {
  if (refreshInFlight) return;
  refreshInFlight = true;
  try {
    const [health, system, profiles, matches, jobs, quarantines, ingestions] = await Promise.all([
      getJson("/api/v1/health"), getJson("/api/v1/system"), getJson("/api/v1/profile-snapshots?page_size=1"),
      getJson("/api/v1/matches/latest?page_size=1"), getJson("/api/v1/jobs?page_size=1"),
      getJson("/api/v1/quarantine?page_size=5"), getJson("/api/v1/ingestion-runs?page_size=5")
    ]);
    if (health.status !== "ok" || system.status !== "ok") throw new Error("로컬 서비스 상태를 확인할 수 없습니다.");
    byId("match-count").textContent = number(system.match_count);
    byId("profile-count").textContent = number(system.profile_snapshot_count);
    byId("running-job-count").textContent = number(system.running_job_count);
    byId("quarantine-count").textContent = number(system.open_quarantine_count);
    renderProfile(profiles.items[0] || null);
    renderMatch(matches.items[0] || null);
    renderJob(jobs.items[0] || null);
    renderQuarantine(quarantines.items);
    renderIngestions(ingestions.items);
    setConnection("ok", "로컬 서비스 연결됨");
    setState("ok", system.match_count ? "최신 로컬 데이터를 표시합니다." : "아직 수집된 데이터가 없습니다. 로그인을 완료한 뒤 수집을 시작하세요.");
    byId("last-refresh").textContent = `마지막 갱신: ${timestamp(Date.now())}`;
  } catch (_) {
    setConnection("error", "로컬 서비스에 연결할 수 없음");
    setState("error", "데이터를 불러오지 못했습니다. 잠시 후 다시 시도합니다.");
  } finally {
    refreshInFlight = false;
  }
}

byId("login-form").addEventListener("submit", (event) => { void beginLogin(event); });
byId("obs-copy").addEventListener("click", () => { void copyObsUrl(); });
configureObsUrl();
window.addEventListener("pywebviewready", updateLoginAvailability);
window.setTimeout(updateLoginAvailability, 0);
void refresh();
window.setInterval(() => { void refresh(); }, POLL_INTERVAL_MS);
