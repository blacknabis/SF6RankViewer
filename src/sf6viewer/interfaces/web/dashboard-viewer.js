"use strict";

(function exposeDashboardViewer(root, factory) {
  const api = Object.freeze(factory());
  if (typeof module === "object" && module.exports) module.exports = api;
  else if (root) root.SF6DashboardViewer = api;
})(typeof globalThis === "object" ? globalThis : this, function createDashboardViewerBoundary() {
  const SVG_NS = "http://www.w3.org/2000/svg";
  const RESULT_LABELS = Object.freeze({ WIN: "승리", LOSE: "패배", DRAW: "무승부" });

  function create({ document, metrics }) {
    if (!document || typeof document.getElementById !== "function") throw new TypeError("document dependency is required");
    if (!metrics || typeof metrics.winRate !== "function") throw new TypeError("metrics dependency is required");

    const element = (id) => document.getElementById(id);
    const finite = (value) => typeof value === "number" && Number.isFinite(value);
    const display = (value) => value === null || value === undefined || value === "" ? "—" : String(value);
    const number = (value) => finite(value) ? new Intl.NumberFormat("ko-KR").format(value) : "—";
    const clear = (node) => { while (node && node.firstChild) node.removeChild(node.firstChild); };
    const feedNodes = new Map();

    function setText(id, value) {
      const node = element(id);
      if (node) node.textContent = value;
    }

    function formatDate(value) {
      if (!finite(value)) return "일시 정보 없음";
      return new Intl.DateTimeFormat("ko-KR", {
        month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"
      }).format(new Date(value));
    }

    function renderRecord(prefix, record) {
      const wins = finite(record && record.wins) ? record.wins : 0;
      const losses = finite(record && record.losses) ? record.losses : 0;
      const rate = metrics.winRate(wins, losses);
      setText(`${prefix}-rate`, `${rate.toFixed(1)}%`);
      setText(`${prefix}-record`, `${wins}W ${losses}L`);
      const progress = element(`${prefix}-progress`);
      if (progress) {
        progress.value = rate;
        progress.textContent = `${rate.toFixed(1)}%`;
      }
    }

    function deltaClass(delta) {
      if (!finite(delta) || delta === 0) return "delta-neutral";
      return delta > 0 ? "delta-positive" : "delta-negative";
    }

    function renderDelta(payload, preferences) {
      const range = metrics.rangeDelta(payload.mr_history, preferences.chartLimit);
      const session = payload.session && typeof payload.session === "object" ? payload.session : {};
      const delta = preferences.deltaMode === "range" ? range.delta : session.delta;
      const target = element("kpi-session-delta");
      if (target) {
        target.textContent = metrics.deltaLabel(delta);
        target.classList.remove("delta-positive", "delta-negative", "delta-neutral");
        target.classList.add(deltaClass(delta));
      }
      if (preferences.deltaMode === "range") {
        setText("kpi-session-context", range.pointCount === 1
          ? "기준 데이터 1건"
          : `표시 구간 최근 ${preferences.chartLimit}전`);
      } else {
        setText("kpi-session-context", session.boundary_kind === "MATCH_RESET"
          ? "전적 초기화 이후"
          : "앱 시작 기준");
      }
    }

    function renderProfile(profile) {
      const empty = !profile;
      setText("viewer-profile-name", empty ? "플레이어 정보 없음" : display(profile.display_name));
      setText("viewer-profile-character", empty ? "—" : display(profile.character));
      setText("viewer-profile-rank", empty ? "—" : display(profile.rank_name));
      setText("viewer-profile-rating", empty ? "— MR / — LP" : `${number(profile.mr)} MR / ${number(profile.lp)} LP`);
      const emptyState = element("viewer-profile-empty");
      if (emptyState) emptyState.hidden = !empty;
    }

    function renderLive(presentation) {
      const safe = presentation && typeof presentation.live === "boolean"
        ? presentation
        : { live: false, text: "자동 수집 상태 확인 불가" };
      const badge = element("viewer-live-badge");
      if (badge) {
        badge.dataset.live = String(safe.live);
        const label = badge.lastElementChild;
        if (label) label.textContent = safe.text;
      }
      setText("viewer-live-status", safe.text);
    }

    function renderStreak(streak) {
      if (!streak || !Number.isInteger(streak.count) || streak.count < 1) {
        setText("kpi-streak-value", "—");
        setText("kpi-streak-context", "현재 연속 결과 없음");
        return;
      }
      const won = streak.result === "WIN";
      setText("kpi-streak-value", `${streak.count}연${won ? "승 🔥" : "패 ❄️"}`);
      setText("kpi-streak-context", won ? "연승 진행 중" : "연패 진행 중");
    }

    function tooltipText(point) {
      return [
        formatDate(point.occurred_at_ms),
        `${display(point.opponent_name)} · ${display(point.opponent_character)}`,
        `${number(point.mr)} MR · ${RESULT_LABELS[point.result] || display(point.result)}`
      ].join(" / ");
    }

    function hideTooltip() {
      const tooltip = element("mr-chart-tooltip");
      if (tooltip) tooltip.hidden = true;
    }

    function showTooltip(point, x, y) {
      const content = tooltipText(point);
      const tooltip = element("mr-chart-tooltip");
      if (tooltip) {
        tooltip.textContent = content;
        tooltip.style.left = `${Math.max(2, Math.min(82, (x / 760) * 100))}%`;
        tooltip.style.top = `${Math.max(2, Math.min(82, (y / 280) * 100))}%`;
        tooltip.hidden = false;
      }
      setText("mr-chart-tooltip-status", content);
    }

    function renderChart(history, limit) {
      const points = metrics.sliceMrHistory(history, limit).slice().sort((left, right) => left.occurred_at_ms - right.occurred_at_ms);
      const area = element("mr-chart-area");
      const line = element("mr-chart-line");
      const group = element("mr-chart-points");
      const dataList = element("mr-chart-data");
      clear(group);
      clear(dataList);
      hideTooltip();
      const empty = points.length === 0;
      const emptyState = element("chart-empty");
      if (emptyState) emptyState.hidden = !empty;
      if (area) area.setAttribute("d", "");
      if (line) line.setAttribute("d", "");
      if (empty) {
        setText("chart-state", "표시할 MR 기록이 없습니다.");
        return;
      }

      const left = 20;
      const right = 740;
      const top = 20;
      const bottom = 255;
      const values = points.map((point) => point.mr);
      let minimum = Math.min(...values);
      let maximum = Math.max(...values);
      if (minimum === maximum) {
        minimum -= 10;
        maximum += 10;
      } else {
        const padding = Math.max(5, (maximum - minimum) * 0.12);
        minimum -= padding;
        maximum += padding;
      }
      const coordinates = points.map((point, index) => ({
        point,
        x: points.length === 1 ? (left + right) / 2 : left + ((right - left) * index) / (points.length - 1),
        y: bottom - ((point.mr - minimum) / (maximum - minimum)) * (bottom - top)
      }));
      const linePath = coordinates.map(({ x, y }, index) => `${index ? "L" : "M"}${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
      if (line) line.setAttribute("d", linePath);
      if (area) {
        const last = coordinates[coordinates.length - 1];
        area.setAttribute("d", `${linePath} L${last.x.toFixed(2)},${bottom} L${coordinates[0].x.toFixed(2)},${bottom} Z`);
      }
      for (const coordinate of coordinates) {
        const target = document.createElementNS(SVG_NS, "circle");
        target.setAttribute("class", "chart-point");
        target.setAttribute("cx", coordinate.x.toFixed(2));
        target.setAttribute("cy", coordinate.y.toFixed(2));
        target.setAttribute("r", "4");
        target.setAttribute("tabindex", "0");
        target.setAttribute("aria-label", tooltipText(coordinate.point));
        target.addEventListener("mouseenter", () => showTooltip(coordinate.point, coordinate.x, coordinate.y));
        target.addEventListener("focus", () => showTooltip(coordinate.point, coordinate.x, coordinate.y));
        target.addEventListener("mouseleave", hideTooltip);
        target.addEventListener("blur", hideTooltip);
        group.appendChild(target);
        if (dataList) appendText(dataList, "li", "", tooltipText(coordinate.point));
      }
      setText("chart-state", `${points.length}건의 MR 기록을 시간순으로 표시합니다.`);
    }

    function appendText(parent, tag, className, value) {
      const node = document.createElement(tag);
      if (className) node.className = className;
      node.textContent = value;
      parent.appendChild(node);
      return node;
    }

    function renderMatchups(matchups) {
      const grid = element("matchup-grid");
      clear(grid);
      const items = Array.isArray(matchups) ? matchups : [];
      const empty = items.length === 0;
      const emptyState = element("matchup-empty");
      if (emptyState) emptyState.hidden = !empty;
      for (const matchup of items) {
        const wins = finite(matchup.wins) ? matchup.wins : 0;
        const losses = finite(matchup.losses) ? matchup.losses : 0;
        const tier = metrics.matchupTier(wins, losses);
        const card = document.createElement("article");
        card.className = "matchup-card";
        card.dataset.tier = tier.key;
        appendText(card, "strong", "matchup-character", display(matchup.character));
        appendText(card, "span", "matchup-rate", `${tier.rate.toFixed(1)}%`);
        appendText(card, "span", "muted", `${wins}W ${losses}L · ${wins + losses}전`);
        appendText(card, "span", "matchup-tier", tier.label);
        grid.appendChild(card);
      }
      setText("matchup-state", empty ? "집계할 상성 전적이 없습니다." : `${items.length}개 캐릭터 상성을 표시합니다.`);
    }

    function renderAggregate({ payload, preferences, live } = {}) {
      const safePayload = payload && typeof payload === "object" ? payload : {};
      const safePreferences = metrics.normalizeObsOptions(preferences);
      renderProfile(safePayload.viewer_profile || null);
      const statistics = safePayload.statistics && typeof safePayload.statistics === "object" ? safePayload.statistics : {};
      renderRecord("kpi-total", statistics.total);
      renderRecord("kpi-recent", statistics.recent);
      renderDelta(safePayload, safePreferences);
      renderStreak(safePayload.streak);
      renderLive(live);
      renderChart(safePayload.mr_history, safePreferences.chartLimit);
      renderMatchups(safePayload.matchups);
      const select = element("viewer-delta-mode");
      if (select) select.value = safePreferences.deltaMode;
      for (const chartLimit of metrics.SUPPORTED_LIMITS) {
        const chip = element(`chart-limit-${chartLimit}`);
        if (chip) chip.setAttribute("aria-pressed", String(chartLimit === safePreferences.chartLimit));
      }
    }

    function matchRating(match) {
      if (finite(match.opponent_mr)) return `${number(match.opponent_mr)} MR`;
      if (finite(match.opponent_lp)) return `${number(match.opponent_lp)} LP`;
      return "등급 정보 없음";
    }

    function createFeedCard() {
      const item = document.createElement("li");
      item.className = "match-card";
      const header = document.createElement("div");
      header.className = "match-card-header";
      const result = appendText(header, "strong", "match-card-result", "");
      const delta = appendText(header, "span", "match-delta-neutral", "");
      item.appendChild(header);
      const versus = appendText(item, "strong", "match-versus", "");
      const opponent = appendText(item, "span", "match-opponent", "");
      const meta = document.createElement("div");
      meta.className = "match-card-meta";
      const relative = appendText(meta, "span", "muted", "");
      const occurred = appendText(meta, "span", "muted", "");
      item.appendChild(meta);
      return { item, result, delta, versus, opponent, relative, occurred };
    }

    function updateFeedCard(card, match, now) {
      const result = Object.prototype.hasOwnProperty.call(RESULT_LABELS, match.result) ? match.result : "DRAW";
      card.item.dataset.result = result;
      card.result.textContent = RESULT_LABELS[result];
      card.delta.className = deltaClass(match.mr_delta).replace("delta", "match-delta");
      card.delta.textContent = metrics.deltaLabel(match.mr_delta);
      card.delta.setAttribute("aria-label", `MR 변동 ${metrics.deltaLabel(match.mr_delta)}`);
      card.versus.textContent = `${display(match.my_character)} vs ${display(match.opponent_character)}`;
      card.opponent.textContent = `${display(match.opponent_name)} · ${matchRating(match)}`;
      card.relative.textContent = metrics.relativeTimeKo(match.occurred_at_ms, now);
      card.occurred.textContent = formatDate(match.occurred_at_ms);
    }

    function renderFeed(feedState = {}) {
      const list = element("match-feed-list");
      const items = Array.isArray(feedState.items) ? feedState.items : [];
      const now = Date.now();
      const retained = new Set();
      items.forEach((match, index) => {
        const key = typeof match.id === "string" && match.id
          ? match.id
          : `anonymous:${match.occurred_at_ms || 0}:${index}`;
        retained.add(key);
        let card = feedNodes.get(key);
        if (!card) {
          card = createFeedCard();
          feedNodes.set(key, card);
        }
        updateFeedCard(card, match, now);
        list.appendChild(card.item);
      });
      for (const [key, card] of feedNodes) {
        if (!retained.has(key)) {
          card.item.remove();
          feedNodes.delete(key);
        }
      }
      const empty = items.length === 0 && !feedState.inFlight;
      const emptyState = element("match-feed-empty");
      if (emptyState) emptyState.hidden = !empty;
      const more = element("match-feed-load-more");
      if (more) {
        more.disabled = feedState.inFlight === true;
        more.hidden = empty || feedState.exhausted === true;
        more.textContent = feedState.inFlight ? "불러오는 중…" : "더 보기";
      }
      setText("match-feed-state", feedState.inFlight
        ? "대전 기록을 불러오는 중입니다."
        : empty ? "아직 수집된 대전 기록이 없습니다."
          : feedState.exhausted ? "모든 대전 기록을 표시했습니다."
            : `${items.length}건 표시 중`);
    }

    function setRegionState(region, state = {}) {
      const statusIds = { aggregate: "viewer-state", chart: "chart-state", feed: "match-feed-state", matchup: "matchup-state" };
      const id = statusIds[region];
      if (id && typeof state.message === "string") setText(id, state.message);
      const error = element("viewer-error");
      if (error && region === "aggregate") {
        error.hidden = state.stale !== true;
        if (state.stale && typeof state.message === "string") error.textContent = state.message;
      }
    }

    let interactionsBound = false;
    function bindInteractions({ onDeltaMode, onChartLimit, onLoadMore } = {}) {
      if (interactionsBound) return;
      interactionsBound = true;
      const safely = (callback, value) => {
        if (typeof callback !== "function") return;
        try { Promise.resolve(callback(value)).catch(() => {}); } catch (_) { /* coordinator renders recovery */ }
      };
      const deltaMode = element("viewer-delta-mode");
      if (deltaMode) deltaMode.addEventListener("change", () => safely(onDeltaMode, deltaMode.value));
      for (const chartLimit of metrics.SUPPORTED_LIMITS) {
        const chip = element(`chart-limit-${chartLimit}`);
        if (chip) chip.addEventListener("click", () => safely(onChartLimit, chartLimit));
      }
      const more = element("match-feed-load-more");
      if (more) more.addEventListener("click", () => safely(onLoadMore));
    }

    return Object.freeze({ renderAggregate, renderFeed, setRegionState, bindInteractions });
  }

  return { create };
});
