(function () {
  "use strict";

  const PAYLOAD_URL = "./data/foreign-net-buy-ranking.json";
  const THEME_STORAGE_KEY = "krx-theme";
  const THEME_VALUES = new Set(["light", "dark"]);
  const SYSTEM_THEME_QUERY = "(prefers-color-scheme: dark)";
  const HORIZONS = ["1d", "5d", "10d", "20d", "60d"];
  const HORIZON_LABELS = { "1d": "1일", "5d": "5일", "10d": "10일", "20d": "20일", "60d": "60일" };
  const MARKET_LABELS = { KOSPI: "코스피", KOSDAQ: "코스닥" };
  const byId = (id) => document.getElementById(id);
  const numberFormat = new Intl.NumberFormat("ko-KR");
  let payload = null;
  let activeHorizon = "20d";
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

  function formatNetBuy(value) {
    if (value == null || value === "" || !Number.isFinite(Number(value))) return "—";
    const number = Number(value);
    const sign = number > 0 ? "+" : number < 0 ? "−" : "";
    const absolute = Math.abs(number);
    if (absolute >= 100000000) return `${sign}${formatNumber(absolute / 100000000, 2)}억원`;
    if (absolute >= 10000) return `${sign}${formatNumber(absolute / 10000, 0)}만원`;
    return `${sign}${formatNumber(absolute)}원`;
  }

  function formatReturn(value) {
    if (value == null || value === "" || !Number.isFinite(Number(value))) return "—";
    const percent = Number(value) * 100;
    if (percent === 0) return "0.0%";
    return `${percent > 0 ? "+" : ""}${percent.toFixed(1)}%`;
  }

  function valueClass(value) {
    if (value == null || value === "" || !Number.isFinite(Number(value)) || Number(value) === 0) return "return-neutral";
    return Number(value) > 0 ? "return-positive" : "return-negative";
  }

  function marketLabel(value) { return MARKET_LABELS[value] || "마켓 확인 필요"; }

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
        try { localStorage.setItem(THEME_STORAGE_KEY, next); } catch (error) { /* current page still switches */ }
        applyTheme(next);
      });
    }
  }

  function validatePayload(value) {
    return Boolean(
      value && value.schema_version === 1 && value.scope && value.scope.type === "KRX_COMMON_STOCKS" &&
      value.as_of === "2026-09-04" && Array.isArray(value.horizons) && HORIZONS.every((horizon) => value.horizons.includes(horizon)) &&
      value.coverage && Number.isInteger(value.coverage.target_common_universe_count) && Array.isArray(value.items) &&
      value.items.every((item) => item && item.asset_type === "COMMON" && item.market && item.ticker && item.name)
    );
  }

  function itemMatches(item) {
    const normalized = searchQuery.trim().toLocaleLowerCase("ko-KR");
    if (!normalized) return true;
    return [item.ticker, item.name, item.sector_name].some((value) => String(value || "").toLocaleLowerCase("ko-KR").includes(normalized));
  }

  function validFlow(value) {
    return (
      value !== null &&
      value !== "" &&
      Number.isFinite(Number(value))
    );
  }

  function rankedItems() {
    const field = `foreign_net_buy_${activeHorizon}`;
    return (payload.items || [])
      .filter((item) => validFlow(item[field]))
      .filter((item) => activeMarket === "ALL" || item.market === activeMarket)
      .filter(itemMatches)
      .slice()
      .sort((left, right) => {
        const flowOrder = Number(right[field]) - Number(left[field]);
        if (flowOrder !== 0) return flowOrder;
        const nameOrder = String(left.name || "").localeCompare(String(right.name || ""), "ko-KR");
        if (nameOrder !== 0) return nameOrder;
        return String(left.ticker || "").localeCompare(String(right.ticker || ""));
      });
  }

  function createField(label, value, detail, className) {
    const field = createElement("span", `foreign-ranking-field${className ? ` ${className}` : ""}`);
    field.appendChild(createElement("small", "foreign-ranking-label", label));
    field.appendChild(createElement("strong", "foreign-ranking-value", value));
    if (detail) field.appendChild(createElement("small", "foreign-ranking-detail", detail));
    return field;
  }

  function createRankingRow(item) {
    const flow = item[`foreign_net_buy_${activeHorizon}`];
    const periodReturn = item[`stock_return_${activeHorizon}`];
    const row = createElement("article", "foreign-ranking-row");
    const identity = createElement("div", "foreign-ranking-identity");
    identity.appendChild(createElement("strong", "foreign-ranking-name", item.name || item.ticker));
    const sector = item.sector_name ? ` · ${item.sector_name}` : "";
    identity.appendChild(createElement("span", "foreign-ranking-meta", `${item.ticker} · ${marketLabel(item.market)}${sector}`));
    const flowField = createField("외인 순매수", formatNetBuy(flow), `최근 ${HORIZON_LABELS[activeHorizon]}`, `foreign-ranking-flow ${valueClass(flow)}`);
    const returnField = createField("기간 등락", formatReturn(periodReturn), `최근 ${HORIZON_LABELS[activeHorizon]}`, `foreign-ranking-return ${valueClass(periodReturn)}`);
    const priceField = createField("현재가", formatPrice(item.latest_close), formatDate(item.latest_close_as_of), "foreign-ranking-price");
    const report = item.report_available
      ? createElement("a", "foreign-ranking-report", "리포트 보기 ›")
      : createElement("span", "foreign-ranking-report is-disabled", "리포트 준비 중");
    if (item.report_available) {
      report.href = `./report.html?ticker=${encodeURIComponent(item.ticker)}`;
      report.setAttribute("aria-label", `${item.name} ${item.ticker} 리포트 보기`);
    }
    row.append(identity, flowField, returnField, priceField, report);
    return row;
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
    if (!payload) return;
    renderControls();
    setText("foreign-as-of", `기준일 ${formatDate(payload.as_of)}`);
    const items = rankedItems();
    const list = byId("foreign-ranking-list");
    list.replaceChildren();
    if (!items.length) list.appendChild(createElement("p", "foreign-ranking-empty", "조건에 맞는 외인 순매수 종목이 없습니다."));
    else items.forEach((item) => list.appendChild(createRankingRow(item)));
    const suffix = searchQuery.trim() ? ` · 검색 결과 ${items.length}종목` : ` · ${items.length}종목`;
    setText("foreign-ranking-meta", `${HORIZON_LABELS[activeHorizon]} 외인 순매수${suffix}`);
  }

  function initInteractions() {
    document.querySelectorAll("[data-horizon]").forEach((button) => button.addEventListener("click", () => {
      if (HORIZONS.includes(button.dataset.horizon)) { activeHorizon = button.dataset.horizon; renderRanking(); }
    }));
    document.querySelectorAll("[data-market]").forEach((button) => button.addEventListener("click", () => {
      activeMarket = button.dataset.market || "ALL";
      renderRanking();
    }));
    const search = byId("foreign-search");
    if (search) search.addEventListener("input", () => { searchQuery = search.value; renderRanking(); });
  }

  async function loadPayload() {
    const response = await fetch(PAYLOAD_URL, { cache: "no-store" });
    if (!response.ok) throw new Error("foreign ranking request failed");
    const value = await response.json();
    if (!validatePayload(value)) throw new Error("foreign ranking schema is incomplete");
    payload = value;
    renderRanking();
  }

  initTheme();
  initInteractions();
  loadPayload().catch(() => {
    const error = byId("foreign-error");
    if (error) error.hidden = false;
  });
}());
