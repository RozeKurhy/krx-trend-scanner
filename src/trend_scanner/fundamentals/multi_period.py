"""Canonical multi-period production boundary for OpenDART fundamentals.

This module is deliberately a thin adapter around ``PeriodizationProvider``.
It does not read OpenDART endpoints directly and does not reimplement
periodization or derived-metric arithmetic.  Its responsibility is to retain
quarter/year identity, expose comparison windows, and make gaps or unusable
canonical observations explicit for downstream consumers.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Any, Iterable, Mapping, Sequence

from .opendart_contract import CompanyFamily
from .period_models import (
    BASIS_MISMATCH,
    DATA_UNAVAILABLE,
    PERIOD_AMBIGUOUS,
    PeriodizationResult,
    PeriodizedFinancialObservation,
    READY,
)
from .periodization_provider import PeriodizationBuild, PeriodizationProvider


CURRENCY_MISMATCH = "CURRENCY_MISMATCH"


class CoverageMetadata(dict):
    """Dict-compatible coverage metadata with convenient attribute access."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def to_dict(self) -> dict[str, Any]:
        return dict(self)


QUARTER_PERIODS = ("Q1", "Q2", "Q3", "Q4")
QUARTER_REQUIRED_METRICS = (
    "revenue",
    "operating_income",
    "net_income",
    "operating_cash_flow",
)
ANNUAL_REQUIRED_METRICS = (
    "revenue",
    "operating_income",
    "net_income",
    "equity",
    "liabilities",
)
OPTIONAL_ANNUAL_METRICS = ("operating_cash_flow",)
REQUIRED_SOURCE_METRICS = tuple(dict.fromkeys(QUARTER_REQUIRED_METRICS + ANNUAL_REQUIRED_METRICS))
_STATUS_PRIORITY = {
    PERIOD_AMBIGUOUS: 50,
    BASIS_MISMATCH: 40,
    CURRENCY_MISMATCH: 40,
    "DIRECT_DERIVED_MISMATCH": 40,
    "PERIODIZATION_UNSUPPORTED": 30,
    DATA_UNAVAILABLE: 20,
    "DERIVATION_UNAVAILABLE": 20,
    "INPUT_NOT_READY": 20,
    READY: 0,
}


def _as_of(value: str | date) -> str:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except (TypeError, ValueError):
        raise ValueError(f"Invalid requested_as_of: {value!r}") from None


def _as_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10].replace("/", "-"))
    except (TypeError, ValueError):
        return None


def _year(value: Any) -> int | None:
    try:
        return int(str(value)[:4])
    except (TypeError, ValueError):
        return None


def _family_text(value: Any) -> str:
    if hasattr(value, "value"):
        value = value.value
    return str(value or "").strip()


def _quarter_number(value: Any) -> int | None:
    text = str(value or "").upper().strip()
    if text in QUARTER_PERIODS:
        return QUARTER_PERIODS.index(text) + 1
    # Instant balance-sheet snapshots are periodized at the end of a quarter.
    if text.endswith("_END"):
        return _quarter_number(text[:-4])
    return None


def _quarter_identity(year: Any, period: Any) -> tuple[int, int] | None:
    number = _year(year)
    quarter = _quarter_number(period)
    if number is None or quarter is None:
        return None
    return number, quarter


def _annual_identity(year: Any, period: Any) -> int | None:
    if str(period or "").upper() not in {"FY", "FULL_YEAR", "FY_END"}:
        return None
    return _year(year)


def _quarter_label(identity: tuple[int, int]) -> str:
    return f"{identity[0]}Q{identity[1]}"


def _normalise_years(value: Iterable[str] | str | None, cutoff: date) -> tuple[str, ...]:
    if value is None:
        years = range(cutoff.year - 5, cutoff.year + 1)
    elif isinstance(value, (str, int)):
        years = (int(str(value)[:4]),)
    else:
        years = (int(str(item)[:4]) for item in value)
    return tuple(dict.fromkeys(str(year) for year in years))


def _pit_eligible(item: PeriodizedFinancialObservation, cutoff: date) -> bool:
    available = _as_date(item.pit_available_from or item.anchor_rcept_dt)
    return available is not None and available <= cutoff


