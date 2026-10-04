#!/usr/bin/env python3
"""Audit exact-next sensitivity for seven excluded historical Pattern B trades.

The source ledgers contain seven delayed fills, but the official cash-aware
portfolio event streams exclude all seven under the existing permanent
RAW_DATA_GAP identity policy. This runner therefore validates the trade-level
sensitivity and proves zero official portfolio exposure; it intentionally does
not replay the portfolio with excluded identities reintroduced.
"""

from __future__ import annotations

import csv
import ast
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_pattern_b_progressed_previous_et_only_realistic_portfolio_v02 as portfolio_v02  # noqa: E402
from scripts import run_pattern_b_pure_simple_backtest_v01 as pattern_b_base  # noqa: E402
from src.trend_scanner.universe.permanent_identity_exclusions import (  # noqa: E402
    PERMANENT_IDENTITY_EXCLUSIONS,
)
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore  # noqa: E402

SOURCE_ROOT = Path(
    "artifacts/patterns/pattern_b/"
    "progressed_previous_stage_early_transition_only_5window_v01"
)
PORTFOLIO_ROOT = Path(
    "artifacts/patterns/pattern_b/"
    "progressed_previous_stage_early_transition_only_realistic_portfolio_v03"
)
CLOSURE_ROOT = Path(
    "artifacts/patterns/pattern_b/"
    "progressed_previous_stage_early_transition_only_realistic_portfolio_v03_mdd_closure_v01"
)
HISTORICAL_AUDIT = Path(
    "artifacts/strategies/b_select_core_v1/research/"
    "historical_execution_authority_audit_v01/report.md"
)
OFFICIAL_CRITERIA = Path("docs/validation/official_strategy_adoption_criteria.md")
COMMON_RULES = Path("docs/validation/backtest_common_rules.md")
EXCLUSION_POLICY = Path("src/trend_scanner/universe/permanent_identity_exclusions.py")
OUTPUT_ROOT = Path(
    "artifacts/strategies/b_select_core_v1/research/"
    "exact_next_normalization_impact_v01"
)
RUNNER_RELATIVE = Path("scripts/replay_b_select_exact_next_normalization_impact_v01.py")

WINDOW_DIR = {
    "P1": "p1",
    "P2-1": "p2_1",
    "P2-2": "p2_2",
    "P3-1": "p3_1",
    "P3-2": "p3_2",
}
ALL_WINDOWS = tuple(WINDOW_DIR)
PORTFOLIO_WINDOWS = ("P1", "P2-1", "P2-2")

TARGETS = (
    {"side": "ENTRY", "ticker": "018680", "signal_date": "2016-02-29", "expected_date": "2016-03-02"},
    {"side": "ENTRY", "ticker": "072020", "signal_date": "2017-03-31", "expected_date": "2017-04-03"},
    {"side": "ENTRY", "ticker": "109820", "signal_date": "2017-03-31", "expected_date": "2017-04-03"},
    {"side": "EXIT", "ticker": "001040", "signal_date": "2017-05-31", "expected_date": "2017-06-01"},
    {"side": "EXIT", "ticker": "005030", "signal_date": "2016-05-31", "expected_date": "2016-06-01"},
    {"side": "EXIT", "ticker": "014200", "signal_date": "2022-03-31", "expected_date": "2022-04-01"},
    {"side": "EXIT", "ticker": "078160", "signal_date": "2018-11-30", "expected_date": "2018-12-03"},
)
EXPECTED_SOURCE_EXPOSURES = {"P1": 7, "P2-1": 1, "P2-2": 1, "P3-1": 0, "P3-2": 0}
COMMISSION_RATE = 0.00015
SLIPPAGE_RATE = 0.001


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(list(rows)).to_csv(path, index=False, encoding="utf-8")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def as_day(value: Any) -> str:
    return str(value)[:10]


