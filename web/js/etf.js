(function () {
  "use strict";

  const RANKING_URL = "./data/etf-ranking.json";
  const THEME_STORAGE_KEY = "krx-theme";
  const THEME_VALUES = new Set(["light", "dark"]);
  const SYSTEM_THEME_QUERY = "(prefers-color-scheme: dark)";
  const HORIZONS = ["2w", "1m", "3m", "6m", "12m"];
  const HORIZON_LABELS = { "2w": "2주", "1m": "1개월", "3m": "3개월", "6m": "6개월", "12m": "12개월" };
  const RETURN_FIELDS = { "2w": "return_2w", "1m": "return_1m", "3m": "return_3m", "6m": "return_6m", "12m": "return_12m" };
  const EXPECTED_HORIZONS = { "2w": 10, "1m": 21, "3m": 63, "6m": 126, "12m": 252 };
  const byId = (id) => document.getElementById(id);
  let ranking = null;
  let activeHorizon = "1m";

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
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value.slice(0, 10))) return "—";
    return value.slice(0, 10).replaceAll("-", ".");
  }

  function formatPrice(value) {
    return value == null || value === "" || !Number.isFinite(Number(value)) ? "—" : `${formatNumber(value)}원`;
  }

  function formatReturn(value) {
    if (value == null || value === "" || !Number.isFinite(Number(value))) return "—";
    const percent = Number(value) * 100;
    if (percent === 0) return "0.0%";
    return `${percent > 0 ? "+" : ""}${percent.toFixed(1)}%`;
  }

  function returnClass(value) {
    if (value == null || value === "" || !Number.isFinite(Number(value)) || Number(value) === 0) return "return-neutral";
    return Number(value) > 0 ? "return-positive" : "return-negative";
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

  function setText(id, value) {
    const element = byId(id);
    if (element) element.textContent = value == null || value === "" ? "—" : String(value);
  }

  function createField(label, value, detail, className) {
    const field = createElement("span", `etf-ranking-field${className ? ` ${className}` : ""}`);
    field.appendChild(createElement("small", "etf-ranking-label", label));
    field.appendChild(createElement("strong", "etf-ranking-value", value));
    if (detail) field.appendChild(createElement("small", "etf-ranking-detail", detail));
    return field;
  }

  function rankedItems() {
    const field = RETURN_FIELDS[activeHorizon];
    return (ranking.items || []).slice().sort((left, right) => {
      const returnOrder = Number(right[field]) - Number(left[field]);
      if (returnOrder !== 0) return returnOrder;
      const nameOrder = String(left.name || "").localeCompare(String(right.name || ""), "ko-KR");
      if (nameOrder !== 0) return nameOrder;
      return String(left.ticker || "").localeCompare(String(right.ticker || ""));
    });
  }

  function createRankingRow(item, rank) {
    const row = createElement("article", "etf-ranking-row");
    row.setAttribute("aria-label", `${rank}위 ${item.name || item.ticker}`);
    const identity = createElement("span", "etf-ranking-identity");
    identity.appendChild(createElement("strong", "etf-ranking-name", item.name || item.ticker));
    identity.appendChild(createElement("span", "etf-ranking-meta", `${item.ticker} · ${item.category || "ETF"}`));
    const periodReturn = item[RETURN_FIELDS[activeHorizon]];
    const position = createField("순위", `${rank}위`, null, "etf-ranking-position");
    const returnField = createField("기간 수익률", formatReturn(periodReturn), `최근 ${HORIZON_LABELS[activeHorizon]}`, `etf-ranking-return ${returnClass(periodReturn)}`);
    const price = createField("현재가", formatPrice(item.latest_close), formatDate(item.latest_close_as_of), "etf-ranking-price");
    row.append(identity, position, returnField, price);
    return row;
  }

  function renderScope() {
    setText("etf-scope", `기준일 ${formatDate(ranking.as_of)} · ${formatNumber(ranking.scope.count)}개 ETF`);
  }

  function renderControls() {
    document.querySelectorAll("[data-horizon]").forEach((button) => {
      const selected = button.dataset.horizon === activeHorizon;
      button.classList.toggle("is-active", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
  }

  function renderRanking() {
    if (!ranking) return;
    renderScope();
    renderControls();
    const list = byId("etf-ranking-list");
    while (list.firstChild) list.removeChild(list.firstChild);
    rankedItems().forEach((item, index) => list.appendChild(createRankingRow(item, index + 1)));
    setText("etf-ranking-meta", `${HORIZON_LABELS[activeHorizon]} · ${formatNumber(ranking.items.length)}개 ETF`);
  }

  function validNumber(value) {
    return typeof value === "number" && Number.isFinite(value);
  }

  function validateRanking(value) {
    if (!value || value.schema_version !== 1 || value.as_of !== "2026-09-04" || !value.scope || value.scope.type !== "FIXED_ETF_UNIVERSE" || value.scope.count !== 24 || !Array.isArray(value.items) || value.items.length !== 24) return false;
    if (!value.horizons || HORIZONS.some((horizon) => value.horizons[horizon] !== EXPECTED_HORIZONS[horizon])) return false;
    return value.items.every((item) => item && typeof item.ticker === "string" && typeof item.name === "string" && typeof item.category === "string" && typeof item.latest_close_as_of === "string" && validNumber(item.latest_close) && item.latest_close > 0 && HORIZONS.every((horizon) => validNumber(item[RETURN_FIELDS[horizon]])));
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
  }

  async function loadRanking() {
    const response = await fetch(RANKING_URL, { cache: "no-store" });
    if (!response.ok) throw new Error("ETF ranking request failed");
    const value = await response.json();
    if (!validateRanking(value)) throw new Error("ETF ranking schema is incomplete");
    ranking = value;
    renderRanking();
  }

  initTheme();
  initInteractions();
  loadRanking().catch(() => {
    const error = byId("etf-error");
    if (error) error.hidden = false;
  });
}());
