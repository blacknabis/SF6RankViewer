"use strict";

const POLL_INTERVAL_MS = 12_000;
let refreshInFlight = false;
const byId = (id) => document.getElementById(id);
const text = (value, fallback = "—") => value === null || value === undefined || value === "" ? fallback : String(value);
const score = (mr, lp) => `MR ${text(mr)} · LP ${text(lp)}`;

async function refresh() {
  if (refreshInFlight) return;
  refreshInFlight = true;
  try {
    const response = await fetch("/api/v1/obs", { credentials: "same-origin", headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(String(response.status));
    const payload = await response.json();
    if (payload.status !== "ok" || payload.schema_version !== "1") throw new Error("invalid payload");
    const profile = payload.profile;
    const match = payload.latest_match;
    const job = payload.latest_job;
    byId("profile-name").textContent = profile ? text(profile.display_name, "이름 미확인") : "플레이어 정보 대기 중";
    byId("profile-meta").textContent = profile ? `${text(profile.character)} · ${text(profile.rank_name)} · ${score(profile.mr, profile.lp)}` : "수집 후 자동으로 표시됩니다.";
    byId("match-result").textContent = match ? `${text(match.result)} · ${text(match.my_character)}` : "최근 대전 없음";
    byId("match-meta").textContent = match ? `상대 ${text(match.opponent_name)} · ${text(match.opponent_character)} · ${score(match.opponent_mr, match.opponent_lp)}` : "수집 후 자동으로 표시됩니다.";
    byId("job-status").textContent = job ? `작업 ${text(job.type)} · ${text(job.state)}${job.phase ? ` · ${text(job.phase)}` : ""}` : "작업 상태 대기 중";
    byId("overlay-status").textContent = "연결됨";
  } catch (_) {
    byId("overlay-status").textContent = "연결 재시도 중";
    byId("job-status").textContent = "로컬 서비스 연결을 기다리는 중";
  } finally {
    refreshInFlight = false;
  }
}

void refresh();
window.setInterval(() => { void refresh(); }, POLL_INTERVAL_MS);