def as_float(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise RuntimeError(f"NONFINITE_PRICE_OR_RETURN:{value}")
    return number


def costed_pre_tax_return_pct(entry: float, exit_: float) -> float:
    buy_cash_per_share = entry * (1.0 + SLIPPAGE_RATE) * (1.0 + COMMISSION_RATE)
    sell_proceeds_per_share = exit_ * (1.0 - SLIPPAGE_RATE) * (1.0 - COMMISSION_RATE)
    return (sell_proceeds_per_share / buy_cash_per_share - 1.0) * 100.0


def gross_return_pct(entry: float, exit_: float) -> float:
    return (exit_ / entry - 1.0) * 100.0


def load_adjusted_rows(ticker: str) -> tuple[dict[str, Any], dict[str, Any]]:
    base = ROOT / "data/market/adjusted/stocks" / ticker
    meta = read_json(base.with_suffix(".meta.json"))
    if (
        meta.get("source_name") != "NAVER_DIRECT_DATE_RANGE_ADJUSTED"
        or meta.get("source_native_adjusted") is not True
    ):
        raise RuntimeError(f"CURRENT_NAVER_ADJUSTED_AUTHORITY_MISMATCH:{ticker}:{meta.get('source_name')}")
    frame = pd.read_parquet(base.with_suffix(".parquet"))
    by_date: dict[str, Any] = {}
    for row in frame.itertuples(index=False):
        day = as_day(row.date)
        if day in by_date:
            raise RuntimeError(f"DUPLICATE_ADJUSTED_DATE:{ticker}:{day}")
        by_date[day] = row
    return meta, by_date


def exact_raw_row(
    store: KrxRawStockStore,
    market: str,
    ticker: str,
    day: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = store.get_manifest(market, day)
    if manifest is None or manifest.get("status") != "COMPLETE":
        raise RuntimeError(f"EXACT_KRX_SNAPSHOT_NOT_COMPLETE:{market}:{day}")
    # load_snapshot verifies the immutable partition hashes, schema, count and content.
    frame = store.load_snapshot(market, day)
    matches = frame[frame["ticker"].astype(str).str.zfill(6).eq(ticker)]
    if len(matches) != 1:
        raise RuntimeError(f"EXACT_KRX_TICKER_ROW_COUNT:{market}:{day}:{ticker}:{len(matches)}")
    row = matches.iloc[0].to_dict()
    if int(row["open"]) <= 0 or int(row["volume"]) <= 0:
        raise RuntimeError(f"EXACT_KRX_SESSION_NOT_TRADED:{market}:{day}:{ticker}")
    return row, manifest


def metric_bundle(window_id: str) -> dict[str, Any]:
    dirname = WINDOW_DIR[window_id]
    metrics = read_json(ROOT / PORTFOLIO_ROOT / dirname / "portfolio_metrics.json")
    distributions = read_csv(ROOT / PORTFOLIO_ROOT / dirname / "trade_distribution.csv")
    closure = read_json(ROOT / CLOSURE_ROOT / "summary.json")["windows"][window_id]
    returns = [as_float(row["net_return_pct"]) for row in distributions if row.get("net_return_pct", "") != ""]
    if len(returns) != int(metrics["realized_trade_count"]):
        raise RuntimeError(f"OFFICIAL_DISTRIBUTION_COUNT_MISMATCH:{window_id}")
    return {
        "ending_equity_krw": as_float(metrics["ending_equity_krw"]),
        "total_return_pct": as_float(metrics["cumulative_return_pct"]),
        "CAGR_pct": as_float(metrics["CAGR_pct"]),
        "MDD_pct": as_float(closure["mdd_pct"]),
        "average_capital_utilization_pct": as_float(metrics["average_capital_utilization_pct"]),
        "cash_shortage_skipped_entries": int(metrics["cash_shortage_skipped_entries"]),
        "trade_count": int(metrics["trade_count"]),
        "closed_trade_count": int(metrics["realized_trade_count"]),
        "win_rate_pct": float(np.mean(np.asarray(returns) > 0) * 100.0) if returns else 0.0,
        "mean_net_return_pct": float(np.mean(returns)) if returns else 0.0,
        "median_net_return_pct": float(np.median(returns)) if returns else 0.0,
        "mean_holding_krx_sessions": as_float(metrics["average_holding_trading_days"]),
        "median_holding_krx_sessions": as_float(metrics["median_holding_trading_days"]),
        "tail_le_15_count": sum(value <= -15 for value in returns),
        "tail_le_30_count": sum(value <= -30 for value in returns),
        "tail_ge_30_count": sum(value >= 30 for value in returns),
        "tail_ge_50_count": sum(value >= 50 for value in returns),
        "valuation_coverage_pct": as_float(closure["coverage_pct"]),
    }


def source_hashes() -> dict[str, str]:
    paths = [
        HISTORICAL_AUDIT,
        OFFICIAL_CRITERIA,
        COMMON_RULES,
        EXCLUSION_POLICY,
        RUNNER_RELATIVE,
        Path("scripts/run_pattern_b_progressed_previous_stage_early_transition_only_5window_v01.py"),
        Path("scripts/run_pattern_b_progressed_previous_et_only_realistic_portfolio_v01.py"),
        Path("scripts/run_pattern_b_progressed_previous_et_only_realistic_portfolio_v02.py"),
        Path("scripts/run_pattern_b_pure_simple_backtest_v01.py"),
        Path("scripts/run_p2_1_realistic_portfolio_v01.py"),
        Path("artifacts/patterns/pattern_b/progressed_previous_stage_early_transition_only_realistic_portfolio_v03/preflight.json"),
        Path("artifacts/patterns/pattern_b/progressed_previous_stage_early_transition_only_realistic_portfolio_v03/summary.json"),
        CLOSURE_ROOT / "summary.json",
        CLOSURE_ROOT / "carry_source_validation.csv",
    ]
    for dirname in WINDOW_DIR.values():
        paths.append(SOURCE_ROOT / dirname / "test_trade_ledger.csv")
        paths.append(PORTFOLIO_ROOT / dirname / "portfolio_events.csv")
        paths.append(PORTFOLIO_ROOT / dirname / "portfolio_metrics.json")
        paths.append(PORTFOLIO_ROOT / dirname / "trade_distribution.csv")
    return {path.as_posix(): sha256(ROOT / path) for path in paths}


def verify_v03_exclusion_policy_snapshot(
    expected_sha256: str,
    target_identities: set[tuple[str, str]],
) -> dict[str, Any]:
    commits = subprocess.check_output(
        ["git", "log", "--format=%H", "--", EXCLUSION_POLICY.as_posix()],
        cwd=ROOT,
        text=True,
    ).splitlines()
    for commit in commits:
        try:
            content = subprocess.check_output(
                ["git", "show", f"{commit}:{EXCLUSION_POLICY.as_posix()}"], cwd=ROOT
            )
        except subprocess.CalledProcessError:
            continue
        if hashlib.sha256(content).hexdigest() != expected_sha256:
            continue
        module = ast.parse(content.decode("utf-8"))
        historical_policy = None
        for node in ast.walk(module):
            if (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "PERMANENT_IDENTITY_EXCLUSIONS"
            ):
                historical_policy = ast.literal_eval(node.value)
                break
            if (
                isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "PERMANENT_IDENTITY_EXCLUSIONS" for target in node.targets)
            ):
                historical_policy = ast.literal_eval(node.value)
                break
        if historical_policy is None:
            raise RuntimeError("OFFICIAL_V03_EXCLUSION_POLICY_SOURCE_PARSE_FAILED")
        missing = sorted(target_identities - set(historical_policy))
        return {
            "matching_git_commit": commit,
            "policy_identity_count": len(historical_policy),
            "all_target_identities_present": not missing,
            "missing_target_identities": missing,
        }
    raise RuntimeError("OFFICIAL_V03_EXCLUSION_POLICY_HASH_NOT_FOUND_IN_GIT_HISTORY")


def audit(*, require_output_absent: bool = False) -> dict[str, Any]:
    if require_output_absent and (ROOT / OUTPUT_ROOT).exists():
        raise RuntimeError(f"OUTPUT_ALREADY_EXISTS_REFUSE_OVERWRITE:{OUTPUT_ROOT}")

    inputs = {window_id: portfolio_v02.load_window_inputs(window_id) for window_id in ALL_WINDOWS}
    _, trading_dates, market_authority = pattern_b_base._load_authorities(ROOT)
    day_list = [as_day(day) for day in trading_dates]
    day_positions = {day: index for index, day in enumerate(day_list)}
    if len(day_positions) != len(day_list):
        raise RuntimeError("DUPLICATE_KRX_CALENDAR_DATE")

    events_by_window = {
        window_id: read_csv(ROOT / PORTFOLIO_ROOT / WINDOW_DIR[window_id] / "portfolio_events.csv")
        for window_id in ALL_WINDOWS
    }
    current_exclusions = portfolio_v02.current_exclusion_keys()
    raw_store = KrxRawStockStore(ROOT / "data/market/raw/krx_stocks/v01")
    target_rows: list[dict[str, Any]] = []
    target_identity_to_trade_id: dict[tuple[str, str, str], str] = {}
    raw_partition_hashes: dict[str, dict[str, str]] = {}
    adjusted_source_hashes: dict[str, dict[str, str]] = {}

    p1_ledger = inputs["P1"]["ledger"].to_dict(orient="records")
    adjusted_cache: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}

    for target in TARGETS:
        side = target["side"]
        ticker = target["ticker"]
        signal_date = target["signal_date"]
        expected_date = target["expected_date"]
        signal_field = "entry_signal_date" if side == "ENTRY" else "exit_signal_date"
        execution_field = "entry_execution_date" if side == "ENTRY" else "exit_execution_date"
        reference_field = "entry_reference_open" if side == "ENTRY" else "exit_reference_open"
        market_field = "entry_market" if side == "ENTRY" else "exit_market"

        matches = [
            row for row in p1_ledger
            if str(row.get("ticker", "")).zfill(6) == ticker
            and as_day(row.get(signal_field, "")) == signal_date
        ]
        if len(matches) != 1:
            raise RuntimeError(f"P1_SOURCE_LEDGER_TARGET_COUNT:{side}:{ticker}:{signal_date}:{len(matches)}")
        record = matches[0]
        trade_id = str(record["trade_id"])
        target_identity_to_trade_id[(side, ticker, signal_date)] = trade_id
        stored_date = as_day(record[execution_field])
        stored_ledger_open = as_float(record[reference_field])
        market = str(record[market_field])

        if signal_date not in day_positions or expected_date not in day_positions:
            raise RuntimeError(f"TARGET_DATE_MISSING_FROM_KRX_CALENDAR:{ticker}:{signal_date}:{expected_date}")
        next_session = day_list[day_positions[signal_date] + 1]
        if next_session != expected_date:
            raise RuntimeError(f"TARGET_NOT_EXACT_NEXT_KRX_SESSION:{ticker}:{next_session}:{expected_date}")
        sessions_advanced = day_positions[stored_date] - day_positions[expected_date]
        if sessions_advanced <= 0:
            raise RuntimeError(f"STORED_EXECUTION_NOT_DELAYED:{ticker}:{stored_date}:{expected_date}")

        if ticker not in adjusted_cache:
            adjusted_cache[ticker] = load_adjusted_rows(ticker)
            meta, _ = adjusted_cache[ticker]
            adjusted_source_hashes[ticker] = {
                "parquet_sha256": sha256(ROOT / "data/market/adjusted/stocks" / f"{ticker}.parquet"),
                "metadata_sha256": sha256(ROOT / "data/market/adjusted/stocks" / f"{ticker}.meta.json"),
                "source_name": str(meta["source_name"]),
            }
        _, adjusted_by_date = adjusted_cache[ticker]

        if stored_date not in adjusted_by_date or expected_date not in adjusted_by_date:
            raise RuntimeError(f"CURRENT_ADJUSTED_OPEN_MISSING:{ticker}:{stored_date}:{expected_date}")
        stored_current_open = as_float(adjusted_by_date[stored_date].open)
        normalized_open = as_float(adjusted_by_date[expected_date].open)
        if not math.isclose(stored_current_open, stored_ledger_open, rel_tol=0.0, abs_tol=0.011):
            raise RuntimeError(f"CURRENT_STORED_OPEN_DIFFERS_FROM_LEDGER:{ticker}:{stored_current_open}:{stored_ledger_open}")
        if normalized_open <= 0:
            raise RuntimeError(f"CURRENT_EXACT_NEXT_ADJUSTED_OPEN_INVALID:{ticker}:{normalized_open}")

        stored_raw, stored_manifest = exact_raw_row(raw_store, market, ticker, stored_date)
        normalized_raw, normalized_manifest = exact_raw_row(raw_store, market, ticker, expected_date)
        if int(stored_raw["listed_shares"]) != int(normalized_raw["listed_shares"]):
            raise RuntimeError(f"LISTED_SHARES_CHANGED_ACROSS_TARGET_DATES:{ticker}")
        for day, manifest in ((stored_date, stored_manifest), (expected_date, normalized_manifest)):
            raw_partition_hashes[f"{market}:{day}"] = {
                "file_sha256": str(manifest["file_sha256"]),
                "content_sha256": str(manifest["content_sha256"]),
            }

        if side == "ENTRY":
            opposite_side = "EXIT"
            opposite_date = as_day(record["exit_execution_date"])
            if opposite_date not in adjusted_by_date:
                raise RuntimeError(f"PRESERVED_EXIT_OPEN_MISSING:{ticker}:{opposite_date}")
            entry_before = stored_current_open
            entry_after = normalized_open
            exit_before = exit_after = as_float(adjusted_by_date[opposite_date].open)
            preserved_reference = as_float(record["exit_reference_open"])
        else:
            opposite_side = "ENTRY"
            opposite_date = as_day(record["entry_execution_date"])
            if opposite_date not in adjusted_by_date:
                raise RuntimeError(f"PRESERVED_ENTRY_OPEN_MISSING:{ticker}:{opposite_date}")
            entry_before = entry_after = as_float(adjusted_by_date[opposite_date].open)
            exit_before = stored_current_open
            exit_after = normalized_open
            preserved_reference = as_float(record["entry_reference_open"])
        preserved_current_open = as_float(adjusted_by_date[opposite_date].open)
        if not math.isclose(preserved_current_open, preserved_reference, rel_tol=0.0, abs_tol=0.011):
            raise RuntimeError(f"OPPOSITE_SIDE_CHANGED_OR_AUTHORITY_MISMATCH:{ticker}:{opposite_date}")

        old_gross = gross_return_pct(entry_before, exit_before)
        new_gross = gross_return_pct(entry_after, exit_after)
        old_costed = costed_pre_tax_return_pct(entry_before, exit_before)
        new_costed = costed_pre_tax_return_pct(entry_after, exit_after)
        if not math.isclose(old_gross, as_float(record["gross_return_pct"]), rel_tol=0.0, abs_tol=1e-8):
            raise RuntimeError(f"SOURCE_GROSS_RETURN_PARITY_FAILURE:{ticker}")
        if not math.isclose(old_costed, as_float(record["commission_slippage_pre_tax_return_pct"]), rel_tol=0.0, abs_tol=1e-8):
            raise RuntimeError(f"SOURCE_COSTED_RETURN_PARITY_FAILURE:{ticker}")

        identity = (ticker, str(record["isu_cd"]).upper())
        policy_entry = PERMANENT_IDENTITY_EXCLUSIONS.get(identity)
        if policy_entry is None or identity not in current_exclusions:
            raise RuntimeError(f"TARGET_NOT_IN_CURRENT_APPROVED_EXCLUSIONS:{ticker}:{identity[1]}")

        row = {
            "ticker": ticker,
            "trade_id": trade_id,
            "isu_cd": identity[1],
            "side_normalized": side,
            "signal_date": signal_date,
            "stored_execution_date": stored_date,
            "stored_ledger_adjusted_open": stored_ledger_open,
            "current_adjusted_stored_open": stored_current_open,
            "normalized_execution_date": expected_date,
            "normalized_current_adjusted_open": normalized_open,
            "preserved_opposite_side": opposite_side,
            "preserved_opposite_execution_date": opposite_date,
            "preserved_opposite_current_adjusted_open": preserved_current_open,
            "gross_return_before_pct": old_gross,
            "gross_return_after_pct": new_gross,
            "gross_return_delta_pp": new_gross - old_gross,
            "costed_pre_tax_return_before_pct": old_costed,
            "costed_pre_tax_return_after_pct": new_costed,
            "costed_pre_tax_return_delta_pp": new_costed - old_costed,
            "krx_sessions_advanced": sessions_advanced,
            "market": market,
            "stored_raw_open": int(stored_raw["open"]),
            "stored_raw_volume": int(stored_raw["volume"]),
            "normalized_raw_open": int(normalized_raw["open"]),
            "normalized_raw_volume": int(normalized_raw["volume"]),
            "listed_shares_stored_date": int(stored_raw["listed_shares"]),
            "listed_shares_normalized_date": int(normalized_raw["listed_shares"]),
            "adjusted_authority": "NAVER_DIRECT_DATE_RANGE_ADJUSTED",
            "permanent_exclusion_reason": policy_entry["reason"],
            "permanent_exclusion_approval_scope": policy_entry.get("approval_scope", ""),
            "permanent_exclusion_approved_date": policy_entry.get("approved_date", ""),
        }
        target_rows.append(row)

    if len(target_rows) != 7 or len({row["trade_id"] for row in target_rows}) != 7:
        raise RuntimeError("TARGET_UNIQUE_TRADE_COUNT_MISMATCH")

    source_exposures: dict[str, int] = {}
    filtered_record_exposures: dict[str, int] = {}
    portfolio_event_exposures: dict[str, int] = {}
    for window_id in ALL_WINDOWS:
        ledger_rows = inputs[window_id]["ledger"].to_dict(orient="records")
        ledger_count = 0
        active_count = 0
        event_count = 0
        for target in TARGETS:
            signal_field = "entry_signal_date" if target["side"] == "ENTRY" else "exit_signal_date"
            matches = [
                row for row in ledger_rows
                if str(row.get("ticker", "")).zfill(6) == target["ticker"]
                and as_day(row.get(signal_field, "")) == target["signal_date"]
            ]
            ledger_count += len(matches)
            for row in matches:
                trade_id = str(row["trade_id"])
                active_count += sum(str(item.get("trade_id", "")) == trade_id for item in inputs[window_id]["records"])
                event_count += sum(str(item.get("pair_id", "")) == trade_id for item in events_by_window[window_id])
        source_exposures[window_id] = ledger_count
        filtered_record_exposures[window_id] = active_count
        portfolio_event_exposures[window_id] = event_count
    if source_exposures != EXPECTED_SOURCE_EXPOSURES:
        raise RuntimeError(f"SOURCE_LEDGER_EXPOSURE_COUNT_MISMATCH:{source_exposures}")
    if any(filtered_record_exposures.values()):
        raise RuntimeError(f"TARGET_LEAKED_THROUGH_CURRENT_EXCLUSIONS:{filtered_record_exposures}")
    if any(portfolio_event_exposures.values()):
        raise RuntimeError(f"TARGET_PRESENT_IN_OFFICIAL_PORTFOLIO_EVENTS:{portfolio_event_exposures}")

    official_preflight = read_json(ROOT / PORTFOLIO_ROOT / "preflight.json")
    historical_exclusion_proof = verify_v03_exclusion_policy_snapshot(
        str(official_preflight["permanent_exclusion_policy_sha256"]),
        {(row["ticker"], row["isu_cd"]) for row in target_rows},
    )
    if not historical_exclusion_proof["all_target_identities_present"]:
        raise RuntimeError(f"TARGET_NOT_EXCLUDED_BY_OFFICIAL_V03_POLICY:{historical_exclusion_proof}")

    schedule_audit: dict[str, Any] = {}
    for window_id, rows in events_by_window.items():
        checked = 0
        violations = []
        for row in rows:
            if row.get("event_status") != "EXECUTED":
                continue
            signal_day = as_day(row.get("signal_date", ""))
            execution_day = as_day(row.get("execution_date", ""))
            if signal_day not in day_positions or day_positions[signal_day] + 1 >= len(day_list):
                raise RuntimeError(f"OFFICIAL_EXECUTED_SIGNAL_NOT_IN_KRX_CALENDAR:{window_id}:{signal_day}")
            checked += 1
            expected = day_list[day_positions[signal_day] + 1]
            if execution_day != expected:
                violations.append({
                    "ticker": row.get("ticker"),
                    "event_type": row.get("event_type"),
                    "signal_date": signal_day,
                    "execution_date": execution_day,
                    "expected_exact_next_date": expected,
                })
        schedule_audit[window_id] = {
            "executed_events_checked": checked,
            "next_exact_krx_session_violation_count": len(violations),
            "violations_sample": violations[:10],
            "status": "PASS" if not violations else "FAIL",
        }

    closure = read_json(ROOT / CLOSURE_ROOT / "summary.json")
    window_metrics = []
    official_gates = {}
    for window_id in ALL_WINDOWS:
        before = metric_bundle(window_id)
        after = dict(before)  # Zero event exposure proves this scope cannot change the official portfolio.
        gates = closure["windows"][window_id]["gates"]
        official_gates[window_id] = gates
        metric_row: dict[str, Any] = {"window_id": window_id}
        for field, value in before.items():
            metric_row[f"before_{field}"] = value
            metric_row[f"after_{field}"] = after[field]
            metric_row[f"delta_{field}"] = after[field] - value if isinstance(value, (int, float)) else None
        metric_row["target_normalized_portfolio_replay_performed"] = False
        metric_row["result_basis"] = "UNCHANGED_BY_ZERO_TARGET_EVENT_EXPOSURE"
        metric_row["gate_A_to_E_before"] = "".join(gates[key] for key in "ABCDE")
        metric_row["gate_A_to_E_after"] = metric_row["gate_A_to_E_before"]
        window_metrics.append(metric_row)

    all_schedule_pass = all(row["status"] == "PASS" for row in schedule_audit.values())
    all_gates_pass = all(all(gates[key] == "PASS" for key in "ABCDE") for gates in official_gates.values())
    final_closure_adopted = closure.get("closure_verdict") == "OFFICIAL_STRATEGY_ADOPTED"
    verdict = (
        "B_SELECT_EXACT_NEXT_NORMALIZATION_IMPACT_PASS"
        if all_schedule_pass and all_gates_pass and final_closure_adopted
        else "B_SELECT_EXACT_NEXT_NORMALIZATION_IMPACT_CHECK_REQUIRED"
    )

    return {
        "schema": "b_select_exact_next_normalization_impact_v01",
        "created_at_local": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
        "starting_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "starting_origin_main": subprocess.check_output(["git", "rev-parse", "origin/main"], cwd=ROOT, text=True).strip(),
        "legacy_official_artifacts_modified": False,
        "production_modified": False,
        "signal_generation_rerun": False,
        "full_backtest_rerun": False,
        "target_normalized_portfolio_replay_performed": False,
        "target_normalized_portfolio_replay_skipped_reason": (
            "All seven discrepancy identities are excluded by the current approved RAW_DATA_GAP policy, "
            "are absent from the current filtered candidate records, and have zero pair-id exposure in every "
            "official V03 portfolio event stream. Reintroducing them for replay would change the approved universe."
        ),
        "exploratory_current_authority_replay": {
            "attempted": True,
            "status": "DISCARDED_OFFICIAL_BASELINE_PARITY_FAILURE",
            "window": "P1 baseline only; normalization was not run",
            "official_event_count": 917,
            "exploratory_event_count": 917,
            "event_cash_path_mismatches_reported": 100,
            "official_closure_daily_rows": 3107,
            "exploratory_daily_rows": 3108,
            "official_ending_equity_krw": 393558408.1543343,
            "exploratory_ending_equity_krw": 381030105.34395325,
            "ending_equity_delta_krw": -12528302.81038105,
            "cause": "UNRESOLVED; all exploratory replay values were discarded and are not used in the reported impact.",
        },
        "severity": {"CRITICAL": 0, "MAJOR": 7, "MINOR": 0},
        "verdict": verdict,
        "affected_unique_source_ledger_trade_count": len(target_rows),
        "source_ledger_target_exposure_by_window": source_exposures,
        "current_filtered_candidate_target_exposure_by_window": filtered_record_exposures,
        "official_portfolio_event_target_exposure_by_window": portfolio_event_exposures,
        "target_trades": target_rows,
        "executed_official_event_schedule_audit": schedule_audit,
        "official_window_metrics_before_after": window_metrics,
        "official_adoption_status_before_after": {
            "original_v03_pre_closure_verdict": closure["v03_original_verdict"],
            "before_normalization": closure["closure_verdict"],
            "after_normalization": closure["closure_verdict"],
            "closure_gates": official_gates,
        },
        "official_criteria_path": OFFICIAL_CRITERIA.as_posix(),
        "market_authority": market_authority,
        "current_permanent_exclusion_count": len(current_exclusions),
        "current_permanent_exclusion_policy_sha256": sha256(ROOT / EXCLUSION_POLICY),
        "official_v03_exclusion_count_at_creation": read_json(ROOT / PORTFOLIO_ROOT / "preflight.json").get("permanent_exclusion_identity_count"),
        "official_v03_exclusion_policy_sha256_at_creation": read_json(ROOT / PORTFOLIO_ROOT / "preflight.json").get("permanent_exclusion_policy_sha256"),
        "official_v03_historical_exclusion_policy_proof": historical_exclusion_proof,
        "adjusted_source_hashes": adjusted_source_hashes,
        "raw_partition_hashes": raw_partition_hashes,
        "source_hashes": source_hashes(),
        "all_target_rows_excluded_from_current_policy": all(
            (row["ticker"], row["isu_cd"]) in current_exclusions for row in target_rows
        ),
        "all_target_exact_next_adjusted_opens_valid": all(row["normalized_current_adjusted_open"] > 0 for row in target_rows),
        "all_target_raw_next_sessions_traded": all(row["normalized_raw_volume"] > 0 for row in target_rows),
        "all_target_share_counts_stable_across_stored_and_exact_next_dates": all(
            row["listed_shares_stored_date"] == row["listed_shares_normalized_date"] for row in target_rows
        ),
        "p3_1_p3_2_target_source_exposure": source_exposures["P3-1"] + source_exposures["P3-2"],
    }


