(function () {
  "use strict";

  const MONITOR_URL = "./data/strategy-monitor.json";
  const THEME_STORAGE_KEY = "krx-theme";
  const THEME_VALUES = new Set(["light", "dark"]);
  const SYSTEM_THEME_QUERY = "(prefers-color-scheme: dark)";
  const MARKET_LABELS = { KOSPI: "코스피", KOSDAQ: "코스닥", KONEX: "코넥스" };
  const ASSET_LABELS = { COMMON: "보통주", ETF: "ETF" };
  const ACTION_LABELS = {
    ENTRY: "진입 조건 충족",
    ENTER_NEXT_OPEN: "진입 조건 충족",
    HOLD: "보유 유지",
    EXIT: "매도 조건 충족",
    WATCH: "관찰 중",
    WAIT: "관찰 중",
    NONE: "전략 데이터 없음",
  };
  const POSITION_LABELS = { OPEN: "보유 중", FLAT: "미보유", NOT_APPLICABLE: "해당 없음" };
  const STATE_LABELS = {
    HOLD_PROGRESSED: "상승 진행 구간 보유",
    HOLD_PRE_PROGRESSED: "초기 추세 구간 보유",
    WAIT: "진입 전 관찰",
    ENTRY: "진입 조건 충족",
    NOT_APPLICABLE: "해당 없음",
  };
  const STAGE_LABELS = {
    WEAK: "약세",
    BASE: "기반 형성",
    TRANSITION: "전환",
    EARLY_TREND: "상승 초기",
    PROGRESSED: "상승 진행",
    UNAVAILABLE: "확인 필요",
  };
  const SECTION_LABELS = {
    hold: "보유 종목",
    entry: "진입 조건을 충족한 종목",
    exit: "매도 조건을 충족한 종목",
    watch: "관찰 종목",
    unavailable: "기타",
  };
  const SECTION_IDS = { hold: "hold", entry: "entry", exit: "exit", watch: "watch", unavailable: "unavailable" };
  const FILTERS = new Set(["all", ...Object.keys(SECTION_IDS).filter((key) => key !== "unavailable")]);

  const byId = (id) => document.getElementById(id);
  let monitor = null;
  let activeFilter = "all";
  let searchQuery = "";

  function setText(id, value) {
    const element = byId(id);
    if (element) element.textContent = value == null || value === "" ? "—" : String(value);
  }

  function marketLabel(value) { return MARKET_LABELS[value] || "마켓 확인 필요"; }
  function assetLabel(value) { return ASSET_LABELS[value] || "자산 확인 필요"; }
  function actionLabel(value, dataStatus) {
    if (dataStatus === "NOT_APPLICABLE") return "해당 없음";
    if (dataStatus === "CHECK_REQUIRED") return "확인 필요";
    return ACTION_LABELS[value] || "전략 데이터 없음";
  }
  function positionLabel(value) { return POSITION_LABELS[value] || "상태 확인 필요"; }
  function stateLabel(value) { return STATE_LABELS[value] || "상태 확인 필요"; }
  function stageLabel(value) { return STAGE_LABELS[value] || "확인 필요"; }

  function formatNumber(value, maximumFractionDigits) {
    if (value == null || value === "" || !Number.isFinite(Number(value))) return "—";
    return new Intl.NumberFormat("ko-KR", { maximumFractionDigits: maximumFractionDigits == null ? 0 : maximumFractionDigits }).format(Number(value));
  }

  function formatPrice(value) {
    return value == null || value === "" || !Number.isFinite(Number(value)) ? "—" : `${formatNumber(value)}원`;
  }

  function formatDate(value) {
    if (!value) return "—";
    const parts = String(value).slice(0, 10).split("-");
    return parts.length === 3 ? `${parts[0]}.${parts[1]}.${parts[2]}` : String(value);
  }

  function formatReturn(value) {
    if (value == null || value === "" || !Number.isFinite(Number(value))) return "—";
    const number = Number(value);
    const sign = number > 0 ? "+" : number < 0 ? "−" : "";
    return `${sign}${formatNumber(Math.abs(number), 2)}%`;
  }

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

  function createElement(tagName, className, text) {
    const element = document.createElement(tagName);
    if (className) element.className = className;
    if (text != null) element.textContent = text;
    return element;
  }

  function itemMatches(item) {
    const normalized = searchQuery.trim().toLocaleLowerCase("ko-KR");
    if (!normalized) return true;
    return [item.ticker, item.name, item.sector_name].some((value) => String(value || "").toLocaleLowerCase("ko-KR").includes(normalized));
  }

  function createField(label, value, className) {
    const field = createElement("span", `strategy-item-field${className ? ` ${className}` : ""}`);
    field.appendChild(createElement("small", "strategy-item-label", label));
    field.appendChild(createElement("strong", "strategy-item-value", value));
    return field;
  }

  function createPriceDateField(label, price, date, className) {
    const field = createElement("span", `strategy-item-field${className ? ` ${className}` : ""}`);
    field.appendChild(createElement("small", "strategy-item-label", label));
    const value = createElement("strong", "strategy-item-value strategy-item-price-date");
    value.appendChild(createElement("span", "strategy-item-price", price));
    if (date !== "—") value.appendChild(createElement("small", "strategy-item-date", date));
    field.appendChild(value);
    return field;
  }

  function createPositionField(item) {
    if (item.data_status === "NOT_APPLICABLE" || item.canonical_position === "NOT_APPLICABLE") {
      return createField("현재 상태", "해당 없음", "strategy-item-position");
    }
    if (item.data_status === "CHECK_REQUIRED") {
      return createField("현재 상태", "확인 필요", "strategy-item-position");
    }
    const field = createElement("span", "strategy-item-field strategy-item-position");
    field.appendChild(createElement("small", "strategy-item-label", "현재 상태"));
    const value = createElement("span", "strategy-item-value strategy-item-position-value");
    value.appendChild(createElement("strong", "strategy-item-position-main", positionLabel(item.canonical_position)));
    value.appendChild(createElement("span", "strategy-item-position-sub", stateLabel(item.strategy_state)));
    field.appendChild(value);
    return field;
  }

  function createStrategyItem(item) {
    const link = createElement("a", "strategy-item");
    link.href = `./report.html?ticker=${encodeURIComponent(item.ticker)}`;
    link.setAttribute("aria-label", `${item.name} ${item.ticker} 리포트 보기`);

    const identity = createElement("span", "strategy-item-identity");
    identity.appendChild(createElement("strong", "strategy-item-name", item.name || item.ticker));
    const sector = item.sector_name ? ` · ${item.sector_name}` : "";
    identity.appendChild(createElement("span", "strategy-item-meta", `${item.ticker} · ${marketLabel(item.market)} · ${assetLabel(item.asset_type)}${sector}`));

    const action = createField("전략 판단", actionLabel(item.action, item.data_status), `strategy-item-action action-${item.bucket}`);
    const position = createPositionField(item);
    const pattern = item.canonical_position === "NOT_APPLICABLE"
      ? createField("패턴", "해당 없음")
      : createField("패턴", `${stageLabel(item.pattern_stage)} · ${formatNumber(item.pattern_score, 2)}점`);
    const price = createPriceDateField("현재가", formatPrice(item.latest_close), formatDate(item.latest_close_as_of));
    const trade = item.current_trade;
    const entry = trade
      ? createPriceDateField("진입가", formatPrice(trade.entry_open), formatDate(trade.entry_execution_date))
      : createField("진입가", "—");
    const returnClass = trade && Number(trade.return_pct) > 0 ? "detail-value-positive" : trade && Number(trade.return_pct) < 0 ? "detail-value-negative" : "";
    const returnField = createField("수익률", trade ? formatReturn(trade.return_pct) : "—", returnClass);
    const arrow = createElement("span", "strategy-item-link", "리포트 보기 ›");

    link.append(identity, action, position, pattern, price, entry, returnField, arrow);
    return link;
  }

  function filteredItems(category) {
    return (monitor.items || []).filter((item) => item.bucket === category && itemMatches(item));
  }

  function renderSections() {
    if (!monitor) return;
    let visibleCount = 0;
    Object.keys(SECTION_IDS).forEach((category) => {
      const section = byId(`${category}-section`);
      const list = byId(`${category}-list`);
      if (!section || !list) return;
      const enabled = activeFilter === "all" || activeFilter === category;
      section.hidden = !enabled;
      while (list.firstChild) list.removeChild(list.firstChild);
      if (!enabled) return;
      const items = filteredItems(category);
      visibleCount += items.length;
      setText(`${category}-count`, items.length);
      if (!items.length) {
        const message = searchQuery.trim()
          ? "검색 조건에 맞는 종목이 없습니다."
          : category === "entry"
            ? "현재 진입 조건을 충족한 종목이 없습니다."
            : category === "exit"
              ? "현재 매도 조건을 충족한 종목이 없습니다."
              : category === "hold"
                ? "현재 보유 중인 종목이 없습니다."
                : category === "watch"
                  ? "현재 관찰 중인 종목이 없습니다."
                  : "표시할 전략 데이터가 없습니다.";
        list.appendChild(createElement("p", "strategy-empty", message));
      } else {
        items.forEach((item) => list.appendChild(createStrategyItem(item)));
      }
    });
    const suffix = searchQuery.trim() ? ` · 검색 결과 ${visibleCount}종목` : ` · ${visibleCount}종목 표시`;
    setText("strategy-results-meta", `${SECTION_LABELS[activeFilter] || "전체 전략 현황"}${suffix}`);
  }

  function setFilter(filter) {
    activeFilter = FILTERS.has(filter) ? filter : "all";
    document.querySelectorAll("[data-filter]").forEach((button) => {
      const selected = button.dataset.filter === activeFilter;
      button.classList.toggle("is-active", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
    renderSections();
  }

  function renderSummary() {
    const counts = monitor.counts || {};
    setText("summary-all-count", monitor.scope && monitor.scope.report_count);
    setText("summary-hold-count", counts.hold);
    setText("summary-entry-count", counts.entry);
    setText("summary-exit-count", counts.exit);
    setText("strategy-scope", `기준일 ${formatDate(monitor.as_of)} · ${monitor.scope.label} ${formatNumber(monitor.scope.report_count)}종목`);
  }

  function validateMonitor(value) {
    return Boolean(
      value && value.schema_version === 1 && value.strategy && value.strategy.label === "A FAST Core" &&
      value.scope && value.scope.type === "PUBLISHED_REPORTS" && Number.isInteger(value.scope.report_count) &&
      value.counts && Array.isArray(value.items)
    );
  }

  async function loadMonitor() {
    const response = await fetch(MONITOR_URL, { cache: "no-store" });
    if (!response.ok) throw new Error("strategy monitor request failed");
    const value = await response.json();
    if (!validateMonitor(value)) throw new Error("strategy monitor schema is incomplete");
    monitor = value;
    renderSummary();
    renderSections();
  }

  function initInteractions() {
    document.querySelectorAll("[data-filter]").forEach((button) => {
      button.addEventListener("click", () => setFilter(button.dataset.filter));
    });
    const search = byId("strategy-search");
    if (search) search.addEventListener("input", () => {
      searchQuery = search.value;
      renderSections();
    });
  }

  initTheme();
  initInteractions();
  loadMonitor().catch(() => {
    const error = byId("strategy-error");
    if (error) error.hidden = false;
  });
}());