def _observation_status(items: Sequence[PeriodizedFinancialObservation]) -> tuple[str, str | None]:
    if not items:
        return DATA_UNAVAILABLE, "MISSING_QUARTER_OR_FISCAL_YEAR"
    statuses = [str(item.resolution_status or DATA_UNAVAILABLE) for item in items]
    non_ready = [status for status in statuses if status != READY]
    if non_ready:
        selected = max(non_ready, key=lambda item: _STATUS_PRIORITY.get(item, 10))
        reasons = sorted({str(item.reason) for item in items if item.reason})
        return selected, ";".join(reasons) if reasons else selected
    return READY, None


@dataclass(frozen=True)
class MultiPeriodCoverageSlot:
    """One expected quarter/FY identity, including an explicit gap status."""

    identity: str
    fiscal_year: str
    fiscal_period: str
    status: str
    reason: str | None = None
    observation_count: int = 0
    metrics: tuple[str, ...] = ()
    missing_metrics: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.status == READY

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "fiscal_year": self.fiscal_year,
            "fiscal_period": self.fiscal_period,
            "status": self.status,
            "reason": self.reason,
            "observation_count": self.observation_count,
            "metrics": list(self.metrics),
            "missing_metrics": list(self.missing_metrics),
        }


def _coverage(
    slots: Sequence[MultiPeriodCoverageSlot],
    *,
    requested_count: int,
    display_count: int,
    comparison_label: str,
    display_label: str,
    not_applicable: bool = False,
    basis_consistent: bool = True,
    currency_consistent: bool = True,
) -> CoverageMetadata:
    ready = sum(slot.status == READY for slot in slots)
    ambiguous = sum(slot.status == PERIOD_AMBIGUOUS for slot in slots)
    missing = sum(slot.status == DATA_UNAVAILABLE for slot in slots)
    display_slots = tuple(slots[-display_count:]) if display_count else ()
    has_comparison = bool(
        not_applicable is False and len(slots) >= requested_count
        and basis_consistent and currency_consistent
        and all(slot.status == READY for slot in slots[-requested_count:])
    )
    has_display = bool(
        not_applicable is False and len(display_slots) >= display_count
        and basis_consistent and currency_consistent
        and all(slot.status == READY for slot in display_slots)
    )
    return CoverageMetadata({
        "requested_count": requested_count,
        "ready_count": ready,
        "missing_count": missing,
        "ambiguous_count": ambiguous,
        "unavailable_count": len(slots) - ready,
        # Verbose aliases are part of the F2 coverage contract and make the
        # metadata convenient for population-level aggregation.
        "quarter_requested_count": requested_count if comparison_label.endswith("Q") else 0,
        "quarter_ready_count": ready if comparison_label.endswith("Q") else 0,
        "quarter_missing_count": missing if comparison_label.endswith("Q") else 0,
        "quarter_ambiguous_count": ambiguous if comparison_label.endswith("Q") else 0,
        "annual_requested_count": requested_count if comparison_label.endswith("FY") else 0,
        "annual_ready_count": ready if comparison_label.endswith("FY") else 0,
        "annual_missing_count": missing if comparison_label.endswith("FY") else 0,
        "annual_ambiguous_count": ambiguous if comparison_label.endswith("FY") else 0,
        "comparison_window": comparison_label,
        "display_window": display_label,
        "has_comparison_window": has_comparison,
        "has_display_window": has_display,
        "has_16q_comparison_window": has_comparison if comparison_label == "16Q" else False,
        "has_12q_display_window": has_display if display_label == "12Q" else False,
        "has_6fy_comparison_window": has_comparison if comparison_label == "6FY" else False,
        "has_5y_display_window": has_display if display_label == "5FY" else False,
        "basis_consistent": bool(basis_consistent),
        "currency_consistent": bool(currency_consistent),
        "not_applicable": bool(not_applicable),
        "slots": [slot.to_dict() for slot in slots],
    })