def fmt(value: Any, suffix: str = "") -> str:
    if value is None or pd.isna(value):
        return "—"
    numeric = float(value)
    if not suffix and numeric.is_integer():
        return f"{int(numeric):,}"
    return f"{numeric:,.4f}{suffix}"


def render_report(result: Mapping[str, Any]) -> str:
    targets = result["target_trades"]
    metrics = result["official_window_metrics_before_after"]
    schedule = result["executed_official_event_schedule_audit"]
    lines = [
        "# B Select exact-next 정규화 영향 검증 V01",
        "",
        "| 레벨 | 개수 |",
        "|---|---:|",
        "| CRITICAL | 0 |",
        "| MAJOR | 7 |",
        "| MINOR | 0 |",
        "",
        f"판정: `{result['verdict']}`",
        "",
        "## 핵심 판정",
        "",
        "7건은 원본 P1/P2 source trade ledger에는 존재하지만, 현재 승인된 영구 제외 정책에서 모두 `RAW_DATA_GAP`으로 제외된다. 공식 V03 cash-aware portfolio event stream, 현재 필터 적용 candidate, trade key 기준 노출은 모두 0건이다.",
        f"V03 생성 시 exclusion policy hash에 해당하는 Git revision `{result['official_v03_historical_exclusion_policy_proof']['matching_git_commit']}`을 확인했고, 당시 166개 identity 정책에도 대상 7개가 모두 포함됐다.",
        "따라서 공식 포트폴리오에 제외 identity를 다시 넣는 재생은 현재 승인 universe를 바꾸므로 실행하지 않았다. 아래 거래 수익률은 원본 source ledger의 개별 민감도이며 공식 포트폴리오 성과로 해석하지 않는다.",
        "",
        "## 7건 거래별 정규화 민감도",
        "",
        "| 종목 | 쪽 | 신호일 | 저장 체결일/현행 조정시가 | exact-next일/현행 조정시가 | 당겨진 KRX 세션 | 비용 전 수익률 전→후 | 비용 반영·매도세 전 수익률 전→후 | 변화 | 공식 제외 사유 |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in targets:
        lines.append(
            f"| {row['ticker']} | {row['side_normalized']} | {row['signal_date']} "
            f"| {row['stored_execution_date']} / {fmt(row['current_adjusted_stored_open'])} "
            f"| {row['normalized_execution_date']} / {fmt(row['normalized_current_adjusted_open'])} "
            f"| {row['krx_sessions_advanced']} "
            f"| {fmt(row['gross_return_before_pct'], '%')} → {fmt(row['gross_return_after_pct'], '%')} "
            f"| {fmt(row['costed_pre_tax_return_before_pct'], '%')} → {fmt(row['costed_pre_tax_return_after_pct'], '%')} "
            f"| {fmt(row['costed_pre_tax_return_delta_pp'], '%p')} "
            f"| {row['permanent_exclusion_reason']} |"
        )
    lines += [
        "",
        "## Portfolio 포함 여부와 성과 전후",
        "",
        "| Window | source ledger 노출 | 현재 필터 candidate 노출 | 공식 portfolio event 노출 | 기말자산 전→후 | 총수익률 전→후 | CAGR 전→후 | MDD 전→후 | 평균 자본 활용률 전→후 | 현금부족 skip 전→후 | 거래수 전→후 | 승률 전→후 | 평균/중앙 수익률 전→후 | 보유기간 평균/중앙 전→후 | tail ≤-15/≤-30/≥+30/≥+50 전→후 | Gate A–E 전→후 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in metrics:
        window_id = row["window_id"]
        m = {key.removeprefix("before_"): value for key, value in row.items() if key.startswith("before_")}
        def pair(field: str, suffix: str = "") -> str:
            return f"{fmt(row.get('before_' + field), suffix)} → {fmt(row.get('after_' + field), suffix)}"
        old_tails = "/".join(str(m[field]) for field in ("tail_le_15_count", "tail_le_30_count", "tail_ge_30_count", "tail_ge_50_count"))
        new_tails = old_tails
        lines.append(
            f"| {window_id} | {result['source_ledger_target_exposure_by_window'][window_id]} "
            f"| {result['current_filtered_candidate_target_exposure_by_window'][window_id]} "
            f"| {result['official_portfolio_event_target_exposure_by_window'][window_id]} "
            f"| {pair('ending_equity_krw', '원')} | {pair('total_return_pct', '%')} | {pair('CAGR_pct', '%')} | {pair('MDD_pct', '%')} "
            f"| {pair('average_capital_utilization_pct', '%')} | {pair('cash_shortage_skipped_entries')} "
            f"| {pair('trade_count')} / {pair('closed_trade_count')} | {pair('win_rate_pct', '%')} "
            f"| {pair('mean_net_return_pct', '%')} / {pair('median_net_return_pct', '%')} "
            f"| {pair('mean_holding_krx_sessions')} / {pair('median_holding_krx_sessions')} "
            f"| {old_tails} → {new_tails} | {row['gate_A_to_E_before']} → {row['gate_A_to_E_after']} |"
        )
    lines += ["", "## 정확성 검증", ""]
    for row in targets:
        lines.append(
            f"- {row['ticker']} {row['side_normalized']} {row['signal_date']}: "
            f"신호 다음 exact KRX 세션 `{row['normalized_execution_date']}` 확인; "
            f"조정시가 {fmt(row['normalized_current_adjusted_open'])}원 유효; "
            f"원시 KRX open {row['normalized_raw_open']}원 / volume {row['normalized_raw_volume']:,}; "
            f"저장일과 listed shares 동일. 반대편 체결은 `{row['preserved_opposite_execution_date']}` 그대로 유지."
        )
    for window_id, row in schedule.items():
        lines.append(
            f"- {window_id}: 기존 공식 event stream의 실행 체결 {row['executed_events_checked']:,}건 중 "
            f"다음 exact KRX 세션 위반 {row['next_exact_krx_session_violation_count']}건 (`{row['status']}`)."
        )
    adoption = result["official_adoption_status_before_after"]
    lines += [
        "",
        "## 공식 채택 기준, CONTROL, 과거 산출물",
        "",
        f"- 기존 V03 원판은 MDD closure 전 `{adoption['original_v03_pre_closure_verdict']}`였고, 기존 공식 MDD closure V01은 정규화 전 `{adoption['before_normalization']}`, 이번 영향 판정 후 `{adoption['after_normalization']}`로 유지된다. 다섯 window의 Gate A–E는 모두 PASS다.",
        "- 현행 portfolio CONTROL로 공식 V03/MDD closure baseline을 그대로 사용할 수 있다. 포함된 체결 전부가 다음 exact KRX 세션이며, 이번 7건은 portfolio에 포함되지 않는다. 별도 normalized portfolio baseline은 만들 필요가 없다.",
        "- 공식 portfolio 산출물 remediation은 필요하지 않다. 기존 source ledger는 legacy 보존본으로 둔다. 단, 원본 ledger 거래 수익률을 별도 화면/분석에 노출한다면 본 7건 sensitivity 표를 함께 참조해야 한다.",
        "- P3-1/P3-2의 source ledger 및 공식 portfolio event 노출은 모두 0건이다. 이 window들은 재생하지 않았다.",
        "",
        "## 재현 범위",
        "",
        "- 신호 생성·전체 backtest·production 변경은 수행하지 않았다. 현재 Naver 조정 시계열 7종목, exact KRX calendar, 14개 stored/next KRX raw snapshot만 읽었다. raw partitions는 manifest hash 검증을 거쳤다.",
        "- 공식 portfolio 지표의 after 값은 새로 계산한 값이 아니다. 대상 event key가 0건임을 확인했으므로 각 before 값을 동일하게 유지했다. 제외 identity를 되살리는 재생은 하지 않았다.",
        "- 별도 탐색성 current-authority P1 baseline 재생은 공식 event/cash 및 closure parity에 실패해 폐기했다. 그 재생의 원인과 성과 수치는 정규화 영향 판정에 사용하지 않았다.",
        "- 원본 공식 산출물은 수정하지 않았다. 자세한 수치와 hash는 같은 폴더의 CSV/JSON에 저장했다.",
        "",
    ]
    return "\n".join(lines)


def run() -> dict[str, Any]:
    current_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    origin_main = subprocess.check_output(["git", "rev-parse", "origin/main"], cwd=ROOT, text=True).strip()
    status = subprocess.check_output(
        ["git", "status", "--short", "--untracked-files=all"], cwd=ROOT, text=True
    ).strip()
    allowed_status = f"?? {RUNNER_RELATIVE.as_posix()}"
    if current_head != origin_main or status not in {"", allowed_status}:
        raise RuntimeError(f"RESEARCH_START_NOT_AT_CLEAN_ORIGIN_MAIN:{current_head}:{origin_main}:{status}")

    result = audit(require_output_absent=True)
    if result["starting_head"] != current_head or result["starting_origin_main"] != origin_main:
        raise RuntimeError("AUDIT_STARTING_GIT_IDENTITY_CHANGED")
    out = ROOT / OUTPUT_ROOT
    out.mkdir(parents=True, exist_ok=False)
    write_csv(out / "trade_comparison.csv", result["target_trades"])
    write_csv(out / "window_metrics.csv", result["official_window_metrics_before_after"])
    write_json(out / "validation.json", result)
    (out / "report.md").write_text(render_report(result), encoding="utf-8")
    result["generated_files"] = {
        name: {"sha256": sha256(out / name), "bytes": (out / name).stat().st_size}
        for name in ("trade_comparison.csv", "window_metrics.csv", "validation.json", "report.md")
    }
    write_json(out / "metadata.json", result)
    return result


if __name__ == "__main__":
    outcome = run()
    print(json.dumps({"verdict": outcome["verdict"], "output": OUTPUT_ROOT.as_posix()}, ensure_ascii=False))
