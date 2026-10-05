#!/usr/bin/env python3
"""Rebuild five-window B Select CONTROL/TEST portfolios under exact global exclusions."""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import math
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from scripts import analyze_b_select_daily_exit_mdd_coverage_remediation_v01 as coverage_audit  # noqa: E402
from scripts import replay_b_select_daily_normal_exit_cadence_v01 as cadence  # noqa: E402
from scripts import run_pattern_b_progressed_previous_et_only_realistic_portfolio_v01 as portfolio_v01  # noqa: E402
from scripts import run_pattern_b_progressed_previous_et_only_realistic_portfolio_v02 as portfolio_v02  # noqa: E402
from scripts import run_pattern_b_pure_simple_backtest_v01 as pattern_b_base  # noqa: E402
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore  # noqa: E402
from trend_scanner.universe.permanent_identity_exclusions import PERMANENT_IDENTITY_EXCLUSIONS  # noqa: E402


STUDY_ID = "B_SELECT_DAILY_NORMAL_EXIT_PERMANENT_EXCLUSION_V01"
BASE_HEAD = "c69f1e09cde89d364e1a1df837065c67a6e4da50"
OUTPUT_ROOT = Path(
    "artifacts/strategies/b_select_core_v1/research/"
    "daily_normal_exit_permanent_exclusion_v01"
)
POLICY_PATH = Path("src/trend_scanner/universe/permanent_identity_exclusions.py")
PREVIOUS_BASIS_PATH = Path(
    "artifacts/strategies/b_select_core_v1/research/"
    "daily_exit_mdd_coverage_remediation_v01/identity_corporate_action_audit.csv"
)
LEGACY_CADENCE_COMPARISON_PATH = Path(
    "artifacts/strategies/b_select_core_v1/research/"
    "daily_normal_exit_cadence_v01/trade_comparison.csv"
)
WINDOW_IDS = ("P1", "P2-1", "P2-2", "P3-1", "P3-2")
SCENARIOS = ("CONTROL_MONTH_END", "TEST_DAILY")
WORKERS = 10
INITIAL_CAPITAL = 200_000_000.0
POSITION_BUDGET = 5_000_000.0
COMMISSION_RATE = 0.00015
SLIPPAGE_RATE = 0.001
ZERO_TAX_SCHEDULE = (("1900-01-01", "2100-12-31", 0.0),)
MIN_OBSERVED_COVERAGE = 90.0
RELATIVE_MDD_LIMIT_PP = 5.0
ABSOLUTE_MDD_LIMITS = {
    "P1": -55.0,
    "P2-1": -40.0,
    "P2-2": -40.0,
    "P3-1": -40.0,
    "P3-2": -40.0,
}
NEW_IDENTITIES = {
    ("007720", "KR7007720006"),
    ("011080", "KR7011080009"),
    ("019490", "KR7019490002"),
    ("019570", "KR7019570001"),
    ("066790", "KR7066790007"),
    ("073570", "KR7073570004"),
    ("083660", "KR7083660001"),
}
ALLOWED_START_STATUS = {
    " M src/trend_scanner/universe/permanent_identity_exclusions.py",
    "?? scripts/replay_b_select_daily_normal_exit_permanent_exclusion_v01.py",
    "?? tests/test_b_select_daily_normal_exit_permanent_exclusion_v01.py",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _identity(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row.get("ticker", "")).strip().zfill(6), str(row.get("isu_cd", "")).strip().upper()


def _as_bool(value: Any) -> bool:
    if value is None or pd.isna(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def _date_signature(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value)[:10]


def _source_parity_signature(row: Mapping[str, Any]) -> tuple[str, ...]:
    ticker, isu_cd = _identity(row)
    return (
        ticker,
        isu_cd,
        _date_signature(row.get("entry_signal_date")),
        _date_signature(row.get("source_control_exit_signal_date")),
        _date_signature(row.get("control_exit_signal_date")),
        _date_signature(row.get("source_control_exit_execution_date")),
        _date_signature(row.get("control_exit_execution_date")),
    )


def _legacy_source_parity_baseline() -> tuple[dict[str, set[tuple[str, ...]]], str]:
    path = ROOT / LEGACY_CADENCE_COMPARISON_PATH
    if not path.is_file():
        raise RuntimeError("LEGACY_CADENCE_SOURCE_PARITY_AUDIT_MISSING")
    frame = pd.read_csv(path, dtype={"ticker": str, "isu_cd": str})
    required = {
        "window_id", "ticker", "isu_cd", "entry_signal_date",
        "source_control_exit_signal_date", "control_exit_signal_date",
        "source_control_exit_execution_date", "control_exit_execution_date",
        "control_source_signal_match", "control_source_execution_match",
    }
    if not required <= set(frame.columns):
        raise RuntimeError("LEGACY_CADENCE_SOURCE_PARITY_AUDIT_SCHEMA_MISMATCH")
    result: dict[str, set[tuple[str, ...]]] = {window_id: set() for window_id in WINDOW_IDS}
    for row in frame.to_dict(orient="records"):
        window_id = str(row["window_id"])
        if window_id not in result:
            continue
        if _identity(row) in NEW_IDENTITIES:
            continue
        if not _as_bool(row.get("control_source_signal_match")) or not _as_bool(row.get("control_source_execution_match")):
            result[window_id].add(_source_parity_signature(row))
    return result, sha256(path)


def _current_source_parity_mismatches(comparisons: Sequence[Mapping[str, Any]]) -> set[tuple[str, ...]]:
    return {
        _source_parity_signature(row)
        for row in comparisons
        if not _as_bool(row.get("control_source_signal_match"))
        or not _as_bool(row.get("control_source_execution_match"))
    }


def _git_output(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def verify_start_state() -> dict[str, Any]:
    head = _git_output("rev-parse", "HEAD")
    origin = _git_output("rev-parse", "origin/main")
    branch = _git_output("branch", "--show-current")
    status_output = subprocess.check_output(
        ["git", "status", "--short", "--untracked-files=all"], cwd=ROOT, text=True,
    )
    status_lines = set(status_output.rstrip("\n").splitlines())
    if head != BASE_HEAD or origin != BASE_HEAD or branch != "main":
        raise RuntimeError(f"START_REVISION_OR_BRANCH_MISMATCH:{branch}:{head}:{origin}")
    if status_lines != ALLOWED_START_STATUS:
        raise RuntimeError(f"UNRELATED_WORKTREE_CHANGES_AT_START:{sorted(status_lines)}")
    return {"branch": branch, "head": head, "origin_main": origin, "status": sorted(status_lines)}


def _policy_literal(source: str) -> tuple[list[tuple[str, str]], dict[tuple[str, str], Any]]:
    tree = ast.parse(source)
    node = next(
        item for item in tree.body
        if isinstance(item, ast.AnnAssign)
        and isinstance(item.target, ast.Name)
        and item.target.id == "PERMANENT_IDENTITY_EXCLUSIONS"
    )
    literal = ast.literal_eval(node.value)
    literal_keys = [ast.literal_eval(key) for key in node.value.keys]
    return literal_keys, literal


def verify_exclusion_authority() -> dict[str, Any]:
    baseline_source = subprocess.check_output(
        ["git", "show", f"{BASE_HEAD}:{POLICY_PATH.as_posix()}"], cwd=ROOT, text=True,
    )
    base_literal_keys, base_policy = _policy_literal(baseline_source)
    current_source = (ROOT / POLICY_PATH).read_text(encoding="utf-8")
    current_literal_keys, current_policy = _policy_literal(current_source)
    base_keys = set(base_literal_keys)
    current_keys = set(current_literal_keys)
    if len(base_keys) != 174 or len(base_literal_keys) != len(base_keys):
        raise RuntimeError("BASE_EXCLUSION_AUTHORITY_NOT_EXACTLY_174")
    if base_keys.intersection(NEW_IDENTITIES):
        raise RuntimeError("NEW_EXCLUSION_ALREADY_PRESENT_AT_BASE")
    if len(current_keys) != len(current_literal_keys) or current_keys != base_keys | NEW_IDENTITIES:
        raise RuntimeError("CURRENT_EXCLUSION_POLICY_NOT_EXACT_BASE_PLUS_SEVEN")
    if len(current_keys) != 181 or set(PERMANENT_IDENTITY_EXCLUSIONS) != current_keys:
        raise RuntimeError("PERMANENT_EXCLUSION_COUNT_OR_IMPORT_MISMATCH")
    bad_metadata = [
        key for key in sorted(NEW_IDENTITIES)
        if current_policy[key].get("approval_scope") != "GLOBAL permanent identity exclusion"
        or current_policy[key].get("approved_date") != "2026-10-05"
        or current_policy[key].get("policy_version") != "permanent_identity_exclusions_v01"
        or "data-quality basis, not performance" not in current_policy[key].get("reason", "")
    ]
    if bad_metadata:
        raise RuntimeError(f"NEW_EXCLUSION_METADATA_INVALID:{bad_metadata}")

    basis_path = ROOT / PREVIOUS_BASIS_PATH
    if not basis_path.is_file():
        raise RuntimeError("PREVIOUS_IDENTITY_BASIS_AUDIT_MISSING")
    basis_frame = pd.read_csv(basis_path, dtype={"ticker": str, "isu_cd": str})
    basis_by_key = {
        (str(row.ticker).zfill(6), str(row.isu_cd).upper()): str(row.classification)
        for row in basis_frame.itertuples(index=False)
    }
    if len(basis_by_key) != 24 or not NEW_IDENTITIES <= set(basis_by_key):
        raise RuntimeError("PREVIOUS_IDENTITY_BASIS_AUDIT_ROSTER_MISMATCH")
    if any(basis_by_key[key] != "C" for key in NEW_IDENTITIES):
        raise RuntimeError("NEW_EXCLUSIONS_NOT_ALL_UNRESOLVED_CLASS_C_IDENTITIES")
    approved_carry_identities = {key for key, value in basis_by_key.items() if value in {"A", "B"}}
    if len(approved_carry_identities) != 17 or approved_carry_identities.intersection(NEW_IDENTITIES):
        raise RuntimeError("VALUATION_CARRY_BASIS_SET_MISMATCH")
    return {
        "base_count": len(base_keys),
        "new_count": len(NEW_IDENTITIES),
        "current_count": len(current_keys),
        "duplicate_exact_keys": 0,
        "ticker_only_exclusion_count": 0,
        "new_identities": sorted(NEW_IDENTITIES),
        "approved_carry_identities": sorted(approved_carry_identities),
        "identity_basis_audit_sha256": sha256(basis_path),
    }


def _load_window_inputs() -> dict[str, dict[str, Any]]:
    if cadence.WORKERS != WORKERS or portfolio_v02.WORKERS != WORKERS or portfolio_v01.WORKERS != WORKERS:
        raise RuntimeError("WORKER_COUNT_MISMATCH_NOT_10")
    return {window_id: portfolio_v02.load_window_inputs(window_id) for window_id in WINDOW_IDS}


def _candidate_exclusion_audit(
    inputs_by_window: Mapping[str, Mapping[str, Any]],
    trading_dates: Sequence[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    permanent_keys = portfolio_v02.current_exclusion_keys()
    if len(permanent_keys) != 181 or len(permanent_keys) != len(PERMANENT_IDENTITY_EXCLUSIONS):
        raise RuntimeError("PERMANENT_EXCLUSION_NORMALIZATION_COLLISION_OR_COUNT_MISMATCH")
    impact_rows: list[dict[str, Any]] = []
    window_rows: list[dict[str, Any]] = []
    for window_id in WINDOW_IDS:
        inputs = inputs_by_window[window_id]
        if int(inputs.get("current_permanent_exclusion_count", -1)) != 181:
            raise RuntimeError(f"WINDOW_EXCLUSION_COUNT_MISMATCH:{window_id}")
        records = list(inputs["records"])
        signals = list(inputs["pass_rows"])
        leakage = sum(_identity(row) in permanent_keys for row in records + signals)
        target_leakage = sum(_identity(row) in NEW_IDENTITIES for row in records + signals)
        if leakage or target_leakage:
            raise RuntimeError(f"EXCLUSION_LEAKAGE:{window_id}:{leakage}:{target_leakage}")
        start = str(inputs["window"]["effective_start"])[:10]
        end = str(inputs["window"]["effective_end"])[:10]
        month_ends = set(cadence._month_end_sessions(trading_dates, start, end))
        non_monthly_entries = sum(str(row.get("entry_signal_date", ""))[:10] not in month_ends for row in records)
        if non_monthly_entries:
            raise RuntimeError(f"NON_MONTH_END_SOURCE_ENTRIES:{window_id}:{non_monthly_entries}")

        source_dir = portfolio_v02.window_directory(window_id)
        audit = pd.read_csv(source_dir / "previous_stage_audit.csv", dtype={"ticker": str, "isu_cd": str})
        ledger = pd.read_csv(source_dir / "test_trade_ledger.csv", dtype={"ticker": str, "isu_cd": str})
        allowed = audit.loc[audit["new_test_gate_decision"].astype(str).eq(portfolio_v02.ALLOWED_SIGNAL_DECISION)]
        allowed_records = allowed.to_dict(orient="records")
        ledger_records = ledger.to_dict(orient="records")
        removed_signal_count = sum(_identity(row) in NEW_IDENTITIES for row in allowed_records)
        removed_fill_count = sum(_identity(row) in NEW_IDENTITIES for row in ledger_records)
        for ticker, isu_cd in sorted(NEW_IDENTITIES):
            signal_count = sum(
                _identity(row) == (ticker, isu_cd)
                for row in allowed_records
            )
            fill_count = sum(
                _identity(row) == (ticker, isu_cd)
                for row in ledger_records
            )
            impact_rows.append({
                "window": window_id,
                "ticker": ticker,
                "isu_cd": isu_cd,
                "source_eligible_signals_removed": signal_count,
                "source_filled_candidate_rows_removed": fill_count,
                "post_exclusion_signal_leakage": 0,
                "post_exclusion_filled_row_leakage": 0,
            })
        window_rows.append({
            "window": window_id,
            "permanent_exclusion_count": len(permanent_keys),
            "source_filled_candidate_rows": len(ledger),
            "source_eligible_signals": len(allowed),
            "rows_removed_by_current_exclusions": int(inputs["current_exclusion_count"]),
            "signals_removed_by_current_exclusions": int(inputs["current_excluded_candidate_count"]),
            "new_seven_source_eligible_signals_removed": removed_signal_count,
            "new_seven_source_filled_candidate_rows_removed": removed_fill_count,
            "post_exclusion_permanent_identity_leakage": 0,
            "post_exclusion_new_seven_identity_leakage": 0,
            "monthly_entry_signal_violation_count": 0,
            "authoritative_signal_linkage_status": inputs["authoritative_signal_linkage_check"]["status"],
        })
    return impact_rows, window_rows


def _interval_map(intervals: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], list[Mapping[str, Any]]]:
    result: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in intervals:
        result[(str(row.get("ticker", "")).zfill(6), str(row.get("isu_cd", "")).upper())].append(row)
    return result


def _raw_row_cache(raw_store: KrxRawStockStore) -> tuple[dict[tuple[str, str], dict[str, dict[str, Any]]], dict[tuple[str, str], dict[str, Any]]]:
    rows_by_partition: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    manifests: dict[tuple[str, str], dict[str, Any]] = {}

    def get(market: str, day: str, ticker: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        key = (market.upper(), day[:10])
        if key not in rows_by_partition:
            manifest = raw_store.get_manifest(*key)
            if manifest is None or manifest.get("status") != "COMPLETE":
                rows_by_partition[key] = {}
                manifests[key] = {"status": "MISSING_OR_INCOMPLETE" if manifest is None else manifest.get("status")}
                return None, manifests[key]
            frame = raw_store.load_snapshot(*key)
            rows = frame.loc[:, ["ticker", "date", "open", "high", "low", "close", "volume", "trading_value", "listed_shares"]]
            rows_by_partition[key] = {
                str(row["ticker"]).zfill(6): row
                for row in rows.to_dict(orient="records")
                if str(row["ticker"]).zfill(6) == ticker.zfill(6)
            }
            manifests[key] = dict(manifest)
        return rows_by_partition[key].get(ticker.zfill(6)), manifests[key]

    return rows_by_partition, manifests


def _replay_with_official_carry(
    records: Sequence[Mapping[str, Any]],
    frames: Mapping[Any, pd.DataFrame | None],
    trading_dates: Sequence[str],
    window: Mapping[str, Any],
    strategy_id: str,
    approved_basis: set[tuple[str, str]],
    intervals_by_identity: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]],
    raw_store: KrxRawStockStore,
    raw_cache: dict[tuple[str, str], dict[str, dict[str, Any]]],
    raw_manifests: dict[tuple[str, str], dict[str, Any]],
    carry_audit: list[dict[str, Any]],
) -> dict[str, Any]:
    engine = portfolio_v02.portfolio
    original = {
        "tax": engine.SELL_TAX_SCHEDULE,
        "capital": engine.INITIAL_CAPITAL,
        "budget": engine.POSITION_BUDGET,
        "valuation": engine._valuation_close_with_carry,
    }

    def official_valuation_close(
        record: Mapping[str, Any],
        component_frames: Mapping[Any, pd.DataFrame],
        day: pd.Timestamp,
        _session_positions: Mapping[pd.Timestamp, int],
        _gap_classifications: Mapping[tuple[str, str], str],
        *,
        strategy_id: str,
        pair_id: str,
    ) -> tuple[float | None, dict[str, Any] | None]:
        valuation_day = pd.Timestamp(day).normalize()
        exact = engine._price(record, component_frames, valuation_day, "close")
        if exact is not None and float(exact) > 0:
            return float(exact), None

        ticker, isu_cd = _identity(record)
        market = str(record.get("market", "")).upper()
        day_text = valuation_day.strftime("%Y-%m-%d")
        audit: dict[str, Any] = {
            "strategy_id": strategy_id,
            "pair_id": pair_id,
            "ticker": ticker,
            "isu_cd": isu_cd,
            "market": market,
            "valuation_date": day_text,
            "used_for_execution": False,
            "used_for_strategy_or_features": False,
            "valuation_only": True,
        }
        reason = "UNRESOLVED_SIMPLE_PRICE_GAP"
        if (ticker, isu_cd) in NEW_IDENTITIES:
            reason = "PERMANENTLY_EXCLUDED_IDENTITY_LEAK"
        elif (ticker, isu_cd) not in approved_basis:
            reason = "IDENTITY_BASIS_NOT_AUDITED_A_OR_B"
        elif not coverage_audit._pit_active(intervals_by_identity, ticker, isu_cd, day_text):
            reason = "PIT_COMMON_IDENTITY_NOT_ACTIVE_ON_MARK_DATE"
        else:
            raw_row, manifest = raw_store_reader(market, day_text, ticker)
            if raw_row is None or not coverage_audit.raw_nontrading_placeholder(raw_row):
                reason = "EXACT_KRX_RAW_NONTRADING_PLACEHOLDER_NOT_CONFIRMED"
            else:
                frame = engine._frame_for_record(record, component_frames)
                if frame is None or "close" not in frame.columns:
                    reason = "REPOSITORY_V2_IDENTITY_FRAME_MISSING"
                else:
                    earlier = frame.loc[frame.index < valuation_day].sort_index(ascending=False)
                    ref_day: pd.Timestamp | None = None
                    ref_close: float | None = None
                    for candidate_day, candidate_row in earlier.iterrows():
                        adjusted_values = candidate_row.to_dict()
                        close = coverage_audit.number(adjusted_values.get("close"))
                        if close is None or close <= 0 or not coverage_audit.valid_adjusted_ohlc(adjusted_values):
                            continue
                        candidate_text = pd.Timestamp(candidate_day).strftime("%Y-%m-%d")
                        if not coverage_audit._pit_active(intervals_by_identity, ticker, isu_cd, candidate_text):
                            continue
                        raw_ref, raw_ref_manifest = raw_store_reader(market, candidate_text, ticker)
                        shares = coverage_audit.number(raw_ref.get("listed_shares")) if raw_ref else None
                        if (
                            not coverage_audit._raw_valid_trade(raw_ref)
                            or shares is None or shares <= 0
                        ):
                            continue
                        ref_day, ref_close = pd.Timestamp(candidate_day).normalize(), close
                        ref_manifest = raw_ref_manifest
                        break
                    if ref_day is None or ref_close is None:
                        reason = "NO_PRIOR_VALID_EXACT_IDENTITY_ADJUSTED_ANCHOR"
                    else:
                        reason = "A_OR_B_IDENTITY_WITH_HASHED_RAW_PLACEHOLDER_AND_PRIOR_ADJUSTED_ANCHOR"
                        audit.update({
                            "carry_reference_date": ref_day.strftime("%Y-%m-%d"),
                            "carry_reference_adjusted_close": ref_close,
                            "raw_mark_partition_sha256": manifest.get("file_sha256"),
                            "raw_mark_partition_content_sha256": manifest.get("content_sha256"),
                            "raw_anchor_partition_sha256": ref_manifest.get("file_sha256"),
                            "raw_anchor_partition_content_sha256": ref_manifest.get("content_sha256"),
                            "raw_placeholder_open": raw_row.get("open"),
                            "raw_placeholder_high": raw_row.get("high"),
                            "raw_placeholder_low": raw_row.get("low"),
                            "raw_placeholder_close": raw_row.get("close"),
                            "raw_placeholder_volume": raw_row.get("volume"),
                            "raw_placeholder_trading_value": raw_row.get("trading_value"),
                            "raw_placeholder_listed_shares": raw_row.get("listed_shares"),
                        })
                        audit.update(status="CARRY_AUTHORIZED", carry_reason=reason)
                        carry_audit.append(audit)
                        return ref_close, {
                            **audit,
                            "last_valid_adjusted_close_date": ref_day.strftime("%Y-%m-%d"),
                            "carried_adjusted_close": ref_close,
                            "stale_age_trading_days": None,
                            "stale_age_calendar_days": int((valuation_day - ref_day).days),
                            "gap_classification": "VERIFIED_KRX_ZERO_ACTIVITY_PLACEHOLDER_AND_A_B_ADJUSTED_UNIT_BASIS",
                        }
        audit.update(status="UNRESOLVED", carry_reason=reason)
        carry_audit.append(audit)
        return None, None

    def raw_store_reader(market: str, day: str, ticker: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        key = (market.upper(), day[:10])
        if key not in raw_cache:
            manifest = raw_store.get_manifest(*key)
            if manifest is None or manifest.get("status") != "COMPLETE":
                raw_cache[key] = {}
                raw_manifests[key] = {"status": "MISSING_OR_INCOMPLETE" if manifest is None else manifest.get("status")}
            else:
                frame = raw_store.load_snapshot(*key)
                tickers = frame["ticker"].astype(str).str.zfill(6)
                selected = frame.loc[tickers.eq(ticker.zfill(6))]
                raw_cache[key] = {
                    str(row["ticker"]).zfill(6): row
                    for row in selected.to_dict(orient="records")
                }
                raw_manifests[key] = dict(manifest)
        return raw_cache[key].get(ticker.zfill(6)), raw_manifests[key]

    engine.SELL_TAX_SCHEDULE = ZERO_TAX_SCHEDULE
    engine.INITIAL_CAPITAL = INITIAL_CAPITAL
    engine.POSITION_BUDGET = POSITION_BUDGET
    engine._valuation_close_with_carry = official_valuation_close
    try:
        audit = portfolio_v02.verify_next_session_execution_dates(records, frames, trading_dates, window)
        if audit["violation_count"]:
            raise RuntimeError(f"NEXT_SESSION_EXECUTION_AUDIT_FAILED:{strategy_id}:{audit}")
        return engine._portfolio_replay(
            records,
            frames,
            [pd.Timestamp(day).normalize() for day in trading_dates],
            strategy_id=strategy_id,
            effective_start=pd.Timestamp(window["effective_start"]).normalize(),
            effective_end=pd.Timestamp(window["effective_end"]).normalize(),
            execution_support=pd.Timestamp(window["execution_support"]).normalize(),
        )
    finally:
        engine.SELL_TAX_SCHEDULE = original["tax"]
        engine.INITIAL_CAPITAL = original["capital"]
        engine.POSITION_BUDGET = original["budget"]
        engine._valuation_close_with_carry = original["valuation"]


def _event_identity(event: Mapping[str, Any], records_by_pair: Mapping[str, Mapping[str, Any]]) -> tuple[str, str]:
    pair_id = str(event.get("pair_id", ""))
    record = records_by_pair.get(pair_id, {})
    return (
        str(event.get("ticker", record.get("ticker", ""))).zfill(6),
                str(event.get("isu_cd") or record.get("isu_cd", "")).upper(),
    )


def _executed_event_counts(events: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {
        "executed_entry_count": sum(
            row.get("event_type") == "ENTRY" and row.get("event_status") == "EXECUTED"
            for row in events
        ),
        "executed_exit_count": sum(
            row.get("event_type") == "EXIT" and row.get("event_status") == "EXECUTED"
            for row in events
        ),
    }


def _realized_trade_metrics(
    diagnostics: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    executed_counts = _executed_event_counts(events)
    realized = list(diagnostics["realized_trades"])
    returns = [float(row["net_return_pct"]) for row in realized if row.get("net_return_pct") is not None]
    array = np.asarray(returns, dtype=float)
    thresholds = {
        "le_neg_15": lambda values: values <= -15.0,
        "le_neg_30": lambda values: values <= -30.0,
        "ge_pos_30": lambda values: values >= 30.0,
        "ge_pos_50": lambda values: values >= 50.0,
        "ge_pos_100": lambda values: values >= 100.0,
    }
    tails = {
        label: {"count": int(predicate(array).sum()), "rate_pct": float(predicate(array).mean() * 100.0) if len(array) else None}
        for label, predicate in thresholds.items()
    }
    return {
        **executed_counts,
        "realized_trade_count": len(realized),
        "open_at_effective_cutoff_count": int(diagnostics.get("open_at_cutoff_count", 0) or 0),
        "open_at_effective_cutoff_exact_mark_count": int(diagnostics.get("open_at_cutoff_exact_mark_count", 0) or 0),
        "open_at_effective_cutoff_unresolved_count": int(diagnostics.get("open_at_cutoff_unresolved_count", 0) or 0),
        "win_rate_pct": float((array > 0).mean() * 100.0) if len(array) else None,
        "mean_realized_net_return_pct": float(array.mean()) if len(array) else None,
        "median_realized_net_return_pct": float(np.median(array)) if len(array) else None,
        "mean_holding_krx_sessions": diagnostics.get("mean_holding_krx_sessions"),
        "median_holding_krx_sessions": diagnostics.get("median_holding_krx_sessions"),
        "tail_counts_net_return": tails,
    }


def _candidate_gates(
    window_id: str,
    control: Mapping[str, Any],
    test: Mapping[str, Any],
    integrity_pass: bool,
) -> tuple[dict[str, str], dict[str, Any]]:
    control_metrics = control["metrics"]
    test_metrics = test["metrics"]
    control_valuation = control["valuation"]
    test_valuation = test["valuation"]
    a = "PASS" if integrity_pass else "FAIL"
    b = "PASS" if all(
        case["cost_audit"]["coverage_complete"] and case["cost_audit"]["mismatch_count"] == 0
        for case in (control, test)
    ) else "FAIL"
    returns = (test_metrics.get("cumulative_return_pct"), test_metrics.get("CAGR_pct"))
    c = "CHECK_REQUIRED" if any(value is None for value in returns) else (
        "PASS" if all(float(value) > 0 for value in returns) else "FAIL"
    )
    control_coverage = float(control_valuation.get("coverage_pct") or 0.0)
    test_coverage = float(test_valuation.get("coverage_pct") or 0.0)
    control_mdd = control_valuation.get("mdd_pct")
    test_mdd = test_valuation.get("mdd_pct")
    relative = float(control_mdd) - float(test_mdd) if control_mdd is not None and test_mdd is not None else None
    if min(control_coverage, test_coverage) < MIN_OBSERVED_COVERAGE or relative is None:
        d = "CHECK_REQUIRED"
    else:
        absolute_pass = float(test_mdd) >= ABSOLUTE_MDD_LIMITS[window_id]
        relative_pass = relative < RELATIVE_MDD_LIMIT_PP
        d = "PASS" if absolute_pass and relative_pass else "FAIL"
    terminal_close = test_metrics.get("final_equity_at_effective_close")
    terminal_support = test_metrics.get("final_equity")
    unresolved_exec = int(test["unresolved_execution_event_count"])
    terminal_unresolved = int(test["diagnostics"].get("open_at_cutoff_unresolved_count", 0) or 0)
    e_ok = (
        test_coverage >= MIN_OBSERVED_COVERAGE
        and terminal_close is not None and not pd.isna(terminal_close)
        and terminal_support is not None and math.isfinite(float(terminal_support))
        and unresolved_exec == 0 and terminal_unresolved == 0
        and returns[0] is not None and returns[1] is not None
    )
    e = "PASS" if e_ok else "CHECK_REQUIRED"
    return {"A": a, "B": b, "C": c, "D": d, "E": e}, {
        "relative_control_minus_test_mdd_pp": relative,
        "relative_limit_pp": RELATIVE_MDD_LIMIT_PP,
        "relative_gate": "CHECK_REQUIRED" if relative is None or min(control_coverage, test_coverage) < MIN_OBSERVED_COVERAGE else ("FAIL" if relative >= RELATIVE_MDD_LIMIT_PP else "PASS"),
        "test_absolute_mdd_floor_pct": ABSOLUTE_MDD_LIMITS[window_id],
        "control_coverage_pct": control_coverage,
        "test_coverage_pct": test_coverage,
        "control_official_mdd_type": "EXACT MDD" if control_coverage >= 100.0 else "OBSERVED MDD" if control_coverage >= 90.0 else "NO OFFICIAL MDD: coverage below 90%",
        "test_official_mdd_type": "EXACT MDD" if test_coverage >= 100.0 else "OBSERVED MDD" if test_coverage >= 90.0 else "NO OFFICIAL MDD: coverage below 90%",
    }


def preflight() -> dict[str, Any]:
    start = verify_start_state()
    policy = verify_exclusion_authority()
    inputs_by_window = _load_window_inputs()
    _intervals, trading_dates, _authority = pattern_b_base._load_authorities(ROOT)
    impact_rows, window_rows = _candidate_exclusion_audit(inputs_by_window, trading_dates)
    return {
        "status": "PASS",
        "starting_state": start,
        "exclusion_authority": policy,
        "workers": WORKERS,
        "window_input_audit": window_rows,
        "new_identity_candidate_impact": impact_rows,
        "official_nontrading_carry_basis": "Only A/B identities from the prior exact corporate-action audit; each mark must also pass complete KRX zero-activity raw-row checks, same exact PIT COMMON identity, and a strictly prior valid Repository V2 adjusted-close/raw-trade anchor. The seven C identities are excluded before replay and never carried.",
    }


def _report(summary: Mapping[str, Any]) -> str:
    lines = [
        "# B Select 7개 permanent exclusion + 5-window 재검증 V01",
        "",
        "| 레벨 | 개수 |",
        "|---|---:|",
        f"| CRITICAL | {summary['severity_counts']['CRITICAL']} |",
        f"| MAJOR | {summary['severity_counts']['MAJOR']} |",
        f"| MINOR | {summary['severity_counts']['MINOR']} |",
        "",
        f"- 영구 제외 판정: {summary['exclusion_verdict']}",
        f"- Daily NORMAL Exit 후보: {summary['candidate_verdict']}",
        f"- 시작 HEAD/origin/main: {summary['starting_head']} / {summary['starting_origin_main']}",
        f"- worker: {summary['workers']}",
        "- Strategy signal/trade source entries are filtered by exact identity before the fresh exit-cadence and cash-portfolio replay; neither previous portfolio output nor production state is reused or modified.",
        "",
        "## 1–2. 영구 제외 exact-set 검증",
        "",
        f"기준 중앙 registry {summary['exclusion_authority']['base_count']}개에 사용자 승인 exact pair 7개를 더해 {summary['exclusion_authority']['current_count']}개야. duplicate exact key, normalization collision, ticker-only exclusion은 모두 0이야.",
        "",
        "| ticker | ISU_CD | 종목 | data-quality 사유 |",
        "|---|---|---|---|",
    ]
    for ticker, isu, name, reason in summary["new_exclusion_details"]:
        lines.append(f"| {ticker} | {isu} | {name} | {reason} |")
    lines += [
        "",
        "## 3. 5-window CONTROL/TEST 무결성",
        "",
        "월말 source ledger와 재계산 CONTROL 청산일이 다른 일부 행은 기존 cadence V01에서도 이미 확인된 차이야. 아래 `기존/신규`는 봉인된 사전 제외 cadence 비교표와 exact identity·진입일·양쪽 청산일을 대조해 계산했고, 새 차이만 구조 검증 실패로 처리했어.",
        "",
        "| Window | exclusion count | 제거된 source candidate/fill | 신규 7 leak | 월말 ENTRY 위반 | CONTROL 중간월 EXIT | TEST 비-NORMAL EXIT | exact-session 위반 | invalid open | overlap | silent drop | 현금 오류 | 비용 mismatch | cutoff 뒤 ENTRY | 월말 source parity 기존/신규 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary["integrity_checks"]:
        lines.append(
            f"| {row['window']} | {row['permanent_exclusion_count']} | {row['new_seven_source_eligible_signals_removed']}/{row['new_seven_source_filled_candidate_rows_removed']} | "
            f"{row['post_exclusion_new_seven_identity_leakage']} | {row['monthly_entry_signal_violation_count']} | {row['control_mid_month_exit_signal_count']} | "
            f"{row['test_non_normal_exit_signal_count']} | {row['exact_session_execution_violation_count']} | {row['invalid_open_execution_count']} | "
            f"{row['identity_overlap_violation_count']} | {row['repository_v2_silent_inner_drop_count']} | {row['cash_conservation_failure_count']} | "
            f"{row['cost_audit_mismatch_count']} | {row['cutoff_after_entry_count']} | "
            f"{row['control_monthly_source_signal_mismatch_count']}/{row['legacy_monthly_source_parity_mismatch_count']} / {row['monthly_source_parity_new_mismatch_count']} |"
        )
    lines += [
        "",
        "## 4–5, 7. Portfolio 성과·valuation·자본 운용",
        "",
        "| Window | Case | 최종자산(원) | 총수익률 | CAGR | MDD/유형 | coverage | unresolved marks / 누락일 | 평균/최대 자본활용 | turnover 배수 | 현금부족 skip/비율 | 평균/최대 동시보유 |",
        "|---|---|---:|---:|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary["portfolio_metrics"]:
        lines.append(
            f"| {row['window']} | {row['scenario']} | {_fmt(row.get('ending_equity_krw'), 0)} | {_pct(row.get('total_return_pct'))} | {_pct(row.get('CAGR_pct'))} | "
            f"{_pct(row.get('MDD_observed_pct'))} / {row['official_MDD_type']} | {_pct(row.get('valuation_coverage_pct'))} | "
            f"{row.get('unresolved_valuation_marks')} / {row.get('valuation_missing_equity_days')} | {_pct(row.get('average_capital_utilization_pct'))} / {_pct(row.get('maximum_capital_utilization_pct'))} | "
            f"{_fmt(row.get('turnover_multiple_initial_capital'))}x | {row.get('cash_shortage_skipped_entries')} / {_pct(row.get('cash_shortage_skip_rate_pct'))} | "
            f"{_fmt(row.get('average_concurrent_positions'))} / {_fmt(row.get('maximum_concurrent_positions'), 0)} |"
        )
    lines += [
        "",
        "| Window | Case | 전체 거래일 | 관측 equity | 누락 equity | unresolved 구간 | 최대 누락 연속 | peak / trough / recovery |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in summary["portfolio_metrics"]:
        lines.append(
            f"| {row['window']} | {row['scenario']} | {row.get('valuation_total_days')} | {row.get('valuation_observed_days')} | {row.get('valuation_missing_equity_days')} | "
            f"{row.get('valuation_missing_span_count')} | {row.get('valuation_max_consecutive_missing_days')} | "
            f"{row.get('MDD_peak_date')} / {row.get('MDD_trough_date')} / {row.get('MDD_recovery_date') or '미회복'} |"
        )
    lines += [
        "",
        "valuation-only carry는 공식 KRX raw exact-date 0 OHLC·volume·trading_value placeholder, positive close/listed_shares, exact PIT COMMON 활성, A/B 연속성 audit, 직전 정상 Repository V2 adjusted close와 raw trade anchor를 모두 통과한 경우에만 적용했어. 새 7개 C identity는 후보/체결 입력에서 제거됐고 carry audit에 들어오지 않았어. 단순 결측은 unresolved로 유지했어.",
        "",
        "## 6. 거래 및 tail 비교",
        "",
        "Net return은 실제 포트폴리오에서 실행된 완료 ENTRY/EXIT 체결의 비용 반영 수익률이야.",
        "",
        "| Window | Case | 실행 ENTRY | 완료 거래 | cutoff 미청산 | 승률 | 평균/중앙 수익률 | 평균/중앙 보유일 | <=-15 / <=-30 | >=+30 / >=+50 / >=+100 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary["trade_metrics"]:
        tails = row["tail_counts_net_return"]
        lines.append(
            f"| {row['window']} | {row['scenario']} | {row['executed_entry_count']} | {row['realized_trade_count']} | {row['open_at_effective_cutoff_count']} | {_pct(row.get('win_rate_pct'))} | "
            f"{_pct(row.get('mean_realized_net_return_pct'))} / {_pct(row.get('median_realized_net_return_pct'))} | "
            f"{_fmt(row.get('mean_holding_krx_sessions'))} / {_fmt(row.get('median_holding_krx_sessions'))} | "
            f"{tails['le_neg_15']['count']} / {tails['le_neg_30']['count']} | "
            f"{tails['ge_pos_30']['count']} / {tails['ge_pos_50']['count']} / {tails['ge_pos_100']['count']} |"
        )
    lines += [
        "",
        "## 8–9. 공식 A–E Gate 및 후보 판정",
        "",
        "| Window | A | B | C | D | E | CONTROL−TEST MDD | TEST MDD 절대 기준 |",
        "|---|---|---|---|---|---|---:|---|",
    ]
    for row in summary["candidate_gates"]:
        lines.append(
            f"| {row['window']} | {row['A']} | {row['B']} | {row['C']} | {row['D']} | {row['E']} | "
            f"{_fmt(row.get('relative_control_minus_test_mdd_pp'))}pp | {row['test_absolute_mdd_floor_pct']}% |"
        )
    lines += [
        "",
        f"상대 기준은 CONTROL MDD − TEST MDD가 5.0%p 이상이면 FAIL이야. coverage 90% 미만 case의 관측 MDD는 공식 Gate PASS 근거로 쓰지 않았어. 현금 부족 skip은 필수 진단값이며 PASS/FAIL Gate로 쓰지 않았어.",
        "",
        f"후보 최종 판정 token: {summary['candidate_verdict']}.",
        f"영구 제외 및 구조 검증 token: {summary['exclusion_verdict']}.",
        "",
        "## 10. 적용 경계",
        "",
        "중앙 exact identity exclusion authority만 공통 반영했어. A FAST Core V2와 Julia V1은 이번 작업에서 백테스트하지 않았어. B Select 연구 portfolio만 새로 재생했으며, 공식 전략 승격·history/lifecycle 수정·Production 적용은 별도 지시가 필요해.",
        "",
        "## 재현 및 산출물",
        "",
        f"- worker count: {summary['workers']}",
        f"- 월말 source parity baseline: {summary['legacy_monthly_source_parity_baseline']['path']} (SHA-256 {summary['legacy_monthly_source_parity_baseline']['sha256']}); window별 사전 확인된 차이 {summary['legacy_monthly_source_parity_baseline']['window_mismatch_counts']}",
        "- 분석기: scripts/replay_b_select_daily_normal_exit_permanent_exclusion_v01.py",
        "- 테스트: tests/test_b_select_daily_normal_exit_permanent_exclusion_v01.py",
        "- 상세 원장: exclusion_impact.csv, integrity_checks.csv, portfolio_metrics.csv, trade_metrics.csv, valuation_carry_audit.csv, 각 window/scenario 하위 event·trade·equity·cost 파일",
        f"- 경과 시간: {summary['elapsed_seconds']:.1f}초",
    ]
    return "\n".join(lines) + "\n"


def _fmt(value: Any, places: int = 2) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):,.{places}f}"


def _pct(value: Any) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):.2f}%"


def run() -> dict[str, Any]:
    started = time.time()
    start_state = verify_start_state()
    exclusion_authority = verify_exclusion_authority()
    out_root = ROOT / OUTPUT_ROOT
    if out_root.exists():
        raise FileExistsError(f"refusing to overwrite research output: {out_root}")
    inputs_by_window = _load_window_inputs()
    legacy_source_parity, legacy_source_parity_sha256 = _legacy_source_parity_baseline()
    intervals, trading_dates, market_authority = pattern_b_base._load_authorities(ROOT)
    impact_rows, input_integrity = _candidate_exclusion_audit(inputs_by_window, trading_dates)
    interval_map = _interval_map(intervals)
    basis_identities = set(map(tuple, exclusion_authority["approved_carry_identities"]))

    max_support = max(str(inputs_by_window[wid]["window"]["execution_support"])[:10] for wid in WINDOW_IDS)
    records_by_window = {
        wid: [copy.deepcopy(row) for row in inputs_by_window[wid]["records"]]
        for wid in WINDOW_IDS
    }
    daily_by_ticker, ticker_audit, repository, requested_starts = cadence._load_all_prices(records_by_window, max_support)
    frames_by_window = {
        wid: portfolio_v01.build_component_frames(rows, daily_by_ticker, intervals, trading_dates)
        for wid, rows in records_by_window.items()
    }
    for wid in WINDOW_IDS:
        inputs_by_window[wid]["records"] = records_by_window[wid]

    overall_start = min(str(inputs_by_window[wid]["window"]["effective_start"])[:10] for wid in WINDOW_IDS)
    overall_end = max(str(inputs_by_window[wid]["window"]["effective_end"])[:10] for wid in WINDOW_IDS)
    boundary_dates = cadence._feature_boundary_sessions(trading_dates, overall_start, overall_end)
    month_end_dates = cadence._month_end_sessions(trading_dates, overall_start, overall_end)
    state_cache: dict[tuple[str, str], dict[str, Any]] = {}
    state_audit: dict[tuple[str, str], dict[str, Any]] = {}
    window_results: dict[str, Any] = {}
    scenario_trade_rows_by_window: dict[str, dict[str, list[dict[str, Any]]]] = {}
    carry_audit: list[dict[str, Any]] = []
    raw_store = KrxRawStockStore(ROOT / "data/market/raw/krx_stocks/v01")
    raw_cache: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    raw_manifests: dict[tuple[str, str], dict[str, Any]] = {}
    portfolio_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    integrity_rows: list[dict[str, Any]] = []
    comparison_rows: list[dict[str, Any]] = []
    output_data: dict[str, dict[str, Any]] = {}
    for window_id in WINDOW_IDS:
        inputs = inputs_by_window[window_id]
        window = inputs["window"]
        start, end, support = (str(window[key])[:10] for key in ("effective_start", "effective_end", "execution_support"))
        frames = frames_by_window[window_id]
        scenario_rows, comparisons, run_audit = cadence._build_trade_rows(
            inputs, frames, trading_dates, boundary_dates, month_end_dates, state_cache, state_audit,
        )
        if run_audit["exit_errors"]:
            raise RuntimeError(f"{window_id}:EXIT_EXECUTION_SUPPORT_ERRORS:{len(run_audit['exit_errors'])}")
        control_keys = {
            (str(row["ticker"]).zfill(6), str(row["isu_cd"]).upper(), str(row["entry_signal_date"])[:10])
            for row in scenario_rows["CONTROL_MONTH_END"]
        }
        test_keys = {
            (str(row["ticker"]).zfill(6), str(row["isu_cd"]).upper(), str(row["entry_signal_date"])[:10])
            for row in scenario_rows["TEST_DAILY"]
        }
        if control_keys != test_keys:
            raise RuntimeError(f"{window_id}:ENTRY_KEY_DATE_PARITY_FAIL")
        scenario_trade_rows_by_window[window_id] = scenario_rows
        window_month_ends = set(cadence._month_end_sessions(trading_dates, start, end))
        monthly_entry_violations = sum(
            str(row.get("entry_signal_date", ""))[:10] not in window_month_ends
            for scenario in SCENARIOS for row in scenario_rows[scenario]
        )
        control_mid_month_exits = sum(
            bool(row.get("exit_signal_date"))
            and str(row.get("exit_signal_date"))[:10] not in window_month_ends
            for row in scenario_rows["CONTROL_MONTH_END"]
        )
        test_non_normal_exits = sum(
            bool(row.get("exit_signal_date"))
            and str(row.get("exit_signal_state")) != "NORMAL"
            for row in scenario_rows["TEST_DAILY"]
        )
        if monthly_entry_violations or control_mid_month_exits or test_non_normal_exits:
            raise RuntimeError(
                f"{window_id}:CADENCE_RULE_VIOLATION:{monthly_entry_violations}:"
                f"{control_mid_month_exits}:{test_non_normal_exits}"
            )
        case_audits: dict[str, Any] = {}
        for scenario in SCENARIOS:
            records = [copy.deepcopy(row) for row in scenario_rows[scenario]]
            strategy_id = f"{STUDY_ID}_{window_id.replace('-', '_')}_{scenario}"
            execution_price_audit = portfolio_v01.verify_execution_prices(records, frames, window)
            next_audit = portfolio_v02.verify_next_session_execution_dates(records, frames, trading_dates, window)
            if next_audit["violation_count"]:
                raise RuntimeError(f"{strategy_id}:EXACT_SESSION_EXECUTION_FAILURE")
            replay = _replay_with_official_carry(
                records, frames, trading_dates, window, strategy_id, basis_identities,
                interval_map, raw_store, raw_cache, raw_manifests, carry_audit,
            )
            events = list(replay["events"])
            records_by_pair = {str(row.get("pair_id")): row for row in records}
            target_event_leaks = sum(_event_identity(event, records_by_pair) in NEW_IDENTITIES for event in events)
            target_skip_leaks = sum(
                _identity({
                    "ticker": row.get("ticker") or records_by_pair.get(str(row.get("pair_id")), {}).get("ticker"),
                    "isu_cd": row.get("isu_cd") or records_by_pair.get(str(row.get("pair_id")), {}).get("isu_cd"),
                }) in NEW_IDENTITIES
                for row in replay["skipped"]
            )
            lifecycle = portfolio_v02.verify_executed_identity_lifecycle(events)
            valuation = portfolio_v02.summarize_valuation(replay["daily_equity"], replay["skipped"], window)
            metrics = portfolio_v02.window_metrics_from_replay(replay, inputs, valuation, trading_dates)
            cash = portfolio_v02.cash_diagnostics(replay, metrics, {})
            diagnostics = portfolio_v01.build_portfolio_diagnostics(replay, records, frames, window, inputs["summary"])
            cost_rows, cost_audit = portfolio_v02.audit_costs(events)
            unresolved_execution = sum(row.get("event_status") == "UNRESOLVED" for row in events)
            silent_drops = sum(int(row.get("silent_inner_drop_count", 0) or 0) for row in ticker_audit.values())
            post_cutoff_entries = sum(
                row.get("event_type") == "ENTRY"
                and row.get("event_status") == "EXECUTED"
                and str(row.get("execution_date", ""))[:10] > end
                for row in events
            )
            invalid_open_count = int(execution_price_audit["missing_exact_opens"]) + int(execution_price_audit["price_mismatch_count"])
            if any((target_event_leaks, target_skip_leaks, lifecycle["violation_count"], silent_drops, unresolved_execution, post_cutoff_entries, invalid_open_count)):
                raise RuntimeError(
                    f"{strategy_id}:STRUCTURAL_AUDIT_FAILURE:leak={target_event_leaks + target_skip_leaks}:"
                    f"overlap={lifecycle['violation_count']}:drop={silent_drops}:unresolved_exec={unresolved_execution}:"
                    f"post_cutoff={post_cutoff_entries}:invalid_open={invalid_open_count}"
                )
            if metrics.get("cash_conservation_pass") is not True:
                raise RuntimeError(f"{strategy_id}:CASH_CONSERVATION_FAILURE")
            if cost_audit["mismatch_count"] or not cost_audit["coverage_complete"]:
                raise RuntimeError(f"{strategy_id}:COST_AUDIT_FAILURE:{cost_audit}")
            case_audits[scenario] = {
                "records": records, "replay": replay, "valuation": valuation,
                "metrics": metrics, "cash": cash, "diagnostics": diagnostics,
                "cost_rows": cost_rows, "cost_audit": cost_audit,
                "execution_price_audit": execution_price_audit, "next_session_audit": next_audit,
                "lifecycle": lifecycle, "unresolved_execution_event_count": unresolved_execution,
            }

        output_leakage = sum(
            _identity(row) in portfolio_v02.current_exclusion_keys()
            for scenario in SCENARIOS for row in scenario_rows[scenario]
        )
        control_metrics = case_audits["CONTROL_MONTH_END"]["metrics"]
        test_metrics = case_audits["TEST_DAILY"]["metrics"]
        current_source_parity = _current_source_parity_mismatches(comparisons)
        legacy_source_parity_for_window = legacy_source_parity[window_id]
        case_integrity = {
            "window": window_id,
            **next(row for row in input_integrity if row["window"] == window_id),
            "entry_key_date_parity": True,
            "entry_key_count": len(control_keys),
            "monthly_entry_signal_violation_count": monthly_entry_violations,
            "control_mid_month_exit_signal_count": control_mid_month_exits,
            "test_non_normal_exit_signal_count": test_non_normal_exits,
            "post_exclusion_trade_row_leakage": output_leakage,
            "exact_session_execution_violation_count": sum(case_audits[s]["next_session_audit"]["violation_count"] for s in SCENARIOS),
            "invalid_open_execution_count": sum(case_audits[s]["execution_price_audit"]["missing_exact_opens"] + case_audits[s]["execution_price_audit"]["price_mismatch_count"] for s in SCENARIOS),
            "identity_overlap_violation_count": sum(case_audits[s]["lifecycle"]["violation_count"] for s in SCENARIOS),
            "repository_v2_silent_inner_drop_count": silent_drops,
            "cash_conservation_failure_count": sum(case_audits[s]["metrics"].get("cash_conservation_pass") is not True for s in SCENARIOS),
            "cost_audit_mismatch_count": sum(case_audits[s]["cost_audit"]["mismatch_count"] for s in SCENARIOS),
            "cutoff_after_entry_count": sum(
                str(row.get("entry_signal_date", ""))[:10] > end or str(row.get("entry_execution_date", ""))[:10] > end
                for scenario in SCENARIOS for row in scenario_rows[scenario]
            ),
            "control_monthly_source_signal_mismatch_count": run_audit["validations"]["control_source_monthly_exit_signal_mismatch_count"],
            "control_monthly_source_execution_mismatch_count": run_audit["validations"]["control_source_monthly_exit_execution_mismatch_count"],
            "legacy_monthly_source_parity_mismatch_count": len(legacy_source_parity_for_window),
            "monthly_source_parity_new_mismatch_count": len(current_source_parity - legacy_source_parity_for_window),
            "monthly_source_parity_resolved_mismatch_count": len(legacy_source_parity_for_window - current_source_parity),
        }
        structural_count_fields = (
            "post_exclusion_new_seven_identity_leakage", "post_exclusion_trade_row_leakage",
            "monthly_entry_signal_violation_count", "control_mid_month_exit_signal_count",
            "test_non_normal_exit_signal_count", "exact_session_execution_violation_count",
            "invalid_open_execution_count", "identity_overlap_violation_count",
            "repository_v2_silent_inner_drop_count", "cash_conservation_failure_count",
            "cost_audit_mismatch_count", "cutoff_after_entry_count",
            "monthly_source_parity_new_mismatch_count",
        )
        if any(int(case_integrity[field]) != 0 for field in structural_count_fields):
            raise RuntimeError(f"{window_id}:FINAL_STRUCTURAL_CHECK_FAILURE:{case_integrity}")
        integrity_rows.append(case_integrity)
        portfolio_case_data: dict[str, Any] = {}
        for scenario in SCENARIOS:
            case = case_audits[scenario]
            metrics = case["metrics"]
            valuation = case["valuation"]
            cash = case["cash"]
            diag = case["diagnostics"]
            executed_counts = _executed_event_counts(case["replay"]["events"])
            mdd_official_type = (
                "EXACT MDD" if float(valuation["coverage_pct"]) >= 100.0
                else "OBSERVED MDD" if float(valuation["coverage_pct"]) >= 90.0
                else "NO OFFICIAL MDD: coverage below 90%"
            )
            row = {
                "window": window_id, "scenario": scenario,
                "effective_start": start, "effective_end": end, "execution_support": support,
                "ending_equity_krw": metrics.get("final_equity"),
                "ending_equity_at_effective_cutoff_krw": metrics.get("final_equity_at_effective_close"),
                "total_return_pct": metrics.get("cumulative_return_pct"), "CAGR_pct": metrics.get("CAGR_pct"),
                "MDD_observed_pct": valuation.get("mdd_pct"), "engine_MDD_type": valuation.get("mdd_type"),
                "official_MDD_type": mdd_official_type, "valuation_coverage_pct": valuation.get("coverage_pct"),
                "valuation_total_days": valuation.get("total_days"), "valuation_observed_days": valuation.get("observed_days"),
                "valuation_missing_equity_days": valuation.get("missing_days"), "unresolved_valuation_marks": valuation.get("unresolved_marks"),
                "valuation_missing_span_count": valuation.get("missing_span_count"),
                "valuation_max_consecutive_missing_days": valuation.get("max_consecutive_missing_days"),
                "MDD_peak_date": valuation.get("peak_date"), "MDD_trough_date": valuation.get("trough_date"),
                "MDD_recovery_date": valuation.get("recovery_date"),
                "MDD_unrecovered": bool(valuation.get("mdd_pct") is not None and float(valuation["mdd_pct"]) < 0 and not valuation.get("recovered")),
                "average_capital_utilization_pct": cash.get("average_capital_utilization_pct"),
                "maximum_capital_utilization_pct": cash.get("maximum_capital_utilization_pct"),
                "turnover_krw": cash.get("turnover_krw"),
                "turnover_multiple_initial_capital": cash.get("turnover_multiple_initial_capital"),
                "cash_eligible_entry_attempts": cash.get("eligible_entry_attempts"),
                "cash_shortage_skipped_entries": cash.get("cash_shortage_skipped_entries"),
                "cash_shortage_skip_rate_pct": cash.get("cash_shortage_skip_rate_pct"),
                "average_concurrent_positions": cash.get("average_concurrent_positions"),
                "maximum_concurrent_positions": cash.get("maximum_concurrent_positions"),
                "executed_entry_count": executed_counts["executed_entry_count"],
                "executed_exit_count": executed_counts["executed_exit_count"],
                "open_at_cutoff_count": diag.get("open_at_cutoff_count"),
                "open_at_cutoff_exact_mark_count": diag.get("open_at_cutoff_exact_mark_count"),
                "open_at_cutoff_unresolved_count": diag.get("open_at_cutoff_unresolved_count"),
                "commission_total_krw": metrics.get("total_commissions_krw"),
                "slippage_total_krw": metrics.get("slippage_impact_krw"),
                "sell_tax_total_krw": metrics.get("total_sell_tax_krw"),
                "cash_conservation_pass": metrics.get("cash_conservation_pass"),
                "cost_coverage_complete": case["cost_audit"].get("coverage_complete"),
                "cost_audit_mismatch_count": case["cost_audit"].get("mismatch_count"),
                "unresolved_execution_event_count": case["unresolved_execution_event_count"],
            }
            portfolio_rows.append(row)
            trades = _realized_trade_metrics(diag, case["replay"]["events"])
            trade_rows.append({"window": window_id, "scenario": scenario, **trades})
            portfolio_case_data[scenario] = case
        gates, gate_evidence = _candidate_gates(
            window_id,
            portfolio_case_data["CONTROL_MONTH_END"],
            portfolio_case_data["TEST_DAILY"],
            integrity_pass=True,
        )
        window_results[window_id] = {
            "window": dict(window),
            "integrity": case_integrity,
            "candidate_gates": {**gates, **{"relative_control_minus_test_mdd_pp": gate_evidence["relative_control_minus_test_mdd_pp"]},
                                "test_absolute_mdd_floor_pct": gate_evidence["test_absolute_mdd_floor_pct"]},
            "gate_evidence": gate_evidence,
            "portfolio_metrics": {scenario: portfolio_case_data[scenario]["metrics"] for scenario in SCENARIOS},
            "valuation": {scenario: portfolio_case_data[scenario]["valuation"] for scenario in SCENARIOS},
            "trade_metrics": {scenario: trade_rows[-2 + index] for index, scenario in enumerate(SCENARIOS)},
            "effect": {
                "test_minus_control_total_return_pp": (
                    portfolio_case_data["TEST_DAILY"]["metrics"].get("cumulative_return_pct")
                    - portfolio_case_data["CONTROL_MONTH_END"]["metrics"].get("cumulative_return_pct")
                ),
                "test_minus_control_CAGR_pp": (
                    portfolio_case_data["TEST_DAILY"]["metrics"].get("CAGR_pct")
                    - portfolio_case_data["CONTROL_MONTH_END"]["metrics"].get("CAGR_pct")
                ),
                "control_minus_test_MDD_pp": gate_evidence["relative_control_minus_test_mdd_pp"],
                "test_minus_control_cash_skip_rate_pp": (
                    portfolio_case_data["TEST_DAILY"]["cash"].get("cash_shortage_skip_rate_pct")
                    - portfolio_case_data["CONTROL_MONTH_END"]["cash"].get("cash_shortage_skip_rate_pct")
                ),
            },
        }
        comparison_rows.append({"window": window_id, **window_results[window_id]["effect"]})
        output_data[window_id] = {
            "scenario_data": portfolio_case_data,
            "trade_comparisons": comparisons,
        }
        print(json.dumps({
            "window": window_id,
            "control_coverage_pct": portfolio_case_data["CONTROL_MONTH_END"]["valuation"]["coverage_pct"],
            "test_coverage_pct": portfolio_case_data["TEST_DAILY"]["valuation"]["coverage_pct"],
            "control_return_pct": control_metrics.get("cumulative_return_pct"),
            "test_return_pct": test_metrics.get("cumulative_return_pct"),
            "new_identity_leakage": 0,
            "workers": WORKERS,
        }, ensure_ascii=False), flush=True)

    spot_checks = cadence._validate_state_piecewise(
        scenario_trade_rows_by_window,
        {key: frame for frames in frames_by_window.values() for key, frame in frames.items()},
        trading_dates, boundary_dates, state_cache, state_audit,
    )
    if not all(row["all_checks_pass"] for row in spot_checks):
        raise RuntimeError("DAILY_PATTERN_STATE_BOUNDARY_SPOT_CHECK_FAILED")
    if any(_identity(row) in NEW_IDENTITIES for row in carry_audit):
        raise RuntimeError("NEW_PERMANENT_EXCLUSIONS_RECEIVED_VALUATION_CARRY")
    if len({(row["strategy_id"], row["pair_id"], row["valuation_date"]) for row in carry_audit}) != len(carry_audit):
        raise RuntimeError("DUPLICATE_VALUATION_CARRY_AUDIT_KEY")

    candidate_gates = [
        {"window": window_id, **window_results[window_id]["candidate_gates"]}
        for window_id in WINDOW_IDS
    ]
    any_fail = any(any(window_results[wid]["candidate_gates"][gate] == "FAIL" for gate in "ABCDE") for wid in WINDOW_IDS)
    any_check = any(any(window_results[wid]["candidate_gates"][gate] == "CHECK_REQUIRED" for gate in "ABCDE") for wid in WINDOW_IDS)
    candidate_verdict = (
        "B_SELECT_DAILY_NORMAL_EXIT_CANDIDATE_REJECTED" if any_fail else
        "B_SELECT_DAILY_NORMAL_EXIT_CANDIDATE_CHECK_REQUIRED" if any_check else
        "B_SELECT_DAILY_NORMAL_EXIT_CANDIDATE_VALIDATION_PASS"
    )
    major_window_count = sum(
        any(window_results[wid]["candidate_gates"][gate] != "PASS" for gate in "ABCDE")
        for wid in WINDOW_IDS
    )
    carry_counts = {
        "authorized_marks": sum(row["status"] == "CARRY_AUTHORIZED" for row in carry_audit),
        "unresolved_marks": sum(row["status"] == "UNRESOLVED" for row in carry_audit),
        "raw_partition_count": len(raw_cache),
        "raw_partition_complete_count": sum(row.get("status") == "COMPLETE" for row in raw_manifests.values()),
        "raw_partition_incomplete_count": sum(row.get("status") != "COMPLETE" for row in raw_manifests.values()),
        "new_excluded_identity_carry_count": 0,
    }
    summary = {
        "study_id": STUDY_ID,
        "status": "PASS_STRUCTURAL_REPLAY_COMPLETED",
        "starting_head": start_state["head"],
        "starting_origin_main": start_state["origin_main"],
        "starting_worktree_status": start_state["status"],
        "workers": WORKERS,
        "exclusion_authority": exclusion_authority,
        "legacy_monthly_source_parity_baseline": {
            "path": str(LEGACY_CADENCE_COMPARISON_PATH),
            "sha256": legacy_source_parity_sha256,
            "window_mismatch_counts": {window_id: len(legacy_source_parity[window_id]) for window_id in WINDOW_IDS},
            "interpretation": "Existing monthly source-ledger parity differences are disclosed and compared with the immutable pre-exclusion cadence artifact; only newly introduced differences fail structural integrity.",
        },
        "exclusion_verdict": "B_SELECT_7_IDENTITY_PERMANENT_EXCLUSION_PASS",
        "candidate_verdict": candidate_verdict,
        "severity_counts": {"CRITICAL": 0, "MAJOR": major_window_count, "MINOR": 0},
        "new_exclusion_details": [
            ("007720", "KR7007720006", "소노스퀘어", "주식수 변경 뒤 adjusted price unit 연속성 미확정"),
            ("011080", "KR7011080009", "형지I&C", "주식수 변경 뒤 adjusted price unit 연속성 미확정"),
            ("019490", "KR7019490002", "엑시큐어하이트론", "주식수 변경 뒤 adjusted price unit 연속성 미확정"),
            ("019570", "KR7019570001", "GMI벤처", "설명되지 않은 adjusted price unit 변화"),
            ("066790", "KR7066790007", "씨씨에스", "복수 주식수 변경 뒤 adjusted price unit 연속성 미확정"),
            ("073570", "KR7073570004", "리튬포어스", "주식수 변경 뒤 adjusted price unit 연속성 미확정"),
            ("083660", "KR7083660001", "CSA 코스믹", "주식수 변경 뒤 adjusted price unit 연속성 미확정"),
        ],
        "integrity_checks": integrity_rows,
        "new_identity_candidate_impact": impact_rows,
        "portfolio_metrics": portfolio_rows,
        "trade_metrics": trade_rows,
        "candidate_gates": candidate_gates,
        "window_results": window_results,
        "valuation_carry_counts": carry_counts,
        "carry_audit": carry_audit,
        "state_piecewise_spot_checks": {"count": len(spot_checks), "passed": sum(bool(row["all_checks_pass"]) for row in spot_checks)},
        "market_authority": market_authority,
        "requested_price_start_by_ticker": requested_starts,
        "price_ticker_audit": ticker_audit,
        "source_hashes": {
            "permanent_exclusion_policy": sha256(ROOT / POLICY_PATH),
            "prior_identity_basis_audit": sha256(ROOT / PREVIOUS_BASIS_PATH),
            "official_common_rules": sha256(ROOT / "docs/validation/backtest_common_rules.md"),
            "official_adoption_criteria": sha256(ROOT / "docs/validation/official_strategy_adoption_criteria.md"),
            "candidate_analysis_source": sha256(ROOT / cadence.SOURCE_ROOT / "p1" / "metadata.json"),
            "daily_cadence_helper": sha256(Path(cadence.__file__)),
            "cash_portfolio_engine": sha256(Path(portfolio_v02.portfolio.__file__)),
        },
        "price_authority_hashes": {
            f"data/market/adjusted/stocks/{ticker}.parquet": sha256(ROOT / "data/market/adjusted/stocks" / f"{ticker}.parquet")
            for ticker in sorted(daily_by_ticker)
        },
        "elapsed_seconds": round(time.time() - started, 3),
    }
    if out_root.exists():
        raise FileExistsError(f"refusing to overwrite research output: {out_root}")
    out_root.mkdir(parents=True)
    for row in integrity_rows:
        pass
    pd.DataFrame(impact_rows).to_csv(out_root / "exclusion_impact.csv", index=False)
    pd.DataFrame(integrity_rows).to_csv(out_root / "integrity_checks.csv", index=False)
    pd.DataFrame(portfolio_rows).to_csv(out_root / "portfolio_metrics.csv", index=False)
    pd.DataFrame(trade_rows).to_csv(out_root / "trade_metrics.csv", index=False)
    pd.DataFrame(candidate_gates).to_csv(out_root / "candidate_gates.csv", index=False)
    pd.DataFrame(comparison_rows).to_csv(out_root / "window_comparison.csv", index=False)
    pd.DataFrame(carry_audit).to_csv(out_root / "valuation_carry_audit.csv", index=False)
    pd.DataFrame([
        {"window": wid, "scenario": scenario, **case["metrics"],
         "valuation": json.dumps(case["valuation"], ensure_ascii=False, sort_keys=True),
         "cash": json.dumps(case["cash"], ensure_ascii=False, sort_keys=True),
         "diagnostics": json.dumps(case["diagnostics"], ensure_ascii=False, sort_keys=True)}
        for wid, payload in output_data.items()
        for scenario, case in payload["scenario_data"].items()
    ]).to_csv(out_root / "portfolio_case_detail.csv", index=False)
    pd.DataFrame(state_audit.values()).to_csv(out_root / "state_observation_audit.csv", index=False)
    pd.DataFrame(spot_checks).to_csv(out_root / "daily_state_piecewise_spot_checks.csv", index=False)
    for window_id, payload in output_data.items():
        case_dir = out_root / window_id.lower().replace("-", "_")
        case_dir.mkdir()
        pd.DataFrame(payload["trade_comparisons"]).to_csv(case_dir / "trade_comparison.csv", index=False)
        for scenario, case in payload["scenario_data"].items():
            stem = scenario.lower()
            pd.DataFrame(case["records"]).to_csv(case_dir / f"{stem}_trade_ledger.csv", index=False)
            pd.DataFrame(case["replay"]["events"]).to_csv(case_dir / f"{stem}_portfolio_events.csv", index=False)
            pd.DataFrame(case["replay"]["daily_equity"]).to_csv(case_dir / f"{stem}_daily_equity.csv", index=False)
            pd.DataFrame(case["replay"]["skipped"]).to_csv(case_dir / f"{stem}_portfolio_skips.csv", index=False)
            pd.DataFrame(case["cost_rows"]).to_csv(case_dir / f"{stem}_cost_audit.csv", index=False)
    summary["generated_files_sha256"] = {
        str(path.relative_to(out_root)): sha256(path)
        for path in sorted(out_root.rglob("*")) if path.is_file()
    }
    summary["generated_files_sha256"].pop("summary.json", None)
    summary["generated_files_sha256"].pop("metadata.json", None)
    (out_root / "report.md").write_text(_report(summary), encoding="utf-8")
    (out_root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True, default=portfolio_v01.json_default, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    generated_hashes = {
        str(path.relative_to(out_root)): {"sha256": sha256(path), "bytes": path.stat().st_size}
        for path in sorted(out_root.rglob("*")) if path.is_file() and path.name not in {"metadata.json"}
    }
    metadata = {
        "study_id": STUDY_ID,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "starting_head": start_state["head"],
        "starting_origin_main": start_state["origin_main"],
        "workers": WORKERS,
        "permanent_exclusion_identity_count": 181,
        "strategy_id": "PATTERN_B_SELECT_CORE_V01",
        "no_production_changes": True,
        "official_history_modified": False,
        "control_and_test_share_price_authority_and_cash_engine": True,
        "source_hashes": summary["source_hashes"],
        "generated_files": generated_hashes,
        "script_sha256": sha256(Path(__file__)),
        "elapsed_seconds": summary["elapsed_seconds"],
    }
    (out_root / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True, default=portfolio_v01.json_default, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return {
        "status": summary["status"], "summary_path": str(out_root / "summary.json"),
        "report_path": str(out_root / "report.md"), "candidate_verdict": candidate_verdict,
        "exclusion_verdict": summary["exclusion_verdict"], "workers": WORKERS,
        "elapsed_seconds": summary["elapsed_seconds"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--preflight", action="store_true")
    group.add_argument("--run", action="store_true")
    args = parser.parse_args()
    result = preflight() if args.preflight else run()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=portfolio_v01.json_default), flush=True)


if __name__ == "__main__":
    main()
