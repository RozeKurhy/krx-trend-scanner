"""Latest-quarter operating-income entry gate for the B Select Core V03 study.

The gate looks at exactly one fiscal quarter: the most recent quarter whose
periodic report had been filed by the entry signal date.  It never falls back
to an older quarter when the latest one cannot be read, and it reads values
only from PIT-ready canonical periodization observations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Mapping, Sequence

from trend_scanner.backtest.fastcore_fundamentals_abc_v01 import (
    _as_date,
    _basis_currency_consistent,
    _latest_version,
)
from trend_scanner.fundamentals.period_models import PeriodizedFinancialObservation


OPERATING_INCOME_MIN_KRW = 2_000_000_000
# YoY >= +1% is checked as 100 * current >= 101 * prior so the boundary is exact.
YOY_MIN_NUMERATOR = 101
YOY_MIN_DENOMINATOR = 100
QUARTER_BY_REPORT_CODE = {"11013": "Q1", "11012": "Q2", "11014": "Q3", "11011": "Q4"}
QUARTER_ORDER = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}

PASS = "PASS"
FAIL = "FAIL"
UNAVAILABLE = "UNAVAILABLE"
BASIS_OR_CURRENCY_MISMATCH = "BASIS_OR_CURRENCY_MISMATCH"


@dataclass(frozen=True)
class DisclosedQuarter:
    fiscal_year: int
    quarter: str
    first_rcept_dt: str

    @property
    def label(self) -> str:
        return f"{self.fiscal_year}{self.quarter}"


def latest_disclosed_quarter(
    filings: Iterable[Mapping[str, Any]],
    *,
    as_of: str | date,
) -> DisclosedQuarter | None:
    """Return the latest fiscal quarter with a periodic report filed by ``as_of``.

    Quarters are ordered by fiscal period, not receipt date, so a late
    correction of an old quarter never becomes the "latest" quarter.  The
    disclosure date of a quarter is its earliest receipt.
    """

    cutoff = _as_date(as_of)
    if cutoff is None:
        raise ValueError(f"invalid as_of={as_of!r}")
    first_receipt: dict[tuple[int, str], date] = {}
    for row in filings:
        quarter = QUARTER_BY_REPORT_CODE.get(str(row.get("reprt_code") or ""))
        received = _as_date(row.get("rcept_dt"))
        try:
            year = int(str(row.get("bsns_year")))
        except (TypeError, ValueError):
            continue
        if quarter is None or received is None or received > cutoff:
            continue
        key = (year, quarter)
        if key not in first_receipt or received < first_receipt[key]:
            first_receipt[key] = received
    if not first_receipt:
        return None
    year, quarter = max(first_receipt, key=lambda key: (key[0], QUARTER_ORDER[key[1]]))
    return DisclosedQuarter(year, quarter, first_receipt[(year, quarter)].isoformat())


def operating_income_rule(
    current: int | float,
    prior: int | float,
    min_operating_income_krw: int = OPERATING_INCOME_MIN_KRW,
) -> tuple[bool, str, list[str]]:
    """Apply the frozen V03 rule to exact KRW values.

    Returns ``(passed, branch, fail_reasons)``.  YoY percent is only meaningful
    for a positive prior; a zero or negative prior uses the turnaround branch.
    """

    reasons: list[str] = []
    if current < 0:
        reasons.append("CURRENT_OPERATING_LOSS")
    if current < min_operating_income_krw:
        reasons.append(f"CURRENT_BELOW_{min_operating_income_krw // 1_000_000_000}B")
    if prior > 0:
        branch = "A_PRIOR_POSITIVE_YOY"
        if YOY_MIN_DENOMINATOR * current < YOY_MIN_NUMERATOR * prior:
            reasons.append("YOY_BELOW_1PCT")
    else:
        branch = "B_PRIOR_ZERO_OR_LOSS"
    return not reasons, branch, reasons


@dataclass(frozen=True)
class OI1QEvaluation:
    status: str
    reason: str
    company_family: str
    latest_quarter: str | None = None
    latest_quarter_first_rcept_dt: str | None = None
    prior_quarter: str | None = None
    current_operating_income: int | float | None = None
    prior_operating_income: int | float | None = None
    current_source_rcept_dt: str | None = None
    prior_source_rcept_dt: str | None = None
    current_fs_div: str | None = None
    prior_fs_div: str | None = None
    rule_branch: str | None = None
    yoy_pct: float | None = None
    fail_reasons: str = ""

    @property
    def available(self) -> bool:
        return self.status in {PASS, FAIL}

    def to_row(self) -> dict[str, Any]:
        return {
            "oi_status": self.status,
            "oi_reason": self.reason,
            "company_family": self.company_family,
            "latest_quarter": self.latest_quarter,
            "latest_quarter_first_rcept_dt": self.latest_quarter_first_rcept_dt,
            "prior_year_same_quarter": self.prior_quarter,
            "current_operating_income": self.current_operating_income,
            "prior_operating_income": self.prior_operating_income,
            "current_source_rcept_dt": self.current_source_rcept_dt,
            "prior_source_rcept_dt": self.prior_source_rcept_dt,
            "current_fs_div": self.current_fs_div,
            "prior_fs_div": self.prior_fs_div,
            "rule_branch": self.rule_branch,
            "yoy_pct": self.yoy_pct,
            "fail_reasons": self.fail_reasons,
        }


def _source_date(item: PeriodizedFinancialObservation) -> str | None:
    value = _as_date(item.pit_available_from or item.anchor_rcept_dt)
    return value.isoformat() if value else None


def evaluate_signal(
    *,
    company_family: str,
    filings: Sequence[Mapping[str, Any]] | None,
    observations: Sequence[PeriodizedFinancialObservation],
    as_of: str | date,
    unavailable_reason: str | None = None,
    min_operating_income_krw: int = OPERATING_INCOME_MIN_KRW,
) -> OI1QEvaluation:
    """Evaluate one entry signal at its exact ``entry_signal_date``.

    ``filings`` must be the complete registry rows for every fiscal year that
    can contain the latest quarter.  ``unavailable_reason`` lets the caller
    report a known source gap (missing company or registry cache) without
    guessing a quarter from incomplete data.
    """

    family = str(company_family or "UNKNOWN")
    if family == "FINANCIAL":
        return OI1QEvaluation(UNAVAILABLE, "FINANCIAL_NOT_APPLICABLE", family)
    if family != "NON_FINANCIAL":
        return OI1QEvaluation(UNAVAILABLE, unavailable_reason or "COMPANY_FAMILY_UNKNOWN", family)
    if unavailable_reason:
        return OI1QEvaluation(UNAVAILABLE, unavailable_reason, family)
    cutoff = _as_date(as_of)
    if cutoff is None:
        raise ValueError(f"invalid as_of={as_of!r}")
    latest = latest_disclosed_quarter(filings or (), as_of=cutoff)
    if latest is None:
        return OI1QEvaluation(UNAVAILABLE, "NO_PERIODIC_REPORT_FILED", family)
    if latest.fiscal_year < cutoff.year - 1:
        return OI1QEvaluation(UNAVAILABLE, "LATEST_QUARTER_STALE", family, latest.label, latest.first_rcept_dt)
    prior_label = f"{latest.fiscal_year - 1}{latest.quarter}"
    current, current_status = _latest_version(
        observations, fiscal_year=latest.fiscal_year, fiscal_period=latest.quarter,
        metric="operating_income", as_of=cutoff,
    )
    prior, prior_status = _latest_version(
        observations, fiscal_year=latest.fiscal_year - 1, fiscal_period=latest.quarter,
        metric="operating_income", as_of=cutoff,
    )
    common = {
        "latest_quarter": latest.label,
        "latest_quarter_first_rcept_dt": latest.first_rcept_dt,
        "prior_quarter": prior_label,
        "current_operating_income": current.value if current else None,
        "prior_operating_income": prior.value if prior else None,
        "current_source_rcept_dt": _source_date(current) if current else None,
        "prior_source_rcept_dt": _source_date(prior) if prior else None,
        "current_fs_div": current.fs_div_used if current else None,
        "prior_fs_div": prior.fs_div_used if prior else None,
    }
    if current is None:
        return OI1QEvaluation(UNAVAILABLE, f"CURRENT_QUARTER_{current_status or 'UNAVAILABLE'}", family, **common)
    if prior is None:
        return OI1QEvaluation(UNAVAILABLE, f"PRIOR_YEAR_QUARTER_{prior_status or 'UNAVAILABLE'}", family, **common)
    if not _basis_currency_consistent((current, prior)):
        return OI1QEvaluation(BASIS_OR_CURRENCY_MISMATCH, BASIS_OR_CURRENCY_MISMATCH, family, **common)
    passed, branch, reasons = operating_income_rule(current.value, prior.value, min_operating_income_krw)
    yoy = (float(current.value) - float(prior.value)) / float(prior.value) * 100.0 if prior.value > 0 else None
    return OI1QEvaluation(
        PASS if passed else FAIL,
        "PASS" if passed else reasons[0],
        family,
        rule_branch=branch,
        yoy_pct=yoy,
        fail_reasons="|".join(reasons),
        **common,
    )
