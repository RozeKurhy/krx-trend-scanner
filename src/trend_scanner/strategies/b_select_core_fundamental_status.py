"""Display-only fundamental status for B Select Core V1 items.

The status is informational.  It never changes B Select Core V1 entry, exit
or lifecycle decisions.  One function produces the value used by the strategy
monitor list, its filter and the stock report current-judgment card.

Evaluation reuses the V03 FIX01 latest-quarter path: the most recent fiscal
quarter filed by ``requested_as_of``, PIT-ready canonical periodization values,
no fallback to an older quarter, and the existing fail-closed policy.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import fields
from pathlib import Path
from typing import Any

from trend_scanner.backtest.b_select_core_oi_1q_v03 import (
    FAIL,
    PASS,
    OI1QEvaluation,
    evaluate_signal,
)
from trend_scanner.fundamentals.period_models import PeriodizedFinancialObservation, READY


EXCELLENT = "우수"
GOOD = "양호"
NEUTRAL = "보통"
CAUTION = "주의"
UNKNOWN = "미상"
FUNDAMENTAL_STATUSES = (EXCELLENT, GOOD, NEUTRAL, CAUTION, UNKNOWN)
EXCELLENT_MIN_OPERATING_INCOME_KRW = 2_000_000_000
PRODUCTION_ROOT = Path("artifacts/fundamentals/production")

_OBSERVATION_FIELDS = {item.name for item in fields(PeriodizedFinancialObservation)}


def classify_fundamental_status(evaluation: OI1QEvaluation) -> str:
    """Map one latest-quarter evaluation to the five display states."""

    current = evaluation.current_operating_income
    if evaluation.latest_quarter is None or current is None:
        return UNKNOWN
    if current <= 0:
        return CAUTION
    prior = evaluation.prior_operating_income
    comparable = evaluation.status in {PASS, FAIL} and prior is not None
    if comparable and current > prior:
        return EXCELLENT if current >= EXCELLENT_MIN_OPERATING_INCOME_KRW else GOOD
    return NEUTRAL


def _observations(f2: Mapping[str, Any]) -> list[PeriodizedFinancialObservation]:
    result = []
    for raw in f2.get("quarters") or []:
        data = {key: value for key, value in raw.items() if key in _OBSERVATION_FIELDS}
        for key in ("source_rcept_nos", "source_rcept_dts", "source_sha256s"):
            if key in data and isinstance(data[key], list):
                data[key] = tuple(data[key])
        result.append(PeriodizedFinancialObservation(**data))
    return result


def _filings(f2: Mapping[str, Any], fiscal_year_end_month: str | None) -> list[dict[str, str]]:
    """Periodic reports eligible at the artifact's requested_as_of.

    The filing registry labels the domestic re-filing of an overseas annual
    report ("해외증권거래소등에신고한사업보고서등의국내신고") as the annual report of
    its receipt year.  For a December fiscal-year company an annual report for
    fiscal year Y is always received after Y ends, so an annual row received
    within Y is not that year's report and must not become the latest quarter.
    """

    rows = []
    for build in f2.get("periodization_builds") or []:
        for selection in build.get("anchor_selections") or []:
            if selection.get("status") != READY or not selection.get("selected_rcept_dt"):
                continue
            year = str(build.get("fiscal_year"))
            code = str(selection.get("reprt_code"))
            received = str(selection.get("selected_rcept_dt"))
            if fiscal_year_end_month == "12" and code == "11011" and received[:4] <= year:
                continue
            rows.append({"bsns_year": year, "reprt_code": code, "rcept_dt": received})
    return rows


def _fiscal_year_end_month(repo_root: Path | str, ticker: str) -> str | None:
    path = Path(repo_root) / "data/cache/opendart/company" / f"{ticker}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    month = str((payload.get("selected_fields") or {}).get("acc_mt") or "").strip()
    return month.zfill(2) if month else None


def evaluate_production_artifact(
    payload: Mapping[str, Any],
    requested_as_of: str,
    fiscal_year_end_month: str | None = None,
) -> OI1QEvaluation:
    f2 = payload.get("f2")
    family = str(payload.get("company_family") or "UNKNOWN")
    if not isinstance(f2, Mapping):
        return evaluate_signal(company_family=family, filings=None, observations=[],
                               as_of=requested_as_of, unavailable_reason="FUNDAMENTALS_F2_UNAVAILABLE")
    return evaluate_signal(company_family=family, filings=_filings(f2, fiscal_year_end_month),
                           observations=_observations(f2), as_of=requested_as_of)


def fundamental_status_for_ticker(repo_root: Path | str, ticker: str, requested_as_of: str) -> str:
    """Status from the production Fundamentals artifact of exactly ``requested_as_of``.

    A missing, mismatched or unreadable artifact is ``미상``; it is never
    treated as ``주의``.
    """

    clean_ticker = str(ticker).strip().zfill(6)
    clean_as_of = str(requested_as_of).strip()[:10]
    path = Path(repo_root) / PRODUCTION_ROOT / clean_as_of.replace("-", "") / "tickers" / f"{clean_ticker}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return UNKNOWN
    if not isinstance(payload, Mapping) \
            or str(payload.get("ticker", "")).strip().zfill(6) != clean_ticker \
            or str(payload.get("requested_as_of", "")).strip()[:10] != clean_as_of:
        return UNKNOWN
    month = _fiscal_year_end_month(repo_root, clean_ticker)
    return classify_fundamental_status(evaluate_production_artifact(payload, clean_as_of, month))