@dataclass(frozen=True)
class MultiPeriodFundamentalsResult:
    """Canonical observations plus explicit 16Q/6FY coverage metadata.

    ``quarters`` and ``annuals`` contain flat canonical observations (all
    source metrics).  ``quarter_slots``/``annual_slots`` are the identity
    windows consumed by reporting code; they retain missing and ambiguous
    periods instead of compressing them away.
    """

    ticker: str
    corp_code: str
    company_family: str
    requested_as_of: str
    quarters: tuple[PeriodizedFinancialObservation, ...]
    annuals: tuple[PeriodizedFinancialObservation, ...]
    quarter_slots: tuple[MultiPeriodCoverageSlot, ...]
    annual_slots: tuple[MultiPeriodCoverageSlot, ...]
    quarter_coverage: Mapping[str, Any]
    annual_coverage: Mapping[str, Any]
    latest_quarter: str | None = None
    latest_fy: str | None = None
    diagnostics: tuple[Mapping[str, Any], ...] = ()
    periodization_builds: tuple[PeriodizationBuild, ...] = ()

    @property
    def canonical_observations(self) -> tuple[PeriodizedFinancialObservation, ...]:
        return self.quarters + self.annuals

    @classmethod
    def from_canonical(cls, **kwargs: Any) -> "MultiPeriodFundamentalsResult":
        """Construct a result from canonical observations without a provider."""

        return build_multi_period_result(**kwargs)

    @property
    def coverage(self) -> Mapping[str, Mapping[str, Any]]:
        return {"quarter": self.quarter_coverage, "annual": self.annual_coverage}

    @property
    def quarter_observations(self) -> tuple[PeriodizedFinancialObservation, ...]:
        return self.quarters

    @property
    def annual_observations(self) -> tuple[PeriodizedFinancialObservation, ...]:
        return self.annuals

    @property
    def comparison_quarters(self) -> tuple[MultiPeriodCoverageSlot, ...]:
        return self.quarter_slots

    @property
    def display_quarters(self) -> tuple[MultiPeriodCoverageSlot, ...]:
        return self.quarter_slots[-12:]

    @property
    def comparison_annuals(self) -> tuple[MultiPeriodCoverageSlot, ...]:
        return self.annual_slots

    @property
    def display_annuals(self) -> tuple[MultiPeriodCoverageSlot, ...]:
        return self.annual_slots[-5:]

    @property
    def has_16q_comparison_window(self) -> bool:
        return bool(self.quarter_coverage.get("has_comparison_window", False))

    @property
    def has_12q_display_window(self) -> bool:
        return bool(self.quarter_coverage.get("has_display_window", False))

    @property
    def has_6fy_comparison_window(self) -> bool:
        return bool(self.annual_coverage.get("has_comparison_window", False))

    @property
    def has_5y_display_window(self) -> bool:
        return bool(self.annual_coverage.get("has_display_window", False))

    @property
    def quarter_requested_count(self) -> int:
        return int(self.quarter_coverage.get("quarter_requested_count", 0))

    @property
    def quarter_ready_count(self) -> int:
        return int(self.quarter_coverage.get("quarter_ready_count", 0))

    @property
    def annual_requested_count(self) -> int:
        return int(self.annual_coverage.get("annual_requested_count", 0))

    @property
    def annual_ready_count(self) -> int:
        return int(self.annual_coverage.get("annual_ready_count", 0))

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "corp_code": self.corp_code,
            "company_family": self.company_family,
            "requested_as_of": self.requested_as_of,
            "quarters": [item.to_dict() for item in self.quarters],
            "annuals": [item.to_dict() for item in self.annuals],
            "quarter_slots": [item.to_dict() for item in self.quarter_slots],
            "annual_slots": [item.to_dict() for item in self.annual_slots],
            "quarter_coverage": dict(self.quarter_coverage),
            "annual_coverage": dict(self.annual_coverage),
            "latest_quarter": self.latest_quarter,
            "latest_fy": self.latest_fy,
            "diagnostics": [dict(item) for item in self.diagnostics],
            "periodization_builds": [item.to_dict() for item in self.periodization_builds],
        }


