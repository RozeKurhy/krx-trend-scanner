#!/usr/bin/env python3
"""Bounded recovery and common-start discovery for ABC preflight.

This script only revisits the existing preflight's non-evaluable candidates in
the four frozen baseline quarters. It is deliberately separate from the
return backtest and never refreshes market data or the raw candidate set.
"""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from trend_scanner.backtest.fastcore_fundamentals_abc_v01 import (
    ABCEntryEvaluation,
    classify_recovery,
    first_four_qualifying_quarters,
    future_filing_violations,
    qualifies_quarter,
    evaluate_entry,
)
from trend_scanner.fundamentals.corp_code_repository import CorpCodeRepository
from trend_scanner.fundamentals.filing_registry import FilingRegistry, RegistryCoverageInsufficientError
from trend_scanner.fundamentals.models import RegisteredFiling
from trend_scanner.fundamentals.opendart_contract import CompanyFamily, classify_company_family
from trend_scanner.fundamentals.opendart_client import OpenDartError
from trend_scanner.fundamentals.periodization_provider import PeriodizationProvider
from trend_scanner.fundamentals.xbrl_repository import XbrlRepository, XbrlRepositoryError

try:
    from scripts.run_fastcore_control import (
        EXPECTED_RAW_ROWS, EXPECTED_RAW_SHA256, RAW_CANDIDATE_PATH, COMMON_START_DATE, SIGNAL_END_DATE,
        EXECUTION_SUPPORT_END_DATE, sha256_file,
    )
except ModuleNotFoundError:
    from run_fastcore_control import (
        EXPECTED_RAW_ROWS, EXPECTED_RAW_SHA256, RAW_CANDIDATE_PATH, COMMON_START_DATE, SIGNAL_END_DATE,
        EXECUTION_SUPPORT_END_DATE, sha256_file,
    )


ROOT = Path(__file__).resolve().parents[1]
ABC_DIR = ROOT / "artifacts/backtests/fastcore_fundamentals_simple_v01/fundamentals_abc"
ENTRY_PATH = ABC_DIR / "fundamentals_abc_entry_evaluations.csv"
QUARTER_PATH = ABC_DIR / "fundamentals_abc_common_start_by_quarter.csv"
RECOVERY_PATH = ABC_DIR / "fundamentals_abc_coverage_recovery.csv"
SUMMARY_PATH = ABC_DIR / "fundamentals_abc_common_start_summary.json"
INITIAL_SUMMARY_PATH = ABC_DIR / "fundamentals_abc_summary.json"

BASELINE = {
    "2021Q2": (418, 366),
    "2021Q3": (150, 117),
    "2021Q4": (46, 42),
    "2022Q1": (43, 43),
}


def _json_read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _q_label(value: Any) -> str:
    timestamp = pd.Timestamp(value)
    return f"{timestamp.year}Q{((timestamp.month - 1) // 3) + 1}"


def _normal_date(value: Any) -> str:
    text = str(value or "")[:10]
    if len(text) >= 8 and text[:8].isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text


def _company_payload(ticker: str) -> dict[str, Any] | None:
    path = ROOT / "data/cache/opendart/company" / f"{str(ticker)}.json"
    if not path.exists():
        return None
    try:
        payload = _json_read(path)
    except (OSError, ValueError, TypeError):
        return None
    return payload if str(payload.get("status") or "") == "000" else None


def _family(payload: dict[str, Any] | None) -> str:
    if payload is None:
        return CompanyFamily.UNKNOWN.value
    result = classify_company_family(payload, ())
    return str(result.get("company_family") or CompanyFamily.UNKNOWN.value)


class CacheGapXbrlRepository(XbrlRepository):
    """Turn a cache-only XBRL miss into an auditable local-gap signal."""

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.misses: list[dict[str, str]] = []

    def fetch(self, filing: RegisteredFiling, *, force_refresh: bool = False):
        try:
            return super().fetch(filing, force_refresh=force_refresh)
        except XbrlRepositoryError:
            if self.client is not None:
                raise
            self.misses.append({
                "rcept_no": str(filing.rcept_no), "reprt_code": str(filing.reprt_code),
                "rcept_dt": str(filing.rcept_dt), "bsns_year": str(filing.bsns_year),
            })
            raise OpenDartError("LOCAL_XBRL_CACHE_MISS", status="014", classification="REQUEST") from None


def _years_for_candidate(candidate: pd.Series) -> range:
    year = pd.Timestamp(candidate["entry_signal_information_date"]).year
    return range(max(2015, year - 2), year + 1)


