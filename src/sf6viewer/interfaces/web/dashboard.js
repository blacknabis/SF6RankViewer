"use strict";

const POLL_INTERVAL_MS = 12_000;
let refreshInFlight = false;

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
  } catch (error) {
    setConnection("error", "로컬 서비스에 연결할 수 없음");
    setState("error", `데이터를 불러오지 못했습니다. ${error instanceof Error ? error.message : "잠시 후 다시 시도합니다."}`);
  } finally {
    refreshInFlight = false;
  }
}

void refresh();
window.setInterval(() => { void refresh(); }, POLL_INTERVAL_MS);
