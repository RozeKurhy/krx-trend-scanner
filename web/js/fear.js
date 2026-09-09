(function () {
  "use strict";

  const PAYLOAD_URL = "./data/fear-index.json";
  const THEME_STORAGE_KEY = "krx-theme";
  const THEME_VALUES = new Set(["light", "dark"]);
  const SYSTEM_THEME_QUERY = "(prefers-color-scheme: dark)";
  const REGIME_LABELS = Object.freeze({
    OVERHEATED: "과열·흥분",
    NORMAL: "정상·안정",
    ANXIOUS: "불안",
    PANIC: "공포·패닉",
    APATHY: "침체·무관심",
  });
  const REGIMES = Object.freeze(Object.keys(REGIME_LABELS));
  const REGIME_COLORS = {
    OVERHEATED: "--regime-overheated-bg",
    NORMAL: "--regime-normal-bg",
    ANXIOUS: "--regime-anxious-bg",
    PANIC: "--regime-panic-bg",
    APATHY: "--regime-apathy-bg",
  };
  const RANGE_SESSION_COUNTS = Object.freeze({ "5y": 1260, "3y": 756, "1y": 252, "6m": 126 });
  const RANGE_LABELS = Object.freeze({ all: "전체", "5y": "5년", "3y": "3년", "1y": "1년", "6m": "6개월" });
  const byId = (id) => document.getElementById(id);
  const state = {
    payload: null,
    rows: [],
    selectedRows: [],
    range: "all",
    plot: null,
    hoverIndex: null,
  };

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
    return value !== null && value !== undefined && value !== "" &&
      !(typeof value === "string" && value.trim() === "") &&
      typeof value !== "boolean" && Number.isFinite(Number(value));
  }

  function isValidDate(value) {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    const parsed = new Date(`${value}T00:00:00Z`);
    return !Number.isNaN(parsed.getTime());
  }

  function safeRegime(value) {
    return REGIMES.includes(value) ? value : "UNKNOWN";
  }

  function regimeLabel(value) {
    return REGIME_LABELS[value] || "확인 불가";
  }

  function formatNumber(value, maximumFractionDigits) {
    if (!isFiniteNumber(value)) return "—";
    return new Intl.NumberFormat("ko-KR", {
      maximumFractionDigits: maximumFractionDigits == null ? 0 : maximumFractionDigits,
    }).format(Number(value));
  }

  function formatScore(value) {
    return isFiniteNumber(value) ? `${Number(value).toFixed(1)} / 100` : "— / 100";
  }

  function formatDate(value) {
    return isValidDate(value) ? value.replaceAll("-", ".") : "—";
  }

  function formatTradingValue(value, exact) {
    if (!isFiniteNumber(value)) return "—";
    const number = Number(value);
    const trillion = number / 1000000000000;
    if (exact) return `${formatNumber(number)}원 · ${trillion.toFixed(2)}조`;
    return `${trillion.toFixed(2)}조`;
  }

  function validPayload(value) {
    return Boolean(
      value && typeof value === "object" &&
      value.schema_version === "FEAR_INDEX_WEB_V01" &&
      value.model && typeof value.model === "object" &&
      Array.isArray(value.items) && value.items.length > 0 &&
      value.current && isFiniteNumber(value.current.fear_score) &&
      isFiniteNumber(value.current.kospi_close) &&
      isFiniteNumber(value.current.v_kospi200_close) &&
      isFiniteNumber(value.current.trading_value) &&
      REGIMES.includes(value.current.regime) &&
      isValidDate(value.current.date) && isValidDate(value.as_of)
    );
  }

  function normalizeRows(payload) {
    return payload.items
      .filter((item) => item && isValidDate(item.date) &&
        ["kospi_close", "v_kospi200_close", "trading_value", "fear_score"].every((field) => isFiniteNumber(item[field])))
      .map((item) => ({
        date: item.date,
        kospi_close: Number(item.kospi_close),
        v_kospi200_close: Number(item.v_kospi200_close),
        trading_value: Number(item.trading_value),
        fear_score: Number(item.fear_score),
        regime: safeRegime(item.regime),
      }))
      .sort((left, right) => left.date.localeCompare(right.date));
  }

  function filterRange(rows, range) {
    const count = RANGE_SESSION_COUNTS[range];
    if (!count || rows.length <= count) return rows.slice();
    return rows.slice(-count);
  }

  function buildRegimeBands(rows) {
    if (!rows.length) return [];
    const bands = [];
    let start = 0;
    let regime = safeRegime(rows[0].regime);
    for (let index = 1; index < rows.length; index += 1) {
      const next = safeRegime(rows[index].regime);
      if (next === regime) continue;
      bands.push({ start, end: index - 1, regime });
      start = index;
      regime = next;
    }
    bands.push({ start, end: rows.length - 1, regime });
    return bands;
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
    if (button) {
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
    if (state.selectedRows.length) renderChart();
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
    if (window.matchMedia) {
      const media = window.matchMedia(SYSTEM_THEME_QUERY);
      const syncWithSystem = () => {
        if (!readStoredTheme()) applyTheme(systemTheme());
      };
      if (media.addEventListener) media.addEventListener("change", syncWithSystem);
      else if (media.addListener) media.addListener(syncWithSystem);
    }
  }

  function renderRegimes(currentRegime) {
    document.querySelectorAll("#fear-regimes .fear-regime-chip").forEach((chip) => {
      const active = REGIMES.includes(currentRegime) && chip.dataset.regime === currentRegime;
      chip.classList.toggle("is-current", active);
      if (active) chip.setAttribute("aria-current", "true");
      else chip.removeAttribute("aria-current");
    });
  }

  function renderCurrent(current) {
    setText("fear-current-score", formatScore(current.fear_score));
    setText("fear-current-regime", regimeLabel(current.regime));
    setText("fear-current-vkospi", formatNumber(current.v_kospi200_close, 2));
    setText("fear-current-kospi", formatNumber(current.kospi_close, 2));
    setText("fear-current-trading-value", formatTradingValue(current.trading_value));
    setText("fear-current-as-of", formatDate(current.date));
    setText("fear-current-date", `기준일 ${formatDate(current.date)}`);
    renderRegimes(current.regime);
  }

  function cssVariable(name, fallback) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
  }

  function chartGeometry(width, height) {
    const compact = width < 560;
    const left = compact ? 45 : 62;
    const right = compact ? 45 : 60;
    const top = 30;
    const bottom = compact ? 42 : 48;
    const lowerHeight = Math.max(82, Math.round(height * 0.22));
    const lowerBottom = height - bottom;
    const lowerTop = lowerBottom - lowerHeight;
    const paneGap = compact ? 29 : 36;
    const upperTop = top;
    const upperBottom = lowerTop - paneGap;
    return {
      width, height, left, right, top, bottom, lowerTop, lowerBottom, upperTop, upperBottom,
      plotWidth: Math.max(1, width - left - right),
      upperHeight: Math.max(1, upperBottom - upperTop),
      lowerHeight: Math.max(1, lowerBottom - lowerTop),
    };
  }

  function drawGrid(ctx, geometry, rows) {
    const { left, right, upperTop, upperBottom, lowerTop, lowerBottom, plotWidth } = geometry;
    const line = cssVariable("--line", "#e2e5e9");
    const soft = cssVariable("--ink-faint", "#8b9097");
    ctx.strokeStyle = line;
    ctx.fillStyle = soft;
    ctx.lineWidth = 1;
    ctx.font = "10px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    ctx.textBaseline = "middle";

    for (let tick = 0; tick <= 4; tick += 1) {
      const y = upperTop + (upperBottom - upperTop) * tick / 4;
      ctx.beginPath();
      ctx.moveTo(left, y);
      ctx.lineTo(left + plotWidth, y);
      ctx.stroke();
    }
    for (let tick = 0; tick <= 2; tick += 1) {
      const y = lowerTop + (lowerBottom - lowerTop) * tick / 2;
      ctx.beginPath();
      ctx.moveTo(left, y);
      ctx.lineTo(left + plotWidth, y);
      ctx.stroke();
    }
    ctx.fillText("KOSPI", left, upperTop - 16);
    ctx.textAlign = "right";
    ctx.fillText("Fear Score · 0–100", geometry.width - right, upperTop - 16);
    ctx.textAlign = "left";
    ctx.fillText("거래대금 · 조원", left, lowerTop - 15);
    ctx.textBaseline = "alphabetic";

    const kospiValues = rows.map((row) => row.kospi_close);
    const min = Math.min(...kospiValues);
    const max = Math.max(...kospiValues);
    const span = max - min || Math.max(1, Math.abs(max) * 0.08);
    const minScale = min - span * 0.08;
    const maxScale = max + span * 0.08;
    ctx.textAlign = "right";
    for (let tick = 0; tick <= 4; tick += 1) {
      const value = maxScale - (maxScale - minScale) * tick / 4;
      const y = upperTop + (upperBottom - upperTop) * tick / 4;
      ctx.fillText(formatNumber(value, 0), left - 8, y + 3);
    }
    ctx.textAlign = "left";
    for (let tick = 0; tick <= 4; tick += 1) {
      const value = 100 - 25 * tick;
      const y = upperTop + (upperBottom - upperTop) * tick / 4;
      ctx.fillText(String(value), geometry.width - right + 8, y + 3);
    }
    const maxTrading = Math.max(...rows.map((row) => row.trading_value), 0) / 1000000000000;
    ctx.textAlign = "right";
    for (let tick = 0; tick <= 2; tick += 1) {
      const value = maxTrading * (1 - tick / 2);
      const y = lowerTop + (lowerBottom - lowerTop) * tick / 2;
      ctx.fillText(value.toFixed(0), left - 8, y + 3);
    }
    ctx.textAlign = "left";
    return { minScale, maxScale, maxTrading };
  }

  function xFor(index, geometry, length) {
    if (length <= 1) return geometry.left + geometry.plotWidth / 2;
    return geometry.left + geometry.plotWidth * index / (length - 1);
  }

  function yFor(value, minimum, maximum, top, bottom) {
    const ratio = (value - minimum) / (maximum - minimum || 1);
    return bottom - Math.max(0, Math.min(1, ratio)) * (bottom - top);
  }

  function drawBands(ctx, rows, geometry) {
    const bands = buildRegimeBands(rows);
    const fallback = cssVariable("--surface-muted", "#f1f3f5");
    bands.forEach((band) => {
      const startX = band.start === 0
        ? geometry.left
        : (xFor(band.start - 1, geometry, rows.length) + xFor(band.start, geometry, rows.length)) / 2;
      const endX = band.end === rows.length - 1
        ? geometry.left + geometry.plotWidth
        : (xFor(band.end, geometry, rows.length) + xFor(band.end + 1, geometry, rows.length)) / 2;
      ctx.globalAlpha = band.regime === "UNKNOWN" ? 0.08 : 0.24;
      ctx.fillStyle = band.regime === "UNKNOWN" ? fallback : cssVariable(REGIME_COLORS[band.regime], fallback);
      ctx.fillRect(startX, geometry.upperTop, Math.max(1, endX - startX), geometry.lowerBottom - geometry.upperTop);
    });
    ctx.globalAlpha = 1;
  }

  function drawLine(ctx, rows, geometry, valueField, minimum, maximum, top, bottom, color, width) {
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();
    rows.forEach((row, index) => {
      const x = xFor(index, geometry, rows.length);
      const y = yFor(row[valueField], minimum, maximum, top, bottom);
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }

  function drawTradingBars(ctx, rows, geometry, maximum) {
    const barColor = cssVariable("--market-down-blue", "#2d63a5");
    const baseline = geometry.lowerBottom;
    const step = rows.length <= 1 ? geometry.plotWidth : geometry.plotWidth / (rows.length - 1);
    const barWidth = Math.max(0.8, Math.min(7, step * 0.66));
    ctx.fillStyle = barColor;
    ctx.globalAlpha = 0.52;
    rows.forEach((row, index) => {
      const x = xFor(index, geometry, rows.length);
      const value = row.trading_value / 1000000000000;
      const height = maximum > 0 ? (value / maximum) * geometry.lowerHeight : 0;
      ctx.fillRect(x - barWidth / 2, baseline - height, barWidth, Math.max(1, height));
    });
    ctx.globalAlpha = 1;
  }

  function drawDateTicks(ctx, rows, geometry) {
    if (!rows.length) return;
    const color = cssVariable("--ink-faint", "#8b9097");
    const count = geometry.width < 560 ? 3 : 5;
    ctx.fillStyle = color;
    ctx.font = "10px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "alphabetic";
    for (let tick = 0; tick < count; tick += 1) {
      const index = count === 1 ? 0 : Math.round((rows.length - 1) * tick / (count - 1));
      ctx.fillText(formatDate(rows[index].date), xFor(index, geometry, rows.length), geometry.height - 13);
    }
  }

  function drawCrosshair(ctx, rows, geometry) {
    if (state.hoverIndex == null || !rows[state.hoverIndex]) return;
    const row = rows[state.hoverIndex];
    const x = xFor(state.hoverIndex, geometry, rows.length);
    const kospiValues = rows.map((item) => item.kospi_close);
    const min = Math.min(...kospiValues);
    const max = Math.max(...kospiValues);
    const span = max - min || Math.max(1, Math.abs(max) * 0.08);
    const minScale = min - span * 0.08;
    const maxScale = max + span * 0.08;
    const guide = cssVariable("--line-strong", "#cdd2d8");
    ctx.strokeStyle = guide;
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(x, geometry.upperTop);
    ctx.lineTo(x, geometry.lowerBottom);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = cssVariable("--brand-red", "#9f1d2f");
    ctx.beginPath();
    ctx.arc(x, yFor(row.kospi_close, minScale, maxScale, geometry.upperTop, geometry.upperBottom), 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = cssVariable("--fear-line", "#4967b1");
    ctx.beginPath();
    ctx.arc(x, yFor(row.fear_score, 0, 100, geometry.upperTop, geometry.upperBottom), 4, 0, Math.PI * 2);
    ctx.fill();
  }

  function renderChart() {
    const canvas = byId("fear-chart");
    const wrap = byId("fear-chart-wrap");
    if (!canvas || !wrap || !state.selectedRows.length) return;
    const width = Math.max(1, wrap.clientWidth);
    const height = Math.max(420, canvas.clientHeight || 500);
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const geometry = chartGeometry(width, height);
    state.plot = geometry;
    const rows = state.selectedRows;
    drawBands(ctx, rows, geometry);
    const scales = drawGrid(ctx, geometry, rows);
    drawTradingBars(ctx, rows, geometry, scales.maxTrading);
    drawLine(ctx, rows, geometry, "kospi_close", scales.minScale, scales.maxScale, geometry.upperTop, geometry.upperBottom, cssVariable("--brand-red", "#9f1d2f"), 2.2);
    drawLine(ctx, rows, geometry, "fear_score", 0, 100, geometry.upperTop, geometry.upperBottom, cssVariable("--fear-line", "#4967b1"), 1.8);
    drawDateTicks(ctx, rows, geometry);
    drawCrosshair(ctx, rows, geometry);
  }

  function renderControls() {
    document.querySelectorAll("[data-fear-range]").forEach((button) => {
      const selected = button.dataset.fearRange === state.range;
      button.classList.toggle("is-active", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
    setText("fear-chart-range", RANGE_LABELS[state.range] || RANGE_LABELS.all);
    setText("fear-chart-status", `${RANGE_LABELS[state.range] || RANGE_LABELS.all} · ${formatNumber(state.selectedRows.length)}개 거래일`);
  }

  function selectRange(range) {
    if (!Object.prototype.hasOwnProperty.call(RANGE_LABELS, range)) return;
    state.range = range;
    state.selectedRows = filterRange(state.rows, range);
    state.hoverIndex = null;
    renderControls();
    hideTooltip();
    renderChart();
  }

  function nearestIndex(event) {
    if (!state.plot || !state.selectedRows.length) return null;
    const canvas = byId("fear-chart");
    const rect = canvas.getBoundingClientRect();
    const x = (event.clientX - rect.left) * state.plot.width / rect.width;
    const ratio = (x - state.plot.left) / state.plot.plotWidth;
    return Math.max(0, Math.min(state.selectedRows.length - 1, Math.round(ratio * (state.selectedRows.length - 1))));
  }

  function renderTooltip(row) {
    const tooltip = byId("fear-tooltip");
    if (!tooltip) return;
    tooltip.replaceChildren();
    tooltip.appendChild(createElement("strong", "fear-tooltip-date", formatDate(row.date)));
    tooltip.appendChild(createElement("span", "fear-tooltip-regime", `시장 상태 · ${regimeLabel(row.regime)}`));
    const values = [
      ["KOSPI", formatNumber(row.kospi_close, 2)],
      ["공포점수", formatScore(row.fear_score)],
      ["V-KOSPI", formatNumber(row.v_kospi200_close, 2)],
      ["거래대금", formatTradingValue(row.trading_value, true)],
    ];
    const list = createElement("dl", "fear-tooltip-list");
    values.forEach(([label, value]) => {
      list.appendChild(createElement("dt", null, label));
      list.appendChild(createElement("dd", null, value));
    });
    tooltip.appendChild(list);
  }

  function positionTooltip(index) {
    const tooltip = byId("fear-tooltip");
    const wrap = byId("fear-chart-wrap");
    const canvas = byId("fear-chart");
    if (!tooltip || !wrap || !canvas || !state.plot) return;
    const wrapRect = wrap.getBoundingClientRect();
    const canvasRect = canvas.getBoundingClientRect();
    const pointX = canvasRect.left - wrapRect.left + xFor(index, state.plot, state.selectedRows.length);
    const pointY = canvasRect.top - wrapRect.top + state.plot.upperTop;
    const tooltipWidth = tooltip.offsetWidth;
    const tooltipHeight = tooltip.offsetHeight;
    const maxLeft = Math.max(8, wrap.clientWidth - tooltipWidth - 8);
    const left = Math.max(8, Math.min(maxLeft, pointX - tooltipWidth / 2));
    const preferredTop = pointY - tooltipHeight - 14;
    const maxTop = Math.max(8, wrap.clientHeight - tooltipHeight - 8);
    const top = preferredTop < 8
      ? Math.min(maxTop, pointY + 18)
      : Math.min(maxTop, preferredTop);
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${Math.max(8, top)}px`;
  }

  function showTooltip(index) {
    if (index == null || !state.selectedRows[index]) return;
    state.hoverIndex = index;
    const tooltip = byId("fear-tooltip");
    if (!tooltip) return;
    renderTooltip(state.selectedRows[index]);
    tooltip.hidden = false;
    renderChart();
    positionTooltip(index);
  }

  function hideTooltip() {
    const tooltip = byId("fear-tooltip");
    if (tooltip) tooltip.hidden = true;
    state.hoverIndex = null;
    if (state.selectedRows.length) renderChart();
  }

  function initChartInteractions() {
    document.querySelectorAll("[data-fear-range]").forEach((button) => {
      button.addEventListener("click", () => selectRange(button.dataset.fearRange));
    });
    const canvas = byId("fear-chart");
    if (!canvas) return;
    canvas.addEventListener("pointermove", (event) => {
      if (event.pointerType === "mouse") showTooltip(nearestIndex(event));
    });
    canvas.addEventListener("pointerdown", (event) => {
      if (event.pointerType !== "mouse") showTooltip(nearestIndex(event));
    });
    canvas.addEventListener("pointerleave", (event) => {
      if (event.pointerType === "mouse") hideTooltip();
    });
    canvas.addEventListener("keydown", (event) => {
      if (!state.selectedRows.length) return;
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        const direction = event.key === "ArrowLeft" ? -1 : 1;
        const next = state.hoverIndex == null ? state.selectedRows.length - 1 : state.hoverIndex + direction;
        showTooltip(Math.max(0, Math.min(state.selectedRows.length - 1, next)));
      }
    });
    if (window.ResizeObserver) {
      const observer = new ResizeObserver(() => renderChart());
      observer.observe(byId("fear-chart-wrap"));
    } else {
      window.addEventListener("resize", renderChart);
    }
  }

  async function loadPayload() {
    const response = await fetch(PAYLOAD_URL, { cache: "no-store" });
    if (!response.ok) throw new Error("fear index request failed");
    const payload = await response.json();
    if (!validPayload(payload)) throw new Error("fear index schema is incomplete");
    const rows = normalizeRows(payload);
    if (!rows.length) throw new Error("fear index has no chartable rows");
    state.payload = payload;
    state.rows = rows;
    state.selectedRows = rows.slice();
    renderCurrent(payload.current);
    renderControls();
    renderChart();
  }

  initTheme();
  initChartInteractions();
  loadPayload().catch(() => {
    const error = byId("fear-error");
    if (error) error.hidden = false;
    setText("fear-chart-status", "공포 지수 데이터를 확인할 수 없습니다.");
  });
}());
