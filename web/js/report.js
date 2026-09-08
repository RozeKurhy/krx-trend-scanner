(function () {
  "use strict";

  const INDEX_URL = "./data/stock-index.json";
  const STOCKS_PATH = "./data/stocks/";
  const THEME_STORAGE_KEY = "krx-theme";
  const THEME_VALUES = new Set(["light", "dark"]);
  const SYSTEM_THEME_QUERY = "(prefers-color-scheme: dark)";
  const MARKET_LABELS = { KOSPI: "코스피", KOSDAQ: "코스닥", KONEX: "코넥스" };
  const ASSET_LABELS = { COMMON: "보통주", ETF: "ETF" };
  const ACTION_LABELS = {
    WATCH: "관찰 중",
    ENTRY: "진입 조건 충족",
    ENTER_NEXT_OPEN: "진입 조건 충족",
    HOLD: "보유 유지",
    EXIT: "매도 조건 충족",
    WAIT: "관찰 중",
    NONE: "전략 데이터 없음",
  };
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
  const MARKET_STRENGTH_LABELS = {
    RECOVERING: "회복 흐름",
    IMPROVING: "개선 흐름",
    WEAKENING: "약화 흐름",
    MIXED: "혼합 흐름",
    UNAVAILABLE: "정보 없음",
  };
  const TRADING_VALUE_LABELS = {
    TRADING_VALUE_EXPANDING: "증가 흐름",
    TRADING_VALUE_MIXED: "혼합 흐름",
    TRADING_VALUE_WEAKENING: "감소 흐름",
    TRADING_VALUE_STABLE: "안정 흐름",
    INCREASING: "증가 흐름",
    DECREASING: "감소 흐름",
    STABLE: "안정 흐름",
    UNAVAILABLE: "정보 없음",
  };
  const STRATEGY_STATE_DETAILS = {
    HOLD_PROGRESSED: "추세 진행 구간의 보유 상태를 확인합니다.",
    HOLD_PRE_PROGRESSED: "초기 추세 구간의 보유 상태를 확인합니다.",
    WAIT: "진입 전 관찰 상태입니다.",
    ENTRY: "진입 조건 충족 상태입니다.",
    NOT_APPLICABLE: "현재 전략 적용 대상이 아닙니다.",
  };
  const FLOW_DETAILS = {
    FLOW_ACCUMULATION: "최근 외국인 수급은 매수 우위입니다.",
    FLOW_DISTRIBUTION: "최근 외국인 수급은 매도 우위입니다.",
    FLOW_MIXED: "최근 외국인 수급은 혼합 흐름입니다.",
    FLOW_RECENT_WEAKENING: "최근 외국인 수급은 약화 흐름입니다.",
    FLOW_RECENT_RECOVERY: "최근 외국인 수급은 회복 흐름입니다.",
    FLOW_UNAVAILABLE: "최근 외국인 수급 정보가 없습니다.",
  };

  const byId = (id) => document.getElementById(id);
  const numberFormat = new Intl.NumberFormat("ko-KR");
  let indexData = null;
  let searchMatches = [];

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

  function setText(id, value) {
    const element = byId(id);
    if (element) element.textContent = value == null || value === "" ? "—" : String(value);
  }

  function setHidden(id, hidden) {
    const element = byId(id);
    if (element) element.hidden = hidden;
  }

  function formatNumber(value, maximumFractionDigits) {
    if (value == null || value === "" || !Number.isFinite(Number(value))) return "—";
    return new Intl.NumberFormat("ko-KR", { maximumFractionDigits: maximumFractionDigits == null ? 0 : maximumFractionDigits }).format(Number(value));
  }

  function formatPrice(value) {
    return value == null || value === "" || !Number.isFinite(Number(value)) ? "—" : `${formatNumber(value)}원`;
  }

  function formatDate(value) {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}/.test(value)) return "—";
    return value.slice(0, 10).replaceAll("-", ".");
  }

  function label(map, value, fallback) {
    return Object.prototype.hasOwnProperty.call(map, value) ? map[value] : (fallback || "정보 없음");
  }

  function marketLabel(value) { return label(MARKET_LABELS, value, value || "시장 정보 없음"); }
  function assetLabel(value) { return label(ASSET_LABELS, value, value || "자산 유형 확인 필요"); }
  function actionLabel(value) { return label(ACTION_LABELS, value, "전략 판단 확인 필요"); }
  function stageLabel(value) { return label(STAGE_LABELS, value, "확인 필요"); }
  function flowLabel(value) { return label(FLOW_LABELS, value, "정보 없음"); }
  function marketStrengthLabel(value) { return label(MARKET_STRENGTH_LABELS, value, "정보 없음"); }
  function tradingValueLabel(value) { return label(TRADING_VALUE_LABELS, value, "정보 없음"); }
  function strategyDetail(value) { return label(STRATEGY_STATE_DETAILS, value, "전략 상태 확인 필요"); }
  function flowDetail(value) { return label(FLOW_DETAILS, value, "수급 상태 확인 필요"); }

  function validateIndex(value) {
    return Boolean(value && typeof value === "object" && Array.isArray(value.items) && Number.isInteger(value.count));
  }

  function validateReport(value, ticker) {
    return Boolean(
      value && typeof value === "object" && value.identity && value.identity.ticker === ticker &&
      value.decision && value.summary && value.price_trend && value.pattern && value.market_strength &&
      value.flow && value.fundamentals && value.strategy && value.technical_details
    );
  }

  function currentTicker() {
    return new URL(window.location.href).searchParams.get("ticker");
  }

  function updateUrl(ticker) {
    const url = new URL(window.location.href);
    if (ticker) url.searchParams.set("ticker", ticker);
    else url.searchParams.delete("ticker");
    window.history.pushState({}, "", url);
  }

  function renderSearchResults(query) {
    const results = byId("search-results");
    if (!results || !indexData) return;
    while (results.firstChild) results.removeChild(results.firstChild);
    const normalized = String(query || "").trim().toLocaleLowerCase("ko-KR");
    if (!normalized) {
      results.hidden = true;
      searchMatches = [];
      return;
    }
    searchMatches = indexData.items.filter((item) => (
      String(item.ticker).toLocaleLowerCase("ko-KR").includes(normalized) ||
      String(item.name).toLocaleLowerCase("ko-KR").includes(normalized)
    )).slice(0, 12);
    searchMatches.forEach((item) => {
      const li = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "search-result-button";
      const copy = document.createElement("span");
      copy.className = "search-result-copy";
      const name = document.createElement("strong");
      name.className = "search-result-name";
      name.textContent = item.name;
      const meta = document.createElement("span");
      meta.className = "search-result-meta";
      meta.textContent = `${item.ticker} · ${marketLabel(item.market)}`;
      copy.append(name, meta);
      const status = document.createElement("small");
      status.className = "search-result-status";
      status.textContent = item.report_available ? "리포트 보기" : "리포트 준비 중";
      button.append(copy, status);
      button.addEventListener("click", () => selectTicker(item.ticker));
      li.appendChild(button);
      results.appendChild(li);
    });
    results.hidden = searchMatches.length === 0;
  }

  function showEmpty() {
    setHidden("report-empty", false);
    setHidden("report-pending", true);
    setHidden("report-view", true);
    setHidden("report-error", true);
  }

  function showPending(item) {
    setHidden("report-empty", true);
    setHidden("report-pending", false);
    setHidden("report-view", true);
    setHidden("report-error", true);
    setText("pending-detail", `${item.name}(${item.ticker})의 현재 공개된 종목 리포트가 없습니다.`);
  }

  function showError(message) {
    setHidden("report-empty", true);
    setHidden("report-pending", true);
    setHidden("report-view", true);
    setHidden("report-error", false);
    setText("report-error-detail", message || "데이터 파일을 확인해 주세요.");
  }

  function buildSummary(report) {
    const trend = `추세는 ${stageLabel(report.summary.trend_stage)} 상태입니다.`;
    const market = report.summary.market_strength_state === "UNAVAILABLE"
      ? "시장 대비 강도는 확인이 필요합니다."
      : `시장 대비 강도는 ${marketStrengthLabel(report.summary.market_strength_state)}입니다.`;
    const flow = `수급은 ${flowLabel(report.summary.flow_state)}입니다.`;
    return `${trend} ${market} ${flow}`;
  }

  function appendDetail(list, name, value) {
    const wrapper = document.createElement("div");
    const term = document.createElement("dt");
    term.textContent = name;
    const description = document.createElement("dd");
    description.textContent = value == null || value === "" ? "—" : String(value);
    wrapper.append(term, description);
    list.appendChild(wrapper);
  }

  function renderTechnicalDetails(report) {
    const list = byId("technical-detail-list");
    if (!list) return;
    while (list.firstChild) list.removeChild(list.firstChild);
    const details = report.technical_details;
    appendDetail(list, "기준일", details.requested_as_of);
    appendDetail(list, "시장 데이터 기준일", details.reference_market_date);
    appendDetail(list, "리포트 상태", details.report_status);
    appendDetail(list, "자산 유형", details.asset_type);
    appendDetail(list, "Pattern A 단계", details.pattern_stage);
    appendDetail(list, "Pattern A 점수", details.pattern_score == null ? "—" : formatNumber(details.pattern_score, 2));
    appendDetail(list, "전략 상태", report.strategy.state);
    appendDetail(list, "전략 행동", report.strategy.action);
    appendDetail(list, "수급 상태", details.flow_state);
    appendDetail(list, "시장 강도 데이터", details.relative_strength_status);
    appendDetail(list, "거래대금 상태", details.trading_value_state);
    appendDetail(list, "원본 리포트", details.source_report);
  }

  function renderReport(report) {
    const identity = report.identity;
    const market = marketLabel(identity.market);
    setHidden("report-empty", true);
    setHidden("report-pending", true);
    setHidden("report-error", true);
    setHidden("report-view", false);
    setText("report-name", identity.name);
    setText("report-identity", `${identity.ticker} · ${market} · ${assetLabel(identity.asset_type)}`);
    setText("decision-heading", actionLabel(report.decision.action));
    setText("decision-summary", buildSummary(report));
    setText("signal-trend", stageLabel(report.summary.trend_stage));
    setText("signal-market", marketStrengthLabel(report.summary.market_strength_state));
    setText("signal-flow", flowLabel(report.summary.flow_state));
    setText("price-value", formatPrice(report.price_trend.latest_close));
    setText("price-detail", `기준일 ${formatDate(report.price_trend.latest_close_as_of)} · 거래대금 ${tradingValueLabel(report.price_trend.trading_value_state)}`);
    setText("pattern-value", stageLabel(report.pattern.official_stage));
    setText("pattern-detail", report.pattern.score == null ? "점수 확인 필요" : `Pattern A 점수 ${formatNumber(report.pattern.score, 2)}점`);
    setText("market-value", marketStrengthLabel(report.market_strength.state));
    setText("market-detail", `${report.market_strength.benchmark_name || "시장"} 대비 ${marketStrengthLabel(report.market_strength.state)}입니다.`);
    setText("flow-value", flowLabel(report.flow.state));
    setText("flow-detail", flowDetail(report.flow.state));
    setText("strategy-value", actionLabel(report.strategy.action));
    setText("strategy-detail", strategyDetail(report.strategy.state));
    renderTechnicalDetails(report);
    const naver = byId("naver-link");
    if (naver && report.external_links && typeof report.external_links.naver_finance === "string") {
      naver.href = report.external_links.naver_finance;
    }
  }

  async function loadSelected(item) {
    if (!item.report_available) {
      showPending(item);
      return;
    }
    try {
      const response = await fetch(`${STOCKS_PATH}${encodeURIComponent(item.ticker)}.json`, { cache: "no-store" });
      if (!response.ok) throw new Error("stock report request failed");
      const report = await response.json();
      if (!validateReport(report, item.ticker)) throw new Error("stock report schema is incomplete");
      renderReport(report);
    } catch (error) {
      showError("종목 리포트 파일을 확인해 주세요.");
    }
  }

  function selectTicker(ticker) {
    const item = indexData && indexData.items.find((candidate) => candidate.ticker === ticker);
    if (!item) {
      showError("종목 정보를 찾을 수 없습니다.");
      return;
    }
    const input = byId("stock-search");
    if (input) input.value = item.name;
    const results = byId("search-results");
    if (results) results.hidden = true;
    updateUrl(item.ticker);
    loadSelected(item);
  }

  async function loadIndex() {
    const response = await fetch(INDEX_URL, { cache: "no-store" });
    if (!response.ok) throw new Error("stock index request failed");
    const value = await response.json();
    if (!validateIndex(value)) throw new Error("stock index schema is incomplete");
    indexData = value;
    setText("search-meta", `전체 ${formatNumber(value.count)}개 종목 · 리포트 ${formatNumber(value.available_report_count)}개`);
    const ticker = currentTicker();
    if (!ticker) {
      showEmpty();
      return;
    }
    const item = value.items.find((candidate) => candidate.ticker === ticker);
    if (!item) {
      showError("종목 정보를 찾을 수 없습니다.");
      return;
    }
    const input = byId("stock-search");
    if (input) input.value = item.name;
    await loadSelected(item);
  }

  initTheme();
  const input = byId("stock-search");
  if (input) {
    input.addEventListener("input", () => renderSearchResults(input.value));
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && searchMatches[0]) {
        event.preventDefault();
        selectTicker(searchMatches[0].ticker);
      } else if (event.key === "Escape") {
        input.value = "";
        renderSearchResults("");
      }
    });
  }
  window.addEventListener("popstate", () => {
    const ticker = currentTicker();
    if (!ticker) {
      if (input) input.value = "";
      showEmpty();
      return;
    }
    const item = indexData && indexData.items.find((candidate) => candidate.ticker === ticker);
    if (!item) {
      showError("종목 정보를 찾을 수 없습니다.");
      return;
    }
    if (input) input.value = item.name;
    loadSelected(item);
  });
  loadIndex().catch(() => showError("종목 목록 파일을 확인해 주세요."));
}());