class MultiPeriodFundamentalsProvider:
    """Build one multi-year result from the existing periodization authority."""

    def __init__(self, periodization_provider: PeriodizationProvider):
        self.periodization_provider = periodization_provider

    def build(
        self,
        ticker: str,
        requested_as_of: str | date | Iterable[str],
        *args: Any,
        fiscal_years: Iterable[str] | str | None = None,
        company: Mapping[str, Any] | None = None,
        company_metadata: Mapping[str, Any] | None = None,
        force_refresh: bool = False,
    ) -> MultiPeriodFundamentalsResult:
        # Match the existing DerivedMetricsProvider convenience signature as
        # well: build(ticker, fiscal_years, requested_as_of).  The canonical
        # F2 form remains build(ticker, requested_as_of, fiscal_years=...).
        if args:
            if len(args) != 1 or fiscal_years is not None:
                raise TypeError("use build(ticker, requested_as_of, fiscal_years=...) or "
                                "build(ticker, fiscal_years, requested_as_of)")
            fiscal_years, requested_as_of = requested_as_of, args[0]
        cutoff_text = _as_of(requested_as_of)
        cutoff = date.fromisoformat(cutoff_text)
        years = _normalise_years(fiscal_years, cutoff)
        # A year is built at most once.  This keeps comparison history from
        # re-running the same provider pipeline when callers pass duplicates.
        builds: list[PeriodizationBuild] = []
        built_years: list[str] = []

        def build_year(year: str) -> None:
            if year in built_years:
                return
            builds.append(self.periodization_provider.build(
                str(ticker), year, cutoff_text, company=company,
                company_metadata=company_metadata, force_refresh=force_refresh,
            ))
            built_years.append(year)

        for year in years:
            build_year(year)

        builds_tuple = tuple(builds)
        observations = tuple(item for build in builds_tuple for item in build.result.observations)
        family = ""
        if builds_tuple:
            family = _family_text(getattr(builds_tuple[0], "company_family", "UNKNOWN"))
        if family == "UNKNOWN":
            family = ""
        if not family:
            family = _family_text((company_metadata or company or {}).get("company_family"))
        resolved_corp_code = next(
            (str(item.corp_code) for build in builds_tuple for item in build.facts if item.corp_code),
            next((str(getattr(build, "corp_code")) for build in builds_tuple if getattr(build, "corp_code", None)), None),
        )
        initial = build_multi_period_result(
            ticker=str(ticker),
            requested_as_of=cutoff_text,
            observations=observations,
            company_family=family or None,
            corp_code=resolved_corp_code,
            periodization_builds=builds_tuple,
        )
        latest_fy = _year(initial.latest_fy)
        additional_years: list[str] = []
        if latest_fy is not None:
            required_years = tuple(range(latest_fy - 5, latest_fy + 1))
            additional_years = [str(year) for year in required_years if str(year) not in built_years]
            for year in additional_years:
                build_year(year)
        final_builds = tuple(builds)
        final_observations = tuple(item for build in final_builds for item in build.result.observations)
        final = build_multi_period_result(
            ticker=str(ticker),
            requested_as_of=cutoff_text,
            observations=final_observations,
            company_family=family or None,
            corp_code=resolved_corp_code,
            periodization_builds=final_builds,
        )
        plan_diagnostic = {
            "type": "ANNUAL_WINDOW_BUILD_PLAN",
            "initial_requested_years": list(years),
            "latest_available_fy": initial.latest_fy,
            "additional_historical_fy_builds": additional_years,
            "built_years": list(built_years),
        }
        return replace(final, diagnostics=final.diagnostics + (plan_diagnostic,))


