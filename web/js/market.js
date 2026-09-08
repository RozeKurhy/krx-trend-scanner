(function () {
  "use strict";

  const RANKING_URL = "./data/market-ranking.json";
  const THEME_STORAGE_KEY = "krx-theme";
  const THEME_VALUES = new Set(["light", "dark"]);
  const SYSTEM_THEME_QUERY = "(prefers-color-scheme: dark)";
  const HORIZONS = ["2w", "1m", "3m", "6m", "12m"];
  const HORIZON_LABELS = { "2w": "2주", "1m": "1개월", "3m": "3개월", "6m": "6개월", "12m": "12개월" };
  const MARKET_LABELS = { KOSPI: "코스피", KOSDAQ: "코스닥", KONEX: "코넥스" };
  const STAGE_LABELS = {
    WEAK: "약세",
    BASE: "기반 형성",
    TRANSITION: "전환",
    EARLY_TREND: "상승 초기",
    PROGRESSED: "상승 진행",
    UNAVAILABLE: "확인 필요",
  };
  const FLOW_LABELS = {
    FLOW_ACCUMULATION: "매수 우위",
    FLOW_DISTRIBUTION: "매도 우위",
    FLOW_MIXED: "혼합 흐름",
    FLOW_RECENT_WEAKENING: "최근 약화",
    FLOW_RECENT_RECOVERY: "최근 회복",
    FLOW_UNAVAILABLE: "정보 없음",
  };
  const ACTION_LABELS = {
    ENTRY: "진입 조건 충족",
    ENTER_NEXT_OPEN: "진입 조건 충족",
    HOLD: "보유 유지",
    EXIT: "매도 조건 충족",
    WATCH: "관찰 중",
    WAIT: "관찰 중",
    NONE: "전략 데이터 없음",
  };

  const byId = (id) => document.getElementById(id);
  const numberFormat = new Intl.NumberFormat("ko-KR");
  let ranking = null;
  let activeHorizon = "1m";
  let activeMarket = "ALL";
  let searchQuery = "";

  function setText(id, value) {
    const element = byId(id);
    if (element) element.textContent = value == null || value === "" ? "—" : String(value);
  }

  function createElement(tagName, className, text) {
    const element = document.createElement(tagName);
    if (className) element.className = className;
    if (text != null) element.textContent = text;
    return element;
  }

  function formatNumber(value, maximumFractionDigits) {
    if (value == null || value === "" || !Number.isFinite(Number(value))) return "—";
    return new Intl.NumberFormat("ko-KR", { maximumFractionDigits: maximumFractionDigits == null ? 0 : maximumFractionDigits }).format(Number(value));
  }

  function formatDate(value) {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}/.test(value)) return "—";
    return value.slice(0, 10).replaceAll("-", ".");
  }

  function formatPrice(value) {
    return value == null || value === "" || !Number.isFinite(Number(value)) ? "—" : `${formatNumber(value)}원`;
  }

  function marketLabel(value) { return MARKET_LABELS[value] || "시장 확인 필요"; }
  function stageLabel(value) { return STAGE_LABELS[value] || "확인 필요"; }
  function flowLabel(value) { return FLOW_LABELS[value] || "정보 없음"; }
  function actionLabel(value) { return ACTION_LABELS[value] || "전략 판단 확인 필요"; }

  function readStoredTheme() {
    try {
      const value = localStorage.getItem(THEME_STORAGE_KEY);
      return THEME_VALUES.has(value) ? value : null;
    } catch (error) {
      return null;
    }
  }

  function systemTheme() {
    return window.matchMedia && window.matchMedia(SYSTEM_THEME_QUERY).matches ? "dark" : "light";
  }

  function applyTheme(theme) {
    const resolved = THEME_VALUES.has(theme) ? theme : systemTheme();
    document.documentElement.dataset.theme = resolved;
    const button = byId("theme-toggle");
    if (!button) return;
    const next = resolved === "dark" ? "light" : "dark";
    const label = next === "dark" ? "어둡게 보기" : "밝게 보기";
    button.setAttribute("aria-label", label);
    button.title = label;
    button.setAttribute("aria-pressed", String(resolved === "dark"));
    setText("theme-toggle-label", label);
    const sun = byId("theme-icon-sun");
    const moon = byId("theme-icon-moon");
    if (sun) sun.hidden = next !== "light";
    if (moon) moon.hidden = next !== "dark";
  }

  function initTheme() {
    applyTheme(readStoredTheme() || systemTheme());
    const button = byId("theme-toggle");
    if (button) {
      button.addEventListener("click", () => {
        const current = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
        const next = current === "dark" ? "light" : "dark";
        try {
          localStorage.setItem(THEME_STORAGE_KEY, next);
        } catch (error) {
          // Theme switching still works for the current page when storage is unavailable.
        }
        applyTheme(next);
      });
    }
    if (window.matchMedia) {
      const media = window.matchMedia(SYSTEM_THEME_QUERY);
      const syncWithSystem = () => {
        if (!readStoredTheme()) applyTheme(systemTheme());
      };
      if (media.addEventListener) media.addEventListener("change", syncWithSystem);
      else if (media.addListener) media.addListener(syncWithSystem);
    }
  }

  function validPercentile(value) {
    return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 100;
  }

  function percentileField(horizon) { return `percentile_${horizon}`; }

  function isEligible(item, horizon) {
    return Boolean(
      item && item.asset_type === "COMMON" &&
      item.market_strength_applicability === "APPLICABLE" &&
      item.market_strength_status === "READY" &&
      validPercentile(item[percentileField(horizon)])
    );
  }

  function itemMatches(item) {
    const normalized = searchQuery.trim().toLocaleLowerCase("ko-KR");
    if (!normalized) return true;
    return [item.ticker, item.name, item.sector_name].some((value) => String(value || "").toLocaleLowerCase("ko-KR").includes(normalized));
  }

  function rankedItems() {
    const field = percentileField(activeHorizon);
    return (ranking.items || [])
      .filter((item) => isEligible(item, activeHorizon))
      .filter((item) => activeMarket === "ALL" || item.market === activeMarket)
      .filter(itemMatches)
      .slice()
      .sort((left, right) => {
        const percentileOrder = right[field] - left[field];
        if (percentileOrder !== 0) return percentileOrder;
        const nameOrder = String(left.name || "").localeCompare(String(right.name || ""), "ko-KR");
        if (nameOrder !== 0) return nameOrder;
        return String(left.ticker || "").localeCompare(String(right.ticker || ""));
      });
  }

  function topPercentLabel(percentile) {
    const topPercent = Math.max(0, Math.min(100, 100 - percentile));
    return `상위 ${formatNumber(topPercent, 1)}%`;
  }

  function createField(label, value, detail, className) {
    const field = createElement("span", `market-ranking-field${className ? ` ${className}` : ""}`);
    field.appendChild(createElement("small", "market-ranking-label", label));
    field.appendChild(createElement("strong", "market-ranking-value", value));
    if (detail) field.appendChild(createElement("small", "market-ranking-detail", detail));
    return field;
  }

  function createPriceField(item) {
    return createField("현재가", formatPrice(item.latest_close), formatDate(item.latest_close_as_of), "market-ranking-price");
  }

  function createRankingRow(item) {
    const link = createElement("a", "market-ranking-row");
    link.href = `./report.html?ticker=${encodeURIComponent(item.ticker)}`;
    link.setAttribute("aria-label", `${item.name} ${item.ticker} 리포트 보기`);

    const identity = createElement("span", "market-ranking-identity");
    identity.appendChild(createElement("strong", "market-ranking-name", item.name || item.ticker));
    const sector = item.sector_name ? ` · ${item.sector_name}` : "";
    identity.appendChild(createElement("span", "market-ranking-meta", `${item.ticker} · ${marketLabel(item.market)}${sector}`));

    const strength = createField("시장 강도", topPercentLabel(item[percentileField(activeHorizon)]), `최근 ${HORIZON_LABELS[activeHorizon]}`, "market-ranking-strength");
    const pattern = createField("패턴", item.pattern_score == null ? stageLabel(item.pattern_stage) : `${stageLabel(item.pattern_stage)} · ${formatNumber(item.pattern_score, 2)}점`);
    const flow = createField("수급", flowLabel(item.flow_state));
    const action = createField("전략 판단", actionLabel(item.strategy_action), null, "market-ranking-action");
    const price = createPriceField(item);
    const report = createElement("span", "market-ranking-report", "리포트 보기 ›");

    link.append(identity, strength, pattern, flow, action, price, report);
    return link;
  }

  function renderScope() {
    const scope = ranking.scope;
    const metricScope = ranking.metric_scope;
    setText("market-scope", `기준일 ${formatDate(ranking.as_of)} · ${scope.label} ${formatNumber(scope.report_count)}종목 · ${metricScope.label}`);
    setText("market-metric-scope", metricScope.label);
  }

  function renderControls() {
    document.querySelectorAll("[data-horizon]").forEach((button) => {
      const selected = button.dataset.horizon === activeHorizon;
      button.classList.toggle("is-active", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
    document.querySelectorAll("[data-market]").forEach((button) => {
      const selected = button.dataset.market === activeMarket;
      button.classList.toggle("is-active", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
  }

  function renderRanking() {
    if (!ranking) return;
    renderScope();
    renderControls();
    const items = rankedItems();
    const list = byId("market-ranking-list");
    while (list.firstChild) list.removeChild(list.firstChild);
    if (!items.length) {
      list.appendChild(createElement("p", "market-ranking-empty", "조건에 맞는 시장 강도 랭킹 종목이 없습니다."));
    } else {
      items.forEach((item) => list.appendChild(createRankingRow(item)));
    }
    const suffix = searchQuery.trim() ? ` · 검색 결과 ${items.length}종목` : ` · ${items.length}종목`;
    setText("market-ranking-meta", `${HORIZON_LABELS[activeHorizon]} 시장 강도${suffix}`);
  }

  function validateRanking(value) {
    return Boolean(
      value && value.schema_version === 1 &&
      value.scope && value.scope.type === "PUBLISHED_REPORTS" && Number.isInteger(value.scope.report_count) &&
      value.metric_scope && typeof value.metric_scope.label === "string" &&
      typeof value.as_of === "string" && value.eligible_counts && Array.isArray(value.items)
    );
  }

  function initInteractions() {
    document.querySelectorAll("[data-horizon]").forEach((button) => {
      button.addEventListener("click", () => {
        if (HORIZONS.includes(button.dataset.horizon)) {
          activeHorizon = button.dataset.horizon;
          renderRanking();
        }
      });
    });
    document.querySelectorAll("[data-market]").forEach((button) => {
      button.addEventListener("click", () => {
        activeMarket = button.dataset.market || "ALL";
        renderRanking();
      });
    });
    const search = byId("market-search");
    if (search) search.addEventListener("input", () => {
      searchQuery = search.value;
      renderRanking();
    });
  }

  async function loadRanking() {
    const response = await fetch(RANKING_URL, { cache: "no-store" });
    if (!response.ok) throw new Error("market ranking request failed");
    const value = await response.json();
    if (!validateRanking(value)) throw new Error("market ranking schema is incomplete");
    ranking = value;
    renderRanking();
  }

  initTheme();
  initInteractions();
  loadRanking().catch(() => {
    const error = byId("market-error");
    if (error) error.hidden = false;
  });
}());
