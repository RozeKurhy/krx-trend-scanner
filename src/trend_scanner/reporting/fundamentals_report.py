"""Pure F2/F3/F4 to Stock Report v0.5 fundamentals adapter.

No provider, raw filing, network, or filter calculation belongs in this module.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from trend_scanner.reporting.models import (
    FundamentalsAnnualRow,
    FundamentalsQuarterRow,
    FundamentalsSection,
    FundamentalsSummary,
)


READY = "READY"
PARTIAL = "PARTIAL"
DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
NOT_APPLICABLE = "NOT_APPLICABLE"
_NON_COMMON_ASSET_TYPES = {"ETF", "ETN", "PREFERRED", "SPAC", "REIT", "OTHER", "UNKNOWN"}
_QUARTER_SNAPSHOT = {"Q1": "Q1_END", "Q2": "H1_END", "Q3": "Q3_END", "Q4": "FY_END"}


def _text(value: Any) -> str:
    if value in (None, ""):
        return ""
    return str(getattr(value, "value", value)).strip()


def _as_of_value(value: Any) -> str | None:
    """Return a comparable ISO date without introducing a provider dependency."""
    if value in (None, ""):
        return None
    if hasattr(value, "date") and not isinstance(value, str):
        try:
            value = value.date()
        except (AttributeError, TypeError, ValueError):
            pass
    if hasattr(value, "isoformat") and not isinstance(value, str):
        try:
            return str(value.isoformat())[:10]
        except (AttributeError, TypeError, ValueError):
            pass
    text = _text(value).replace("/", "-")
    return text[:10] if text else None


def _number(value: Any) -> int | float | None:
    if value in (None, "", "-", "—", "–") or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _observations(result: Any) -> tuple[Any, ...]:
    source = result.result if hasattr(result, "result") and not hasattr(result, "observations") else result
    return tuple(getattr(source, "observations", ()) or ())


def _f2_observations(result: Any, name: str) -> tuple[Any, ...]:
    return tuple(getattr(result, name, ()) or ())


def _key(metric: Any, metric_type: Any, year: Any, period: Any) -> tuple[str, str, str, str]:
    return _text(metric), _text(metric_type), _text(year), _text(period).upper()


def _index_derived(result: Any, ticker: str, corp_code: str, family: str) -> tuple[dict[tuple[str, str, str, str], tuple[Any, ...]], list[dict[str, Any]]]:
    index: dict[tuple[str, str, str, str], list[Any]] = {}
    diagnostics: list[dict[str, Any]] = []
    saw_mismatch = False
    accepted = 0
    for item in _observations(result):
        item_ticker = _text(getattr(item, "ticker", ""))
        item_corp = _text(getattr(item, "corp_code", ""))
        item_family = _text(getattr(item, "company_family", ""))
        mismatch = item_ticker != ticker or (corp_code and item_corp and item_corp != corp_code) or (family and item_family and item_family != family)
        if mismatch:
            saw_mismatch = True
            continue
        accepted += 1
        index.setdefault(_key(getattr(item, "metric", ""), getattr(item, "metric_type", ""), getattr(item, "fiscal_year", ""), getattr(item, "fiscal_period", "")), []).append(item)
    if saw_mismatch and not accepted:
        diagnostics.append({
            "type": "IDENTITY_MISMATCH", "status": DATA_UNAVAILABLE,
            "reason": "F3_TARGET_OBSERVATIONS_NOT_FOUND", "target_ticker": ticker,
        })
    return {key: tuple(values) for key, values in index.items()}, diagnostics


def _index_f2(
    result: Any,
    name: str,
    *,
    ticker: str = "",
    corp_code: str = "",
    family: str = "",
    diagnostics: list[dict[str, Any]] | None = None,
) -> dict[tuple[str, str, str], tuple[Any, ...]]:
    index: dict[tuple[str, str, str], list[Any]] = {}
    saw_mismatch = False
    accepted = 0
    for item in _f2_observations(result, name):
        item_ticker = _text(getattr(item, "ticker", ""))
        item_corp = _text(getattr(item, "corp_code", ""))
        item_family = _text(getattr(item, "company_family", ""))
        mismatch = (ticker and item_ticker and item_ticker != ticker) or (corp_code and item_corp and item_corp != corp_code) or (family and item_family and item_family != family)
        if mismatch:
            saw_mismatch = True
            continue
        accepted += 1
        index.setdefault((_text(getattr(item, "metric", "")), _text(getattr(item, "fiscal_year", "")), _text(getattr(item, "fiscal_period", "")).upper()), []).append(item)
    if saw_mismatch and accepted == 0 and diagnostics is not None:
        diagnostics.append({"type": "IDENTITY_MISMATCH", "status": DATA_UNAVAILABLE, "reason": f"F2_{name.upper()}_TARGET_OBSERVATIONS_NOT_FOUND", "target_ticker": ticker})
    return {key: tuple(values) for key, values in index.items()}


def _target_f3_as_ofs(
    result: Any,
    *,
    ticker: str,
    corp_code: str,
    family: str,
) -> tuple[str, ...]:
    """Collect as-of values only from target F3 observations."""
    values: set[str] = set()
    for item in _observations(result):
        item_ticker = _text(getattr(item, "ticker", ""))
        item_corp = _text(getattr(item, "corp_code", ""))
        item_family = _text(getattr(item, "company_family", ""))
        if ticker and item_ticker != ticker:
            continue
        if corp_code and item_corp and item_corp != corp_code:
            continue
        if family and item_family and item_family != family:
            continue
        as_of = _as_of_value(getattr(item, "requested_as_of", None))
        if as_of:
            values.add(as_of)
    return tuple(sorted(values))


def _value(candidates: Iterable[Any], diagnostics: list[dict[str, Any]], *, label: str) -> int | float | None:
    values = tuple(candidates)
    ready = [item for item in values if _text(getattr(item, "resolution_status", DATA_UNAVAILABLE)) == READY and _number(getattr(item, "value", None)) is not None]
    if ready:
        return _number(getattr(ready[0], "value", None))
    if values:
        item = values[0]
        diagnostics.append({
            "type": "METRIC_UNAVAILABLE", "metric": label,
            "status": _text(getattr(item, "resolution_status", DATA_UNAVAILABLE)) or DATA_UNAVAILABLE,
            "reason": getattr(item, "reason", None) or "INPUT_NOT_READY",
        })
    else:
        diagnostics.append({"type": "METRIC_UNAVAILABLE", "metric": label, "status": DATA_UNAVAILABLE, "reason": "MISSING_REQUIRED_INPUT"})
    return None


def _f3_value(index: Mapping[tuple[str, str, str, str], tuple[Any, ...]], metric: str, metric_type: str, year: str, period: str, diagnostics: list[dict[str, Any]]) -> int | float | None:
    return _value(index.get(_key(metric, metric_type, year, period), ()), diagnostics, label=f"{metric}:{metric_type}:{year}{period}")


def _f2_value(index: Mapping[tuple[str, str, str], tuple[Any, ...]], metric: str, year: str, period: str, diagnostics: list[dict[str, Any]]) -> int | float | None:
    return _value(index.get((_text(metric), _text(year), _text(period).upper()), ()), diagnostics, label=f"{metric}:{year}{period}")


def _ready_number(candidates: Iterable[Any]) -> int | float | None:
    for item in candidates:
        if _text(getattr(item, "resolution_status", DATA_UNAVAILABLE)) == READY:
            value = _number(getattr(item, "value", None))
            if value is not None:
                return value
    return None


def _operating_income_yoy_status(
    f2_index: Mapping[tuple[str, str, str], tuple[Any, ...]],
    year: str,
    period: str,
    yoy_pct: int | float | None,
) -> str:
    current = _ready_number(f2_index.get(("operating_income", _text(year), _text(period).upper()), ()))
    try:
        prior_year = str(int(year) - 1)
    except (TypeError, ValueError):
        return "UNAVAILABLE"
    prior = _ready_number(f2_index.get(("operating_income", prior_year, _text(period).upper()), ()))
    if current is None or prior is None:
        return "UNAVAILABLE"
    if current > 0 and prior > 0:
        return "PERCENT" if yoy_pct is not None else "UNAVAILABLE"
    if prior > 0 and current < 0:
        return "TURNED_TO_LOSS"
    if prior < 0 and current > 0:
        return "TURNED_TO_PROFIT"
    if prior < 0 and current < 0:
        return "LOSS_CONTINUED"
    if prior == 0 and current == 0:
        return "ZERO_BASE"
    if prior == 0:
        return "ZERO_BASE"
    if current == 0:
        return "ZERO_CURRENT"
    return "UNAVAILABLE"


def _slot(slot: Any, *, identity: str, kind: str) -> tuple[str, str | None, str, str]:
    if slot is None:
        return DATA_UNAVAILABLE, "MISSING_PERIOD_SLOT", str(identity), kind
    return _text(getattr(slot, "status", DATA_UNAVAILABLE)) or DATA_UNAVAILABLE, getattr(slot, "reason", None), str(identity), kind


def _quarter_parts(identity: str) -> tuple[str, str] | None:
    text = _text(identity).upper()
    if "Q" not in text:
        return None
    year, quarter = text.split("Q", 1)
    if quarter not in {"1", "2", "3", "4"}:
        return None
    return year, f"Q{quarter}"


def _annual_rows(multi_period_result: Any, f2_index: Mapping[tuple[str, str], tuple[Any, ...]], derived_index: Mapping[tuple[str, str, str, str], tuple[Any, ...]], diagnostics: list[dict[str, Any]]) -> list[FundamentalsAnnualRow]:
    slots = tuple(getattr(multi_period_result, "annual_slots", ()) or ())[-5:]
    rows: list[FundamentalsAnnualRow] = []
    for slot in slots:
        year = _text(getattr(slot, "identity", ""))
        status, reason, _, _ = _slot(slot, identity=year, kind="annual")
        revenue = _f2_value(f2_index, "revenue", year, "FY", diagnostics)
        op_income = _f2_value(f2_index, "operating_income", year, "FY", diagnostics)
        net_income = _f2_value(f2_index, "net_income", year, "FY", diagnostics)
        operating_income_yoy = _f3_value(
            derived_index, "operating_income", "ANNUAL_YOY", year, "FY", diagnostics,
        )
        if revenue is None or op_income is None or net_income is None:
            if status == READY:
                status, reason = DATA_UNAVAILABLE, reason or "REQUIRED_METRIC_UNAVAILABLE"
        rows.append(FundamentalsAnnualRow(
            fiscal_year=year, status=status, reason=reason,
            revenue_krw=revenue,
            revenue_yoy_pct=_f3_value(derived_index, "revenue", "ANNUAL_YOY", year, "FY", diagnostics),
            operating_income_krw=op_income,
            operating_income_yoy_pct=operating_income_yoy,
            operating_margin_pct=_f3_value(derived_index, "operating_income", "OPERATING_MARGIN", year, "FY", diagnostics),
            net_income_krw=net_income,
            net_margin_pct=_f3_value(derived_index, "net_income", "NET_MARGIN", year, "FY", diagnostics),
            roe_pct=_f3_value(derived_index, "net_income", "ANNUAL_ROE", year, "FY", diagnostics),
            debt_ratio_pct=_f3_value(derived_index, "liabilities", "DEBT_RATIO", year, "FY_END", diagnostics),
            operating_income_yoy_status=_operating_income_yoy_status(
                f2_index, year, "FY",
                operating_income_yoy,
            ),
        ))
    return rows


def _quarter_rows(multi_period_result: Any, f2_index: Mapping[tuple[str, str], tuple[Any, ...]], derived_index: Mapping[tuple[str, str, str, str], tuple[Any, ...]], diagnostics: list[dict[str, Any]]) -> list[FundamentalsQuarterRow]:
    slots = tuple(getattr(multi_period_result, "quarter_slots", ()) or ())[-12:]
    rows: list[FundamentalsQuarterRow] = []
    for slot in slots:
        identity = _text(getattr(slot, "identity", ""))
        parts = _quarter_parts(identity)
        status, reason, _, _ = _slot(slot, identity=identity, kind="quarter")
        if parts is None:
            rows.append(FundamentalsQuarterRow(
                quarter=identity, status=DATA_UNAVAILABLE, reason="INVALID_PERIOD_IDENTITY",
                revenue_krw=None, revenue_yoy_pct=None, operating_income_krw=None,
                operating_income_yoy_pct=None, operating_margin_pct=None,
                net_income_krw=None, net_margin_pct=None, operating_cash_flow_krw=None,
            ))
            continue
        year, period = parts
        revenue = _f2_value(f2_index, "revenue", year, period, diagnostics)
        op_income = _f2_value(f2_index, "operating_income", year, period, diagnostics)
        net_income = _f2_value(f2_index, "net_income", year, period, diagnostics)
        ocf = _f2_value(f2_index, "operating_cash_flow", year, period, diagnostics)
        operating_income_yoy = _f3_value(
            derived_index, "operating_income", "QUARTERLY_YOY", year, period, diagnostics,
        )
        if revenue is None or op_income is None or net_income is None:
            if status == READY:
                status, reason = DATA_UNAVAILABLE, reason or "REQUIRED_METRIC_UNAVAILABLE"
        rows.append(FundamentalsQuarterRow(
            quarter=identity, status=status, reason=reason,
            revenue_krw=revenue,
            revenue_yoy_pct=_f3_value(derived_index, "revenue", "QUARTERLY_YOY", year, period, diagnostics),
            operating_income_krw=op_income,
            operating_income_yoy_pct=operating_income_yoy,
            operating_margin_pct=_f3_value(derived_index, "operating_income", "OPERATING_MARGIN", year, period, diagnostics),
            net_income_krw=net_income,
            net_margin_pct=_f3_value(derived_index, "net_income", "NET_MARGIN", year, period, diagnostics),
            operating_cash_flow_krw=ocf,
            operating_income_yoy_status=_operating_income_yoy_status(
                f2_index, year, period,
                operating_income_yoy,
            ),
        ))
    return rows


def _empty_summary(filter_result: Any = None, *, latest_fy: str | None = None, latest_quarter: str | None = None) -> FundamentalsSummary:
    return FundamentalsSummary(
        latest_fy=latest_fy, latest_quarter=latest_quarter,
        filter_status=_text(getattr(filter_result, "status", DATA_UNAVAILABLE)) or DATA_UNAVAILABLE,
        filter_passed=bool(getattr(filter_result, "passed", False)),
        filter_reasons=list(getattr(filter_result, "reasons", ()) or ()),
    )


def _snapshot_period(period: str) -> str | None:
    return _QUARTER_SNAPSHOT.get(period.upper())


def build_fundamentals_section(
    multi_period_result: Any,
    derived_metrics_result: Any,
    filter_result: Any,
    requested_as_of: Any = None,
    asset_type: Any = "COMMON",
) -> FundamentalsSection:
    """Adapt already-built F2/F3/F4 outputs into a JSON-native report section."""
    asset = _text(asset_type) or "COMMON"
    explicit_as_of = _as_of_value(requested_as_of)
    f2_as_of = _as_of_value(getattr(multi_period_result, "requested_as_of", None))
    f4_as_of = _as_of_value(getattr(filter_result, "requested_as_of", None))
    as_of = explicit_as_of or f2_as_of or f4_as_of
    if asset in _NON_COMMON_ASSET_TYPES:
        summary = _empty_summary(filter_result)
        return FundamentalsSection(asset == "COMMON" and "APPLICABLE" or "NOT_APPLICABLE", NOT_APPLICABLE, "ASSET_TYPE_NOT_APPLICABLE", as_of, _text(getattr(filter_result, "company_family", "")) or None, "KRW", NOT_APPLICABLE, False, [], summary)
    if filter_result is None:
        summary = _empty_summary()
        return FundamentalsSection("APPLICABLE", DATA_UNAVAILABLE, "FUNDAMENTALS_INPUT_NOT_PROVIDED", as_of, None, "KRW", DATA_UNAVAILABLE, False, [], summary)

    ticker = _text(getattr(filter_result, "ticker", ""))
    family = _text(getattr(filter_result, "company_family", "")) or _text(getattr(multi_period_result, "company_family", "")) or None
    filter_status = _text(getattr(filter_result, "status", DATA_UNAVAILABLE)) or DATA_UNAVAILABLE
    filter_passed = bool(getattr(filter_result, "passed", False))
    filter_reasons = list(getattr(filter_result, "reasons", ()) or ())
    diagnostics: list[dict[str, Any]] = []
    f2_ticker = _text(getattr(multi_period_result, "ticker", ""))
    if f2_ticker and ticker and f2_ticker != ticker:
        diagnostics.append({
            "type": "IDENTITY_MISMATCH", "status": DATA_UNAVAILABLE,
            "reason": "F2_F4_TICKER_MISMATCH", "f2_ticker": f2_ticker, "f4_ticker": ticker,
        })
        return FundamentalsSection(
            "APPLICABLE", DATA_UNAVAILABLE, "IDENTITY_MISMATCH", as_of, family, "KRW",
            DATA_UNAVAILABLE, False, filter_reasons, _empty_summary(filter_result), diagnostics=diagnostics,
        )
    # F4 is the authority for applicability.  A financial-company or explicit
    # NOT_APPLICABLE decision must be preserved even when the upstream F2
    # context carries a different/legacy company-family label.
    if family == "FINANCIAL" or filter_status == NOT_APPLICABLE:
        summary = _empty_summary(
            filter_result,
            latest_fy=_text(getattr(filter_result, "latest_fy", "")) or None,
            latest_quarter=_text(getattr(filter_result, "latest_quarter", "")) or None,
        )
        return FundamentalsSection(
            "NOT_APPLICABLE", NOT_APPLICABLE, "FINANCIAL_COMPANY", as_of,
            family, "KRW", filter_status, False, filter_reasons, summary,
        )
    f3_as_ofs = _target_f3_as_ofs(
        derived_metrics_result,
        ticker=ticker,
        corp_code=_text(getattr(multi_period_result, "corp_code", "")),
        family=family or "",
    )
    f3_as_of = f3_as_ofs[0] if len(f3_as_ofs) == 1 else None
    known_as_ofs = {
        value for value in (explicit_as_of, f2_as_of, f3_as_of, f4_as_of)
        if value is not None
    }
    if len(f3_as_ofs) > 1 or len(known_as_ofs) > 1:
        diagnostics.append({
            "type": "AS_OF_MISMATCH", "status": DATA_UNAVAILABLE,
            "f2_requested_as_of": f2_as_of, "f3_requested_as_of": f3_as_of,
            "f3_requested_as_of_values": list(f3_as_ofs),
            "f4_requested_as_of": f4_as_of, "requested_as_of": explicit_as_of,
        })
        summary = _empty_summary(filter_result, latest_fy=_text(getattr(filter_result, "latest_fy", "")) or None, latest_quarter=_text(getattr(filter_result, "latest_quarter", "")) or None)
        summary.filter_status = DATA_UNAVAILABLE
        summary.filter_passed = False
        return FundamentalsSection(
            "APPLICABLE", DATA_UNAVAILABLE, "AS_OF_MISMATCH", as_of, family,
            "KRW", DATA_UNAVAILABLE, False, filter_reasons, summary,
            diagnostics=diagnostics,
        )
    f2_family = _text(getattr(multi_period_result, "company_family", ""))
    if f2_family and family and f2_family != family:
        diagnostics.append({
            "type": "IDENTITY_MISMATCH", "status": DATA_UNAVAILABLE,
            "reason": "F2_F4_COMPANY_FAMILY_MISMATCH", "f2_company_family": f2_family,
            "f4_company_family": family,
        })
        return FundamentalsSection(
            "APPLICABLE", DATA_UNAVAILABLE, "IDENTITY_MISMATCH", as_of, family, "KRW",
            DATA_UNAVAILABLE, False, filter_reasons, _empty_summary(filter_result), diagnostics=diagnostics,
        )
    latest_fy = _text(getattr(filter_result, "latest_fy", "")) or None
    latest_quarter = _text(getattr(filter_result, "latest_quarter", "")) or None
    f2_quarters = _index_f2(
        multi_period_result, "quarters", ticker=ticker,
        corp_code=_text(getattr(multi_period_result, "corp_code", "")),
        family=family or "", diagnostics=diagnostics,
    )
    f2_annuals = _index_f2(
        multi_period_result, "annuals", ticker=ticker,
        corp_code=_text(getattr(multi_period_result, "corp_code", "")),
        family=family or "", diagnostics=diagnostics,
    )
    derived_index, identity_diagnostics = _index_derived(
        derived_metrics_result,
        ticker=ticker,
        corp_code=_text(getattr(multi_period_result, "corp_code", "")),
        family=family or "",
    )
    diagnostics.extend(identity_diagnostics)
    quarterly = _quarter_rows(multi_period_result, f2_quarters, derived_index, diagnostics)
    annual = _annual_rows(multi_period_result, f2_annuals, derived_index, diagnostics)

    summary = FundamentalsSummary(
        latest_fy=latest_fy,
        latest_quarter=latest_quarter,
        latest_fy_revenue_krw=_number(getattr(filter_result, "annual_revenue", None)),
        latest_4q_avg_revenue_krw=_number(getattr(filter_result, "quarterly_avg_revenue", None)),
        ttm_revenue_krw=None,
        ttm_operating_income_krw=None,
        ttm_net_income_krw=None,
        filter_status=filter_status, filter_passed=filter_passed, filter_reasons=filter_reasons,
    )
    endpoint_parts = _quarter_parts(latest_quarter or "")
    if endpoint_parts is not None:
        year, period = endpoint_parts
        summary.ttm_revenue_krw = _f3_value(derived_index, "revenue", "TTM", year, period, diagnostics)
        summary.ttm_operating_income_krw = _f3_value(derived_index, "operating_income", "TTM", year, period, diagnostics)
        summary.ttm_net_income_krw = _f3_value(derived_index, "net_income", "TTM", year, period, diagnostics)
        summary.ttm_operating_cash_flow_krw = _f3_value(derived_index, "operating_cash_flow", "TTM", year, period, diagnostics)
        summary.ttm_operating_margin_pct = _f3_value(derived_index, "operating_income", "TTM_OPERATING_MARGIN", year, period, diagnostics)
        summary.ttm_net_margin_pct = _f3_value(derived_index, "net_income", "TTM_NET_MARGIN", year, period, diagnostics)
        summary.ttm_operating_cash_flow_margin_pct = _f3_value(derived_index, "operating_cash_flow", "TTM_OPERATING_CASH_FLOW_MARGIN", year, period, diagnostics)
        summary.ttm_roe_pct = _f3_value(derived_index, "net_income", "TTM_ROE", year, period, diagnostics)
        snapshot = _snapshot_period(period)
        if snapshot:
            summary.latest_debt_ratio_pct = _f3_value(derived_index, "liabilities", "DEBT_RATIO", year, snapshot, diagnostics)

    core_window_ready = (
        len(quarterly) == 12 and len(annual) == 5
        and all(
            row.status == READY
            and row.revenue_krw is not None
            and row.operating_income_krw is not None
            and row.net_income_krw is not None
            for row in (*quarterly, *annual)
        )
    )
    core_available = (
        summary.ttm_revenue_krw is not None
        and summary.ttm_operating_income_krw is not None
        and summary.ttm_net_income_krw is not None
        and core_window_ready
    )
    if filter_status == DATA_UNAVAILABLE or (not core_available and not quarterly and not annual):
        data_status = DATA_UNAVAILABLE
        reason = "F4_FILTER_OR_CORE_UNAVAILABLE" if filter_status != DATA_UNAVAILABLE else "F4_DATA_UNAVAILABLE"
    elif not core_available:
        data_status = PARTIAL
        reason = "DISPLAY_WINDOW_PARTIAL" if quarterly or annual else "F4_FILTER_OR_CORE_UNAVAILABLE"
    else:
        data_status = READY
        reason = None
    return FundamentalsSection(
        "APPLICABLE", data_status, reason, as_of, family, "KRW",
        filter_status, filter_passed, filter_reasons, summary,
        quarterly=quarterly, annual=annual, diagnostics=diagnostics,
    )


def fundamentals_executive_bullet(section: FundamentalsSection | None) -> str | None:
    if section is None:
        return None
    if section.data_status == NOT_APPLICABLE:
        return "펀더멘털: NOT_APPLICABLE (일반기업 Fundamentals V1 적용 대상 아님)"
    if section.data_status == DATA_UNAVAILABLE:
        detail = section.reason or section.filter_status
        return f"펀더멘털: DATA_UNAVAILABLE ({detail})"
    summary = section.summary
    fy = _format_eok(summary.latest_fy_revenue_krw)
    oi = _format_eok(summary.ttm_operating_income_krw)
    ni = _format_eok(summary.ttm_net_income_krw)
    return f"펀더멘털: Filter {summary.filter_status}, 최근 FY 매출 {fy}, TTM 영업이익 {oi}, TTM 순이익 {ni}."


def _format_eok(value: int | float | None) -> str:
    return "N/A" if value is None else f"{value / 100_000_000:,.1f}억원"