def build_multi_period_result(
    *,
    ticker: str,
    requested_as_of: str | date,
    observations: PeriodizationResult | Iterable[PeriodizedFinancialObservation],
    company_family: str | None = None,
    corp_code: str | None = None,
    quarter_window: int = 16,
    quarter_display: int = 12,
    annual_window: int = 6,
    annual_display: int = 5,
    periodization_builds: Iterable[PeriodizationBuild] = (),
) -> MultiPeriodFundamentalsResult:
    """Create a result from canonical observations without any network call.

    The helper is intentionally public so focused tests and offline tooling
    can exercise the boundary with committed/synthetic canonical fixtures.
    """

    cutoff_text = _as_of(requested_as_of)
    cutoff = date.fromisoformat(cutoff_text)
    source = tuple(observations.observations if isinstance(observations, PeriodizationResult) else observations)
    source = tuple(item for item in source if isinstance(item, PeriodizedFinancialObservation))
    family = _family_text(company_family) or next(
        (_family_text(item.company_family) for item in source if item.company_family), "UNKNOWN"
    )
    resolved_corp_code = corp_code or next((str(item.corp_code) for item in source if item.corp_code), "")
    diagnostics: list[Mapping[str, Any]] = []

    # Future observations remain in diagnostics but never enter a coverage
    # slot or the public canonical windows.
    eligible: list[PeriodizedFinancialObservation] = []
    for item in source:
        if _pit_eligible(item, cutoff):
            eligible.append(item)
        else:
            diagnostics.append({
                "type": "FUTURE_OR_UNAVAILABLE_SOURCE_EXCLUDED",
                "fiscal_year": item.fiscal_year,
                "fiscal_period": item.fiscal_period,
                "metric": item.metric,
                "anchor_rcept_no": item.anchor_rcept_no,
                "pit_available_from": item.pit_available_from or item.anchor_rcept_dt,
            })

    if family == CompanyFamily.FINANCIAL.value:
        return _financial_result(
            ticker=str(ticker), corp_code=resolved_corp_code, family=family,
            requested_as_of=cutoff_text, source=tuple(eligible),
            quarter_window=quarter_window, quarter_display=quarter_display,
            annual_window=annual_window, annual_display=annual_display,
            diagnostics=tuple(diagnostics),
        )

    quarter_groups: dict[tuple[int, int], list[PeriodizedFinancialObservation]] = {}
    annual_groups: dict[int, list[PeriodizedFinancialObservation]] = {}
    for item in eligible:
        identity = _quarter_identity(item.fiscal_year, item.fiscal_period)
        period_text = str(item.fiscal_period).upper()
        if identity is not None and (period_text in QUARTER_PERIODS or period_text.endswith("_END")) \
                and period_text != "FY_END":
            quarter_groups.setdefault(identity, []).append(item)
        annual = _annual_identity(item.fiscal_year, item.fiscal_period)
        if annual is not None:
            annual_groups.setdefault(annual, []).append(item)

    quarter_end = max(quarter_groups) if quarter_groups else _as_of_quarter(cutoff)
    quarter_identities = _sequence_quarters(quarter_end, quarter_window)
    annual_end = max(annual_groups) if annual_groups else cutoff.year
    annual_years = tuple(range(annual_end - annual_window + 1, annual_end + 1))
    quarter_slots = tuple(
        _slot_for_quarter(identity, quarter_groups.get(identity, ()))
        for identity in quarter_identities
    )
    annual_slots = tuple(
        _slot_for_annual(year, annual_groups.get(year, ()))
        for year in annual_years
    )

    quarter_observations = tuple(
        item for identity in quarter_identities for item in sorted(
            quarter_groups.get(identity, ()), key=_observation_sort_key
        )
    )
    annual_observations = tuple(
        item for year in annual_years for item in sorted(
            annual_groups.get(year, ()), key=_observation_sort_key
        )
    )
    latest_quarter = _quarter_label(quarter_end) if quarter_groups else None
    latest_fy = str(annual_end) if annual_groups else None
    diagnostics.extend(_metric_gap_diagnostics(quarter_slots))
    diagnostics.extend(_metric_gap_diagnostics(annual_slots))
    quarter_basis_ok, quarter_currency_ok, quarter_coherence = _window_coherence(quarter_observations)
    annual_basis_ok, annual_currency_ok, annual_coherence = _window_coherence(annual_observations)
    diagnostics.extend(quarter_coherence)
    diagnostics.extend(annual_coherence)
    diagnostics.extend(_build_diagnostics(periodization_builds))
    quarter_coverage = _coverage(
        quarter_slots, requested_count=quarter_window, display_count=quarter_display,
        comparison_label=f"{quarter_window}Q", display_label=f"{quarter_display}Q",
        basis_consistent=quarter_basis_ok, currency_consistent=quarter_currency_ok,
    )
    annual_coverage = _coverage(
        annual_slots, requested_count=annual_window, display_count=annual_display,
        comparison_label=f"{annual_window}FY", display_label=f"{annual_display}FY",
        basis_consistent=annual_basis_ok, currency_consistent=annual_currency_ok,
    )
    return MultiPeriodFundamentalsResult(
        ticker=str(ticker), corp_code=resolved_corp_code, company_family=family,
        requested_as_of=cutoff_text, quarters=quarter_observations,
        annuals=annual_observations, quarter_slots=quarter_slots,
        annual_slots=annual_slots, quarter_coverage=quarter_coverage,
        annual_coverage=annual_coverage, latest_quarter=latest_quarter,
        latest_fy=latest_fy, diagnostics=tuple(diagnostics),
        periodization_builds=tuple(periodization_builds),
    )


