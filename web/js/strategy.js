(function () {
  "use strict";

  const MONITOR_URL = "./data/strategy-monitor.json";
  const THEME_STORAGE_KEY = "krx-theme";
  const THEME_VALUES = new Set(["light", "dark"]);
  const SYSTEM_THEME_QUERY = "(prefers-color-scheme: dark)";
  const MARKET_LABELS = { KOSPI: "코스피", KOSDAQ: "코스닥", KONEX: "코넥스" };
  const ASSET_LABELS = { COMMON: "보통주", ETF: "ETF" };
  const POSITION_LABELS = { OPEN: "보유 중", FLAT: "미보유", NOT_APPLICABLE: "해당 없음" };
  const STATE_LABELS = {
    HOLD_PROGRESSED: "상승 진행 구간 보유",
    HOLD_PRE_PROGRESSED: "초기 추세 구간 보유",
    WAIT: "진입 전 관찰",
    ENTRY: "진입 조건 충족",
    ENTRY_PENDING: "다음 시가 진입 대기",
    EXIT_PENDING: "다음 시가 청산 대기",
    HOLD: "보유 유지",
    DATA_UNAVAILABLE: "전략 데이터 없음",
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
  const PATTERN_B_LABELS = {
    DEEP_DEPRESSED: "깊은 침체",
    DEPRESSED: "침체",
    NORMAL: "정상",
    OVERHEATED: "과열",
    EXTREME_OVERHEATED: "극단 과열",
  };
  const STRATEGY_LABELS = {
    PATTERN_A_FAST_FINAL_STRATEGY_V02: "A FAST Core V2",
    PATTERN_B_SELECT_CORE_V01: "B Select Core V1",
    JULIA_ETF_STRATEGY_V01: "Julia V1",
  };
  const EXPECTED_STRATEGY_IDS = Object.keys(STRATEGY_LABELS);
  const SECTION_IDS = { hold: "hold", entry: "entry", exit: "exit", watch: "watch", unavailable: "unavailable" };
  const FILTERS = new Set(["all", ...Object.keys(SECTION_IDS)]);

  const byId = (id) => document.getElementById(id);
  let monitor = null;
  let activeStrategyId = "PATTERN_A_FAST_FINAL_STRATEGY_V02";
  let activeFilter = "all";
  let searchQuery = "";
  let holdSort = "entry-date";

  function setText(id, value) {
    const element = byId(id);
    if (element) element.textContent = value == null || value === "" ? "—" : String(value);
  }

  function marketLabel(value) { return MARKET_LABELS[value] || "마켓 확인 필요"; }
  function assetLabel(value) { return ASSET_LABELS[value] || "자산 확인 필요"; }
  function positionLabel(value) { return POSITION_LABELS[value] || "상태 확인 필요"; }
  function stateLabel(value) { return STATE_LABELS[value] || "상태 확인 필요"; }
  function stageLabel(value) { return STAGE_LABELS[value] || "확인 필요"; }
  function patternBLabel(value) { return PATTERN_B_LABELS[value] || (value ? "확인 필요" : "확인 필요"); }
  function activeStrategy() {
    if (!monitor) return null;
    return (monitor.strategies || []).find((strategy) => strategy.id === activeStrategyId) || monitor.strategies[0] || null;
  }

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
    const sun = byId("theme-icon-sun");
    const moon = byId("theme-icon-moon");
    if (sun) sun.classList.toggle("is-active", resolved === "light");
    if (moon) moon.classList.toggle("is-active", resolved === "dark");
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
    return [
      item.ticker,
      item.name,
      item.sector_name,
      item.pattern_b_state,
      item.pattern_a_stage,
      item.previous_pattern_a_stage,
      item.strategy_state,
    ].some((value) => String(value || "").toLocaleLowerCase("ko-KR").includes(normalized));
  }

  function compareText(a, b) {
    return String(a.name || "").localeCompare(String(b.name || ""), "ko");
  }

  function compareTicker(a, b) {
    return String(a.ticker || "").localeCompare(String(b.ticker || ""));
  }

  function parseSortableDate(value) {
    const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!match) return null;
    const year = Number(match[1]);
    const month = Number(match[2]);
    const day = Number(match[3]);
    const date = new Date(Date.UTC(year, month - 1, day));
    if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return null;
    return date.getTime();
  }

  function parseSortableNumber(value) {
    if (value == null || String(value).trim() === "") return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function compareHoldItems(a, b) {
    const tradeA = a && a.current_trade;
    const tradeB = b && b.current_trade;
    if (holdSort === "return") {
      const returnA = parseSortableNumber(tradeA && tradeA.return_pct);
      const returnB = parseSortableNumber(tradeB && tradeB.return_pct);
      if (returnA == null && returnB != null) return 1;
      if (returnA != null && returnB == null) return -1;
      if (returnA != null && returnB != null && returnA !== returnB) return returnB - returnA;
    } else if (holdSort === "name") {
      const nameResult = compareText(a, b);
      if (nameResult) return nameResult;
    } else {
      const dateA = parseSortableDate(tradeA && tradeA.entry_execution_date);
      const dateB = parseSortableDate(tradeB && tradeB.entry_execution_date);
      if (dateA == null && dateB != null) return 1;
      if (dateA != null && dateB == null) return -1;
      if (dateA != null && dateB != null && dateA !== dateB) return dateB - dateA;
    }
    const tieName = compareText(a, b);
    return tieName || compareTicker(a, b);
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
    const strategyId = activeStrategyId;
    const layoutClass = strategyId === "PATTERN_B_SELECT_CORE_V01"
      ? "strategy-item-b-select"
      : strategyId === "JULIA_ETF_STRATEGY_V01"
        ? "strategy-item-julia"
        : "strategy-item-a-fast";
    const link = createElement("a", `strategy-item ${layoutClass}`);
    link.href = `./report.html?ticker=${encodeURIComponent(item.ticker)}`;
    link.setAttribute("aria-label", `${item.name} ${item.ticker} 리포트 보기`);

    const identity = createElement("span", "strategy-item-identity");
    identity.appendChild(createElement("strong", "strategy-item-name", item.name || item.ticker));
    const meta = [item.ticker, marketLabel(item.market)];
    if (item.asset_type !== "COMMON") meta.push(assetLabel(item.asset_type));
    if (item.sector_name) meta.push(item.sector_name);
    identity.appendChild(createElement("span", "strategy-item-meta", meta.join(" · ")));

    const position = createPositionField(item);
    let detailFields = [];
    if (strategyId === "PATTERN_B_SELECT_CORE_V01") {
      detailFields = [
        createField("Pattern A", stageLabel(item.pattern_a_stage)),
        createField("Pattern B", `${stageLabel(item.previous_pattern_a_stage)} → ${patternBLabel(item.pattern_b_state)}`),
      ];
    } else if (strategyId === "JULIA_ETF_STRATEGY_V01") {
      detailFields = [];
    } else {
      const pattern = item.canonical_position === "NOT_APPLICABLE"
        ? createField("패턴", "해당 없음")
        : createField("패턴", `${stageLabel(item.pattern_stage)} · ${formatNumber(item.pattern_score, 2)}점`);
      detailFields = [pattern];
    }
    const price = createPriceDateField("현재가", formatPrice(item.latest_close), formatDate(item.latest_close_as_of));
    const trade = item.current_trade;
    const entry = trade
      ? createPriceDateField("진입가", formatPrice(trade.entry_open), formatDate(trade.entry_execution_date))
      : createField("진입가", "—");
    const returnClass = trade && Number(trade.return_pct) > 0 ? "detail-value-positive" : trade && Number(trade.return_pct) < 0 ? "detail-value-negative" : "";
    const returnField = createField("수익률", trade ? formatReturn(trade.return_pct) : "—", returnClass);
    const arrow = createElement("span", "strategy-item-link", "리포트 보기 ›");

    link.append(identity, position, ...detailFields, price, entry, returnField, arrow);
    return link;
  }

  function filteredItems(category) {
    const selected = activeStrategy();
    const items = ((selected && selected.items) || []).filter((item) => item.bucket === category && itemMatches(item));
    if (category !== "hold" || activeFilter !== "hold") return items;
    return items.slice().sort(compareHoldItems);
  }

  function syncHoldSortVisibility() {
    const row = byId("strategy-hold-sort-row");
    const select = byId("strategy-hold-sort");
    const visible = activeFilter === "hold";
    if (row) row.hidden = !visible;
    if (select) {
      select.disabled = !visible;
      if (select.value !== holdSort) select.value = holdSort;
    }
  }

  function renderFilterCounts() {
    const selected = activeStrategy();
    if (!selected) return;
    const counts = { all: 0, hold: 0, entry: 0, exit: 0, watch: 0, unavailable: 0 };
    if (searchQuery.trim()) {
      const matched = (selected.items || []).filter(itemMatches);
      counts.all = matched.length;
      matched.forEach((item) => {
        if (Object.prototype.hasOwnProperty.call(counts, item.bucket)) counts[item.bucket] += 1;
      });
    } else {
      counts.all = selected.scope.report_count;
      Object.keys(SECTION_IDS).forEach((category) => {
        counts[category] = selected.counts[category] || 0;
      });
    }
    Object.keys(counts).forEach((category) => setText(`strategy-filter-count-${category}`, counts[category]));
  }

  function renderSections() {
    if (!monitor) return;
    renderFilterCounts();
    Object.keys(SECTION_IDS).forEach((category) => {
      const section = byId(`${category}-section`);
      const list = byId(`${category}-list`);
      if (!section || !list) return;
      const enabled = activeFilter === "all" || activeFilter === category;
      section.hidden = !enabled;
      while (list.firstChild) list.removeChild(list.firstChild);
      if (!enabled) return;
      const items = filteredItems(category);
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
  }

  function setFilter(filter) {
    activeFilter = FILTERS.has(filter) ? filter : "all";
    document.querySelectorAll("[data-filter]").forEach((button) => {
      const selected = button.dataset.filter === activeFilter;
      button.classList.toggle("is-active", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
    syncHoldSortVisibility();
    renderSections();
  }

  function renderScope() {
    const selected = activeStrategy();
    if (!selected) return;
    setText(
      "strategy-scope",
      `기준일 ${formatDate(monitor.requested_as_of || monitor.as_of)} · ${formatNumber(selected.scope.report_count)}개`
    );
    document.querySelectorAll("[data-strategy-id]").forEach((button) => {
      const available = (monitor.strategies || []).some((strategy) => strategy.id === button.dataset.strategyId);
      const selectedButton = available && button.dataset.strategyId === activeStrategyId;
      button.disabled = !available;
      button.classList.toggle("is-active", selectedButton);
      button.setAttribute("aria-pressed", String(selectedButton));
    });
  }

  function validateMonitor(value) {
    if (!value || value.source?.type !== "PUBLISHED_STOCK_REPORTS") return false;
    if (value.schema_version === 1) {
      return Boolean(
        value.strategy?.id === "PATTERN_A_FAST_FINAL_STRATEGY_V02"
        && value.scope?.type === "PUBLISHED_COMMON_REPORTS"
        && Number.isInteger(value.scope.report_count)
        && value.counts && Array.isArray(value.items)
      );
    }
    if (
      value.schema_version !== 2
      || value.default_strategy_id !== "PATTERN_A_FAST_FINAL_STRATEGY_V02"
      || !/^\d{4}-\d{2}-\d{2}$/.test(value.requested_as_of || "")
      || !/^\d{4}-\d{2}-\d{2}$/.test(value.reference_market_date || "")
      || value.reference_market_date > value.requested_as_of
      || !Array.isArray(value.strategies)
      || value.strategies.length !== EXPECTED_STRATEGY_IDS.length
    ) return false;
    const byId = new Map(value.strategies.map((strategy) => [strategy && strategy.id, strategy]));
    if (EXPECTED_STRATEGY_IDS.some((id) => !byId.has(id))) return false;
    for (const id of EXPECTED_STRATEGY_IDS) {
      const strategy = byId.get(id);
      const expectedScope = id === "JULIA_ETF_STRATEGY_V01" ? "OFFICIAL_ETF_36" : "COMMON";
      const expectedScopeType = expectedScope === "OFFICIAL_ETF_36" ? "OFFICIAL_ETF_36" : "PUBLISHED_COMMON_REPORTS";
      if (
        strategy.label !== STRATEGY_LABELS[id]
        || strategy.asset_scope !== expectedScope
        || !strategy.scope || strategy.scope.type !== expectedScopeType
        || !Number.isInteger(strategy.scope.report_count)
        || !strategy.counts || !Array.isArray(strategy.items)
        || strategy.items.length !== strategy.scope.report_count
        || (expectedScope === "OFFICIAL_ETF_36" && strategy.scope.report_count !== 36)
      ) return false;
      const seen = new Set();
      const counts = { entry: 0, hold: 0, exit: 0, watch: 0, unavailable: 0 };
      for (const item of strategy.items) {
        if (!item || !item.ticker || seen.has(String(item.ticker))) return false;
        seen.add(String(item.ticker));
        if (item.asset_type !== (expectedScope === "OFFICIAL_ETF_36" ? "ETF" : "COMMON")) return false;
        if (!Object.prototype.hasOwnProperty.call(counts, item.bucket)) return false;
        counts[item.bucket] += 1;
      }
      if (Object.keys(counts).some((key) => Number(strategy.counts[key] || 0) !== counts[key])) return false;
    }
    const commonA = new Set(byId.get("PATTERN_A_FAST_FINAL_STRATEGY_V02").items.map((item) => item.ticker));
    const commonB = new Set(byId.get("PATTERN_B_SELECT_CORE_V01").items.map((item) => item.ticker));
    return commonA.size === commonB.size && Array.from(commonA).every((ticker) => commonB.has(ticker));
  }

  function normalizeMonitor(value) {
    if (value.schema_version !== 1) return value;
    return {
      ...value,
      schema_version: 2,
      requested_as_of: value.requested_as_of || value.as_of,
      default_strategy_id: value.strategy.id,
      strategies: [{
        id: value.strategy.id,
        label: STRATEGY_LABELS[value.strategy.id],
        asset_scope: "COMMON",
        scope: value.scope,
        counts: value.counts,
        items: value.items,
      }],
    };
  }

  async function loadMonitor() {
    const response = await fetch(MONITOR_URL, { cache: "no-store" });
    if (!response.ok) throw new Error("strategy monitor request failed");
    const raw = await response.json();
    if (!validateMonitor(raw)) throw new Error("strategy monitor schema is incomplete");
    const value = normalizeMonitor(raw);
    monitor = value;
    activeStrategyId = value.default_strategy_id;
    renderScope();
    renderSections();
  }

  function setStrategy(strategyId) {
    if (!monitor || !(monitor.strategies || []).some((strategy) => strategy.id === strategyId)) return;
    activeStrategyId = strategyId;
    renderScope();
    renderSections();
  }

  function initInteractions() {
    document.querySelectorAll("[data-strategy-id]").forEach((button) => {
      button.addEventListener("click", () => setStrategy(button.dataset.strategyId));
    });
    document.querySelectorAll("[data-filter]").forEach((button) => {
      button.addEventListener("click", () => setFilter(button.dataset.filter));
    });
    const search = byId("strategy-search");
    if (search) search.addEventListener("input", () => {
      searchQuery = search.value;
      renderSections();
    });
    const holdSortSelect = byId("strategy-hold-sort");
    if (holdSortSelect) holdSortSelect.addEventListener("change", () => {
      holdSort = ["entry-date", "return", "name"].includes(holdSortSelect.value) ? holdSortSelect.value : "entry-date";
      syncHoldSortVisibility();
      renderSections();
    });
    syncHoldSortVisibility();
  }

  initTheme();
  initInteractions();
  loadMonitor().catch(() => {
    const error = byId("strategy-error");
    if (error) error.hidden = false;
  });
}());
