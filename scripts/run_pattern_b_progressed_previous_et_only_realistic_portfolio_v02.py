#!/usr/bin/env python3
"""Official five-window portfolio review for the frozen Pattern B E/T candidate.

The V02 runner reuses hash-verified V01 candidate signals and per-window path
outcomes, filters them through the current exact-identity exclusion policy,
and performs a new cash-aware portfolio replay using fees and slippage only.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import math
import resource
from pathlib import Path
import sys
import time
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_pattern_b_progressed_previous_et_only_realistic_portfolio_v01 as v01  # noqa: E402
from scripts import run_pattern_b_progressed_weak_exclusion_p1_simple_v01 as candidate_runner  # noqa: E402
from scripts import run_pattern_b_pure_simple_backtest_v01 as pattern_b_base  # noqa: E402
from scripts import run_p2_1_realistic_portfolio_v01 as portfolio  # noqa: E402
from trend_scanner.universe.permanent_identity_exclusions import (  # noqa: E402
    PERMANENT_IDENTITY_EXCLUSIONS,
)

OUTPUT_ROOT = Path(
    "artifacts/patterns/pattern_b/"
    "progressed_previous_stage_early_transition_only_realistic_portfolio_v02"
)
SOURCE_ROOT = Path(
    "artifacts/patterns/pattern_b/"
    "progressed_previous_stage_early_transition_only_5window_v01"
)
STAGE_HISTORY_PATH = Path(
    "artifacts/patterns/pattern_b/progressed_previous_pattern_a_stage_v01/"
    "candidate_signal_stage_history.csv"
)
STAGE_LINKAGE_PATH = Path(
    "artifacts/patterns/pattern_b/depressed_entry_pattern_a_state_v01/"
    "signal_stage_path_trade_linkage.csv"
)
STAGE_HISTORY_METADATA_PATH = Path(
    "artifacts/patterns/pattern_b/progressed_previous_pattern_a_stage_v01/metadata.json"
)
STAGE_LINKAGE_METADATA_PATH = Path(
    "artifacts/patterns/pattern_b/depressed_entry_pattern_a_state_v01/metadata.json"
)
EXCLUSION_POLICY_PATH = Path("src/trend_scanner/universe/permanent_identity_exclusions.py")
OFFICIAL_CRITERIA_PATH = Path("docs/validation/official_strategy_adoption_criteria.md")
COMMON_RULES_PATH = Path("docs/validation/backtest_common_rules.md")
WORK_INSTRUCTION_PATH = Path("/Users/june/Documents/projects/w.md")
V2_REFERENCE_ROOT = Path(
    "artifacts/patterns/pattern_a_fast/strategy/"
    "v2_official_adoption_revalidation_mdd_closure_v02"
)

WINDOW_IDS = ("P1", "P2-1", "P2-2", "P3-1", "P3-2")
GATE_IDS = ("A", "B", "C", "D", "E")
STRATEGY_ID = "PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01"
DISPLAY_NAME = "Pattern B E/T PROGRESSED Candidate V1"
ALLOWED_PREVIOUS_STAGES = {"EARLY_TREND", "TRANSITION"}
ALLOWED_SIGNAL_DECISION = "PASS_EARLY_TREND_OR_TRANSITION"
INITIAL_CAPITAL = 200_000_000.0
POSITION_BUDGET = 5_000_000.0
COMMISSION_RATE = 0.00015
SLIPPAGE_RATE = 0.001
WORKERS = 10
MIN_OBSERVED_COVERAGE = 90.0
ABSOLUTE_MDD_LIMITS = {
    "P1": -55.0,
    "P2-1": -40.0,
    "P2-2": -40.0,
    "P3-1": -40.0,
    "P3-2": -40.0,
}
RELATIVE_MDD_LIMIT_PP = 5.0
V2_MDD_REFERENCE = {
    "P1": -52.25,
    "P2-1": -32.71,
    "P2-2": -34.54,
    "P3-1": -37.34,
    "P3-2": -38.46,
}
ZERO_TAX_SCHEDULE = (("1900-01-01", "2100-12-31", 0.0),)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_write(path: Path, value: Any) -> None:
    v01.json_write(path, value)


def json_clean(value: Any) -> Any:
    return v01.clean_json(value)


def key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return v01.row_key(row)


def window_directory(window_id: str) -> Path:
    return ROOT / SOURCE_ROOT / window_id.lower().replace("-", "_")


def identity_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row.get("ticker", "")).zfill(6), str(row.get("isu_cd", "")).upper()


def bool_value(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def valid_equity(row: Mapping[str, Any]) -> bool:
    value = row.get("equity")
    if value is None or pd.isna(value):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def frozen_source_hashes_verified(inputs: Mapping[str, Any]) -> bool:
    generated = inputs.get("generated_file_checks", {})
    code_checks = inputs.get("code_checks", {})
    bootstrap_checks = inputs.get("bootstrap_source_checks", {})
    authority_check = inputs.get("authoritative_signal_linkage_check", {})
    generated_ok = bool(generated) and all(row.get("status") == "PASS" for row in generated.values())
    # The historical study runner was intentionally untracked when it produced
    # the V01 frozen artifact. Its original source hash cannot be reconstructed
    # from Git, so V02 proves each accepted signal against the frozen stage and
    # raw Pattern B linkage authorities instead of claiming that runner hash is
    # verified.
    code_ok = bool(code_checks) and all(
        row.get("expected_sha256") and row.get("actual_sha256")
        and row.get("status") in {"PASS", "RUN_SOURCE_UNTRACKED_AT_START"}
        for row in code_checks.values()
    )
    bootstrap_ok = bool(bootstrap_checks) and all(row.get("status") == "PASS" for row in bootstrap_checks.values())
    authority_ok = authority_check.get("status") == "PASS"
    return generated_ok and code_ok and bootstrap_ok and authority_ok


@lru_cache(maxsize=1)
def authoritative_signal_maps() -> tuple[dict[tuple[str, str, str], dict[str, Any]], dict[tuple[str, str, str], dict[str, Any]], dict[str, Any]]:
    history_path = ROOT / STAGE_HISTORY_PATH
    linkage_path = ROOT / STAGE_LINKAGE_PATH
    history_metadata_path = ROOT / STAGE_HISTORY_METADATA_PATH
    linkage_metadata_path = ROOT / STAGE_LINKAGE_METADATA_PATH
    for path in (history_path, linkage_path, history_metadata_path, linkage_metadata_path):
        if not path.is_file():
            raise RuntimeError(f"MISSING_FROZEN_SIGNAL_AUTHORITY:{path}")

    history_metadata = json.loads(history_metadata_path.read_text(encoding="utf-8"))
    linkage_metadata = json.loads(linkage_metadata_path.read_text(encoding="utf-8"))
    history_digest = sha256(history_path)
    linkage_digest = sha256(linkage_path)
    expected_history = history_metadata.get("generated_files", {}).get(STAGE_HISTORY_PATH.name, {}).get("sha256")
    expected_linkage = linkage_metadata.get("generated_files", {}).get(STAGE_LINKAGE_PATH.name, {}).get("sha256")
    if history_digest != expected_history or linkage_digest != expected_linkage:
        raise RuntimeError("FROZEN_SIGNAL_AUTHORITY_HASH_MISMATCH")
    if history_metadata.get("source_studies", {}).get("stage_linkage_sha256") != linkage_digest:
        raise RuntimeError("STAGE_HISTORY_TO_RAW_LINKAGE_HASH_MISMATCH")
    if history_metadata.get("source_studies", {}).get("stage_metadata_sha256") != sha256(linkage_metadata_path):
        raise RuntimeError("STAGE_HISTORY_TO_LINKAGE_METADATA_HASH_MISMATCH")

    history = pd.read_csv(history_path, dtype={"ticker": str, "isu_cd": str, "entry_signal_date": str})
    linkage = pd.read_csv(linkage_path, dtype={"ticker": str, "isu_cd": str, "entry_signal_date": str})
    history_rows = history.to_dict(orient="records")
    linkage_rows = linkage.to_dict(orient="records")
    history_map = {key(row): row for row in history_rows}
    linkage_map = {key(row): row for row in linkage_rows}
    if len(history_map) != len(history_rows) or len(linkage_map) != len(linkage_rows):
        raise RuntimeError("DUPLICATE_FROZEN_SIGNAL_AUTHORITY_KEY")
    evidence = {
        "status": "PASS",
        "candidate_signal_stage_history_sha256": history_digest,
        "candidate_signal_stage_history_expected_sha256": expected_history,
        "raw_signal_stage_path_trade_linkage_sha256": linkage_digest,
        "raw_signal_stage_path_trade_linkage_expected_sha256": expected_linkage,
        "history_metadata_sha256": sha256(history_metadata_path),
        "raw_linkage_metadata_sha256": sha256(linkage_metadata_path),
        "stage_history_unique_signal_count": len(history_map),
        "raw_linkage_unique_signal_count": len(linkage_map),
    }
    return history_map, linkage_map, evidence


def verify_authoritative_signal_linkage(
    pass_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    history_map, linkage_map, authority_evidence = authoritative_signal_maps()
    failures: list[dict[str, Any]] = []
    history_checked = 0
    raw_linkage_checked = 0
    for candidate in pass_rows:
        signal_key = key(candidate)
        history = history_map.get(signal_key)
        linkage = linkage_map.get(signal_key)
        if history is None:
            failures.append({"signal_key": signal_key, "source": "CANDIDATE_STAGE_HISTORY", "reason": "MISSING"})
            continue
        if linkage is None:
            failures.append({"signal_key": signal_key, "source": "RAW_STAGE_PATH_LINKAGE", "reason": "MISSING"})
            continue
        history_checked += 1
        raw_linkage_checked += 1
        if (
            str(history.get("pattern_a_stage")) != "PROGRESSED"
            or str(history.get("entry_pattern_a_stage_recomputed")) != "PROGRESSED"
            or str(history.get("previous_pattern_a_stage")) != str(candidate.get("previous_pattern_a_stage"))
            or str(history.get("previous_pattern_a_stage")) not in ALLOWED_PREVIOUS_STAGES
            or str(history.get("previous_pattern_a_stage_date", ""))[:10]
            != str(candidate.get("previous_pattern_a_stage_date", ""))[:10]
            or str(history.get("entry_pattern_a_requested_asof", ""))[:10] != signal_key[2]
            or not bool_value(history.get("entry_pattern_a_lookahead_free"))
        ):
            failures.append({"signal_key": signal_key, "source": "CANDIDATE_STAGE_HISTORY", "reason": "STAGE_OR_PIT_MISMATCH"})
        if (
            str(linkage.get("pattern_a_stage")) != "PROGRESSED"
            or str(linkage.get("entry_signal_state")) != str(candidate.get("pattern_b_entry_state"))
            or str(linkage.get("entry_signal_state")) != "DEPRESSED"
            or str(linkage.get("previous_state")) != str(candidate.get("pattern_b_previous_state"))
            or str(linkage.get("pattern_a_requested_asof", ""))[:10] != signal_key[2]
            or not bool_value(linkage.get("pattern_a_lookahead_free"))
        ):
            failures.append({"signal_key": signal_key, "source": "RAW_STAGE_PATH_LINKAGE", "reason": "STAGE_OR_PIT_MISMATCH"})
    return {
        **authority_evidence,
        "status": "PASS" if not failures else "FAIL",
        "candidate_signals_checked": len(pass_rows),
        "stage_history_signals_checked": history_checked,
        "raw_linkage_signals_checked": raw_linkage_checked,
        "mismatch_count": len(failures),
        "mismatches": failures[:20],
    }


def current_exclusion_keys() -> set[tuple[str, str]]:
    return {
        (str(ticker).zfill(6), str(isu_cd).upper())
        for ticker, isu_cd in PERMANENT_IDENTITY_EXCLUSIONS
    }


def load_window_inputs(window_id: str) -> dict[str, Any]:
    """Verify the frozen V01 signal/path inputs, then apply current exclusions."""
    loaded = v01.load_window_inputs(window_id)
    exclusions = current_exclusion_keys()
    historical_records = [dict(row) for row in loaded["records"]]
    historical_signals = [dict(row) for row in loaded["pass_rows"]]
    excluded_records = [row for row in historical_records if identity_key(row) in exclusions]
    excluded_signals = [row for row in historical_signals if identity_key(row) in exclusions]
    records = [row for row in historical_records if identity_key(row) not in exclusions]
    pass_rows = [row for row in historical_signals if identity_key(row) not in exclusions]
    authority_linkage_check = verify_authoritative_signal_linkage(pass_rows)
    if authority_linkage_check["status"] != "PASS":
        raise RuntimeError(f"FROZEN_SIGNAL_STAGE_LINKAGE_MISMATCH:{window_id}:{authority_linkage_check}")

    if any(identity_key(row) in exclusions for row in records + pass_rows):
        raise RuntimeError(f"CURRENT_PERMANENT_EXCLUSION_LEAK:{window_id}")
    if len({key(row) for row in records}) != len(records):
        raise RuntimeError(f"DUPLICATE_CURRENT_CANDIDATE:{window_id}")
    for row in records:
        if row.get("pattern_a_stage") != "PROGRESSED":
            raise RuntimeError(f"CURRENT_PATTERN_A_STAGE_MISMATCH:{window_id}:{key(row)}")
        if row.get("previous_pattern_a_stage") not in ALLOWED_PREVIOUS_STAGES:
            raise RuntimeError(f"PREVIOUS_PATTERN_A_STAGE_MISMATCH:{window_id}:{key(row)}")
        if str(row.get("pattern_a_lookahead_free", "")).lower() != "true":
            raise RuntimeError(f"LOOKAHEAD_ENTRY_STAGE:{window_id}:{key(row)}")

    loaded.update(
        records=records,
        pass_rows=pass_rows,
        current_exclusion_count=len(excluded_records),
        current_excluded_candidate_count=len(excluded_signals),
        source_filled_trade_count=len(historical_records),
        source_allowed_signal_count=len(historical_signals),
        current_permanent_exclusion_count=len(exclusions),
        authoritative_signal_linkage_check=authority_linkage_check,
    )
    return loaded


def compute_mdd(equity_rows: Sequence[Mapping[str, Any]], initial_capital: float) -> dict[str, Any]:
    valid: list[tuple[str, float]] = []
    for row in equity_rows:
        value = row.get("equity")
        if value is None or pd.isna(value):
            continue
        number = float(value)
        if not math.isfinite(number):
            continue
        valid.append((str(row["date"])[:10], number))
    if not valid:
        return {
            "mdd_pct": None,
            "peak_date": None,
            "trough_date": None,
            "recovery_date": None,
            "recovered": False,
        }

    peak_value = float(initial_capital)
    peak_date = valid[0][0]
    worst = 0.0
    worst_peak_value = peak_value
    worst_peak_date = peak_date
    worst_trough_date: str | None = None
    recovery_date: str | None = None
    for day, equity in valid:
        if equity >= peak_value:
            peak_value = equity
            peak_date = day
        drawdown = (equity / peak_value - 1.0) * 100.0 if peak_value else 0.0
        if drawdown < worst:
            worst = drawdown
            worst_peak_value = peak_value
            worst_peak_date = peak_date
            worst_trough_date = day
            recovery_date = None
        elif (
            worst_trough_date is not None
            and day > worst_trough_date
            and equity >= worst_peak_value
            and recovery_date is None
        ):
            recovery_date = day

    return {
        "mdd_pct": worst if worst_trough_date is not None else 0.0,
        "peak_date": worst_peak_date,
        "trough_date": worst_trough_date,
        "recovery_date": recovery_date,
        "recovered": recovery_date is not None,
    }


def summarize_valuation(
    equity_rows: Sequence[Mapping[str, Any]],
    skipped: Sequence[Mapping[str, Any]],
    window: Mapping[str, Any],
) -> dict[str, Any]:
    effective_end = str(window["effective_end"])[:10]
    rows = [row for row in equity_rows if str(row.get("date", ""))[:10] <= effective_end]
    dates = [str(row.get("date", ""))[:10] for row in rows]
    if len(dates) != len(set(dates)) or dates != sorted(dates):
        raise RuntimeError("DAILY_EQUITY_DATE_DUPLICATE_OR_ORDER_ERROR")

    observed_rows = [row for row in rows if valid_equity(row)]
    missing_dates = [str(row["date"])[:10] for row in rows if not valid_equity(row)]
    total_days = len(rows)
    observed_days = len(observed_rows)
    missing_days = total_days - observed_days
    coverage = 100.0 * observed_days / total_days if total_days else 0.0

    spans = 0
    max_streak = 0
    streak = 0
    for row in rows:
        missing = not valid_equity(row)
        if missing:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            if streak:
                spans += 1
            streak = 0
    if streak:
        spans += 1

    marks = [
        row for row in skipped
        if row.get("skip_reason") == "MISSING_EXACT_DAILY_MARK"
        and str(row.get("date", ""))[:10] <= effective_end
    ]
    mdd = compute_mdd(rows, INITIAL_CAPITAL)
    if missing_days == 0:
        mdd_type = "EXACT"
    elif coverage >= MIN_OBSERVED_COVERAGE:
        mdd_type = "OBSERVED"
    else:
        mdd_type = "OBSERVED_BELOW_90_COVERAGE"
    return {
        "mdd_type": mdd_type,
        "mdd_pct": mdd["mdd_pct"],
        "coverage_pct": coverage,
        "total_days": total_days,
        "observed_days": observed_days,
        "missing_days": missing_days,
        "unresolved_marks": len(marks),
        "missing_span_count": spans,
        "max_consecutive_missing_days": max_streak,
        "peak_date": mdd["peak_date"],
        "trough_date": mdd["trough_date"],
        "recovery_date": mdd["recovery_date"],
        "recovered": mdd["recovered"],
        "missing_equity_dates": missing_dates,
    }


def gate_status(
    *,
    window_id: str,
    metrics: Mapping[str, Any],
    valuation: Mapping[str, Any],
    v2_reference: Mapping[str, Any],
    input_audit: Mapping[str, Any],
    cost_audit: Mapping[str, Any],
    unresolved_execution_event_count: int,
) -> tuple[dict[str, str], dict[str, Any]]:
    reasons: dict[str, Any] = {}
    integrity_failures = []
    if not input_audit.get("source_hashes_verified"):
        integrity_failures.append("FROZEN_SOURCE_HASH_MISMATCH")
    if not input_audit.get("exclusion_leakage_zero"):
        integrity_failures.append("CURRENT_PERMANENT_EXCLUSION_LEAK")
    if int(input_audit.get("duplicate_input_key_count", 0)):
        integrity_failures.append("DUPLICATE_INPUT_SIGNAL_KEY")
    if int(input_audit.get("post_cutoff_entry_count", 0)):
        integrity_failures.append("POST_CUTOFF_ENTRY")
    if int(input_audit.get("lookahead_entry_count", 0)):
        integrity_failures.append("LOOKAHEAD_ENTRY")
    if int(input_audit.get("identity_overlap_violation_count", 0)):
        integrity_failures.append("EXECUTED_IDENTITY_OVERLAP")
    if int(input_audit.get("repository_v2_silent_inner_drop_count", 0)):
        integrity_failures.append("REPOSITORY_V2_SILENT_INNER_DROP")
    price_audit = input_audit.get("execution_price_audit", {})
    if int(price_audit.get("missing_exact_opens", 0)) or int(price_audit.get("price_mismatch_count", 0)):
        integrity_failures.append("EXECUTION_PRICE_AUDIT_FAILURE")
    if int(price_audit.get("next_session_execution_violation_count", 0)):
        integrity_failures.append("NEXT_SESSION_EXECUTION_RULE_FAILURE")
    if not input_audit.get("frozen_source_hashes_verified"):
        integrity_failures.append("FROZEN_SOURCE_HASH_MISMATCH")
    if metrics.get("cash_conservation_pass") is not True:
        integrity_failures.append("CASH_CONSERVATION_FAILURE")
    if metrics.get("position_cap") is not None:
        integrity_failures.append("HIDDEN_POSITION_CAP")
    if integrity_failures:
        gates_a = "FAIL"
        reasons["A"] = integrity_failures
    else:
        gates_a = "PASS"
        reasons["A"] = "Frozen authorities, PIT/stage linkage, current exclusions, lifecycle and cash conservation passed."

    gates_b = "PASS" if cost_audit.get("mismatch_count", 1) == 0 and cost_audit.get("coverage_complete") else "FAIL"
    reasons["B"] = {
        "cost_coverage_complete": bool(cost_audit.get("coverage_complete")),
        "mismatch_count": int(cost_audit.get("mismatch_count", 0)),
        "sell_tax_applied_krw": 0.0,
    }

    total_return = metrics.get("cumulative_return_pct")
    cagr = metrics.get("CAGR_pct")
    if total_return is None or cagr is None:
        gates_c = "CHECK_REQUIRED"
        reasons["C"] = "Terminal equity does not support a complete return and CAGR calculation."
    elif float(total_return) > 0 and float(cagr) > 0:
        gates_c = "PASS"
        reasons["C"] = "Net total return and CAGR are both positive."
    else:
        gates_c = "FAIL"
        reasons["C"] = "Net total return or CAGR is not positive."

    coverage = float(valuation.get("coverage_pct", 0.0) or 0.0)
    candidate_mdd = valuation.get("mdd_pct")
    v2_mdd = v2_reference.get("mdd_pct")
    abs_limit = ABSOLUTE_MDD_LIMITS[window_id]
    if coverage < MIN_OBSERVED_COVERAGE or candidate_mdd is None or v2_mdd is None:
        gates_d = "CHECK_REQUIRED"
        relative_delta = None
        reasons["D"] = "MDD evidence is unavailable or valuation coverage is below 90%."
    else:
        relative_delta = float(v2_mdd) - float(candidate_mdd)
        absolute_pass = float(candidate_mdd) >= abs_limit
        relative_pass = relative_delta < RELATIVE_MDD_LIMIT_PP
        gates_d = "PASS" if absolute_pass and relative_pass else "FAIL"
        reasons["D"] = {
            "absolute_limit_pct": abs_limit,
            "absolute_pass": absolute_pass,
            "candidate_minus_control_deterioration_pp": relative_delta,
            "relative_limit_pp": RELATIVE_MDD_LIMIT_PP,
            "relative_pass": relative_pass,
            "v2_reference_mdd_pct": v2_mdd,
        }

    terminal_equity_available = metrics.get("final_equity") is not None
    e_issues = []
    if coverage < MIN_OBSERVED_COVERAGE:
        e_issues.append("VALUATION_COVERAGE_BELOW_90_PERCENT")
    if not terminal_equity_available:
        e_issues.append("TERMINAL_EQUITY_UNRESOLVED")
    if unresolved_execution_event_count:
        e_issues.append("UNRESOLVED_EXECUTION_EVENT")
    if metrics.get("cumulative_return_pct") is None or metrics.get("CAGR_pct") is None:
        e_issues.append("RETURN_OR_CAGR_UNAVAILABLE")
    gates_e = "CHECK_REQUIRED" if e_issues else "PASS"
    reasons["E"] = e_issues or "Observed valuation gaps are within coverage policy; no other material validity issue was found."

    return {"A": gates_a, "B": gates_b, "C": gates_c, "D": gates_d, "E": gates_e}, {
        "reasons": reasons,
        "relative_mdd_deterioration_pp": relative_delta,
    }


def run_replay(
    records: Sequence[Mapping[str, Any]],
    frames: Mapping[Any, pd.DataFrame | None],
    trading_dates: Sequence[str],
    window: Mapping[str, Any],
    strategy_id: str,
) -> dict[str, Any]:
    original_schedule = portfolio.SELL_TAX_SCHEDULE
    original_valuation = portfolio._valuation_close_with_carry
    original_capital = portfolio.INITIAL_CAPITAL
    original_budget = portfolio.POSITION_BUDGET
    portfolio.SELL_TAX_SCHEDULE = ZERO_TAX_SCHEDULE
    portfolio.INITIAL_CAPITAL = INITIAL_CAPITAL
    portfolio.POSITION_BUDGET = POSITION_BUDGET
    portfolio._valuation_close_with_carry = v01.exact_close_without_carry
    try:
        result = portfolio._portfolio_replay(
            records,
            frames,
            [pd.Timestamp(day).normalize() for day in trading_dates],
            strategy_id=strategy_id,
            effective_start=pd.Timestamp(window["effective_start"]).normalize(),
            effective_end=pd.Timestamp(window["effective_end"]).normalize(),
            execution_support=pd.Timestamp(window["execution_support"]).normalize(),
        )
    finally:
        portfolio.SELL_TAX_SCHEDULE = original_schedule
        portfolio.INITIAL_CAPITAL = original_capital
        portfolio.POSITION_BUDGET = original_budget
        portfolio._valuation_close_with_carry = original_valuation
    return result


def verify_next_session_execution_dates(
    records: Sequence[Mapping[str, Any]],
    frames: Mapping[Any, pd.DataFrame | None],
    trading_dates: Sequence[str],
    window: Mapping[str, Any],
) -> dict[str, Any]:
    dates = [str(day)[:10] for day in trading_dates]
    effective_end = str(window["effective_end"])[:10]
    support = str(window["execution_support"])[:10]
    failures = []
    checked_exit_count = 0

    def next_exact_open(row: Mapping[str, Any], signal_day: str, limit: str) -> str | None:
        for day in dates:
            if day <= signal_day:
                continue
            if day > limit:
                break
            price = portfolio._price(row, frames, pd.Timestamp(day).normalize(), "open")
            if price is not None and price > 0:
                return day
        return None

    for row in records:
        ticker = str(row.get("ticker", "")).zfill(6)
        signal_day = str(row.get("entry_signal_date", ""))[:10]
        entry_execution_day = str(row.get("entry_execution_date", ""))[:10]
        expected_entry_day = next_exact_open(row, signal_day, effective_end)
        if expected_entry_day != entry_execution_day:
            failures.append({
                "pair_id": row.get("pair_id"), "ticker": ticker, "event": "ENTRY",
                "signal_date": signal_day, "execution_date": entry_execution_day,
                "expected_execution_date": expected_entry_day,
            })
        if str(row.get("trade_status")) == "REALIZED":
            checked_exit_count += 1
            exit_signal_day = str(row.get("exit_signal_date", ""))[:10]
            exit_execution_day = str(row.get("exit_execution_date", ""))[:10]
            expected_exit_day = next_exact_open(row, exit_signal_day, support)
            if (
                expected_exit_day != exit_execution_day
                or exit_signal_day > effective_end
            ):
                failures.append({
                    "pair_id": row.get("pair_id"), "ticker": ticker, "event": "EXIT",
                    "signal_date": exit_signal_day, "execution_date": exit_execution_day,
                    "expected_execution_date": expected_exit_day,
                })
    return {
        "status": "PASS" if not failures else "FAIL",
        "checked_entry_count": len(records),
        "checked_realized_exit_count": checked_exit_count,
        "violation_count": len(failures),
        "violations": failures[:20],
    }


def load_v2_references() -> dict[str, dict[str, Any]]:
    summary_path = ROOT / V2_REFERENCE_ROOT / "summary.json"
    if not summary_path.is_file():
        raise RuntimeError(f"MISSING_V2_REFERENCE_SUMMARY:{summary_path}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    metrics_by_window = summary.get("metrics_by_window", {})
    references: dict[str, dict[str, Any]] = {}
    for window_id in WINDOW_IDS:
        key_id = window_id.replace("-", "-")
        metrics = metrics_by_window.get(key_id)
        if not metrics:
            raise RuntimeError(f"MISSING_V2_REFERENCE_WINDOW:{window_id}")
        equity_path = ROOT / V2_REFERENCE_ROOT / f"daily_equity_{window_id.lower().replace('-', '_')}.csv"
        event_path = ROOT / V2_REFERENCE_ROOT / f"portfolio_events_{window_id.lower().replace('-', '_')}.csv"
        if not equity_path.is_file() or not event_path.is_file():
            raise RuntimeError(f"MISSING_V2_REFERENCE_OUTPUT:{window_id}")
        equity = pd.read_csv(equity_path).to_dict(orient="records")
        valuation = summarize_valuation(equity, (), {
            "effective_end": metrics["effective_end"],
        })
        events = pd.read_csv(event_path)
        exits = events.loc[
            events["event_type"].astype(str).eq("EXIT")
            & events["event_status"].astype(str).eq("EXECUTED")
        ]
        returns = pd.to_numeric(exits.get("net_return_pct"), errors="coerce").dropna()
        references[window_id] = {
            "ending_equity_krw": metrics.get("ending_equity_krw"),
            "profit_krw": (
                float(metrics["ending_equity_krw"]) - INITIAL_CAPITAL
                if metrics.get("ending_equity_krw") is not None else None
            ),
            "total_return_pct": metrics.get("total_return_pct"),
            "cagr_pct": metrics.get("cagr_pct"),
            "mdd_pct": valuation["mdd_pct"],
            "mdd_type": valuation["mdd_type"],
            "coverage_pct": valuation["coverage_pct"],
            "cash_shortage_skip_rate_pct": metrics.get("cash_shortage_skip_rate_pct"),
            "turnover_krw": metrics.get("turnover_krw"),
            "turnover_multiple": metrics.get("turnover_multiple"),
            "trade_count": metrics.get("executed_entry_count"),
            "closed_trade_count": metrics.get("realized_exit_count"),
            "positive_trade_rate_pct": metrics.get("win_rate_pct"),
            "median_trade_return_pct": float(returns.median()) if len(returns) else None,
            "+30_count": int((returns >= 30).sum()),
            "+50_count": int((returns >= 50).sum()),
            "+100_count": int((returns >= 100).sum()),
            "-30_count": int((returns <= -30).sum()),
            "-40_count": int((returns <= -40).sum()),
            "-50_count": int((returns <= -50).sum()),
            "-60_count": int((returns <= -60).sum()),
        }
        if abs(float(references[window_id]["mdd_pct"]) - V2_MDD_REFERENCE[window_id]) > 0.1:
            raise RuntimeError(f"V2_REFERENCE_MDD_PROFILE_MISMATCH:{window_id}:{references[window_id]}")
    return references


def window_metrics_from_replay(
    replay: Mapping[str, Any],
    inputs: Mapping[str, Any],
    valuation: Mapping[str, Any],
    trading_dates: Sequence[str],
) -> dict[str, Any]:
    metrics = dict(replay["metrics"])
    window = inputs["window"]
    support_date = str(window["execution_support"])[:10]
    support_rows = [row for row in replay["daily_equity"] if str(row.get("date", ""))[:10] == support_date]
    if len(support_rows) != 1:
        raise RuntimeError(f"MISSING_OR_DUPLICATE_EXECUTION_SUPPORT_EQUITY:{inputs['window_id']}")
    terminal = support_rows[0].get("equity")
    terminal_equity = None if terminal is None or pd.isna(terminal) or not math.isfinite(float(terminal)) else float(terminal)
    elapsed_days = max(1, int((pd.Timestamp(window["effective_end"]) - pd.Timestamp(window["effective_start"])).days))
    total_return = terminal_equity / INITIAL_CAPITAL - 1.0 if terminal_equity is not None else None
    cagr = (
        (terminal_equity / INITIAL_CAPITAL) ** (365.25 / elapsed_days) - 1.0
        if terminal_equity is not None and terminal_equity > 0 else None
    )
    metrics.update(
        final_equity=terminal_equity,
        final_equity_at_effective_close=next(
            (row.get("equity") for row in replay["daily_equity"] if str(row.get("date", ""))[:10] == str(window["effective_end"])[:10]),
            None,
        ),
        ending_equity_krw=terminal_equity,
        profit_krw=terminal_equity - INITIAL_CAPITAL if terminal_equity is not None else None,
        cumulative_return_pct=total_return * 100.0 if total_return is not None else None,
        CAGR_pct=cagr * 100.0 if cagr is not None else None,
        mdd_pct=valuation["mdd_pct"],
        mdd_type=valuation["mdd_type"],
        coverage_pct=valuation["coverage_pct"],
        total_days=valuation["total_days"],
        observed_days=valuation["observed_days"],
        missing_days=valuation["missing_days"],
        unresolved_marks=valuation["unresolved_marks"],
        missing_span_count=valuation["missing_span_count"],
        max_consecutive_missing_days=valuation["max_consecutive_missing_days"],
        mdd_peak_date=valuation["peak_date"],
        mdd_trough_date=valuation["trough_date"],
        mdd_recovery_date=valuation["recovery_date"],
        mdd_recovered=valuation["recovered"],
        initial_capital_krw=INITIAL_CAPITAL,
        effective_start=window["effective_start"],
        effective_end=window["effective_end"],
        execution_support=window["execution_support"],
        current_exclusion_filtered_count=inputs["current_exclusion_count"],
        current_allowed_signal_count=len(inputs["pass_rows"]),
        source_allowed_signal_count=inputs["source_allowed_signal_count"],
        source_filled_trade_count=inputs["source_filled_trade_count"],
        worker_count=WORKERS,
    )
    return metrics


def audit_costs(events: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = []
    mismatches = 0
    executed = [row for row in events if row.get("event_status") == "EXECUTED"]
    for event in executed:
        is_exit = event.get("event_type") == "EXIT"
        reference = float(event.get("reference_open") or 0.0)
        expected_fill = reference * (1.0 - SLIPPAGE_RATE if is_exit else 1.0 + SLIPPAGE_RATE)
        notional = float(event.get("notional") or 0.0)
        expected_commission = notional * COMMISSION_RATE
        valid = (
            math.isclose(float(event.get("fill_price") or 0.0), expected_fill, rel_tol=0.0, abs_tol=1e-8)
            and math.isclose(float(event.get("commission") or 0.0), expected_commission, rel_tol=0.0, abs_tol=1e-6)
            and float(event.get("sell_tax") or 0.0) == 0.0
        )
        mismatches += int(not valid)
        rows.append({
            **event,
            "commission_rate": COMMISSION_RATE,
            "slippage_rate": SLIPPAGE_RATE,
            "sell_tax_applied_krw": 0.0,
            "official_cost_status": "PASS" if valid else "FAIL",
        })
    return rows, {
        "executed_cost_event_count": len(executed),
        "mismatch_count": mismatches,
        "coverage_complete": len(rows) == len(executed),
        "sell_tax_applied_krw": 0.0,
    }


def verify_executed_identity_lifecycle(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    active: set[tuple[str, str, str]] = set()
    opened = 0
    closed = 0
    violations = []
    # The engine appends all same-session exits before same-session entries.
    for event in events:
        if event.get("event_status") != "EXECUTED":
            continue
        ident = (
            str(event.get("ticker", "")).zfill(6),
            str(event.get("isu_cd", "")).upper(),
            str(event.get("market", "")).upper(),
        )
        if event.get("event_type") == "EXIT":
            if ident not in active:
                violations.append({"identity": ident, "event": "EXIT_WITHOUT_ACTIVE_ENTRY", "date": event.get("execution_date")})
            else:
                active.remove(ident)
                closed += 1
        elif event.get("event_type") == "ENTRY":
            if ident in active:
                violations.append({"identity": ident, "event": "DUPLICATE_ACTIVE_ENTRY", "date": event.get("execution_date")})
            else:
                active.add(ident)
                opened += 1
    return {
        "executed_entries": opened,
        "executed_exits": closed,
        "open_identity_count_after_support": len(active),
        "violation_count": len(violations),
        "violations": violations[:20],
    }


def cost_and_input_audits(
    inputs: Mapping[str, Any],
    replay: Mapping[str, Any],
    loader_audit: Mapping[str, Any],
    price_audit: Mapping[str, Any],
    source_hashes_verified: bool,
) -> dict[str, Any]:
    exclusions = current_exclusion_keys()
    all_records = list(inputs["records"])
    all_signals = list(inputs["pass_rows"])
    events = list(replay["events"])
    lifecycle = verify_executed_identity_lifecycle(events)
    post_cutoff = sum(
        str(row.get("entry_execution_date", ""))[:10] > str(inputs["window"]["effective_end"])[:10]
        for row in all_records
    )
    lookahead = sum(
        str(row.get("pattern_a_lookahead_free", "")).lower() != "true"
        for row in all_records
    )
    loader_silent_drops = sum(int(row.get("silent_inner_drop_count", 0) or 0) for row in loader_audit.values())
    leakage = sum(identity_key(row) in exclusions for row in all_records + all_signals)
    duplicates = len(all_records) - len({key(row) for row in all_records})
    input_audit = {
        "source_hashes_verified": source_hashes_verified,
        "frozen_source_hashes_verified": source_hashes_verified,
        "exclusion_leakage_zero": leakage == 0,
        "exclusion_leakage_count": leakage,
        "current_exclusion_count": len(exclusions),
        "window_current_excluded_fill_count": inputs["current_exclusion_count"],
        "window_current_excluded_signal_count": inputs["current_excluded_candidate_count"],
        "duplicate_input_key_count": duplicates,
        "post_cutoff_entry_count": int(post_cutoff),
        "lookahead_entry_count": int(lookahead),
        "identity_overlap_violation_count": lifecycle["violation_count"],
        "identity_lifecycle_audit": lifecycle,
        "repository_v2_silent_inner_drop_count": loader_silent_drops,
        "execution_price_audit": dict(price_audit),
        "authoritative_signal_linkage_check": dict(inputs["authoritative_signal_linkage_check"]),
        "historical_runner_code_hash_checks": dict(inputs.get("code_checks", {})),
        "historical_runner_code_hash_mismatch_count": sum(
            row.get("expected_sha256") != row.get("actual_sha256")
            for row in inputs.get("code_checks", {}).values()
        ),
        "source_allowed_signal_count": inputs["source_allowed_signal_count"],
        "current_allowed_signal_count": len(all_signals),
        "current_filled_signal_count": len(all_records),
        "source_filled_signal_count": inputs["source_filled_trade_count"],
    }
    return input_audit


def cash_diagnostics(
    replay: Mapping[str, Any],
    metrics: Mapping[str, Any],
    diagnostics: Mapping[str, Any],
) -> dict[str, Any]:
    candidates = list(replay["entry_candidate_audit"])
    attempts = sum(row.get("decision") in {"EXECUTED", "CASH_INSUFFICIENT"} for row in candidates)
    cash_skips = int(metrics.get("cash_shortage_skipped_entries", 0) or 0)
    return {
        "eligible_entry_attempts": attempts,
        "cash_shortage_skipped_entries": cash_skips,
        "cash_shortage_skip_rate_pct": cash_skips / attempts * 100.0 if attempts else 0.0,
        "average_capital_utilization_pct": metrics.get("average_capital_utilization_pct"),
        "maximum_capital_utilization_pct": metrics.get("maximum_capital_utilization_pct"),
        "average_cash_ratio_pct": metrics.get("average_cash_ratio_pct"),
        "average_concurrent_positions": metrics.get("average_concurrent_positions"),
        "maximum_concurrent_positions": metrics.get("maximum_concurrent_positions"),
        "turnover_krw": metrics.get("turnover_krw"),
        "turnover_multiple_initial_capital": metrics.get("turnover_multiple"),
        "cash_conservation_pass": metrics.get("cash_conservation_pass"),
        "cash_shortage_is_gate": False,
    }


def build_cash_skip_lifecycle(inputs: Mapping[str, Any], replay: Mapping[str, Any]) -> list[dict[str, Any]]:
    later_by_identity: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in inputs["pass_rows"]:
        later_by_identity[identity_key(row)].append(str(row.get("entry_signal_date", ""))[:10])
    for dates in later_by_identity.values():
        dates.sort()
    record_by_id = {str(row.get("pair_id")): row for row in inputs["records"]}
    output = []
    for event in replay["events"]:
        if event.get("event_type") != "ENTRY" or event.get("event_status") != "SKIPPED_CASH_UNAVAILABLE":
            continue
        record = record_by_id[str(event.get("pair_id"))]
        ident = identity_key(record)
        signal_day = str(event.get("signal_date", ""))[:10]
        later = [day for day in later_by_identity.get(ident, []) if day > signal_day]
        output.append({
            "ticker": ident[0],
            "isu_cd": ident[1],
            "cash_skipped_signal_date": signal_day,
            "later_allowed_signal_count": len(later),
            "later_allowed_signal_dates": "|".join(later),
            "later_signals_remain_in_portfolio_event_stream": True,
            "portfolio_decision_after_skip": "IDENTITY_REMAINS_FLAT_AND_LATER_SIGNAL_IS_REEVALUATED",
        })
    return output


def unresolved_valuation_rows(
    window_id: str,
    replay: Mapping[str, Any],
    valuation: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    record_by_pair = {str(row.get("pair_id", "")): row for row in records}
    for row in replay["skipped"]:
        if row.get("skip_reason") != "MISSING_EXACT_DAILY_MARK":
            continue
        source = record_by_pair.get(str(row.get("pair_id", "")), {})
        grouped[(
            str(row.get("ticker", source.get("ticker", ""))).zfill(6),
            str(row.get("identity", row.get("isu_cd", source.get("isu_cd", "")))).upper(),
        )].append(row)
    rows = []
    total_days = max(1, int(valuation["total_days"]))
    for (ticker, isu_cd), marks in sorted(grouped.items()):
        dates = sorted({str(row.get("date", ""))[:10] for row in marks if row.get("date")})
        rows.append({
            "window_id": window_id,
            "ticker": ticker,
            "isu_cd": isu_cd,
            "unresolved_valuation_marks": len(marks),
            "missing_valuation_days": len(dates),
            "first_date": dates[0] if dates else None,
            "last_date": dates[-1] if dates else None,
            "whole_portfolio_missing_equity_days": len(valuation["missing_equity_dates"]),
            "coverage_pct": valuation["coverage_pct"],
            "coverage_impact_pp_upper_bound": len(dates) / total_days * 100.0,
            "conclusion_impact": (
                "TERMINAL_OR_EXECUTION_VALIDITY_REVIEW_REQUIRED"
                if str(valuation.get("recovery_date") or "") >= str(dates[-1] if dates else "9999")
                else "OBSERVED_EQUITY_GAPS_EXCLUDED_FROM_MDD"
            ),
        })
    return rows


def write_window_outputs(
    inputs: Mapping[str, Any],
    replay: Mapping[str, Any],
    frames: Mapping[Any, pd.DataFrame | None],
    loader_audit: Mapping[str, Any],
    cap_audit: Mapping[str, Any],
    price_audit: Mapping[str, Any],
    v2_reference: Mapping[str, Any],
    trading_dates: Sequence[str],
    source_hashes_verified: bool,
) -> dict[str, Any]:
    window_id = str(inputs["window_id"])
    window = inputs["window"]
    out = ROOT / OUTPUT_ROOT / window_id.lower().replace("-", "_")
    out.mkdir(parents=True, exist_ok=False)

    events = [dict(row) for row in replay["events"]]
    equity_rows = [dict(row) for row in replay["daily_equity"]]
    skipped = [dict(row) for row in replay["skipped"]]
    valuation = summarize_valuation(equity_rows, skipped, window)
    metrics = window_metrics_from_replay(replay, inputs, valuation, trading_dates)
    diagnostics = v01.build_portfolio_diagnostics(replay, inputs["records"], frames, window, inputs["summary"])
    costs, cost_status = audit_costs(events)
    input_status = cost_and_input_audits(inputs, replay, loader_audit, price_audit, source_hashes_verified)
    unresolved_execution_events = sum(row.get("event_status") == "UNRESOLVED" for row in events)
    gates, gate_evidence = gate_status(
        window_id=window_id,
        metrics=metrics,
        valuation=valuation,
        v2_reference=v2_reference,
        input_audit=input_status,
        cost_audit=cost_status,
        unresolved_execution_event_count=unresolved_execution_events,
    )
    metrics["gates"] = gates
    metrics["gate_evidence"] = gate_evidence
    metrics["diagnostics"] = diagnostics
    metrics["input_audit"] = input_status
    metrics["cost_audit"] = cost_status
    metrics["unresolved_execution_event_count"] = unresolved_execution_events

    peak_equity = INITIAL_CAPITAL
    for row in equity_rows:
        row["valuation_valid"] = valid_equity(row)
        row["mdd_type"] = valuation["mdd_type"]
        row["coverage_pct"] = valuation["coverage_pct"]
        if row["valuation_valid"]:
            value = float(row["equity"])
            peak_equity = max(peak_equity, value)
            row["drawdown"] = value / peak_equity - 1.0 if peak_equity else 0.0
        else:
            row["drawdown"] = None

    cost_mismatches = cost_status["mismatch_count"]
    realized_sell_count = sum(row.get("event_type") == "EXIT" and row.get("event_status") == "EXECUTED" for row in events)
    if realized_sell_count != sum(row.get("event_type") == "EXIT" and row.get("event_status") == "EXECUTED" for row in costs):
        cost_status["coverage_complete"] = False
        gates["B"] = "FAIL"
        metrics["gates"]["B"] = "FAIL"
    entry_attempts = cash_diagnostics(replay, metrics, diagnostics)
    cash_skip_lifecycle = build_cash_skip_lifecycle(inputs, replay)
    valuation_audit = [dict(row) for row in replay["valuation_gap_audit"]]
    valuation_audit.extend({
        "pair_id": row.get("pair_id"),
        "ticker": row.get("ticker"),
        "identity": row.get("identity"),
        "valuation_date": row.get("date"),
        "status": "UNRESOLVED_MISSING_EXACT_DAILY_CLOSE",
        "used_for_execution": False,
    } for row in skipped if row.get("skip_reason") == "MISSING_EXACT_DAILY_MARK")
    unresolved_rows = unresolved_valuation_rows(window_id, replay, valuation, inputs["records"])

    execution_contract = {
        "run_id": "PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_REALISTIC_PORTFOLIO_V02",
        "strategy_id": STRATEGY_ID,
        "display_name": DISPLAY_NAME,
        "window": window,
        "frozen_rule": {
            "entry": "Pattern B DEPRESSED AND current Pattern A Stage PROGRESSED AND previous authoritative Pattern A Stage in {EARLY_TREND, TRANSITION}",
            "exit": "Pattern B NORMAL observed while held, then next exact KRX session open",
            "strategy_rule_changed": False,
        },
        "portfolio": {
            "initial_capital_krw": INITIAL_CAPITAL,
            "per_position_total_buy_budget_krw": POSITION_BUDGET,
            "position_cap": None,
            "partial_fill": False,
            "cash_shortage_status": "SKIPPED_CASH_UNAVAILABLE",
            "cash_shortage_is_gate": False,
            "same_open_exit_reentry": False,
            "sale_proceeds_settlement": "next exact KRX session; unavailable to same-open entries",
            "within_day_order": "release previously settled proceeds; exits; buys ordered by exact signal-date KRX market cap descending then ticker and pair id",
            "portfolio_aware_signal_stream": "all frozen allowed candidate signals remain in chronological stream; actual active identity and current cash determine each execution; cash-skipped identities remain flat and later signals are reevaluated",
            "workers": WORKERS,
        },
        "costs": {
            "buy_commission_rate": COMMISSION_RATE,
            "sell_commission_rate": COMMISSION_RATE,
            "buy_slippage_rate": SLIPPAGE_RATE,
            "sell_slippage_rate": SLIPPAGE_RATE,
            "sell_tax_or_transaction_tax_applied_to_official_path": False,
            "sell_tax_applied_krw": 0.0,
        },
        "valuation": {
            "daily_mark": "exact Repository V2 close; if any held position cannot be marked, the whole portfolio equity day is unresolved",
            "unresolved_equity_day_policy": "exclude the entire day from Observed MDD; no missing-position omission, zero fill, nearest date, interpolation, or arbitrary carry",
            "approved_same_date_exchange_status_carry": "only when common rule evidence authorizes it; audit required",
            "coverage_formula": "valid whole-portfolio equity trading days / total effective-window trading days",
            "mdd_thresholds_pct": ABSOLUTE_MDD_LIMITS,
            "exact_coverage_pct": 100.0,
            "observed_coverage_min_pct": MIN_OBSERVED_COVERAGE,
            "observed_coverage_max_exclusive_pct": 100.0,
            "v2_relative_mdd_limit_pp": RELATIVE_MDD_LIMIT_PP,
        },
        "sources": {
            "historical_window_source_dir": str(inputs["source_dir"].relative_to(ROOT)),
            "historical_window_source_sha256": inputs["source_hashes"],
            "current_permanent_exclusion_count": len(current_exclusion_keys()),
            "current_permanent_exclusion_policy_path": str(EXCLUSION_POLICY_PATH),
            "current_permanent_exclusion_policy_sha256": sha256(ROOT / EXCLUSION_POLICY_PATH),
            "candidate_signal_history": str(STAGE_HISTORY_PATH),
            "candidate_stage_linkage": str(STAGE_LINKAGE_PATH),
            "candidate_signal_history_sha256": sha256(ROOT / STAGE_HISTORY_PATH),
            "candidate_stage_linkage_sha256": sha256(ROOT / STAGE_LINKAGE_PATH),
            "frozen_authoritative_signal_linkage_audit": inputs["authoritative_signal_linkage_check"],
            "historical_candidate_runner_code_hash_checks": inputs.get("code_checks", {}),
            "market_cap_priority_audit": cap_audit,
            "execution_price_audit": price_audit,
            "repository_loader_unavailable_ticker_count": sum(row.get("status") == "EXPLICIT_DATA_UNAVAILABLE" for row in loader_audit.values()),
            "repository_v2_silent_inner_drop_count": input_status["repository_v2_silent_inner_drop_count"],
        },
    }
    json_write(out / "execution_contract.json", execution_contract)
    pd.DataFrame(events).to_csv(out / "portfolio_events.csv", index=False, encoding="utf-8")
    pd.DataFrame(equity_rows).to_csv(out / "daily_equity.csv", index=False, encoding="utf-8")
    pd.DataFrame(skipped).to_csv(out / "skipped_entries.csv", index=False, encoding="utf-8")
    pd.DataFrame(costs).to_csv(out / "cost_audit.csv", index=False, encoding="utf-8")
    pd.DataFrame([
        {
            "pair_id": row.get("pair_id"), "ticker": row.get("ticker"),
            "date": row.get("execution_date"), "event_type": row.get("event_type"),
            "event_status": row.get("event_status"), "cash_before": row.get("cash_before"),
            "cash_after": row.get("cash_after"), "pending_sale_proceeds": row.get("pending_sale_proceeds"),
            "notional": row.get("notional"), "commission": row.get("commission"),
        }
        for row in events if row.get("event_status") in {"EXECUTED", "SKIPPED_CASH_UNAVAILABLE"}
    ]).to_csv(out / "cash_audit.csv", index=False, encoding="utf-8")
    pd.DataFrame(valuation_audit).to_csv(out / "valuation_audit.csv", index=False, encoding="utf-8")
    pd.DataFrame(replay["entry_candidate_audit"]).to_csv(out / "entry_attempt_audit.csv", index=False, encoding="utf-8")
    pd.DataFrame(cash_skip_lifecycle).to_csv(out / "cash_skip_lifecycle_audit.csv", index=False, encoding="utf-8")
    pd.DataFrame(diagnostics["annual_performance"]).to_csv(out / "annual_performance.csv", index=False, encoding="utf-8")
    pd.DataFrame(diagnostics["realized_trades"]).to_csv(out / "trade_distribution.csv", index=False, encoding="utf-8")
    json_write(out / "hidden_position_cap_audit.json", {
        "configured_position_cap": None,
        "maximum_concurrent_positions": metrics.get("maximum_concurrent_positions"),
        "position_limit_skip_count": sum(str(row.get("event_status", "")).startswith("SKIPPED_POSITION") for row in events),
        "status": "PASS_NO_POSITION_CAP_OR_POSITION_LIMIT_SKIP",
    })
    json_write(out / "valuation_coverage.json", valuation)
    json_write(out / "portfolio_metrics.json", metrics)
    json_write(out / "official_adoption_gates.json", {
        "window_id": window_id,
        "gates": gates,
        "gate_evidence": gate_evidence,
        "cash_shortage_is_gate": False,
    })
    json_write(out / "input_audit.json", input_status)
    json_write(out / "cost_audit_summary.json", cost_status)
    json_write(out / "v2_reference.json", dict(v2_reference))
    return {
        "window_id": window_id,
        "window": window,
        "metrics": metrics,
        "gates": gates,
        "gate_evidence": gate_evidence,
        "diagnostics": diagnostics,
        "valuation": valuation,
        "cash_diagnostics": entry_attempts,
        "unresolved_valuation_rows": unresolved_rows,
        "cost_status": cost_status,
        "input_status": input_status,
        "v2_reference": dict(v2_reference),
    }


def run_preflight() -> dict[str, Any]:
    out_root = ROOT / OUTPUT_ROOT
    if out_root.exists():
        raise RuntimeError(f"V02_OUTPUT_ALREADY_EXISTS_NO_AUTOMATIC_RETRY:{out_root}")
    if len(current_exclusion_keys()) != len(PERMANENT_IDENTITY_EXCLUSIONS):
        raise RuntimeError("CURRENT_PERMANENT_EXCLUSION_NORMALIZATION_COLLISION")
    if candidate_runner.WORKERS != WORKERS:
        raise RuntimeError(f"MARKET_DATA_WORKER_COUNT_NOT_10:{candidate_runner.WORKERS}")

    inputs_by_window = {wid: load_window_inputs(wid) for wid in WINDOW_IDS}
    sample_source = inputs_by_window["P2-1"]
    records = sample_source["records"]
    if len(records) < 20:
        raise RuntimeError("PREFLIGHT_SAMPLE_TOO_SMALL")
    sample_n = min(30, len(records))
    indexes = np.linspace(0, len(records) - 1, num=sample_n, dtype=int)
    sample = [dict(records[int(index)]) for index in sorted(set(indexes.tolist()))]
    sample_tickers = sorted({str(row["ticker"]).zfill(6) for row in sample})

    started = time.perf_counter()
    cpu_started = time.process_time()
    rss_start = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    load_started = time.perf_counter()
    daily_frames, loader_audit, _repository = candidate_runner._load_prices(
        ROOT, sample_tickers,
        sample_source["window"]["effective_start"],
        sample_source["window"]["execution_support"],
    )
    sample_silent_drops = sum(
        int(row.get("silent_inner_drop_count", 0) or 0)
        for row in loader_audit.values()
    )
    if sample_silent_drops:
        raise RuntimeError(f"PREFLIGHT_REPOSITORY_V2_SILENT_INNER_DROP:{sample_silent_drops}")
    price_load_seconds = time.perf_counter() - load_started
    intervals, trading_dates, market_authority = pattern_b_base._load_authorities(ROOT)
    frames = v01.build_component_frames(sample, daily_frames, intervals, trading_dates)
    cap_lookup = v01.ExactMarketCapPriority()
    cap_started = time.perf_counter()
    cap_audit = cap_lookup.attach(sample)
    cap_seconds = time.perf_counter() - cap_started
    price_audit = v01.verify_execution_prices(sample, frames, sample_source["window"])
    next_session_audit = verify_next_session_execution_dates(sample, frames, trading_dates, sample_source["window"])
    price_audit.update(
        next_session_execution_audit=next_session_audit,
        next_session_execution_violation_count=next_session_audit["violation_count"],
    )
    if next_session_audit["status"] != "PASS":
        raise RuntimeError(f"PREFLIGHT_NEXT_SESSION_EXECUTION_RULE_FAILURE:{next_session_audit}")
    replay_started = time.perf_counter()
    replay = run_replay(
        sample, frames, trading_dates, sample_source["window"],
        "PATTERN_B_ET_REALISTIC_PREFLIGHT_V02_P2_1",
    )
    replay_seconds = time.perf_counter() - replay_started
    valuation = summarize_valuation(replay["daily_equity"], replay["skipped"], sample_source["window"])
    executed_sells = [
        row for row in replay["events"]
        if row.get("event_type") == "EXIT" and row.get("event_status") == "EXECUTED"
    ]
    sample_tax = sum(float(row.get("sell_tax") or 0.0) for row in executed_sells)
    if replay["metrics"].get("cash_conservation_pass") is not True or sample_tax != 0.0:
        raise RuntimeError("PREFLIGHT_CASH_OR_ZERO_TAX_SANITY_FAILURE")

    now = datetime.now(timezone.utc).isoformat()
    total_estimate = 0.0
    estimates = {}
    for wid, data in inputs_by_window.items():
        active_tickers = sorted({str(row["ticker"]).zfill(6) for row in data["records"]})
        cap_dates = {
            (str(row.get("signal_market", row.get("entry_market", ""))).upper(), str(row.get("entry_signal_date", ""))[:10])
            for row in data["records"]
        }
        day_count = sum(
            str(data["window"]["effective_start"])[:10] <= day <= str(data["window"]["execution_support"])[:10]
            for day in trading_dates
        )
        price_est = price_load_seconds / max(1, len(sample_tickers)) * len(active_tickers)
        cap_est = cap_seconds / max(1, int(cap_audit["partition_count"])) * len(cap_dates)
        replay_est = replay_seconds * len(data["records"]) / max(1, sample_n) * day_count / max(1, valuation["total_days"])
        est = price_est + cap_est + replay_est + 3.0
        estimates[wid] = {
            "current_candidate_count": len(data["records"]),
            "unique_ticker_count": len(active_tickers),
            "exact_market_cap_partition_count": len(cap_dates),
            "trading_sessions": day_count,
            "estimated_seconds": round(est, 2),
        }
        total_estimate += est
    rss_end = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_scale = 1 if sys.platform == "darwin" else 1024
    result = {
        "status": "PASS" if replay["metrics"].get("cash_conservation_pass") is True and sample_tax == 0.0 else "CHECK_REQUIRED",
        "run_id": "PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_REALISTIC_PORTFOLIO_V02",
        "execution_timestamp_utc": now,
        "starting_head": __import__("subprocess").check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "starting_origin_main": __import__("subprocess").check_output(["git", "rev-parse", "origin/main"], cwd=ROOT, text=True).strip(),
        "starting_worktree_status": __import__("subprocess").check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip(),
        "official_criteria_sha256": sha256(ROOT / OFFICIAL_CRITERIA_PATH),
        "common_rules_sha256": sha256(ROOT / COMMON_RULES_PATH),
        "permanent_exclusion_policy_path": str(EXCLUSION_POLICY_PATH),
        "permanent_exclusion_policy_sha256": sha256(ROOT / EXCLUSION_POLICY_PATH),
        "permanent_exclusion_policy_version": sorted({value["policy_version"] for value in PERMANENT_IDENTITY_EXCLUSIONS.values()}),
        "permanent_exclusion_identity_count": len(PERMANENT_IDENTITY_EXCLUSIONS),
        "sample_window": "P2-1",
        "sample_candidate_count": len(sample),
        "sample_ticker_count": len(sample_tickers),
        "sample_wall_seconds": round(time.perf_counter() - started, 2),
        "sample_cpu_seconds": round(time.process_time() - cpu_started, 2),
        "sample_peak_rss_bytes": int(rss_end * rss_scale),
        "sample_peak_rss_delta_bytes": int(max(0, rss_end - rss_start) * rss_scale),
        "sample_price_load_seconds": round(price_load_seconds, 2),
        "sample_market_cap_lookup_seconds": round(cap_seconds, 2),
        "sample_replay_seconds": round(replay_seconds, 2),
        "sample_market_cap_partition_count": cap_audit["partition_count"],
        "sample_execution_price_audit": price_audit,
        "sample_repository_v2_silent_inner_drop_count": sample_silent_drops,
        "sample_daily_valuation": valuation,
        "sample_cash_conservation_pass": replay["metrics"].get("cash_conservation_pass"),
        "sample_sell_tax_applied_krw": sample_tax,
        "window_estimates": estimates,
        "estimated_total_seconds": round(total_estimate, 2),
        "estimated_total_minutes": round(total_estimate / 60.0, 2),
        "execution_limit_seconds": 7200,
        "estimated_runtime_within_two_hours": total_estimate < 7200,
        "workers": WORKERS,
        "frozen_source_hashes": {
            "candidate_signal_stage_history": sha256(ROOT / STAGE_HISTORY_PATH),
            "candidate_stage_linkage": sha256(ROOT / STAGE_LINKAGE_PATH),
            **{wid: data["source_hashes"] for wid, data in inputs_by_window.items()},
        },
        "frozen_source_hashes_verified_by_window": {
            wid: frozen_source_hashes_verified(data)
            for wid, data in inputs_by_window.items()
        },
        "market_authority": market_authority,
    }
    if not all(result["frozen_source_hashes_verified_by_window"].values()):
        raise RuntimeError("PREFLIGHT_FROZEN_SOURCE_HASH_VERIFICATION_FAILED")
    out_root.mkdir(parents=True, exist_ok=False)
    json_write(out_root / "preflight.json", result)
    return result


def combine_gate(statuses: Sequence[str]) -> str:
    if "CHECK_REQUIRED" in statuses:
        return "CHECK_REQUIRED"
    if "FAIL" in statuses:
        return "FAIL"
    return "PASS"


def compare_to_v2(
    window_id: str,
    candidate_metrics: Mapping[str, Any],
    candidate_diagnostics: Mapping[str, Any],
    candidate_cash: Mapping[str, Any],
    candidate_gates: Mapping[str, str],
    v2: Mapping[str, Any],
) -> dict[str, Any]:
    deterioration = float(v2["mdd_pct"]) - float(candidate_metrics["mdd_pct"]) if candidate_metrics.get("mdd_pct") is not None else None
    return {
        "window_id": window_id,
        "candidate_total_return_pct": candidate_metrics.get("cumulative_return_pct"),
        "v2_total_return_pct": v2.get("total_return_pct"),
        "total_return_delta_pp": candidate_metrics.get("cumulative_return_pct") - v2.get("total_return_pct") if candidate_metrics.get("cumulative_return_pct") is not None and v2.get("total_return_pct") is not None else None,
        "candidate_cagr_pct": candidate_metrics.get("CAGR_pct"),
        "v2_cagr_pct": v2.get("cagr_pct"),
        "cagr_delta_pp": candidate_metrics.get("CAGR_pct") - v2.get("cagr_pct") if candidate_metrics.get("CAGR_pct") is not None and v2.get("cagr_pct") is not None else None,
        "candidate_profit_krw": candidate_metrics.get("profit_krw"),
        "v2_profit_krw": v2.get("profit_krw"),
        "candidate_mdd_pct": candidate_metrics.get("mdd_pct"),
        "candidate_mdd_type": candidate_metrics.get("mdd_type"),
        "candidate_coverage_pct": candidate_metrics.get("coverage_pct"),
        "v2_mdd_pct": v2.get("mdd_pct"),
        "v2_mdd_type": v2.get("mdd_type"),
        "v2_coverage_pct": v2.get("coverage_pct"),
        "mdd_delta_pp_candidate_minus_v2": candidate_metrics.get("mdd_pct") - v2.get("mdd_pct") if candidate_metrics.get("mdd_pct") is not None else None,
        "mdd_deterioration_pp": deterioration,
        "relative_mdd_limit_pp": RELATIVE_MDD_LIMIT_PP,
        "relative_mdd_gate": candidate_gates.get("D"),
        "candidate_ending_equity_krw": candidate_metrics.get("ending_equity_krw"),
        "v2_ending_equity_krw": v2.get("ending_equity_krw"),
        "candidate_cash_shortage_skip_rate_pct": candidate_cash.get("cash_shortage_skip_rate_pct"),
        "v2_cash_shortage_skip_rate_pct": v2.get("cash_shortage_skip_rate_pct"),
        "candidate_turnover_multiple": candidate_metrics.get("turnover_multiple"),
        "v2_turnover_multiple": v2.get("turnover_multiple"),
        "candidate_trade_count": candidate_metrics.get("trade_count"),
        "v2_trade_count": v2.get("trade_count"),
        "candidate_positive_trade_rate_pct": candidate_diagnostics.get("positive_trade_rate_pct"),
        "v2_positive_trade_rate_pct": v2.get("positive_trade_rate_pct"),
        "candidate_median_trade_return_pct": candidate_diagnostics.get("median_net_trade_return_pct"),
        "v2_median_trade_return_pct": v2.get("median_trade_return_pct"),
        "candidate_tail_counts": candidate_diagnostics.get("tail_counts"),
        "v2_tail_counts": {key: v2.get(key) for key in ("+30_count", "+50_count", "+100_count", "-30_count", "-40_count", "-50_count", "-60_count")},
    }


def run_full() -> dict[str, Any]:
    out_root = ROOT / OUTPUT_ROOT
    preflight_path = out_root / "preflight.json"
    if not preflight_path.is_file():
        raise RuntimeError("V02_PREFLIGHT_REQUIRED_BEFORE_FULL_RUN")
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    if preflight.get("status") != "PASS" or not preflight.get("estimated_runtime_within_two_hours"):
        raise RuntimeError("V02_PREFLIGHT_NOT_CLEAR_FOR_FULL_RUN")
    for wid in WINDOW_IDS:
        if (out_root / wid.lower().replace("-", "_")).exists():
            raise RuntimeError(f"V02_WINDOW_OUTPUT_ALREADY_EXISTS_NO_AUTOMATIC_RETRY:{wid}")

    start_head = preflight["starting_head"]
    expected_current_head = __import__("subprocess").check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if start_head != expected_current_head:
        raise RuntimeError(f"START_HEAD_CHANGED_AFTER_PREFLIGHT:{start_head}:{expected_current_head}")
    if __import__("subprocess").check_output(["git", "status", "--short"], cwd=ROOT, text=True).strip():
        raise RuntimeError("WORKTREE_CHANGED_AFTER_PREFLIGHT")

    intervals, trading_dates, market_authority = pattern_b_base._load_authorities(ROOT)
    cap_lookup = v01.ExactMarketCapPriority()
    references = load_v2_references()
    completed: dict[str, Any] = {}
    global_unresolved_rows: list[dict[str, Any]] = []
    input_hashes: dict[str, Any] = {}
    try:
        for window_id in WINDOW_IDS:
            inputs = load_window_inputs(window_id)
            input_hashes[window_id] = inputs["source_hashes"]
            records = [dict(row) for row in inputs["records"]]
            inputs["records"] = records
            tickers = sorted({str(row["ticker"]).zfill(6) for row in records})
            daily_frames, loader_audit, _repository = candidate_runner._load_prices(
                ROOT, tickers, inputs["window"]["effective_start"], inputs["window"]["execution_support"],
            )
            frames = v01.build_component_frames(records, daily_frames, intervals, trading_dates)
            cap_audit = cap_lookup.attach(records)
            price_audit = v01.verify_execution_prices(records, frames, inputs["window"])
            next_session_audit = verify_next_session_execution_dates(records, frames, trading_dates, inputs["window"])
            price_audit.update(
                next_session_execution_audit=next_session_audit,
                next_session_execution_violation_count=next_session_audit["violation_count"],
            )
            if next_session_audit["status"] != "PASS":
                raise RuntimeError(f"NEXT_SESSION_EXECUTION_RULE_FAILURE:{window_id}:{next_session_audit}")
            silent_drops = sum(int(row.get("silent_inner_drop_count", 0) or 0) for row in loader_audit.values())
            if silent_drops:
                raise RuntimeError(f"REPOSITORY_V2_SILENT_INNER_DROP:{window_id}:{silent_drops}")
            replay = run_replay(
                records, frames, trading_dates, inputs["window"],
                f"PATTERN_B_ET_REALISTIC_PORTFOLIO_V02_{window_id.replace('-', '_')}",
            )
            result = write_window_outputs(
                inputs, replay, frames, loader_audit, cap_audit, price_audit,
                references[window_id], trading_dates, frozen_source_hashes_verified(inputs),
            )
            completed[window_id] = result
            global_unresolved_rows.extend(result["unresolved_valuation_rows"])
            print(
                f"Completed {window_id}: return={result['metrics'].get('cumulative_return_pct')}% "
                f"CAGR={result['metrics'].get('CAGR_pct')}% MDD={result['metrics'].get('mdd_pct')}% "
                f"coverage={result['metrics'].get('coverage_pct')}% gates={result['gates']}",
                flush=True,
            )

        global_gates = {
            gate: combine_gate([completed[wid]["gates"][gate] for wid in WINDOW_IDS])
            for gate in GATE_IDS
        }
        if "CHECK_REQUIRED" in global_gates.values():
            verdict = "HOLD"
        elif "FAIL" in global_gates.values():
            verdict = "NOT_ADOPTED"
        else:
            verdict = "OFFICIAL_STRATEGY_ADOPTED"

        summary_rows = []
        portfolio_metrics_rows = []
        cash_rows = []
        coverage_rows = []
        comparison_rows = []
        gate_rows = []
        trade_rows = []
        for wid in WINDOW_IDS:
            result = completed[wid]
            metrics = result["metrics"]
            diag = result["diagnostics"]
            cash = result["cash_diagnostics"]
            valuation = result["valuation"]
            summary_rows.append({
                "window_id": wid,
                "ending_equity_krw": metrics.get("ending_equity_krw"),
                "profit_krw": metrics.get("profit_krw"),
                "total_return_pct": metrics.get("cumulative_return_pct"),
                "CAGR_pct": metrics.get("CAGR_pct"),
                "mdd_pct": metrics.get("mdd_pct"),
                "mdd_type": metrics.get("mdd_type"),
                "coverage_pct": metrics.get("coverage_pct"),
                "cash_shortage_skip_rate_pct": cash.get("cash_shortage_skip_rate_pct"),
                "turnover_krw": metrics.get("turnover_krw"),
                "turnover_multiple": metrics.get("turnover_multiple"),
                "trade_count": metrics.get("trade_count"),
                "closed_trade_count": metrics.get("realized_trade_count"),
                "open_at_cutoff_count": metrics.get("open_at_effective_cutoff_count"),
                "positive_trade_rate_pct": diag.get("positive_trade_rate_pct"),
                "median_trade_return_pct": diag.get("median_net_trade_return_pct"),
                "tail_counts": json.dumps(diag.get("tail_counts", {}), ensure_ascii=False, sort_keys=True),
                **{f"gate_{gate}": result["gates"][gate] for gate in GATE_IDS},
            })
            portfolio_metrics_rows.append({
                "window_id": wid,
                **{k: v for k, v in metrics.items() if not isinstance(v, (dict, list))},
                **{f"gate_{gate}": result["gates"][gate] for gate in GATE_IDS},
            })
            cash_rows.append({"window_id": wid, **cash})
            coverage_rows.append({
                "window_id": wid,
                **{k: v for k, v in valuation.items() if k != "missing_equity_dates"},
                "missing_equity_dates": "|".join(valuation["missing_equity_dates"]),
            })
            comparison_rows.append(compare_to_v2(wid, metrics, diag, cash, result["gates"], result["v2_reference"]))
            trade_path = out_root / wid.lower().replace("-", "_") / "trade_distribution.csv"
            trade_frame = pd.read_csv(trade_path)
            if not trade_frame.empty:
                trade_frame.insert(0, "window_id", wid)
                trade_rows.extend(trade_frame.to_dict(orient="records"))
            for gate, status in result["gates"].items():
                gate_rows.append({"window_id": wid, "gate": gate, "status": status, "evidence": json.dumps(result["gate_evidence"]["reasons"][gate], ensure_ascii=False, sort_keys=True)})
        for gate, status in global_gates.items():
            gate_rows.append({"window_id": "ALL", "gate": gate, "status": status, "evidence": "aggregate of five standard windows"})

        pd.DataFrame(summary_rows).to_csv(out_root / "five_window_summary.csv", index=False, encoding="utf-8")
        pd.DataFrame(portfolio_metrics_rows).to_csv(out_root / "portfolio_metrics.csv", index=False, encoding="utf-8")
        pd.DataFrame(cash_rows).to_csv(out_root / "cash_shortage_diagnostics.csv", index=False, encoding="utf-8")
        pd.DataFrame(coverage_rows).to_csv(out_root / "valuation_coverage.csv", index=False, encoding="utf-8")
        pd.DataFrame(global_unresolved_rows).to_csv(out_root / "unresolved_valuation_summary.csv", index=False, encoding="utf-8")
        pd.DataFrame(comparison_rows).to_csv(out_root / "v2_comparison.csv", index=False, encoding="utf-8")
        pd.DataFrame(gate_rows).to_csv(out_root / "official_adoption_gates.csv", index=False, encoding="utf-8")
        pd.DataFrame(trade_rows).to_csv(out_root / "trade_distribution.csv", index=False, encoding="utf-8")

        report = [
            "# Pattern B E/T PROGRESSED Candidate V02 공식 포트폴리오 심사",
            "",
            f"최종 판정: **{verdict}**",
            "",
            "- 후보 규칙은 V1 동결 조건을 유지했다.",
            "- 각 window의 전체 allowed signal stream을 chronological portfolio state에 공급하고, 현재 보유 상태와 가용 현금으로 신호별 체결 가능성을 새로 결정했다.",
            "- 매수·매도 수수료 0.015%, 양방향 슬리피지 0.1%를 적용했다. 거래세/매도세는 공식 cash path와 모든 공식 지표에서 제외했다.",
            "- 현금 부족은 진단값이며 Gate가 아니다.",
            "",
            "## 5-window 결과",
            "",
            "| Window | Profit KRW | Total Return | CAGR | MDD | Type / coverage | Cash skip (reference) | Turnover | Trades / closed | Positive / median | A | B | C | D | E |",
            "|---|---:|---:|---:|---:|---|---:|---:|---:|---|---|---|---|---|---|",
        ]
        for row in summary_rows:
            def fmt(value: Any, suffix: str = "") -> str:
                return "UNRESOLVED" if value is None or pd.isna(value) else f"{float(value):,.2f}{suffix}"
            report.append(
                f"| {row['window_id']} | {fmt(row['profit_krw'])} | {fmt(row['total_return_pct'], '%')} | {fmt(row['CAGR_pct'], '%')} | "
                f"{fmt(row['mdd_pct'], '%')} | {row['mdd_type']} / {fmt(row['coverage_pct'], '%')} | "
                f"{fmt(row['cash_shortage_skip_rate_pct'], '%')} | {fmt(row['turnover_multiple'], 'x')} | "
                f"{fmt(row['trade_count'], ' / ' + fmt(row['closed_trade_count']))} | "
                f"{fmt(row['positive_trade_rate_pct'], '%')} / {fmt(row['median_trade_return_pct'], '%')} | "
                + " | ".join(row[f"gate_{gate}"] for gate in GATE_IDS)
                + " |"
            )
        report += ["", "## Gate 판정", "", *(f"- Gate {gate}: `{status}`" for gate, status in global_gates.items()), "", "## V2 comparison", "", "| Window | Candidate MDD | V2 MDD | Deterioration pp | Relative D | Candidate Return | V2 Return | Candidate CAGR | V2 CAGR |", "|---|---:|---:|---:|---|---:|---:|---:|---:|"]
        for row in comparison_rows:
            report.append(
                f"| {row['window_id']} | {fmt(row['candidate_mdd_pct'], '%')} ({row['candidate_mdd_type']}) | {fmt(row['v2_mdd_pct'], '%')} ({row['v2_mdd_type']}) | "
                f"{fmt(row['mdd_deterioration_pp'])} | {row['relative_mdd_gate']} | {fmt(row['candidate_total_return_pct'], '%')} | {fmt(row['v2_total_return_pct'], '%')} | "
                f"{fmt(row['candidate_cagr_pct'], '%')} | {fmt(row['v2_cagr_pct'], '%')} |"
            )
        unresolved_total = sum(int(row.get("unresolved_valuation_marks", 0) or 0) for row in global_unresolved_rows)
        report += [
            "",
            "## 데이터 gap / 제한",
            "",
            f"미해결 valuation identity 그룹: {len(global_unresolved_rows)}; 미해결 mark 합계: {unresolved_total}.",
            "Identity별 window·mark/date·coverage 영향은 `unresolved_valuation_summary.csv`에 있다. 추가 영구 제외는 적용하지 않았다.",
            "",
            "## 기존 결과와 범위",
            "",
            "V01 산출물과 당시 HOLD 판정은 역사 기록으로 그대로 보존했다. 이번 V02는 최신 A~E 기준에 따른 독립 portfolio-aware replay다.",
            "A FAST Core V2의 기본 전략 지위는 이번 판정으로 바뀌지 않는다.",
            "",
            "## 산출물",
            "",
            "`summary.json`, `execution_contract.json`, `metadata.json`, `source_hashes.json`, `five_window_summary.csv`, `official_adoption_gates.csv`, `v2_comparison.csv`, `portfolio_metrics.csv`, `trade_distribution.csv`, `cash_shortage_diagnostics.csv`, `valuation_coverage.csv`, `unresolved_valuation_summary.csv`, window별 daily equity 및 portfolio event/audit 파일.",
        ]
        (out_root / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")

        official_gates = {
            "gates": global_gates,
            "window_gate_statuses": {wid: completed[wid]["gates"] for wid in WINDOW_IDS},
            "cash_shortage_is_gate": False,
            "gate_count": 5,
            "verdict": verdict,
        }
        json_write(out_root / "official_adoption_gates.json", official_gates)
        summary = {
            "schema": "pattern_b_progressed_previous_et_only_official_portfolio_summary_v02",
            "strategy_id": STRATEGY_ID,
            "display_name": DISPLAY_NAME,
            "verdict": verdict,
            "gates": global_gates,
            "window_metrics": {wid: completed[wid]["metrics"] for wid in WINDOW_IDS},
            "v2_comparison": comparison_rows,
            "permanent_exclusion_count": len(current_exclusion_keys()),
            "workers": WORKERS,
            "failed_attempts": [],
        }
        json_write(out_root / "summary.json", summary)
        source_hash_map = {
            str(STAGE_HISTORY_PATH): sha256(ROOT / STAGE_HISTORY_PATH),
            str(STAGE_LINKAGE_PATH): sha256(ROOT / STAGE_LINKAGE_PATH),
            str(EXCLUSION_POLICY_PATH): sha256(ROOT / EXCLUSION_POLICY_PATH),
            str(OFFICIAL_CRITERIA_PATH): sha256(ROOT / OFFICIAL_CRITERIA_PATH),
            str(COMMON_RULES_PATH): sha256(ROOT / COMMON_RULES_PATH),
            "V2 reference summary.json": sha256(ROOT / V2_REFERENCE_ROOT / "summary.json"),
            **{wid: input_hashes[wid] for wid in WINDOW_IDS},
        }
        json_write(out_root / "source_hashes.json", source_hash_map)
        metadata = {
            "run_id": summary["schema"],
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "starting_head": start_head,
            "ending_head": __import__("subprocess").check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "starting_origin_main": preflight.get("starting_origin_main"),
            "official_criteria_sha256": preflight["official_criteria_sha256"],
            "common_rules_sha256": preflight["common_rules_sha256"],
            "permanent_exclusion_policy": {
                "path": str(EXCLUSION_POLICY_PATH),
                "sha256": sha256(ROOT / EXCLUSION_POLICY_PATH),
                "version": preflight["permanent_exclusion_policy_version"],
                "identity_count": len(PERMANENT_IDENTITY_EXCLUSIONS),
            },
            "work_instruction_path": str(WORK_INSTRUCTION_PATH),
            "work_instruction_sha256": sha256(WORK_INSTRUCTION_PATH) if WORK_INSTRUCTION_PATH.is_file() else None,
            "script_path": str(Path(__file__).relative_to(ROOT)),
            "script_sha256": sha256(Path(__file__)),
            "portfolio_engine_path": "scripts/run_p2_1_realistic_portfolio_v01.py",
            "portfolio_engine_sha256": sha256(ROOT / "scripts/run_p2_1_realistic_portfolio_v01.py"),
            "workers": WORKERS,
            "window_ids": list(WINDOW_IDS),
            "source_hashes": source_hash_map,
            "window_gate_statuses": {wid: completed[wid]["gates"] for wid in WINDOW_IDS},
            "verdict": verdict,
            "generated_files": {},
        }
        for path in sorted(out_root.rglob("*")):
            if path.is_file() and path.name != "metadata.json":
                metadata["generated_files"][str(path.relative_to(out_root))] = {
                    "sha256": sha256(path),
                    "bytes": path.stat().st_size,
                }
        json_write(out_root / "metadata.json", metadata)
        json_write(out_root / "run_status.json", {
            "status": "COMPLETE",
            "verdict": verdict,
            "completed_windows": list(WINDOW_IDS),
            "failed_attempts": [],
        })
        return {"verdict": verdict, "gates": global_gates, "windows": completed}
    except Exception as exc:
        json_write(out_root / "run_status.json", {
            "status": "ABORTED",
            "reason": f"{type(exc).__name__}: {exc}",
            "completed_windows": list(completed),
            "automatic_retry": False,
            "run_is_superseded": True,
        })
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.preflight == args.run:
        parser.error("choose exactly one of --preflight or --run")
    result = run_preflight() if args.preflight else run_full()
    print(json.dumps(json_clean(result), ensure_ascii=False, indent=2, default=str), flush=True)


if __name__ == "__main__":
    main()
