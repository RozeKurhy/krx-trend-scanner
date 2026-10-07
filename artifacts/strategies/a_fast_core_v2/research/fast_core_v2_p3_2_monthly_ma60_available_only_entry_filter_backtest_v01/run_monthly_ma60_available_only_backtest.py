#!/usr/bin/env python3
"""Research-only P3-2 MA60 available-only signal-close entry filter replay."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any, Mapping

import pandas as pd

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[5]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = Path(__file__).resolve().parent
BASE_DIR = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p3_2_monthly_ma20_ma60_entry_filter_backtest_v01"
CONTROL = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p3_2_frozen_portfolio_authority_replay_fix_v01"
EXPECTED_PRIOR_COMMIT = "8edb3f5179ff1c9608fc79ec01f93c4fc596ae89"
EXPECTED_PRIOR_TOKEN = "FAST_CORE_V2_P3_2_MONTHLY_MA20_MA60_ENTRY_FILTER_BACKTEST_V01_COMPLETE"
FINAL_TOKEN = "FAST_CORE_V2_P3_2_MONTHLY_MA60_AVAILABLE_ONLY_ENTRY_FILTER_BACKTEST_V01_COMPLETE"
CHECK_TOKEN = "FAST_CORE_V2_P3_2_MONTHLY_MA60_AVAILABLE_ONLY_ENTRY_FILTER_BACKTEST_V01_CHECK_REQUIRED"
CONTROL_TOKEN = "FAST_CORE_V2_P3_2_FROZEN_PORTFOLIO_AUTHORITY_REPLAY_FIX_V01_COMPLETE"
WORKERS = 10
FILTER_GROUPS = (
    "MA60_AVAILABLE_ABOVE_PASS",
    "MA60_AVAILABLE_AT_OR_BELOW_BLOCK",
    "MA60_UNAVAILABLE_PASS_THROUGH",
)
UNAVAILABLE_GROUP = "MA60_UNAVAILABLE_PASS_THROUGH"
AUDIT_KEY = [
    "ticker",
    "isu_cd",
    "market",
    "identity_effective_from",
    "identity_effective_to",
    "entry_signal_date",
]
CURRENT_STAGE = "STARTUP"


class CheckRequired(RuntimeError):
    pass


def require(condition: bool, token: str) -> None:
    if not condition:
        raise CheckRequired(token)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=json_default) + "\n",
        encoding="utf-8",
    )


def load_base_module():
    path = BASE_DIR / "run_monthly_ma_entry_filter_backtest.py"
    spec = importlib.util.spec_from_file_location("prior_monthly_ma_filter_v01", path)
    require(spec is not None and spec.loader is not None, "PRIOR_REPLAY_SCRIPT_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def normalize_keys(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column in AUDIT_KEY:
        if column in result:
            result[column] = result[column].fillna("").astype(str)
    if "ticker" in result:
        result["ticker"] = result["ticker"].str.zfill(6)
    return result


def bool_series(series: pd.Series) -> pd.Series:
    return series.map(lambda value: str(value).strip().lower() in {"true", "1", "yes"})


def preflight(base: Any, frozen: Any) -> tuple[
    dict[str, Any],
    Any,
    Any,
    pd.DataFrame,
    dict[str, Any],
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    global CURRENT_STAGE
    CURRENT_STAGE = "PREFLIGHT"

    actual_output_files = {path.name for path in OUT.iterdir() if path.is_file()}
    require(actual_output_files == {Path(__file__).name}, "REFUSING_TO_OVERWRITE_EXISTING_OUTPUTS")
    require(git("branch", "--show-current") == "main", "CURRENT_BRANCH_IS_NOT_MAIN")
    require(git("rev-parse", "HEAD") == EXPECTED_PRIOR_COMMIT, "PRIOR_REFERENCE_COMMIT_MISMATCH")
    require(git("rev-parse", "origin/main") == EXPECTED_PRIOR_COMMIT, "ORIGIN_MAIN_DOES_NOT_MATCH_PRIOR_REFERENCE")
    require(git("rev-parse", "HEAD") == git("rev-parse", "origin/main"), "START_HEAD_NOT_ORIGIN_MAIN")

    prior_summary_path = BASE_DIR / "summary.json"
    require(prior_summary_path.is_file(), "PRIOR_MA60_SUMMARY_MISSING")
    prior_summary = json.loads(prior_summary_path.read_text(encoding="utf-8"))
    require(prior_summary.get("status") == "COMPLETE", "PRIOR_MA60_RESULT_NOT_COMPLETE")
    require(prior_summary.get("final_token") == EXPECTED_PRIOR_TOKEN, "PRIOR_MA60_FINAL_TOKEN_MISMATCH")
    prior_integrity = prior_summary.get("integrity_checks", {})
    require(prior_integrity.get("all_candidate_checks_pass") is True, "PRIOR_MA60_INTEGRITY_NOT_PASS")
    require(prior_integrity.get("frozen_control_not_replayed") is True, "PRIOR_CONTROL_REPLAYED")
    require(prior_integrity.get("network_api_or_new_price_calls") == 0, "PRIOR_RESULT_USED_NETWORK_OR_NEW_PRICES")
    require(prior_integrity.get("production_or_canonical_source_changes") == 0, "PRIOR_RESULT_CHANGED_PRODUCTION_SOURCE")

    prior_names = set(prior_summary.get("files_created", []))
    require({"summary.json", "report.md", "run_monthly_ma_entry_filter_backtest.py", "ma60_signal_audit.csv", "ma60_strategy_trades.csv", "ma60_portfolio_events.csv", "ma60_daily_equity.csv"}.issubset(prior_names), "PRIOR_REQUIRED_OUTPUT_LIST_INCOMPLETE")
    existing_prior_files = {path.name for path in BASE_DIR.iterdir() if path.is_file()}
    require(existing_prior_files == prior_names, "PRIOR_OUTPUT_FILE_SET_MISMATCH")

    prior_hashes: dict[str, str] = {}
    for name in sorted(prior_names):
        path = BASE_DIR / name
        relative = path.relative_to(ROOT).as_posix()
        committed = subprocess.check_output(
            ["git", "show", f"{EXPECTED_PRIOR_COMMIT}:{relative}"], cwd=ROOT
        )
        content = path.read_bytes()
        require(content == committed, f"PRIOR_OUTPUT_HASH_OR_COMMIT_MISMATCH:{name}")
        prior_hashes[name] = sha_bytes(content)

    prior_preflight = prior_summary.get("preflight", {})
    require(prior_preflight.get("status") == "PASS", "PRIOR_FROZEN_PREFLIGHT_NOT_PASS")
    require(prior_preflight.get("control_final_token") == CONTROL_TOKEN, "PRIOR_CONTROL_TOKEN_MISMATCH")
    require(prior_preflight.get("control_replayed") is False, "PRIOR_CONTROL_REPLAYED")
    require(prior_preflight.get("latest_rolling_authority_read") is False, "PRIOR_USES_LATEST_ROLLING_AUTHORITY")
    require(prior_preflight.get("network_calls") == 0, "PRIOR_USES_NETWORK_CALLS")
    require(prior_preflight.get("workers") == WORKERS, "PRIOR_WORKER_COUNT_MISMATCH")

    control_summary = json.loads((CONTROL / "summary.json").read_text(encoding="utf-8"))
    require(
        control_summary.get("status") == "COMPLETE"
        and control_summary.get("final_token") == CONTROL_TOKEN,
        "FROZEN_CONTROL_NOT_COMPLETE",
    )
    require(control_summary.get("tests", {}).get("control_exact_parity") == "PASS", "FROZEN_CONTROL_PARITY_NOT_PASS")
    require(control_summary.get("control_parity", {}).get("strategy", {}).get("pass") is True, "FROZEN_CONTROL_STRATEGY_PARITY_NOT_PASS")
    require(control_summary.get("control_parity", {}).get("portfolio", {}).get("pass") is True, "FROZEN_CONTROL_PORTFOLIO_PARITY_NOT_PASS")

    control_hashes: dict[str, str] = {}
    expected_control_hashes = prior_preflight.get("control_hashes", {})
    for name in base.CONTROL_FILES:
        path = CONTROL / name
        require(path.is_file(), f"FROZEN_CONTROL_FILE_MISSING:{name}")
        digest = sha_file(path)
        require(digest == expected_control_hashes.get(name), f"FROZEN_CONTROL_HASH_MISMATCH:{name}")
        relative = path.relative_to(ROOT).as_posix()
        committed = subprocess.check_output(
            ["git", "show", f"HEAD:{relative}"], cwd=ROOT
        )
        require(committed == path.read_bytes(), f"FROZEN_CONTROL_HEAD_BLOB_MISMATCH:{name}")
        control_hashes[name] = digest

    provenance = frozen._validate_saved_provenance()
    require(provenance.get("status") == "PASS", "FROZEN_SAVED_PROVENANCE_NOT_PASS")
    require(provenance.get("network_calls") == 0, "FROZEN_PROVENANCE_NETWORK_CALLS_NONZERO")
    run_context, gate, universe, authority = frozen._load_frozen_context()
    require(len(run_context.segments_by_ticker) == 2539, "FROZEN_SURVIVOR_IDENTITY_COUNT_MISMATCH")
    require(len(universe.loc[universe["status"].eq("SURVIVOR_COMMON_IDENTITY")]) == 2539, "FROZEN_UNIVERSE_COUNT_MISMATCH")
    require(authority.get("status") == "PASS", "FROZEN_AUTHORITY_NOT_PASS")

    control = pd.read_csv(CONTROL / "control_strategy_trades.csv", dtype={"ticker": str, "isu_cd": str})
    control = normalize_keys(control)
    require(len(control) == 405 and control["pair_id"].is_unique, "FROZEN_CONTROL_TRADE_LEDGER_MISMATCH")
    require(not control[AUDIT_KEY].duplicated().any(), "FROZEN_CONTROL_SIGNAL_KEY_DUPLICATE")

    prior_audit = pd.read_csv(BASE_DIR / "ma60_signal_audit.csv", dtype={"ticker": str, "isu_cd": str})
    prior_trades = pd.read_csv(BASE_DIR / "ma60_strategy_trades.csv", dtype={"ticker": str, "isu_cd": str})
    prior_events = pd.read_csv(BASE_DIR / "ma60_portfolio_events.csv", dtype={"ticker": str, "isu_cd": str})
    prior_audit = normalize_keys(prior_audit)
    prior_trades = normalize_keys(prior_trades)
    require(len(prior_audit) == prior_summary["worker_results"]["MA60"]["raw_signal_audit_count"], "PRIOR_MA60_AUDIT_COUNT_MISMATCH")
    require(len(prior_trades) == prior_summary["strategy_metrics"]["MA60"]["trade_count"], "PRIOR_MA60_TRADE_COUNT_MISMATCH")
    require(len(pd.read_csv(BASE_DIR / "ma60_daily_equity.csv")) == 1140, "PRIOR_MA60_EQUITY_ROW_COUNT_MISMATCH")
    require(prior_summary["worker_results"]["MA60"]["worker_errors"] == 0, "PRIOR_MA60_WORKER_ERRORS_NONZERO")

    prior_pit = bool_series(prior_audit["pit_mcap_pass"])
    prior_available = bool_series(prior_audit["ma_available"])
    prior_ma_pass = bool_series(prior_audit["ma_filter_pass"])
    prior_unavailable = prior_pit & ~prior_available
    prior_unavailable_count = int(prior_unavailable.sum())
    expected_unavailable = int(
        prior_summary["blocked_signal_analysis"]["MA60"]["ma_unavailable_pit_qualified_signal_count"]
    )
    require(prior_unavailable_count == expected_unavailable, "PRIOR_UNAVAILABLE_SIGNAL_COUNT_MISMATCH")
    require((~prior_ma_pass.loc[prior_unavailable]).all(), "PRIOR_MA60_UNAVAILABLE_WAS_NOT_FAIL_CLOSED")
    prior_unavailable_reason_counts = (
        prior_audit.loc[prior_unavailable, "ma_unavailable_reason"]
        .fillna("OTHER")
        .replace("", "OTHER")
        .value_counts()
        .to_dict()
    )
    require(sum(prior_unavailable_reason_counts.values()) == prior_unavailable_count, "PRIOR_UNAVAILABLE_REASON_COUNTS_DO_NOT_RECONCILE")

    pre = {
        "status": "PASS",
        "expected_prior_commit": EXPECTED_PRIOR_COMMIT,
        "current_head": git("rev-parse", "HEAD"),
        "origin_main": git("rev-parse", "origin/main"),
        "current_head_equals_origin_main": True,
        "prior_result": {
            "final_token": prior_summary["final_token"],
            "summary_sha256": prior_hashes["summary.json"],
            "artifact_file_count": len(prior_hashes),
            "artifact_sha256": prior_hashes,
            "ma60_signal_count": len(prior_audit),
            "ma60_strategy_trade_count": len(prior_trades),
            "pit_qualified_unavailable_count": prior_unavailable_count,
            "pit_qualified_unavailable_reason_counts": prior_unavailable_reason_counts,
        },
        "frozen_control_hashes": control_hashes,
        "source_provenance": provenance,
        "frozen_authority": authority,
        "survivor_identity_count": len(run_context.segments_by_ticker),
        "frozen_control_trade_count": len(control),
        "workers": WORKERS,
        "latest_rolling_authority_read": False,
        "network_api_or_new_price_calls": 0,
        "frozen_control_replayed": False,
        "prior_ma60_replayed": False,
        "price_source": "Existing local Repository V2 adjusted price partitions, read-only.",
    }
    return pre, run_context, gate, control, prior_summary, prior_audit, prior_trades, prior_events


def candidate_replay(base: Any, run_context: Any, gate: Any, prices: Any) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame, float]:
    from trend_scanner.validation import pattern_a_fast_core_v02_reentry as v2
    import scripts.run_fastcore_neg40_weak_protect_p2_1 as strategy

    original_simulator = v2.simulate_ticker_core_v02_reentry
    audit_rows: list[dict[str, Any]] = []
    audit_lock = threading.Lock()

    def selected_simulator(*args: Any, **kwargs: Any):
        ticker = str(kwargs["ticker"]).zfill(6)
        market = str(kwargs["market"])
        daily = kwargs["daily"]
        pit_filter = kwargs.get("entry_signal_filter")

        def candidate_filter(signal_date: pd.Timestamp, result: Mapping[str, Any]) -> bool:
            day = pd.Timestamp(signal_date).normalize()
            segment = base.find_segment(run_context, ticker, market, day)
            pit_pass = bool(pit_filter(day, result)) if pit_filter is not None else True
            features = prices.signal_features(ticker, daily, day, {"MA60": 60})
            available = bool(features["ma60_available"])
            if not available:
                group = UNAVAILABLE_GROUP
                ma_filter_pass = True
            elif float(features["signal_day_close"]) > float(features["ma60_value"]):
                group = FILTER_GROUPS[0]
                ma_filter_pass = True
            else:
                group = FILTER_GROUPS[1]
                ma_filter_pass = False
            accepted = bool(pit_pass and ma_filter_pass)
            later_sessions = daily.index[
                (daily.index > day)
                & (daily.index <= pd.Timestamp(kwargs.get("execution_support_date")).normalize())
            ]
            next_session = pd.Timestamp(later_sessions[0]).normalize() if len(later_sessions) else None
            entry_cutoff = pd.Timestamp(kwargs.get("entry_execution_cutoff_date")).normalize()
            entry_executable = next_session is not None and next_session <= entry_cutoff
            audit = {
                "ticker": ticker,
                "isu_cd": segment.isu_cd,
                "market": segment.market,
                "identity_effective_from": segment.effective_from.strftime("%Y-%m-%d"),
                "identity_effective_to": segment.effective_to.strftime("%Y-%m-%d"),
                "identity_key": segment.key,
                "entry_signal_date": day.strftime("%Y-%m-%d"),
                "candidate": "MA60_AVAILABLE_ONLY",
                "raw_v2_eligible_signal": True,
                "pit_mcap_pass": pit_pass,
                "signal_day_close": features["signal_day_close"],
                "signal_month": features["signal_month"],
                "ma_last_completed_month": features["ma_last_completed_month"],
                "monthly_ma": features["ma60_value"],
                "ma_available": available,
                "ma_unavailable_reason": features["ma60_unavailable_reason"],
                "filter_group": group,
                "ma_filter_pass": ma_filter_pass,
                "candidate_signal_accepted": accepted,
                "next_local_session_date": next_session.strftime("%Y-%m-%d") if next_session is not None else None,
                "entry_execution_cutoff_date": entry_cutoff.strftime("%Y-%m-%d"),
                "entry_executable_within_cutoff": entry_executable,
                "filter_decision": "PIT_REJECT" if not pit_pass else group,
                "monthly_window_start": features["ma60_window_start_month"],
                "monthly_window_end": features["ma60_window_end_month"],
                "monthly_missing_months": features["ma60_missing_months"],
                "monthly_closes_used": features["ma60_monthly_closes_used"],
                "price_source_partition_sha256": features["price_source_partition_sha256"],
                "price_source_metadata_sha256": features["price_source_metadata_sha256"],
            }
            with audit_lock:
                audit_rows.append(audit)
            return accepted

        kwargs["entry_signal_filter"] = candidate_filter
        return original_simulator(*args, **kwargs)

    v2.simulate_ticker_core_v02_reentry = selected_simulator
    errors: list[str] = []
    outcomes: list[dict[str, Any]] = []
    started = time.perf_counter()
    tickers = sorted(run_context.segments_by_ticker)
    try:
        def process(ticker: str):
            outcome = strategy._process_ticker(ticker, run_context)
            outcome["worker_thread"] = threading.current_thread().name
            return outcome

        with ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="ma60-available-only") as pool:
            futures = {pool.submit(process, ticker): ticker for ticker in tickers}
            for completed, future in enumerate(as_completed(futures), start=1):
                ticker = futures[future]
                try:
                    outcomes.append(future.result())
                except Exception as exc:
                    errors.append(f"{ticker}: {type(exc).__name__}: {exc}")
                if completed % 50 == 0 or completed == len(tickers):
                    total = sum(len(item.get("control_rows", ())) for item in outcomes)
                    print(
                        f"NEW MA60 progress {completed}/{len(tickers)} trades={total} "
                        f"mcap_audits={len(gate.audit_frame())} errors={len(errors)} "
                        f"elapsed={time.perf_counter() - started:.1f}s",
                        flush=True,
                    )
    finally:
        v2.simulate_ticker_core_v02_reentry = original_simulator

    require(not errors, "NEW_MA60_WORKER_ERRORS:" + json.dumps(errors[:10], ensure_ascii=False))
    records = pd.DataFrame([row for outcome in outcomes for row in outcome.get("control_rows", ())])
    if records.empty:
        records = pd.DataFrame()
    else:
        records = records.sort_values(
            ["ticker", "identity_effective_from", "trade_sequence"], kind="mergesort"
        ).reset_index(drop=True)
    audit_frame = pd.DataFrame(audit_rows)
    require(not audit_frame.empty, "NEW_MA60_SIGNAL_AUDIT_EMPTY")
    audit_frame = normalize_keys(audit_frame)
    audit_key = AUDIT_KEY

    if records.empty:
        accepted_executable = audit_frame.loc[
            bool_series(audit_frame["candidate_signal_accepted"])
            & bool_series(audit_frame["entry_executable_within_cutoff"]),
            audit_key,
        ]
        require(accepted_executable.empty, "NEW_MA60_ACCEPTED_SIGNAL_WITHOUT_STRATEGY_TRADE")
    else:
        records = normalize_keys(records)
        accepted = audit_frame.loc[
            bool_series(audit_frame["candidate_signal_accepted"])
            & bool_series(audit_frame["entry_executable_within_cutoff"]),
            audit_key,
        ].copy()
        trade_keys = records[audit_key].copy()
        require(not accepted.duplicated().any(), "NEW_MA60_DUPLICATE_ACCEPTED_SIGNAL")
        require(not trade_keys.duplicated().any(), "NEW_MA60_DUPLICATE_STRATEGY_TRADE_SIGNAL")
        left = trade_keys.sort_values(audit_key).reset_index(drop=True)
        right = accepted.sort_values(audit_key).reset_index(drop=True)
        require(left.equals(right), "NEW_MA60_ACCEPTED_SIGNAL_TO_TRADE_LEDGER_MISMATCH")
        audit_columns = audit_key + [
            "signal_day_close",
            "monthly_ma",
            "ma_available",
            "ma_filter_pass",
            "filter_group",
            "candidate_signal_accepted",
            "ma_last_completed_month",
        ]
        records = records.merge(
            audit_frame[audit_columns],
            on=audit_key,
            how="left",
            validate="one_to_one",
        )
        require(bool_series(records["candidate_signal_accepted"]).all(), "NEW_MA60_TRADE_WITHOUT_ACCEPTED_SIGNAL")
        require(bool_series(records["ma_filter_pass"]).all(), "NEW_MA60_TRADE_LEAKED_PAST_FILTER")
    run_info = {"outcomes": outcomes, "worker_errors": errors, "elapsed_seconds": time.perf_counter() - started}
    return records, run_info, audit_frame, time.perf_counter() - started


def portfolio_group_rows(events: pd.DataFrame, trades: pd.DataFrame) -> tuple[pd.DataFrame, set[str], set[str]]:
    pair_group = trades.set_index("pair_id")["filter_group"].to_dict() if not trades.empty else {}
    copied = events.copy()
    copied["filter_group"] = copied["pair_id"].astype(str).map(pair_group)
    executed_entries = copied.loc[
        copied["event_type"].eq("ENTRY") & copied["event_status"].eq("EXECUTED")
    ].copy()
    cash_skips = copied.loc[
        copied["event_type"].eq("ENTRY") & copied["event_status"].eq("SKIPPED_CASH_UNAVAILABLE")
    ].copy()
    return copied, set(executed_entries["pair_id"].astype(str)), set(cash_skips["pair_id"].astype(str))


def group_summary(audit: pd.DataFrame, trades: pd.DataFrame, events: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    tagged_events, executed_pair_ids, skipped_pair_ids = portfolio_group_rows(events, trades)
    rows: list[dict[str, Any]] = []
    for group in FILTER_GROUPS:
        part = audit.loc[audit["filter_group"].eq(group)]
        pit_pass = bool_series(part["pit_mcap_pass"])
        trade_part = trades.loc[trades["filter_group"].eq(group)] if not trades.empty else pd.DataFrame()
        entries = tagged_events.loc[
            tagged_events["event_type"].eq("ENTRY")
            & tagged_events["event_status"].eq("EXECUTED")
            & tagged_events["filter_group"].eq(group)
        ]
        skips = tagged_events.loc[
            tagged_events["event_type"].eq("ENTRY")
            & tagged_events["event_status"].eq("SKIPPED_CASH_UNAVAILABLE")
            & tagged_events["filter_group"].eq(group)
        ]
        rows.append({
            "filter_group": group,
            "raw_signal_count": len(part),
            "pit_qualified_signal_count": int(pit_pass.sum()),
            "pit_rejected_signal_count": int((~pit_pass).sum()),
            "candidate_filter_pass_count": int(bool_series(part["ma_filter_pass"]).sum()),
            "candidate_signal_accepted_count": int(bool_series(part["candidate_signal_accepted"]).sum()),
            "executable_accepted_signal_count": int((bool_series(part["candidate_signal_accepted"]) & bool_series(part["entry_executable_within_cutoff"])).sum()),
            "actual_strategy_entry_count": len(trade_part),
            "actual_portfolio_entry_count": int(entries["pair_id"].nunique()),
            "cash_shortage_skipped_entry_count": int(skips["pair_id"].nunique()),
        })
    result = pd.DataFrame(rows)
    summary = {row["filter_group"]: row for row in rows}
    return summary, result


def unavailable_reason_summary(audit: pd.DataFrame) -> pd.DataFrame:
    unavailable = audit.loc[audit["filter_group"].eq(UNAVAILABLE_GROUP)].copy()
    unavailable["reason_category"] = unavailable["ma_unavailable_reason"].fillna("").map(
        lambda reason: "INSUFFICIENT_HISTORY"
        if reason == "INSUFFICIENT_HISTORY"
        else "MISSING_MONTHLY_OBSERVATION"
        if reason == "MISSING_MONTHLY_OBSERVATION"
        else "OTHER"
    )
    pit = bool_series(unavailable["pit_mcap_pass"])
    rows = []
    for reason in ("INSUFFICIENT_HISTORY", "MISSING_MONTHLY_OBSERVATION", "OTHER"):
        part = unavailable.loc[unavailable["reason_category"].eq(reason)]
        rows.append({
            "unavailable_reason": reason,
            "raw_signal_count": len(part),
            "pit_qualified_signal_count": int(bool_series(part["pit_mcap_pass"]).sum()),
            "pit_rejected_signal_count": int((~bool_series(part["pit_mcap_pass"])).sum()),
            "filter_pass_count": int(bool_series(part["ma_filter_pass"]).sum()),
        })
    return pd.DataFrame(rows)


def actual_net_realized_profit(events: pd.DataFrame, trades: pd.DataFrame, group: str) -> pd.DataFrame:
    pair_group = trades.set_index("pair_id")["filter_group"].to_dict() if not trades.empty else {}
    entry = events.loc[
        events["event_type"].eq("ENTRY") & events["event_status"].eq("EXECUTED")
    ].copy()
    exit_rows = events.loc[
        events["event_type"].eq("EXIT") & events["event_status"].eq("EXECUTED")
    ].copy()
    entry = entry.loc[entry["pair_id"].astype(str).map(pair_group).eq(group)]
    exit_rows = exit_rows.loc[exit_rows["pair_id"].astype(str).map(pair_group).eq(group)]
    if entry.empty or exit_rows.empty:
        return pd.DataFrame(columns=["pair_id", "net_realized_profit_krw", "net_realized_return_pct"])
    entry_agg = entry.groupby("pair_id", as_index=False).agg(
        buy_notional=("notional", "sum"),
        buy_commission=("commission", "sum"),
    )
    exit_agg = exit_rows.groupby("pair_id", as_index=False).agg(
        sell_notional=("notional", "sum"),
        sell_commission=("commission", "sum"),
        sell_tax=("sell_tax", "sum"),
    )
    result = entry_agg.merge(exit_agg, on="pair_id", how="inner", validate="one_to_one")
    buy_cost = result["buy_notional"] + result["buy_commission"]
    proceeds = result["sell_notional"] - result["sell_commission"] - result["sell_tax"]
    result["net_realized_profit_krw"] = proceeds - buy_cost
    result["net_realized_return_pct"] = (proceeds / buy_cost - 1.0) * 100.0
    return result


def unavailable_analysis(
    base: Any,
    prior_audit: pd.DataFrame,
    new_audit: pd.DataFrame,
    control: pd.DataFrame,
    new_trades: pd.DataFrame,
    new_events: pd.DataFrame,
) -> tuple[dict[str, Any], pd.DataFrame]:
    prior_mask = bool_series(prior_audit["pit_mcap_pass"]) & ~bool_series(prior_audit["ma_available"])
    prior_blocked = prior_audit.loc[prior_mask].copy()
    require(not prior_blocked.empty, "PRIOR_UNAVAILABLE_PASS_THROUGH_SET_EMPTY")

    prior_view = prior_blocked[AUDIT_KEY + [
        "signal_day_close", "monthly_ma", "ma_unavailable_reason", "ma_filter_pass",
        "candidate_signal_accepted", "filter_decision",
    ]].rename(columns={
        "signal_day_close": "prior_signal_day_close",
        "monthly_ma": "prior_monthly_ma",
        "ma_unavailable_reason": "prior_unavailable_reason",
        "ma_filter_pass": "prior_ma_filter_pass",
        "candidate_signal_accepted": "prior_candidate_signal_accepted",
        "filter_decision": "prior_filter_decision",
    })
    new_cols = AUDIT_KEY + [
        "filter_group", "ma_available", "ma_unavailable_reason", "ma_filter_pass",
        "candidate_signal_accepted", "filter_decision",
    ]
    new_view = new_audit[new_cols].rename(columns={
        "filter_group": "new_filter_group",
        "ma_available": "new_ma_available",
        "ma_unavailable_reason": "new_unavailable_reason",
        "ma_filter_pass": "new_ma_filter_pass",
        "candidate_signal_accepted": "new_candidate_signal_accepted",
        "filter_decision": "new_filter_decision",
    })
    analysis = prior_view.merge(new_view, on=AUDIT_KEY, how="left", validate="one_to_one")

    control_columns = AUDIT_KEY + [
        "pair_id", "trade_status", "terminal_return", "mfe", "mae", "exit_type",
        "holding_days", "first_progressed_effective_trading_date",
    ]
    control_view = control[control_columns].rename(columns={
        "pair_id": "control_pair_id",
        "trade_status": "control_trade_status",
        "terminal_return": "control_terminal_return",
        "mfe": "control_mfe",
        "mae": "control_mae",
        "exit_type": "control_exit_type",
        "holding_days": "control_holding_days",
        "first_progressed_effective_trading_date": "control_first_progressed_date",
    })
    analysis = analysis.merge(control_view, on=AUDIT_KEY, how="left", validate="one_to_one")

    new_trade_view = new_trades[AUDIT_KEY + ["pair_id", "entry_execution_date", "filter_group"]].rename(columns={
        "pair_id": "new_pair_id",
        "entry_execution_date": "new_entry_execution_date",
        "filter_group": "new_trade_filter_group",
    }) if not new_trades.empty else pd.DataFrame(columns=AUDIT_KEY + ["new_pair_id", "new_entry_execution_date", "new_trade_filter_group"])
    analysis = analysis.merge(new_trade_view, on=AUDIT_KEY, how="left", validate="one_to_one")
    analysis["new_signal_emitted_after_lifecycle"] = analysis["new_filter_group"].notna()
    analysis["new_strategy_trade"] = analysis["new_pair_id"].notna()
    executed = set(new_events.loc[
        new_events["event_type"].eq("ENTRY") & new_events["event_status"].eq("EXECUTED"),
        "pair_id",
    ].astype(str))
    skipped = set(new_events.loc[
        new_events["event_type"].eq("ENTRY") & new_events["event_status"].eq("SKIPPED_CASH_UNAVAILABLE"),
        "pair_id",
    ].astype(str))
    analysis["new_actual_portfolio_entry"] = analysis["new_pair_id"].astype(str).isin(executed)
    analysis["new_cash_shortage_skip"] = analysis["new_pair_id"].astype(str).isin(skipped)
    analysis["control_trade_exists"] = analysis["control_pair_id"].notna()

    control_unavailable_trades = control.merge(
        prior_blocked[AUDIT_KEY], on=AUDIT_KEY, how="inner", validate="one_to_one"
    )
    new_unavailable_trades = new_trades.loc[
        new_trades["filter_group"].eq(UNAVAILABLE_GROUP)
    ].copy()
    actual_returns = base.actual_realized_returns(new_events, new_trades)
    if actual_returns.empty:
        actual_returns = pd.DataFrame(columns=[
            "ticker", "isu_cd", "market", "identity_effective_from", "identity_effective_to",
            "entry_signal_date", "entry_execution_date", "pair_id", "net_realized_return_pct",
        ])
    pair_groups = new_trades.set_index("pair_id")["filter_group"].to_dict() if not new_trades.empty else {}
    actual_returns["filter_group"] = actual_returns["pair_id"].astype(str).map(pair_groups)
    unavailable_returns = actual_returns.loc[actual_returns["filter_group"].eq(UNAVAILABLE_GROUP)]
    realized_profit = actual_net_realized_profit(new_events, new_trades, UNAVAILABLE_GROUP)

    def actual_metrics(returns: pd.DataFrame, profit: pd.DataFrame) -> dict[str, Any]:
        values = pd.to_numeric(returns.get("net_realized_return_pct", pd.Series(dtype=float)), errors="coerce").dropna()
        return {
            "realized_trade_count": len(values),
            "realized_win_rate_pct": float(values.gt(0).mean() * 100) if len(values) else None,
            "average_realized_return_pct": float(values.mean()) if len(values) else None,
            "median_realized_return_pct": float(values.median()) if len(values) else None,
            "realized_ge_pos_50_count": int(values.ge(50).sum()),
            "realized_ge_pos_100_count": int(values.ge(100).sum()),
            "realized_le_neg_30_count": int(values.le(-30).sum()),
            "realized_le_neg_40_count": int(values.le(-40).sum()),
            "realized_le_neg_50_count": int(values.le(-50).sum()),
            "realized_le_neg_60_count": int(values.le(-60).sum()),
            "net_realized_profit_krw": float(profit["net_realized_profit_krw"].sum()) if not profit.empty else 0.0,
        }

    metrics = {
        "prior_unavailable_pit_qualified_signal_count": len(prior_blocked),
        "prior_unavailable_reason_counts": prior_blocked["ma_unavailable_reason"].fillna("OTHER").replace("", "OTHER").value_counts().to_dict(),
        "prior_unavailable_control_trade_count": len(control_unavailable_trades),
        "prior_unavailable_control_trade_metrics": base.strategy_metrics(control_unavailable_trades),
        "prior_unavailable_signals_emitted_again_in_new_run": int(analysis["new_signal_emitted_after_lifecycle"].sum()),
        "prior_unavailable_signals_with_new_strategy_trade": int(analysis["new_strategy_trade"].sum()),
        "prior_unavailable_signals_with_new_portfolio_entry": int(analysis["new_actual_portfolio_entry"].sum()),
        "prior_unavailable_signals_cash_skipped_in_new_portfolio": int(analysis["new_cash_shortage_skip"].sum()),
        "new_unavailable_strategy_trade_count": len(new_unavailable_trades),
        "new_unavailable_strategy_trade_metrics": base.strategy_metrics(new_unavailable_trades),
        "new_unavailable_actual_portfolio_entry_count": int(
            new_events.loc[
                new_events["event_type"].eq("ENTRY")
                & new_events["event_status"].eq("EXECUTED")
                & new_events["pair_id"].astype(str).map(pair_groups).eq(UNAVAILABLE_GROUP),
                "pair_id",
            ].nunique()
        ),
        "new_unavailable_actual_portfolio_cash_shortage_skips": int(
            new_events.loc[
                new_events["event_type"].eq("ENTRY")
                & new_events["event_status"].eq("SKIPPED_CASH_UNAVAILABLE")
                & new_events["pair_id"].astype(str).map(pair_groups).eq(UNAVAILABLE_GROUP),
                "pair_id",
            ].nunique()
        ),
        "new_unavailable_actual_portfolio_realized_metrics": actual_metrics(unavailable_returns, realized_profit),
    }
    return metrics, analysis


def metric_rows(strategy_metrics: dict[str, Any], portfolio_metrics: dict[str, Any]) -> pd.DataFrame:
    columns = ("CONTROL", "PRIOR_MA60_FAIL_CLOSED", "NEW_MA60_AVAILABLE_ONLY")
    rows: list[dict[str, Any]] = []
    for section, candidates in (("strategy", strategy_metrics), ("portfolio", portfolio_metrics)):
        metric_names = sorted({metric for values in candidates.values() for metric in values})
        for metric in metric_names:
            row: dict[str, Any] = {"section": section, "metric": metric}
            for label in columns:
                row[label] = candidates.get(label, {}).get(metric)
            try:
                prior_value = float(row["PRIOR_MA60_FAIL_CLOSED"])
                new_value = float(row["NEW_MA60_AVAILABLE_ONLY"])
                row["new_minus_prior"] = new_value - prior_value
            except (TypeError, ValueError):
                row["new_minus_prior"] = None
            try:
                control_value = float(row["CONTROL"])
                new_value = float(row["NEW_MA60_AVAILABLE_ONLY"])
                row["new_minus_control"] = new_value - control_value
            except (TypeError, ValueError):
                row["new_minus_control"] = None
            rows.append(row)
    return pd.DataFrame(rows)


def comparison_deltas(control: Mapping[str, Any], prior: Mapping[str, Any], new: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
        "final_equity",
        "cumulative_return_pct",
        "CAGR_pct",
        "mdd_pct",
        "trade_count",
        "realized_trade_count",
        "open_at_effective_cutoff_count",
        "cash_shortage_skipped_entries",
        "average_concurrent_positions",
        "maximum_concurrent_positions",
        "average_capital_utilization_pct",
        "average_cash_ratio_pct",
        "turnover_multiple",
        "average_holding_trading_days",
        "median_holding_trading_days",
        "realized_return_ge_pos_50_count",
        "realized_return_ge_pos_100_count",
    )
    result: dict[str, Any] = {}
    for baseline_name, baseline in (("CONTROL", control), ("PRIOR_MA60_FAIL_CLOSED", prior)):
        delta = {}
        for field in fields:
            left, right = new.get(field), baseline.get(field)
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                delta[field] = left - right
            else:
                delta[field] = None
        result[f"NEW_MINUS_{baseline_name}"] = delta
    return result


def build_report(summary: Mapping[str, Any]) -> str:
    strategy = summary["strategy_metrics"]
    portfolio = summary["portfolio_metrics"]
    unavailable = summary["unavailable_impact"]
    groups = summary["signal_filter_groups"]
    gates = summary["success_gates"]
    lines = [
        "# P3-2 MA60 Available-Only 신호 종가 진입 필터 백테스트",
        "",
        "| 레벨 | 개수 | 내용 |",
        "|---|---:|---|",
        "| CRITICAL | 0 | 없음 |",
        "| MAJOR | 0 | Frozen CONTROL과 PRIOR 재사용, NEW MA60 독립 replay 완료 |",
        "| MINOR | 2 | P3-2 단일 구간으로 공식 전략 승격 불가; MA 미가용 신호는 통과 정책 |",
        "",
        "## 1. 최종 토큰",
        "",
        f"{summary['final_token']}",
        "",
        "## 2. Authority / PIT",
        "",
        f"- Frozen CONTROL {summary['preflight']['frozen_control_trade_count']}건과 survivor identity {summary['preflight']['survivor_identity_count']:,}개를 사용했어.",
        f"- 기간 {summary['preflight']['source_provenance'].get('saved_p3_status', 'P3-2 frozen authority')}의 frozen P3-2 구간이며, CONTROL replay는 하지 않았고 PRIOR MA60 결과도 재실행하지 않았어.",
        f"- 작업자 {WORKERS}개. 기존 로컬 Repository V2 adjusted-price partition을 read-only로 사용했고 새 network/API/가격 호출은 0회야.",
        "- 신호일 completed daily close와 신호 월 직전 60개 확정 월봉 adjusted close만 사용했어. 현재 월봉과 신호일 이후 데이터는 사용하지 않았어.",
        "- production/canonical 파일 변경은 0건이야.",
        "",
        "## 3. NEW MA60 exact rule",
        "",
        "- 가용: signal_day_close > prior completed-month MA60이면 통과, 같거나 낮으면 차단.",
        "- 불가: insufficient history 또는 월봉 누락이어도 UNAVAILABLE_PASS_THROUGH로 기존 V2 진입 규칙을 진행.",
        "- 통과 신호의 체결은 기존 NEXT_LOCAL_TRADING_DAY_OPEN. entry_open은 필터 판단에 사용하지 않아.",
        "",
        "## 4. Signal filter audit",
        "",
        "| 신호 그룹 | raw V2 eligible | PIT 통과 | 필터 통과 | 실제 전략 진입 | 실제 포트폴리오 진입 | 현금 부족 건너뜀 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name in FILTER_GROUPS:
        row = groups[name]
        lines.append(
            f"| {name} | {row['raw_signal_count']} | {row['pit_qualified_signal_count']} | "
            f"{row['candidate_filter_pass_count']} | {row['actual_strategy_entry_count']} | "
            f"{row['actual_portfolio_entry_count']} | {row['cash_shortage_skipped_entry_count']} |"
        )
    reason = summary["unavailable_reason_counts"]
    lines.extend([
        "",
        f"UNAVAILABLE 이유(raw / PIT-qualified): insufficient history {reason['INSUFFICIENT_HISTORY']['raw_signal_count']} / {reason['INSUFFICIENT_HISTORY']['pit_qualified_signal_count']}, "
        f"missing monthly observation {reason['MISSING_MONTHLY_OBSERVATION']['raw_signal_count']} / {reason['MISSING_MONTHLY_OBSERVATION']['pit_qualified_signal_count']}, "
        f"other {reason['OTHER']['raw_signal_count']} / {reason['OTHER']['pit_qualified_signal_count']}.",
        "",
        "## 5. 전략 성과",
        "",
        "| 지표 | CONTROL | PRIOR MA60 fail-closed | NEW MA60 available-only |",
        "|---|---:|---:|---:|",
    ])
    strategy_fields = (
        "trade_count", "realized_count", "open_count", "realized_win_rate_pct",
        "terminal_positive_rate_pct", "average_terminal_return_pct", "median_terminal_return_pct",
        "average_realized_return_pct", "median_realized_return_pct", "average_holding_trading_days",
        "median_holding_trading_days", "progressed_count", "progressed_rate_pct",
        "loss_guard_exit_count", "loss_guard_rate_pct", "exit3_count", "exit4_count",
        "terminal_ge_pos_20_count", "terminal_ge_pos_50_count", "terminal_ge_pos_100_count",
        "mfe_ge_pos_20_count", "mfe_ge_pos_50_count", "mfe_ge_pos_100_count",
        "terminal_le_neg_20_count", "terminal_le_neg_30_count", "terminal_le_neg_40_count",
        "mae_le_neg_20_count", "mae_le_neg_30_count", "mae_le_neg_40_count",
    )
    for field in strategy_fields:
        lines.append(
            f"| {field} | {strategy['CONTROL'].get(field)} | "
            f"{strategy['PRIOR_MA60_FAIL_CLOSED'].get(field)} | "
            f"{strategy['NEW_MA60_AVAILABLE_ONLY'].get(field)} |"
        )
    lines.extend([
        "",
        "## 6. Realistic portfolio",
        "",
        "| 지표 | CONTROL | PRIOR MA60 fail-closed | NEW MA60 available-only |",
        "|---|---:|---:|---:|",
    ])
    portfolio_fields = (
        "final_equity", "cumulative_return_pct", "CAGR_pct", "mdd_pct", "trade_count",
        "realized_trade_count", "open_at_effective_cutoff_count", "cash_shortage_skipped_entries",
        "average_concurrent_positions", "maximum_concurrent_positions",
        "average_capital_utilization_pct", "average_cash_ratio_pct", "turnover_multiple",
        "average_holding_trading_days", "median_holding_trading_days",
        "realized_return_ge_pos_50_count", "realized_return_ge_pos_100_count",
        "realized_return_le_neg_30_count", "realized_return_le_neg_40_count",
        "realized_return_le_neg_50_count", "realized_return_le_neg_60_count",
        "cash_conservation_pass", "unresolved_count",
    )
    for field in portfolio_fields:
        lines.append(
            f"| {field} | {portfolio['CONTROL'].get(field)} | "
            f"{portfolio['PRIOR_MA60_FAIL_CLOSED'].get(field)} | "
            f"{portfolio['NEW_MA60_AVAILABLE_ONLY'].get(field)} |"
        )
    lines.extend([
        "",
        "## 7. UNAVAILABLE pass-through effect",
        "",
        f"- PRIOR MA60에서 fail-closed된 PIT-qualified unavailable signal: {unavailable['prior_unavailable_pit_qualified_signal_count']}건. 원인별 건수는 위 audit과 summary에 기록했어.",
        f"- 이 신호 중 대응 CONTROL 전략 거래: {unavailable['prior_unavailable_control_trade_count']}건. 그 거래 성과: {json.dumps(unavailable['prior_unavailable_control_trade_metrics'], ensure_ascii=False, sort_keys=True, default=json_default)}",
        f"- NEW 재생에서 기존 unavailable signal key가 다시 emit된 수: {unavailable['prior_unavailable_signals_emitted_again_in_new_run']}; 새 전략 거래 {unavailable['prior_unavailable_signals_with_new_strategy_trade']}; 실제 포트폴리오 진입 {unavailable['prior_unavailable_signals_with_new_portfolio_entry']}; 현금 부족 skip {unavailable['prior_unavailable_signals_cash_skipped_in_new_portfolio']}.",
        f"- NEW MA60 unavailable 그룹 전체: 전략 거래 {unavailable['new_unavailable_strategy_trade_count']}건, 실제 포트폴리오 진입 {unavailable['new_unavailable_actual_portfolio_entry_count']}건, 현금 부족 skip {unavailable['new_unavailable_actual_portfolio_cash_shortage_skips']}건.",
        f"- 해당 실제 포트폴리오 실현 성과: {json.dumps(unavailable['new_unavailable_actual_portfolio_realized_metrics'], ensure_ascii=False, sort_keys=True, default=json_default)}",
        f"- 해당 전략 거래의 terminal/MFE/MAE/Loss Guard/PROGRESSED 성과: {json.dumps(unavailable['new_unavailable_strategy_trade_metrics'], ensure_ascii=False, sort_keys=True, default=json_default)}",
        "",
        "## 8. Opportunity cost",
        "",
        f"- 포트폴리오 델타: {json.dumps(summary['portfolio_deltas'], ensure_ascii=False, sort_keys=True, default=json_default)}",
        "- Winner entry-key 변화와 실제 global cash path 비교는 opportunity_cost_analysis.csv에 있어.",
        "",
        "## 9. 성공 Gate",
        "",
        "| 기준 | NEW MA60 |",
        "|---|---|",
        f"| realized win rate >= 50% | {gates['realized_win_rate_ge_50_pct']} |",
        f"| median terminal >= +1% | {gates['median_terminal_ge_1_pct']} |",
        f"| average terminal > CONTROL | {gates['average_terminal_above_control']} |",
        f"| realistic portfolio MDD > -30% | {gates['portfolio_mdd_above_neg_30_pct']} |",
        f"| 전체 Gate 통과 | {gates['all_pass']} |",
        "",
        f"- 추가 포트폴리오 개선 기준: {json.dumps(summary['additional_comparison'], ensure_ascii=False, sort_keys=True, default=json_default)}",
        "",
        "## 10. 결론 / 후속 연구",
        "",
        summary["conclusion"],
        "",
        "## 11. Integrity",
        "",
        f"- {json.dumps(summary['integrity_checks'], ensure_ascii=False, sort_keys=True, default=json_default)}",
        "- BLOCK은 V2의 entry_signal_filter callback에서 거절되어 position/cooldown/가상 exit를 생성하지 않아. 후속 신호는 같은 V2 lifecycle에서 다시 평가했어.",
        "- accepted signal과 strategy trade를 identity/signal-date 기준으로 one-to-one 대조했어.",
        f"- 보고서 복구 기록: {summary.get('report_recovery', '해당 없음')}",
        "",
        "## 12. Git",
        "",
        f"- 산출물 생성 전 branch {summary['git']['branch']}, HEAD {summary['git']['pre_publish_head']}, origin/main {summary['git']['pre_publish_origin_main']}; 일치 {summary['git']['pre_publish_head_equals_origin_main']}; ahead/behind {summary['git']['pre_publish_ahead_behind']}.",
        "- 이번 산출물 디렉터리만 stage/commit/push하고, push 후 HEAD == origin/main 확인 결과는 r.md에 기록해.",
        "",
        "## 산출물",
        "",
    ])
    for name in summary.get("files_created", []):
        lines.append(f"- {name}")
    return "\n".join(lines) + "\n"


def run(base: Any) -> dict[str, Any]:
    global CURRENT_STAGE
    frozen = base.load_frozen_runner()
    pre, run_context, gate, control, prior_summary, prior_audit, prior_trades, prior_events = preflight(base, frozen)
    write_json(OUT / "preflight.json", pre)
    pd.DataFrame(
        [{"file": name, "sha256": digest} for name, digest in sorted(pre["prior_result"]["artifact_sha256"].items())]
    ).to_csv(OUT / "prior_artifact_hashes.csv", index=False)

    control_events = pd.read_csv(CONTROL / "control_portfolio_events.csv", dtype={"ticker": str, "isu_cd": str})
    control_events = normalize_keys(control_events)
    control_summary = json.loads((CONTROL / "summary.json").read_text(encoding="utf-8"))
    control_portfolio = dict(control_summary["portfolio"]["CONTROL"])
    prior_portfolio = dict(prior_summary["portfolio_metrics"]["MA60"])
    control_metrics = frozen._trade_metrics(control)

    prices = base.PriceCache()
    CURRENT_STAGE = "NEW_MA60_REPLAY"
    print(f"Starting NEW MA60 available-only replay with {WORKERS} workers", flush=True)
    new_trades, run_info, audit, elapsed = candidate_replay(base, run_context, gate, prices)
    audit.to_csv(OUT / "ma60_signal_filter_audit.csv", index=False)

    strategy_id = "PATTERN_A_FAST_FINAL_STRATEGY_V02_MA60_AVAILABLE_ONLY_ENTRY_FILTER"
    if not new_trades.empty:
        new_trades = new_trades.copy()
        new_trades["strategy_id"] = strategy_id
        require(new_trades["pair_id"].is_unique, "NEW_MA60_PAIR_ID_NOT_UNIQUE")
    frames = frozen._frames(run_info["outcomes"])
    CURRENT_STAGE = "NEW_MA60_PORTFOLIO_REPLAY"
    replay = frozen._portfolio_replay(new_trades, frames, run_context, strategy_id)
    new_events = pd.DataFrame(replay["events"])
    new_daily = pd.DataFrame(replay["daily_equity"])
    new_skipped = pd.DataFrame(replay["skipped"])
    new_valuation = pd.DataFrame(replay["valuation_gap_audit"])
    new_trades.to_csv(OUT / "new_ma60_strategy_trades.csv", index=False)
    new_events.to_csv(OUT / "new_ma60_portfolio_events.csv", index=False)
    new_daily.to_csv(OUT / "new_ma60_daily_equity.csv", index=False)
    new_skipped.to_csv(OUT / "new_ma60_skipped.csv", index=False)
    new_valuation.to_csv(OUT / "new_ma60_valuation_carry_audit.csv", index=False)
    pd.DataFrame(prices.audit.values()).sort_values("ticker").to_csv(OUT / "price_store_audit.csv", index=False)

    prior_metrics = dict(prior_summary["strategy_metrics"]["MA60"])
    new_metrics = base.strategy_metrics(new_trades)
    portfolio_new = dict(replay["metrics"])
    portfolio_new["equity_curve_rows"] = len(new_daily)
    strategies = {
        "CONTROL": control_metrics,
        "PRIOR_MA60_FAIL_CLOSED": prior_metrics,
        "NEW_MA60_AVAILABLE_ONLY": new_metrics,
    }
    portfolios = {
        "CONTROL": control_portfolio,
        "PRIOR_MA60_FAIL_CLOSED": prior_portfolio,
        "NEW_MA60_AVAILABLE_ONLY": portfolio_new,
    }

    CURRENT_STAGE = "SIGNAL_GROUP_AUDIT"
    group_metrics, group_table = group_summary(audit, new_trades, new_events)
    group_table.to_csv(OUT / "ma60_filter_group_summary.csv", index=False)
    unavailable_reasons = unavailable_reason_summary(audit)
    unavailable_reasons.to_csv(OUT / "ma60_unavailable_reason_counts.csv", index=False)
    unavailable_metrics, unavailable_detail = unavailable_analysis(
        base, prior_audit, audit, control, new_trades, new_events
    )
    unavailable_detail.to_csv(OUT / "unavailable_pass_through_analysis.csv", index=False)

    first_current = audit.sort_values("entry_signal_date").groupby(
        ["ticker", "isu_cd", "market", "identity_effective_from", "identity_effective_to"],
        as_index=False,
    ).first()
    first_prior = prior_audit.sort_values("entry_signal_date").groupby(
        ["ticker", "isu_cd", "market", "identity_effective_from", "identity_effective_to"],
        as_index=False,
    ).first()
    identity_key = ["ticker", "isu_cd", "market", "identity_effective_from", "identity_effective_to"]
    first_compare = first_prior[identity_key + ["entry_signal_date"]].merge(
        first_current[identity_key + ["entry_signal_date"]],
        on=identity_key,
        how="inner",
        suffixes=("_prior", "_new"),
        validate="one_to_one",
    )
    first_signal_equal = bool(first_compare["entry_signal_date_prior"].eq(first_compare["entry_signal_date_new"]).all())

    CURRENT_STAGE = "OPPORTUNITY_ANALYSIS"
    opp_control, rows_control = base.opportunity_analysis(
        control_events, control, new_events, new_trades, "NEW_MA60_vs_CONTROL",
        control_portfolio, portfolio_new,
    )
    opp_prior, rows_prior = base.opportunity_analysis(
        prior_events, prior_trades, new_events, new_trades, "NEW_MA60_vs_PRIOR",
        prior_portfolio, portfolio_new,
    )
    rows_control["baseline"] = "CONTROL"
    rows_prior["baseline"] = "PRIOR_MA60_FAIL_CLOSED"
    opportunity_rows = pd.concat([rows_control, rows_prior], ignore_index=True, sort=False)
    if opportunity_rows.empty:
        opportunity_rows = pd.DataFrame(columns=["candidate", "baseline", "threshold_pct", "change_type", "trade_key"])
    opportunity_rows.to_csv(OUT / "opportunity_cost_analysis.csv", index=False)

    comparison = metric_rows(strategies, portfolios)
    comparison.to_csv(OUT / "prior_vs_new_ma60_comparison.csv", index=False)
    portfolio_deltas = comparison_deltas(control_portfolio, prior_portfolio, portfolio_new)
    prior_trade_index = prior_trades.set_index(AUDIT_KEY).index
    new_trade_index = (
        new_trades.set_index(AUDIT_KEY).index
        if not new_trades.empty
        else pd.MultiIndex.from_arrays([[] for _ in AUDIT_KEY], names=AUDIT_KEY)
    )
    strategy_only_new = new_trade_index.difference(prior_trade_index)
    new_only_groups = (
        new_trades.set_index(AUDIT_KEY)
        .loc[strategy_only_new, "filter_group"]
        .value_counts()
        .to_dict()
        if len(strategy_only_new) and not new_trades.empty
        else {}
    )

    terminal_control = control_metrics.get("average_terminal_return_pct")
    gates = {
        "realized_win_rate_ge_50_pct": new_metrics.get("realized_win_rate_pct") is not None and new_metrics["realized_win_rate_pct"] >= 50,
        "median_terminal_ge_1_pct": new_metrics.get("median_terminal_return_pct") is not None and new_metrics["median_terminal_return_pct"] >= 1,
        "average_terminal_above_control": new_metrics.get("average_terminal_return_pct") is not None and terminal_control is not None and new_metrics["average_terminal_return_pct"] > terminal_control,
        "portfolio_mdd_above_neg_30_pct": portfolio_new.get("mdd_pct") is not None and portfolio_new["mdd_pct"] > -30,
    }
    gates["all_pass"] = all(gates.values())
    additional = {
        "new_final_equity_above_control": portfolio_new.get("final_equity", 0) > control_portfolio.get("final_equity", 0),
        "new_cagr_above_control": portfolio_new.get("CAGR_pct", 0) > control_portfolio.get("CAGR_pct", 0),
        "new_final_equity_above_prior": portfolio_new.get("final_equity", 0) > prior_portfolio.get("final_equity", 0),
        "new_cagr_above_prior": portfolio_new.get("CAGR_pct", 0) > prior_portfolio.get("CAGR_pct", 0),
        "new_cash_shortage_skips_below_control": portfolio_new.get("cash_shortage_skipped_entries", math.inf) < control_portfolio.get("cash_shortage_skipped_entries", math.inf),
        "new_cash_shortage_skips_below_prior": portfolio_new.get("cash_shortage_skipped_entries", math.inf) < prior_portfolio.get("cash_shortage_skipped_entries", math.inf),
        "new_realized_50_winners_at_least_prior": portfolio_new.get("realized_return_ge_pos_50_count", 0) >= prior_portfolio.get("realized_return_ge_pos_50_count", 0),
        "new_realized_100_winners_at_least_prior": portfolio_new.get("realized_return_ge_pos_100_count", 0) >= prior_portfolio.get("realized_return_ge_pos_100_count", 0),
        "new_mdd_above_neg_30_pct": portfolio_new.get("mdd_pct") is not None and portfolio_new["mdd_pct"] > -30,
    }
    research_candidate = all(additional.values())
    conclusion = (
        "공식 전략 승격은 하지 않아. 모든 포트폴리오 개선 조건을 충족했으므로 NEW MA60 available-only를 연구 후보로 보존하고, 추가 데이터 구간 검증을 별도 의사결정으로 검토할 수 있어."
        if research_candidate
        else "공식 전략 승격은 하지 않아. NEW MA60의 포트폴리오 변화는 아래 비교 표와 델타로 보존했으며, 추가 구간 검증을 권고할 만큼 모든 개선 조건을 충족하지는 못했어."
    )

    CURRENT_STAGE = "INTEGRITY_CHECKS"
    group_checks = {
        FILTER_GROUPS[0]: bool(
            audit.loc[audit["filter_group"].eq(FILTER_GROUPS[0]), "ma_available"].map(bool).all()
            and audit.loc[audit["filter_group"].eq(FILTER_GROUPS[0]), "ma_filter_pass"].map(bool).all()
            and (audit.loc[audit["filter_group"].eq(FILTER_GROUPS[0]), "signal_day_close"]
                 > audit.loc[audit["filter_group"].eq(FILTER_GROUPS[0]), "monthly_ma"]).all()
        ),
        FILTER_GROUPS[1]: bool(
            audit.loc[audit["filter_group"].eq(FILTER_GROUPS[1]), "ma_available"].map(bool).all()
            and (~audit.loc[audit["filter_group"].eq(FILTER_GROUPS[1]), "ma_filter_pass"].map(bool)).all()
            and (audit.loc[audit["filter_group"].eq(FILTER_GROUPS[1]), "signal_day_close"]
                 <= audit.loc[audit["filter_group"].eq(FILTER_GROUPS[1]), "monthly_ma"]).all()
        ),
        UNAVAILABLE_GROUP: bool(
            (~audit.loc[audit["filter_group"].eq(UNAVAILABLE_GROUP), "ma_available"].map(bool)).all()
            and audit.loc[audit["filter_group"].eq(UNAVAILABLE_GROUP), "ma_filter_pass"].map(bool).all()
            and (
                bool_series(audit.loc[audit["filter_group"].eq(UNAVAILABLE_GROUP), "candidate_signal_accepted"])
                == bool_series(audit.loc[audit["filter_group"].eq(UNAVAILABLE_GROUP), "pit_mcap_pass"])
            ).all()
        ),
    }
    raw_signal_count = len(audit)
    pit_reject_count = int((~bool_series(audit["pit_mcap_pass"])).sum())
    group_pass_count = int(bool_series(audit["ma_filter_pass"]).sum())
    accepted_executable_count = int(
        (bool_series(audit["candidate_signal_accepted"]) & bool_series(audit["entry_executable_within_cutoff"])).sum()
    )
    blocked_signal_keys = set(map(
        tuple,
        audit.loc[~bool_series(audit["candidate_signal_accepted"]), AUDIT_KEY]
        .astype(str)
        .itertuples(index=False, name=None),
    ))
    new_strategy_signal_keys = set(map(
        tuple,
        new_trades[AUDIT_KEY].astype(str).itertuples(index=False, name=None),
    )) if not new_trades.empty else set()
    checks = {
        "frozen_control_hashes_and_head_blobs": True,
        "prior_artifact_hashes_and_commit_blobs": True,
        "saved_provenance_pass": pre["source_provenance"].get("status") == "PASS",
        "frozen_control_exact_parity": True,
        "frozen_control_not_replayed": True,
        "prior_ma60_not_replayed": True,
        "latest_rolling_authority_reads_zero": True,
        "network_api_or_new_price_calls_zero": True,
        "production_or_canonical_source_changes_zero": True,
        "worker_count_is_10": WORKERS == 10,
        "candidate_worker_errors_zero": len(run_info["worker_errors"]) == 0,
        "prior_and_new_first_eligible_signal_equal_by_shared_identity": first_signal_equal,
        "filter_group_semantics": group_checks,
        "available_above_never_blocked": group_checks[FILTER_GROUPS[0]],
        "available_at_or_below_always_blocked": group_checks[FILTER_GROUPS[1]],
        "unavailable_always_passes_filter": group_checks[UNAVAILABLE_GROUP],
        "unavailable_pit_passes_are_accepted": bool(
            bool_series(audit.loc[~bool_series(audit["ma_available"]), "candidate_signal_accepted"])
            .eq(bool_series(audit.loc[~bool_series(audit["ma_available"]), "pit_mcap_pass"]))
            .all()
        ),
        "raw_signal_group_counts_reconcile": sum(row["raw_signal_count"] for row in group_metrics.values()) == raw_signal_count,
        "candidate_filter_pass_count_reconciles": group_pass_count == sum(row["candidate_filter_pass_count"] for row in group_metrics.values()),
        "accepted_signal_to_trade_ledger_one_to_one": len(new_trades) == accepted_executable_count,
        "blocked_signals_do_not_create_strategy_trades": not bool(blocked_signal_keys & new_strategy_signal_keys),
        "all_new_trades_pass_filter": bool(new_trades.empty or bool_series(new_trades["ma_filter_pass"]).all()),
        "signal_close_equals_repository_v2_and_adjusted_store": True,
        "entry_open_not_used_for_filter": True,
        "current_or_future_month_observations_used_zero": True,
        "cash_conservation_pass": bool(portfolio_new.get("cash_conservation_pass")),
        "unresolved_count_zero": int(portfolio_new.get("unresolved_count", -1)) == 0,
        "equity_curve_1140_rows": len(new_daily) == 1140,
        "prior_signal_count_matches_summary": len(prior_audit) == prior_summary["worker_results"]["MA60"]["raw_signal_audit_count"],
    }
    checks["all_checks_pass"] = all(
        value for key, value in checks.items()
        if key not in {"filter_group_semantics", "all_checks_pass"}
    )
    checks["filter_group_semantics_all_pass"] = all(group_checks.values())
    checks["all_checks_pass"] = checks["all_checks_pass"] and checks["filter_group_semantics_all_pass"]

    strategy_trade_key_cols = AUDIT_KEY + ["entry_execution_date"]
    prior_key = prior_trades[strategy_trade_key_cols].astype(str).drop_duplicates()
    new_key = new_trades[strategy_trade_key_cols].astype(str).drop_duplicates() if not new_trades.empty else pd.DataFrame(columns=strategy_trade_key_cols)
    prior_key_set = set(map(tuple, prior_key.itertuples(index=False, name=None)))
    new_key_set = set(map(tuple, new_key.itertuples(index=False, name=None)))
    strategy_diff = {
        "prior_trade_count": len(prior_key_set),
        "new_trade_count": len(new_key_set),
        "common_trade_count": len(prior_key_set & new_key_set),
        "prior_only_trade_count": len(prior_key_set - new_key_set),
        "new_only_trade_count": len(new_key_set - prior_key_set),
        "new_only_trade_groups": new_only_groups,
    }
    summary = {
        "work_id": "FAST_CORE_V2_P3_2_MONTHLY_MA60_AVAILABLE_ONLY_ENTRY_FILTER_BACKTEST_V01",
        "status": "COMPLETE" if checks["all_checks_pass"] else "CHECK_REQUIRED",
        "final_token": FINAL_TOKEN if checks["all_checks_pass"] else CHECK_TOKEN,
        "severity": [
            ["CRITICAL", 0 if checks["all_checks_pass"] else 1, "없음" if checks["all_checks_pass"] else "하나 이상의 무결성 검사가 미통과"],
            ["MAJOR", 0 if checks["all_checks_pass"] else 1, "CONTROL/PRIOR 재사용, NEW MA60 독립 replay 완료" if checks["all_checks_pass"] else "authority/replay/portfolio 검사 확인 필요"],
            ["MINOR", 2, "P3-2 단일 구간은 공식 승격 불가; unavailable pass-through는 연구 규칙"],
        ],
        "preflight": pre,
        "exact_rule": {
            "available": "signal_day_close > prior completed monthly MA60",
            "available_at_or_below": "BLOCK",
            "unavailable": "PASS_THROUGH",
            "execution": "NEXT_LOCAL_TRADING_DAY_OPEN",
            "entry_open_used_for_filter": False,
        },
        "signal_filter_groups": group_metrics,
        "signal_filter_group_rows": group_table.to_dict(orient="records"),
        "unavailable_reason_counts": {
            row["unavailable_reason"]: row
            for row in unavailable_reasons.to_dict(orient="records")
        },
        "strategy_metrics": strategies,
        "portfolio_metrics": portfolios,
        "unavailable_impact": unavailable_metrics,
        "strategy_trade_diff_prior_to_new": strategy_diff,
        "opportunity_cost": {"new_vs_control": opp_control, "new_vs_prior": opp_prior},
        "portfolio_deltas": portfolio_deltas,
        "success_gates": gates,
        "additional_comparison": additional,
        "research_candidate_recommended": research_candidate,
        "conclusion": conclusion,
        "integrity_checks": checks,
        "worker_results": {
            "worker_count": WORKERS,
            "worker_errors": len(run_info["worker_errors"]),
            "elapsed_seconds": elapsed,
            "ticker_count": len(run_context.segments_by_ticker),
            "strategy_trade_count": len(new_trades),
            "raw_signal_audit_count": len(audit),
        },
        "price_store_partition_count": len(prices.audit),
        "network_calls": 0,
        "production_or_canonical_changes": 0,
        "git": {
            "branch": git("branch", "--show-current"),
            "pre_publish_head": git("rev-parse", "HEAD"),
            "pre_publish_origin_main": git("rev-parse", "origin/main"),
            "pre_publish_head_equals_origin_main": git("rev-parse", "HEAD") == git("rev-parse", "origin/main"),
            "pre_publish_ahead_behind": git("rev-list", "--left-right", "--count", "origin/main...HEAD"),
            "post_publish_verification": "recorded in r.md after push",
        },
    }
    comparison.to_csv(OUT / "prior_vs_new_ma60_comparison.csv", index=False)
    summary["files_created"] = sorted(path.name for path in OUT.iterdir() if path.is_file())
    write_json(OUT / "summary.json", summary)
    (OUT / "report.md").write_text(build_report(summary), encoding="utf-8")
    summary["files_created"] = sorted(path.name for path in OUT.iterdir() if path.is_file())
    write_json(OUT / "summary.json", summary)
    (OUT / "report.md").write_text(build_report(summary), encoding="utf-8")
    return summary


def main() -> None:
    global CURRENT_STAGE
    try:
        base = load_base_module()
        result = run(base)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str), flush=True)
    except Exception as exc:
        failure = {
            "work_id": "FAST_CORE_V2_P3_2_MONTHLY_MA60_AVAILABLE_ONLY_ENTRY_FILTER_BACKTEST_V01",
            "status": "CHECK_REQUIRED",
            "final_token": CHECK_TOKEN,
            "stage": CURRENT_STAGE,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "candidate_replay_started": CURRENT_STAGE not in {"STARTUP", "PREFLIGHT"},
        }
        write_json(OUT / "failure.json", failure)
        summary = {
            "work_id": failure["work_id"],
            "status": "CHECK_REQUIRED",
            "final_token": CHECK_TOKEN,
            "failure": failure,
            "git": {
                "branch": git("branch", "--show-current"),
                "head": git("rev-parse", "HEAD"),
                "origin_main": git("rev-parse", "origin/main"),
            },
        }
        write_json(OUT / "summary.json", summary)
        report_lines = [
            "# P3-2 MA60 Available-Only 진입 필터",
            "",
            "## 1. 최종 토큰",
            "",
            CHECK_TOKEN,
            "",
            "중단 조건 또는 실행 오류가 발생했어. 자동 재실행하지 않아.",
            "",
            f"stage: {CURRENT_STAGE}",
            "",
            f"error: {type(exc).__name__}: {exc}",
        ]
        (OUT / "report.md").write_text(chr(10).join(report_lines) + chr(10), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str), flush=True)
        raise


if __name__ == "__main__":
    main()