# Short aliases keep the boundary discoverable without introducing another
# implementation hierarchy.
MultiPeriodProvider = MultiPeriodFundamentalsProvider


def build_multi_period_fundamentals(
    ticker: str,
    requested_as_of: str | date,
    observations: PeriodizationResult | Iterable[PeriodizedFinancialObservation],
    **kwargs: Any,
) -> MultiPeriodFundamentalsResult:
    """Positional-friendly wrapper around :func:`build_multi_period_result`."""

    return build_multi_period_result(
        ticker=ticker, requested_as_of=requested_as_of,
        observations=observations, **kwargs,
    )


def _as_of_quarter(cutoff: date) -> tuple[int, int]:
    return cutoff.year, min(4, ((cutoff.month - 1) // 3) + 1)


def _sequence_quarters(end: tuple[int, int], count: int) -> tuple[tuple[int, int], ...]:
    year, quarter = end
    values: list[tuple[int, int]] = []
    for offset in range(max(0, count)):
        index = year * 4 + quarter - 1 - (count - 1 - offset)
        values.append((index // 4, (index % 4) + 1))
    return tuple(values)


def _observation_sort_key(item: PeriodizedFinancialObservation) -> tuple[str, str, str, str]:
    return (str(item.metric), str(item.resolution_status), str(item.anchor_rcept_dt), str(item.anchor_rcept_no))


def _slot_for_quarter(
    identity: tuple[int, int],
    items: Iterable[PeriodizedFinancialObservation],
) -> MultiPeriodCoverageSlot:
    values = tuple(items)
    status, reason = _observation_status(values)
    metrics = tuple(sorted({str(item.metric) for item in values}))
    missing_metrics = tuple(sorted(set(QUARTER_REQUIRED_METRICS) - set(metrics)))
    if missing_metrics:
        reason = "REQUIRED_METRIC_MISSING" if status == READY else \
            f"{reason};REQUIRED_METRIC_MISSING" if reason else "REQUIRED_METRIC_MISSING"
        if status == READY:
            status = DATA_UNAVAILABLE
    return MultiPeriodCoverageSlot(
        identity=_quarter_label(identity), fiscal_year=str(identity[0]),
        fiscal_period=f"Q{identity[1]}", status=status, reason=reason,
        observation_count=len(values), metrics=metrics, missing_metrics=missing_metrics,
    )


def _slot_for_annual(
    year: int,
    items: Iterable[PeriodizedFinancialObservation],
) -> MultiPeriodCoverageSlot:
    values = tuple(items)
    status, reason = _observation_status(values)
    metrics = tuple(sorted({str(item.metric) for item in values}))
    missing_metrics = tuple(sorted(set(ANNUAL_REQUIRED_METRICS) - set(metrics)))
    if missing_metrics:
        reason = "REQUIRED_METRIC_MISSING" if status == READY else \
            f"{reason};REQUIRED_METRIC_MISSING" if reason else "REQUIRED_METRIC_MISSING"
        if status == READY:
            status = DATA_UNAVAILABLE
    return MultiPeriodCoverageSlot(
        identity=str(year), fiscal_year=str(year), fiscal_period="FY",
        status=status, reason=reason, observation_count=len(values),
        metrics=metrics, missing_metrics=missing_metrics,
    )


def _metric_gap_diagnostics(
    slots: Sequence[MultiPeriodCoverageSlot],
) -> list[Mapping[str, Any]]:
    diagnostics: list[Mapping[str, Any]] = []
    for slot in slots:
        if slot.missing_metrics:
            diagnostics.append({
                "type": "CANONICAL_METRIC_MISSING",
                "identity": slot.identity,
                "missing_metrics": list(slot.missing_metrics),
            })
    return diagnostics


def _window_coherence(
    observations: Sequence[PeriodizedFinancialObservation],
) -> tuple[bool, bool, list[Mapping[str, Any]]]:
    """Check cross-period basis/currency without recalculating any metric."""

    by_metric: dict[str, list[PeriodizedFinancialObservation]] = {}
    for item in observations:
        if item.resolution_status == READY:
            by_metric.setdefault(str(item.metric), []).append(item)
    diagnostics: list[Mapping[str, Any]] = []
    basis_ok = True
    currency_ok = True
    for metric, items in sorted(by_metric.items()):
        bases = {item.fs_div_used for item in items}
        currencies = {item.currency for item in items}
        if len(bases) > 1:
            basis_ok = False
            diagnostics.append({
                "type": "BASIS_MISMATCH_WINDOW", "metric": metric,
                "values": sorted(str(value) for value in bases),
            })
        if len(currencies) > 1:
            currency_ok = False
            diagnostics.append({
                "type": "CURRENCY_MISMATCH_WINDOW", "metric": metric,
                "values": sorted(str(value) for value in currencies),
            })
    return basis_ok, currency_ok, diagnostics


def _build_diagnostics(builds: Iterable[PeriodizationBuild]) -> list[Mapping[str, Any]]:
    diagnostics: list[Mapping[str, Any]] = []
    for build in builds:
        for item in build.skipped_anchors:
            diagnostics.append({
                "type": "PERIODIZATION_SKIPPED_ANCHOR",
                "fiscal_year": build.fiscal_year,
                **dict(item),
            })
    return diagnostics


def _financial_result(
    *,
    ticker: str,
    corp_code: str,
    family: str,
    requested_as_of: str,
    source: tuple[PeriodizedFinancialObservation, ...],
    quarter_window: int,
    quarter_display: int,
    annual_window: int,
    annual_display: int,
    diagnostics: tuple[Mapping[str, Any], ...],
) -> MultiPeriodFundamentalsResult:
    cutoff = date.fromisoformat(requested_as_of)
    q_end = _as_of_quarter(cutoff)
    quarter_slots = tuple(
        MultiPeriodCoverageSlot(_quarter_label(identity), str(identity[0]), f"Q{identity[1]}", "NOT_APPLICABLE", "FINANCIAL_COMPANY")
        for identity in _sequence_quarters(q_end, quarter_window)
    )
    annual_slots = tuple(
        MultiPeriodCoverageSlot(str(year), str(year), "FY", "NOT_APPLICABLE", "FINANCIAL_COMPANY")
        for year in range(cutoff.year - annual_window + 1, cutoff.year + 1)
    )
    return MultiPeriodFundamentalsResult(
        ticker=ticker, corp_code=corp_code, company_family=family,
        requested_as_of=requested_as_of, quarters=(), annuals=(),
        quarter_slots=quarter_slots, annual_slots=annual_slots,
        quarter_coverage=_coverage(
            quarter_slots, requested_count=quarter_window, display_count=quarter_display,
            comparison_label=f"{quarter_window}Q", display_label=f"{quarter_display}Q", not_applicable=True,
        ),
        annual_coverage=_coverage(
            annual_slots, requested_count=annual_window, display_count=annual_display,
            comparison_label=f"{annual_window}FY", display_label=f"{annual_display}FY", not_applicable=True,
        ),
        latest_quarter=None, latest_fy=None,
        diagnostics=diagnostics + ({"type": "FINANCIAL_NOT_APPLICABLE", "company_family": family},),
    )


__all__ = [
    "CoverageMetadata",
    "MultiPeriodCoverageSlot",
    "MultiPeriodFundamentalsResult",
    "MultiPeriodFundamentalsProvider",
    "MultiPeriodProvider",
    "QUARTER_REQUIRED_METRICS",
    "ANNUAL_REQUIRED_METRICS",
    "OPTIONAL_ANNUAL_METRICS",
    "REQUIRED_SOURCE_METRICS",
    "build_multi_period_result",
    "build_multi_period_fundamentals",
]
