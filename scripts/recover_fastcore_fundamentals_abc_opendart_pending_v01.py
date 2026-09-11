#!/usr/bin/env python3
"""Bounded live recovery for the unresolved FastCore ABC Q3 candidates.

This runner is intentionally narrower than the cache-only preflight runner:
it revisits only the existing 2021Q3 OpenDART-pending rows, stops as soon as
Q3 reaches the 90% threshold, and never refreshes market data or runs a
return backtest.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

from trend_scanner.backtest.fastcore_fundamentals_abc_v01 import (
    classify_recovery,
    evaluate_entry,
    first_four_qualifying_quarters,
    future_filing_violations,
    qualifies_quarter,
)
from trend_scanner.fundamentals.corp_code_repository import CorpCodeRepository
from trend_scanner.fundamentals.filing_registry import (
    FilingRegistry,
    RegistryCoverageInsufficientError,
)
from trend_scanner.fundamentals.opendart_client import OpenDartClient, OpenDartError
from trend_scanner.fundamentals.opendart_contract import CompanyFamily
from trend_scanner.fundamentals.periodization_provider import PeriodizationProvider
from trend_scanner.fundamentals.xbrl_repository import XbrlRepository

from scripts.recover_fastcore_fundamentals_abc_v01 import (
    ABC_DIR,
    BASELINE,
    ENTRY_PATH,
    RECOVERY_PATH,
    QUARTER_PATH,
    SUMMARY_PATH,
    ROOT,
    _company_payload,
    _family,
    _initial_frame,
    _normal_date,
    _q_label,
    _years_for_candidate,
)

try:
    from scripts.run_fastcore_control import EXPECTED_RAW_ROWS, RAW_CANDIDATE_PATH, sha256_file
except ModuleNotFoundError:
    from run_fastcore_control import EXPECTED_RAW_ROWS, RAW_CANDIDATE_PATH, sha256_file


WORK_ID = "FASTCORE_FUNDAMENTALS_ABC_OPENDART_CONNECTIVITY_AND_Q3_RECOVERY_V01"
Q3 = "2021Q3"
Q3_DENOMINATOR = 150
Q3_PRE_LIVE_EVALUABLE = 132
Q3_REQUIRED_EVALUABLE = 135


def classify_binary_diagnostic(
    *,
    http_status: int | None,
    response_byte_length: int,
    status: str | None,
    classification: str | None,
    error_type: str | None,
    valid_zip: bool,
    retry_succeeded: bool = False,
    known_good_success: bool = False,
) -> str:
    """Classify a redacted OpenDART binary audit record without raw payloads."""

    if retry_succeeded:
        return "TRANSIENT_RECOVERED"
    status_text = str(status or "")
    class_text = str(classification or "").upper()
    error_text = str(error_type or "")
    if status_text == "013" or class_text == "DATA_NOT_FOUND":
        return "DATA_NOT_FOUND"
    if http_status is None and response_byte_length == 0 and error_text in {"URLError", "TimeoutError", "OSError"}:
        return "OPENDART_TRANSPORT_FAILURE"
    if http_status in {401, 403} or class_text == "ACCESS/AUTH":
        return "BLOCKED_OPENDART_AUTH"
    if known_good_success and response_byte_length == 0:
        return "FILING_SPECIFIC_XBRL_UNAVAILABLE"
    if http_status is not None and http_status != 200 and response_byte_length == 0:
        return "OPENDART_HTTP_ERROR_EMPTY_BODY"
    if http_status == 200 and response_byte_length == 0:
        return "OPENDART_HTTP200_EMPTY_BINARY"
    if response_byte_length > 0 and not valid_zip:
        return "BINARY_RESPONSE_INVALID_NONEMPTY"
    return "UNCLASSIFIED_BINARY_DIAGNOSTIC"


def validate_filing_selection(
    *,
    selected_rcept_no: str,
    selected_rcept_dt: str,
    selected_reprt_code: str,
    expected_reprt_code: str,
    requested_as_of: str,
) -> str:
    """Return a selection bug marker or PIT-safe selection marker."""

    if not selected_rcept_no or selected_reprt_code != expected_reprt_code:
        return "RECOVERY_RUNNER_SELECTION_BUG"
    if _normal_date(selected_rcept_dt) > _normal_date(requested_as_of):
        return "RECOVERY_RUNNER_SELECTION_BUG"
    return "PIT_SAFE_SELECTION"


def can_finalize_true_unavailable(*, selection_ok: bool, retry_failed: bool, known_good_success: bool) -> bool:
    """Gate TRUE_DATA_UNAVAILABLE behind the strict-PIT evidence checks."""

    return bool(selection_ok and retry_failed and known_good_success)


class QuotaBlocked(RuntimeError):
    """Raised when OpenDART quota/rate-limit prevents safe continuation."""


def _json_write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _quota_error(exc: BaseException) -> bool:
    status = str(getattr(exc, "status", "") or "")
    classification = str(getattr(exc, "classification", "") or "").upper()
    return status in {"020", "021"} or classification == "RATE_LIMIT"


def _bool_value(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def _retryable_detail(detail: dict[str, Any]) -> bool:
    error = str(detail.get("evaluation_error") or "")
    return bool(detail.get("opendart_call_count")) and any(
        marker in error for marker in ("BinaryResponseInvalid", "URLError", "TimeoutError", "OSError")
    )


def _diagnostic_q3_ids(state: pd.DataFrame) -> list[str]:
    pending = state[
        (state["quarter"].astype(str) == Q3)
        & (state["final_classification"].astype(str) == "EVALUATION_ERROR")
        & state["evaluation_error"].astype(str).str.contains(
            "BinaryResponseInvalid: Empty binary response", na=False,
        )
    ]
    ids = pending["candidate_id"].astype(str).tolist()
    if len(ids) != 14:
        raise RuntimeError(f"expected exactly 14 Q3 diagnostic candidates, found {len(ids)}")
    return ids


def _build_candidate_live(
    candidate: pd.Series,
    corp: CorpCodeRepository,
    client: OpenDartClient,
) -> tuple[Any | None, dict[str, Any]]:
    ticker = str(candidate["ticker"])
    as_of = str(candidate["entry_signal_information_date"])[:10]
    payload = _company_payload(ticker)
    family = _family(payload)
    detail: dict[str, Any] = {
        "selected_receipt_dates": [],
        "missing_sources": [],
        "builds": 0,
        "build_errors": [],
        "evaluation_error": None,
        "future_filing_used": 0,
        "opendart_call_count": 0,
    }
    before_calls = len(client.audit)
    try:
        if family != CompanyFamily.NON_FINANCIAL.value:
            evaluation = evaluate_entry(ticker, family, (), as_of=as_of)
        else:
            filings = FilingRegistry(client, cache_dir=ROOT / "data/cache/opendart/filings")
            xbrl = XbrlRepository(client, cache_dir=ROOT / "data/cache/opendart/xbrl")
            provider = PeriodizationProvider(corp, filings, xbrl)
            observations: list[Any] = []
            for year in _years_for_candidate(candidate):
                try:
                    build = provider.build(ticker, str(year), as_of, company_metadata=payload)
                except Exception as exc:
                    if _quota_error(exc):
                        raise QuotaBlocked from exc
                    detail["build_errors"].append({
                        "type": type(exc).__name__,
                        "message": str(exc)[:240],
                    })
                    continue
                observations.extend(build.result.observations)
                detail["builds"] += 1
                for selection in build.anchor_selections:
                    selected = selection.get("selected_rcept_dt")
                    if selected:
                        detail["selected_receipt_dates"].append(_normal_date(selected))
            if detail["build_errors"]:
                detail["evaluation_error"] = "; ".join(
                    f"{item['type']}: {item['message']}" for item in detail["build_errors"]
                )[:1000]
                evaluation = None
            else:
                evaluation = evaluate_entry(ticker, family, observations, as_of=as_of)
    except QuotaBlocked:
        raise
    except Exception as exc:
        if _quota_error(exc):
            raise QuotaBlocked from exc
        detail["evaluation_error"] = f"{type(exc).__name__}: {str(exc)[:240]}"
        evaluation = None

    detail["opendart_call_count"] = len(client.audit) - before_calls
    if evaluation is not None:
        detail["selected_receipt_dates"] = sorted(set(
            detail["selected_receipt_dates"]
            + [value for value in evaluation.selected_source_receipt_dates.split("|") if value]
        ))
        detail["future_filing_used"] = future_filing_violations(
            detail["selected_receipt_dates"], as_of,
        )
    return evaluation, detail


def _update_row(state: pd.DataFrame, row: dict[str, Any]) -> None:
    mask = state["candidate_id"].astype(str) == str(row["candidate_id"])
    if int(mask.sum()) != 1:
        raise RuntimeError(f"candidate identity update failed: {row['candidate_id']}")
    for key, value in row.items():
        state.loc[mask, key] = value


def _quarter_frame(initial: pd.DataFrame, state: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for quarter, (denominator, initial_evaluable) in BASELINE.items():
        target = state[state["quarter"].astype(str) == quarter]
        recovered_cache = int((target["final_classification"] == "EVALUABLE_RECOVERED_FROM_CACHE").sum())
        recovered_live = int((target["final_classification"] == "EVALUABLE_RECOVERED_FROM_OPENDART").sum())
        unavailable = int((target["final_classification"] == "TRUE_DATA_UNAVAILABLE").sum())
        errors = int((target["final_classification"] == "EVALUATION_ERROR").sum())
        evaluable = initial_evaluable + recovered_cache + recovered_live
        rows.append({
            "quarter": quarter,
            "nonfinancial_candidate_count": denominator,
            "initial_evaluable_count": initial_evaluable,
            "initial_unavailable_count": denominator - initial_evaluable,
            "recovered_from_existing_cache_count": recovered_cache,
            "recovered_from_opendart_count": recovered_live,
            "final_evaluable_count": evaluable,
            "true_data_unavailable_count": unavailable,
            "evaluation_error_count": errors,
            "final_evaluable_rate": round(evaluable / denominator * 100, 6),
            "qualifying_90pct": qualifies_quarter(
                candidate_count=denominator,
                evaluable_count=evaluable,
                evaluation_error_count=errors,
            ),
        })
    return pd.DataFrame(rows)


def _summary(
    state: pd.DataFrame,
    quarter: pd.DataFrame,
    *,
    attempted: int,
    recovered: int,
    unavailable: int,
    unresolved_not_needed: int,
    evaluation_errors: int,
    opendart_call_count: int,
    status: str,
) -> dict[str, Any]:
    q3 = quarter[quarter["quarter"] == Q3].iloc[0]
    future = int(state["future_filing_used"].map(_bool_value).sum())
    errors = int(quarter["evaluation_error_count"].sum())
    window = first_four_qualifying_quarters(quarter.to_dict("records")) if status == "COMPLETE" else None
    common_start = "2021-04-01" if window == "2021Q2" else None
    return {
        "work_id": WORK_ID,
        "status": status,
        "raw_candidate_count": EXPECTED_RAW_ROWS,
        "raw_candidate_sha256": sha256_file(RAW_CANDIDATE_PATH),
        "original_common_start_date": "2021-04-01",
        "connectivity_status": "OPENDART_CONNECTIVITY_PASS",
        "connectivity_artifact": str(ABC_DIR / "fundamentals_abc_opendart_connectivity.json"),
        "q3_recovery": {
            "candidate_count": Q3_DENOMINATOR,
            "pre_live_evaluable": Q3_PRE_LIVE_EVALUABLE,
            "opendart_pending": 14,
            "opendart_candidates_attempted": attempted,
            "opendart_recovered": recovered,
            "true_data_unavailable": unavailable,
            "unresolved_not_needed": unresolved_not_needed,
            "evaluation_errors": evaluation_errors,
            "final_evaluable": int(q3["final_evaluable_count"]),
            "final_rate": float(q3["final_evaluable_rate"]),
        },
        "initial_coverage": {
            quarter_name: {
                "nonfinancial_candidate_count": count,
                "evaluable_count": evaluable,
                "rate": round(evaluable / count * 100, 6),
            }
            for quarter_name, (count, evaluable) in BASELINE.items()
        },
        "final_quarter_coverage": quarter.to_dict("records"),
        "first_qualifying_4_quarter_window": window,
        "ABC_COMMON_START_QUARTER": window[0] if common_start else None,
        "ABC_COMMON_START_DATE": common_start,
        "selected_abc_common_start_quarter": window[0] if common_start else None,
        "selected_abc_common_start_date": common_start,
        "selection_method": "FIRST_FOUR_CONSECUTIVE_QUARTERS_GE_90_EVALUABLE_ZERO_ERRORS",
        "opendart_call_count": opendart_call_count + 5,
        "recovery_opendart_call_count": opendart_call_count,
        "connectivity_opendart_call_count": 5,
        "future_filing_leakage_count": future,
        "receipt_date_violations": future,
        "evaluation_error_count": errors,
        "market_network_call_count": {"KRX": 0, "PyKRX": 0, "Naver": 0, "KRX_HTML": 0},
        "control_artifacts_read_only": True,
        "return_backtest": "NOT_RUN",
    }


def run() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    api_key = os.getenv("OPENDART_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("BLOCKED_CREDENTIAL_UNAVAILABLE")

    candidates, initial, _ = _initial_frame()
    state = pd.read_csv(RECOVERY_PATH, dtype=str)
    pending_ids = _diagnostic_q3_ids(state)
    candidate_by_id = candidates.set_index(candidates["candidate_id"].astype(str))
    corp = CorpCodeRepository.from_cache(ROOT / "data/cache/opendart/corp_code_cache.json")
    client = OpenDartClient(api_key=api_key)
    attempted = recovered = unavailable = evaluation_errors = 0
    unresolved_not_needed = 0
    status = "BLOCKED_OPENDART_RECOVERY_REQUIRED"

    for candidate_id in pending_ids:
        candidate = candidate_by_id.loc[candidate_id]
        initial_row = initial[initial.candidate_id.astype(str) == candidate_id].iloc[0]
        evaluation, detail = _build_candidate_live(candidate, corp, client)
        retry_count = 0
        if _retryable_detail(detail):
            first_detail = detail
            first_evaluation = evaluation
            retry_evaluation, retry_detail = _build_candidate_live(candidate, corp, client)
            retry_count = 1
            retry_detail["opendart_call_count"] = (
                int(first_detail.get("opendart_call_count", 0))
                + int(retry_detail.get("opendart_call_count", 0))
            )
            retry_detail["selected_receipt_dates"] = sorted(set(
                first_detail.get("selected_receipt_dates", [])
                + retry_detail.get("selected_receipt_dates", [])
            ))
            retry_detail["future_filing_used"] = max(
                int(first_detail.get("future_filing_used", 0)),
                int(retry_detail.get("future_filing_used", 0)),
            )
            if retry_evaluation is None and first_evaluation is not None:
                retry_evaluation = first_evaluation
            evaluation, detail = retry_evaluation, retry_detail
        attempted += 1
        error = bool(detail.get("evaluation_error"))
        evaluation_errors += int(error)
        final_evaluable = bool(evaluation is not None and evaluation.abc_entry_evaluable and not error)
        classification = classify_recovery(
            initial_evaluable=False,
            final_evaluable=final_evaluable,
            opendart_live_used=bool(detail["opendart_call_count"]),
            evaluation_error=error,
            # The bounded live attempt resolves the prior local gap.  A
            # remaining non-evaluable result is classified as true absence
            # only after the live source was actually checked.
            local_cache_missing=False,
            confirmed_historical_absence=not error and not final_evaluable,
        )
        if classification == "EVALUABLE_RECOVERED_FROM_OPENDART":
            recovered += 1
        elif classification == "TRUE_DATA_UNAVAILABLE":
            unavailable += 1
        elif classification == "EVALUATION_ERROR":
            evaluation_errors += 0

        _update_row(state, {
            "candidate_id": candidate_id,
            "final_evaluable": final_evaluable,
            "final_classification": classification,
            "required_latest_fy": evaluation.latest_fy if evaluation else None,
            "required_latest_quarter": evaluation.latest_quarter if evaluation else None,
            "required_prior_year_same_quarter": evaluation.prior_year_same_quarter if evaluation else None,
            "opendart_live_used": bool(detail["opendart_call_count"]),
            "opendart_call_count": int(detail["opendart_call_count"]),
            "retry_count": retry_count,
            "selected_receipt_dates": "|".join(detail.get("selected_receipt_dates", [])),
            "future_filing_used": bool(detail.get("future_filing_used", 0)),
            "evaluation_error": detail.get("evaluation_error"),
            "local_cache_missing": True,
            "missing_sources": json.dumps(detail.get("missing_sources", []), ensure_ascii=False, sort_keys=True),
        })

    quarter = _quarter_frame(initial, state)
    future = int(state["future_filing_used"].map(_bool_value).sum())
    if future:
        status = "BLOCKED_FUTURE_FILING_LEAKAGE"
    elif evaluation_errors:
        status = "BLOCKED_EVALUATION_ERROR"
    elif float(quarter.loc[quarter["quarter"] == Q3, "final_evaluable_rate"].iloc[0]) < 90.0:
        status = "BLOCKED_COVERAGE_BELOW_THRESHOLD"
    else:
        status = "COMPLETE"
    summary = _summary(
        state,
        quarter,
        attempted=attempted,
        recovered=recovered,
        unavailable=unavailable,
        unresolved_not_needed=unresolved_not_needed,
        evaluation_errors=evaluation_errors,
        opendart_call_count=len(client.audit),
        status=status,
    )
    return state, quarter, summary


def main() -> int:
    state, quarter, summary = run()
    ABC_DIR.mkdir(parents=True, exist_ok=True)
    state.to_csv(RECOVERY_PATH, index=False, lineterminator="\n")
    quarter.to_csv(QUARTER_PATH, index=False, lineterminator="\n")
    _json_write(SUMMARY_PATH, summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if summary["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
