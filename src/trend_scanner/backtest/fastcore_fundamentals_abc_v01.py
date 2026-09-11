"""FastCore Fundamentals ABC rules for the bounded V01 backtest.

This module is intentionally independent from the legacy F4/TTM evaluator.
It consumes canonical PIT periodization observations and exposes small,
deterministic entry/quarter-event functions that are easy to test without a
network or a market-data fixture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable, Mapping, Sequence

from trend_scanner.fundamentals.period_models import (
    BASIS_MISMATCH,
    DATA_UNAVAILABLE,
    PERIOD_AMBIGUOUS,
    READY,
    STANDALONE_QUARTER,
    PeriodizedFinancialObservation,
)


ANNUAL_REVENUE_MIN = 50_000_000_000
ANNUAL_OPERATING_INCOME_MIN = 4_000_000_000
QUARTER_REVENUE_MIN = 15_000_000_000
QUARTER_OPERATING_INCOME_MIN = 1_000_000_000
QUARTER_REVENUE_GROWTH_MIN_PCT = 5.0
OPERATING_INCOME_GROWTH_MIN_PCT = 5.0
SUPPORTED_QUARTERS = ("Q1", "Q2", "Q3", "Q4")
PREVIOUS_QUARTER = {
    "Q1": (None, "Q4"),
    "Q2": (0, "Q1"),
    "Q3": (0, "Q2"),
    "Q4": (0, "Q3"),
}


class ABCEvaluationError(RuntimeError):
    """A parser/provider failure that must not be converted to unavailable."""


def _date_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value.isoformat()
    raw = str(value).strip()
    if len(raw) >= 8 and raw[:8].isdigit() and (len(raw) == 8 or raw[8] in {"T", " "}):
        raw = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    text = raw[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return text or None


def _as_date(value: Any) -> date | None:
    text = _date_text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _number(value: Any) -> int | float | None:
    if value in (None, "", "-", "—", "–") or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _pct(current: Any, prior: Any) -> float | None:
    current_value = _number(current)
    prior_value = _number(prior)
    if current_value is None or prior_value in (None, 0):
        return None
    return round((float(current_value) / float(prior_value) - 1.0) * 100.0, 12)


def _is_krw(value: Any) -> bool:
    return str(value or "").strip().upper() in {"KRW", "ISO4217_KRW", "ISO4217:KRW"}


def _period_year(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _obs_key(item: PeriodizedFinancialObservation) -> tuple[str, str, str, str]:
    return (str(item.fiscal_year), str(item.fiscal_period), str(item.metric), str(item.anchor_rcept_no))


def _pit_ready(item: Any, as_of: date) -> bool:
    available = _as_date(getattr(item, "pit_available_from", None) or getattr(item, "anchor_rcept_dt", None))
    return available is not None and available <= as_of and str(getattr(item, "resolution_status", "")) == READY


def _latest_version(
    observations: Iterable[PeriodizedFinancialObservation],
    *,
    fiscal_year: int,
    fiscal_period: str,
    metric: str,
    as_of: date,
) -> tuple[PeriodizedFinancialObservation | None, str | None]:
    values = [
        item for item in observations
        if _period_year(getattr(item, "fiscal_year", None)) == fiscal_year
        and str(getattr(item, "fiscal_period", "")) == fiscal_period
        and str(getattr(item, "metric", "")) == metric
        and _as_date(getattr(item, "pit_available_from", None) or getattr(item, "anchor_rcept_dt", None)) is not None
        and (_as_date(getattr(item, "pit_available_from", None) or getattr(item, "anchor_rcept_dt", None)) <= as_of)
    ]
    if not values:
        return None, DATA_UNAVAILABLE
    latest_date = max(_as_date(item.pit_available_from or item.anchor_rcept_dt) for item in values)
    latest = [item for item in values if _as_date(item.pit_available_from or item.anchor_rcept_dt) == latest_date]
    anchor_ids = {str(item.anchor_rcept_no) for item in latest}
    if len(anchor_ids) != 1:
        return None, PERIOD_AMBIGUOUS
    # A latest source that is explicitly non-ready is not replaced by an older
    # source. It is a PIT data gap, not permission to look through the gap.
    ready = [item for item in latest if str(item.resolution_status) == READY and _number(item.value) is not None]
    if len(ready) != len(latest):
        statuses = {str(item.resolution_status) for item in latest}
        return None, next(iter(statuses - {READY}), DATA_UNAVAILABLE)
    if len(ready) != 1:
        return None, PERIOD_AMBIGUOUS
    return ready[0], None


def _basis_currency_consistent(items: Sequence[PeriodizedFinancialObservation]) -> bool:
    values = [item for item in items if item is not None]
    if not values:
        return False
    bases = {str(item.fs_div_used or "") for item in values}
    currencies = {str(item.currency or "") for item in values}
    return len(bases) == 1 and len(currencies) == 1 and _is_krw(next(iter(currencies)))


def _source_dates(items: Sequence[PeriodizedFinancialObservation]) -> str:
    values = sorted({
        _date_text(item.pit_available_from or item.anchor_rcept_dt)
        for item in items if item is not None and _date_text(item.pit_available_from or item.anchor_rcept_dt)
    })
    return "|".join(values)


@dataclass(frozen=True)
class ABCEntryEvaluation:
    ticker: str
    company_family: str
    as_of: str
    latest_fy: int | None = None
    annual_revenue: int | float | None = None
    annual_operating_income: int | float | None = None
    latest_quarter: str | None = None
    quarter_revenue: int | float | None = None
    quarter_operating_income: int | float | None = None
    prior_year_same_quarter: str | None = None
    prior_year_quarter_revenue: int | float | None = None
    prior_year_quarter_operating_income: int | float | None = None
    revenue_yoy_pct: float | None = None
    operating_income_yoy_pct: float | None = None
    operating_income_growth_mode: str | None = None
    annual_revenue_pass: bool = False
    annual_operating_income_pass: bool = False
    quarter_revenue_pass: bool = False
    quarter_operating_income_pass: bool = False
    revenue_growth_pass: bool = False
    operating_income_growth_pass: bool = False
    abc_entry_evaluable: bool = False
    abc_entry_gate_pass: bool = False
    reject_reasons: tuple[str, ...] = ()
    selected_source_receipt_dates: str = ""
    status: str = "DATA_UNAVAILABLE"

    def to_row(self, *, candidate: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "candidate_id": candidate.get("candidate_id"),
            "ticker": candidate.get("ticker"),
            "isu_cd": candidate.get("isu_cd"),
            "market": candidate.get("market"),
            "candidate_signal_date": candidate.get("candidate_signal_date"),
            "entry_signal_information_date": candidate.get("entry_signal_information_date"),
            "company_family": self.company_family,
            "latest_fy": self.latest_fy,
            "annual_revenue": self.annual_revenue,
            "annual_operating_income": self.annual_operating_income,
            "latest_quarter": self.latest_quarter,
            "quarter_revenue": self.quarter_revenue,
            "quarter_operating_income": self.quarter_operating_income,
            "prior_year_same_quarter": self.prior_year_same_quarter,
            "prior_year_quarter_revenue": self.prior_year_quarter_revenue,
            "prior_year_quarter_operating_income": self.prior_year_quarter_operating_income,
            "revenue_yoy_pct": self.revenue_yoy_pct,
            "operating_income_yoy_pct": self.operating_income_yoy_pct,
            "operating_income_growth_mode": self.operating_income_growth_mode,
            "annual_revenue_pass": self.annual_revenue_pass,
            "annual_operating_income_pass": self.annual_operating_income_pass,
            "quarter_revenue_pass": self.quarter_revenue_pass,
            "quarter_operating_income_pass": self.quarter_operating_income_pass,
            "revenue_growth_pass": self.revenue_growth_pass,
            "operating_income_growth_pass": self.operating_income_growth_pass,
            "abc_entry_evaluable": self.abc_entry_evaluable,
            "abc_entry_gate_pass": self.abc_entry_gate_pass,
            "reject_reasons": "|".join(self.reject_reasons),
            "selected_source_receipt_dates": self.selected_source_receipt_dates,
            "status": self.status,
        }


def evaluate_entry(
    ticker: str,
    company_family: str,
    observations: Sequence[PeriodizedFinancialObservation],
    *,
    as_of: str | date,
) -> ABCEntryEvaluation:
    """Evaluate the V01 entry gate using only PIT-ready canonical observations."""

    cutoff = _as_date(as_of)
    if cutoff is None:
        raise ABCEvaluationError(f"invalid ABC entry as_of={as_of!r}")
    family = str(company_family or "UNKNOWN")
    if family != "NON_FINANCIAL":
        status = "NOT_APPLICABLE" if family == "FINANCIAL" else DATA_UNAVAILABLE
        return ABCEntryEvaluation(ticker=ticker, company_family=family, as_of=cutoff.isoformat(), status=status,
                                  reject_reasons=(status,))

    # Pick the latest completed FY by fiscal year, but only from a source
    # available at the candidate information date.
    annual_selection: tuple[int, PeriodizedFinancialObservation | None, PeriodizedFinancialObservation | None] | None = None
    years = sorted({_period_year(item.fiscal_year) for item in observations if _period_year(item.fiscal_year) is not None}, reverse=True)
    for year in years:
        revenue, rev_status = _latest_version(observations, fiscal_year=year, fiscal_period="FY", metric="revenue", as_of=cutoff)
        operating, op_status = _latest_version(observations, fiscal_year=year, fiscal_period="FY", metric="operating_income", as_of=cutoff)
        if revenue is not None or operating is not None:
            annual_selection = (year, revenue, operating)
            break
    if annual_selection is None:
        return ABCEntryEvaluation(ticker=ticker, company_family=family, as_of=cutoff.isoformat(), status=DATA_UNAVAILABLE,
                                  reject_reasons=("ANNUAL_DATA_UNAVAILABLE",))
    latest_fy, annual_revenue, annual_operating = annual_selection
    if annual_revenue is None or annual_operating is None:
        return ABCEntryEvaluation(ticker=ticker, company_family=family, as_of=cutoff.isoformat(), latest_fy=latest_fy,
                                  annual_revenue=annual_revenue.value if annual_revenue else None,
                                  annual_operating_income=annual_operating.value if annual_operating else None,
                                  status=DATA_UNAVAILABLE, reject_reasons=("ANNUAL_DATA_UNAVAILABLE",),
                                  selected_source_receipt_dates=_source_dates(tuple(item for item in (annual_revenue, annual_operating) if item)))

    quarter_candidates: list[tuple[date, int, str, PeriodizedFinancialObservation, PeriodizedFinancialObservation]] = []
    for year in years:
        for quarter in SUPPORTED_QUARTERS:
            revenue, _ = _latest_version(observations, fiscal_year=year, fiscal_period=quarter, metric="revenue", as_of=cutoff)
            operating, _ = _latest_version(observations, fiscal_year=year, fiscal_period=quarter, metric="operating_income", as_of=cutoff)
            if revenue is None or operating is None or not _basis_currency_consistent((revenue, operating)):
                continue
            end = _as_date(revenue.period_end) or date.min
            quarter_candidates.append((end, year, quarter, revenue, operating))
    if not quarter_candidates:
        return ABCEntryEvaluation(ticker=ticker, company_family=family, as_of=cutoff.isoformat(), latest_fy=latest_fy,
                                  annual_revenue=annual_revenue.value, annual_operating_income=annual_operating.value,
                                  status=DATA_UNAVAILABLE, reject_reasons=("QUARTER_DATA_UNAVAILABLE",),
                                  selected_source_receipt_dates=_source_dates((annual_revenue, annual_operating)))
    _, quarter_year, quarter, quarter_revenue, quarter_operating = max(quarter_candidates, key=lambda value: (value[0], value[1], value[2]))
    prior_year = quarter_year - 1
    prior_revenue, prior_rev_status = _latest_version(observations, fiscal_year=prior_year, fiscal_period=quarter, metric="revenue", as_of=cutoff)
    prior_operating, prior_op_status = _latest_version(observations, fiscal_year=prior_year, fiscal_period=quarter, metric="operating_income", as_of=cutoff)
    selected = (annual_revenue, annual_operating, quarter_revenue, quarter_operating, prior_revenue, prior_operating)
    reasons: list[str] = []
    if prior_revenue is None or prior_operating is None:
        reasons.append("PRIOR_YEAR_SAME_QUARTER_UNAVAILABLE")
    annual_consistent = _basis_currency_consistent((annual_revenue, annual_operating))
    quarter_consistent = prior_revenue is not None and prior_operating is not None \
        and _basis_currency_consistent((quarter_revenue, quarter_operating, prior_revenue, prior_operating))
    if not annual_consistent:
        reasons.append("ANNUAL_BASIS_OR_CURRENCY_MISMATCH")
    if prior_revenue is not None and prior_operating is not None and not quarter_consistent:
        reasons.append(BASIS_MISMATCH if {str(item.fs_div_used) for item in (quarter_revenue, quarter_operating, prior_revenue, prior_operating)} else "CURRENCY_MISMATCH")
    revenue_yoy = _pct(quarter_revenue.value, prior_revenue.value if prior_revenue else None)
    operating_yoy = _pct(quarter_operating.value, prior_operating.value if prior_operating else None)
    annual_revenue_pass = _number(annual_revenue.value) is not None and annual_revenue.value >= ANNUAL_REVENUE_MIN
    annual_operating_pass = _number(annual_operating.value) is not None and annual_operating.value >= ANNUAL_OPERATING_INCOME_MIN
    quarter_revenue_pass = _number(quarter_revenue.value) is not None and quarter_revenue.value >= QUARTER_REVENUE_MIN
    quarter_operating_pass = _number(quarter_operating.value) is not None and quarter_operating.value >= QUARTER_OPERATING_INCOME_MIN
    revenue_growth_pass = revenue_yoy is not None and revenue_yoy >= QUARTER_REVENUE_GROWTH_MIN_PCT
    growth_mode = None
    if prior_operating is not None:
        if quarter_operating.value is not None and prior_operating.value <= 0 < quarter_operating.value:
            growth_mode = "TURNAROUND_TO_PROFIT"
            operating_growth_pass = True
        else:
            growth_mode = "YOY_PERCENT"
            operating_growth_pass = operating_yoy is not None and operating_yoy >= OPERATING_INCOME_GROWTH_MIN_PCT
    else:
        operating_growth_pass = False
    checks = {
        "ANNUAL_REVENUE_BELOW_MIN": annual_revenue_pass,
        "ANNUAL_OPERATING_INCOME_BELOW_MIN": annual_operating_pass,
        "QUARTER_REVENUE_BELOW_MIN": quarter_revenue_pass,
        "QUARTER_OPERATING_INCOME_BELOW_MIN": quarter_operating_pass,
        "QUARTER_REVENUE_GROWTH_BELOW_MIN": revenue_growth_pass,
        "OPERATING_INCOME_GROWTH_BELOW_MIN": operating_growth_pass,
    }
    reasons.extend(key for key, passed in checks.items() if not passed)
    evaluable = prior_revenue is not None and prior_operating is not None and annual_consistent and quarter_consistent
    gate = evaluable and not any(not passed for passed in checks.values())
    return ABCEntryEvaluation(
        ticker=ticker, company_family=family, as_of=cutoff.isoformat(), latest_fy=latest_fy,
        annual_revenue=annual_revenue.value, annual_operating_income=annual_operating.value,
        latest_quarter=f"{quarter_year}{quarter}", quarter_revenue=quarter_revenue.value,
        quarter_operating_income=quarter_operating.value, prior_year_same_quarter=f"{prior_year}{quarter}",
        prior_year_quarter_revenue=prior_revenue.value if prior_revenue else None,
        prior_year_quarter_operating_income=prior_operating.value if prior_operating else None,
        revenue_yoy_pct=round(revenue_yoy, 6) if revenue_yoy is not None else None,
        operating_income_yoy_pct=round(operating_yoy, 6) if operating_yoy is not None else None,
        operating_income_growth_mode=growth_mode, annual_revenue_pass=annual_revenue_pass,
        annual_operating_income_pass=annual_operating_pass, quarter_revenue_pass=quarter_revenue_pass,
        quarter_operating_income_pass=quarter_operating_pass, revenue_growth_pass=revenue_growth_pass,
        operating_income_growth_pass=operating_growth_pass, abc_entry_evaluable=evaluable,
        abc_entry_gate_pass=gate, reject_reasons=tuple(dict.fromkeys(reasons)),
        selected_source_receipt_dates=_source_dates(tuple(item for item in selected if item)),
        status="PASS" if gate else ("DATA_UNAVAILABLE" if not evaluable else "FILTERED"),
    )


@dataclass(frozen=True)
class ABCQuarterEvent:
    ticker: str
    fiscal_year: int
    quarter: str
    fundamental_information_date: str
    quarter_revenue: int | float | None
    quarter_operating_income: int | float | None
    prior_year_quarter_revenue: int | float | None
    prior_year_quarter_operating_income: int | float | None
    revenue_yoy_pct: float | None
    operating_income_yoy_pct: float | None
    previous_quarter: str | None
    previous_quarter_revenue_declined_yoy: bool | None
    previous_quarter_operating_income_declined_yoy: bool | None
    exit_a_evaluable: bool
    exit_a_triggered: bool
    exit_b_evaluable: bool
    exit_b_triggered: bool
    exit_c_evaluable: bool
    exit_c_triggered: bool
    fundamental_primary_trigger: str | None
    proposed_execution_date: str | None = None
    fundamental_exit_accelerated: bool = False
    selected_source_receipt_dates: str = ""

    @property
    def all_flags(self) -> list[str]:
        return [
            name for name, value in (("FUNDAMENTAL_A_OPERATING_LOSS", self.exit_a_triggered),
                                     ("FUNDAMENTAL_B_SHARP_DECLINE", self.exit_b_triggered),
                                     ("FUNDAMENTAL_C_TWO_CONSECUTIVE_DECLINES", self.exit_c_triggered)) if value
        ]

    def to_row(self, *, trade_id: str) -> dict[str, Any]:
        return {
            "trade_id": trade_id, "ticker": self.ticker, "quarter": f"{self.fiscal_year}{self.quarter}",
            "fundamental_information_date": self.fundamental_information_date,
            "quarter_revenue": self.quarter_revenue, "quarter_operating_income": self.quarter_operating_income,
            "prior_year_quarter_revenue": self.prior_year_quarter_revenue,
            "prior_year_quarter_operating_income": self.prior_year_quarter_operating_income,
            "revenue_yoy_pct": self.revenue_yoy_pct, "operating_income_yoy_pct": self.operating_income_yoy_pct,
            "previous_quarter": self.previous_quarter,
            "previous_quarter_revenue_declined_yoy": self.previous_quarter_revenue_declined_yoy,
            "previous_quarter_operating_income_declined_yoy": self.previous_quarter_operating_income_declined_yoy,
            "exit_a_evaluable": self.exit_a_evaluable, "exit_a_triggered": self.exit_a_triggered,
            "exit_b_evaluable": self.exit_b_evaluable, "exit_b_triggered": self.exit_b_triggered,
            "exit_c_evaluable": self.exit_c_evaluable, "exit_c_triggered": self.exit_c_triggered,
            "fundamental_primary_trigger": self.fundamental_primary_trigger,
            "proposed_execution_date": self.proposed_execution_date,
            "fundamental_exit_accelerated": self.fundamental_exit_accelerated,
            "all_flags": "|".join(self.all_flags),
            "selected_source_receipt_dates": self.selected_source_receipt_dates,
        }


def _quarter_previous(year: int, quarter: str) -> tuple[int, str] | None:
    if quarter == "Q1":
        return year - 1, "Q4"
    if quarter in {"Q2", "Q3", "Q4"}:
        return year, {"Q2": "Q1", "Q3": "Q2", "Q4": "Q3"}[quarter]
    return None


def evaluate_quarter_event(
    ticker: str,
    observations: Sequence[PeriodizedFinancialObservation],
    *,
    fiscal_year: int,
    quarter: str,
    as_of: str | date,
) -> ABCQuarterEvent | None:
    """Evaluate one new PIT quarter vintage. Return None when no event data exists."""

    cutoff = _as_date(as_of)
    if cutoff is None or quarter not in SUPPORTED_QUARTERS:
        raise ABCEvaluationError(f"invalid quarter event: {ticker}/{fiscal_year}/{quarter}/{as_of}")
    revenue, _ = _latest_version(observations, fiscal_year=fiscal_year, fiscal_period=quarter, metric="revenue", as_of=cutoff)
    operating, _ = _latest_version(observations, fiscal_year=fiscal_year, fiscal_period=quarter, metric="operating_income", as_of=cutoff)
    if revenue is None or operating is None or not _basis_currency_consistent((revenue, operating)):
        return None
    prior_revenue, _ = _latest_version(observations, fiscal_year=fiscal_year - 1, fiscal_period=quarter, metric="revenue", as_of=cutoff)
    prior_operating, _ = _latest_version(observations, fiscal_year=fiscal_year - 1, fiscal_period=quarter, metric="operating_income", as_of=cutoff)
    source_items = [revenue, operating, prior_revenue, prior_operating]
    rev_yoy = _pct(revenue.value, prior_revenue.value if prior_revenue else None)
    op_yoy = _pct(operating.value, prior_operating.value if prior_operating else None)
    exit_a_evaluable = True
    exit_a_triggered = _number(operating.value) is not None and operating.value < 0
    exit_b_evaluable = (prior_revenue is not None and prior_operating is not None
                        and _basis_currency_consistent(tuple(item for item in source_items if item))
                        and prior_operating.value > 0 and rev_yoy is not None and op_yoy is not None)
    exit_b_triggered = bool(exit_b_evaluable and rev_yoy <= -10.0 and op_yoy <= -20.0)

    previous = _quarter_previous(fiscal_year, quarter)
    previous_rev_declined = None
    previous_op_declined = None
    exit_c_evaluable = False
    if previous is not None:
        prev_year, prev_q = previous
        prev_rev, _ = _latest_version(observations, fiscal_year=prev_year, fiscal_period=prev_q, metric="revenue", as_of=cutoff)
        prev_op, _ = _latest_version(observations, fiscal_year=prev_year, fiscal_period=prev_q, metric="operating_income", as_of=cutoff)
        prev_prior_rev, _ = _latest_version(observations, fiscal_year=prev_year - 1, fiscal_period=prev_q, metric="revenue", as_of=cutoff)
        prev_prior_op, _ = _latest_version(observations, fiscal_year=prev_year - 1, fiscal_period=prev_q, metric="operating_income", as_of=cutoff)
        prev_basis_ready = all(item is not None for item in (prev_rev, prev_op, prev_prior_rev, prev_prior_op))
        if prev_basis_ready:
            prev_basis_ready = _basis_currency_consistent((prev_rev, prev_op, prev_prior_rev, prev_prior_op))
        if prev_basis_ready:
            previous_rev_declined = prev_rev.value < prev_prior_rev.value
            previous_op_declined = prev_op.value < prev_prior_op.value
    current_rev_declined = prior_revenue is not None and revenue.value < prior_revenue.value
    current_op_declined = prior_operating is not None and operating.value < prior_operating.value
    exit_c_evaluable = bool(previous_rev_declined is not None and previous_op_declined is not None and prior_revenue is not None and prior_operating is not None)
    exit_c_triggered = bool(exit_c_evaluable and current_rev_declined and current_op_declined
                            and previous_rev_declined and previous_op_declined)
    flags = []
    if exit_a_triggered:
        flags.append("FUNDAMENTAL_A_OPERATING_LOSS")
    if exit_b_triggered:
        flags.append("FUNDAMENTAL_B_SHARP_DECLINE")
    if exit_c_triggered:
        flags.append("FUNDAMENTAL_C_TWO_CONSECUTIVE_DECLINES")
    information_date = max(_as_date(item.pit_available_from or item.anchor_rcept_dt) for item in (revenue, operating))
    return ABCQuarterEvent(
        ticker=ticker, fiscal_year=fiscal_year, quarter=quarter, fundamental_information_date=information_date.isoformat(),
        quarter_revenue=revenue.value, quarter_operating_income=operating.value,
        prior_year_quarter_revenue=prior_revenue.value if prior_revenue else None,
        prior_year_quarter_operating_income=prior_operating.value if prior_operating else None,
        revenue_yoy_pct=round(rev_yoy, 6) if rev_yoy is not None else None,
        operating_income_yoy_pct=round(op_yoy, 6) if op_yoy is not None else None,
        previous_quarter=f"{previous[0]}{previous[1]}" if previous else None,
        previous_quarter_revenue_declined_yoy=previous_rev_declined,
        previous_quarter_operating_income_declined_yoy=previous_op_declined,
        exit_a_evaluable=exit_a_evaluable, exit_a_triggered=exit_a_triggered,
        exit_b_evaluable=exit_b_evaluable, exit_b_triggered=exit_b_triggered,
        exit_c_evaluable=exit_c_evaluable, exit_c_triggered=exit_c_triggered,
        fundamental_primary_trigger=flags[0] if flags else None,
        selected_source_receipt_dates=_source_dates(tuple(item for item in source_items if item)),
    )


def event_versions(observations: Sequence[PeriodizedFinancialObservation], *, cutoff: str | date) -> list[ABCQuarterEvent]:
    """Return unique quarter-vintage events in chronological information order."""

    end = _as_date(cutoff)
    if end is None:
        raise ABCEvaluationError(f"invalid event cutoff={cutoff!r}")
    keys = sorted({
        (_period_year(item.fiscal_year), str(item.fiscal_period), _as_date(item.pit_available_from or item.anchor_rcept_dt))
        for item in observations
        if _period_year(item.fiscal_year) is not None
        and str(item.fiscal_period) in SUPPORTED_QUARTERS
        and _as_date(item.pit_available_from or item.anchor_rcept_dt) is not None
        and _as_date(item.pit_available_from or item.anchor_rcept_dt) <= end
    }, key=lambda value: (value[2], value[0], value[1]))
    result: list[ABCQuarterEvent] = []
    seen: set[tuple[str, str]] = set()
    for year, quarter, available in keys:
        event = evaluate_quarter_event(observations[0].ticker if observations else "", observations,
                                       fiscal_year=int(year), quarter=quarter, as_of=available)
        if event is None or not event.all_flags:
            continue
        key = (event.fundamental_information_date, f"{year}{quarter}")
        if key not in seen:
            seen.add(key)
            result.append(event)
    return result


def select_exit_candidate(
    fastcore_execution_date: str | date | None,
    fundamental_events: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any] | None, bool]:
    """Apply earliest-execution selection; FastCore wins an execution tie."""

    fastcore = _as_date(fastcore_execution_date) if fastcore_execution_date not in (None, "") else None
    parsed = []
    for event in fundamental_events:
        execution = _as_date(event.get("proposed_execution_date"))
        if execution is not None:
            parsed.append((execution, event))
    if not parsed:
        return None, False
    execution, event = min(parsed, key=lambda item: item[0])
    if fastcore is not None and fastcore <= execution:
        return None, False
    return event, True


def qualifies_quarter(*, candidate_count: int, evaluable_count: int, evaluation_error_count: int) -> bool:
    """Apply the frozen raw-count coverage rule without rounded rates."""

    return bool(candidate_count > 0 and evaluation_error_count == 0
                and evaluable_count / candidate_count >= 0.90)


def first_four_qualifying_quarters(rows: Sequence[Mapping[str, Any]]) -> str | None:
    """Return the earliest quarter starting a four-quarter qualifying run."""

    def quarter_index(label: str) -> int | None:
        text = str(label or "")
        try:
            year, quarter = int(text[:4]), int(text[-1])
            if text[4:5] != "Q" or quarter not in {1, 2, 3, 4}:
                return None
            return year * 4 + quarter - 1
        except (TypeError, ValueError):
            return None

    ordered = sorted((row for row in rows if quarter_index(str(row.get("quarter"))) is not None),
                     key=lambda row: quarter_index(str(row.get("quarter"))))
    for offset in range(max(0, len(ordered) - 3)):
        window = ordered[offset:offset + 4]
        indices = [quarter_index(str(row.get("quarter"))) for row in window]
        if indices != list(range(indices[0], indices[0] + 4)):
            continue
        if all(bool(row.get("qualifying_90pct")) for row in window):
            return str(window[0].get("quarter"))
    return None


def classify_recovery(
    *,
    initial_evaluable: bool,
    final_evaluable: bool,
    opendart_live_used: bool,
    evaluation_error: bool,
    local_cache_missing: bool,
    confirmed_historical_absence: bool,
) -> str:
    """Keep local cache gaps, true absence, and software errors distinct."""

    if initial_evaluable:
        return "ALREADY_EVALUABLE"
    if evaluation_error:
        return "EVALUATION_ERROR"
    if local_cache_missing:
        return "LOCAL_CACHE_MISS_PENDING_OPENDART"
    if final_evaluable and opendart_live_used:
        return "EVALUABLE_RECOVERED_FROM_OPENDART"
    if final_evaluable:
        return "EVALUABLE_RECOVERED_FROM_CACHE"
    if confirmed_historical_absence:
        return "TRUE_DATA_UNAVAILABLE"
    return "TRUE_DATA_UNAVAILABLE"


def future_filing_violations(receipt_dates: Iterable[str], requested_as_of: str) -> int:
    cutoff = _date_text(requested_as_of) or ""
    return sum(1 for value in receipt_dates if str(value)[:10] > cutoff)
