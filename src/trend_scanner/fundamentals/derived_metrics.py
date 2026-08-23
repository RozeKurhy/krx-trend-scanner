"""Pure derived metrics over canonical periodization observations.

This module intentionally knows nothing about OpenDART, XBRL, FilingRegistry,
or PITResolver.  Its only authority is a :class:`PeriodizationResult` (or its
canonical observations), so unavailable and ambiguous periodization results
are never silently turned into zeros.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Iterable, Mapping

from .period_models import PeriodizationResult, PeriodizedFinancialObservation, READY


DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
PERIOD_AMBIGUOUS = "PERIOD_AMBIGUOUS"
QUARTERS = ("Q1", "Q2", "Q3", "Q4")
QUARTER_NUMBER = {period: index for index, period in enumerate(QUARTERS, 1)}
FLOW_METRICS = ("revenue", "operating_income", "net_income", "operating_cash_flow")
MARGIN_METRICS = {
    "operating_income": "OPERATING_MARGIN",
    "net_income": "NET_MARGIN",
    "operating_cash_flow": "OPERATING_CASH_FLOW_MARGIN",
}
GROWTH_METRICS = {
    "revenue": "REVENUE_GROWTH",
    "operating_income": "OPERATING_INCOME_GROWTH",
    "net_income": "NET_INCOME_GROWTH",
    "operating_cash_flow": "OPERATING_CASH_FLOW_GROWTH",
}


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10].replace("/", "-"))
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float | int | None:
    if value in (None, "", "-", "—", "–") or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _year_number(year: str) -> int | None:
    try:
        return int(str(year)[:4])
    except (TypeError, ValueError):
        return None


def _quarter_index(year: str, period: str) -> int | None:
    number = _year_number(year)
    quarter = QUARTER_NUMBER.get(period)
    return number * 4 + quarter if number is not None and quarter else None


def _value_ready(item: PeriodizedFinancialObservation | None) -> bool:
    return bool(item and item.resolution_status == READY and _number(item.value) is not None)


class DerivedMetricsError(ValueError):
    """Raised when the derived metrics input is not canonical periodization."""


class DerivedMetricObservation:
    """One auditable derived metric observation."""

    __slots__ = (
        "ticker", "corp_code", "company_family", "fiscal_year", "fiscal_period",
        "metric", "metric_type", "value", "unit", "resolution_status", "reason",
        "period_end", "source_rcept_nos", "source_rcept_dts", "source_sha256s",
        "metadata",
    )

    def __init__(self, ticker: str, corp_code: str, company_family: str, fiscal_year: str,
                 fiscal_period: str, metric: str, metric_type: str,
                 value: float | int | str | None, *, unit: str = "VALUE",
                 resolution_status: str = READY, reason: str | None = None,
                 period_end: str | None = None, source_rcept_nos: Iterable[str] = (),
                 source_rcept_dts: Iterable[str] = (), source_sha256s: Iterable[str] = (),
                 metadata: Mapping[str, Any] | None = None):
        self.ticker = ticker
        self.corp_code = corp_code
        self.company_family = company_family
        self.fiscal_year = fiscal_year
        self.fiscal_period = fiscal_period
        self.metric = metric
        self.metric_type = metric_type
        self.value = value
        self.unit = unit
        self.resolution_status = resolution_status
        self.reason = reason
        self.period_end = period_end
        self.source_rcept_nos = tuple(source_rcept_nos)
        self.source_rcept_dts = tuple(source_rcept_dts)
        self.source_sha256s = tuple(source_sha256s)
        self.metadata = dict(metadata or {})

    @property
    def kind(self) -> str:
        return self.metric_type

    @property
    def metric_name(self) -> str:
        return self.metric_type

    @property
    def status(self) -> str:
        return self.resolution_status

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker, "corp_code": self.corp_code,
            "company_family": self.company_family, "fiscal_year": self.fiscal_year,
            "fiscal_period": self.fiscal_period, "period_end": self.period_end,
            "metric": self.metric, "metric_type": self.metric_type,
            "metric_name": self.metric_type, "value": self.value, "unit": self.unit,
            "resolution_status": self.resolution_status, "status": self.resolution_status,
            "reason": self.reason, "source_rcept_nos": list(self.source_rcept_nos),
            "source_rcept_dts": list(self.source_rcept_dts),
            "source_sha256s": list(self.source_sha256s), "metadata": dict(self.metadata),
        }

    def __repr__(self) -> str:
        return (f"DerivedMetricObservation(metric={self.metric!r}, metric_type={self.metric_type!r}, "
                f"fiscal_year={self.fiscal_year!r}, fiscal_period={self.fiscal_period!r}, value={self.value!r})")


class DerivedMetricsResult:
    """Immutable-ish result container with convenient metric filtering."""

    def __init__(self, observations: Iterable[DerivedMetricObservation] = (),
                 diagnostics: Iterable[Mapping[str, Any]] = ()):
        self.observations = tuple(observations)
        self.diagnostics = tuple(dict(item) for item in diagnostics)

    def __iter__(self):
        return iter(self.observations)

    def __len__(self) -> int:
        return len(self.observations)

    def filter(self, *, metric: str | None = None, metric_type: str | None = None,
               fiscal_year: str | None = None, fiscal_period: str | None = None,
               status: str | None = None) -> tuple[DerivedMetricObservation, ...]:
        return tuple(item for item in self.observations
                     if (metric is None or item.metric == metric)
                     and (metric_type is None or item.metric_type == metric_type)
                     and (fiscal_year is None or item.fiscal_year == str(fiscal_year))
                     and (fiscal_period is None or item.fiscal_period == fiscal_period)
                     and (status is None or item.resolution_status == status))

    def get(self, metric: str, metric_type: str, fiscal_year: str,
            fiscal_period: str) -> DerivedMetricObservation | None:
        return next(iter(self.filter(metric=metric, metric_type=metric_type,
                                     fiscal_year=fiscal_year, fiscal_period=fiscal_period)), None)

    def to_dict(self) -> dict[str, Any]:
        return {"observations": [item.to_dict() for item in self.observations],
                "diagnostics": [dict(item) for item in self.diagnostics]}


class DerivedMetricsEngine:
    """Calculate growth, TTM, margins, trends, and transitions from PIT facts."""

    def derive(self, source: PeriodizationResult | Iterable[PeriodizedFinancialObservation]) -> DerivedMetricsResult:
        observations = self._coerce(source)
        selected = self._select_periods(observations)
        output: list[DerivedMetricObservation] = []
        diagnostics: list[Mapping[str, Any]] = []
        for group_key, periods in sorted(selected.items()):
            ticker, corp_code, family, metric = group_key
            if metric not in FLOW_METRICS:
                continue
            output.extend(self._growth_metrics(group_key, periods))
            output.extend(self._ttm_metrics(group_key, periods))
            output.extend(self._margin_metrics(group_key, selected))
            output.extend(self._margin_expansion_metrics(group_key, selected))
            output.extend(self._transition_metrics(group_key, periods))
            output.extend(self._trend_metrics(group_key, periods))
        output.sort(key=lambda item: (item.ticker, item.metric, item.fiscal_year,
                                      item.fiscal_period, item.metric_type))
        return DerivedMetricsResult(output, diagnostics)

    def calculate(self, source: PeriodizationResult | Iterable[PeriodizedFinancialObservation]) -> DerivedMetricsResult:
        return self.derive(source)

    def compute(self, source: PeriodizationResult | Iterable[PeriodizedFinancialObservation]) -> DerivedMetricsResult:
        return self.derive(source)

    @staticmethod
    def _coerce(source: Any) -> tuple[PeriodizedFinancialObservation, ...]:
        if isinstance(source, PeriodizationResult):
            values = source.observations
        elif hasattr(source, "result") and isinstance(source.result, PeriodizationResult):
            values = source.result.observations
        else:
            values = tuple(source or ())
        if any(not isinstance(item, PeriodizedFinancialObservation) for item in values):
            raise DerivedMetricsError("DerivedMetricsEngine requires PeriodizedFinancialObservation inputs")
        return tuple(values)

    @staticmethod
    def _select_periods(observations: Iterable[PeriodizedFinancialObservation]):
        grouped: dict[tuple[str, str, str, str], list[PeriodizedFinancialObservation]] = defaultdict(list)
        for item in observations:
            if item.metric not in FLOW_METRICS or item.fiscal_period not in (*QUARTERS, "FY"):
                continue
            grouped[(item.ticker, item.corp_code, item.company_family, item.metric)].append(item)
        selected: dict[tuple[str, str, str, str], dict[tuple[str, str], PeriodizedFinancialObservation | None]] = {}
        for key, values in grouped.items():
            candidates: dict[tuple[str, str], list[PeriodizedFinancialObservation]] = defaultdict(list)
            for value in values:
                candidates[(str(value.fiscal_year), value.fiscal_period)].append(value)
            periods: dict[tuple[str, str], PeriodizedFinancialObservation | None] = {}
            for period_key, period_values in candidates.items():
                ready = [item for item in period_values if _value_ready(item)]
                if not ready:
                    # Keep a single unavailable/ambiguous observation so derived
                    # output retains the canonical fiscal context and fail-closed
                    # status instead of manufacturing a zero.
                    latest_dt = max((_parse_date(item.anchor_rcept_dt) or date.min) for item in period_values)
                    latest = [item for item in period_values
                              if (_parse_date(item.anchor_rcept_dt) or date.min) == latest_dt]
                    periods[period_key] = latest[0] if len({item.anchor_rcept_no for item in latest}) == 1 else None
                    continue
                latest_dt = max((_parse_date(item.anchor_rcept_dt) or date.min) for item in ready)
                latest = [item for item in ready if (_parse_date(item.anchor_rcept_dt) or date.min) == latest_dt]
                periods[period_key] = latest[0] if len({item.anchor_rcept_no for item in latest}) == 1 else None
            selected[key] = periods
        return selected

    @staticmethod
    def _source(items: Iterable[PeriodizedFinancialObservation | None]) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        nos: list[str] = []
        dts: list[str] = []
        shas: list[str] = []
        seen: set[tuple[str, str, str]] = set()
        for item in items:
            if item is None:
                continue
            for no, dt, sha in zip(item.source_rcept_nos, item.source_rcept_dts, item.source_sha256s):
                triple = (no, dt, sha)
                if triple not in seen:
                    seen.add(triple)
                    nos.append(no); dts.append(dt); shas.append(sha)
            if not item.source_rcept_nos:
                triple = (item.anchor_rcept_no, item.anchor_rcept_dt, "")
                if triple not in seen:
                    seen.add(triple)
                    nos.append(triple[0]); dts.append(triple[1]); shas.append(triple[2])
        return tuple(nos), tuple(dts), tuple(shas)

    @staticmethod
    def _period_context(group_key, current: PeriodizedFinancialObservation | None,
                        *, metric_type: str, value: Any, unit: str,
                        status: str = READY, reason: str | None = None,
                        sources: Iterable[PeriodizedFinancialObservation | None] = (),
                        metadata: Mapping[str, Any] | None = None) -> DerivedMetricObservation:
        ticker, corp_code, family, metric = group_key
        source_items = tuple(sources)
        nos, dts, shas = DerivedMetricsEngine._source(source_items)
        return DerivedMetricObservation(
            ticker, corp_code, family, str(current.fiscal_year) if current else "",
            current.fiscal_period if current else "", metric, metric_type, value,
            unit=unit, resolution_status=status, reason=reason,
            period_end=current.period_end if current else None,
            source_rcept_nos=nos, source_rcept_dts=dts, source_sha256s=shas,
            metadata=metadata,
        )

    @staticmethod
    def _rate(current: PeriodizedFinancialObservation | None, prior: PeriodizedFinancialObservation | None,
              group_key, metric_type: str, *, sources=()) -> DerivedMetricObservation:
        if not _value_ready(current):
            return DerivedMetricsEngine._period_context(group_key, current, metric_type=metric_type, value=None,
                                                        unit="PERCENT", status=DATA_UNAVAILABLE,
                                                        reason="CURRENT_OBSERVATION_UNAVAILABLE", sources=sources or (current,))
        if not _value_ready(prior):
            return DerivedMetricsEngine._period_context(group_key, current, metric_type=metric_type, value=None,
                                                        unit="PERCENT", status=DATA_UNAVAILABLE,
                                                        reason="MISSING_PRIOR_PERIOD", sources=sources or (current, prior))
        prior_value = _number(prior.value)
        if prior_value == 0:
            return DerivedMetricsEngine._period_context(group_key, current, metric_type=metric_type, value=None,
                                                        unit="PERCENT", status=DATA_UNAVAILABLE,
                                                        reason="PRIOR_VALUE_ZERO", sources=sources or (current, prior))
        value = ((_number(current.value) - prior_value) / abs(prior_value)) * 100
        return DerivedMetricsEngine._period_context(group_key, current, metric_type=metric_type, value=value,
                                                    unit="PERCENT", sources=sources or (current, prior))

    def _growth_metrics(self, group_key, periods):
        metric = group_key[-1]
        output: list[DerivedMetricObservation] = []
        growth_type = GROWTH_METRICS[metric]
        for (year, period), current in sorted(periods.items(), key=lambda item: (_year_number(item[0][0]) or 0, item[0][1])):
            if current is None:
                continue
            if period in QUARTERS:
                prior = periods.get((str((_year_number(year) or 0) - 1), period))
                output.append(self._rate(current, prior, group_key, "QUARTERLY_YOY"))
                output.append(self._rate(current, prior, group_key, growth_type))
            elif period == "FY":
                prior = periods.get((str((_year_number(year) or 0) - 1), "FY"))
                output.append(self._rate(current, prior, group_key, "ANNUAL_YOY"))
                output.append(self._rate(current, prior, group_key, growth_type, sources=(current, prior)))
        return output

    def _ttm_metrics(self, group_key, periods):
        output: list[DerivedMetricObservation] = []
        quarters = {index: item for (year, period), item in periods.items()
                    if period in QUARTERS
                    for index in [_quarter_index(year, period)]}
        ttm: dict[int, DerivedMetricObservation] = {}
        for index, current in sorted(quarters.items()):
            source_items = [quarters.get(index - offset) for offset in (3, 2, 1, 0)]
            if any(not _value_ready(item) for item in source_items):
                if not _value_ready(current):
                    continue
                output.append(self._period_context(group_key, current, metric_type="TTM", value=None,
                                                   unit="VALUE", status=DATA_UNAVAILABLE,
                                                   reason="MISSING_FOUR_QUARTER_WINDOW", sources=source_items))
                continue
            value = sum(_number(item.value) for item in source_items)
            ttm_item = self._period_context(group_key, current, metric_type="TTM", value=value,
                                             unit="VALUE", sources=source_items)
            ttm[index] = ttm_item
            output.append(ttm_item)
        for index, current_ttm in sorted(ttm.items()):
            prior_ttm = ttm.get(index - 4)
            current_obs = quarters[index]
            if prior_ttm is None:
                output.append(self._period_context(group_key, current_obs, metric_type="TTM_YOY", value=None,
                                                   unit="PERCENT", status=DATA_UNAVAILABLE,
                                                   reason="MISSING_PRIOR_TTM", sources=(current_obs,)))
            else:
                value = ((_number(current_ttm.value) - _number(prior_ttm.value)) / abs(_number(prior_ttm.value)) * 100
                         if _number(prior_ttm.value) != 0 else None)
                output.append(self._period_context(
                    group_key, current_obs, metric_type="TTM_YOY", value=value, unit="PERCENT",
                    status=READY if value is not None else DATA_UNAVAILABLE,
                    reason=None if value is not None else "PRIOR_TTM_ZERO",
                    sources=(current_obs, quarters.get(index - 4)),
                ))
        return output

    def _margin_metrics(self, group_key, selected):
        metric = group_key[-1]
        if metric not in MARGIN_METRICS:
            return []
        revenue_key = group_key[:-1] + ("revenue",)
        revenue_periods = selected.get(revenue_key, {})
        numerator_periods = selected.get(group_key, {})
        if not revenue_periods:
            return []
        output: list[DerivedMetricObservation] = []
        for period_key in sorted(set(revenue_periods) | set(numerator_periods), key=lambda item: (_year_number(item[0]) or 0, item[1])):
            revenue = revenue_periods.get(period_key)
            numerator = numerator_periods.get(period_key)
            current = numerator or revenue
            if not _value_ready(numerator) or not _value_ready(revenue):
                output.append(self._period_context(
                    group_key, current, metric_type=MARGIN_METRICS[metric], value=None, unit="PERCENT",
                    status=DATA_UNAVAILABLE, reason="MARGIN_INPUT_UNAVAILABLE", sources=(numerator, revenue),
                ))
                continue
            denominator = _number(revenue.value)
            value = (_number(numerator.value) / denominator * 100) if denominator else None
            output.append(self._period_context(
                group_key, numerator, metric_type=MARGIN_METRICS[metric], value=value, unit="PERCENT",
                status=READY if value is not None else DATA_UNAVAILABLE,
                reason=None if value is not None else "REVENUE_ZERO", sources=(numerator, revenue),
            ))
        return output

    def _transition_metrics(self, group_key, periods):
        if group_key[-1] not in {"operating_income", "net_income"}:
            return []
        output: list[DerivedMetricObservation] = []
        for (year, period), current in sorted(periods.items(), key=lambda item: (_year_number(item[0][0]) or 0, item[0][1])):
            if period not in QUARTERS:
                continue
            if current is None:
                continue
            prior = periods.get((str((_year_number(year) or 0) - 1), period))
            if not _value_ready(current) or not _value_ready(prior):
                output.append(self._period_context(group_key, current, metric_type="EARNINGS_TRANSITION", value=None,
                                                   unit="CLASSIFICATION", status=DATA_UNAVAILABLE,
                                                   reason="MISSING_PRIOR_PERIOD", sources=(current, prior)))
                continue
            left, right = _number(prior.value), _number(current.value)
            if left < 0 <= right:
                transition = "LOSS_TO_PROFIT"
            elif left >= 0 > right:
                transition = "PROFIT_TO_LOSS"
            elif left < 0 and right < 0:
                transition = "LOSS_NARROWING" if abs(right) < abs(left) else "LOSS_WIDENING" if abs(right) > abs(left) else "LOSS_UNCHANGED"
            else:
                transition = "PROFIT_GROWTH" if right > left else "PROFIT_DECLINE" if right < left else "PROFIT_UNCHANGED"
            output.append(self._period_context(group_key, current, metric_type="EARNINGS_TRANSITION", value=transition,
                                               unit="CLASSIFICATION", sources=(current, prior),
                                               metadata={"transition": transition}))
        return output

    def _margin_expansion_metrics(self, group_key, selected):
        """Compare each margin with the same fiscal period in the prior year."""
        metric = group_key[-1]
        if metric not in MARGIN_METRICS:
            return []
        revenue_periods = selected.get(group_key[:-1] + ("revenue",), {})
        numerator_periods = selected.get(group_key, {})
        output: list[DerivedMetricObservation] = []
        for year, period in sorted(set(revenue_periods) | set(numerator_periods),
                                   key=lambda item: (_year_number(item[0]) or 0, item[1])):
            current = numerator_periods.get((year, period))
            revenue = revenue_periods.get((year, period))
            prior_key = (str((_year_number(year) or 0) - 1), period)
            prior = numerator_periods.get(prior_key)
            prior_revenue = revenue_periods.get(prior_key)
            source = (current, revenue, prior, prior_revenue)
            if not (_value_ready(current) and _value_ready(revenue)
                    and _value_ready(prior) and _value_ready(prior_revenue)):
                if current is None and revenue is None:
                    continue
                output.append(self._period_context(
                    group_key, current or revenue, metric_type="MARGIN_EXPANSION_TREND",
                    value=None, unit="PERCENTAGE_POINTS", status=DATA_UNAVAILABLE,
                    reason="MISSING_COMPARABLE_MARGIN_PERIOD", sources=source,
                ))
                continue
            current_revenue = _number(revenue.value)
            prior_revenue_value = _number(prior_revenue.value)
            if current_revenue == 0 or prior_revenue_value == 0:
                output.append(self._period_context(
                    group_key, current, metric_type="MARGIN_EXPANSION_TREND",
                    value=None, unit="PERCENTAGE_POINTS", status=DATA_UNAVAILABLE,
                    reason="REVENUE_ZERO", sources=source,
                ))
                continue
            current_margin = _number(current.value) / current_revenue * 100
            prior_margin = _number(prior.value) / prior_revenue_value * 100
            delta = current_margin - prior_margin
            classification = "EXPANDING" if delta > 0 else "CONTRACTING" if delta < 0 else "FLAT"
            output.append(self._period_context(
                group_key, current, metric_type="MARGIN_EXPANSION_TREND", value=delta,
                unit="PERCENTAGE_POINTS", sources=source,
                metadata={"classification": classification, "current_margin": current_margin,
                          "prior_margin": prior_margin},
            ))
        return output

    def _trend_metrics(self, group_key, periods):
        output: list[DerivedMetricObservation] = []
        metric = group_key[-1]
        yoy: dict[int, DerivedMetricObservation] = {}
        for (year, period), current in periods.items():
            if period not in QUARTERS:
                continue
            prior = periods.get((str((_year_number(year) or 0) - 1), period))
            item = self._rate(current, prior, group_key, "QUARTERLY_YOY")
            index = _quarter_index(year, period)
            if index is not None:
                yoy[index] = item
        for index, current in sorted(yoy.items()):
            if current.resolution_status != READY:
                continue
            prior = yoy.get(index - 1)
            previous_value = _number(prior.value) if prior and prior.resolution_status == READY else None
            current_value = _number(current.value)
            if previous_value is None:
                continue
            delta = current_value - previous_value
            current_source = next((item for (year, period), item in periods.items()
                                   if _quarter_index(year, period) == index), None)
            previous_source = next((item for (year, period), item in periods.items()
                                    if _quarter_index(year, period) == index - 1), None)
            output.append(self._period_context(
                group_key, current_source,
                metric_type="YOY_GROWTH_ACCELERATION", value=delta, unit="PERCENTAGE_POINTS",
                sources=(current_source, previous_source),
            ))
        if metric == "operating_cash_flow":
            for index, current in sorted(yoy.items()):
                prior = yoy.get(index - 1)
                if not prior or current.resolution_status != READY or prior.resolution_status != READY:
                    continue
                current_value, prior_value = _number(current.value), _number(prior.value)
                trend = "IMPROVING" if current_value > prior_value else "DETERIORATING" if current_value < prior_value else "FLAT"
                source = next((item for (year, period), item in periods.items() if _quarter_index(year, period) == index), None)
                output.append(self._period_context(group_key, source, metric_type="OPERATING_CASH_FLOW_TREND",
                                                   value=trend, unit="CLASSIFICATION", sources=(source,),
                                                   metadata={"latest_yoy": current_value, "prior_yoy": prior_value}))
        # A consecutive run and margin expansion are derived from already
        # selected canonical periods; no raw provider access is possible here.
        run = 0
        for index, current in sorted(yoy.items()):
            if current.resolution_status == READY and _number(current.value) > 0:
                run += 1
                source = next((item for (year, period), item in periods.items() if _quarter_index(year, period) == index), None)
                output.append(self._period_context(group_key, source, metric_type="CONSECUTIVE_YOY_GROWTH",
                                                   value=run, unit="COUNT", sources=(source,),
                                                   metadata={"is_consecutive": run >= 2}))
            else:
                run = 0
        return output


def derive_metrics(source: PeriodizationResult | Iterable[PeriodizedFinancialObservation]) -> DerivedMetricsResult:
    return DerivedMetricsEngine().derive(source)


def calculate_derived_metrics(source: PeriodizationResult | Iterable[PeriodizedFinancialObservation]) -> DerivedMetricsResult:
    return derive_metrics(source)
