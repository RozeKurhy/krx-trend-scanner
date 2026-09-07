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
INPUT_NOT_READY = "INPUT_NOT_READY"
UNDEFINED_BASE = "UNDEFINED_BASE"
NOT_APPLICABLE = "NOT_APPLICABLE"
BASIS_MISMATCH = "BASIS_MISMATCH"
CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
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
ANNUAL_ROE = "ANNUAL_ROE"
TTM_ROE = "TTM_ROE"
DEBT_RATIO = "DEBT_RATIO"
PERCENT = "PERCENT"
INSTANT_METRICS = frozenset({"equity", "liabilities"})
INSTANT_PERIODS = frozenset({"Q1_END", "H1_END", "Q3_END", "FY_END"})


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


def _normalise_as_of(value: Any) -> tuple[str | None, date | None]:
    if value in (None, ""):
        return None, None
    parsed = _parse_date(value)
    return (parsed.isoformat(), parsed) if parsed is not None else (str(value), None)


def _source_available_on(item: PeriodizedFinancialObservation | None) -> date | None:
    if item is None:
        return None
    return _parse_date(item.pit_available_from or item.anchor_rcept_dt)


class DerivedMetricsError(ValueError):
    """Raised when the derived metrics input is not canonical periodization."""


class DerivedMetricObservation:
    """One auditable derived metric observation."""

    __slots__ = (
        "ticker", "corp_code", "company_family", "fiscal_year", "fiscal_period",
        "metric", "metric_type", "value", "unit", "resolution_status", "reason",
        "period_end", "source_rcept_nos", "source_rcept_dts", "source_sha256s",
        "requested_as_of", "pit_available_from", "metadata",
    )

    def __init__(self, ticker: str, corp_code: str, company_family: str, fiscal_year: str,
                 fiscal_period: str, metric: str, metric_type: str,
                 value: float | int | str | None, *, unit: str = "VALUE",
                 resolution_status: str = READY, reason: str | None = None,
                 period_end: str | None = None, source_rcept_nos: Iterable[str] = (),
                 source_rcept_dts: Iterable[str] = (), source_sha256s: Iterable[str] = (),
                 requested_as_of: str | None = None, pit_available_from: str | None = None,
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
        self.requested_as_of = requested_as_of
        self.pit_available_from = pit_available_from
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
            "requested_as_of": self.requested_as_of,
            "pit_available_from": self.pit_available_from,
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

    def __init__(self):
        self._requested_as_of: str | None = None
        self._requested_as_of_date: date | None = None
        self._ttm_cache: dict[Any, dict[int, tuple[DerivedMetricObservation, tuple[PeriodizedFinancialObservation, ...]]]] = {}

    def derive(self, source: PeriodizationResult | Iterable[PeriodizedFinancialObservation],
               *, requested_as_of: Any = None) -> DerivedMetricsResult:
        self._requested_as_of, self._requested_as_of_date = _normalise_as_of(requested_as_of)
        self._ttm_cache = {}
        observations = self._coerce(source)
        selected = self._select_periods(observations)
        output: list[DerivedMetricObservation] = []
        diagnostics: list[Mapping[str, Any]] = []
        for group_key, periods in sorted(selected.items()):
            _, _, _, metric = group_key
            if metric not in FLOW_METRICS:
                continue
            output.extend(self._growth_metrics(group_key, periods))
            output.extend(self._ttm_metrics(group_key, periods))
            output.extend(self._margin_metrics(group_key, selected))
            output.extend(self._ttm_margin_metrics(group_key, selected))
            output.extend(self._margin_expansion_metrics(group_key, selected))
            output.extend(self._transition_metrics(group_key, periods))
            output.extend(self._trend_metrics(group_key, periods))
        output.extend(self._capital_metrics(observations, selected))
        output.sort(key=lambda item: (item.ticker, item.metric, item.fiscal_year,
                                      item.fiscal_period, item.metric_type))
        return DerivedMetricsResult(output, diagnostics)

    def calculate(self, source: PeriodizationResult | Iterable[PeriodizedFinancialObservation],
                  *, requested_as_of: Any = None) -> DerivedMetricsResult:
        return self.derive(source, requested_as_of=requested_as_of)

    def compute(self, source: PeriodizationResult | Iterable[PeriodizedFinancialObservation],
                *, requested_as_of: Any = None) -> DerivedMetricsResult:
        return self.derive(source, requested_as_of=requested_as_of)

    def _ready(self, item: PeriodizedFinancialObservation | None) -> bool:
        available = _source_available_on(item)
        if not _value_ready(item):
            return False
        if self._requested_as_of_date is None:
            return True
        # A PIT request without an auditable availability date is not safe to
        # use.  Treat unknown availability as INPUT_NOT_READY rather than
        # allowing a numerically valid observation to cross the cutoff gate.
        return available is not None and available <= self._requested_as_of_date

    def _coherence(self, items: Iterable[PeriodizedFinancialObservation | None]) -> tuple[str, str | None]:
        values = tuple(items)
        if any(item is None for item in values):
            return DATA_UNAVAILABLE, "MISSING_COMPARABLE_PERIOD"
        if any(item.fs_div_used != values[0].fs_div_used for item in values[1:]):
            return BASIS_MISMATCH, "BASIS_MISMATCH"
        if any(item.currency != values[0].currency for item in values[1:]):
            return CURRENCY_MISMATCH, "CURRENCY_MISMATCH"
        if any(not self._ready(item) for item in values):
            return INPUT_NOT_READY, "INPUT_NOT_READY"
        return READY, None

    @staticmethod
    def _coerce(source: Any) -> tuple[PeriodizedFinancialObservation, ...]:
        if isinstance(source, PeriodizationResult):
            values = source.observations
        elif hasattr(source, "canonical_observations"):
            values = source.canonical_observations
        elif hasattr(source, "result") and isinstance(source.result, PeriodizationResult):
            values = source.result.observations
        else:
            values = tuple(source or ())
        if any(not isinstance(item, PeriodizedFinancialObservation) for item in values):
            raise DerivedMetricsError("DerivedMetricsEngine requires PeriodizedFinancialObservation inputs")
        return tuple(values)

    def _select_periods(self, observations: Iterable[PeriodizedFinancialObservation]):
        grouped: dict[tuple[str, str, str, str], list[PeriodizedFinancialObservation]] = defaultdict(list)
        for item in observations:
            if item.metric not in FLOW_METRICS or item.fiscal_period not in (*QUARTERS, "FY"):
                continue
            if item.fiscal_period in QUARTERS and item.period_semantics != "STANDALONE_QUARTER":
                continue
            if item.fiscal_period == "FY" and item.period_semantics not in {"CUMULATIVE_YTD", "FULL_YEAR"}:
                continue
            grouped[(item.ticker, item.corp_code, item.company_family, item.metric)].append(item)
        selected: dict[tuple[str, str, str, str], dict[tuple[str, str], PeriodizedFinancialObservation | None]] = {}
        for key, values in grouped.items():
            candidates: dict[tuple[str, str], list[PeriodizedFinancialObservation]] = defaultdict(list)
            for value in values:
                candidates[(str(value.fiscal_year), value.fiscal_period)].append(value)
            periods: dict[tuple[str, str], PeriodizedFinancialObservation | None] = {}
            for period_key, period_values in candidates.items():
                ready = [item for item in period_values if self._ready(item)]
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

    def _period_context(self, group_key, current: PeriodizedFinancialObservation | None,
                        *, metric_type: str, value: Any, unit: str,
                        status: str = READY, reason: str | None = None,
                        sources: Iterable[PeriodizedFinancialObservation | None] = (),
                        metadata: Mapping[str, Any] | None = None) -> DerivedMetricObservation:
        ticker, corp_code, family, metric = group_key
        source_items = tuple(sources)
        nos, dts, shas = self._source(source_items)
        pit_dates = [available for item in source_items
                     if (available := _source_available_on(item)) is not None]
        pit_available = max(pit_dates).isoformat() if pit_dates else None
        final_status = status
        final_value = value
        final_reason = reason
        if (status == READY and self._requested_as_of_date is not None
                and pit_dates and max(pit_dates) > self._requested_as_of_date):
            final_status = INPUT_NOT_READY
            final_value = None
            final_reason = "FUTURE_DATA_AFTER_REQUESTED_AS_OF"
        elif (status == READY and self._requested_as_of_date is not None and not pit_dates):
            final_status = INPUT_NOT_READY
            final_value = None
            final_reason = "PIT_AVAILABILITY_UNKNOWN"
        return DerivedMetricObservation(
            ticker, corp_code, family, str(current.fiscal_year) if current else "",
            current.fiscal_period if current else "", metric, metric_type, final_value,
            unit=unit, resolution_status=final_status, reason=final_reason,
            period_end=current.period_end if current else None,
            source_rcept_nos=nos, source_rcept_dts=dts, source_sha256s=shas,
            requested_as_of=self._requested_as_of, pit_available_from=pit_available,
            metadata=metadata,
        )

    def _rate(self, current: PeriodizedFinancialObservation | None,
              prior: PeriodizedFinancialObservation | None, group_key, metric_type: str,
              *, sources=()) -> DerivedMetricObservation:
        source_items = sources or (current, prior)
        if current is None or not self._ready(current):
            return self._period_context(group_key, current, metric_type=metric_type, value=None,
                                        unit="PERCENT", status=INPUT_NOT_READY,
                                        reason="CURRENT_OBSERVATION_UNAVAILABLE", sources=source_items)
        if prior is None:
            return self._period_context(group_key, current, metric_type=metric_type, value=None,
                                        unit="PERCENT", status=DATA_UNAVAILABLE,
                                        reason="MISSING_PRIOR_PERIOD", sources=source_items)
        coherence_status, coherence_reason = self._coherence((current, prior))
        if coherence_status in {BASIS_MISMATCH, CURRENCY_MISMATCH}:
            return self._period_context(group_key, current, metric_type=metric_type, value=None,
                                        unit="PERCENT", status=coherence_status,
                                        reason=coherence_reason, sources=source_items)
        if coherence_status != READY:
            return self._period_context(group_key, current, metric_type=metric_type, value=None,
                                        unit="PERCENT", status=coherence_status,
                                        reason=coherence_reason or "INPUT_NOT_READY", sources=source_items)
        prior_value = _number(prior.value)
        current_value = _number(current.value)
        if prior_value is None or prior_value <= 0 or current_value is None or current_value < 0:
            return self._period_context(group_key, current, metric_type=metric_type, value=None,
                                        unit="PERCENT", status=UNDEFINED_BASE,
                                        reason="NON_POSITIVE_OR_SIGN_TRANSITION_BASE", sources=source_items)
        value = ((current_value - prior_value) / prior_value) * 100
        return self._period_context(group_key, current, metric_type=metric_type, value=value,
                                    unit="PERCENT", sources=source_items)

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
        ttm: dict[int, tuple[DerivedMetricObservation, tuple[PeriodizedFinancialObservation, ...]]] = {}
        for index, current in sorted(quarters.items()):
            source_items = [quarters.get(index - offset) for offset in (3, 2, 1, 0)]
            if any(item is None for item in source_items):
                if not self._ready(current):
                    continue
                output.append(self._period_context(group_key, current, metric_type="TTM", value=None,
                                                   unit="VALUE", status=DATA_UNAVAILABLE,
                                                   reason="MISSING_FOUR_QUARTER_WINDOW", sources=source_items))
                continue
            coherence_status, coherence_reason = self._coherence(source_items)
            if coherence_status != READY:
                if current is None:
                    continue
                output.append(self._period_context(group_key, current, metric_type="TTM", value=None,
                                                   unit="VALUE", status=coherence_status,
                                                   reason=coherence_reason or "INPUT_NOT_READY",
                                                   sources=source_items))
                continue
            value = sum(_number(item.value) for item in source_items)
            ttm_item = self._period_context(group_key, current, metric_type="TTM", value=value,
                                             unit="VALUE", sources=source_items)
            ttm[index] = (ttm_item, tuple(source_items))
            output.append(ttm_item)
        self._ttm_cache[group_key] = ttm
        for index, (current_ttm, current_sources) in sorted(ttm.items()):
            prior_entry = ttm.get(index - 4)
            current_obs = quarters[index]
            if prior_entry is None:
                output.append(self._period_context(group_key, current_obs, metric_type="TTM_YOY", value=None,
                                                   unit="PERCENT", status=DATA_UNAVAILABLE,
                                                   reason="MISSING_PRIOR_TTM", sources=current_sources))
            else:
                prior_ttm, prior_sources = prior_entry
                all_sources = current_sources + prior_sources
                coherence_status, coherence_reason = self._coherence(all_sources)
                if coherence_status != READY:
                    output.append(self._period_context(
                        group_key, current_obs, metric_type="TTM_YOY", value=None,
                        unit="PERCENT", status=coherence_status,
                        reason=coherence_reason or "INPUT_NOT_READY", sources=all_sources,
                    ))
                    continue
                prior_value = _number(prior_ttm.value)
                current_value = _number(current_ttm.value)
                if prior_value is None or prior_value <= 0 or current_value is None or current_value < 0:
                    output.append(self._period_context(
                        group_key, current_obs, metric_type="TTM_YOY", value=None,
                        unit="PERCENT", status=UNDEFINED_BASE,
                        reason="NON_POSITIVE_OR_SIGN_TRANSITION_BASE", sources=all_sources,
                    ))
                    continue
                value = ((current_value - prior_value) / prior_value) * 100
                output.append(self._period_context(
                    group_key, current_obs, metric_type="TTM_YOY", value=value, unit="PERCENT",
                    sources=all_sources,
                ))
        return output

    @staticmethod
    def _instant_period(item: PeriodizedFinancialObservation) -> str | None:
        """Return the canonical quarter-end label without changing source semantics."""

        period = str(item.fiscal_period or "").upper().strip()
        if period in INSTANT_PERIODS:
            return period
        if str(item.period_semantics or "").upper() != "INSTANT":
            return None
        return {"Q1": "Q1_END", "Q2": "H1_END", "Q3": "Q3_END", "Q4": "FY_END", "FY": "FY_END"}.get(period)

    def _select_instant_snapshots(
        self, observations: Iterable[PeriodizedFinancialObservation],
    ) -> tuple[dict[tuple[str, str, str, str, str, str], PeriodizedFinancialObservation | None],
               set[tuple[str, str, str, str, str, str]]]:
        """Select one PIT candidate per instant metric/snapshot, fail-closed on ties."""

        grouped: dict[tuple[str, str, str, str, str, str], list[PeriodizedFinancialObservation]] = defaultdict(list)
        for item in observations:
            if item.metric not in INSTANT_METRICS:
                continue
            period = self._instant_period(item)
            if period is None:
                continue
            key = (str(item.ticker), str(item.corp_code), str(item.company_family),
                   str(item.fiscal_year), period, str(item.metric))
            grouped[key].append(item)

        selected: dict[tuple[str, str, str, str, str, str], PeriodizedFinancialObservation | None] = {}
        ambiguous: set[tuple[str, str, str, str, str, str]] = set()
        for key, values in grouped.items():
            ready = [item for item in values if self._ready(item)]
            candidates = ready or values
            latest_dt = max((_parse_date(item.anchor_rcept_dt) or date.min) for item in candidates)
            latest = [item for item in candidates
                      if (_parse_date(item.anchor_rcept_dt) or date.min) == latest_dt]
            latest_identities = {
                (item.anchor_rcept_no, item.value, item.currency, item.fs_div_used,
                 item.resolution_status, item.source_rcept_nos, item.source_rcept_dts,
                 item.source_sha256s)
                for item in latest
            }
            if len(latest_identities) != 1:
                selected[key] = None
                ambiguous.add(key)
            else:
                selected[key] = latest[0]
        return selected, ambiguous

    @staticmethod
    def _identity(group_key) -> tuple[str, str, str]:
        return str(group_key[0]), str(group_key[1]), str(group_key[2])

    @staticmethod
    def _quarter_parts(index: int) -> tuple[int, int]:
        year = (index - 1) // 4
        return year, index - year * 4

    @staticmethod
    def _quarter_end_label(quarter: int) -> str:
        return {1: "Q1_END", 2: "H1_END", 3: "Q3_END", 4: "FY_END"}[quarter]

    @staticmethod
    def _snapshot_key(identity: tuple[str, str, str], year: int, period: str, metric: str):
        return (*identity, str(year), period, metric)

    def _snapshot(
        self,
        snapshots: Mapping[tuple[str, str, str, str, str, str], PeriodizedFinancialObservation | None],
        identity: tuple[str, str, str], year: int, period: str, metric: str,
    ) -> PeriodizedFinancialObservation | None:
        return snapshots.get(self._snapshot_key(identity, year, period, metric))

    @staticmethod
    def _source_anchor(sources: Iterable[PeriodizedFinancialObservation | None]) -> PeriodizedFinancialObservation | None:
        return next((item for item in sources if item is not None), None)

    def _capital_status(self, item: PeriodizedFinancialObservation | None, missing_reason: str,
                        *, ambiguous: bool = False) -> tuple[str, str]:
        if ambiguous:
            return PERIOD_AMBIGUOUS, "AMBIGUOUS_SNAPSHOT"
        if item is None:
            return DATA_UNAVAILABLE, missing_reason
        if item.resolution_status != READY or not self._ready(item):
            return (item.resolution_status if item.resolution_status != READY else INPUT_NOT_READY,
                    item.reason or "INPUT_NOT_READY")
        return READY, ""

    def _annual_roe_metrics(self, group_key, periods, snapshots, ambiguous):
        output: list[DerivedMetricObservation] = []
        identity = self._identity(group_key)
        annuals = {int(year): item for (year, period), item in periods.items() if period == "FY"
                   for year in [int(str(year)[:4])]}
        for year, current in sorted(annuals.items()):
            prior_key = self._snapshot_key(identity, year - 1, "FY_END", "equity")
            current_key = self._snapshot_key(identity, year, "FY_END", "equity")
            prior_equity = snapshots.get(prior_key)
            current_equity = snapshots.get(current_key)
            sources = (current, prior_equity, current_equity)
            anchor = self._source_anchor(sources)
            if anchor is None:
                continue
            if group_key[2] == "FINANCIAL":
                output.append(self._period_context(
                    group_key, anchor, metric_type=ANNUAL_ROE, value=None, unit=PERCENT,
                    status=NOT_APPLICABLE, reason="FINANCIAL_COMPANY_ROE_NOT_APPLICABLE", sources=sources,
                ))
                continue
            status, reason = self._capital_status(current, "MISSING_ANNUAL_NET_INCOME")
            if status == READY:
                status, reason = self._capital_status(
                    prior_equity, "MISSING_PRIOR_FY_END_EQUITY",
                    ambiguous=prior_key in ambiguous,
                )
            if status == READY:
                status, reason = self._capital_status(
                    current_equity, "MISSING_CURRENT_FY_END_EQUITY",
                    ambiguous=current_key in ambiguous,
                )
            if status != READY:
                output.append(self._period_context(
                    group_key, anchor, metric_type=ANNUAL_ROE, value=None, unit=PERCENT,
                    status=status, reason=reason, sources=sources,
                    metadata={"numerator": "annual net_income", "begin_equity_period": f"{year - 1}FY_END",
                              "end_equity_period": f"{year}FY_END"},
                ))
                continue
            coherence_status, coherence_reason = self._coherence(sources)
            if coherence_status != READY:
                output.append(self._period_context(
                    group_key, anchor, metric_type=ANNUAL_ROE, value=None, unit=PERCENT,
                    status=coherence_status, reason=coherence_reason, sources=sources,
                ))
                continue
            prior_value, current_value = _number(prior_equity.value), _number(current_equity.value)
            average_equity = (prior_value + current_value) / 2
            metadata = {"numerator": "annual net_income", "begin_equity_period": f"{year - 1}FY_END",
                        "end_equity_period": f"{year}FY_END"}
            if average_equity <= 0:
                output.append(self._period_context(
                    group_key, anchor, metric_type=ANNUAL_ROE, value=None, unit=PERCENT,
                    status=UNDEFINED_BASE, reason="NON_POSITIVE_AVERAGE_EQUITY_BASE", sources=sources,
                    metadata=metadata,
                ))
                continue
            output.append(self._period_context(
                group_key, anchor, metric_type=ANNUAL_ROE,
                value=_number(current.value) / average_equity * 100, unit=PERCENT,
                sources=sources, metadata=metadata,
            ))
        return output

    def _ttm_roe_metrics(self, group_key, periods, snapshots, ambiguous):
        output: list[DerivedMetricObservation] = []
        identity = self._identity(group_key)
        quarters = {
            _quarter_index(year, period): item
            for (year, period), item in periods.items() if period in QUARTERS
        }
        cached_ttm = self._ttm_cache.get(group_key, {})
        for index, current in sorted(quarters.items()):
            if current is None:
                continue
            source_window = tuple(quarters.get(index - offset) for offset in (3, 2, 1, 0))
            begin_year, begin_quarter = self._quarter_parts(index - 4)
            end_year, end_quarter = self._quarter_parts(index)
            begin_period = self._quarter_end_label(begin_quarter)
            end_period = self._quarter_end_label(end_quarter)
            begin_key = self._snapshot_key(identity, begin_year, begin_period, "equity")
            end_key = self._snapshot_key(identity, end_year, end_period, "equity")
            begin_equity = snapshots.get(begin_key)
            end_equity = snapshots.get(end_key)
            sources = source_window + (begin_equity, end_equity)
            # Anchor the derived observation to the endpoint quarter; the
            # four source quarters remain in provenance below.
            anchor = current
            if anchor is None:
                continue
            metadata = {
                "ttm_start": f"{source_window[0].fiscal_year}{source_window[0].fiscal_period}" if source_window[0] else None,
                "ttm_end": f"{current.fiscal_year}{current.fiscal_period}",
                "begin_equity_period": f"{begin_year}{begin_period}",
                "end_equity_period": f"{end_year}{end_period}",
            }
            if group_key[2] == "FINANCIAL":
                output.append(self._period_context(
                    group_key, anchor, metric_type=TTM_ROE, value=None, unit=PERCENT,
                    status=NOT_APPLICABLE, reason="FINANCIAL_COMPANY_ROE_NOT_APPLICABLE", sources=sources,
                    metadata=metadata,
                ))
                continue
            status, reason = self._capital_status(current, "MISSING_TTM_NET_INCOME")
            if status == READY and any(item is None for item in source_window):
                status, reason = DATA_UNAVAILABLE, "MISSING_FOUR_QUARTER_WINDOW"
            if status == READY:
                non_ready = next((item for item in source_window if not self._ready(item)), None)
                if non_ready is not None:
                    status, reason = self._capital_status(non_ready, "INPUT_NOT_READY")
            if status == READY:
                status, reason = self._capital_status(
                    begin_equity, "MISSING_BEGINNING_EQUITY",
                    ambiguous=begin_key in ambiguous,
                )
            if status == READY:
                status, reason = self._capital_status(
                    end_equity, "MISSING_ENDING_EQUITY",
                    ambiguous=end_key in ambiguous,
                )
            if status != READY:
                output.append(self._period_context(
                    group_key, anchor, metric_type=TTM_ROE, value=None, unit=PERCENT,
                    status=status, reason=reason, sources=sources, metadata=metadata,
                ))
                continue
            coherence_status, coherence_reason = self._coherence(sources)
            if coherence_status != READY:
                output.append(self._period_context(
                    group_key, anchor, metric_type=TTM_ROE, value=None, unit=PERCENT,
                    status=coherence_status, reason=coherence_reason, sources=sources, metadata=metadata,
                ))
                continue
            cached = cached_ttm.get(index)
            ttm_value = cached[0].value if cached is not None else sum(_number(item.value) for item in source_window)
            average_equity = (_number(begin_equity.value) + _number(end_equity.value)) / 2
            if average_equity <= 0:
                output.append(self._period_context(
                    group_key, anchor, metric_type=TTM_ROE, value=None, unit=PERCENT,
                    status=UNDEFINED_BASE, reason="NON_POSITIVE_AVERAGE_EQUITY_BASE", sources=sources,
                    metadata=metadata,
                ))
                continue
            output.append(self._period_context(
                group_key, anchor, metric_type=TTM_ROE,
                value=_number(ttm_value) / average_equity * 100, unit=PERCENT,
                sources=sources, metadata=metadata,
            ))
        return output

    def _debt_ratio_metrics(self, identity, family, snapshots, ambiguous):
        output: list[DerivedMetricObservation] = []
        keys = sorted({key[3:5] for key in snapshots
                       if key[:3] == identity and key[5] in INSTANT_METRICS})
        group_key = (*identity, "liabilities")
        for year_text, period in keys:
            year = int(year_text)
            liabilities_key = self._snapshot_key(identity, year, period, "liabilities")
            equity_key = self._snapshot_key(identity, year, period, "equity")
            liabilities = snapshots.get(liabilities_key)
            equity = snapshots.get(equity_key)
            sources = (liabilities, equity)
            anchor = self._source_anchor(sources)
            if anchor is None:
                continue
            metadata = {"snapshot_period": f"{year}{period}"}
            if family == "FINANCIAL":
                output.append(self._period_context(
                    group_key, anchor, metric_type=DEBT_RATIO, value=None, unit=PERCENT,
                    status=NOT_APPLICABLE, reason="FINANCIAL_COMPANY_DEBT_RATIO_NOT_APPLICABLE",
                    sources=sources, metadata=metadata,
                ))
                continue
            status, reason = self._capital_status(
                liabilities, "MISSING_LIABILITIES", ambiguous=liabilities_key in ambiguous,
            )
            if status == READY:
                status, reason = self._capital_status(
                    equity, "MISSING_EQUITY", ambiguous=equity_key in ambiguous,
                )
            if status != READY:
                output.append(self._period_context(
                    group_key, anchor, metric_type=DEBT_RATIO, value=None, unit=PERCENT,
                    status=status, reason=reason, sources=sources, metadata=metadata,
                ))
                continue
            coherence_status, coherence_reason = self._coherence(sources)
            if coherence_status != READY:
                output.append(self._period_context(
                    group_key, anchor, metric_type=DEBT_RATIO, value=None, unit=PERCENT,
                    status=coherence_status, reason=coherence_reason, sources=sources, metadata=metadata,
                ))
                continue
            equity_value = _number(equity.value)
            if equity_value <= 0:
                output.append(self._period_context(
                    group_key, anchor, metric_type=DEBT_RATIO, value=None, unit=PERCENT,
                    status=UNDEFINED_BASE, reason="NON_POSITIVE_EQUITY_BASE", sources=sources, metadata=metadata,
                ))
                continue
            output.append(self._period_context(
                group_key, anchor, metric_type=DEBT_RATIO,
                value=_number(liabilities.value) / equity_value * 100, unit=PERCENT,
                sources=sources, metadata=metadata,
            ))
        return output

    def _capital_metrics(self, observations, selected):
        snapshots, ambiguous = self._select_instant_snapshots(observations)
        output: list[DerivedMetricObservation] = []
        net_income_groups = [key for key in selected if key[-1] == "net_income"]
        identities: dict[tuple[str, str, str], str] = {}
        for key in snapshots:
            identity = key[:3]
            identities.setdefault(identity, key[2])
        for group_key in net_income_groups:
            output.extend(self._annual_roe_metrics(
                group_key, selected[group_key], snapshots, ambiguous,
            ))
            output.extend(self._ttm_roe_metrics(
                group_key, selected[group_key], snapshots, ambiguous,
            ))
            identities.setdefault(self._identity(group_key), group_key[2])
        for identity, family in sorted(identities.items()):
            output.extend(self._debt_ratio_metrics(identity, family, snapshots, ambiguous))
        return output

    def _margin_metrics(self, group_key, selected):
        metric = group_key[-1]
        if metric not in MARGIN_METRICS:
            return []
        revenue_key = group_key[:-1] + ("revenue",)
        revenue_periods = selected.get(revenue_key, {})
        numerator_periods = selected.get(group_key, {})
        if not revenue_periods and group_key[2] != "FINANCIAL":
            return []
        output: list[DerivedMetricObservation] = []
        for period_key in sorted(set(revenue_periods) | set(numerator_periods), key=lambda item: (_year_number(item[0]) or 0, item[1])):
            revenue = revenue_periods.get(period_key)
            numerator = numerator_periods.get(period_key)
            current = numerator or revenue
            if group_key[2] == "FINANCIAL":
                if current is not None:
                    output.append(self._period_context(
                        group_key, current, metric_type=MARGIN_METRICS[metric], value=None,
                        unit="PERCENT", status=NOT_APPLICABLE,
                        reason="FINANCIAL_COMPANY_REVENUE_MARGIN_NOT_APPLICABLE",
                        sources=(numerator, revenue),
                    ))
                continue
            if not self._ready(numerator) or not self._ready(revenue):
                output.append(self._period_context(
                    group_key, current, metric_type=MARGIN_METRICS[metric], value=None, unit="PERCENT",
                    status=INPUT_NOT_READY, reason="MARGIN_INPUT_UNAVAILABLE", sources=(numerator, revenue),
                ))
                continue
            coherence_status, coherence_reason = self._coherence((numerator, revenue))
            if coherence_status in {BASIS_MISMATCH, CURRENCY_MISMATCH}:
                output.append(self._period_context(
                    group_key, numerator, metric_type=MARGIN_METRICS[metric], value=None, unit="PERCENT",
                    status=coherence_status, reason=coherence_reason,
                    sources=(numerator, revenue),
                ))
                continue
            denominator = _number(revenue.value)
            if denominator is None or denominator <= 0:
                output.append(self._period_context(
                    group_key, numerator, metric_type=MARGIN_METRICS[metric], value=None, unit="PERCENT",
                    status=UNDEFINED_BASE, reason="NON_POSITIVE_REVENUE_BASE",
                    sources=(numerator, revenue),
                ))
                continue
            value = _number(numerator.value) / denominator * 100
            output.append(self._period_context(
                group_key, numerator, metric_type=MARGIN_METRICS[metric], value=value, unit="PERCENT",
                sources=(numerator, revenue),
            ))
        return output

    def _ttm_margin_metrics(self, group_key, selected):
        metric = group_key[-1]
        if metric not in MARGIN_METRICS:
            return []
        ttm_metric = {
            "operating_income": "TTM_OPERATING_MARGIN",
            "net_income": "TTM_NET_MARGIN",
            "operating_cash_flow": "TTM_OPERATING_CASH_FLOW_MARGIN",
        }[metric]
        numerator_periods = selected.get(group_key, {})
        revenue_periods = selected.get(group_key[:-1] + ("revenue",), {})
        numerator_quarters = {
            _quarter_index(year, period): item
            for (year, period), item in numerator_periods.items() if period in QUARTERS
        }
        revenue_quarters = {
            _quarter_index(year, period): item
            for (year, period), item in revenue_periods.items() if period in QUARTERS
        }
        output: list[DerivedMetricObservation] = []
        for index, numerator_current in sorted(numerator_quarters.items()):
            revenue_current = revenue_quarters.get(index)
            if group_key[2] == "FINANCIAL":
                output.append(self._period_context(
                    group_key, numerator_current, metric_type=ttm_metric, value=None,
                    unit="PERCENT", status=NOT_APPLICABLE,
                    reason="FINANCIAL_COMPANY_REVENUE_MARGIN_NOT_APPLICABLE",
                    sources=(numerator_current,),
                ))
                continue
            numerator_window = tuple(numerator_quarters.get(index - offset) for offset in (3, 2, 1, 0))
            revenue_window = tuple(revenue_quarters.get(index - offset) for offset in (3, 2, 1, 0))
            all_sources = numerator_window + revenue_window
            if any(item is None for item in all_sources):
                if numerator_current is not None or revenue_current is not None:
                    output.append(self._period_context(
                        group_key, numerator_current or revenue_current, metric_type=ttm_metric,
                        value=None, unit="PERCENT", status=DATA_UNAVAILABLE,
                        reason="MISSING_FOUR_QUARTER_WINDOW", sources=all_sources,
                    ))
                continue
            coherence_status, coherence_reason = self._coherence(all_sources)
            if coherence_status != READY:
                output.append(self._period_context(
                    group_key, numerator_current, metric_type=ttm_metric, value=None,
                    unit="PERCENT", status=coherence_status,
                    reason=coherence_reason or "INPUT_NOT_READY", sources=all_sources,
                ))
                continue
            revenue_total = sum(_number(item.value) for item in revenue_window)
            numerator_total = sum(_number(item.value) for item in numerator_window)
            if revenue_total <= 0:
                output.append(self._period_context(
                    group_key, numerator_current, metric_type=ttm_metric, value=None,
                    unit="PERCENT", status=UNDEFINED_BASE,
                    reason="NON_POSITIVE_REVENUE_BASE", sources=all_sources,
                ))
                continue
            output.append(self._period_context(
                group_key, numerator_current, metric_type=ttm_metric,
                value=numerator_total / revenue_total * 100, unit="PERCENT",
                sources=all_sources,
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
            if prior is None:
                output.append(self._period_context(group_key, current, metric_type="EARNINGS_TRANSITION", value=None,
                                                   unit="CLASSIFICATION", status=DATA_UNAVAILABLE,
                                                   reason="MISSING_PRIOR_PERIOD", sources=(current, prior)))
                continue
            coherence_status, coherence_reason = self._coherence((current, prior))
            if coherence_status in {BASIS_MISMATCH, CURRENCY_MISMATCH, INPUT_NOT_READY}:
                output.append(self._period_context(
                    group_key, current, metric_type="EARNINGS_TRANSITION", value=None,
                    unit="CLASSIFICATION", status=coherence_status,
                    reason=coherence_reason or "INPUT_NOT_READY", sources=(current, prior),
                ))
                continue
            left, right = _number(prior.value), _number(current.value)
            if left is None or right is None:
                output.append(self._period_context(
                    group_key, current, metric_type="EARNINGS_TRANSITION", value=None,
                    unit="CLASSIFICATION", status=INPUT_NOT_READY,
                    reason="INPUT_NOT_READY", sources=(current, prior),
                ))
                continue
            if left == 0:
                transition = "ZERO_BASE"
            elif right == 0:
                transition = "ZERO_CURRENT"
            elif left < 0 < right:
                transition = "LOSS_TO_PROFIT"
            elif left > 0 > right:
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
            if group_key[2] == "FINANCIAL":
                if current is not None:
                    output.append(self._period_context(
                        group_key, current, metric_type="MARGIN_EXPANSION_TREND",
                        value=None, unit="PERCENTAGE_POINTS", status=NOT_APPLICABLE,
                        reason="FINANCIAL_COMPANY_REVENUE_MARGIN_NOT_APPLICABLE",
                        sources=source,
                    ))
                continue
            if not (self._ready(current) and self._ready(revenue)
                    and self._ready(prior) and self._ready(prior_revenue)):
                if current is None and revenue is None:
                    continue
                output.append(self._period_context(
                    group_key, current or revenue, metric_type="MARGIN_EXPANSION_TREND",
                    value=None, unit="PERCENTAGE_POINTS", status=INPUT_NOT_READY,
                    reason="MISSING_COMPARABLE_MARGIN_PERIOD", sources=source,
                ))
                continue
            coherence_status, coherence_reason = self._coherence(source)
            if coherence_status in {BASIS_MISMATCH, CURRENCY_MISMATCH, INPUT_NOT_READY}:
                output.append(self._period_context(
                    group_key, current, metric_type="MARGIN_EXPANSION_TREND",
                    value=None, unit="PERCENTAGE_POINTS", status=coherence_status,
                    reason=coherence_reason or "INPUT_NOT_READY", sources=source,
                ))
                continue
            current_revenue = _number(revenue.value)
            prior_revenue_value = _number(prior_revenue.value)
            if current_revenue is None or current_revenue <= 0 or prior_revenue_value is None or prior_revenue_value <= 0:
                output.append(self._period_context(
                    group_key, current, metric_type="MARGIN_EXPANSION_TREND",
                    value=None, unit="PERCENTAGE_POINTS", status=UNDEFINED_BASE,
                    reason="NON_POSITIVE_REVENUE_BASE", sources=source,
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


def derive_metrics(source: PeriodizationResult | Iterable[PeriodizedFinancialObservation],
                   *, requested_as_of: Any = None) -> DerivedMetricsResult:
    return DerivedMetricsEngine().derive(source, requested_as_of=requested_as_of)


def calculate_derived_metrics(source: PeriodizationResult | Iterable[PeriodizedFinancialObservation],
                              *, requested_as_of: Any = None) -> DerivedMetricsResult:
    return derive_metrics(source, requested_as_of=requested_as_of)
