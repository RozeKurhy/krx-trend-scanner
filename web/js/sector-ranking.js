(function () {
  "use strict";

  const PAYLOAD_URL = "./data/sector-rs-ranking.json";
  const THEME_STORAGE_KEY = "krx-theme";
  const THEME_VALUES = new Set(["light", "dark"]);
  const SYSTEM_THEME_QUERY = "(prefers-color-scheme: dark)";
  const HORIZONS = ["2w", "1m", "3m", "6m", "12m"];
  const HORIZON_LABELS = { "2w": "2주", "1m": "1개월", "3m": "3개월", "6m": "6개월", "12m": "12개월" };
  const MARKET_LABELS = { KOSPI: "코스피", KOSDAQ: "코스닥" };
  const byId = (id) => document.getElementById(id);
  let payload = null;
  let activeHorizon = "2w";

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

  function isFiniteNumber(value) {
    return value != null && value !== "" && Number.isFinite(Number(value));
  }

  function formatNumber(value) {
    if (!isFiniteNumber(value)) return "—";
    return new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 }).format(Number(value));
  }

  function formatDate(value) {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return "—";
    return value.replaceAll("-", ".");
  }

  function formatReturn(value) {
    if (!isFiniteNumber(value)) return "—";
    const percent = Number(value) * 100;
    if (percent === 0) return "0.0%";
    return `${percent > 0 ? "+" : ""}${percent.toFixed(1)}%`;
  }

  function returnClass(value) {
    if (!isFiniteNumber(value) || Number(value) === 0) return "return-neutral";
    return Number(value) > 0 ? "return-positive" : "return-negative";
  }

  function marketLabel(value) {
    return MARKET_LABELS[value] || "마켓 확인 필요";
  }

  function rankedSectors(sectors, horizon) {
    const field = `sector_return_${horizon}`;
    return sectors
      .filter((sector) => isFiniteNumber(sector[field]))
      .slice()
      .sort((left, right) => {
        const returnOrder = Number(right[field]) - Number(left[field]);
        if (returnOrder !== 0) return returnOrder;
        const marketOrder = String(left.market).localeCompare(String(right.market), "en");
        if (marketOrder !== 0) return marketOrder;
        const nameOrder = String(left.sector_name).localeCompare(String(right.sector_name), "ko-KR");
        if (nameOrder !== 0) return nameOrder;
        return String(left.sector_code).localeCompare(String(right.sector_code), "en");
      });
  }

  function countBreadth(items, sectorKey, horizon) {
    const field = `sector_stock_return_${horizon}`;
    const resolved = items
      .filter((item) => item.sector_key === sectorKey)
      .map((item) => item[field])
      .filter(isFiniteNumber);
    return {
      positive: resolved.filter((value) => Number(value) > 0).length,
      resolved: resolved.length,
    };
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
  }

  function validSector(sector) {
    return Boolean(
      sector &&
      ["KOSPI", "KOSDAQ"].includes(sector.market) &&
      typeof sector.sector_code === "string" &&
      typeof sector.sector_name === "string" &&
      sector.sector_key === `${sector.market}:${sector.sector_code}` &&
      HORIZONS.every((horizon) => Object.prototype.hasOwnProperty.call(sector, `sector_return_${horizon}`))
    );
  }

  function validatePayload(value) {
    return Boolean(
      value && value.schema_version === 1 &&
      value.as_of &&
      value.metric_scope && value.metric_scope.type === "WITHIN_SECTOR" &&
      JSON.stringify(value.metric_scope.group_key) === JSON.stringify(["market", "sector_code"]) &&
      Array.isArray(value.horizons) && HORIZONS.every((horizon) => value.horizons.includes(horizon)) &&
      Array.isArray(value.sectors) && value.sectors.length > 0 && value.sectors.every(validSector) &&
      new Set(value.sectors.map((sector) => sector.sector_key)).size === value.sectors.length &&
      Array.isArray(value.items) && value.items.every((item) =>
        item && typeof item === "object" &&
        HORIZONS.every((horizon) => Object.prototype.hasOwnProperty.call(item, `sector_stock_return_${horizon}`))
      )
    );
  }

  function createField(label, value, detail, className) {
    const field = createElement("span", `market-ranking-field${className ? ` ${className}` : ""}`);
    field.appendChild(createElement("small", "market-ranking-label", label));
    field.appendChild(createElement("strong", "market-ranking-value", value));
    if (detail) field.appendChild(createElement("small", "market-ranking-detail", detail));
    return field;
  }

  function createSectorRow(sector, rank) {
    const returnValue = sector[`sector_return_${activeHorizon}`];
    const breadth = countBreadth(payload.items, sector.sector_key, activeHorizon);
    const row = createElement("article", "cross-sector-ranking-row");
    const identity = createElement("div", "market-ranking-identity cross-sector-ranking-identity");
    identity.appendChild(createElement("span", "cross-sector-ranking-place", `${rank}위`));
    identity.appendChild(createElement("strong", "market-ranking-name", sector.sector_name));
    identity.appendChild(createElement("span", "market-ranking-meta", `${marketLabel(sector.market)} · ${sector.sector_code}`));

    const change = createField(
      "섹터 등락",
      formatReturn(returnValue),
      `최근 ${HORIZON_LABELS[activeHorizon]}`,
      `cross-sector-ranking-return ${returnClass(returnValue)}`,
    );
    const advances = createField("상승 종목", `${formatNumber(breadth.positive)} / ${formatNumber(breadth.resolved)}`, "비교 가능 종목");
    const members = createField("구성 종목", formatNumber(sector.member_count));
    const link = createElement("a", "row-chevron cross-sector-ranking-link ranking-report-link", ">");
    link.href = `./sector.html?sector=${encodeURIComponent(sector.sector_key)}`;
    link.setAttribute("aria-label", `${marketLabel(sector.market)} ${sector.sector_name} 섹터 RS 보기`);

    row.append(identity, change, advances, members, link);
    return row;
  }

  function renderScope(sectorCount) {
    setText("cross-sector-scope", `기준일 ${formatDate(payload.as_of)} · ${formatNumber(sectorCount)}개 섹터`);
  }

  function renderRanking() {
    if (!payload) return;
    document.querySelectorAll("[data-horizon]").forEach((button) => {
      const selected = button.dataset.horizon === activeHorizon;
      button.classList.toggle("is-active", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
    const sectors = rankedSectors(payload.sectors, activeHorizon);
    renderScope(sectors.length);
    const list = byId("cross-sector-ranking-list");
    list.replaceChildren(...sectors.map((sector, index) => createSectorRow(sector, index + 1)));
    if (!sectors.length) {
      list.appendChild(createElement("p", "cross-sector-ranking-empty", "선택한 기간에 비교 가능한 섹터가 없습니다."));
    }
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

  async function loadPayload() {
    const response = await fetch(PAYLOAD_URL, { cache: "no-store" });
    if (!response.ok) throw new Error("sector ranking request failed");
    const value = await response.json();
    if (!validatePayload(value)) throw new Error("sector ranking schema is incomplete");
    payload = value;
    renderRanking();
  }

  initTheme();
  initInteractions();
  loadPayload().catch(() => {
    const error = byId("cross-sector-error");
    if (error) error.hidden = false;
  });
}());
