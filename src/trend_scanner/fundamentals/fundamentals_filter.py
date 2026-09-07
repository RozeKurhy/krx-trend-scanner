"""PIT-safe Fundamentals Filter V1 over the closed F2/F3 boundaries."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any, Iterable, Mapping

from .derived_metrics import DATA_UNAVAILABLE
from .period_models import PERIOD_AMBIGUOUS, READY


PASS = "PASS"
FILTERED_ANNUAL_REVENUE = "FILTERED_ANNUAL_REVENUE"
FILTERED_QUARTERLY_REVENUE = "FILTERED_QUARTERLY_REVENUE"
FILTERED_OPERATING_LOSS = "FILTERED_OPERATING_LOSS"
FILTERED_NET_LOSS = "FILTERED_NET_LOSS"
NOT_APPLICABLE = "NOT_APPLICABLE"
AS_OF_MISMATCH = "AS_OF_MISMATCH"
_FILTER_PRIORITY = (
    DATA_UNAVAILABLE,
    NOT_APPLICABLE,
    FILTERED_ANNUAL_REVENUE,
    FILTERED_QUARTERLY_REVENUE,
    FILTERED_OPERATING_LOSS,
    FILTERED_NET_LOSS,
    PASS,
)
_QUARTERS = ("Q1", "Q2", "Q3", "Q4")


def _number(value: Any) -> float | int | None:
    if value in (None, "", "-", "—", "–") or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _as_of(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(str(value)[:10].replace("/", "-")).isoformat()
    except (TypeError, ValueError):
        return str(value)


def _identity_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    return str(getattr(value, "value", value)).strip()


def _currency_text(value: Any) -> str:
    return _identity_text(value).upper()


def _year(value: Any) -> int | None:
    try:
        return int(str(value)[:4])
    except (TypeError, ValueError):
        return None


def _quarter_index(year: Any, period: Any) -> int | None:
    number = _year(year)
    text = str(period or "").upper().strip()
    if number is None or text not in _QUARTERS:
        return None
    return number * 4 + _QUARTERS.index(text) + 1


def _quarter_label(index: int | None) -> str | None:
    if index is None:
        return None
    year = (index - 1) // 4
    quarter = index - year * 4
    return f"{year}Q{quarter}"


def _observation_as_of(result: Any) -> str | None | object:
    explicit = getattr(result, "requested_as_of", None)
    if explicit not in (None, ""):
        return _as_of(explicit)
    values = {
        _as_of(getattr(item, "requested_as_of", None))
        for item in getattr(result, "observations", ())
        if getattr(item, "requested_as_of", None) not in (None, "")
    }
    if len(values) > 1:
        return _AS_OF_MISMATCH
    return next(iter(values), None)


_AS_OF_MISMATCH = object()


@dataclass(frozen=True)
class FundamentalsFilterConfig:
    """Thresholds for the general-company Fundamentals V1 filter."""

    annual_revenue_min: int | float = 50_000_000_000
    quarterly_avg_revenue_min: int | float = 10_000_000_000
    require_positive_ttm_operating_income: bool = True
    require_positive_ttm_net_income: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FundamentalsFilterResult:
    ticker: str
    requested_as_of: str | None
    company_family: str
    status: str
    passed: bool
    latest_fy: str | None
    latest_quarter: str | None
    annual_revenue: int | float | None
    quarterly_avg_revenue: float | None
    ttm_operating_income: int | float | None
    ttm_net_income: int | float | None
    thresholds: Mapping[str, Any]
    reasons: tuple[str, ...] = ()
    diagnostics: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "requested_as_of": self.requested_as_of,
            "company_family": self.company_family,
            "status": self.status,
            "passed": self.passed,
            "latest_fy": self.latest_fy,
            "latest_quarter": self.latest_quarter,
            "annual_revenue": self.annual_revenue,
            "quarterly_avg_revenue": self.quarterly_avg_revenue,
            "ttm_operating_income": self.ttm_operating_income,
            "ttm_net_income": self.ttm_net_income,
            "thresholds": dict(self.thresholds),
            "reasons": list(self.reasons),
            "diagnostics": [dict(item) for item in self.diagnostics],
        }


class FundamentalsFilter:
    """Evaluate only the four frozen Fundamentals V1 conditions."""

    def __init__(self, config: FundamentalsFilterConfig | None = None):
        self.config = config or FundamentalsFilterConfig()

    def evaluate(
        self,
        multi_period_result: Any,
        derived_metrics_result: Any,
        *,
        requested_as_of: Any = None,
    ) -> FundamentalsFilterResult:
        ticker = _identity_text(getattr(multi_period_result, "ticker", ""))
        family_value = getattr(multi_period_result, "company_family", "")
        family = _identity_text(family_value)
        target_corp_code = _identity_text(getattr(multi_period_result, "corp_code", ""))
        raw_latest_fy = getattr(multi_period_result, "latest_fy", None)
        raw_latest_quarter = getattr(multi_period_result, "latest_quarter", None)
        latest_fy = str(raw_latest_fy) if raw_latest_fy not in (None, "") else None
        latest_quarter = str(raw_latest_quarter) if raw_latest_quarter not in (None, "") else None
        diagnostics: list[Mapping[str, Any]] = []
        reasons: list[str] = []
        f2_as_of = _as_of(getattr(multi_period_result, "requested_as_of", None))
        f3_as_of = _observation_as_of(derived_metrics_result)
        explicit_as_of = _as_of(requested_as_of)
        as_of_values = (f2_as_of, None if f3_as_of is _AS_OF_MISMATCH else f3_as_of, explicit_as_of)
        known_as_of = {value for value in as_of_values if value is not None}
        as_of_mismatch = f3_as_of is _AS_OF_MISMATCH or len(known_as_of) > 1
        if (f2_as_of is None) != (f3_as_of is None):
            as_of_mismatch = True
        if as_of_mismatch:
            diagnostics.append({
                "type": AS_OF_MISMATCH,
                "f2_requested_as_of": f2_as_of,
                "f3_requested_as_of": None if f3_as_of is _AS_OF_MISMATCH else f3_as_of,
                "requested_as_of": explicit_as_of,
            })
            reasons.extend((DATA_UNAVAILABLE, AS_OF_MISMATCH))
            return self._result(
                ticker, explicit_as_of or f2_as_of, family, DATA_UNAVAILABLE, latest_fy,
                latest_quarter, None, None, None, None, reasons, diagnostics,
            )
        resolved_as_of = explicit_as_of or f2_as_of or (None if f3_as_of is _AS_OF_MISMATCH else f3_as_of)
        if not ticker:
            diagnostics.append({
                "type": "IDENTITY_MISMATCH", "required": True,
                "status": DATA_UNAVAILABLE, "reason": "F2_TICKER_MISSING",
            })
            return self._result(
                ticker, resolved_as_of, family, DATA_UNAVAILABLE, latest_fy, latest_quarter,
                None, None, None, None, (DATA_UNAVAILABLE,), diagnostics,
            )
        if family == "FINANCIAL":
            diagnostics.append({"type": "FINANCIAL_NOT_APPLICABLE"})
            return self._result(
                ticker, resolved_as_of, family, NOT_APPLICABLE, latest_fy, latest_quarter,
                None, None, None, None, (), diagnostics,
            )
        identity_diagnostics = self._wrapper_identity_diagnostics(
            derived_metrics_result, ticker=ticker, corp_code=target_corp_code, family=family,
        )
        if identity_diagnostics:
            diagnostics.extend(identity_diagnostics)
            return self._result(
                ticker, resolved_as_of, family, DATA_UNAVAILABLE, latest_fy, latest_quarter,
                None, None, None, None, (DATA_UNAVAILABLE,), diagnostics,
            )
        if family != "NON_FINANCIAL":
            diagnostics.append({"type": "COMPANY_FAMILY_UNSUPPORTED", "company_family": family})
            return self._result(
                ticker, resolved_as_of, family, DATA_UNAVAILABLE, latest_fy, latest_quarter,
                None, None, None, None, (DATA_UNAVAILABLE,), diagnostics,
            )

        annual_revenue, annual_diag = self._annual_revenue(multi_period_result, latest_fy)
        diagnostics.extend(annual_diag)
        quarter_endpoint, quarter_values, quarterly_avg, quarter_diag = self._quarter_revenue(multi_period_result)
        diagnostics.extend(quarter_diag)
        if quarter_endpoint is not None:
            latest_quarter = quarter_endpoint

        ttm_oi = ttm_ni = None
        oi_item = ni_item = None
        if self.config.require_positive_ttm_operating_income:
            oi_item, oi_diag = self._latest_ttm(
                derived_metrics_result, "operating_income",
                target_ticker=ticker, target_corp_code=target_corp_code, target_family=family,
            )
            diagnostics.extend(oi_diag)
            ttm_oi = _number(getattr(oi_item, "value", None)) if oi_item else None
        if self.config.require_positive_ttm_net_income:
            ni_item, ni_diag = self._latest_ttm(
                derived_metrics_result, "net_income",
                target_ticker=ticker, target_corp_code=target_corp_code, target_family=family,
            )
            diagnostics.extend(ni_diag)
            ttm_ni = _number(getattr(ni_item, "value", None)) if ni_item else None

        data_unavailable = any(
            item.get("required", False) and item.get("status") != READY
            for item in diagnostics
        )
        if quarter_endpoint is None or len(quarter_values) != 4:
            data_unavailable = True
        if self.config.require_positive_ttm_operating_income and oi_item is None:
            data_unavailable = True
        if self.config.require_positive_ttm_net_income and ni_item is None:
            data_unavailable = True
        if quarter_endpoint is not None:
            endpoint_map = {"quarter_revenue": quarter_endpoint}
            if oi_item is not None:
                endpoint_map["ttm_operating_income"] = self._observation_endpoint(oi_item)
            if ni_item is not None:
                endpoint_map["ttm_net_income"] = self._observation_endpoint(ni_item)
            if any(endpoint != quarter_endpoint for endpoint in endpoint_map.values()):
                diagnostics.append({"type": "ENDPOINT_MISMATCH", "endpoints": endpoint_map, "required": True, "status": DATA_UNAVAILABLE})
                data_unavailable = True

        if annual_revenue is not None and annual_revenue < self.config.annual_revenue_min:
            reasons.append(FILTERED_ANNUAL_REVENUE)
        if quarterly_avg is not None and quarterly_avg < self.config.quarterly_avg_revenue_min:
            reasons.append(FILTERED_QUARTERLY_REVENUE)
        if self.config.require_positive_ttm_operating_income and ttm_oi is not None and ttm_oi <= 0:
            reasons.append(FILTERED_OPERATING_LOSS)
        if self.config.require_positive_ttm_net_income and ttm_ni is not None and ttm_ni <= 0:
            reasons.append(FILTERED_NET_LOSS)
        if data_unavailable:
            reasons.insert(0, DATA_UNAVAILABLE)
        status = self._primary_status(reasons)
        return self._result(
            ticker, resolved_as_of, family, status, latest_fy, latest_quarter,
            annual_revenue, quarterly_avg, ttm_oi, ttm_ni, tuple(dict.fromkeys(reasons)), diagnostics,
        )

    def _annual_revenue(self, result: Any, latest_fy: str | None):
        if latest_fy is None:
            return None, [{"type": "ANNUAL_REVENUE_UNAVAILABLE", "required": True, "status": DATA_UNAVAILABLE, "reason": "LATEST_USABLE_FY_MISSING"}]
        slots = getattr(result, "annual_slots", ())
        slot = next((item for item in slots if str(getattr(item, "identity", "")) == latest_fy), None)
        if slots and (slot is None or str(getattr(slot, "status", DATA_UNAVAILABLE)) != READY):
            slot_status = str(getattr(slot, "status", DATA_UNAVAILABLE)) if slot is not None else DATA_UNAVAILABLE
            slot_reason = getattr(slot, "reason", None) or "LATEST_FY_NOT_READY"
            return None, [{"type": "ANNUAL_REVENUE_UNAVAILABLE", "required": True, "status": slot_status, "reason": slot_reason, "latest_fy": latest_fy}]
        candidates = [
            item for item in getattr(result, "annuals", ())
            if str(getattr(item, "fiscal_year", "")) == latest_fy
            and str(getattr(item, "fiscal_period", "")).upper() == "FY"
            and str(getattr(item, "metric", "")) == "revenue"
        ]
        item, status, reason = self._latest_ready(candidates)
        if item is None:
            return None, [{"type": "ANNUAL_REVENUE_UNAVAILABLE", "required": True, "status": status, "reason": reason or status, "latest_fy": latest_fy}]
        currency = _currency_text(getattr(item, "currency", None))
        if currency != "KRW":
            return None, [{
                "type": "NON_KRW_REVENUE", "required": True,
                "status": DATA_UNAVAILABLE, "reason": "NON_KRW_REVENUE",
                "currency": currency or None, "fiscal_year": latest_fy,
            }]
        return _number(item.value), [{"type": "ANNUAL_REVENUE_SOURCE", "required": True, "status": READY, "fiscal_year": latest_fy, "currency": currency}]

    def _quarter_revenue(self, result: Any):
        raw_expected = getattr(result, "latest_quarter", None)
        expected = str(raw_expected) if raw_expected not in (None, "") else None
        expected_index = self._parse_endpoint(expected)
        rows = [
            item for item in getattr(result, "quarters", ())
            if str(getattr(item, "metric", "")) == "revenue"
            and str(getattr(item, "fiscal_period", "")).upper() in _QUARTERS
            and str(getattr(item, "period_semantics", "")) == "STANDALONE_QUARTER"
        ]
        grouped: dict[int, list[Any]] = {}
        for item in rows:
            index = _quarter_index(getattr(item, "fiscal_year", None), getattr(item, "fiscal_period", None))
            if index is not None:
                grouped.setdefault(index, []).append(item)
        if expected_index is None:
            return None, (), None, [{"type": "QUARTER_REVENUE_UNAVAILABLE", "required": True, "status": DATA_UNAVAILABLE, "reason": "LATEST_QUARTER_MISSING"}]
        selected: list[Any] = []
        diagnostics: list[Mapping[str, Any]] = []
        for index in range(expected_index - 3, expected_index + 1):
            slot = next(
                (item for item in getattr(result, "quarter_slots", ())
                 if str(getattr(item, "identity", "")) == _quarter_label(index)),
                None,
            )
            slot_missing = set(getattr(slot, "missing_metrics", ()) or ()) if slot is not None else set()
            if (
                slot is not None
                and str(getattr(slot, "status", DATA_UNAVAILABLE)) != READY
                and (not slot_missing or "revenue" in slot_missing)
            ):
                diagnostics.append({
                    "type": "QUARTER_REVENUE_UNAVAILABLE", "required": True,
                    "status": str(getattr(slot, "status", DATA_UNAVAILABLE)),
                    "reason": getattr(slot, "reason", None) or "QUARTER_SLOT_NOT_READY",
                    "endpoint": _quarter_label(index),
                })
                continue
            item, status, reason = self._latest_ready(grouped.get(index, ()))
            if item is None:
                diagnostics.append({"type": "QUARTER_REVENUE_UNAVAILABLE", "required": True, "status": status, "reason": reason or status, "endpoint": _quarter_label(index)})
                continue
            selected.append(item)
        if len(selected) != 4:
            return _quarter_label(expected_index), tuple(), None, diagnostics
        latest_selected = max(_quarter_index(item.fiscal_year, item.fiscal_period) for item in selected)
        if latest_selected != expected_index:
            diagnostics.append({"type": "QUARTER_REVENUE_UNAVAILABLE", "required": True, "status": DATA_UNAVAILABLE, "reason": "LATEST_QUARTER_REVENUE_MISSING", "endpoint": expected})
            return _quarter_label(expected_index), tuple(), None, diagnostics
        values = tuple(_number(item.value) for item in selected)
        if any(value is None for value in values):
            diagnostics.append({"type": "QUARTER_REVENUE_UNAVAILABLE", "required": True, "status": DATA_UNAVAILABLE, "reason": "QUARTER_VALUE_MISSING", "endpoint": expected})
            return _quarter_label(expected_index), tuple(), None, diagnostics
        currencies = tuple(_currency_text(getattr(item, "currency", None)) for item in selected)
        if any(currency != "KRW" for currency in currencies):
            diagnostics.append({
                "type": "NON_KRW_REVENUE", "required": True,
                "status": DATA_UNAVAILABLE, "reason": "NON_KRW_REVENUE",
                "endpoint": expected, "currencies": list(currencies),
            })
            return _quarter_label(expected_index), tuple(), None, diagnostics
        bases = tuple(_identity_text(getattr(item, "fs_div_used", None)) for item in selected)
        if any(not basis for basis in bases) or len(set(bases)) != 1:
            diagnostics.append({
                "type": "REVENUE_BASIS_MISMATCH", "required": True,
                "status": DATA_UNAVAILABLE, "reason": "REVENUE_BASIS_MISMATCH",
                "endpoint": expected, "fs_div_used": list(bases),
            })
            return _quarter_label(expected_index), tuple(), None, diagnostics
        diagnostics.append({"type": "QUARTER_REVENUE_SOURCE", "required": True, "status": READY, "endpoint": expected})
        return _quarter_label(expected_index), values, sum(values) / 4, diagnostics

    def _latest_ttm(self, result: Any, metric: str, *, target_ticker: str,
                    target_corp_code: str, target_family: str):
        source = result.result if hasattr(result, "result") and not hasattr(result, "observations") else result
        all_candidates = [
            item for item in getattr(source, "observations", ())
            if str(getattr(item, "metric", "")) == metric
            and str(getattr(item, "metric_type", "")) == "TTM"
        ]
        candidates = []
        identity_mismatches: list[Mapping[str, Any]] = []
        for item in all_candidates:
            item_ticker = _identity_text(getattr(item, "ticker", ""))
            item_corp_code = _identity_text(getattr(item, "corp_code", ""))
            item_family = _identity_text(getattr(item, "company_family", ""))
            if item_ticker != target_ticker:
                identity_mismatches.append({
                    "type": "IDENTITY_MISMATCH", "metric": metric,
                    "required": True, "status": DATA_UNAVAILABLE,
                    "reason": "TTM_TICKER_MISMATCH", "target_ticker": target_ticker,
                    "observation_ticker": item_ticker or None,
                })
                continue
            if target_corp_code and item_corp_code and item_corp_code != target_corp_code:
                identity_mismatches.append({
                    "type": "IDENTITY_MISMATCH", "metric": metric,
                    "required": True, "status": DATA_UNAVAILABLE,
                    "reason": "TTM_CORP_CODE_MISMATCH", "target_corp_code": target_corp_code,
                    "observation_corp_code": item_corp_code,
                })
                continue
            if target_family and item_family != target_family:
                identity_mismatches.append({
                    "type": "IDENTITY_MISMATCH", "metric": metric,
                    "required": True, "status": DATA_UNAVAILABLE,
                    "reason": "TTM_COMPANY_FAMILY_MISMATCH", "target_family": target_family,
                    "observation_family": item_family,
                })
                continue
            candidates.append(item)
        if not candidates and identity_mismatches:
            return None, identity_mismatches
        item, status, reason = self._latest_ready(candidates, endpoint=True)
        if item is None:
            return None, [{"type": "TTM_INPUT_UNAVAILABLE", "metric": metric, "required": True, "status": status, "reason": reason or status}]
        return item, [{"type": "TTM_INPUT_SOURCE", "metric": metric, "required": True, "status": READY, "endpoint": self._observation_endpoint(item)}]

    @staticmethod
    def _wrapper_identity_diagnostics(result: Any, *, ticker: str, corp_code: str, family: str):
        if not hasattr(result, "result"):
            return []
        diagnostics: list[Mapping[str, Any]] = []
        checks = (
            ("ticker", ticker, _identity_text(getattr(result, "ticker", "")), "F3_TICKER_MISMATCH"),
            ("corp_code", corp_code, _identity_text(getattr(result, "corp_code", "")), "F3_CORP_CODE_MISMATCH"),
            ("company_family", family, _identity_text(getattr(result, "company_family", "")), "F3_COMPANY_FAMILY_MISMATCH"),
        )
        for field, expected, actual, reason in checks:
            if actual and expected and actual != expected:
                diagnostics.append({
                    "type": "IDENTITY_MISMATCH", "required": True,
                    "status": DATA_UNAVAILABLE, "reason": reason,
                    "field": field, "target": expected, "f3": actual,
                })
        return diagnostics

    @staticmethod
    def _latest_ready(candidates: Iterable[Any], *, endpoint: bool = False):
        values = tuple(candidates)
        if endpoint:
            keyed = [(_quarter_index(getattr(item, "fiscal_year", None), getattr(item, "fiscal_period", None)) or -1, item) for item in values]
            latest_key = max((key for key, _ in keyed), default=-1)
            latest_all = [item for key, item in keyed if key == latest_key]
        else:
            latest_date = max((str(getattr(item, "anchor_rcept_dt", "")) for item in values), default="")
            latest_all = [item for item in values if str(getattr(item, "anchor_rcept_dt", "")) == latest_date]
        ready = [item for item in latest_all if str(getattr(item, "resolution_status", DATA_UNAVAILABLE)) == READY and _number(getattr(item, "value", None)) is not None]
        not_ready = [item for item in latest_all if item not in ready]
        if not_ready:
            status = next((str(getattr(item, "resolution_status", DATA_UNAVAILABLE)) for item in not_ready), DATA_UNAVAILABLE)
            reason = next((getattr(item, "reason", None) for item in not_ready if getattr(item, "reason", None)), None)
            return None, status, reason or status
        if not ready:
            return None, DATA_UNAVAILABLE, "MISSING_REQUIRED_INPUT"
        latest = ready
        signatures = {(getattr(item, "anchor_rcept_no", None), getattr(item, "value", None), getattr(item, "currency", None), getattr(item, "fs_div_used", None)) for item in latest}
        if len(signatures) != 1:
            return None, PERIOD_AMBIGUOUS, "AMBIGUOUS_INPUT"
        return latest[0], READY, None

    @staticmethod
    def _parse_endpoint(value: Any) -> int | None:
        text = str(value or "").upper().strip()
        if "Q" not in text:
            return None
        year, quarter = text.split("Q", 1)
        return _quarter_index(year, f"Q{quarter}")

    @staticmethod
    def _observation_endpoint(item: Any) -> str | None:
        return _quarter_label(_quarter_index(getattr(item, "fiscal_year", None), getattr(item, "fiscal_period", None)))

    @staticmethod
    def _primary_status(reasons: Iterable[str]) -> str:
        values = set(reasons)
        return next((item for item in _FILTER_PRIORITY if item in values), PASS)

    def _result(self, ticker, requested_as_of, family, status, latest_fy, latest_quarter,
                annual_revenue, quarterly_avg, ttm_oi, ttm_ni, reasons, diagnostics):
        return FundamentalsFilterResult(
            ticker=ticker, requested_as_of=requested_as_of, company_family=family,
            status=status, passed=status == PASS, latest_fy=latest_fy,
            latest_quarter=latest_quarter, annual_revenue=annual_revenue,
            quarterly_avg_revenue=quarterly_avg, ttm_operating_income=ttm_oi,
            ttm_net_income=ttm_ni, thresholds=self.config.to_dict(),
            reasons=tuple(reasons), diagnostics=tuple(dict(item) for item in diagnostics),
        )


def evaluate_fundamentals_filter(
    multi_period_result: Any,
    derived_metrics_result: Any,
    *,
    config: FundamentalsFilterConfig | None = None,
    requested_as_of: Any = None,
) -> FundamentalsFilterResult:
    return FundamentalsFilter(config).evaluate(
        multi_period_result, derived_metrics_result, requested_as_of=requested_as_of,
    )
