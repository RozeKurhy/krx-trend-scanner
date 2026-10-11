#!/usr/bin/env python3
"""Finalize reports and independent audits from the saved P3-1 replay outputs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
EVAL_START = "2022-01-03"
CUTOFF = "2025-05-30"
SUPPORT = "2025-06-02"
INITIAL = 200_000_000.0

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trend_scanner.data.market_calendar import load_rolling_production_market_calendar
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data.rolling_market_data_refresh import load_rolling_authority
from trend_scanner.universe.permanent_identity_exclusions import PERMANENT_IDENTITY_EXCLUSIONS


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv(name: str) -> pd.DataFrame:
    path = OUT / name
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path, keep_default_na=True)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def read_json(name: str) -> dict[str, Any]:
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def json_write(name: str, value: Any) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=json_default) + "\n", encoding="utf-8")


def json_default(value: Any) -> Any:
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if pd.isna(value):
        return None
    raise TypeError(type(value).__name__)


def truth(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def identity_signal_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("ticker", "")).zfill(6),
        str(row.get("isu_cd", row.get("standard_isu_cd", ""))).strip().upper(),
        str(row.get("entry_signal_date", row.get("signal_date", "")))[:10],
        str(row.get("entry_execution_date", ""))[:10],
    )


def mdd_independent(curve: pd.DataFrame) -> dict[str, Any]:
    valid = curve.loc[curve["equity"].notna()].sort_values("date")
    coverage = len(valid) / len(curve) if len(curve) else 0.0
    peak = INITIAL
    peak_day = EVAL_START
    dd = 0.0
    dd_peak = peak_day
    dd_trough = peak_day
    recovery: str | None = peak_day
    dd_peak_value = peak
    for row in valid.to_dict("records"):
        day = str(row["date"])[:10]
        value = float(row["equity"])
        if value > peak:
            peak = value
            peak_day = day
        drawdown = value / peak - 1.0 if peak else 0.0
        if drawdown < dd:
            dd = drawdown
            dd_peak = peak_day
            dd_trough = day
            dd_peak_value = peak
            recovery = None
        elif recovery is None and value >= dd_peak_value:
            recovery = day
    return {"mdd_pct": dd * 100.0 if coverage >= 0.90 else None, "observed_mdd_pct": dd * 100.0, "mdd_peak_date": dd_peak, "mdd_trough_date": dd_trough, "mdd_recovery_date": recovery}


def trade_sequences_contiguous(*frames: pd.DataFrame) -> bool:
    for frame in frames:
        if frame.empty:
            continue
        if "trade_sequence" not in frame or "ticker" not in frame:
            return False
        for _, group in frame.groupby(frame["ticker"].astype(str).str.zfill(6), sort=False):
            try:
                values = sorted(int(value) for value in group["trade_sequence"].tolist())
            except (TypeError, ValueError):
                return False
            if values != list(range(1, len(values) + 1)):
                return False
    return True


def cost_and_portfolio_checks(events: pd.DataFrame, trades: pd.DataFrame, metrics: Mapping[str, Any]) -> dict[str, Any]:
    entry = events.loc[events.get("event_type", pd.Series(dtype=object)).eq("ENTRY")].copy() if not events.empty else pd.DataFrame()
    exit_ = events.loc[events.get("event_type", pd.Series(dtype=object)).eq("EXIT")].copy() if not events.empty else pd.DataFrame()
    executed_entry = entry.loc[entry.get("event_status", pd.Series(dtype=object)).eq("EXECUTED")] if not entry.empty else pd.DataFrame()
    executed_exit = exit_.loc[exit_.get("event_status", pd.Series(dtype=object)).eq("EXECUTED")] if not exit_.empty else pd.DataFrame()
    fill_formula_ok = True
    entry_budget_ok = True
    entry_open_parity = True
    exit_open_parity = True
    event_cost_total = 0.0
    event_slippage_total = 0.0
    support_cost_total = 0.0
    support_slippage_total = 0.0
    support_exit_count = 0
    trade_by_id = {"|".join(identity_signal_key(row)): row for row in trades.to_dict("records")}
    for row in executed_entry.to_dict("records"):
        ref = float(row["reference_price"])
        fill_formula_ok &= abs(float(row["fill_price"]) - ref * 1.001) < 1e-6
        fill_formula_ok &= abs(float(row["commission_krw"]) - float(row["notional_krw"]) * 0.00015) < 1e-6
        fill_formula_ok &= abs(float(row["slippage_impact_krw"]) - abs(float(row["fill_price"]) - ref) * float(row["shares"])) < 1e-6
        if truth(row.get("post_cutoff")):
            support_cost_total += float(row["commission_krw"])
            support_slippage_total += float(row["slippage_impact_krw"])
        else:
            event_cost_total += float(row["commission_krw"])
            event_slippage_total += float(row["slippage_impact_krw"])
        entry_budget_ok &= int(row["shares"]) == float(row["shares"])
        entry_budget_ok &= float(row.get("required_total_buy_cost_krw", 0)) <= 5_000_000.0 + 1e-6
        trade = trade_by_id.get(str(row.get("candidate_id", "")))
        entry_open_parity &= trade is not None and abs(float(trade.get("entry_open")) - ref) <= 0.011
    for row in executed_exit.to_dict("records"):
        ref = float(row["reference_price"])
        fill_formula_ok &= abs(float(row["fill_price"]) - ref * 0.999) < 1e-6
        fill_formula_ok &= abs(float(row["commission_krw"]) - float(row["notional_krw"]) * 0.00015) < 1e-6
        fill_formula_ok &= abs(float(row.get("cash_after_krw", 0)) - float(row.get("cash_before_krw", 0))) < 1e-6
        fill_formula_ok &= abs(float(row["slippage_impact_krw"]) - abs(float(row["fill_price"]) - ref) * float(row["shares"])) < 1e-6
        if truth(row.get("post_cutoff")):
            support_cost_total += float(row["commission_krw"])
            support_slippage_total += float(row["slippage_impact_krw"])
            support_exit_count += 1
        else:
            event_cost_total += float(row["commission_krw"])
            event_slippage_total += float(row["slippage_impact_krw"])
        trade = trade_by_id.get(str(row.get("candidate_id", "")))
        exit_open_parity &= trade is not None and trade.get("exit_price") is not None and not pd.isna(trade.get("exit_price")) and abs(float(trade.get("exit_price")) - ref) <= 0.011
    cash_flag = bool(metrics.get("cash_conservation_pass"))
    entry_count_ok = int(len(entry)) == int(len(trades))
    actual_entries_ok = int(len(executed_entry)) == int(metrics.get("executed_entry_count", -1))
    event_cap_evidence = events.get("event_status", pd.Series(dtype=object)).astype(str) + " " + events.get("reason", pd.Series(dtype=object)).astype(str)
    no_hidden_cap_skip = not event_cap_evidence.str.contains("POSITION_CAP|POSITION_LIMIT|MAX_POSITIONS|MAX_CONCURRENT", case=False, regex=True).any()
    active_tickers: set[str] = set()
    no_same_ticker_overlap = True
    observed_max_positions = 0
    for row in events.to_dict("records"):
        if row.get("event_status") != "EXECUTED":
            continue
        ticker = str(row.get("ticker", "")).zfill(6)
        if row.get("event_type") == "ENTRY":
            no_same_ticker_overlap &= ticker not in active_tickers
            active_tickers.add(ticker)
            observed_max_positions = max(observed_max_positions, len(active_tickers))
        elif row.get("event_type") == "EXIT":
            no_same_ticker_overlap &= ticker in active_tickers
            active_tickers.discard(ticker)
    totals_match = (
        abs(event_cost_total - float(metrics.get("total_commissions_krw") or 0)) < 1e-5
        and abs(event_slippage_total - float(metrics.get("total_slippage_impact_krw") or 0)) < 1e-5
    )
    return {
        "entry_attempt_events_equal_prefixed_trade_rows": bool(entry_count_ok),
        "executed_entry_events_match_summary": bool(actual_entries_ok),
        "all_filled_sides_recalculate_commission_and_slippage": bool(fill_formula_ok),
        "entry_and_exit_fill_prices_match_v2_trade_ledger": bool(entry_open_parity and exit_open_parity),
        "integer_shares_and_inclusive_5m_buy_budget": bool(entry_budget_ok),
        "sale_proceeds_remain_pending_on_exit_execution_day": bool(bool(executed_exit.empty) or (executed_exit["cash_after_krw"].astype(float) - executed_exit["cash_before_krw"].astype(float)).abs().max() < 1e-6),
        "portfolio_cash_conservation": cash_flag,
        "no_hidden_position_cap_skip": bool(no_hidden_cap_skip),
        "no_same_ticker_overlap_or_unmatched_exit": bool(no_same_ticker_overlap),
        "event_cost_totals_match_summary": bool(totals_match),
        "evaluation_window_commission_krw_from_events": float(event_cost_total),
        "evaluation_window_slippage_impact_krw_from_events": float(event_slippage_total),
        "post_cutoff_support_exit_count": int(support_exit_count),
        "post_cutoff_support_commission_krw": float(support_cost_total),
        "post_cutoff_support_slippage_impact_krw": float(support_slippage_total),
        "observed_max_concurrent_positions": int(observed_max_positions),
        "trade_rows": int(len(trades)),
        "entry_attempts": int(len(entry)),
        "executed_entries": int(len(executed_entry)),
        "cash_shortage_skips": int(entry.get("event_status", pd.Series(dtype=object)).eq("SKIPPED_CASH_UNAVAILABLE").sum()) if not entry.empty else 0,
        "other_entry_skips": int(entry.get("event_status", pd.Series(dtype=object)).astype(str).str.startswith("SKIPPED").sum() - entry.get("event_status", pd.Series(dtype=object)).eq("SKIPPED_CASH_UNAVAILABLE").sum()) if not entry.empty else 0,
        "executed_exits": int(len(executed_exit)),
    }


def identity_exclusion_check(*frames: pd.DataFrame) -> dict[str, Any]:
    excluded = {(str(t).zfill(6), str(i).strip().upper()) for t, i in PERMANENT_IDENTITY_EXCLUSIONS}
    leaked: set[tuple[str, str]] = set()
    inspected = 0
    for frame in frames:
        if frame.empty or "ticker" not in frame:
            continue
        isu_column = "isu_cd" if "isu_cd" in frame else "standard_isu_cd" if "standard_isu_cd" in frame else None
        if isu_column is None:
            continue
        for ticker, isu in zip(frame["ticker"], frame[isu_column]):
            inspected += 1
            pair = (str(ticker).zfill(6), str(isu).strip().upper())
            if pair in excluded:
                leaked.add(pair)
    return {"inspected_identity_rows": inspected, "excluded_pairs_leaked": sorted([list(x) for x in leaked]), "no_current_permanent_exclusion_leakage": not leaked}


def main() -> int:
    summary_run = read_json("full_run_execution.json")
    preflight = read_json("preflight.json")
    plan_commit_json = read_json("plan_commit.json")
    plan_commit = str(plan_commit_json["plan_commit"])
    p3_2_policy_audit = read_json("p3_2_policy_consistency_audit.json")
    corporate_action_audit = read_json("corporate_action_audit.json")
    exclusion_source_record = next((row for row in preflight.get("source_file_hashes", []) if row.get("path") == "src/trend_scanner/universe/permanent_identity_exclusions.py"), {})
    exclusion_source_hash_current = sha(ROOT / "src/trend_scanner/universe/permanent_identity_exclusions.py")
    exclusion_policy_matches_preflight = (
        len(PERMANENT_IDENTITY_EXCLUSIONS) == int(preflight.get("universe", {}).get("current_permanent_exclusion_pair_count", -1))
        and exclusion_source_hash_current == exclusion_source_record.get("sha256")
    )
    control = read_csv("control_trades.csv")
    candidate = read_csv("candidate_trades.csv")
    audit = read_csv("candidate_signal_filter_audit.csv")
    resolved_cap_rows = audit.loc[audit.get("mcap_status", pd.Series(dtype=object)).isin(["PASS", "REJECT_BELOW_THRESHOLD"])] if not audit.empty else pd.DataFrame()
    price_audit = read_csv("ticker_price_source_audit.csv")
    adjusted_hashes = read_csv("repository_v2_adjusted_price_file_hashes.csv")
    cap_partitions = read_csv("signal_date_krx_partition_hashes.csv")
    control_events = read_csv("control_portfolio_events.csv")
    candidate_events = read_csv("candidate_portfolio_events.csv")
    control_curve = read_csv("control_daily_equity.csv")
    candidate_curve = read_csv("candidate_daily_equity.csv")
    control_metrics = dict(summary_run["control_sample_metrics"])
    candidate_metrics = dict(summary_run["candidate_sample_metrics"])
    expected_worker_outcomes = int(summary_run.get("eligible_universe_ticker_count", 0) or 0)
    completed_worker_outcomes = int(summary_run.get("evaluator_outcomes", 0) or 0)
    worker_error_count = max(0, expected_worker_outcomes - completed_worker_outcomes)
    control_metrics.update(mdd_independent(control_curve))
    candidate_metrics.update(mdd_independent(candidate_curve))
    reported_mdd_matches = all(
        metrics.get("mdd_pct") is None and summary_run[label].get("mdd_pct") is None
        or metrics.get("mdd_pct") is not None and summary_run[label].get("mdd_pct") is not None and abs(float(metrics["mdd_pct"]) - float(summary_run[label]["mdd_pct"])) < 1e-6
        for metrics, label in ((control_metrics, "control_sample_metrics"), (candidate_metrics, "candidate_sample_metrics"))
    )

    cal = load_rolling_production_market_calendar(ROOT)
    expected_dates = pd.DatetimeIndex(cal.trading_dates).normalize()
    expected_eval = expected_dates[(expected_dates >= pd.Timestamp(EVAL_START)) & (expected_dates <= pd.Timestamp(CUTOFF))]
    source_tickers = set(price_audit.get("ticker", pd.Series(dtype=str)).astype(str).str.zfill(6))
    unavailable_tickers = sorted(price_audit.loc[~price_audit["data_status"].eq("AVAILABLE"), "ticker"].astype(str).str.zfill(6).unique()) if not price_audit.empty else []
    unavailable_reason_counts = (
        price_audit.loc[~price_audit["data_status"].eq("AVAILABLE"), "unavailable_reason"].fillna("UNCLASSIFIED").value_counts().sort_index().to_dict()
        if not price_audit.empty and "unavailable_reason" in price_audit else {}
    )
    bounds_audit = read_csv("identity_repository_v2_bounds.csv")
    unavailable_identity_bounds = []
    if not bounds_audit.empty and "ticker" in bounds_audit:
        unavailable_bounds = bounds_audit.loc[
            bounds_audit["ticker"].astype(str).str.zfill(6).isin(unavailable_tickers)
        ]
        unavailable_identity_bounds = unavailable_bounds.to_dict("records")
    unavailable_reason_diagnostic = {
        "schema": "fast_core_v2_alignment_500b_p3_1_repository_v2_unavailable_reason_diagnostic_v01",
        "unavailable_tickers": unavailable_tickers,
        "repository_v2_loader_reason_counts": unavailable_reason_counts,
        "ticker_outcomes": price_audit.loc[
            ~price_audit.get("data_status", pd.Series(dtype=object)).eq("AVAILABLE")
        ].to_dict("records") if not price_audit.empty else [],
        "matching_pit_identity_price_bounds": unavailable_identity_bounds,
        "limitations": "The loader returns DATA_UNAVAILABLE without exposing whether the adjusted or raw component caused it. Preflight identity-level file presence, read status, date bounds, and hashes are retained separately; no fallback source is substituted.",
    }
    json_write("repository_v2_unavailable_reason_diagnostic.json", unavailable_reason_diagnostic)
    exclusion_audit = identity_exclusion_check(audit, control, candidate, control_events, candidate_events)

    adjusted_hash_mismatches = []
    for row in adjusted_hashes.to_dict("records"):
        source_path = ROOT / str(row.get("path", ""))
        if not source_path.is_file() or sha(source_path) != str(row.get("sha256", "")):
            adjusted_hash_mismatches.append(str(row.get("ticker", "UNKNOWN")))
    adjusted_hashes_ok = not adjusted_hash_mismatches and len(adjusted_hashes) == len(source_tickers - set(unavailable_tickers))

    raw_store = KrxRawStockStore(ROOT / "data/market/raw/krx_stocks/v01")
    verified_cap_partitions = 0
    cap_partition_hash_mismatches = []
    cap_value_mismatches = []
    resolved_cap_by_partition: dict[tuple[str, str], list[dict[str, Any]]] = {}
    if not resolved_cap_rows.empty:
        for cap_row in resolved_cap_rows.to_dict("records"):
            key = (str(cap_row.get("mcap_source_market", "")).upper(), str(cap_row.get("mcap_source_date", ""))[:10])
            resolved_cap_by_partition.setdefault(key, []).append(cap_row)
    for row in cap_partitions.to_dict("records"):
        if str(row.get("status", "")) != "COMPLETE":
            continue
        market = str(row.get("market", "")).upper()
        day = str(row.get("partition_date", ""))[:10]
        manifest = raw_store.get_manifest(market, day) or {}
        try:
            snapshot = raw_store.load_snapshot(market, day)
            loaded_ok = True
        except Exception:
            snapshot = pd.DataFrame()
            loaded_ok = False
        good = loaded_ok and str(manifest.get("file_sha256", "")) == str(row.get("file_sha256", "")) and str(manifest.get("content_sha256", "")) == str(row.get("content_sha256", ""))
        if good:
            verified_cap_partitions += 1
            ticker_caps = {
                str(ticker).zfill(6): group["market_cap"].tolist()
                for ticker, group in snapshot.groupby(snapshot["ticker"].astype(str).str.zfill(6), sort=False)
            }
            for signal in resolved_cap_by_partition.get((market, day), []):
                values = ticker_caps.get(str(signal.get("ticker", "")).zfill(6), [])
                try:
                    matches = len(values) == 1 and int(float(values[0])) == int(float(signal.get("market_cap_krw")))
                except (TypeError, ValueError, OverflowError):
                    matches = False
                if not matches:
                    cap_value_mismatches.append(f"{market}:{day}:{signal.get('ticker')}")
        else:
            cap_partition_hash_mismatches.append(f"{market}:{day}")
    cap_partition_hashes_ok = not cap_partition_hash_mismatches and verified_cap_partitions == int(cap_partitions.get("status", pd.Series(dtype=object)).eq("COMPLETE").sum())
    complete_cap_partition_keys = {
        (str(row.get("market", "")).upper(), str(row.get("partition_date", ""))[:10])
        for row in cap_partitions.to_dict("records") if str(row.get("status", "")) == "COMPLETE"
    }
    resolved_cap_keys_covered = set(resolved_cap_by_partition).issubset(complete_cap_partition_keys)
    cap_values_ok = not cap_value_mismatches and resolved_cap_keys_covered

    audit_map: dict[tuple[str, str, str], dict[str, Any]] = {}
    control_trade_signal_keys = {
        (str(row.get("ticker", "")).zfill(6), str(row.get("isu_cd", "")).strip().upper(), str(row.get("entry_signal_date", ""))[:10])
        for row in control.to_dict("records")
    }
    candidate_trade_signal_keys = {
        (str(row.get("ticker", "")).zfill(6), str(row.get("isu_cd", "")).strip().upper(), str(row.get("entry_signal_date", ""))[:10])
        for row in candidate.to_dict("records")
    }
    sessions = pd.DatetimeIndex(cal.trading_dates).normalize()
    def next_session_after(value: Any) -> str | None:
        day = pd.Timestamp(value).normalize()
        subsequent = sessions[sessions > day]
        return subsequent[0].strftime("%Y-%m-%d") if len(subsequent) else None
    if not audit.empty:
        audit["next_local_execution_date"] = audit["signal_date"].map(next_session_after)
        audit["control_trade_generated"] = audit.apply(lambda r: (str(r.get("ticker", "")).zfill(6), str(r.get("isu_cd", "")).strip().upper(), str(r.get("signal_date", ""))[:10]) in control_trade_signal_keys, axis=1)
        audit["candidate_trade_generated"] = audit.apply(lambda r: (str(r.get("ticker", "")).zfill(6), str(r.get("isu_cd", "")).strip().upper(), str(r.get("signal_date", ""))[:10]) in candidate_trade_signal_keys, axis=1)
        audit["candidate_signal_disposition"] = np.where(
            ~audit["seen_in_candidate_scan"].map(truth), "NOT_IN_CANDIDATE_V2_SCAN",
            np.where(audit["candidate_status"].ne("PASS"), audit["candidate_status"],
                     np.where(audit["candidate_trade_generated"], "TRADE_LEDGER_FROZEN",
                              np.where(pd.to_datetime(audit["next_local_execution_date"]) > pd.Timestamp(CUTOFF), "ENTRY_EXECUTION_AFTER_CUTOFF", "PASS_WITHOUT_TRADE_CHECK_REQUIRED"))),
        )
        audit.to_csv(OUT / "candidate_signal_filter_audit.csv", index=False)
    for row in audit.to_dict("records"):
        key = (str(row.get("ticker", "")).zfill(6), str(row.get("isu_cd", "")).strip().upper(), str(row.get("signal_date", ""))[:10])
        audit_map[key] = row
    control_linked = []
    for row in control.to_dict("records"):
        key = (str(row["ticker"]).zfill(6), str(row["isu_cd"]).strip().upper(), str(row["entry_signal_date"])[:10])
        evidence = audit_map.get(key)
        control_linked.append(evidence is not None and truth(evidence.get("seen_in_control_scan")) and evidence.get("pit_status") == "PASS")
    candidate_linked = []
    for row in candidate.to_dict("records"):
        key = (str(row["ticker"]).zfill(6), str(row["isu_cd"]).strip().upper(), str(row["entry_signal_date"])[:10])
        evidence = audit_map.get(key)
        candidate_linked.append(
            evidence is not None and truth(evidence.get("seen_in_candidate_scan")) and evidence.get("pit_status") == "PASS"
            and evidence.get("candidate_status") == "PASS"
            and float(evidence.get("signal_day_adjusted_close")) > float(evidence.get("ma20")) > float(evidence.get("ma60"))
            and int(float(evidence.get("market_cap_krw"))) >= 500_000_000_000
            and str(evidence.get("mcap_source_date"))[:10] == str(row["entry_signal_date"])[:10]
            and evidence.get("mcap_partition_status") == "COMPLETE"
            and bool(evidence.get("mcap_partition_file_sha256"))
            and bool(evidence.get("mcap_partition_content_sha256"))
        )

    def normalize_trades(df: pd.DataFrame) -> dict[tuple[str, str, str, str], dict[str, Any]]:
        return {identity_signal_key(row): row for row in df.to_dict("records")}
    control_by_signal = normalize_trades(control)
    candidate_by_signal = normalize_trades(candidate)
    shared = sorted(set(control_by_signal) & set(candidate_by_signal))
    parity_fields = ("exit_type", "exit_signal_date", "exit_execution_date", "exit_price", "trade_status")
    shared_exit_parity = all(
        all(str(control_by_signal[k].get(field) or "") == str(candidate_by_signal[k].get(field) or "") for field in parity_fields)
        for k in shared
    )

    eval_dates_ok = True
    for curve in (control_curve, candidate_curve):
        dates = pd.DatetimeIndex(pd.to_datetime(curve.get("date", pd.Series(dtype=str)))).normalize()
        eval_dates_ok &= len(dates) == len(expected_eval) and dates.equals(expected_eval)
    curve_checks = {}
    for label, curve, metrics in (("control", control_curve, control_metrics), ("candidate", candidate_curve, candidate_metrics)):
        valid = curve.loc[curve.get("equity", pd.Series(dtype=float)).notna()].copy() if not curve.empty else pd.DataFrame()
        accounting_ok = True
        if not valid.empty:
            total = valid[["cash", "pending_sale_proceeds", "cash_receivables", "invested_market_value"]].astype(float).sum(axis=1)
            accounting_ok = bool(np.allclose(total, valid["equity"].astype(float), atol=1e-5, rtol=0))
        curve_checks[label] = {
            "daily_rows": int(len(curve)),
            "valid_nav_days": int(curve.get("equity", pd.Series(dtype=float)).notna().sum()),
            "nav_coverage_pct": float(curve.get("equity", pd.Series(dtype=float)).notna().mean() * 100) if not curve.empty else 0.0,
            "equity_accounting_identity": accounting_ok,
            "independent_mdd_pct": metrics.get("mdd_pct"),
            "reported_mdd_pct": summary_run["control_sample_metrics" if label == "control" else "candidate_sample_metrics"].get("mdd_pct"),
        }

    cap_exact_date_ok = bool(resolved_cap_rows.empty or (resolved_cap_rows["mcap_source_date"].astype(str).str[:10] == resolved_cap_rows["signal_date"].astype(str).str[:10]).all())
    cap_hashes_ok = bool(resolved_cap_rows.empty or (resolved_cap_rows[["mcap_partition_file_sha256", "mcap_partition_content_sha256"]].notna().all(axis=None) and resolved_cap_rows["mcap_partition_status"].eq("COMPLETE").all()))
    candidate_predicate_ok = bool(all(candidate_linked))
    control_pit_ok = bool(all(control_linked))
    uncommitted_candidate_passes = audit.loc[
        audit.get("seen_in_candidate_scan", pd.Series(False, index=audit.index)).map(truth)
        & audit.get("candidate_status", pd.Series(dtype=object)).eq("PASS")
        & ~audit.get("candidate_trade_generated", pd.Series(False, index=audit.index)).map(truth)
        & (pd.to_datetime(audit.get("next_local_execution_date", pd.Series(dtype=str))) <= pd.Timestamp(CUTOFF))
    ] if not audit.empty else pd.DataFrame()
    all_entry_dates_ok = bool(
        (pd.to_datetime(control.get("entry_signal_date", pd.Series(dtype=str))) <= pd.Timestamp(CUTOFF)).all()
        and (pd.to_datetime(candidate.get("entry_signal_date", pd.Series(dtype=str))) <= pd.Timestamp(CUTOFF)).all()
        and (pd.to_datetime(control.get("entry_execution_date", pd.Series(dtype=str))) <= pd.Timestamp(CUTOFF)).all()
        and (pd.to_datetime(candidate.get("entry_execution_date", pd.Series(dtype=str))) <= pd.Timestamp(CUTOFF)).all()
    )
    all_portfolio_events = pd.concat([control_events, candidate_events], ignore_index=True)
    support_entries = all_portfolio_events.loc[
        all_portfolio_events.get("event_type", pd.Series(dtype=object)).eq("ENTRY"), "execution_date"
    ].astype(str).eq(SUPPORT) if not all_portfolio_events.empty else pd.Series(dtype=bool)
    no_support_day_entry = bool(not support_entries.any())
    monthly_windows_valid = True
    for row in audit.to_dict("records"):
        day = str(row.get("signal_date", ""))[:10]
        if pd.notna(row.get("ma20_window_last_month")) and pd.notna(row.get("ma60_window_last_month")):
            last_month = str(row.get("ma60_window_last_month", ""))[:7]
            monthly_windows_valid &= bool(last_month and last_month < day[:7])
    audit_signal_keys = [(str(row.get("ticker", "")).zfill(6), str(row.get("isu_cd", "")).strip().upper(), str(row.get("signal_date", ""))[:10]) for row in audit.to_dict("records")]
    unique_signal_audit = len(audit_signal_keys) == len(set(audit_signal_keys))
    control_cost = cost_and_portfolio_checks(control_events, control, control_metrics)
    candidate_cost = cost_and_portfolio_checks(candidate_events, candidate, candidate_metrics)
    candidate_scan_audit = audit.loc[audit.get("seen_in_candidate_scan", pd.Series(dtype=bool)).map(truth)] if not audit.empty else pd.DataFrame()
    price_population_ok = len(source_tickers) == int(summary_run.get("eligible_universe_ticker_count", -1)) and len(price_audit) == len(source_tickers)
    shared_value_parity = shared_exit_parity
    candidate_signal_keys = set(candidate_by_signal)
    control_only_signal_keys = set(control_by_signal) - candidate_signal_keys
    control_only_candidate_ids = {"|".join(key) for key in control_only_signal_keys}
    control_entry_costs = {
        str(row.get("candidate_id", "")): float(row.get("required_total_buy_cost_krw") or 0.0)
        for row in control_events.to_dict("records")
        if row.get("event_type") == "ENTRY" and row.get("event_status") == "EXECUTED"
    }
    control_only_pnl = []
    for row in control_events.to_dict("records"):
        cid = str(row.get("candidate_id", ""))
        if row.get("event_type") != "EXIT" or row.get("event_status") != "EXECUTED" or cid not in control_only_candidate_ids:
            continue
        control_only_pnl.append(float(row.get("notional_krw") or 0.0) - float(row.get("commission_krw") or 0.0) - control_entry_costs.get(cid, 0.0))
    opportunity_diagnostic = {
        "control_trade_signal_rows_absent_from_candidate_ledger": int(len(control_only_signal_keys)),
        "control_only_trades_with_executed_realized_exit": int(len(control_only_pnl)),
        "control_only_realized_net_pnl_krw_actual_control_allocation": float(sum(control_only_pnl)),
        "control_only_positive_realized_pnl_trade_count": int(sum(value > 0 for value in control_only_pnl)),
        "interpretation": "Observed CONTROL portfolio PnL for trade signals absent from candidate ledger; descriptive opportunity diagnostic, not a replay of those trades inside the candidate portfolio.",
    }

    checks = {
        "validated_rolling_calendar_matches_sealed_p3_1_session_count": len(expected_eval) == int(preflight.get("dates", {}).get("evaluation_sessions", -1)),
        "both_nav_curves_cover_exact_calendar_dates": bool(eval_dates_ok),
        "control_trade_signals_match_exact_common_pit_audit": bool(control_pit_ok),
        "candidate_trades_match_both_signal_date_filters": bool(candidate_predicate_ok),
        "candidate_filter_pass_without_pre_cutoff_trade_is_explained": bool(uncommitted_candidate_passes.empty),
        "candidate_mcap_uses_exact_signal_date_and_hashes": bool(cap_exact_date_ok and cap_hashes_ok),
        "krx_exact_signal_partition_files_and_content_reverified": bool(cap_partition_hashes_ok),
        "krx_exact_signal_market_cap_values_recomputed": bool(cap_values_ok),
        "repository_v2_adjusted_price_file_hashes_reverified": bool(adjusted_hashes_ok),
        "monthly_ma_windows_end_before_signal_month": bool(monthly_windows_valid),
        "signal_audit_has_unique_exact_identity_keys": bool(unique_signal_audit),
        "control_and_candidate_trade_sequences_are_contiguous": bool(trade_sequences_contiguous(control, candidate)),
        "current_permanent_identity_exclusions_applied_without_leakage": bool(exclusion_audit["no_current_permanent_exclusion_leakage"]),
        "permanent_exclusion_policy_matches_preflight_hash_and_count": bool(exclusion_policy_matches_preflight),
        "control_and_candidate_common_trades_have_identical_v2_exit_outcomes": bool(shared_value_parity),
        "no_new_entries_after_cutoff_or_on_support_day": bool(all_entry_dates_ok and no_support_day_entry),
        "control_cash_and_cost_integrity": all(bool(v) for k, v in control_cost.items() if k in {"entry_attempt_events_equal_prefixed_trade_rows", "executed_entry_events_match_summary", "all_filled_sides_recalculate_commission_and_slippage", "entry_and_exit_fill_prices_match_v2_trade_ledger", "integer_shares_and_inclusive_5m_buy_budget", "sale_proceeds_remain_pending_on_exit_execution_day", "portfolio_cash_conservation", "no_hidden_position_cap_skip", "no_same_ticker_overlap_or_unmatched_exit", "event_cost_totals_match_summary"}),
        "candidate_cash_and_cost_integrity": all(bool(v) for k, v in candidate_cost.items() if k in {"entry_attempt_events_equal_prefixed_trade_rows", "executed_entry_events_match_summary", "all_filled_sides_recalculate_commission_and_slippage", "entry_and_exit_fill_prices_match_v2_trade_ledger", "integer_shares_and_inclusive_5m_buy_budget", "sale_proceeds_remain_pending_on_exit_execution_day", "portfolio_cash_conservation", "no_hidden_position_cap_skip", "no_same_ticker_overlap_or_unmatched_exit", "event_cost_totals_match_summary"}),
        "control_daily_equity_accounting_identity": bool(curve_checks["control"]["equity_accounting_identity"]),
        "candidate_daily_equity_accounting_identity": bool(curve_checks["candidate"]["equity_accounting_identity"]),
        "independent_daily_equity_mdd_matches_execution_summary": bool(reported_mdd_matches),
        "repository_v2_price_source_roster_matches_pit_tickers": bool(price_population_ok),
        "full_worker_outcomes_match_eligible_universe": summary_run.get("status") == "FULL_COMPLETED" and completed_worker_outcomes == expected_worker_outcomes,
        "no_v2_worker_or_portfolio_execution_errors": worker_error_count == 0 and int(control_metrics.get("source_or_execution_issue_count", 0) or 0) == 0 and int(candidate_metrics.get("source_or_execution_issue_count", 0) or 0) == 0,
    }
    critical_checks = list(checks)
    critical_errors = [key for key in critical_checks if not checks[key]]
    unresolved_price = unavailable_tickers
    unresolved_cap_count = int(audit.get("mcap_status", pd.Series(dtype=object)).eq("UNRESOLVED").sum())
    integrity = {
        "schema": "fast_core_v2_alignment_500b_integrity_audit_v01",
        "status": "PASS" if not critical_errors and not unresolved_price and int(audit.get("mcap_status", pd.Series(dtype=object)).eq("UNRESOLVED").sum()) == 0 else "CHECK_REQUIRED" if not critical_errors else "FAIL",
        "checks": checks,
        "critical_integrity_error_count": len(critical_errors),
        "critical_integrity_errors": critical_errors,
        "worker_error_count": worker_error_count,
        "completed_worker_outcomes": completed_worker_outcomes,
        "expected_worker_outcomes": expected_worker_outcomes,
        "unresolved_universe_price_tickers": unresolved_price,
        "unresolved_universe_price_ticker_count": len(unresolved_price),
        "unresolved_universe_price_reason_counts": unavailable_reason_counts,
        "unresolved_exact_signal_mcap_count": unresolved_cap_count,
        "excluded_identity_audit": exclusion_audit,
        "permanent_exclusion_policy": {
            "pair_count": len(PERMANENT_IDENTITY_EXCLUSIONS),
            "canonical_sha256_from_preflight": preflight.get("universe", {}).get("permanent_exclusion_registry_canonical_sha256"),
            "source_file_sha256_current": exclusion_source_hash_current,
            "source_file_sha256_preflight": exclusion_source_record.get("sha256"),
        },
        "repository_v2_price_hash_audit": {"hash_rows": int(len(adjusted_hashes)), "mismatch_tickers": adjusted_hash_mismatches},
        "krx_partition_hash_audit": {"complete_partition_rows": int(cap_partitions.get("status", pd.Series(dtype=object)).eq("COMPLETE").sum()), "independently_verified_partitions": verified_cap_partitions, "mismatch_partitions": cap_partition_hash_mismatches, "market_cap_value_mismatches": cap_value_mismatches},
        "control_cost_audit": control_cost,
        "candidate_cost_audit": candidate_cost,
        "portfolio_curve_audit": curve_checks,
        "signal_audit_counts": {
            "total_v2_eligible_signals_seen_by_either_scan": int(len(audit)),
            "control_scan_signals": int(audit.get("seen_in_control_scan", pd.Series(dtype=bool)).map(truth).sum()),
            "candidate_scan_signals": int(audit.get("seen_in_candidate_scan", pd.Series(dtype=bool)).map(truth).sum()),
            "candidate_filter_pass_signals": int(candidate_scan_audit.get("candidate_status", pd.Series(dtype=object)).eq("PASS").sum()),
            "candidate_filter_status_counts": candidate_scan_audit.get("candidate_status", pd.Series(dtype=object)).value_counts().sort_index().to_dict(),
            "candidate_trade_rows": int(len(candidate)),
            "mcap_unresolved_signals": int(candidate_scan_audit.get("mcap_status", pd.Series(dtype=object)).eq("UNRESOLVED").sum()),
            "mcap_below_threshold_signals": int(candidate_scan_audit.get("mcap_status", pd.Series(dtype=object)).eq("REJECT_BELOW_THRESHOLD").sum()),
            "ma_unavailable_signals": int(candidate_scan_audit.get("ma_status", pd.Series(dtype=object)).eq("MA_UNAVAILABLE").sum()),
            "alignment_rejected_signals": int(candidate_scan_audit.get("candidate_status", pd.Series(dtype=object)).eq("REJECT_ALIGNMENT").sum()),
        },
        "shared_trade_exit_parity": {"shared_trade_count": len(shared), "identical_exit_fields": shared_exit_parity, "fields": list(parity_fields)},
        "control_only_opportunity_diagnostic": opportunity_diagnostic,
    }
    json_write("integrity_audit.json", integrity)

    control_mdd = control_metrics.get("mdd_pct")
    candidate_mdd = candidate_metrics.get("mdd_pct")
    c_rel = None if control_mdd is None or candidate_mdd is None else float(control_mdd) - float(candidate_mdd)
    mcap_rows = candidate_scan_audit.get("candidate_status", pd.Series(dtype=object)).value_counts().sort_index().to_dict()

    def gate(group_metrics: Mapping[str, Any], *, candidate_group: bool) -> dict[str, Any]:
        nav_coverage = float(group_metrics.get("nav_coverage_pct", 0) or 0) / 100.0
        unresolved_a = bool(unresolved_price) or (candidate_group and unresolved_cap_count > 0)
        a_status = "FAIL" if critical_errors else "CHECK_REQUIRED" if unresolved_a else "PASS"
        costs_ok = all(bool(v) for k, v in (candidate_cost if candidate_group else control_cost).items() if k in {"all_filled_sides_recalculate_commission_and_slippage", "integer_shares_and_inclusive_5m_buy_budget", "portfolio_cash_conservation"})
        b_status = "PASS" if costs_ok else "FAIL"
        tr = group_metrics.get("total_return_pct")
        cg = group_metrics.get("cagr_pct")
        c_status = "CHECK_REQUIRED" if tr is None or cg is None else "PASS" if float(tr) > 0 and float(cg) > 0 else "FAIL"
        mdd = group_metrics.get("mdd_pct")
        if mdd is None:
            d_status = "CHECK_REQUIRED"
        elif float(mdd) < -40:
            d_status = "FAIL"
        elif candidate_group and c_rel is None:
            d_status = "CHECK_REQUIRED"
        elif bool(unresolved_price) or critical_errors or (candidate_group and unresolved_cap_count > 0):
            d_status = "CHECK_REQUIRED"
        elif candidate_group and c_rel is not None and c_rel >= 5.0:
            d_status = "FAIL"
        else:
            d_status = "PASS"
        if nav_coverage < 0.90:
            e_status = "CHECK_REQUIRED"
        elif nav_coverage == 1.0:
            e_status = "EXACT"
        else:
            e_status = "OBSERVED"
        a_reason = "critical structural integrity checks failed" if critical_errors else "unresolved adjusted-price or exact signal-date market-cap input" if unresolved_a else "no material integrity errors"
        return {
            "A_integrity": {"status": a_status, "reason": a_reason},
            "B_costs": {"status": b_status, "all_filled_costs_present": costs_ok},
            "C_profitability": {"status": c_status, "total_return_pct": tr, "cagr_pct": cg},
            "D_mdd": {"status": d_status, "mdd_pct": mdd, "absolute_floor_pct": -40.0, "control_mdd_minus_candidate_mdd_pp": c_rel if candidate_group else None, "relative_failure_threshold_pp": 5.0 if candidate_group else None},
            "E_validity": {"status": e_status, "coverage_pct": group_metrics.get("nav_coverage_pct"), "coverage_class": group_metrics.get("mdd_type"), "valid_days": group_metrics.get("valid_nav_days"), "total_days": group_metrics.get("total_valuation_days")},
        }

    gates = {
        "schema": "fast_core_v2_alignment_500b_p3_1_gate_results_v01",
        "P3-1": {"CONTROL": gate(control_metrics, candidate_group=False), "ALIGNMENT_MCAP_500B": gate(candidate_metrics, candidate_group=True)},
        "whole_five_window_adoption": "NOT_EVALUATED",
        "whole_adoption_status": "NOT_FINAL_5WINDOW",
        "baseline_promotion": "NOT_EVALUATED",
        "official_default_remains": "PATTERN_A_FAST_FINAL_STRATEGY_V02",
        "cash_shortage_is_official_gate": False,
    }
    json_write("gate_results.json", gates)

    # Trading concentration and skipped-cash diagnostics are deliberately not gates.
    def extended_metrics(group: str, trades: pd.DataFrame, events: pd.DataFrame, base: dict[str, Any]) -> dict[str, Any]:
        metrics = dict(base)
        entry_events = events.loc[(events.get("event_type", pd.Series(dtype=object)).eq("ENTRY"))] if not events.empty else pd.DataFrame()
        exit_events = events.loc[(events.get("event_type", pd.Series(dtype=object)).eq("EXIT")) & (events.get("event_status", pd.Series(dtype=object)).eq("EXECUTED"))] if not events.empty else pd.DataFrame()
        support_exits = exit_events.loc[exit_events.get("post_cutoff", pd.Series(False, index=exit_events.index)).map(truth)] if not exit_events.empty else pd.DataFrame()
        in_window_exits = exit_events.loc[~exit_events.get("post_cutoff", pd.Series(False, index=exit_events.index)).map(truth)] if not exit_events.empty else pd.DataFrame()
        trade_by_candidate = {"|".join(identity_signal_key(row)): row for row in trades.to_dict("records")}
        executed_entry_ids = {str(row.get("candidate_id", "")) for row in entry_events.to_dict("records") if row.get("event_status") == "EXECUTED"}
        executed_trade_rows = pd.DataFrame([trade_by_candidate[cid] for cid in executed_entry_ids if cid in trade_by_candidate])
        portfolio_exit_ids = {str(row.get("candidate_id", "")) for row in in_window_exits.to_dict("records")}
        portfolio_exit_trade_rows = pd.DataFrame([trade_by_candidate[cid] for cid in portfolio_exit_ids if cid in trade_by_candidate])
        skipped = entry_events.loc[entry_events.get("event_status", pd.Series(dtype=object)).eq("SKIPPED_CASH_UNAVAILABLE")] if not entry_events.empty else pd.DataFrame()
        skipped_returns = []
        for row in skipped.to_dict("records"):
            trade = trade_by_candidate.get(str(row.get("candidate_id", "")))
            if trade is not None and pd.notna(trade.get("terminal_return")):
                skipped_returns.append(float(trade["terminal_return"]))
        entry_cost = {str(row.get("candidate_id")): float(row.get("required_total_buy_cost_krw") or 0) for row in entry_events.to_dict("records") if row.get("event_status") == "EXECUTED"}
        profits_by_ticker: dict[str, float] = {}
        realized_pnl_by_candidate: dict[str, float] = {}
        # Cutoff-period PnL and concentration exclude the permitted post-cutoff support exit.
        for row in in_window_exits.to_dict("records"):
            cid = str(row.get("candidate_id", ""))
            buy_cost = entry_cost.get(cid, 0.0)
            profit = float(row.get("notional_krw") or 0.0) - float(row.get("commission_krw") or 0.0) - buy_cost
            realized_pnl_by_candidate[cid] = profit
            ticker = str(row.get("ticker", "")).zfill(6)
            profits_by_ticker[ticker] = profits_by_ticker.get(ticker, 0.0) + profit
        total_positive = sum(max(0.0, value) for value in profits_by_ticker.values())
        top5 = sum(sorted((max(0.0, v) for v in profits_by_ticker.values()), reverse=True)[:5])
        top_ticker_trade_share = float(executed_trade_rows.get("ticker", pd.Series(dtype=str)).value_counts(normalize=True).head(1).sum() * 100) if not executed_trade_rows.empty else 0.0
        closed_returns = pd.to_numeric(in_window_exits.get("net_return_pct", pd.Series(dtype=float)), errors="coerce").dropna()
        loss_guard_count = int(executed_trade_rows.get("loss_guard_triggered", pd.Series(dtype=object)).map(truth).sum()) if not executed_trade_rows.empty else 0
        progressed_count = int(executed_trade_rows.get("first_progressed_date", pd.Series(dtype=object)).notna().sum()) if not executed_trade_rows.empty and "first_progressed_date" in executed_trade_rows else 0
        exit_reasons = portfolio_exit_trade_rows.get("exit_type", pd.Series(dtype=str)).value_counts().sort_index().to_dict()
        metrics.update({
            "exit_reason_counts": json.dumps(exit_reasons, ensure_ascii=False),
            "cash_skipped_v2_terminal_return_count": len(skipped_returns),
            "cash_skipped_v2_terminal_return_mean_pct_diagnostic": float(np.mean(skipped_returns)) if skipped_returns else None,
            "cash_skipped_v2_terminal_return_median_pct_diagnostic": float(np.median(skipped_returns)) if skipped_returns else None,
            "top5_ticker_share_of_positive_realized_pnl_pct": top5 / total_positive * 100.0 if total_positive else None,
            "largest_single_ticker_trade_count_share_pct": top_ticker_trade_share,
            "positive_realized_pnl_ticker_count": int(sum(v > 0 for v in profits_by_ticker.values())),
            "realized_portfolio_pnl_krw": float(sum(realized_pnl_by_candidate.values())),
            "win_rate_pct": float((closed_returns > 0).sum() / len(closed_returns) * 100.0) if not closed_returns.empty else None,
            "mean_trade_terminal_return_pct": float(closed_returns.mean()) if not closed_returns.empty else None,
            "median_trade_terminal_return_pct": float(closed_returns.median()) if not closed_returns.empty else None,
            "maximum_trade_terminal_return_pct": float(closed_returns.max()) if not closed_returns.empty else None,
            "minimum_trade_terminal_return_pct": float(closed_returns.min()) if not closed_returns.empty else None,
            "ge_pos_20_count": int((closed_returns >= 20).sum()),
            "ge_pos_50_count": int((closed_returns >= 50).sum()),
            "ge_pos_100_count": int((closed_returns >= 100).sum()),
            "le_neg_10_count": int((closed_returns <= -10).sum()),
            "le_neg_15_count": int((closed_returns <= -15).sum()),
            "le_neg_20_count": int((closed_returns <= -20).sum()),
            "le_neg_30_count": int((closed_returns <= -30).sum()),
            "cash_skipped_trade_count": int(len(skipped)),
            "loss_guard_triggered_trade_count": loss_guard_count,
            "first_progressed_trade_count": progressed_count,
            "never_progressed_trade_count": int(len(executed_trade_rows) - progressed_count),
            "post_cutoff_support_exit_count": int(len(support_exits)),
            "post_cutoff_support_commissions_krw": float(pd.to_numeric(support_exits.get("commission_krw", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()),
            "post_cutoff_support_slippage_krw": float(pd.to_numeric(support_exits.get("slippage_impact_krw", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()),
            "post_cutoff_support_realized_pnl_krw": float(sum(
                float(row.get("notional_krw") or 0.0)
                - float(row.get("commission_krw") or 0.0)
                - entry_cost.get(str(row.get("candidate_id", "")), 0.0)
                for row in support_exits.to_dict("records")
            )),
        })
        return metrics

    control_metrics = extended_metrics("CONTROL", control, control_events, control_metrics)
    candidate_metrics = extended_metrics("ALIGNMENT_MCAP_500B", candidate, candidate_events, candidate_metrics)
    metric_labels = {
        "ending_equity_krw": ("종료일 평가 자산", "KRW"),
        "total_return_pct": ("총수익률", "%"),
        "cagr_pct": ("CAGR", "%"),
        "mdd_pct": ("Observed/Exact MDD", "%"),
        "mdd_type": ("MDD 유형", ""),
        "mdd_peak_date": ("MDD peak", "date"),
        "mdd_trough_date": ("MDD trough", "date"),
        "mdd_recovery_date": ("MDD recovery", "date"),
        "total_valuation_days": ("전체 평가 거래일", "days"),
        "valid_nav_days": ("관측 NAV 거래일", "days"),
        "missing_nav_days": ("결측 NAV 거래일", "days"),
        "nav_coverage_pct": ("NAV coverage", "%"),
        "valuation_unresolved_count": ("미해결 valuation mark", "marks"),
        "eligible_entry_attempts": ("적격 진입 시도", "trades"),
        "cash_shortage_skipped_entries": ("현금 부족 skip", "trades"),
        "cash_shortage_skip_rate_pct": ("현금 부족 skip 비율", "%"),
        "executed_entry_count": ("실제 진입", "trades"),
        "realized_exit_count": ("실현 청산", "trades"),
        "open_at_cutoff_count": ("cutoff 미청산", "positions"),
        "average_concurrent_positions": ("평균 동시 보유", "positions"),
        "maximum_concurrent_positions": ("최대 동시 보유", "positions"),
        "win_rate_pct": ("실현 거래 승률", "%"),
        "average_holding_trading_sessions": ("평균 보유 거래일", "days"),
        "median_holding_trading_sessions": ("중앙 보유 거래일", "days"),
        "turnover_krw": ("회전율 금액", "KRW"),
        "turnover_multiple": ("회전율", "x initial capital"),
        "total_commissions_krw": ("총 수수료", "KRW"),
        "total_slippage_impact_krw": ("총 슬리피지 영향", "KRW"),
        "average_capital_utilization_pct": ("평균 자본 활용", "%"),
        "maximum_capital_utilization_pct": ("최대 자본 활용", "%"),
        "average_cash_ratio_pct": ("평균 현금 비중", "%"),
        "ge_pos_50_count": ("+50% 이상 승자", "trades"),
        "ge_pos_20_count": ("+20% 이상 승자", "trades"),
        "ge_pos_100_count": ("+100% 이상 승자", "trades"),
        "le_neg_10_count": ("-10% 이하 손실", "trades"),
        "le_neg_15_count": ("-15% 이하 손실", "trades"),
        "le_neg_20_count": ("-20% 이하 손실", "trades"),
        "le_neg_30_count": ("-30% 이하 대형 손실", "trades"),
        "mean_trade_terminal_return_pct": ("실제 청산 평균 순수익률", "% net costs"),
        "median_trade_terminal_return_pct": ("실제 청산 중앙 순수익률", "% net costs"),
        "maximum_trade_terminal_return_pct": ("최대 실제 청산 순수익률", "% net costs"),
        "minimum_trade_terminal_return_pct": ("최저 실제 청산 순수익률", "% net costs"),
        "realized_portfolio_pnl_krw": ("실현 포트폴리오 순손익", "KRW"),
        "total_valuation_days": ("전체 평가 거래일", "days"),
        "valid_nav_days": ("유효 NAV 일수", "days"),
        "missing_nav_days": ("결측 NAV 일수", "days"),
        "maximum_consecutive_missing_nav_days": ("최장 연속 NAV 결측", "days"),
        "valuation_unresolved_count": ("미해결 평가 mark", "marks"),
        "mdd_peak_date": ("MDD peak date", "date"),
        "mdd_trough_date": ("MDD trough date", "date"),
        "mdd_recovery_date": ("MDD recovery date", "date"),
        "average_concurrent_positions": ("평균 동시 보유", "positions"),
        "maximum_concurrent_positions": ("최대 동시 보유", "positions"),
        "cash_skipped_trade_count": ("현금 부족 skip 원장 행", "trades"),
        "loss_guard_triggered_trade_count": ("Loss Guard 발동 거래", "trades"),
        "first_progressed_trade_count": ("PROGRESSED 도달 거래", "trades"),
        "never_progressed_trade_count": ("미도달 거래", "trades"),
        "post_cutoff_support_exit_count": ("지원일 이후 cutoff 청산", "trades"),
        "post_cutoff_support_commissions_krw": ("지원일 청산 수수료", "KRW"),
        "post_cutoff_support_slippage_krw": ("지원일 청산 슬리피지", "KRW"),
        "top5_ticker_share_of_positive_realized_pnl_pct": ("상위 5 ticker 실현이익 집중도", "% positive PnL"),
        "largest_single_ticker_trade_count_share_pct": ("최대 단일 ticker 거래 비중", "% trades"),
        "cash_skipped_v2_terminal_return_mean_pct_diagnostic": ("현금 skip V2 terminal return 평균(진단)", "%"),
        "cash_skipped_v2_terminal_return_median_pct_diagnostic": ("현금 skip V2 terminal return 중앙(진단)", "%"),
    }
    metric_rows = []
    for key, (label, unit) in metric_labels.items():
        a, b = control_metrics.get(key), candidate_metrics.get(key)
        delta = None
        if isinstance(a, (int, float, np.integer, np.floating)) and isinstance(b, (int, float, np.integer, np.floating)):
            delta = float(b) - float(a)
        metric_rows.append({"metric": key, "label_ko": label, "unit": unit, "control": a, "alignment_mcap_500b": b, "candidate_minus_control": delta})
    pd.DataFrame(metric_rows).to_csv(OUT / "metrics_comparison.csv", index=False)

    # Severity counts independent issue types, not rows, identities, or dates.
    critical_count = len(critical_errors)
    major_issue_types: list[str] = []
    if unresolved_price:
        major_issue_types.append("P3-1 PIT identities include adjusted-price inputs that are unavailable or unreadable")
    if unresolved_cap_count:
        major_issue_types.append("Candidate V2 signals include unresolved exact signal-date KRX market-cap rows")
    if int(control_metrics.get("valuation_unresolved_count", 0) or 0) or int(candidate_metrics.get("valuation_unresolved_count", 0) or 0):
        major_issue_types.append("At least one held-position valuation mark on an actual KRX session is unresolved")
    if corporate_action_audit.get("status") == "CHECK_REQUIRED":
        major_issue_types.append("P3-1 portfolio exposure intersects the unresolved Koentec cash-exchange settlement")
    minor_issue_types: list[str] = []
    major_count = len(major_issue_types)
    minor_count = len(minor_issue_types)
    severity = {"CRITICAL": critical_count, "MAJOR": major_count, "MINOR": minor_count}
    issue_summary = {
        "schema": "fast_core_v2_alignment_500b_p3_1_issue_summary_v01",
        "counting_unit": "independent issue types, not affected rows, tickers, or sessions",
        "severity_counts": severity,
        "critical_issue_types": critical_errors,
        "major_issue_types": major_issue_types,
        "minor_issue_types": minor_issue_types,
    }
    json_write("issue_summary.json", issue_summary)
    cap_status_counts = mcap_rows
    sample_benchmark = read_json("sample_benchmark.json")
    candidate_open_status = candidate.get("trade_status", pd.Series(dtype=object)).value_counts().sort_index().to_dict()
    control_open_status = control.get("trade_status", pd.Series(dtype=object)).value_counts().sort_index().to_dict()

    def fmt(value: Any, digits: int = 2) -> str:
        if value is None or pd.isna(value):
            return "UNRESOLVED"
        if isinstance(value, (int, np.integer)):
            return f"{int(value):,}"
        if isinstance(value, (float, np.floating)):
            return f"{float(value):,.{digits}f}"
        return str(value)

    display_metrics = [
        ("ending_equity_krw", "종료 자산 (원)"), ("total_return_pct", "총수익률 (%)"), ("cagr_pct", "CAGR (%)"),
        ("mdd_pct", "포트폴리오 MDD (%)"), ("nav_coverage_pct", "NAV coverage (%)"),
        ("mdd_type", "MDD 유형"), ("mdd_peak_date", "MDD peak"), ("mdd_trough_date", "MDD trough"),
        ("mdd_recovery_date", "MDD recovery"), ("total_valuation_days", "전체 평가일"),
        ("valid_nav_days", "관측 NAV일"), ("missing_nav_days", "누락 NAV일"),
        ("maximum_consecutive_missing_nav_days", "최장 연속 NAV 결측일"), ("valuation_unresolved_count", "미해결 valuation marks"),
        ("eligible_entry_attempts", "적격 진입 시도"), ("cash_shortage_skipped_entries", "현금 부족 skip"),
        ("cash_shortage_skip_rate_pct", "현금 부족 skip 비율 (%)"), ("executed_entry_count", "실제 진입"),
        ("realized_exit_count", "실현 청산"), ("open_at_cutoff_count", "cutoff 미청산"),
        ("average_concurrent_positions", "평균 동시 보유 수"),
        ("maximum_concurrent_positions", "최대 동시 보유 수"),
        ("win_rate_pct", "실제 청산 승률 (%)"), ("mean_trade_terminal_return_pct", "실제 청산 평균 순수익률 (%)"),
        ("median_trade_terminal_return_pct", "실제 청산 중앙 순수익률 (%)"), ("average_holding_trading_sessions", "평균 보유 거래일"),
        ("median_holding_trading_sessions", "중앙 보유 거래일"), ("turnover_krw", "회전율 금액 (원)"),
        ("turnover_multiple", "회전율 (초기자본 배수)"),
        ("average_capital_utilization_pct", "평균 자본 활용 (%)"), ("maximum_capital_utilization_pct", "최대 자본 활용 (%)"),
        ("average_cash_ratio_pct", "평균 현금 비중 (%)"), ("maximum_concurrent_positions", "최대 동시 보유 수"),
        ("ge_pos_20_count", "+20% 이상 실제 청산 승자"),
        ("ge_pos_50_count", "+50% 이상 실제 청산 승자"), ("ge_pos_100_count", "+100% 이상 실제 청산 승자"),
        ("le_neg_10_count", "-10% 이하 실제 청산 손실"), ("le_neg_15_count", "-15% 이하 실제 청산 손실"),
        ("le_neg_20_count", "-20% 이하 실제 청산 손실"), ("le_neg_30_count", "-30% 이하 실제 청산 손실"),
        ("loss_guard_triggered_trade_count", "실제 진입 중 Loss Guard 발동"),
        ("first_progressed_trade_count", "실제 진입 중 PROGRESSED 도달"),
        ("never_progressed_trade_count", "실제 진입 중 PROGRESSED 미도달"),
        ("maximum_trade_terminal_return_pct", "최대 실제 청산 수익률 (%)"), ("minimum_trade_terminal_return_pct", "최저 실제 청산 수익률 (%)"),
        ("realized_portfolio_pnl_krw", "cutoff 기간 실현 포트폴리오 순손익 (원)"),
        ("total_commissions_krw", "총 수수료 (원)"), ("total_slippage_impact_krw", "총 슬리피지 (원)"),
        ("post_cutoff_support_exit_count", "지원일 cutoff 청산"),
        ("post_cutoff_support_commissions_krw", "지원일 청산 수수료 (원)"),
        ("post_cutoff_support_slippage_krw", "지원일 청산 슬리피지 (원)"),
        ("top5_ticker_share_of_positive_realized_pnl_pct", "상위 5 ticker 실현이익 집중도 (%)"),
    ]
    table = ["| 지표 | CONTROL | Alignment + 500B | 후보-대조군 |", "|---|---:|---:|---:|"]
    for key, label in display_metrics:
        a, b = control_metrics.get(key), candidate_metrics.get(key)
        delta = float(b) - float(a) if isinstance(a, (int, float, np.integer, np.floating)) and isinstance(b, (int, float, np.integer, np.floating)) else None
        table.append(f"| {label} | {fmt(a)} | {fmt(b)} | {fmt(delta)} |")

    gate_rows = []
    gate_specs = [
        ("A", "A_integrity"), ("B", "B_costs"), ("C", "C_profitability"),
        ("D", "D_mdd"), ("E", "E_validity"),
    ]
    for gate_name, gate_key in gate_specs:
        control_gate = gates["P3-1"]["CONTROL"][gate_key]
        candidate_gate = gates["P3-1"]["ALIGNMENT_MCAP_500B"][gate_key]
        control_text, candidate_text = control_gate["status"], candidate_gate["status"]
        if gate_name == "C":
            control_text += f" (총수익 {fmt(control_gate.get('total_return_pct'))}%, CAGR {fmt(control_gate.get('cagr_pct'))}%)"
            candidate_text += f" (총수익 {fmt(candidate_gate.get('total_return_pct'))}%, CAGR {fmt(candidate_gate.get('cagr_pct'))}%)"
        elif gate_name == "D":
            control_text += f" (MDD {fmt(control_gate.get('mdd_pct'))}%)"
            candidate_text += f" (MDD {fmt(candidate_gate.get('mdd_pct'))}%; CONTROL 상대판정 {candidate_gate.get('status')})"
        elif gate_name == "E":
            control_text += f" ({fmt(control_gate.get('coverage_pct'))}%; {control_gate.get('valid_days')}/{control_gate.get('total_days')}일)"
            candidate_text += f" ({fmt(candidate_gate.get('coverage_pct'))}%; {candidate_gate.get('valid_days')}/{candidate_gate.get('total_days')}일)"
        gate_rows.append(f"| {gate_name} | {control_text} | {candidate_text} |")

    report = "\n".join([
        "# FAST Core V2 Alignment + 500B — P3-1 공식 실전형 포트폴리오 결과",
        "",
        "## 심각도 요약",
        "",
        "| CRITICAL | MAJOR | MINOR |",
        "|---:|---:|---:|",
        f"| {severity['CRITICAL']} | {severity['MAJOR']} | {severity['MINOR']} |",
        "",
        "## 판정",
        "",
        f"- 이전 공식 CONTROL 재사용: **FAIL**. 현재 승인된 {len(PERMANENT_IDENTITY_EXCLUSIONS)}쌍의 정확한 identity 제외 정책 및 unrestricted PIT 조건과 달라 P3-1 CONTROL을 후보와 동일 조건으로 다시 생성했어. 과거 공식 판정은 그대로 보존해.",
        f"- CONTROL / 후보 거래: **{len(control):,} / {len(candidate):,}**. 시총·월간 정배열 후보 gate 결과: `{json.dumps(cap_status_counts, ensure_ascii=False)}`.",
        f"- 미시세 조정가격 입력 {len(unresolved_price):,}종목: 사유별 `{json.dumps(unavailable_reason_counts, ensure_ascii=False)}`. 대표 누락 `{', '.join(unresolved_price[:10])}`(전체 목록은 price-source audit). exact signal-date 시총 UNRESOLVED 신호 {integrity['unresolved_exact_signal_mcap_count']:,}건. 이 입력 누락은 유니버스 분모에서 제외하거나 legacy/API 값으로 대체하지 않았고, 영향 미해결로 A를 CHECK_REQUIRED 처리해.",
        f"- 380440 영구 제외 정책을 두 그룹 공통 pre-signal 유니버스에 적용했어. P3-2 저장 산출물 {p3_2_policy_audit['persisted_p3_2_outputs']['artifact_hashes_rechecked']}/{p3_2_policy_audit['persisted_p3_2_outputs']['artifact_rows_in_prior_invariance_audit']}개 해시가 기존 감사와 일치하고, 저장된 거래/현금/이벤트/valuation 행은 {p3_2_policy_audit['persisted_p3_2_outputs']['target_exact_pair_transaction_or_portfolio_rows']}개야. P3-2 재실행은 하지 않았고 이전 A 상태는 그대로 CHECK_REQUIRED야. 완전 가격자료였다면 어떤 신호가 나왔을지는 UNKNOWN이야.",
        f"- 코엔텍(029960) 기업행동 점검: `{corporate_action_audit.get('status')}`. P3-1에 해당 identity의 cutoff 보유 {corporate_action_audit.get('control_open_at_cutoff_count')} / {corporate_action_audit.get('candidate_open_at_cutoff_count')}건, 지원일 청산 {corporate_action_audit.get('support_day_exit_count')}건. 확인하지 못한 교부금·세금·입금일을 임의 회계 처리하지 않았어.",
        "- P3-1 기간별 예비 A~E 결과는 `gate_results.json`에 있어. 나머지 4개 공식 기간을 실행하지 않았으므로 최종 5기간 판정은 **NOT_FINAL_5WINDOW**, 전체 공식 채택과 기본전략 승격은 **NOT_EVALUATED**야. A FAST Core V2가 공식 기본 전략으로 유지돼.",
        "",
        "### P3-1 예비 A~E 판정",
        "",
        "| 기준 | CONTROL | Alignment + 500B |",
        "|---|---|---|",
        *gate_rows,
        "",
        f"- A의 미해결 가격 입력은 {len(unresolved_price)}종목({json.dumps(unavailable_reason_counts, ensure_ascii=False)}), exact signal-date 시총 UNRESOLVED는 {integrity['unresolved_exact_signal_mcap_count']}건이야. 구조 무결성 오류는 {critical_count}건.",
        "",
        "## CONTROL 대비",
        "",
        *table,
        "",
        "### 추가 원장 진단",
        "",
        f"- 평가 거래일 {len(expected_eval):,}일. CONTROL NAV coverage {fmt(control_metrics.get('nav_coverage_pct'))}%, 후보 {fmt(candidate_metrics.get('nav_coverage_pct'))}%; MDD 종류는 각각 {control_metrics.get('mdd_type')} / {candidate_metrics.get('mdd_type')}.",
        f"- CONTROL V2 신호 원장 cutoff 상태(현금 skip 포함, 실제 포트폴리오 보유 수가 아님): `{json.dumps(control_open_status, ensure_ascii=False)}`. 후보 신호 원장 상태: `{json.dumps(candidate_open_status, ensure_ascii=False)}`. 실제 포트폴리오 cutoff 미청산은 표의 CONTROL {control_metrics.get("open_at_cutoff_count")}건 / 후보 {candidate_metrics.get("open_at_cutoff_count")}건이야.",
        f"- 실제 포트폴리오 청산 exit reason(현금 skip 제외): CONTROL `{control_metrics.get('exit_reason_counts')}`, 후보 `{candidate_metrics.get('exit_reason_counts')}`.",
        f"- 2025-06-02 지원일 cutoff 이전 청산 체결: CONTROL {control_metrics.get('post_cutoff_support_exit_count')}건(수수료 {fmt(control_metrics.get('post_cutoff_support_commissions_krw'))}원, 슬리피지 {fmt(control_metrics.get('post_cutoff_support_slippage_krw'))}원, 실현손익 {fmt(control_metrics.get('post_cutoff_support_realized_pnl_krw'))}원), 후보 {candidate_metrics.get('post_cutoff_support_exit_count')}건(수수료 {fmt(candidate_metrics.get('post_cutoff_support_commissions_krw'))}원, 슬리피지 {fmt(candidate_metrics.get('post_cutoff_support_slippage_krw'))}원, 실현손익 {fmt(candidate_metrics.get('post_cutoff_support_realized_pnl_krw'))}원). 지원일 손익·비용은 평가 cutoff NAV와 기간 성과에서 분리해.",
        f"- 실제 청산 원장의 순수익률(0.1% 슬리피지와 양방향 0.015% 수수료 반영) 평균/중앙: CONTROL {fmt(control_metrics.get('mean_trade_terminal_return_pct'))}% / {fmt(control_metrics.get('median_trade_terminal_return_pct'))}%, 후보 {fmt(candidate_metrics.get('mean_trade_terminal_return_pct'))}% / {fmt(candidate_metrics.get('median_trade_terminal_return_pct'))}%. 최저/최고는 CONTROL {fmt(control_metrics.get('minimum_trade_terminal_return_pct'))}% / {fmt(control_metrics.get('maximum_trade_terminal_return_pct'))}%, 후보 {fmt(candidate_metrics.get('minimum_trade_terminal_return_pct'))}% / {fmt(candidate_metrics.get('maximum_trade_terminal_return_pct'))}%.",
        f"- 후보 원장에 없는 CONTROL 거래 신호 {opportunity_diagnostic['control_trade_signal_rows_absent_from_candidate_ledger']:,}건 중 CONTROL 포트폴리오에서 체결·실현된 {opportunity_diagnostic['control_only_trades_with_executed_realized_exit']:,}건의 실제 순손익은 {fmt(opportunity_diagnostic['control_only_realized_net_pnl_krw_actual_control_allocation'])}원({opportunity_diagnostic['control_only_positive_realized_pnl_trade_count']:,}건 양수)이야. 후보 포트폴리오에 동일하게 재투자했다고 가정한 값은 아니고, 필터로 빠진 CONTROL 수익 기회 진단이야.",
        f"- 현금 부족 skip 후 재생성 없음. cash-skip된 후보 원장의 V2 terminal return 평균/중앙은 각각 {fmt(candidate_metrics.get('cash_skipped_v2_terminal_return_mean_pct_diagnostic'))}% / {fmt(candidate_metrics.get('cash_skipped_v2_terminal_return_median_pct_diagnostic'))}%이며, 포트폴리오 실현손익이 아닌 기회 진단치야.",
        f"- 실제 진입 시도 / 현금 부족 skip: CONTROL {control_metrics.get('eligible_entry_attempts')} / {control_metrics.get('cash_shortage_skipped_entries')} ({fmt(control_metrics.get('cash_shortage_skip_rate_pct'))}%), 후보 {candidate_metrics.get('eligible_entry_attempts')} / {candidate_metrics.get('cash_shortage_skipped_entries')} ({fmt(candidate_metrics.get('cash_shortage_skip_rate_pct'))}%). 현금 부족은 공식 A~E 게이트가 아니야.",
        "- 현금 부족률은 공식 PASS/FAIL 게이트가 아니라 실행 제약 진단치로만 보고했어.",
        "",
        "## 무결성 / provenance",
        "",
        f"- 독립 원장 검증 상태: **{integrity['status']}**; 중대 구조 검사 실패 {critical_count}건. 세부 검사는 `integrity_audit.json` 참조.",
        f"- Severity는 독립 문제 유형 수야(행·종목·날짜 수가 아님). 유형은 `issue_summary.json`에 있어: MAJOR `{json.dumps(major_issue_types, ensure_ascii=False)}`.",
        f"- 대표 샘플: {sample_benchmark.get('sample_ticker_count')} ticker, CONTROL/후보 신호거래 {sample_benchmark.get('control_trade_count')}/{sample_benchmark.get('candidate_trade_count')}, 후보 필터 감사 {sample_benchmark.get('candidate_signal_audit_count')}행; worker {sample_benchmark.get('workers')}, 측정시간 {fmt(sample_benchmark.get('wall_seconds_including_portfolio_replays'))}초, 예상 전체 {fmt(sample_benchmark.get('estimated_full_wall_hours_by_staged_estimate'), 2)}시간. 샘플/전체 실행 요약은 각각 `sample_benchmark.json`, `full_run_execution.json`에 있어.",
        f"- 전체 실행: worker {summary_run.get('workers')}, 유니버스 {summary_run.get('eligible_universe_ticker_count'):,} ticker, CONTROL/후보 signal trade {len(control):,}/{len(candidate):,}; CPU {fmt(summary_run.get('cpu_seconds'))}초, RSS peak {fmt(summary_run.get('max_rss_mb'))} MB.",
        f"- Worker 오류 {worker_error_count}건 ({completed_worker_outcomes:,}/{expected_worker_outcomes:,} ticker outcome 완료); 포트폴리오 실행 오류 CONTROL/후보 {control_metrics.get('source_or_execution_issue_count', 0)}/{candidate_metrics.get('source_or_execution_issue_count', 0)}건.",
        f"- 계획/정책 봉인 commit: `{plan_commit}`. 결과 경로: `{OUT.relative_to(ROOT)}/`.",
        "- 원천 문서, 실행 코드, Repository V2 adjusted 가격 파일, rolling authority, exact KRX cap partitions 및 산출물 SHA-256은 `source_manifest.json`과 `artifact_hashes.json`에 기록했어.",
        "",
    ])
    (OUT / "report.md").write_text(report, encoding="utf-8")

    plan_path = OUT / "plan.md"
    plan_commit_json["plan_sha256"] = sha(plan_path)
    plan_commit_json["plan_commit_pushed"] = True
    json_write("plan_commit.json", plan_commit_json)

    summary = {
        "schema": "fast_core_v2_alignment_500b_p3_1_summary_v01",
        "work_id": "FAST_CORE_V2_ALIGNMENT_500B_P3_1_OFFICIAL_REALISTIC_PORTFOLIO_V01",
        "full_execution_status": summary_run.get("status"),
        "worker_error_count": worker_error_count,
        "period": {"id": "P3-1", "start": EVAL_START, "cutoff": CUTOFF, "execution_support": SUPPORT},
        "control_reuse_audit": read_json("control_reuse_audit.json"),
        "plan_commit": plan_commit_json,
        "sample_benchmark": read_json("sample_benchmark.json"),
        "full_execution": summary_run,
        "control_metrics": control_metrics,
        "candidate_metrics": candidate_metrics,
        "candidate_minus_control": {key: (candidate_metrics.get(key) - control_metrics.get(key) if isinstance(candidate_metrics.get(key), (int, float)) and isinstance(control_metrics.get(key), (int, float)) else None) for key in set(candidate_metrics) | set(control_metrics)},
        "preliminary_gates": gates,
        "integrity_audit_path": "integrity_audit.json",
        "candidate_adoption": "NOT_EVALUATED",
        "baseline_promotion": "NOT_EVALUATED",
        "official_default": "PATTERN_A_FAST_FINAL_STRATEGY_V02",
    }
    json_write("summary.json", summary)

    # Refresh source provenance using the sealed plan and the exact output inputs.
    plan_hash = sha(plan_path)
    source_paths = [
        "docs/validation/official_strategy_adoption_criteria.md",
        "docs/validation/backtest_common_rules.md",
        "docs/strategies/strategy_lifecycle.md",
        "docs/patterns/pattern_a_fast/strategy/version_02/README.md",
        "docs/patterns/pattern_a_fast/strategy/version_02/OFFICIAL_ADOPTION_REVALIDATION_PLAN_V02.md",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_realistic_v01/plan.md",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_realistic_v01/execution_contract.json",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_realistic_v01/run_official_realistic_replay.py",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_realistic_v01/finalize_research_artifacts.py",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_realistic_v01/report.md",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_data_nav_closure_v01/report.md",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_data_nav_closure_v01/price_input_124_audit.csv",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_data_nav_closure_v01/integrity_validation.json",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_data_nav_closure_v01/corporate_action_audit.md",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p3_1_ma60_vs_bullish_alignment_simple_backtest_v01/report.md",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p3_1_ma60_vs_bullish_alignment_simple_backtest_v01/preflight.json",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p3_1_ma60_vs_bullish_alignment_simple_backtest_v01/p3_1_execution_audit.json",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p3_1_ma60_vs_bullish_alignment_simple_backtest_v01/p3_1_control_trades.csv",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p3_1_ma60_vs_bullish_alignment_simple_backtest_v01/p3_1_alignment_trades.csv",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p3_2_380440_single_period_exclusion_v01/report.md",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p3_2_380440_single_period_exclusion_v01/scope_decision.json",
        "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p3_2_380440_single_period_exclusion_v01/gate_results.json",
        "src/trend_scanner/universe/permanent_identity_exclusions.py",
        "src/trend_scanner/validation/pattern_a_fast_core_v02_reentry.py",
        "scripts/run_v2_official_adoption_revalidation_v02.py",
        "scripts/run_fastcore_neg40_weak_protect_p2_1.py",
        "src/trend_scanner/data/repository_v2.py",
        "src/trend_scanner/data/repository_v2_loader.py",
        "src/trend_scanner/data/market_calendar.py",
        "src/trend_scanner/data/rolling_market_data_refresh.py",
        "src/trend_scanner/data/krx_raw_stock_store.py",
        "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json",
        "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json",
        str((OUT / "run_official_realistic_replay.py").relative_to(ROOT)),
        str((OUT / "finalize_research_artifacts.py").relative_to(ROOT)),
        str((OUT / "seal_preflight.py").relative_to(ROOT)),
        str((OUT / "audit_p3_2_policy_consistency.py").relative_to(ROOT)),
        str((OUT / "audit_corporate_action.py").relative_to(ROOT)),
    ]
    source_rows = [{"path": p, "sha256": sha(ROOT / p)} for p in source_paths]
    data_paths = [
        "data/market/rolling_authority/manifest.json", "data/market/rolling_authority/merged_pit_intervals.json",
        "data/market/rolling_authority/merged_trading_calendar.json", "data/market/raw/krx_stocks/v01/manifest.sqlite3",
    ]
    data_rows = [{"path": p, "sha256": sha(ROOT / p)} for p in data_paths]
    source_manifest = {
        "schema": "fast_core_v2_alignment_500b_source_manifest_v02",
        "task_id": summary["work_id"],
        "plan_commit": plan_commit,
        "plan_sha256": plan_hash,
        "initial_head": preflight.get("head"),
        "initial_origin_main": preflight.get("origin_main"),
        "execution_base_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "execution_settings": {"worker_count": summary_run.get("workers"), "portfolio_event_workers": 1, "external_api_requests": 0},
        "source_files": source_rows,
        "authority_data_files": data_rows,
        "repository_v2_adjusted_price_hashes_path": "repository_v2_adjusted_price_file_hashes.csv",
        "repository_v2_adjusted_price_hashes_file_sha256": sha(OUT / "repository_v2_adjusted_price_file_hashes.csv"),
        "ticker_price_source_audit_path": "ticker_price_source_audit.csv",
        "ticker_price_source_audit_file_sha256": sha(OUT / "ticker_price_source_audit.csv"),
        "repository_v2_unavailable_reason_diagnostic_path": "repository_v2_unavailable_reason_diagnostic.json",
        "repository_v2_unavailable_reason_diagnostic_sha256": sha(OUT / "repository_v2_unavailable_reason_diagnostic.json"),
        "krx_signal_partition_hashes_path": "signal_date_krx_partition_hashes.csv",
        "krx_signal_partition_hashes_file_sha256": sha(OUT / "signal_date_krx_partition_hashes.csv"),
        "krx_signal_partition_count": int(len(cap_partitions)),
        "exact_signal_candidate_audit_file_sha256": sha(OUT / "candidate_signal_filter_audit.csv"),
        "excluded_identity_pair_count": len(PERMANENT_IDENTITY_EXCLUSIONS),
        "excluded_identity_pair_canonical_sha256": preflight.get("universe", {}).get("permanent_exclusion_registry_canonical_sha256"),
        "excluded_identity_pair_hash_scheme": preflight.get("universe", {}).get("permanent_exclusion_hash_scheme"),
        "price_source_unavailable_tickers": unavailable_tickers,
        "price_source_unavailable_reason_counts": unavailable_reason_counts,
        "p3_2_policy_consistency_audit_sha256": sha(OUT / "p3_2_policy_consistency_audit.json"),
        "corporate_action_audit_sha256": sha(OUT / "corporate_action_audit.json"),
        "provenance_contract": "RepositoryV2 adjusted prices; rolling merged PIT/calendar; verified exact signal-date KRX raw MKTCAP partitions; no API/fallback/current survivor roster",
    }
    json_write("source_manifest.json", source_manifest)
    contract = read_json("execution_contract.json")
    contract["status"] = "P3_1_FULL_REPLAY_COMPLETE"
    contract["plan_commit"] = plan_commit
    contract["candidate_adoption"] = "NOT_EVALUATED"
    contract["baseline_promotion"] = "NOT_EVALUATED"
    contract["official_default_remains"] = "PATTERN_A_FAST_FINAL_STRATEGY_V02"
    json_write("execution_contract.json", contract)

    hashes = []
    for path in sorted(OUT.iterdir()):
        if path.is_file() and path.name != "artifact_hashes.json":
            hashes.append({"path": path.name, "sha256": sha(path), "bytes": path.stat().st_size})
    json_write("artifact_hashes.json", {"schema": "fast_core_v2_alignment_500b_artifact_hashes_v01", "files": hashes})

    # Re-hash the final sources after README and report generation. artifact_hashes.json is excluded from itself by design.
    print(json.dumps({"report": str(OUT / "report.md"), "severity": severity, "gates": gates["P3-1"], "control_trades": len(control), "candidate_trades": len(candidate), "unavailable_price_tickers": unavailable_tickers, "integrity_status": integrity["status"]}, ensure_ascii=False, indent=2, default=json_default))
    return 0 if not critical_errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
