(function () {
  "use strict";

  const INDEX_URL = "./data/stock-index.json";
  const STOCKS_PATH = "./data/stocks/";
  const DART_SEARCH_URL = "https://dart.fss.or.kr/html/search/SearchCompanyIR3_M.html";
  const THEME_STORAGE_KEY = "krx-theme";
  const THEME_VALUES = new Set(["light", "dark"]);
  const SYSTEM_THEME_QUERY = "(prefers-color-scheme: dark)";
  const REPORT_MOBILE_QUERY = "(max-width: 560px)";
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
  const FUNDAMENTAL_LABELS = {
    READY: "데이터 충분",
    PARTIAL: "일부 데이터",
    DATA_UNAVAILABLE: "정보 부족",
    NOT_APPLICABLE: "해당 없음",
    NOT_AVAILABLE: "준비 중",
  };
  const FUNDAMENTAL_ROW_LABELS = {
    READY: "정상",
    PARTIAL: "일부 데이터",
    DATA_UNAVAILABLE: "정보 없음",
    NOT_APPLICABLE: "해당 없음",
  };
  const PATTERN_STEPS = [
    ["WEAK", "약세"],
    ["BASE", "기반 형성"],
    ["TRANSITION", "전환"],
    ["EARLY_TREND", "상승 초기"],
    ["PROGRESSED", "상승 진행"],
  ];
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
  const TRADE_STATUS_LABELS = {
    REALIZED: "청산 완료",
    OPEN_AT_CUTOFF: "보유 중",
  };
  const EXIT_TYPE_LABELS = {
    LOSS_GUARD_CLOSE_LE_NEG_15: "손실 제한",
    EXIT3_PROGRESSED_TO_TRANSITION: "상승 진행 → 전환",
    EXIT4_SCORE_DRAWDOWN_GE_15: "패턴 점수 하락",
    NO_EXIT_BEFORE_CUTOFF: "기준일 현재 보유 중",
  };
  const DETAIL_BUTTON_LABELS = {
    price: "가격·추세",
    pattern: "패턴 점수",
    market: "마켓 RS",
    flow: "수급",
    strategy: "전략",
  };
  const DETAIL_BUTTON_IDS = {
    price: "price-card",
    pattern: "pattern-card",
    market: "market-card",
    flow: "flow-card",
    strategy: "strategy-card",
  };

  const byId = (id) => document.getElementById(id);
  const numberFormat = new Intl.NumberFormat("ko-KR");
  let indexData = null;
  let searchMatches = [];
  let currentReport = null;
  let activeDetailKey = null;

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

  function formatSignedRate(value) {
    if (value == null || value === "" || !Number.isFinite(Number(value))) return "—";
    const number = Number(value) * 100;
    const sign = number > 0 ? "+" : number < 0 ? "−" : "";
    return `${sign}${formatNumber(Math.abs(number), 2)}%`;
  }

  function formatSignedPercentPoints(value) {
    if (value == null || value === "" || !Number.isFinite(Number(value))) return "—";
    const number = Number(value);
    const sign = number > 0 ? "+" : number < 0 ? "−" : "";
    return `${sign}${formatNumber(Math.abs(number), 2)}%`;
  }

  function formatKrwCompact(value) {
    if (value == null || value === "" || !Number.isFinite(Number(value))) return "—";
    const number = Number(value);
    const sign = number > 0 ? "+" : number < 0 ? "−" : "";
    const absolute = Math.abs(number);
    if (absolute >= 1e12) return `${sign}${formatNumber(absolute / 1e12, 2)}조원`;
    if (absolute >= 1e8) return `${sign}${formatNumber(absolute / 1e8, 1)}억원`;
    return `${sign}${formatNumber(absolute)}원`;
  }

  function topPercentFromPercentile(value) {
    if (value == null || value === "" || !Number.isFinite(Number(value))) return null;
    return Math.max(0, Math.min(100, 100 - Number(value)));
  }

  function topPercentLabel(value) {
    const topPercent = topPercentFromPercentile(value);
    return topPercent == null ? "정보 있음" : `상위 ${formatNumber(topPercent, 1)}%`;
  }

  function label(map, value, fallback) {
    return Object.prototype.hasOwnProperty.call(map, value) ? map[value] : (fallback || "정보 없음");
  }

  function marketLabel(value) { return label(MARKET_LABELS, value, value || "시장 정보 없음"); }
  function assetLabel(value) { return label(ASSET_LABELS, value, value || "자산 유형 확인 필요"); }
  function actionLabel(value) { return label(ACTION_LABELS, value, "전략 판단 확인 필요"); }
  function stageLabel(value) { return label(STAGE_LABELS, value, "확인 필요"); }
  function flowLabel(value) { return label(FLOW_LABELS, value, "정보 없음"); }
  function tradingValueLabel(value) { return label(TRADING_VALUE_LABELS, value, "정보 없음"); }
  function strategyDetail(value) { return label(STRATEGY_STATE_DETAILS, value, "전략 상태 확인 필요"); }
  function flowDetail(value) { return label(FLOW_DETAILS, value, "수급 상태 확인 필요"); }
  function tradeStatusLabel(value) { return label(TRADE_STATUS_LABELS, value, "상태 확인 필요"); }
  function exitTypeLabel(value) { return label(EXIT_TYPE_LABELS, value, "종료 기준 확인 필요"); }

  function marketStrengthLabel(market) {
    if (!market || market.applicability === "NOT_APPLICABLE") return "해당 없음";
    if (market.data_status !== "READY") return "정보 없음";
    if (market.percentile_1m != null && Number.isFinite(Number(market.percentile_1m))) {
      return `최근 1개월 ${topPercentLabel(market.percentile_1m)}`;
    }
    if (market.percentile_3m == null || !Number.isFinite(Number(market.percentile_3m))) return "정보 있음";
    return `최근 3개월 ${topPercentLabel(market.percentile_3m)}`;
  }

  function marketStrengthDetail(market) {
    if (!market || market.applicability === "NOT_APPLICABLE") return "마켓 RS 적용 대상이 아닙니다.";
    if (market.data_status !== "READY") return "마켓 RS 정보가 없습니다.";
    const benchmark = market.benchmark_name || "시장";
    const asOf = formatDate(market.benchmark_last_observation_date);
    return `${benchmark} 기준 · 최근 관측일 ${asOf}`;
  }

  function fundamentalLabel(report) {
    return label(FUNDAMENTAL_LABELS, report && report.fundamentals && report.fundamentals.status, "준비 중");
  }

  function fundamentalDetail(report) {
    const fundamentals = report && report.fundamentals;
    if (!fundamentals) return "정보 없음";
    if (fundamentals.status === "NOT_APPLICABLE") return "이 종목에는 적용되지 않습니다.";
    if (fundamentals.status === "DATA_UNAVAILABLE") return fundamentals.reason || "필요한 재무 데이터가 없습니다.";
    return `${fundamentals.company_family || "회사"} · 기준일 ${formatDate(fundamentals.requested_as_of)}`;
  }

  function validateIndex(value) {
    return Boolean(value && typeof value === "object" && Array.isArray(value.items) && Number.isInteger(value.count));
  }

  function validateReport(value, ticker) {
    return Boolean(
      value && typeof value === "object" && value.identity && value.identity.ticker === ticker &&
      value.decision && value.summary && value.price_trend && value.pattern && value.market_strength &&
      value.flow && value.fundamentals && typeof value.fundamentals.status === "string" &&
      Array.isArray(value.fundamentals.quarterly) && Array.isArray(value.fundamentals.annual) &&
      value.fundamentals.summary && value.strategy && value.technical_details
    );
  }

  function currentTicker() {
    return new URL(window.location.href).searchParams.get("ticker");
  }

  function dartSearchUrl(ticker) {
    return `${DART_SEARCH_URL}?textCrpNM=${encodeURIComponent(ticker)}`;
  }

  function updateUrl(ticker) {
    const url = new URL(window.location.href);
    if (ticker) url.searchParams.set("ticker", ticker);
    else url.searchParams.delete("ticker");
    window.history.pushState({}, "", url);
  }

  function createResultItem(item) {
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
    return li;
  }

  function randomSample(items, count) {
    const pool = items.slice();
    for (let index = pool.length - 1; index > 0; index -= 1) {
      const swapIndex = Math.floor(Math.random() * (index + 1));
      [pool[index], pool[swapIndex]] = [pool[swapIndex], pool[index]];
    }
    return pool.slice(0, count);
  }

  function renderRecommendations() {
    const recommendations = byId("recommendations");
    if (!recommendations || !indexData) return;
    while (recommendations.firstChild) recommendations.removeChild(recommendations.firstChild);
    const available = indexData.items.filter((item) => item.report_available === true);
    randomSample(available, 5).forEach((item) => recommendations.appendChild(createResultItem(item)));
  }

  function renderSearchResults(query) {
    const results = byId("search-results");
    if (!results || !indexData) return;
    while (results.firstChild) results.removeChild(results.firstChild);
    const normalized = String(query || "").trim().toLocaleLowerCase("ko-KR");
    setHidden("recommendations-panel", Boolean(normalized));
    setHidden("search-no-results", true);
    if (!normalized) {
      results.hidden = true;
      searchMatches = [];
      return;
    }
    searchMatches = indexData.items.filter((item) => (
      String(item.ticker).toLocaleLowerCase("ko-KR").includes(normalized) ||
      String(item.name).toLocaleLowerCase("ko-KR").includes(normalized)
    )).slice(0, 12);
    searchMatches.forEach((item) => results.appendChild(createResultItem(item)));
    results.hidden = searchMatches.length === 0;
    setHidden("search-no-results", searchMatches.length !== 0);
  }

  function showEmpty() {
    resetDetailPanel();
    setHidden("report-empty", false);
    setHidden("report-pending", true);
    setHidden("report-view", true);
    setHidden("report-error", true);
  }

  function showPending(item) {
    resetDetailPanel();
    setHidden("report-empty", true);
    setHidden("report-pending", false);
    setHidden("report-view", true);
    setHidden("report-error", true);
    setText("pending-heading", item.name);
    setText("pending-identity", `${item.ticker} · ${marketLabel(item.market)}`);
    const requestButton = byId("report-request-button");
    if (requestButton) {
      requestButton.hidden = false;
      requestButton.dataset.ticker = item.ticker;
      requestButton.dataset.name = item.name;
      requestButton.dataset.market = item.market || "";
    }
    setHidden("report-request-status", true);
  }

  function reportRequest(ticker, name, market) {
    const request = {
      ticker: ticker || "",
      name: name || "",
      market: market || "",
      page: window.location.href,
    };
    window.dispatchEvent(new CustomEvent("krx:report-request", { detail: request }));
    return { status: "NOT_CONNECTED", request };
  }

  function showError(message) {
    resetDetailPanel();
    setHidden("report-empty", true);
    setHidden("report-pending", true);
    setHidden("report-view", true);
    setHidden("report-error", false);
    setText("report-error-detail", message || "데이터 파일을 확인해 주세요.");
  }

  function buildSummary(report) {
    const trend = `추세는 ${stageLabel(report.summary.trend_stage)} 상태입니다.`;
    const market = `마켓 RS는 ${marketStrengthLabel(report.market_strength)}입니다.`;
    const flow = `수급은 ${flowLabel(report.summary.flow_state)}입니다.`;
    return `${trend} ${market} ${flow}`;
  }

  function renderPatternStepper(currentStage) {
    const stepper = byId("pattern-stepper");
    if (!stepper) return;
    while (stepper.firstChild) stepper.removeChild(stepper.firstChild);
    PATTERN_STEPS.forEach(([code, text], index) => {
      const step = document.createElement("span");
      step.className = "pattern-step";
      step.setAttribute("role", "listitem");
      step.textContent = text;
      if (code === currentStage) {
        step.classList.add("is-current");
        step.setAttribute("aria-current", "step");
      }
      stepper.appendChild(step);
      if (index < PATTERN_STEPS.length - 1) {
        const arrow = document.createElement("span");
        arrow.className = "pattern-arrow";
        arrow.setAttribute("aria-hidden", "true");
        arrow.textContent = "→";
        stepper.appendChild(arrow);
      }
    });
  }

  function appendTableCell(row, value, className) {
    const cell = document.createElement("td");
    cell.textContent = value == null || value === "" ? "—" : String(value);
    if (className) cell.className = className;
    row.appendChild(cell);
  }

  function createDetailTable(headers, rows, className) {
    const wrapper = document.createElement("div");
    wrapper.className = "detail-table-wrap";
    const table = document.createElement("table");
    table.className = `detail-table${className ? ` ${className}` : ""}`;
    const thead = document.createElement("thead");
    const headerRow = document.createElement("tr");
    headers.forEach((header) => {
      const cell = document.createElement("th");
      cell.scope = "col";
      cell.textContent = header;
      headerRow.appendChild(cell);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    rows.forEach((values) => {
      const row = document.createElement("tr");
      values.forEach((value) => {
        if (value && typeof value === "object" && !Array.isArray(value)) {
          appendTableCell(row, value.value, value.className);
        } else {
          appendTableCell(row, value);
        }
      });
      tbody.appendChild(row);
    });
    table.appendChild(tbody);
    wrapper.appendChild(table);
    return wrapper;
  }

  function appendDetailNote(container, text, className) {
    const note = document.createElement("p");
    note.className = className || "detail-note";
    note.textContent = text;
    container.appendChild(note);
  }

  function appendDetailEmpty(container, text) {
    const empty = document.createElement("p");
    empty.className = "detail-empty";
    empty.textContent = text || "표시할 상세 데이터가 없습니다.";
    container.appendChild(empty);
  }

  function formatFundamentalKrw(value) {
    if (value == null || value === "" || !Number.isFinite(Number(value))) return "—";
    const number = Number(value) / 1e8;
    const sign = number > 0 ? "+" : number < 0 ? "−" : "";
    return `${sign}${formatNumber(Math.abs(number), 1)}억원`;
  }

  function formatFundamentalPercent(value) {
    if (value == null || value === "" || !Number.isFinite(Number(value))) return "—";
    return `${formatNumber(value, 2)}%`;
  }

  function appendFundamentalMetric(container, labelText, value) {
    const item = document.createElement("div");
    item.className = "fundamental-metric";
    const label = document.createElement("dt");
    label.textContent = labelText;
    const valueElement = document.createElement("dd");
    valueElement.textContent = value == null || value === "" ? "—" : String(value);
    item.append(label, valueElement);
    container.appendChild(item);
  }

  function fundamentalRowStatus(value) {
    return label(FUNDAMENTAL_ROW_LABELS, value, "확인 필요");
  }

  function renderFundamentalsDetail(report) {
    const panel = byId("fundamentals-detail-panel");
    const statusElement = byId("fundamentals-detail-status");
    const reasonElement = byId("fundamentals-detail-reason");
    const summaryElement = byId("fundamentals-summary");
    const periodsElement = byId("fundamentals-periods");
    const fundamentals = report && report.fundamentals;
    if (!panel || !fundamentals || !summaryElement || !periodsElement) return;
    while (summaryElement.firstChild) summaryElement.removeChild(summaryElement.firstChild);
    while (periodsElement.firstChild) periodsElement.removeChild(periodsElement.firstChild);
    if (statusElement) {
      statusElement.textContent = fundamentalLabel(report);
      const visualStatus = fundamentals.status === "READY" ? "NORMAL"
        : fundamentals.status === "PARTIAL" ? "UPDATING"
          : fundamentals.status === "DATA_UNAVAILABLE" ? "CHECK_REQUIRED" : "UNKNOWN";
      statusElement.setAttribute("data-status", visualStatus);
    }
    if (reasonElement) reasonElement.textContent = fundamentalDetail(report);
    const summary = fundamentals.summary || {};
    [
      ["최근 사업연도", summary.latest_fy],
      ["최근 분기", summary.latest_quarter],
      ["최근 사업연도 매출", formatFundamentalKrw(summary.latest_fy_revenue_krw)],
      ["최근 4분기 평균 매출", formatFundamentalKrw(summary.latest_4q_avg_revenue_krw)],
      ["TTM 매출", formatFundamentalKrw(summary.ttm_revenue_krw)],
      ["TTM 영업이익", formatFundamentalKrw(summary.ttm_operating_income_krw)],
      ["TTM 순이익", formatFundamentalKrw(summary.ttm_net_income_krw)],
      ["TTM 영업현금흐름", formatFundamentalKrw(summary.ttm_operating_cash_flow_krw)],
      ["TTM 영업이익률", formatFundamentalPercent(summary.ttm_operating_margin_pct)],
      ["TTM 순이익률", formatFundamentalPercent(summary.ttm_net_margin_pct)],
      ["TTM 영업현금흐름률", formatFundamentalPercent(summary.ttm_operating_cash_flow_margin_pct)],
      ["TTM ROE", formatFundamentalPercent(summary.ttm_roe_pct)],
      ["최근 부채비율", formatFundamentalPercent(summary.latest_debt_ratio_pct)],
      ["필터 상태", summary.filter_status],
    ].forEach(([labelText, value]) => appendFundamentalMetric(summaryElement, labelText, value));

    const appendPeriodTable = (titleText, headers, rows) => {
      const heading = document.createElement("h4");
      heading.className = "fundamentals-period-heading";
      heading.textContent = titleText;
      periodsElement.appendChild(heading);
      if (!rows.length) {
        appendDetailEmpty(periodsElement, "표시할 기간 데이터가 없습니다.");
        return;
      }
      periodsElement.appendChild(createDetailTable(headers, rows));
    };
    const quarterly = Array.isArray(fundamentals.quarterly) ? fundamentals.quarterly : [];
    appendPeriodTable("최근 12개 분기", ["분기", "상태", "매출", "매출 YoY", "영업이익", "영업이익률", "순이익", "순이익률", "영업현금흐름"], quarterly.map((row) => [
      row.quarter,
      fundamentalRowStatus(row.status),
      formatFundamentalKrw(row.revenue_krw),
      formatFundamentalPercent(row.revenue_yoy_pct),
      formatFundamentalKrw(row.operating_income_krw),
      formatFundamentalPercent(row.operating_margin_pct),
      formatFundamentalKrw(row.net_income_krw),
      formatFundamentalPercent(row.net_margin_pct),
      formatFundamentalKrw(row.operating_cash_flow_krw),
    ]));
    const annual = Array.isArray(fundamentals.annual) ? fundamentals.annual : [];
    appendPeriodTable("최근 5개년", ["사업연도", "상태", "매출", "매출 YoY", "영업이익", "영업이익률", "순이익", "순이익률", "ROE", "부채비율"], annual.map((row) => [
      row.fiscal_year,
      fundamentalRowStatus(row.status),
      formatFundamentalKrw(row.revenue_krw),
      formatFundamentalPercent(row.revenue_yoy_pct),
      formatFundamentalKrw(row.operating_income_krw),
      formatFundamentalPercent(row.operating_margin_pct),
      formatFundamentalKrw(row.net_income_krw),
      formatFundamentalPercent(row.net_margin_pct),
      formatFundamentalPercent(row.roe_pct),
      formatFundamentalPercent(row.debt_ratio_pct),
    ]));
    panel.hidden = false;
  }

  function renderPatternDetail(report, container) {
    const history = Array.isArray(report.pattern.history_12m) ? report.pattern.history_12m : [];
    if (!history.length) {
      appendDetailEmpty(container, "최근 12개월 패턴 이력이 없습니다.");
      return;
    }
    const chart = document.createElement("div");
    chart.className = "pattern-score-chart-wrap";
    renderPatternScoreChart(history, chart);
    container.appendChild(chart);
    const rows = history.map((observation) => [
      formatDate(observation.as_of),
      observation.data_available === false ? "정보 없음" : formatPrice(observation.close),
      observation.score == null ? "—" : `${formatNumber(observation.score, 2)}점`,
      stageLabel(observation.stage),
    ]);
    container.appendChild(createDetailTable(["기준일", "종가", "패턴 점수", "단계"], rows));
  }

  function renderPatternScoreChart(history, container) {
    const SVG_NS = "http://www.w3.org/2000/svg";
    const width = 720;
    const height = 250;
    const padding = { top: 16, right: 18, bottom: 38, left: 42 };
    const chartWidth = width - padding.left - padding.right;
    const chartHeight = height - padding.top - padding.bottom;
    const points = history
      .filter((observation) => observation && observation.score != null && Number.isFinite(Number(observation.score)))
      .map((observation) => ({ asOf: observation.as_of, score: Number(observation.score) }));
    const x = (index) => padding.left + (points.length <= 1 ? chartWidth / 2 : (index / (points.length - 1)) * chartWidth);
    const y = (score) => padding.top + ((100 - Math.max(0, Math.min(100, score))) / 100) * chartHeight;
    const createSvgElement = (tag, attributes) => {
      const element = document.createElementNS(SVG_NS, tag);
      Object.entries(attributes || {}).forEach(([name, value]) => element.setAttribute(name, String(value)));
      return element;
    };
    const svg = createSvgElement("svg", {
      id: "pattern-score-chart",
      class: "pattern-score-chart",
      viewBox: `0 0 ${width} ${height}`,
      role: "img",
      "aria-label": "최근 패턴 점수 추이",
    });
    [0, 50, 100].forEach((score) => {
      const scoreY = y(score);
      svg.appendChild(createSvgElement("line", {
        class: "pattern-chart-grid",
        x1: padding.left,
        x2: width - padding.right,
        y1: scoreY,
        y2: scoreY,
      }));
      const label = createSvgElement("text", {
        class: "pattern-chart-axis-label",
        x: padding.left - 8,
        y: scoreY + 4,
        "text-anchor": "end",
      });
      label.textContent = `${score}`;
      svg.appendChild(label);
    });
    if (points.length) {
      const line = points.map((point, index) => `${index === 0 ? "M" : "L"}${x(index)} ${y(point.score)}`).join(" ");
      svg.appendChild(createSvgElement("path", { class: "pattern-chart-line", d: line }));
      points.forEach((point, index) => {
        const circle = createSvgElement("circle", {
          class: "pattern-chart-point",
          cx: x(index),
          cy: y(point.score),
          r: 4,
          tabindex: 0,
          "aria-label": `${formatDate(point.asOf)} 패턴 점수 ${formatNumber(point.score, 2)}점`,
        });
        const title = createSvgElement("title");
        title.textContent = `${formatDate(point.asOf)} · ${formatNumber(point.score, 2)}점`;
        circle.appendChild(title);
        svg.appendChild(circle);
      });
      points.forEach((point, index) => {
        const date = createSvgElement("text", {
          class: "pattern-chart-date",
          x: x(index),
          y: height - 12,
          "text-anchor": "middle",
        });
        date.textContent = String(point.asOf || "").slice(2, 7).replace("-", ".");
        svg.appendChild(date);
      });
    }
    container.appendChild(svg);
  }

  function renderMarketDetail(report, container) {
    const market = report.market_strength;
    if (!market || market.applicability === "NOT_APPLICABLE") {
      appendDetailEmpty(container, "이 종목에는 마켓 RS 정보가 적용되지 않습니다.");
      return;
    }
    if (market.data_status !== "READY") {
      appendDetailEmpty(container, "마켓 RS 정보가 없습니다.");
      return;
    }
    const rows = [
      ["최근 2주", { value: formatSignedRate(market.market_rs_2w), className: signedValueClass(market.market_rs_2w) }, topPercentLabel(market.percentile_2w)],
      ["최근 1개월", { value: formatSignedRate(market.market_rs_1m), className: signedValueClass(market.market_rs_1m) }, topPercentLabel(market.percentile_1m)],
      ["최근 3개월", { value: formatSignedRate(market.market_rs_3m), className: signedValueClass(market.market_rs_3m) }, topPercentLabel(market.percentile_3m)],
      ["최근 6개월", { value: formatSignedRate(market.market_rs_6m), className: signedValueClass(market.market_rs_6m) }, topPercentLabel(market.percentile_6m)],
      ["최근 12개월", { value: formatSignedRate(market.market_rs_12m), className: signedValueClass(market.market_rs_12m) }, topPercentLabel(market.percentile_12m)],
    ];
    container.appendChild(createDetailTable(["구간", "마켓 대비 수익률", "마켓 내 위치"], rows));
    appendDetailNote(container, `${market.benchmark_name || "시장"} 기준 · 최근 관측일 ${formatDate(market.benchmark_last_observation_date)}`);
    if (market.explanation) appendDetailNote(container, market.explanation);
  }

  function renderPriceDetail(report, container) {
    const price = report.price_trend;
    if (!price) {
      appendDetailEmpty(container, "가격·거래대금 정보가 없습니다.");
      return;
    }
    const valueLabel = (value) => value == null || !Number.isFinite(Number(value))
      ? "—"
      : `${formatNumber(value, 2)}억원`;
    const rows = [
      ["1일", valueLabel(price.avg_trading_value_1d_eok)],
      ["5일", valueLabel(price.avg_trading_value_5d_eok)],
      ["10일", valueLabel(price.avg_trading_value_10d_eok)],
      ["20일", valueLabel(price.avg_trading_value_20d_eok)],
      ["60일", valueLabel(price.avg_trading_value_60d_eok)],
    ];
    container.appendChild(createDetailTable(["기간", "평균 거래대금"], rows));
    appendDetailNote(container, `거래대금 상태: ${tradingValueLabel(price.trading_value_state)}`);
    if (price.trading_value_explanation) appendDetailNote(container, price.trading_value_explanation);
  }

  function signedValueClass(value) {
    if (value == null || !Number.isFinite(Number(value)) || Number(value) === 0) return "";
    return Number(value) > 0 ? "detail-value-positive" : "detail-value-negative";
  }

  function renderFlowDetail(report, container) {
    const flow = report.flow;
    if (!flow || flow.data_status !== "READY") {
      appendDetailEmpty(container, "최근 외국인 수급 정보가 없습니다.");
      return;
    }
    const rows = [
      ["1일", { value: formatKrwCompact(flow.net_buy_value_1d_krw), className: signedValueClass(flow.net_buy_value_1d_krw) }, { value: formatSignedRate(flow.intensity_1d), className: signedValueClass(flow.intensity_1d) }, flow.positive_days_1d == null ? "—" : `${formatNumber(flow.positive_days_1d)}일`],
      ["5일", { value: formatKrwCompact(flow.net_buy_value_5d_krw), className: signedValueClass(flow.net_buy_value_5d_krw) }, { value: formatSignedRate(flow.intensity_5d), className: signedValueClass(flow.intensity_5d) }, flow.positive_days_5d == null ? "—" : `${formatNumber(flow.positive_days_5d)}일`],
      ["10일", { value: formatKrwCompact(flow.net_buy_value_10d_krw), className: signedValueClass(flow.net_buy_value_10d_krw) }, { value: formatSignedRate(flow.intensity_10d), className: signedValueClass(flow.intensity_10d) }, flow.positive_days_10d == null ? "—" : `${formatNumber(flow.positive_days_10d)}일`],
      ["20일", { value: formatKrwCompact(flow.net_buy_value_20d_krw), className: signedValueClass(flow.net_buy_value_20d_krw) }, { value: formatSignedRate(flow.intensity_20d), className: signedValueClass(flow.intensity_20d) }, flow.positive_days_20d == null ? "—" : `${formatNumber(flow.positive_days_20d)}일`],
      ["60일", { value: formatKrwCompact(flow.net_buy_value_60d_krw), className: signedValueClass(flow.net_buy_value_60d_krw) }, { value: formatSignedRate(flow.intensity_60d), className: signedValueClass(flow.intensity_60d) }, flow.positive_days_60d == null ? "—" : `${formatNumber(flow.positive_days_60d)}일`],
    ];
    container.appendChild(createDetailTable(["기간", "외국인 누적 순매수", "순매수 강도", "양수 일수"], rows));
    if (flow.explanation) appendDetailNote(container, flow.explanation);
  }

  function renderStrategyDetail(report, container) {
    const history = Array.isArray(report.strategy.history) ? report.strategy.history : [];
    if (!history.length) {
      appendDetailEmpty(container, "표시할 전략 이력이 없습니다.");
      return;
    }
    const rows = history.map((trade) => [
      trade.trade_sequence == null ? "—" : `${formatNumber(trade.trade_sequence)}회`,
      formatDate(trade.entry_execution_date || trade.entry_signal_date),
      formatPrice(trade.entry_open),
      formatDate(trade.exit_execution_date),
      formatPrice(trade.exit_price),
      { value: formatSignedPercentPoints(trade.return_pct), className: signedValueClass(trade.return_pct) },
      tradeStatusLabel(trade.trade_status),
      exitTypeLabel(trade.exit_type),
    ]);
    container.appendChild(createDetailTable(["회차", "진입일", "진입가", "청산일", "청산가", "수익률", "상태", "종료 사유"], rows, "strategy-history-table"));
    appendDetailNote(container, "과거 전략 이력은 과거 데이터에 전략 규칙을 적용한 결과이며 미래 수익을 의미하지 않습니다.", "strategy-disclaimer");
  }

  function isMobileLayout() {
    return Boolean(window.matchMedia && window.matchMedia(REPORT_MOBILE_QUERY).matches);
  }

  function positionDetailPanel(key) {
    const panel = byId("report-detail-panel");
    if (panel && isMobileLayout()) {
      const selectedCard = byId(DETAIL_BUTTON_IDS[key]);
      if (selectedCard) selectedCard.insertAdjacentElement("afterend", panel);
      return;
    }
    const slot = byId(key === "price" || key === "pattern" || key === "market" ? "top-detail-slot" : "bottom-detail-slot");
    if (panel && slot) slot.appendChild(panel);
  }

  function repositionActiveDetail() {
    if (activeDetailKey) positionDetailPanel(activeDetailKey);
  }

  function renderDetail(key, report) {
    const panel = byId("report-detail-panel");
    const title = byId("report-detail-title");
    const content = byId("report-detail-content");
    if (!panel || !title || !content) return;
    while (content.firstChild) content.removeChild(content.firstChild);
    positionDetailPanel(key);
    title.textContent = `${DETAIL_BUTTON_LABELS[key]} 상세`;
    if (key === "price") renderPriceDetail(report, content);
    else if (key === "pattern") renderPatternDetail(report, content);
    else if (key === "market") renderMarketDetail(report, content);
    else if (key === "flow") renderFlowDetail(report, content);
    else if (key === "strategy") renderStrategyDetail(report, content);
    panel.hidden = false;
  }

  function setDetailButtonStates() {
    Object.entries(DETAIL_BUTTON_IDS).forEach(([key, id]) => {
      const button = byId(id);
      if (!button) return;
      const selected = key === activeDetailKey;
      button.classList.toggle("is-selected", selected);
      button.setAttribute("aria-expanded", String(selected));
      button.setAttribute("aria-label", `${DETAIL_BUTTON_LABELS[key]} 상세 정보 ${selected ? "닫기" : "열기"}`);
      const affordance = button.querySelector(".report-card-affordance");
      if (affordance) affordance.textContent = selected ? "상세 닫기 ×" : "상세 보기 ›";
    });
  }

  function closeDetail() {
    activeDetailKey = null;
    setHidden("report-detail-panel", true);
    setDetailButtonStates();
  }

  function resetDetailPanel() {
    currentReport = null;
    closeDetail();
    setHidden("fundamentals-detail-panel", true);
  }

  function toggleDetail(key) {
    if (!currentReport) return;
    if (activeDetailKey === key) {
      closeDetail();
      return;
    }
    activeDetailKey = key;
    setDetailButtonStates();
    renderDetail(key, currentReport);
  }

  function initDetailInteractions() {
    Object.entries(DETAIL_BUTTON_IDS).forEach(([key, id]) => {
      const button = byId(id);
      if (button) button.addEventListener("click", () => toggleDetail(key));
    });
    const close = byId("report-detail-close");
    if (close) close.addEventListener("click", closeDetail);
    window.addEventListener("resize", repositionActiveDetail);
    const requestButton = byId("report-request-button");
    if (requestButton) {
      requestButton.addEventListener("click", () => {
        const result = reportRequest(requestButton.dataset.ticker, requestButton.dataset.name, requestButton.dataset.market);
        if (result.status === "NOT_CONNECTED") {
          setText("report-request-status", "리포트 요청 연결은 아직 준비되지 않았습니다.");
          setHidden("report-request-status", false);
        }
      });
    }
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
    appendDetail(list, "마켓 RS 적용", details.market_strength_applicability);
    appendDetail(list, "마켓 RS 상태", details.market_strength_status);
    appendDetail(list, "거래대금 상태", details.trading_value_state);
    appendDetail(list, "가격 기준일", details.price_as_of);
    appendDetail(list, "가격 출처", details.price_source);
    appendDetail(list, "원본 리포트", details.source_report);
  }

  function renderReport(report) {
    closeDetail();
    currentReport = report;
    const identity = report.identity;
    const market = marketLabel(identity.market);
    setHidden("report-empty", true);
    setHidden("report-pending", true);
    setHidden("report-error", true);
    setHidden("report-view", false);
    setText("report-name", identity.name);
    const sector = report.technical_details && report.technical_details.sector_name;
    const identityParts = [identity.ticker, market, assetLabel(identity.asset_type)];
    if (sector && sector !== "UNKNOWN" && sector !== "None") identityParts.push(sector);
    setText("report-identity", identityParts.join(" · "));
    setText("decision-heading", actionLabel(report.decision.action));
    setText("decision-summary", buildSummary(report));
    setText("signal-trend", stageLabel(report.summary.trend_stage));
    setText("signal-market", marketStrengthLabel(report.market_strength));
    setText("signal-flow", flowLabel(report.summary.flow_state));
    setText("signal-fundamentals", fundamentalLabel(report));
    setText("price-value", formatPrice(report.price_trend.latest_close));
    setText("price-detail", report.price_trend.latest_close == null
      ? "가격 정보 없음"
      : `기준일 ${formatDate(report.price_trend.latest_close_as_of)} · 거래대금 ${tradingValueLabel(report.price_trend.trading_value_state)}`);
    renderPatternStepper(report.pattern.official_stage);
    setText("pattern-value", `현재 단계 ${stageLabel(report.pattern.official_stage)}`);
    setText("pattern-detail", report.pattern.score == null ? "패턴 점수 확인 필요" : `패턴 점수 ${formatNumber(report.pattern.score, 2)}점`);
    setText("market-value", marketStrengthLabel(report.market_strength));
    setText("market-detail", marketStrengthDetail(report.market_strength));
    setText("flow-value", flowLabel(report.flow.state));
    setText("flow-detail", flowDetail(report.flow.state));
    setText("fundamentals-value", fundamentalLabel(report));
    setText("fundamentals-detail", fundamentalDetail(report));
    renderFundamentalsDetail(report);
    setText("strategy-value", actionLabel(report.strategy.action));
    setText("strategy-detail", strategyDetail(report.strategy.state));
    renderTechnicalDetails(report);
    const naver = byId("naver-link");
    const naverChart = byId("naver-chart-link");
    const dart = byId("dart-link");
    if (naver && report.external_links && typeof report.external_links.naver_finance === "string") {
      naver.href = report.external_links.naver_finance;
    }
    if (naverChart) {
      const tossChart = report.external_links && report.external_links.toss_chart;
      const validTossChart = typeof tossChart === "string" && /^https:\/\/www\.tossinvest\.com\/stocks\/A[0-9A-Z]+\/order$/.test(tossChart);
      naverChart.hidden = !validTossChart;
      if (validTossChart) naverChart.href = tossChart;
      else naverChart.removeAttribute("href");
    }
    if (dart) {
      const ticker = report.identity && typeof report.identity.ticker === "string" ? report.identity.ticker.trim() : "";
      dart.hidden = !ticker;
      if (ticker) dart.href = dartSearchUrl(ticker);
      else dart.removeAttribute("href");
    }
  }

  async function loadSelected(item) {
    if (!item.report_available) {
      showPending(item);
      return;
    }
    closeDetail();
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
    resetDetailPanel();
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
    renderRecommendations();
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
  initDetailInteractions();
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