def _build_candidate_local(candidate: pd.Series, corp: CorpCodeRepository) -> tuple[ABCEntryEvaluation | None, dict[str, Any]]:
    ticker = str(candidate["ticker"])
    as_of = str(candidate["entry_signal_information_date"])[:10]
    payload = _company_payload(ticker)
    family = _family(payload)
    diagnostics: dict[str, Any] = {
        "local_cache_missing": False, "missing_sources": [], "selected_receipt_dates": [],
        "builds": 0, "build_errors": [], "evaluation_error": None,
    }
    if family != CompanyFamily.NON_FINANCIAL.value:
        return evaluate_entry(ticker, family, (), as_of=as_of), diagnostics
    xbrl = CacheGapXbrlRepository(None, cache_dir=ROOT / "data/cache/opendart/xbrl")
    provider = PeriodizationProvider(
        corp,
        FilingRegistry(None, cache_dir=ROOT / "data/cache/opendart/filings"),
        xbrl,
    )
    observations: list[Any] = []
    for year in _years_for_candidate(candidate):
        try:
            build = provider.build(ticker, str(year), as_of, company_metadata=payload)
            observations.extend(build.result.observations)
            diagnostics["builds"] += 1
            for selection in build.anchor_selections:
                selected = selection.get("selected_rcept_dt")
                if selected:
                    diagnostics["selected_receipt_dates"].append(_normal_date(selected))
        except RegistryCoverageInsufficientError as exc:
            diagnostics["local_cache_missing"] = True
            diagnostics["build_errors"].append({"type": type(exc).__name__, "message": str(exc)[:240]})
        except Exception as exc:
            diagnostics["build_errors"].append({"type": type(exc).__name__, "message": str(exc)[:240]})
            diagnostics["evaluation_error"] = f"{type(exc).__name__}: {str(exc)[:240]}"
    diagnostics["missing_sources"] = list(xbrl.misses)
    diagnostics["local_cache_missing"] = bool(diagnostics["local_cache_missing"] or xbrl.misses)
    try:
        evaluation = evaluate_entry(ticker, family, observations, as_of=as_of)
    except Exception as exc:
        diagnostics["evaluation_error"] = f"{type(exc).__name__}: {str(exc)[:240]}"
        return None, diagnostics
    diagnostics["selected_receipt_dates"] = sorted(set(diagnostics["selected_receipt_dates"]
                                                         + [value for value in evaluation.selected_source_receipt_dates.split("|") if value]))
    diagnostics["future_filing_used"] = future_filing_violations(diagnostics["selected_receipt_dates"], as_of)
    return evaluation, diagnostics


def _initial_frame() -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    candidates = pd.read_csv(RAW_CANDIDATE_PATH, dtype={"ticker": str, "isu_cd": str, "candidate_id": str})
    initial = pd.read_csv(ENTRY_PATH, dtype=str)
    initial["abc_entry_evaluable"] = initial["abc_entry_evaluable"].fillna("False").str.lower().eq("true")
    initial["company_family"] = initial["company_family"].fillna(CompanyFamily.UNKNOWN.value)
    initial["preflight_quarter"] = pd.to_datetime(initial["entry_signal_information_date"]).map(_q_label)
    expected = {
        "2021Q2": (418, 366), "2021Q3": (150, 117), "2021Q4": (46, 42), "2022Q1": (43, 43),
    }
    for quarter, (count, evaluable) in expected.items():
        values = initial[(initial.preflight_quarter == quarter) & (initial.company_family == CompanyFamily.NON_FINANCIAL.value)]
        if (len(values), int(values.abc_entry_evaluable.sum())) != (count, evaluable):
            raise RuntimeError(f"initial denominator/evaluable baseline changed for {quarter}")
    targets = initial[
        initial.preflight_quarter.isin(tuple(BASELINE))
        & (initial.company_family == CompanyFamily.NON_FINANCIAL.value)
        & (~initial.abc_entry_evaluable)
    ].copy()
    return candidates, initial, targets["candidate_id"].astype(str).tolist()


