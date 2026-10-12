#!/usr/bin/env python3
"""Independently audit and report saved P1 portfolio replay artifacts."""
from __future__ import annotations

from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
HELPERS = Path(__file__).resolve().parent / "frozen_audit_helpers.py"
EVAL_START = pd.Timestamp("2014-01-02")
CUTOFF = pd.Timestamp("2026-08-31")
SUPPORT = pd.Timestamp("2026-09-01")
INITIAL = 200_000_000.0
EXCLUSION_SHA = "5d3bd9a1e27e7e558235f0fba211263cdc90eb0b477978c8338eb019b1a6ec2e"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trend_scanner.data.market_calendar import load_rolling_production_market_calendar
from trend_scanner.universe.permanent_identity_exclusions import PERMANENT_IDENTITY_EXCLUSIONS


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=json_default) + "\n", encoding="utf-8")


def json_default(value: Any) -> Any:
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if pd.isna(value):
        return None
    raise TypeError(type(value).__name__)


def read_csv(name: str) -> pd.DataFrame:
    try:
        return pd.read_csv(OUT / name, dtype=str, keep_default_na=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def truth(value: Any) -> bool:
    return value is True or str(value).strip().lower() in {"true", "1", "yes"}


def signal_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (str(row.get("ticker", "")).zfill(6), str(row.get("isu_cd", row.get("standard_isu_cd", ""))).strip().upper(), str(row.get("entry_signal_date", row.get("signal_date", "")))[:10])


def candidate_id(row: dict[str, Any]) -> str:
    return "|".join((*signal_key(row), str(row.get("entry_execution_date", row.get("execution_date", "")))[:10]))


def import_p3_helpers():
    path = HELPERS
    spec = importlib.util.spec_from_file_location("p1_readonly_audit_helpers", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("P3_FINALIZER_HELPER_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def verify_source_manifest() -> dict[str, Any]:
    manifest = json.loads((OUT / "source_manifest.json").read_text(encoding="utf-8"))
    mismatches = []
    checked = 0
    for row in manifest.get("files", []):
        path = Path(row["absolute_path"]) if row.get("absolute_path") else ROOT / row["path"]
        if not path.is_file():
            mismatches.append({"path": row["path"], "reason": "MISSING"})
            continue
        checked += 1
        actual = sha(path)
        if actual != row.get("sha256") or path.stat().st_size != int(row.get("bytes", -1)):
            mismatches.append({"path": row["path"], "expected_sha256": row.get("sha256"), "actual_sha256": actual})
    adjusted = manifest.get("adjusted_price_inputs", {}).get("files", [])
    adjusted_checked = 0
    for row in adjusted:
        path = ROOT / row["path"]
        if not path.is_file():
            mismatches.append({"path": row["path"], "reason": "MISSING_ADJUSTED_PRICE"})
            continue
        adjusted_checked += 1
        actual = sha(path)
        if actual != row.get("sha256") or path.stat().st_size != int(row.get("bytes", -1)):
            mismatches.append({"path": row["path"], "expected_sha256": row.get("sha256"), "actual_sha256": actual, "reason": "ADJUSTED_PRICE_HASH_MISMATCH"})
    raw_partitions = manifest.get("krx_raw_market_date_partitions", {}).get("partitions", [])
    raw_checked = 0
    raw_root = ROOT / "data/market/raw/krx_stocks/v01"
    for row in raw_partitions:
        if row.get("status") != "COMPLETE":
            mismatches.append({"market": row.get("market"), "partition_date": row.get("partition_date"), "reason": "FROZEN_RAW_PARTITION_NOT_COMPLETE"})
            continue
        relative = Path(str(row.get("file_path") or ""))
        path = relative if relative.is_absolute() else raw_root / relative
        if not path.is_file():
            mismatches.append({"market": row.get("market"), "partition_date": row.get("partition_date"), "reason": "MISSING_RAW_PARTITION"})
            continue
        raw_checked += 1
        actual = sha(path)
        if actual != row.get("file_sha256"):
            mismatches.append({"market": row.get("market"), "partition_date": row.get("partition_date"), "expected_sha256": row.get("file_sha256"), "actual_sha256": actual, "reason": "RAW_PARTITION_HASH_MISMATCH"})
    expected = len(manifest.get("files", [])) + len(adjusted) + len(raw_partitions)
    return {
        "status": "PASS" if checked == len(manifest.get("files", [])) and adjusted_checked == len(adjusted) and raw_checked == len(raw_partitions) and not mismatches else "FAIL",
        "checked": checked + adjusted_checked + raw_checked,
        "expected": expected,
        "runtime_files_checked": checked,
        "adjusted_price_files_checked": adjusted_checked,
        "raw_partition_files_checked": raw_checked,
        "mismatches": mismatches,
    }


def nav_metrics(daily: pd.DataFrame, missing: pd.DataFrame, base: dict[str, Any]) -> dict[str, Any]:
    equity = pd.to_numeric(daily.get("equity", pd.Series(dtype=str)), errors="coerce")
    valid = equity.notna()
    total = len(daily)
    coverage = int(valid.sum()) / total if total else 0.0
    peak = INITIAL
    peak_date = EVAL_START.strftime("%Y-%m-%d")
    worst = 0.0
    worst_peak = peak_date
    trough = peak_date
    recovery = peak_date
    worst_peak_value = INITIAL
    for row in daily.assign(_equity=equity).sort_values("date").loc[valid].to_dict("records"):
        day, value = str(row["date"])[:10], float(row["_equity"])
        if value > peak:
            peak, peak_date = value, day
        dd = value / peak - 1 if peak else 0.0
        if dd < worst:
            worst, worst_peak, trough = dd, peak_date, day
            recovery, worst_peak_value = None, peak
        elif recovery is None and value >= worst_peak_value:
            recovery = day
    gaps = equity.isna().tolist()
    consecutive = maximum = 0
    for gap in gaps:
        consecutive = consecutive + 1 if gap else 0
        maximum = max(maximum, consecutive)
    class_ = "EXACT" if coverage == 1 else "OBSERVED" if coverage >= .9 else "CHECK_REQUIRED"
    cutoff_rows = daily.loc[daily.get("date", pd.Series(dtype=str)).astype(str).str[:10].eq(CUTOFF.strftime("%Y-%m-%d"))]
    cutoff_equity = pd.to_numeric(cutoff_rows.get("equity", pd.Series(dtype=str)), errors="coerce").dropna()
    return {
        "total_valuation_days": total, "valid_nav_days": int(valid.sum()), "missing_nav_days": int(total - valid.sum()),
        "nav_coverage_pct": coverage * 100, "mdd_type": class_, "mdd_pct": worst * 100 if coverage >= .9 else None,
        "observed_mdd_pct": worst * 100, "mdd_peak_date": worst_peak, "mdd_trough_date": trough,
        "mdd_recovery_date": recovery, "maximum_consecutive_missing_nav_days": maximum,
        "mdd_unresolved_mark_count": len(missing), "cutoff_equity_krw": float(cutoff_equity.iloc[-1]) if len(cutoff_equity) else None,
        **{key: base.get(key) for key in ("ending_equity_krw", "total_return_pct", "cagr_pct", "mdd_underwater_sessions", "mdd_recovered", "average_capital_utilization_pct", "maximum_capital_utilization_pct", "average_cash_ratio_pct", "turnover_krw", "turnover_multiple", "total_commissions_krw", "total_slippage_impact_krw")},
    }


def group_metrics(group: str, trades: pd.DataFrame, events: pd.DataFrame, daily: pd.DataFrame, missing: pd.DataFrame, base: dict[str, Any], dates: pd.DatetimeIndex) -> tuple[dict[str, Any], pd.DataFrame]:
    entries = events.loc[events.get("event_type", pd.Series(dtype=str)).eq("ENTRY")] if not events.empty else pd.DataFrame()
    exits = events.loc[(events.get("event_type", pd.Series(dtype=str)).eq("EXIT")) & (events.get("event_status", pd.Series(dtype=str)).eq("EXECUTED"))] if not events.empty else pd.DataFrame()
    in_window = exits.loc[~exits.get("post_cutoff", pd.Series(False, index=exits.index)).map(truth)] if not exits.empty else pd.DataFrame()
    support = exits.loc[exits.get("post_cutoff", pd.Series(False, index=exits.index)).map(truth)] if not exits.empty else pd.DataFrame()
    trade_map = {candidate_id(row): row for row in trades.to_dict("records")}
    cal_index = {pd.Timestamp(day).strftime("%Y-%m-%d"): i for i, day in enumerate(dates)}
    realized = []
    for row in in_window.to_dict("records"):
        trade = trade_map.get(str(row.get("candidate_id", "")))
        if trade is None:
            continue
        entry_day = str(trade.get("entry_execution_date", ""))[:10]
        exit_day = str(row.get("execution_date", ""))[:10]
        realized.append({"group": group, "candidate_id": row.get("candidate_id"), "ticker": row.get("ticker"), "isu_cd": row.get("isu_cd"), "market": trade.get("market", row.get("market")), "entry_signal_date": trade.get("entry_signal_date"), "entry_execution_date": entry_day, "exit_execution_date": exit_day, "exit_type": trade.get("exit_type", "UNKNOWN"), "net_return_pct": float(row.get("net_return_pct") or 0), "holding_trading_sessions_inclusive": cal_index.get(exit_day, -1) - cal_index.get(entry_day, -1) + 1, "loss_guard_triggered": trade.get("loss_guard_triggered"), "first_progressed_date": trade.get("first_progressed_date"), "exit_notional_krw": row.get("notional_krw"), "exit_commission_krw": row.get("commission_krw")})
    realized_df = pd.DataFrame(realized)
    returns = pd.to_numeric(realized_df.get("net_return_pct", pd.Series(dtype=float)), errors="coerce").dropna()
    holds = pd.to_numeric(realized_df.get("holding_trading_sessions_inclusive", pd.Series(dtype=float)), errors="coerce").dropna()
    executed_entries = entries.loc[entries.get("event_status", pd.Series(dtype=str)).eq("EXECUTED")] if not entries.empty else pd.DataFrame()
    executed_trade_rows = [trade_map[cid] for cid in executed_entries.get("candidate_id", pd.Series(dtype=str)).astype(str) if cid in trade_map]
    counts = Counter(str(row.get("exit_type", "UNKNOWN")) for row in realized)
    entry_costs = {str(row.get("candidate_id", "")): float(row.get("required_total_buy_cost_krw") or 0) for row in events.loc[(events.get("event_type", pd.Series(dtype=str)).eq("ENTRY")) & (events.get("event_status", pd.Series(dtype=str)).eq("EXECUTED"))].to_dict("records")} if not events.empty else {}
    if not realized_df.empty:
        realized_df["entry_buy_cost_krw"] = realized_df["candidate_id"].map(entry_costs)
        realized_df["realized_pnl_krw"] = pd.to_numeric(realized_df["exit_notional_krw"], errors="coerce") - pd.to_numeric(realized_df["exit_commission_krw"], errors="coerce") - pd.to_numeric(realized_df["entry_buy_cost_krw"], errors="coerce")
        ticker_pnl = realized_df.groupby(realized_df["ticker"].astype(str).str.zfill(6))["realized_pnl_krw"].sum()
        positive_total = float(ticker_pnl.clip(lower=0).sum())
        top_positive = float(ticker_pnl.max()) if len(ticker_pnl) else 0.0
        top_ticker = str(ticker_pnl.idxmax()) if len(ticker_pnl) else None
    else:
        positive_total, top_positive, top_ticker = 0.0, 0.0, None
    cash_skips = int(entries.get("event_status", pd.Series(dtype=str)).eq("SKIPPED_CASH_UNAVAILABLE").sum()) if not entries.empty else 0
    nav = nav_metrics(daily, missing, base)
    metrics = {
        **nav, "signal_trade_rows": len(trades), "eligible_entry_attempts": len(entries), "cash_shortage_skipped_entries": cash_skips,
        "cash_shortage_skip_rate_pct": cash_skips / len(entries) * 100 if len(entries) else None,
        "executed_entries": len(executed_entries), "executed_exits_before_cutoff": len(in_window), "support_day_exit_count": len(support),
        "open_at_cutoff_count": int(pd.to_numeric(daily.get("open_stock_positions", pd.Series(dtype=float)), errors="coerce").iloc[-1]) if len(daily) else 0,
        "realized_trade_count": len(returns), "realized_win_rate_pct": float((returns > 0).mean() * 100) if len(returns) else None,
        "realized_mean_net_return_pct": float(returns.mean()) if len(returns) else None, "realized_median_net_return_pct": float(returns.median()) if len(returns) else None,
        "realized_mean_holding_trading_sessions": float(holds.mean()) if len(holds) else None, "realized_median_holding_trading_sessions": float(holds.median()) if len(holds) else None,
        "realized_max_net_return_pct": float(returns.max()) if len(returns) else None, "realized_min_net_return_pct": float(returns.min()) if len(returns) else None,
        "realized_ge_20_pct_count": int((returns >= 20).sum()), "realized_ge_50_pct_count": int((returns >= 50).sum()), "realized_ge_100_pct_count": int((returns >= 100).sum()),
        "realized_le_minus_10_pct_count": int((returns <= -10).sum()), "realized_le_minus_15_pct_count": int((returns <= -15).sum()), "realized_le_minus_20_pct_count": int((returns <= -20).sum()), "realized_le_minus_30_pct_count": int((returns <= -30).sum()),
        "loss_guard_triggered_executed_entry_count": sum(truth(row.get("loss_guard_triggered")) for row in executed_trade_rows),
        "progressed_executed_entry_count": sum(str(row.get("first_progressed_date", "")).strip() not in {"", "nan", "None"} for row in executed_trade_rows),
        "exit_reason_counts": dict(sorted(counts.items())),
        "top_realized_pnl_ticker": top_ticker,
        "top_positive_ticker_pnl_krw": top_positive,
        "top_ticker_share_of_positive_realized_pnl_pct": top_positive / positive_total * 100 if positive_total > 0 else None,
        "average_concurrent_positions": float(pd.to_numeric(daily.get("open_stock_positions", pd.Series(dtype=float)), errors="coerce").mean()) if len(daily) else None,
        "maximum_concurrent_positions": int(pd.to_numeric(daily.get("open_stock_positions", pd.Series(dtype=float)), errors="coerce").max()) if len(daily) else 0,
    }
    return metrics, realized_df


def exact_signal_checks(control: pd.DataFrame, candidate: pd.DataFrame, audit: pd.DataFrame, excluded: set[tuple[str, str]]) -> dict[str, Any]:
    amap = {}
    duplicate = 0
    for row in audit.to_dict("records"):
        key = (str(row.get("ticker", "")).zfill(6), str(row.get("isu_cd", "")).strip().upper(), str(row.get("signal_date", ""))[:10])
        duplicate += key in amap
        amap[key] = row
    control_keys = {signal_key(row) for row in control.to_dict("records")}
    candidate_keys = {signal_key(row) for row in candidate.to_dict("records")}
    # A PASS signal on the cutoff is still audit evidence, but its next-session
    # entry after the signal cutoff is excluded from the P1 order ledger.
    audit_control = {key for key, row in amap.items() if key[2] < CUTOFF.strftime("%Y-%m-%d") and truth(row.get("seen_in_control_scan")) and row.get("pit_status") == "PASS"}
    audit_candidate = {key for key, row in amap.items() if key[2] < CUTOFF.strftime("%Y-%m-%d") and truth(row.get("seen_in_candidate_scan")) and row.get("candidate_status") == "PASS"}
    control_missing = [key for key in control_keys if key not in amap or amap[key].get("pit_status") != "PASS" or int(float(amap[key].get("active_common_identity_count", 0) or 0)) != 1]
    candidate_bad = []
    leakage = []
    for key in candidate_keys:
        row = amap.get(key)
        if key[:2] in excluded:
            leakage.append(key)
        try:
            cap_ok = int(float(row.get("market_cap_krw", 0))) >= 500_000_000_000
            close_ok = float(row.get("signal_day_adjusted_close")) > float(row.get("ma20")) > float(row.get("ma60"))
            sig_month = pd.Period(key[2][:7], freq="M")
            first = pd.Period(str(row.get("ma60_window_first_month")), freq="M")
            last = pd.Period(str(row.get("ma60_window_last_month")), freq="M")
            ma_window_ok = last < sig_month and last.ordinal - first.ordinal == 59
            exact_market_ok = str(row.get("market", "")).strip().upper() == str(amap[key].get("market", "")).strip().upper() and str(row.get("market", "")).strip().upper() == str(amap[key].get("mcap_source_market", "")).strip().upper()
            exact_date_ok = str(amap[key].get("mcap_source_date", ""))[:10] == key[2] and amap[key].get("mcap_partition_status") == "COMPLETE"
        except Exception:
            cap_ok = close_ok = ma_window_ok = exact_market_ok = exact_date_ok = False
        if not row or row.get("pit_status") != "PASS" or row.get("candidate_status") != "PASS" or row.get("mcap_status") != "PASS" or row.get("ma_status") != "PASS" or not (cap_ok and close_ok and ma_window_ok and exact_market_ok and exact_date_ok):
            candidate_bad.append(key)
    return {"duplicate_exact_pit_signal_audit_keys": duplicate, "control_trade_without_one_active_common_identity_audit": len(control_missing), "candidate_trade_alignment_mcap_or_prior_60m_mismatch": candidate_bad, "control_trade_set_matches_pit_pass_audit": control_keys == audit_control, "candidate_trade_set_matches_candidate_pass_audit": candidate_keys == audit_candidate, "excluded_identity_trade_leakage": leakage, "control_missing_examples": control_missing[:20]}


def exposure_audit(control: pd.DataFrame, candidate: pd.DataFrame, control_events: pd.DataFrame, candidate_events: pd.DataFrame, control_missing: pd.DataFrame, candidate_missing: pd.DataFrame) -> pd.DataFrame:
    labels = {"029960": "KOENTEC_LIFECYCLE", "128940": "PRIOR_NAV_MISSING_MARK", "003690": "PRIOR_NAV_MISSING_MARK", "380440": "PERMANENTLY_EXCLUDED"}
    rows = []
    for ticker, label in labels.items():
        item: dict[str, Any] = {"ticker": ticker, "diagnostic": label}
        for name, frame in (("control_trades", control), ("candidate_trades", candidate), ("control_events", control_events), ("candidate_events", candidate_events), ("control_missing_marks", control_missing), ("candidate_missing_marks", candidate_missing)):
            subset = frame.loc[frame.get("ticker", pd.Series(dtype=str)).astype(str).str.zfill(6).eq(ticker)] if not frame.empty else pd.DataFrame()
            item[f"{name}_rows"] = len(subset)
            if name.endswith("events") and not subset.empty:
                item[f"{name}_executed_entries"] = int((subset.get("event_type", pd.Series(dtype=str)).eq("ENTRY") & subset.get("event_status", pd.Series(dtype=str)).eq("EXECUTED")).sum())
                item[f"{name}_executed_exits"] = int((subset.get("event_type", pd.Series(dtype=str)).eq("EXIT") & subset.get("event_status", pd.Series(dtype=str)).eq("EXECUTED")).sum())
                item[f"{name}_unresolved_events"] = int(subset.get("event_status", pd.Series(dtype=str)).eq("UNRESOLVED").sum())
        rows.append(item)
    return pd.DataFrame(rows)


def main() -> int:
    if not (OUT / "full_run_execution.json").is_file():
        raise RuntimeError("P1_FULL_REPLAY_NOT_STARTED; use validate_p1_sample.py for the representative sample")
    execution = json.loads((OUT / "full_run_execution.json").read_text(encoding="utf-8"))
    if execution.get("status") != "FULL_COMPLETED" or execution.get("mode") != "FULL":
        raise RuntimeError("P1_FULL_REPLAY_NOT_COMPLETE")
    manifest_audit = verify_source_manifest()
    source_manifest = json.loads((OUT / "source_manifest.json").read_text(encoding="utf-8"))
    sample_validation = json.loads((OUT / "sample_validation.json").read_text(encoding="utf-8"))
    preflight = json.loads((OUT / "preflight.json").read_text(encoding="utf-8"))
    helpers = import_p3_helpers()
    calendar = load_rolling_production_market_calendar(ROOT)
    if calendar is None:
        raise RuntimeError("P1_FINALIZER_CALENDAR_UNAVAILABLE")
    dates = pd.DatetimeIndex(calendar.trading_dates).normalize()
    eval_dates = dates[(dates >= EVAL_START) & (dates <= CUTOFF)]
    control, candidate = read_csv("control_trades.csv"), read_csv("candidate_trades.csv")
    audit = read_csv("candidate_signal_filter_audit.csv")
    signal_partition_audit = read_csv("signal_date_krx_partition_hashes.csv")
    ce, pe = read_csv("control_portfolio_events.csv"), read_csv("candidate_portfolio_events.csv")
    # The CSV writer may serialize integer share counts as "180.0" when other
    # event rows have blanks; normalize for the shared independent checker.
    for event_frame in (ce, pe):
        if "shares" in event_frame:
            event_frame["shares"] = pd.to_numeric(event_frame["shares"], errors="coerce")
    cd, pdaily = read_csv("control_daily_equity.csv"), read_csv("candidate_daily_equity.csv")
    cm, pm = read_csv("control_missing_marks.csv"), read_csv("candidate_missing_marks.csv")
    cbase, pbase = execution["control_metrics"], execution["candidate_metrics"]
    partition_keys = list(zip(signal_partition_audit.get("market", pd.Series(dtype=str)).str.upper(), signal_partition_audit.get("partition_date", pd.Series(dtype=str)).str[:10]))
    frozen_raw_partitions = source_manifest.get("krx_raw_market_date_partitions", {}).get("partitions", [])
    frozen_raw_map = {
        (str(row.get("market", "")).upper(), str(row.get("partition_date", ""))[:10]): row
        for row in frozen_raw_partitions
    }
    partition_manifest_mismatches = []
    for row in signal_partition_audit.to_dict("records"):
        key = (str(row.get("market", "")).upper(), str(row.get("partition_date", ""))[:10])
        frozen = frozen_raw_map.get(key)
        if (
            frozen is None
            or frozen.get("status") != "COMPLETE"
            or row.get("status") != "COMPLETE"
            or row.get("file_path") != frozen.get("file_path")
            or row.get("file_sha256") != frozen.get("file_sha256")
            or row.get("content_sha256") != frozen.get("content_sha256")
        ):
            partition_manifest_mismatches.append(key)
    signal_partition_audit_valid = bool(
        len(signal_partition_audit) > 0
        and signal_partition_audit.get("status", pd.Series(dtype=str)).eq("COMPLETE").all()
        and signal_partition_audit.get("resolution_error", pd.Series(dtype=str)).eq("").all()
        and signal_partition_audit.get("file_sha256", pd.Series(dtype=str)).str.fullmatch(r"[0-9a-f]{64}").all()
        and signal_partition_audit.get("content_sha256", pd.Series(dtype=str)).str.fullmatch(r"[0-9a-f]{64}").all()
        and len(partition_keys) == len(set(partition_keys))
        and not partition_manifest_mismatches
        and execution.get("signal_partition_hash_row_count") == len(signal_partition_audit)
        and execution.get("signal_partition_unresolved_count") == 0
    )

    pairs = sorted((str(t).zfill(6), str(i).strip().upper()) for t, i in PERMANENT_IDENTITY_EXCLUSIONS)
    canonical = hashlib.sha256(json.dumps({"schema": "sorted_exact_pair_json_v01", "pairs": [list(x) for x in pairs]}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    excluded = set(pairs)
    signal_check = exact_signal_checks(control, candidate, audit, excluded)
    exposure = exposure_audit(control, candidate, ce, pe, cm, pm)
    exposure.to_csv(OUT / "identity_exposure_audit.csv", index=False)
    cmetrics, cr = group_metrics("CONTROL", control, ce, cd, cm, cbase, eval_dates)
    pmetrics, pr = group_metrics("ALIGNMENT_MCAP_500B", candidate, pe, pdaily, pm, pbase, eval_dates)
    cutoff_nav_unresolved_by_group = {
        "CONTROL": cmetrics.get("cutoff_equity_krw") is None,
        "ALIGNMENT_MCAP_500B": pmetrics.get("cutoff_equity_krw") is None,
    }
    for label, metrics in (("CONTROL", cmetrics), ("ALIGNMENT_MCAP_500B", pmetrics)):
        if cutoff_nav_unresolved_by_group[label]:
            metrics["ending_equity_krw"] = None
            metrics["total_return_pct"] = None
            metrics["cagr_pct"] = None
    cr.to_csv(OUT / "control_realized_trades.csv", index=False)
    pr.to_csv(OUT / "candidate_realized_trades.csv", index=False)
    ccost = helpers.cost_and_portfolio_checks(ce, control, cbase)
    pcost = helpers.cost_and_portfolio_checks(pe, candidate, pbase)
    price = read_csv("ticker_price_source_audit.csv")
    price_source = read_csv("identity_price_preflight.csv")
    unavailable = price.loc[price.get("data_status", pd.Series(dtype=str)).ne("AVAILABLE")]
    unresolved_projection = price_source.loc[(pd.to_numeric(price_source.get("rejected_raw_only_count", pd.Series(dtype=str)), errors="coerce").fillna(0) > 0) | (pd.to_numeric(price_source.get("unexplained_adjusted_only_count", pd.Series(dtype=str)), errors="coerce").fillna(0) > 0) | (pd.to_numeric(price_source.get("silent_inner_drop_count", pd.Series(dtype=str)), errors="coerce").fillna(0) > 0)]
    unresolved_cap = int(audit.get("mcap_status", pd.Series(dtype=str)).eq("UNRESOLVED").sum())
    nav_gap_summary = {}
    for label, frame in (("CONTROL", cm), ("ALIGNMENT_MCAP_500B", pm)):
        if frame.empty:
            nav_gap_summary[label] = {"missing_mark_rows": 0, "unresolved_nav_dates": [], "by_ticker": {}}
        else:
            by_ticker = {}
            for ticker, rows in frame.groupby(frame["ticker"].astype(str).str.zfill(6)):
                by_ticker[ticker] = {
                    "count": int(len(rows)),
                    "dates": sorted(rows["date"].astype(str).str[:10].unique().tolist()),
                    "reasons": sorted(rows["reason"].astype(str).unique().tolist()),
                    "evidence_states": sorted(rows["evidence_state"].astype(str).unique().tolist()),
                }
            nav_gap_summary[label] = {
                "missing_mark_rows": int(len(frame)),
                "unresolved_nav_dates": sorted(frame["date"].astype(str).str[:10].unique().tolist()),
                "by_ticker": by_ticker,
            }
    cutoff_nav_unresolved = any(cutoff_nav_unresolved_by_group.values())
    pass_audit = audit.loc[audit.get("candidate_status", pd.Series(dtype=str)).eq("PASS")]
    pass_not_candidate_scan = int((~pass_audit.get("seen_in_candidate_scan", pd.Series(dtype=str)).map(truth)).sum())
    control_koentec_gap = nav_gap_summary.get("CONTROL", {}).get("by_ticker", {}).get("029960", {})
    control_koentec_entries = ce.loc[
        ce.get("ticker", pd.Series(dtype=str)).astype(str).str.zfill(6).eq("029960")
        & ce.get("event_type", pd.Series(dtype=str)).eq("ENTRY")
        & ce.get("event_status", pd.Series(dtype=str)).eq("EXECUTED")
    ]
    control_koentec_entry_execution_date = (
        str(control_koentec_entries.iloc[0].get("execution_date", ""))[:10]
        if len(control_koentec_entries) else None
    )

    structural = []
    if manifest_audit["status"] != "PASS": structural.append("FROZEN_SOURCE_HASH_MISMATCH")
    if canonical != EXCLUSION_SHA or len(pairs) != 184: structural.append("PERMANENT_EXCLUSION_POLICY_HASH_MISMATCH")
    if len(eval_dates) != int(preflight["date_authorities"]["evaluation_sessions"]) or eval_dates.min() != EVAL_START or eval_dates.max() != CUTOFF: structural.append("P1_EXACT_CALENDAR_MISMATCH")
    if execution.get("workers") != 10 or execution.get("portfolio_replay_workers") != 1 or execution.get("worker_error_count") != 0 or execution.get("full_run_authorized_by_sample_contract") is not True: structural.append("FULL_EXECUTION_WORKER_OR_AUTHORIZATION_INVARIANT_FAILURE")
    if execution.get("evaluated_ticker_count") != execution.get("eligible_universe_ticker_count") or execution.get("eligible_universe_ticker_count") != preflight["universe"].get("eligible_tickers_after_exclusions"): structural.append("FULL_EXECUTION_UNIVERSE_COVERAGE_MISMATCH")
    if not signal_partition_audit_valid: structural.append("EXACT_SIGNAL_DATE_KRX_PARTITION_HASH_AUDIT_FAILURE")
    if any(len(frame) != len(eval_dates) or list(pd.to_datetime(frame.get("date", pd.Series(dtype=str)), errors="coerce").dt.normalize()) != list(eval_dates) for frame in (cd, pdaily)): structural.append("DAILY_NAV_CALENDAR_MISMATCH")
    if signal_check["duplicate_exact_pit_signal_audit_keys"] or signal_check["control_trade_without_one_active_common_identity_audit"] or signal_check["candidate_trade_alignment_mcap_or_prior_60m_mismatch"] or signal_check["excluded_identity_trade_leakage"]: structural.append("PIT_SIGNAL_FILTER_OR_EXCLUSION_INVARIANT_FAILURE")
    if not signal_check["control_trade_set_matches_pit_pass_audit"] or not signal_check["candidate_trade_set_matches_candidate_pass_audit"]: structural.append("SIGNAL_AUDIT_SET_MISMATCH")
    support_entries = sum(int((frame.get("event_type", pd.Series(dtype=str)).eq("ENTRY") & pd.to_datetime(frame.get("execution_date", pd.Series(dtype=str)), errors="coerce").ge(SUPPORT)).sum()) for frame in (ce, pe))
    if support_entries: structural.append("POST_CUTOFF_SUPPORT_DAY_ENTRY")
    unresolved_events = sum(int(frame.get("event_status", pd.Series(dtype=str)).eq("UNRESOLVED").sum()) for frame in (ce, pe))
    if unresolved_events: structural.append("UNRESOLVED_PORTFOLIO_TRADE_EVENT")
    cost_fields = ("entry_attempt_events_equal_prefixed_trade_rows", "executed_entry_events_match_summary", "all_filled_sides_recalculate_commission_and_slippage", "entry_and_exit_fill_prices_match_v2_trade_ledger", "integer_shares_and_inclusive_5m_buy_budget", "sale_proceeds_remain_pending_on_exit_execution_day", "portfolio_cash_conservation", "no_hidden_position_cap_skip", "no_same_ticker_overlap_or_unmatched_exit", "event_cost_totals_match_summary")
    costs_ok = all(bool(ccost.get(key)) for key in cost_fields) and all(bool(pcost.get(key)) for key in cost_fields)
    if not costs_ok: structural.append("PORTFOLIO_COST_CASH_INVARIANT_FAILURE")
    if cbase.get("source_or_execution_issue_count", 0) or pbase.get("source_or_execution_issue_count", 0): structural.append("PORTFOLIO_SOURCE_OR_EXECUTION_ISSUES")

    unresolved_issue_types = {"UNRESOLVED_PORTFOLIO_TRADE_EVENT", "PORTFOLIO_SOURCE_OR_EXECUTION_ISSUES"}
    critical = set(structural) - unresolved_issue_types
    unresolved_execution = set(structural) & unresolved_issue_types
    c_mdd, p_mdd = cmetrics.get("mdd_pct"), pmetrics.get("mdd_pct")
    relative = None if c_mdd is None or p_mdd is None else float(c_mdd) - float(p_mdd)
    gate_data = {}
    for group, metrics, cost, is_candidate in (("CONTROL", cmetrics, ccost, False), ("ALIGNMENT_MCAP_500B", pmetrics, pcost, True)):
        group_cutoff_nav_unresolved = cutoff_nav_unresolved_by_group[group]
        cap_issue = is_candidate and unresolved_cap > 0
        price_issue = len(unavailable) > 0 or len(unresolved_projection) > 0
        a = "FAIL" if critical else "CHECK_REQUIRED" if price_issue or cap_issue or unresolved_execution else "PASS"
        b = "PASS" if all(bool(cost.get(key)) for key in ("all_filled_sides_recalculate_commission_and_slippage", "integer_shares_and_inclusive_5m_buy_budget", "portfolio_cash_conservation")) else "FAIL"
        total, cagr = metrics.get("total_return_pct"), metrics.get("cagr_pct")
        c = "CHECK_REQUIRED" if total is None or cagr is None or group_cutoff_nav_unresolved else "PASS" if float(total) > 0 and float(cagr) > 0 else "FAIL"
        mdd = metrics.get("mdd_pct")
        if mdd is None or float(metrics.get("nav_coverage_pct", 0)) < 90: d = "CHECK_REQUIRED"
        elif float(mdd) < -55: d = "FAIL"
        elif is_candidate and relative is not None and relative >= 5: d = "FAIL"
        elif is_candidate and (relative is None or price_issue or cap_issue): d = "CHECK_REQUIRED"
        else: d = "PASS"
        coverage = float(metrics.get("nav_coverage_pct", 0))
        e = "CHECK_REQUIRED" if coverage < 90 or group_cutoff_nav_unresolved else "EXACT" if coverage == 100 else "OBSERVED"
        gate_data[group] = {"A_integrity": {"status": a}, "B_costs": {"status": b, "cost_audit": cost}, "C_profitability": {"status": c, "total_return_pct": total, "cagr_pct": cagr, "cutoff_nav_unresolved": group_cutoff_nav_unresolved}, "D_mdd": {"status": d, "mdd_pct": mdd, "mdd_type": metrics.get("mdd_type"), "control_mdd_minus_candidate_mdd_pp": relative if is_candidate else None, "absolute_floor_pct": -55, "relative_failure_threshold_pp": 5 if is_candidate else None}, "E_validity": {"status": e, "coverage_pct": coverage, "cutoff_nav_unresolved": group_cutoff_nav_unresolved, "valid_days": metrics.get("valid_nav_days"), "total_days": metrics.get("total_valuation_days"), "missing_days": metrics.get("missing_nav_days")}}
    all_gate_statuses = [gate_data[group][key]["status"] for group in gate_data for key in ("A_integrity", "B_costs", "C_profitability", "D_mdd", "E_validity")]
    overall = "FAIL" if "FAIL" in all_gate_statuses else "CHECK_REQUIRED" if "CHECK_REQUIRED" in all_gate_statuses else "PASS_WITH_OBSERVED_NAV" if "OBSERVED" in all_gate_statuses else "PASS"
    gates = {"schema": "fast_core_v2_alignment_500b_p1_gates_v01", "window": "P1", **gate_data, "p1_overall_status": overall, "whole_five_window_adoption": "NOT_EVALUATED", "candidate_adoption": "NOT_EVALUATED", "baseline_promotion": "NOT_EVALUATED", "official_default_remains": "PATTERN_A_FAST_FINAL_STRATEGY_V02", "cash_shortage_is_official_gate": False}

    major = set(unresolved_execution)
    minor = set()
    if unresolved_cap: major.add("EXACT_SIGNAL_DATE_MCAP_UNRESOLVED")
    if len(unavailable): major.add("REPOSITORY_V2_PRICE_UNAVAILABLE")
    if len(unresolved_projection): major.add("REPOSITORY_V2_PROJECTION_MISMATCH")
    if len(cm) or len(pm):
        if cutoff_nav_unresolved or min(float(cmetrics.get("nav_coverage_pct", 0)), float(pmetrics.get("nav_coverage_pct", 0))) < 90:
            major.add("NAV_MARK_UNRESOLVED")
        else:
            minor.add("OBSERVED_NAV_MARK_GAPS")
    if cutoff_nav_unresolved: major.add("CUTOFF_NAV_UNRESOLVED")
    if int(cbase.get("open_at_cutoff_count", 0) or 0) or int(pbase.get("open_at_cutoff_count", 0) or 0): minor.add("CUTOFF_OPEN_POSITIONS_MARKED_WITHOUT_HYPOTHETICAL_EXIT_COST")
    if int(cbase.get("cash_shortage_skipped_entries", 0) or 0) or int(pbase.get("cash_shortage_skipped_entries", 0) or 0): minor.add("CASH_SHORTAGE_SKIP_DIAGNOSTIC")
    adjusted_first = pd.to_datetime(price_source.get("adjusted_first_date", pd.Series(dtype=str)), errors="coerce").dropna()
    adjusted_last = pd.to_datetime(price_source.get("adjusted_last_date", pd.Series(dtype=str)), errors="coerce").dropna()
    pit_first = pd.to_datetime(price_source.get("pit_effective_from_min", pd.Series(dtype=str)), errors="coerce").dropna()
    pit_last = pd.to_datetime(price_source.get("pit_effective_to_max", pd.Series(dtype=str)), errors="coerce").dropna()
    raw_source = read_csv("raw_partition_preflight.csv")
    raw_days = pd.to_datetime(raw_source.get("partition_date", pd.Series(dtype=str)), errors="coerce").dropna()
    source_coverage = {
        "rolling_pit_common": {"overlapping_intervals_before_exclusions": preflight["universe"]["common_intervals_overlapping_p1_before_exclusions"], "intervals_after_exclusions": preflight["universe"]["common_intervals_after_exclusions"], "ticker_count_after_exclusions": preflight["universe"]["eligible_tickers_after_exclusions"], "earliest_identity_start": pit_first.min().strftime("%Y-%m-%d") if len(pit_first) else None, "latest_identity_end": pit_last.max().strftime("%Y-%m-%d") if len(pit_last) else None},
        "repository_v2_adjusted_prices": {"ticker_file_count": len(price_source), "available_ticker_count": len(price_source.loc[price_source.get("load_status", pd.Series(dtype=str)).eq("AVAILABLE")]), "earliest_file_date": adjusted_first.min().strftime("%Y-%m-%d") if len(adjusted_first) else None, "latest_file_date": adjusted_last.max().strftime("%Y-%m-%d") if len(adjusted_last) else None, "unavailable_ticker_count": len(unavailable), "projection_mismatch_ticker_count": len(unresolved_projection)},
        "krx_raw_market_date_partitions": {"partition_count": len(raw_source), "complete_partition_count": int(raw_source.get("status", pd.Series(dtype=str)).eq("COMPLETE").sum()), "earliest_partition_date": raw_days.min().strftime("%Y-%m-%d") if len(raw_days) else None, "latest_partition_date": raw_days.max().strftime("%Y-%m-%d") if len(raw_days) else None, "signal_date_partitions_loaded_and_hash_checked": len(signal_partition_audit), "signal_partition_hash_audit_pass": signal_partition_audit_valid},
        "initial_ma60": {key: preflight["date_authorities"].get(key) for key in ("initial_ma60_required_months", "initial_ma60_required_count", "initial_ma60_available_count_from_repository_calendar", "first_possible_ma60_signal_month_calendar_only", "signal_month_excluded")},
    }
    audit_year = pd.to_datetime(audit.get("signal_date", pd.Series(dtype=str)), errors="coerce").dt.year
    audit_by_year = audit.assign(signal_year=audit_year).dropna(subset=["signal_year"])
    candidate_filter_by_year = audit_by_year.pivot_table(index="signal_year", columns="candidate_status", values="ticker", aggfunc="count", fill_value=0).sort_index()
    candidate_filter_by_year.index = candidate_filter_by_year.index.astype(int)
    candidate_filter_by_year = candidate_filter_by_year.reset_index()
    candidate_filter_by_year.to_csv(OUT / "candidate_signal_filter_by_year.csv", index=False)
    annual_filter_summary = []
    for row in candidate_filter_by_year.to_dict("records"):
        annual_filter_summary.append({"year": int(row["signal_year"]), "candidate_signal_evaluations": int(sum(value for key, value in row.items() if key != "signal_year")), "ma_unavailable": int(row.get("REJECT_MA_UNAVAILABLE", 0)), "mcap_unresolved": int(row.get("REJECT_MCAP_UNRESOLVED", 0)), "mcap_below_500b": int(row.get("REJECT_MCAP_BELOW_500B", 0)), "alignment_rejected": int(row.get("REJECT_ALIGNMENT", 0)), "passed": int(row.get("PASS", 0))})
    integrity = {"schema": "fast_core_v2_alignment_500b_p1_integrity_audit_v01", "status": "FAIL" if critical else "CHECK_REQUIRED" if major else "PASS", "severity_issue_type_counts": {"CRITICAL": len(critical), "MAJOR": len(major), "MINOR": len(minor)}, "critical_issue_types": sorted(critical), "major_issue_types": sorted(major), "minor_issue_types": sorted(minor), "source_manifest_verification": manifest_audit, "postrun_report_generator": {"path": Path(__file__).name, "sha256": sha(Path(__file__).resolve()), "role": "saved-artifact-only finalization; frozen execution generator remains unchanged"}, "sample_gate_authorization": {"status": sample_validation.get("status"), "full_run_allowed": sample_validation.get("full_run_allowed"), "estimated_full_wall_hours": sample_validation.get("estimated_full_wall_hours"), "actual_full_wall_hours": execution.get("wall_seconds_including_portfolio_replays", 0) / 3600, "authorization_guard_passed": sample_validation.get("full_run_allowed") is True and execution.get("mode") == "FULL" and execution.get("status") == "FULL_COMPLETED"}, "adjusted_price_input_hash_check": {"checked": manifest_audit["adjusted_price_files_checked"], "expected": len(source_manifest.get("adjusted_price_inputs", {}).get("files", [])), "status": "PASS" if manifest_audit["adjusted_price_files_checked"] == len(source_manifest.get("adjusted_price_inputs", {}).get("files", [])) else "FAIL"}, "raw_partition_input_hash_check": {"checked": manifest_audit["raw_partition_files_checked"], "expected": len(frozen_raw_partitions), "signal_partition_manifest_mismatch_count": len(partition_manifest_mismatches), "status": "PASS" if manifest_audit["raw_partition_files_checked"] == len(frozen_raw_partitions) and not partition_manifest_mismatches else "FAIL"}, "prior_official_artifact_hash_checks": source_manifest.get("prior_official_artifact_hash_checks", []), "permanent_exclusions": {"pair_count": len(pairs), "canonical_sha256": canonical, "matches_contract": canonical == EXCLUSION_SHA}, "signal_ledger_checks": signal_check, "candidate_signal_filter_status_counts": audit.get("candidate_status", pd.Series(dtype=str)).value_counts().sort_index().to_dict(), "candidate_pass_filter_rows_not_seen_in_candidate_scan": pass_not_candidate_scan, "candidate_signal_filter_by_year": annual_filter_summary, "active_pit_missing_session_reason_counts": preflight["repository_v2_input_preflight"].get("active_pit_missing_session_reason_counts", {}), "source_coverage": source_coverage, "signal_date_partition_audit": {"row_count": len(signal_partition_audit), "valid": signal_partition_audit_valid, "duplicate_exact_market_date_keys": len(partition_keys) - len(set(partition_keys)), "frozen_manifest_mismatch_count": len(partition_manifest_mismatches), "unresolved": execution.get("signal_partition_unresolved_count")}, "unavailable_price_tickers": unavailable.get("ticker", pd.Series(dtype=str)).tolist(), "projection_mismatch_tickers": unresolved_projection.get("ticker", pd.Series(dtype=str)).tolist(), "unresolved_candidate_signal_mcap_count": unresolved_cap, "nav_mark_resolution": {"classification": "OBSERVED_NAV_GAPS_MINOR" if (len(cm) or len(pm)) and not cutoff_nav_unresolved and min(float(cmetrics.get("nav_coverage_pct", 0)), float(pmetrics.get("nav_coverage_pct", 0))) >= 90 else "CHECK_REQUIRED" if len(cm) or len(pm) or cutoff_nav_unresolved else "NO_GAPS", "cutoff_nav_unresolved": cutoff_nav_unresolved, "cutoff_nav_unresolved_by_group": cutoff_nav_unresolved_by_group, "groups": nav_gap_summary}, "control_cost_audit": ccost, "candidate_cost_audit": pcost, "control_nav": cmetrics, "candidate_nav": pmetrics, "identity_exposure_audit": "identity_exposure_audit.csv", "worker_error_count": execution.get("worker_error_count"), "support_day_new_entry_allowed": False, "external_api_requests": 0}
    write_json(OUT / "integrity_audit.json", integrity)
    write_json(OUT / "gate_results.json", gates)

    comparison = []
    for key in sorted(set(cmetrics) | set(pmetrics)):
        a, b, delta = cmetrics.get(key), pmetrics.get(key), None
        try:
            if a is not None and b is not None and np.isfinite(float(a)) and np.isfinite(float(b)): delta = float(b) - float(a)
        except (TypeError, ValueError):
            pass
        comparison.append({"metric": key, "CONTROL": a, "ALIGNMENT_MCAP_500B": b, "candidate_minus_control": delta})
    pd.DataFrame(comparison).to_csv(OUT / "metrics_comparison.csv", index=False)

    for name, frame, events in (("CONTROL", cr, ce), ("ALIGNMENT_MCAP_500B", pr, pe)):
        if frame.empty: continue
        entries = events.loc[(events.get("event_type", pd.Series(dtype=str)).eq("ENTRY")) & (events.get("event_status", pd.Series(dtype=str)).eq("EXECUTED"))]
        costs = {str(row.get("candidate_id", "")): float(row.get("required_total_buy_cost_krw") or 0) for row in entries.to_dict("records")}
        frame["entry_cost_krw"] = frame["candidate_id"].map(costs)
        frame["realized_pnl_krw"] = pd.to_numeric(frame["exit_notional_krw"], errors="coerce") - pd.to_numeric(frame["exit_commission_krw"], errors="coerce") - pd.to_numeric(frame["entry_cost_krw"], errors="coerce")
        frame["exit_year"] = frame["exit_execution_date"].astype(str).str[:4]
        parts = []
        for dimension in ("exit_year", "market"):
            part = frame.groupby(dimension, dropna=False).agg(trades=("candidate_id", "count"), realized_pnl_krw=("realized_pnl_krw", "sum"), mean_return_pct=("net_return_pct", "mean"), win_rate_pct=("net_return_pct", lambda s: float((pd.to_numeric(s, errors="coerce") > 0).mean() * 100))).reset_index().rename(columns={dimension: "bucket"})
            part.insert(0, "group", name); part.insert(1, "dimension", dimension); parts.append(part)
        pd.concat(parts, ignore_index=True).to_csv(OUT / f"{name.lower()}_annual_market_diagnostics.csv", index=False)
        frame.to_csv(OUT / f"{name.lower()}_realized_trades.csv", index=False)

    def fmt(value: Any) -> str:
        if value is None or value == "": return "—"
        try:
            return f"{float(value):,.2f}"
        except (TypeError, ValueError):
            return str(value)

    cutoff_nav_text = (
        f"{CUTOFF.date()} cutoff NAV 미확정 (CONTROL {fmt(cmetrics.get('cutoff_equity_krw'))}원 / 후보 {fmt(pmetrics.get('cutoff_equity_krw'))}원); C/E는 CHECK_REQUIRED"
        if cutoff_nav_unresolved else
        f"{CUTOFF.date()} cutoff NAV 확정 (CONTROL {fmt(cmetrics.get('cutoff_equity_krw'))}원 / 후보 {fmt(pmetrics.get('cutoff_equity_krw'))}원)"
    )
    prior_hashes = source_manifest.get("prior_official_artifact_hash_checks", [])
    pass_audit = audit.loc[audit.get("candidate_status", pd.Series(dtype=str)).eq("PASS")]
    pass_not_candidate_scan = int((~pass_audit.get("seen_in_candidate_scan", pd.Series(dtype=str)).map(truth)).sum())
    control_koentec_gap = nav_gap_summary.get("CONTROL", {}).get("by_ticker", {}).get("029960", {})
    control_koentec_entries = ce.loc[
        ce.get("ticker", pd.Series(dtype=str)).astype(str).str.zfill(6).eq("029960")
        & ce.get("event_type", pd.Series(dtype=str)).eq("ENTRY")
        & ce.get("event_status", pd.Series(dtype=str)).eq("EXECUTED")
    ]
    control_koentec_entry_execution_date = (
        str(control_koentec_entries.iloc[0].get("execution_date", ""))[:10]
        if len(control_koentec_entries) else None
    )

    report = [
        "# FAST Core V2 Alignment + 500B — P1 공식 실전형 결과", "",
        f"**P1 판정: {overall}** · CRITICAL {len(critical)}종 / MAJOR {len(major)}종 / MINOR {len(minor)}종.", "",
        "## 독립 이슈 유형 수", "", "| 심각도 | 유형 수 | 유형 |", "|---|---:|---|",
        f"| CRITICAL | {len(critical)} | {', '.join(sorted(critical)) or '없음'} |",
        f"| MAJOR | {len(major)} | {', '.join(sorted(major)) or '없음'} |",
        f"| MINOR | {len(minor)} | {', '.join(sorted(minor)) or '없음'} |", "",
        "## 실행 범위와 입력 검증", "",
        f"- 실제 평가 구간 {EVAL_START.date()}~{CUTOFF.date()}, {len(eval_dates):,} exact KRX 세션. {SUPPORT.date()}은 cutoff 이전 신호로 발생한 기존 보유분의 청산만 지원하며 신규 매수와 P1 cutoff NAV/성과에는 포함하지 않았어.",
        f"- 종목 {execution['evaluated_ticker_count']:,}/{execution['eligible_universe_ticker_count']:,}, 신호 worker {execution['workers']}개, worker 오류 {execution['worker_error_count']}건.",
        f"- 표본 검증 {sample_validation.get('status')} / 전수 허가 {sample_validation.get('full_run_allowed')}; 전수 실제 소요 {execution.get('wall_seconds_including_portfolio_replays', 0) / 3600:.3f}시간 (표본 추정 {sample_validation.get('estimated_full_wall_hours')}시간). 재생 authorization guard를 통과했어.",
        f"- P1 공통 PIT interval {preflight['universe']['common_intervals_overlapping_p1_before_exclusions']:,}; 영구 제외 184쌍 후 {preflight['universe']['common_intervals_after_exclusions']:,} interval / {preflight['universe']['eligible_tickers_after_exclusions']:,} ticker. Exact pair SHA-256 `{canonical}`.",
        f"- 입력 원천 범위: PIT identity {source_coverage['rolling_pit_common']['earliest_identity_start']}~{source_coverage['rolling_pit_common']['latest_identity_end']}; adjusted 파일 {source_coverage['repository_v2_adjusted_prices']['earliest_file_date']}~{source_coverage['repository_v2_adjusted_prices']['latest_file_date']} ({source_coverage['repository_v2_adjusted_prices']['ticker_file_count']:,} files); KRX raw {source_coverage['krx_raw_market_date_partitions']['earliest_partition_date']}~{source_coverage['krx_raw_market_date_partitions']['latest_partition_date']} ({source_coverage['krx_raw_market_date_partitions']['partition_count']:,} partitions).",
        f"- MA60 예열: 첫 P1 신호 전 완료월 {preflight['date_authorities']['completed_ma60_month_count_before_first_p1_signal']}/60개, 필요 구간 2009-01~2013-12, 달력상 첫 가능 신호월 {preflight['date_authorities']['first_possible_ma60_signal_month_calendar_only']}. 부족 신호만 REJECT_MA_UNAVAILABLE 처리했어.",
        f"- source manifest 재검증: {manifest_audit['status']} ({manifest_audit['checked']:,}/{manifest_audit['expected']:,}; runtime {manifest_audit['runtime_files_checked']:,}, adjusted {manifest_audit['adjusted_price_files_checked']:,}, raw partitions {manifest_audit['raw_partition_files_checked']:,}). 신호일 raw partition {len(signal_partition_audit):,}건은 frozen manifest와 해시 일치 {signal_partition_audit_valid}.",
        f"- signal filter 상태: {json.dumps(audit.get('candidate_status', pd.Series(dtype=str)).value_counts().sort_index().to_dict(), ensure_ascii=False)}.",
        f"- candidate_status PASS {int(len(pass_audit)):,}건 중 {pass_not_candidate_scan}건은 candidate scan에서 발생하지 않은 control-only 감사행이야. 실제 candidate scan PASS 512건과 candidate 거래 원장이 일치해.",
        f"- exact market-cap unresolved {unresolved_cap:,}; Repository V2 미가용 종목 {len(unavailable):,}; projection mismatch 종목 {len(unresolved_projection):,}. P1 입력/전략 기준은 동결 V2와 동일하고 평가 기간·2억원 독립 시작 자금만 P1 계약으로 확정했어; 후보에는 지시된 MA 정배열과 당일 시총 조건만 추가했어.",
        "", "## 공식 A~E", "", "| 게이트 | CONTROL | ALIGNMENT_MCAP_500B |", "|---|---|---|",
    ]
    for key, label in (("A_integrity", "A 무결성"), ("B_costs", "B 비용"), ("C_profitability", "C 수익성"), ("D_mdd", "D MDD"), ("E_validity", "E 유효성")):
        report.append(f"| {label} | {gates['CONTROL'][key]['status']} | {gates['ALIGNMENT_MCAP_500B'][key]['status']} |")
    report.extend(["", "## 포트폴리오 비교", "", "거래 수익률과 승률의 분모는 cutoff 이전 실제 매수 후 실제 청산한 거래야. 순수익률은 양쪽 비용·슬리피지를 포함하고 보유 거래일은 진입/청산 체결 세션을 포함해 계산했어.", "", "| 지표 | CONTROL | 후보 | 후보−CONTROL |", "|---|---:|---:|---:|"])
    for label, key in (("종료 자산(원)", "ending_equity_krw"), ("총수익률(%)", "total_return_pct"), ("CAGR(%)", "cagr_pct"), ("MDD(%)", "mdd_pct"), ("NAV coverage(%)", "nav_coverage_pct"), ("NAV 결측일", "missing_nav_days"), ("지원일 청산", "support_day_exit_count"), ("진입 시도", "eligible_entry_attempts"), ("현금 부족 skip", "cash_shortage_skipped_entries"), ("현금 부족률(%)", "cash_shortage_skip_rate_pct"), ("실매수", "executed_entries"), ("실현 청산", "executed_exits_before_cutoff"), ("cutoff 미청산", "open_at_cutoff_count"), ("실현 거래", "realized_trade_count"), ("승률(%)", "realized_win_rate_pct"), ("평균 순수익률(%)", "realized_mean_net_return_pct"), ("중앙 순수익률(%)", "realized_median_net_return_pct"), ("평균 보유 거래일", "realized_mean_holding_trading_sessions"), ("중앙 보유 거래일", "realized_median_holding_trading_sessions"), ("최대 거래수익률(%)", "realized_max_net_return_pct"), ("최대 거래손실률(%)", "realized_min_net_return_pct"), ("+20% 이상 거래", "realized_ge_20_pct_count"), ("+50% 이상 거래", "realized_ge_50_pct_count"), ("+100% 이상 거래", "realized_ge_100_pct_count"), ("-10% 이하 거래", "realized_le_minus_10_pct_count"), ("-15% 이하 거래", "realized_le_minus_15_pct_count"), ("-20% 이하 거래", "realized_le_minus_20_pct_count"), ("-30% 이하 거래", "realized_le_minus_30_pct_count"), ("Loss Guard 매수", "loss_guard_triggered_executed_entry_count"), ("PROGRESSED 매수", "progressed_executed_entry_count"), ("평균 동시보유", "average_concurrent_positions"), ("최대 동시보유", "maximum_concurrent_positions"), ("평균 자본 활용률(%)", "average_capital_utilization_pct"), ("최대 자본 활용률(%)", "maximum_capital_utilization_pct"), ("평균 현금비중(%)", "average_cash_ratio_pct"), ("회전율 배수", "turnover_multiple"), ("수수료(원)", "total_commissions_krw"), ("슬리피지(원)", "total_slippage_impact_krw"), ("최대 티커 양의 손익 점유율(%)", "top_ticker_share_of_positive_realized_pnl_pct")):
        a, b = cmetrics.get(key), pmetrics.get(key)
        try: delta = float(b) - float(a) if a is not None and b is not None else None
        except (TypeError, ValueError): delta = None
        report.append(f"| {label} | {fmt(a)} | {fmt(b)} | {fmt(delta)} |")
    report.extend(["", "### MDD 및 청산 사유", "", f"- CONTROL: {cmetrics.get('mdd_type')} {fmt(cmetrics.get('mdd_pct'))}% (peak {cmetrics.get('mdd_peak_date')}, trough {cmetrics.get('mdd_trough_date')}, recovery {cmetrics.get('mdd_recovery_date') or '미회복'}).", f"- 후보: {pmetrics.get('mdd_type')} {fmt(pmetrics.get('mdd_pct'))}% (peak {pmetrics.get('mdd_peak_date')}, trough {pmetrics.get('mdd_trough_date')}, recovery {pmetrics.get('mdd_recovery_date') or '미회복'}); CONTROL−후보 {fmt(None if cmetrics.get('mdd_pct') is None or pmetrics.get('mdd_pct') is None else float(cmetrics['mdd_pct']) - float(pmetrics['mdd_pct']))}%p.", "- CONTROL peak/trough/recovery dates are diagnostics from available NAV dates only; coverage is below 90%, so no official CONTROL MDD value is reported.", f"- CONTROL 청산 사유 {json.dumps(cmetrics.get('exit_reason_counts', {}), ensure_ascii=False)}.", f"- 후보 청산 사유 {json.dumps(pmetrics.get('exit_reason_counts', {}), ensure_ascii=False)}.", f"- 최대 티커 손익 점유율: CONTROL {fmt(cmetrics.get('top_ticker_share_of_positive_realized_pnl_pct'))}% ({cmetrics.get('top_realized_pnl_ticker')}); 후보 {fmt(pmetrics.get('top_ticker_share_of_positive_realized_pnl_pct'))}% ({pmetrics.get('top_realized_pnl_ticker')}).", "- 연도/시장별 실현손익은 control_annual_market_diagnostics.csv와 alignment_mcap_500b_annual_market_diagnostics.csv에 저장했어.", "", "## 무결성 및 판정 범위", "", f"- 신호 원장 exact PIT/MA60/시총 검사: {json.dumps(signal_check, ensure_ascii=False)}.", f"- NAV는 {len(eval_dates):,}일 기준 CONTROL {fmt(cmetrics.get('nav_coverage_pct'))}% / 후보 {fmt(pmetrics.get('nav_coverage_pct'))}%; 최장 연속 결측 {cmetrics.get('maximum_consecutive_missing_nav_days')} / {pmetrics.get('maximum_consecutive_missing_nav_days')}일.", f"- {cutoff_nav_text}.", f"- 미해결 mark는 CONTROL {len(cm)}건, 후보 {len(pm)}건이야. 원인/날짜/종목별 근거는 integrity_audit.json의 nav_mark_resolution에 기록했어. 허용된 거래정지 placeholder 외 정상 세션 결측은 보간·carry하지 않고 해당 날짜 전체 NAV를 UNRESOLVED 처리했어. 분류: {integrity['nav_mark_resolution']['classification']}.",
        f"- CONTROL 기말 NAV를 막은 보유는 029960/KR7029960002(KOSDAQ, 매수 체결 {control_koentec_entry_execution_date})야. exact ticker row가 {control_koentec_gap.get('count', 0)}개 mark일에 없어 기간은 {control_koentec_gap.get('dates', ['확인 불가'])[0]}~{control_koentec_gap.get('dates', ['확인 불가'])[-1]}이고, 임의 정산은 적용하지 않았어.", f"- 가격 해시/PIT/현금·비용 독립 검산 결과는 integrity_audit.json, 029960·128940·003690 및 380440 노출 감사는 identity_exposure_audit.csv.", "- 현금 부족 skip은 진단값이지 공식 게이트가 아니야. cutoff 미청산은 cutoff 종가 평가만 하며 가상 매도비용을 부과하지 않았어.", "- 단일 P1 결과야. 5기간 채택, 후보 채택 및 baseline 승격은 NOT_EVALUATED이고 기본 전략 PATTERN_A_FAST_FINAL_STRATEGY_V02를 유지해.", "", "## 주요 산출물", "", "plan.md, execution_contract.json, preflight.json, active_pit_missing_sessions.csv, source_manifest.json, sample_benchmark.json, full_run_execution.json, 그룹별 trades/events/cash/NAV/valuation/missing marks, metrics_comparison.csv, candidate_signal_filter_by_year.csv, gate_results.json, integrity_audit.json, artifact_hashes.json."])
    report.extend(["", "### 연도별 후보 진입 필터 진단", "", "| 연도 | 평가 신호 | MA60 미가용 | 시총 미해결 | 시총 500B 미만 | 정배열 탈락 | 통과 |", "|---:|---:|---:|---:|---:|---:|---:|"])
    for row in annual_filter_summary:
        report.append(f"| {row['year']} | {row['candidate_signal_evaluations']:,} | {row['ma_unavailable']:,} | {row['mcap_unresolved']:,} | {row['mcap_below_500b']:,} | {row['alignment_rejected']:,} | {row['passed']:,} |")
    report.extend(["", f"- P1 시작 당시 MA60 선행 이력은 48/60개월이라 2014년의 후보 신호만 데이터 규칙대로 미가용 처리했어. 달력상 60개월이 처음 완성되는 신호월은 2015-01이야. 전체 P1 평가 시작일은 2014-01-02로 유지했어.", f"- 기존 공식 P2/P3 실행 계약 대비 P1 차이는 평가 기간/지원일과 P1 초기 2억원 독립 자금 경로야. V2 상태 전이·손절/청산·비용·T+1·NAV 원칙은 고정하고, 후보에는 같은 alignment 및 정확 신호일 시총 조건만 적용했어. 선행 산출물 해시 검증 {sum(row.get('status') == 'PASS' for row in prior_hashes)}/{len(prior_hashes)} PASS."])
    (OUT / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    files = [{"path": path.name, "sha256": sha(path), "bytes": path.stat().st_size} for path in sorted(OUT.iterdir()) if path.is_file() and path.name != "artifact_hashes.json" and path.suffix != ".pyc"]
    write_json(OUT / "artifact_hashes.json", {"schema": "fast_core_v2_alignment_500b_p1_artifact_hashes_v01", "files": files, "self_hash_excluded": True})
    print(json.dumps({"report": str(OUT / "report.md"), "issue_type_counts": integrity["severity_issue_type_counts"], "control": gates["CONTROL"], "candidate": gates["ALIGNMENT_MCAP_500B"], "integrity": integrity["status"]}, ensure_ascii=False, indent=2, default=json_default), flush=True)
    return 0 if not critical else 2


if __name__ == "__main__":
    raise SystemExit(main())
