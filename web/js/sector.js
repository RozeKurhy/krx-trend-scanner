(function () {
  "use strict";

  const PAYLOAD_URL = "./data/sector-rs-ranking.json";
  const THEME_STORAGE_KEY = "krx-theme";
  const THEME_VALUES = new Set(["light", "dark"]);
  const SYSTEM_THEME_QUERY = "(prefers-color-scheme: dark)";
  const HORIZONS = ["2w", "1m", "3m", "6m", "12m"];
  const HORIZON_LABELS = { "2w": "2주", "1m": "1개월", "3m": "3개월", "6m": "6개월", "12m": "12개월" };
  const MARKET_LABELS = { KOSPI: "코스피", KOSDAQ: "코스닥" };
  const DISPLAY_FIELDS = [
    "latest_close",
    "latest_close_as_of",
    ...HORIZONS.flatMap((horizon) => [`sector_anchor_date_${horizon}`, `sector_stock_return_${horizon}`]),
  ];

  const byId = (id) => document.getElementById(id);
  let payload = null;
  let activeSectorKey = null;
  let activeHorizon = "1m";
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

  function validRank(value) {
    return (
      value != null &&
      value !== "" &&
      Number.isFinite(Number(value)) &&
      Number(value) >= 1
    );
  }

  function validPercentile(value) {
    return (
      value != null &&
      value !== "" &&
      Number.isFinite(Number(value)) &&
      Number(value) >= 0 &&
      Number(value) <= 100
    );
  }

  function formatRank(value) {
    if (!validRank(value)) return "—";
    const rank = Number(value);
    return Number.isInteger(rank) ? formatNumber(rank) : formatNumber(rank, 6);
  }

  function formatPrice(value) {
    return value == null || value === "" || !Number.isFinite(Number(value)) ? "—" : `${formatNumber(value)}원`;
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

  function validSector(sector) {
    return Boolean(sector && typeof sector.sector_key === "string" && ["KOSPI", "KOSDAQ"].includes(sector.market) && typeof sector.sector_name === "string");
  }

  function validatePayload(value) {
    return Boolean(
      value && value.schema_version === 1 &&
      Array.isArray(value.horizons) && HORIZONS.every((horizon) => value.horizons.includes(horizon)) &&
      Array.isArray(value.sectors) && value.sectors.length > 0 && value.sectors.every(validSector) &&
      Array.isArray(value.items) && value.items.every((item) => item && typeof item === "object" && DISPLAY_FIELDS.every((field) => Object.prototype.hasOwnProperty.call(item, field))) &&
      value.metric_scope && value.metric_scope.type === "WITHIN_SECTOR" &&
      Array.isArray(value.metric_scope.group_key) &&
      JSON.stringify(value.metric_scope.group_key) === JSON.stringify(["market", "sector_code"])
    );
  }

  function sectorByKey() {
    return payload.sectors.find((sector) => sector.sector_key === activeSectorKey) || null;
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

  function topPercentLabel(percentile) {
    if (!validPercentile(percentile)) return "—";
    const topPercent = 100 - percentile;
    return `상위 ${formatNumber(topPercent, 1)}%`;
  }

  function itemMatches(item) {
    const normalized = searchQuery.trim().toLocaleLowerCase("ko-KR");
    if (!normalized) return true;
    return [item.name, item.ticker].some((value) => String(value || "").toLocaleLowerCase("ko-KR").includes(normalized));
  }

  function rankedItems() {
    const rankField = `within_sector_rs_rank_${activeHorizon}`;
    return (payload.items || [])
      .filter((item) => item.sector_key === activeSectorKey)
      .filter((item) => validRank(item[rankField]))
      .filter(itemMatches)
      .slice()
      .sort((left, right) => {
        const rankOrder = Number(left[rankField]) - Number(right[rankField]);
        if (rankOrder !== 0) return rankOrder;
        const nameOrder = String(left.name || "").localeCompare(String(right.name || ""), "ko-KR");
        if (nameOrder !== 0) return nameOrder;
        return String(left.ticker || "").localeCompare(String(right.ticker || ""));
      });
  }

  function createField(label, value, detail, className) {
    const field = createElement("span", `market-ranking-field${className ? ` ${className}` : ""}`);
    field.appendChild(createElement("small", "market-ranking-label", label));
    field.appendChild(createElement("strong", "market-ranking-value", value));
    if (detail) field.appendChild(createElement("small", "market-ranking-detail", detail));
    return field;
  }

  function createRankingRow(item) {
    const rankField = `within_sector_rs_rank_${activeHorizon}`;
    const percentileField = `within_sector_rs_percentile_${activeHorizon}`;
    const rsField = `sector_rs_${activeHorizon}`;
    const stockReturnField = `sector_stock_return_${activeHorizon}`;
    const sector = sectorByKey();
    const row = createElement("article", "sector-ranking-row");
    const identity = createElement("div", "market-ranking-identity");
    identity.appendChild(createElement("strong", "market-ranking-name", item.name || item.ticker));
    identity.appendChild(createElement("span", "market-ranking-meta", `${item.ticker} · ${marketLabel(item.market)} · ${sector ? sector.sector_name : ""}`));

    const eligibleCount = sector ? sector[`eligible_count_${activeHorizon}`] : null;
    const position = createField("섹터 순위", `${formatRank(item[rankField])} / ${formatNumber(eligibleCount)}`, topPercentLabel(item[percentileField]), "sector-ranking-position");
    const rs = createField("섹터 RS", formatReturn(item[rsField]), `최근 ${HORIZON_LABELS[activeHorizon]}`, `sector-ranking-rs ${returnClass(item[rsField])}`);
    const periodReturn = createField("기간 등락", formatReturn(item[stockReturnField]), `최근 ${HORIZON_LABELS[activeHorizon]}`, `sector-ranking-period-return ${returnClass(item[stockReturnField])}`);
    const price = createField("현재가", formatPrice(item.latest_close), formatDate(item.latest_close_as_of), "sector-ranking-price");
    const report = item.report_available
      ? createElement("a", "sector-ranking-report", "리포트 보기 ›")
      : createElement("span", "sector-ranking-report is-disabled", "리포트 준비 중");
    if (item.report_available) {
      report.href = `./report.html?ticker=${encodeURIComponent(item.ticker)}`;
      report.setAttribute("aria-label", `${item.name} ${item.ticker} 리포트 보기`);
    }

    row.append(identity, position, rs, periodReturn, price, report);
    return row;
  }

  function renderSectorOptions() {
    const select = byId("sector-select");
    if (!select) return;
    const options = ["KOSPI", "KOSDAQ"].flatMap((market) => payload.sectors
      .filter((sector) => sector.market === market)
      .map((sector) => {
        const option = createElement("option");
        option.value = sector.sector_key;
        option.textContent = `${marketLabel(sector.market)} · ${sector.sector_name}`;
        return option;
      })
    );
    select.replaceChildren(...options);
    select.value = activeSectorKey;
  }

  function syncSectorUrl() {
    const url = new URL(window.location.href);
    if (activeSectorKey) url.searchParams.set("sector", activeSectorKey);
    window.history.replaceState(null, "", url);
  }

  function renderControls() {
    const select = byId("sector-select");
    if (select) select.value = activeSectorKey || "";
    document.querySelectorAll("[data-horizon]").forEach((button) => {
      const selected = button.dataset.horizon === activeHorizon;
      button.classList.toggle("is-active", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
  }

  function renderSummary() {
    const sector = sectorByKey();
    if (!sector) return;
    const eligible = sector[`eligible_count_${activeHorizon}`];
    setText("sector-scope", `기준일 ${formatDate(payload.as_of)} · 구성 종목 ${formatNumber(sector.member_count)}개 · 비교 가능 ${formatNumber(eligible)}개 · ${HORIZON_LABELS[activeHorizon]}`);
  }

  function renderRanking() {
    if (!payload) return;
    renderControls();
    renderSummary();
    const items = rankedItems();
    const list = byId("sector-ranking-list");
    while (list.firstChild) list.removeChild(list.firstChild);
    if (!items.length) {
      list.appendChild(createElement("p", "sector-ranking-empty", "조건에 맞는 섹터 RS 랭킹 종목이 없습니다."));
    } else {
      items.forEach((item) => list.appendChild(createRankingRow(item)));
    }
    const suffix = searchQuery.trim() ? ` · 검색 결과 ${items.length}종목` : ` · ${items.length}종목`;
    setText("sector-ranking-meta", `${HORIZON_LABELS[activeHorizon]} 섹터 RS${suffix}`);
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
    const select = byId("sector-select");
    if (select) {
      select.addEventListener("change", () => {
        if (payload.sectors.some((sector) => sector.sector_key === select.value)) {
          activeSectorKey = select.value;
          syncSectorUrl();
          renderRanking();
        }
      });
    }
    const search = byId("sector-search");
    if (search) search.addEventListener("input", () => {
      searchQuery = search.value;
      renderRanking();
    });
  }

  async function loadPayload() {
    const response = await fetch(PAYLOAD_URL, { cache: "no-store" });
    if (!response.ok) throw new Error("sector ranking request failed");
    const value = await response.json();
    if (!validatePayload(value)) throw new Error("sector ranking schema is incomplete");
    payload = value;
    const requestedSector = new URLSearchParams(window.location.search).get("sector");
    activeSectorKey = payload.sectors.some((sector) => sector.sector_key === requestedSector) ? requestedSector : payload.sectors[0].sector_key;
    renderSectorOptions();
    syncSectorUrl();
    renderRanking();
  }

  initTheme();
  initInteractions();
  loadPayload().catch(() => {
    const error = byId("sector-error");
    if (error) error.hidden = false;
  });
}());