def run() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    candidates, initial, target_ids = _initial_frame()
    candidate_by_id = candidates.set_index(candidates["candidate_id"].astype(str))
    corp = CorpCodeRepository.from_cache(ROOT / "data/cache/opendart/corp_code_cache.json")
    recovery_rows: list[dict[str, Any]] = []
    recovered_ids: set[str] = set()
    diagnostics = {"target_count": len(target_ids), "cache_rechecks": 0, "evaluation_errors": 0,
                   "local_cache_miss_candidates": 0, "recovered_from_cache": 0, "true_unavailable": 0}
    for candidate_id in target_ids:
        candidate = candidate_by_id.loc[candidate_id]
        initial_row = initial[initial.candidate_id.astype(str) == candidate_id].iloc[0]
        evaluation, detail = _build_candidate_local(candidate, corp)
        diagnostics["cache_rechecks"] += 1
        error = bool(detail.get("evaluation_error"))
        if error:
            diagnostics["evaluation_errors"] += 1
        local_missing = bool(detail.get("local_cache_missing"))
        diagnostics["local_cache_miss_candidates"] += int(local_missing)
        final_evaluable = bool(evaluation and evaluation.abc_entry_evaluable)
        classification = classify_recovery(
            initial_evaluable=False, final_evaluable=final_evaluable, opendart_live_used=False,
            evaluation_error=error, local_cache_missing=local_missing,
            confirmed_historical_absence=not local_missing and not error,
        )
        if classification == "EVALUABLE_RECOVERED_FROM_CACHE":
            diagnostics["recovered_from_cache"] += 1
            recovered_ids.add(candidate_id)
        if classification == "TRUE_DATA_UNAVAILABLE":
            diagnostics["true_unavailable"] += 1
        recovery_rows.append({
            "candidate_id": candidate_id, "ticker": candidate["ticker"], "isu_cd": candidate["isu_cd"],
            "market": candidate["market"], "entry_signal_information_date": candidate["entry_signal_information_date"],
            "quarter": _q_label(candidate["entry_signal_information_date"]),
            "initial_evaluable": False, "initial_failure_reason": initial_row["reject_reasons"],
            "final_evaluable": final_evaluable, "final_classification": classification,
            "required_latest_fy": evaluation.latest_fy if evaluation else None,
            "required_latest_quarter": evaluation.latest_quarter if evaluation else None,
            "required_prior_year_same_quarter": evaluation.prior_year_same_quarter if evaluation else None,
            "opendart_live_used": False, "opendart_call_count": 0,
            "selected_receipt_dates": "|".join(detail.get("selected_receipt_dates", [])),
            "future_filing_used": bool(detail.get("future_filing_used", 0)),
            "evaluation_error": detail.get("evaluation_error"),
            "local_cache_missing": local_missing,
            "missing_sources": json.dumps(detail.get("missing_sources", []), ensure_ascii=False, sort_keys=True),
        })

    recovery = pd.DataFrame(recovery_rows)
    quarter_rows: list[dict[str, Any]] = []
    for quarter, (initial_count, initial_evaluable) in BASELINE.items():
        target = recovery[recovery["quarter"] == quarter] if not recovery.empty else recovery
        recovered_cache = int((target["final_classification"] == "EVALUABLE_RECOVERED_FROM_CACHE").sum()) if not target.empty else 0
        recovered_live = int((target["final_classification"] == "EVALUABLE_RECOVERED_FROM_OPENDART").sum()) if not target.empty else 0
        true_unavailable = int((target["final_classification"] == "TRUE_DATA_UNAVAILABLE").sum()) if not target.empty else 0
        errors = int((target["final_classification"] == "EVALUATION_ERROR").sum()) if not target.empty else 0
        final_evaluable = initial_evaluable + recovered_cache + recovered_live
        denominator = initial_count
        quarter_rows.append({
            "quarter": quarter, "nonfinancial_candidate_count": denominator,
            "initial_evaluable_count": initial_evaluable,
            "initial_unavailable_count": denominator - initial_evaluable,
            "recovered_from_existing_cache_count": recovered_cache,
            "recovered_from_opendart_count": recovered_live,
            "final_evaluable_count": final_evaluable,
            "true_data_unavailable_count": true_unavailable,
            "evaluation_error_count": errors,
            "final_evaluable_rate": round(final_evaluable / denominator * 100, 6),
            "qualifying_90pct": qualifies_quarter(candidate_count=denominator, evaluable_count=final_evaluable, evaluation_error_count=errors),
        })
    quarter_frame = pd.DataFrame(quarter_rows)
    pending = int((recovery["final_classification"] == "LOCAL_CACHE_MISS_PENDING_OPENDART").sum()) if not recovery.empty else 0
    summary = {
        "work_id": "FASTCORE_FUNDAMENTALS_ABC_COVERAGE_RECOVERY_AND_COMMON_START_V01",
        "status": "BLOCKED_OPENDART_RECOVERY_REQUIRED" if pending or diagnostics["evaluation_errors"] else "COMPLETE",
        "raw_candidate_count": EXPECTED_RAW_ROWS, "raw_candidate_sha256": sha256_file(RAW_CANDIDATE_PATH),
        "original_common_start_date": "2021-04-01",
        "initial_coverage": {quarter: {"nonfinancial_candidate_count": count, "evaluable_count": evaluable,
                                        "rate": round(evaluable / count * 100, 6)} for quarter, (count, evaluable) in BASELINE.items()},
        "recovery": {**diagnostics, "pending_opendart_recovery": pending, "recovered_from_opendart": 0,
                     "future_filing_leakage_count": int(recovery["future_filing_used"].fillna(False).astype(bool).sum()) if not recovery.empty else 0},
        "final_quarter_coverage": quarter_rows,
        "first_qualifying_4_quarter_window": None if pending else first_four_qualifying_quarters(quarter_rows),
        "selected_abc_common_start_quarter": None,
        "selected_abc_common_start_date": None,
        "selection_method": "FIRST_FOUR_CONSECUTIVE_QUARTERS_GE_90_EVALUABLE_ZERO_ERRORS",
        "future_filing_leakage_count": int(recovery["future_filing_used"].fillna(False).astype(bool).sum()) if not recovery.empty else 0,
        "market_network_call_count": {"KRX": 0, "PyKRX": 0, "Naver": 0, "KRX_HTML": 0},
        "control_artifacts_read_only": True,
        "return_backtest": "NOT_RUN",
    }
    return recovery, quarter_frame, summary


def main() -> int:
    recovery, quarter, summary = run()
    ABC_DIR.mkdir(parents=True, exist_ok=True)
    recovery.to_csv(RECOVERY_PATH, index=False, lineterminator="\n")
    quarter.to_csv(QUARTER_PATH, index=False, lineterminator="\n")
    _json_write(SUMMARY_PATH, summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if summary["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
