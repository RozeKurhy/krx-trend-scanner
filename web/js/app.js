(function () {
  "use strict";

  const HEALTH_URL = "./data/health.json";
  const STATUS_LABELS = {
    NORMAL: "정상",
    UPDATING: "업데이트 중",
    WAITING: "대기",
    CHECK_REQUIRED: "확인 필요",
    UNKNOWN: "확인 불가",
  };
  const REQUIRED_SECTIONS = ["market_data", "universe", "fundamentals", "stock_reports"];

  const byId = (id) => document.getElementById(id);
  const numberFormat = new Intl.NumberFormat("ko-KR");

  function safeStatus(value) {
    return Object.prototype.hasOwnProperty.call(STATUS_LABELS, value) ? value : "UNKNOWN";
  }

  function setStatus(element, value) {
    if (!element) return;
    const status = safeStatus(value);
    element.dataset.status = status;
    element.textContent = STATUS_LABELS[status];
    element.setAttribute("aria-label", STATUS_LABELS[status]);
  }

  function setText(id, value) {
    const element = byId(id);
    if (element) element.textContent = value == null ? "—" : String(value);
  }

  function formatNumber(value) {
    return Number.isFinite(Number(value)) ? numberFormat.format(Number(value)) : "—";
  }

  function formatPercent(value) {
    return Number.isFinite(Number(value)) ? `${Number(value).toFixed(1)}%` : "—";
  }

  function formatDate(value) {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}/.test(value)) return "—";
    return value.slice(0, 10).replaceAll("-", ".");
  }

  function formatDateTime(value) {
    if (typeof value !== "string") return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "—";
    return new Intl.DateTimeFormat("ko-KR", {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: "Asia/Seoul",
    }).format(date);
  }

  function statusDetail(section) {
    const status = safeStatus(section && section.status);
    return STATUS_LABELS[status];
  }

  function validateHealth(health) {
    return Boolean(
      health && typeof health === "object" &&
      REQUIRED_SECTIONS.every((section) => health[section] && typeof health[section] === "object")
    );
  }

  function renderReadiness(health) {
    const list = byId("readiness-list");
    if (!list) return;
    while (list.firstChild) list.removeChild(list.firstChild);

    [
      ["분석", health.analysis],
      ["백테스트", health.backtest],
    ].forEach(([name, section]) => {
      const item = document.createElement("li");
      item.className = "readiness-item";
      const copy = document.createElement("span");
      const title = document.createElement("span");
      title.textContent = name;
      copy.appendChild(title);
      if (section && section.reason) {
        const reason = document.createElement("small");
        reason.className = "readiness-reason";
        reason.textContent = section.reason;
        copy.appendChild(reason);
      }
      const status = document.createElement("span");
      status.className = "status-dot";
      setStatus(status, section && section.status);
      item.append(copy, status);
      list.appendChild(item);
    });
  }

  function renderSources(health) {
    const sourcePath = (section, child) => {
      if (!section || !section.source) return "—";
      const source = child ? section.source[child] : section.source;
      return source && source.path ? source.path : "—";
    };
    setText("market-source", sourcePath(health.market_data));
    setText("universe-source", sourcePath(health.universe));
    setText("fundamentals-source", sourcePath(health.fundamentals, "production_directory"));
  }

  function render(health) {
    const overall = safeStatus(health.overall_status);
    setStatus(byId("overall-status"), overall);
    setText("overall-detail", `마지막 생성 ${formatDateTime(health.generated_at)}`);

    const market = health.market_data;
    setStatus(byId("market-status"), market.status);
    setText("market-date", formatDate(market.latest_trading_date));
    setText("market-detail", `certified through · ${statusDetail(market)}`);

    const universe = health.universe;
    setStatus(byId("universe-status"), universe.status);
    setText("universe-count", formatNumber(universe.count));
    setText("universe-detail", `PIT ${formatDate(universe.snapshot_date)} · ${statusDetail(universe)}`);

    const fundamentals = health.fundamentals;
    setStatus(byId("fundamentals-status"), fundamentals.status);
    setText("fundamentals-count", `${formatNumber(fundamentals.completed)} / ${formatNumber(fundamentals.total)}`);
    setText("fundamentals-detail", `${formatNumber(fundamentals.remaining)}개 남음 · ${statusDetail(fundamentals)}`);
    setText("progress-percent", formatPercent(fundamentals.percentage));
    setText("progress-completed", `완료 ${formatNumber(fundamentals.completed)}`);
    setText("progress-remaining", `남음 ${formatNumber(fundamentals.remaining)}`);
    setText("progress-note", `요청 기준일 ${formatDate(fundamentals.requested_as_of)} · run ${fundamentals.run_status || "—"}`);
    const progress = Math.max(0, Math.min(100, Number(fundamentals.percentage)));
    const progressBar = byId("fundamentals-progress");
    if (progressBar) progressBar.setAttribute("aria-valuenow", String(progress));
    const fill = byId("fundamentals-progress-fill");
    if (fill) fill.style.width = `${progress}%`;

    const reports = health.stock_reports;
    setStatus(byId("reports-status"), reports.status);
    setText("reports-count", formatNumber(reports.existing_artifact_count));
    setText("reports-detail", reports.reason || statusDetail(reports));

    setText("generated-at", formatDateTime(health.generated_at));
    renderSources(health);
    renderReadiness(health);
  }

  function showError() {
    const error = byId("load-error");
    if (error) error.hidden = false;
    setStatus(byId("overall-status"), "CHECK_REQUIRED");
    setText("overall-detail", "정적 health.json을 확인해야 해.");
  }

  fetch(HEALTH_URL, { cache: "no-store" })
    .then((response) => {
      if (!response.ok) throw new Error("health.json request failed");
      return response.json();
    })
    .then((health) => {
      if (!validateHealth(health)) throw new Error("health.json schema is incomplete");
      render(health);
    })
    .catch(() => showError());
}());
