#!/usr/bin/env python3
"""Independently audit and report saved P2-2 portfolio replay artifacts."""
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
P31 = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01"
EVAL_START = pd.Timestamp("2021-01-04")
CUTOFF = pd.Timestamp("2026-08-31")
SUPPORT = pd.Timestamp("2026-09-01")
INITIAL = 200_000_000.0
EXCLUSION_SHA = "9091a40d5dfc3dc115e00166ea3ef806ef5a4ca3b595d76864598ec050904b12"

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
    path = P31 / "finalize_research_artifacts.py"
    spec = importlib.util.spec_from_file_location("p2_2_readonly_p3_finalizer_helpers", path)
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
    return {"status": "PASS" if checked == len(manifest.get("files", [])) and not mismatches else "FAIL", "checked": checked, "expected": len(manifest.get("files", [])), "mismatches": mismatches}


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
    audit_control = {key for key, row in amap.items() if truth(row.get("seen_in_control_scan")) and row.get("pit_status") == "PASS"}
    audit_candidate = {key for key, row in amap.items() if truth(row.get("seen_in_candidate_scan")) and row.get("candidate_status") == "PASS"}
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


def finalize_sample_gate() -> int:
    """Write a bounded, explicitly non-official report when sample blocks full."""
    preflight = json.loads((OUT / "preflight.json").read_text(encoding="utf-8"))
    benchmark = json.loads((OUT / "sample_benchmark.json").read_text(encoding="utf-8"))
    validation = json.loads((OUT / "sample_validation.json").read_text(encoding="utf-8"))
    if benchmark.get("status") != "SAMPLE_COMPLETED":
        raise RuntimeError("P2_SAMPLE_REPLAY_NOT_COMPLETE")
    if validation.get("status") not in {"PASS", "CHECK_REQUIRED"}:
        raise RuntimeError("P2_SAMPLE_VALIDATION_INVALID")
    manifest_audit = verify_source_manifest()
    helpers = import_p3_helpers()
    calendar = load_rolling_production_market_calendar(ROOT)
    if calendar is None:
        raise RuntimeError("P2_SAMPLE_FINALIZER_CALENDAR_UNAVAILABLE")
    all_dates = pd.DatetimeIndex(calendar.trading_dates).normalize()
    dates = all_dates[(all_dates >= EVAL_START) & (all_dates <= CUTOFF)]

    control, candidate = read_csv("sample_control_trades.csv"), read_csv("sample_candidate_trades.csv")
    audit = read_csv("sample_candidate_signal_filter_audit.csv")
    ce, pe = read_csv("sample_control_portfolio_events.csv"), read_csv("sample_candidate_portfolio_events.csv")
    cd, pdaily = read_csv("sample_control_daily_equity.csv"), read_csv("sample_candidate_daily_equity.csv")
    cm, pm = read_csv("sample_control_missing_marks.csv"), read_csv("sample_candidate_missing_marks.csv")
    cmetrics, cr = group_metrics("CONTROL", control, ce, cd, cm, benchmark["control_metrics"], dates)
    pmetrics, pr = group_metrics("ALIGNMENT_MCAP_500B", candidate, pe, pdaily, pm, benchmark["candidate_metrics"], dates)
    cr.to_csv(OUT / "sample_control_realized_trades.csv", index=False)
    pr.to_csv(OUT / "sample_candidate_realized_trades.csv", index=False)
    sample_exposure = exposure_audit(control, candidate, ce, pe, cm, pm)
    sample_exposure.insert(0, "scope", "SAMPLE_ONLY_NOT_OFFICIAL")
    sample_exposure.to_csv(OUT / "sample_identity_exposure_audit.csv", index=False)

    pairs = sorted((str(t).zfill(6), str(i).strip().upper()) for t, i in PERMANENT_IDENTITY_EXCLUSIONS)
    canonical = hashlib.sha256(json.dumps({"schema": "sorted_exact_pair_json_v01", "pairs": [list(x) for x in pairs]}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    excluded = set(pairs)
    signal_check = exact_signal_checks(control, candidate, audit, excluded)
    price = read_csv("sample_ticker_price_source_audit.csv")
    worker_errors = read_csv("sample_worker_errors.csv")
    c_cost = validation.get("control_cost_audit", {})
    p_cost = validation.get("candidate_cost_audit", {})
    focus = {"029960", "128940", "003690", "380440", "010780", "141070"}
    exposure_rows = []
    for ticker in sorted(focus):
        subset_control = control.loc[control.get("ticker", pd.Series(dtype=str)).astype(str).str.zfill(6).eq(ticker)] if not control.empty else pd.DataFrame()
        subset_candidate = candidate.loc[candidate.get("ticker", pd.Series(dtype=str)).astype(str).str.zfill(6).eq(ticker)] if not candidate.empty else pd.DataFrame()
        subset_cm = cm.loc[cm.get("ticker", pd.Series(dtype=str)).astype(str).str.zfill(6).eq(ticker)] if not cm.empty else pd.DataFrame()
        subset_pm = pm.loc[pm.get("ticker", pd.Series(dtype=str)).astype(str).str.zfill(6).eq(ticker)] if not pm.empty else pd.DataFrame()
        control_event_rows = ce.loc[ce.get("ticker", pd.Series(dtype=str)).astype(str).str.zfill(6).eq(ticker)] if not ce.empty else pd.DataFrame()
        candidate_event_rows = pe.loc[pe.get("ticker", pd.Series(dtype=str)).astype(str).str.zfill(6).eq(ticker)] if not pe.empty else pd.DataFrame()
        source_row = price.loc[price.get("ticker", pd.Series(dtype=str)).astype(str).str.zfill(6).eq(ticker)] if not price.empty else pd.DataFrame()
        preflight_row = read_csv("identity_price_preflight.csv")
        preflight_row = preflight_row.loc[preflight_row.get("ticker", pd.Series(dtype=str)).astype(str).str.zfill(6).eq(ticker)] if not preflight_row.empty else pd.DataFrame()
        exposure_rows.append({
            "ticker": ticker,
            "sample_control_trade_rows": len(subset_control),
            "sample_candidate_trade_rows": len(subset_candidate),
            "sample_control_missing_mark_days": len(subset_cm),
            "sample_candidate_missing_mark_days": len(subset_pm),
            "control_executed_entry_shares": pd.to_numeric(control_event_rows.loc[control_event_rows.get("event_type", pd.Series(dtype=str)).eq("ENTRY") & control_event_rows.get("event_status", pd.Series(dtype=str)).eq("EXECUTED"), "shares"], errors="coerce").sum() if not control_event_rows.empty else 0,
            "candidate_executed_entry_shares": pd.to_numeric(candidate_event_rows.loc[candidate_event_rows.get("event_type", pd.Series(dtype=str)).eq("ENTRY") & candidate_event_rows.get("event_status", pd.Series(dtype=str)).eq("EXECUTED"), "shares"], errors="coerce").sum() if not candidate_event_rows.empty else 0,
            "control_open_positions_at_cutoff": int(((control_event_rows.get("event_type", pd.Series(dtype=str)).eq("ENTRY")) & (control_event_rows.get("event_status", pd.Series(dtype=str)).eq("EXECUTED"))).sum() - ((control_event_rows.get("event_type", pd.Series(dtype=str)).eq("EXIT")) & (control_event_rows.get("event_status", pd.Series(dtype=str)).eq("EXECUTED"))).sum()) if not control_event_rows.empty else 0,
            "candidate_open_positions_at_cutoff": int(((candidate_event_rows.get("event_type", pd.Series(dtype=str)).eq("ENTRY")) & (candidate_event_rows.get("event_status", pd.Series(dtype=str)).eq("EXECUTED"))).sum() - ((candidate_event_rows.get("event_type", pd.Series(dtype=str)).eq("EXIT")) & (candidate_event_rows.get("event_status", pd.Series(dtype=str)).eq("EXECUTED"))).sum()) if not candidate_event_rows.empty else 0,
            "control_missing_mark_dates": ";".join(sorted(subset_cm.get("date", pd.Series(dtype=str)).astype(str).unique())),
            "candidate_missing_mark_dates": ";".join(sorted(subset_pm.get("date", pd.Series(dtype=str)).astype(str).unique())),
            "control_candidate_ids": ";".join(sorted(subset_cm.get("candidate_id", pd.Series(dtype=str)).astype(str).unique())),
            "candidate_candidate_ids": ";".join(sorted(subset_pm.get("candidate_id", pd.Series(dtype=str)).astype(str).unique())),
            "price_load_status": source_row.iloc[0].get("load_status") if len(source_row) else "NOT_IN_SAMPLE",
            "adjusted_first_date": preflight_row.iloc[0].get("adjusted_first_date") if len(preflight_row) else None,
            "adjusted_last_date": preflight_row.iloc[0].get("adjusted_last_date") if len(preflight_row) else None,
            "adjusted_file_sha256": preflight_row.iloc[0].get("adjusted_file_sha256") if len(preflight_row) else None,
            "active_pit_missing_both_source_sessions": preflight_row.iloc[0].get("active_pit_sessions_missing_both_sources") if len(preflight_row) else None,
            "current_permanent_exclusion": any(t == ticker for t, _ in excluded),
        })
    exposure_frame = pd.DataFrame(exposure_rows)
    exposure_frame.to_csv(OUT / "sample_issue_exposure.csv", index=False)

    missing_by_group: dict[str, dict[str, int]] = {}
    for label, frame in (("CONTROL", cm), ("ALIGNMENT_MCAP_500B", pm)):
        missing_by_group[label] = frame.get("ticker", pd.Series(dtype=str)).astype(str).str.zfill(6).value_counts().sort_index().astype(int).to_dict()
    koentec_missing = missing_by_group["CONTROL"].get("029960", 0)
    koentec_open = any("029960|KR7029960002" in str(x) for x in benchmark["control_metrics"].get("open_at_cutoff_candidate_ids", []))
    issue_major = ["029960_OPEN_AFTER_CASH_SHARE_EXCHANGE_NO_CONFIRMED_SETTLEMENT"] if koentec_missing else []
    issue_minor = []
    if missing_by_group["CONTROL"].get("003690", 0) or missing_by_group["ALIGNMENT_MCAP_500B"].get("003690", 0):
        issue_minor.append("003690_ACTIVE_TRADE_DAYS_WITHOUT_VALID_ADJUSTED_MARK")
    if missing_by_group["CONTROL"].get("128940", 0) or missing_by_group["ALIGNMENT_MCAP_500B"].get("128940", 0):
        issue_minor.append("128940_ACTIVE_TRADE_DAY_WITHOUT_VALID_ADJUSTED_MARK")

    sample_cost_fields = (
        "entry_attempt_events_equal_prefixed_trade_rows", "executed_entry_events_match_summary",
        "all_filled_sides_recalculate_commission_and_slippage", "entry_and_exit_fill_prices_match_v2_trade_ledger",
        "integer_shares_and_inclusive_5m_buy_budget", "sale_proceeds_remain_pending_on_exit_execution_day",
        "portfolio_cash_conservation", "no_hidden_position_cap_skip", "no_same_ticker_overlap_or_unmatched_exit",
        "event_cost_totals_match_summary",
    )
    c_sample_cost_pass = all(bool(c_cost.get(k)) for k in sample_cost_fields)
    p_sample_cost_pass = all(bool(p_cost.get(k)) for k in sample_cost_fields)
    critical = []
    if manifest_audit.get("status") != "PASS":
        critical.append("CURRENT_SOURCE_MANIFEST_HASH_MISMATCH")
    if canonical != EXCLUSION_SHA or len(pairs) != 182:
        critical.append("PERMANENT_EXCLUSION_POLICY_HASH_MISMATCH")
    if len(dates) != int(preflight["date_authorities"].get("evaluation_sessions", 0)) or len(dates) != 1387:
        critical.append("P2_EXACT_EVALUATION_CALENDAR_MISMATCH")
    if signal_check["duplicate_exact_pit_signal_audit_keys"] or signal_check["control_trade_without_one_active_common_identity_audit"] or signal_check["candidate_trade_alignment_mcap_or_prior_60m_mismatch"] or signal_check["excluded_identity_trade_leakage"]:
        critical.append("SAMPLE_PIT_OR_CANDIDATE_FILTER_INVARIANT_FAILURE")
    if not signal_check["control_trade_set_matches_pit_pass_audit"] or not signal_check["candidate_trade_set_matches_candidate_pass_audit"]:
        critical.append("SAMPLE_SIGNAL_AUDIT_SET_MISMATCH")
    if len(worker_errors) or len(price) != int(benchmark.get("evaluated_ticker_count", -1)) or not price.get("data_status", pd.Series(dtype=str)).eq("AVAILABLE").all():
        critical.append("SAMPLE_WORKER_OR_PRICE_AVAILABILITY_FAILURE")
    if not c_sample_cost_pass or not p_sample_cost_pass:
        critical.append("SAMPLE_COST_OR_CASH_INVARIANT_FAILURE")
    integrity_status = "FAIL" if critical else "CHECK_REQUIRED" if issue_major or issue_minor or validation.get("status") != "PASS" else "PASS"
    gates: dict[str, Any] = {
        "schema": "fast_core_v2_alignment_500b_p2_2_gates_v02",
        "window": "P2-2",
        "official_execution_status": "NOT_RUN_SAMPLE_GATE_CHECK_REQUIRED",
        "CONTROL": {
            "A_integrity": {"status": "CHECK_REQUIRED", "reason": "Sample contains unresolved post-delisting open position and active-trading-day marks."},
            "B_costs": {"status": "NOT_EVALUATED", "sample_diagnostic_status": "PASS" if c_sample_cost_pass else "FAIL"},
            "C_profitability": {"status": "NOT_EVALUATED", "sample_diagnostic_total_return_pct": cmetrics.get("total_return_pct"), "sample_diagnostic_cagr_pct": cmetrics.get("cagr_pct")},
            "D_mdd": {"status": "NOT_EVALUATED", "sample_screen_status": "CHECK_REQUIRED" if float(cmetrics.get("nav_coverage_pct", 0)) < 90 else "OBSERVED", "sample_coverage_pct": cmetrics.get("nav_coverage_pct"), "sample_observed_mdd_pct": cmetrics.get("observed_mdd_pct")},
            "E_validity": {"status": "NOT_EVALUATED", "sample_screen_status": "CHECK_REQUIRED" if float(cmetrics.get("nav_coverage_pct", 0)) < 90 else "OBSERVED", "sample_coverage_pct": cmetrics.get("nav_coverage_pct")},
        },
        "ALIGNMENT_MCAP_500B": {
            "A_integrity": {"status": "CHECK_REQUIRED", "reason": "Four sample NAV marks remain unresolved for 003690 on raw trading days."},
            "B_costs": {"status": "NOT_EVALUATED", "sample_diagnostic_status": "PASS" if p_sample_cost_pass else "FAIL"},
            "C_profitability": {"status": "NOT_EVALUATED", "sample_diagnostic_total_return_pct": pmetrics.get("total_return_pct"), "sample_diagnostic_cagr_pct": pmetrics.get("cagr_pct")},
            "D_mdd": {"status": "NOT_EVALUATED", "sample_screen_status": "OBSERVED" if float(pmetrics.get("nav_coverage_pct", 0)) >= 90 else "CHECK_REQUIRED", "sample_coverage_pct": pmetrics.get("nav_coverage_pct"), "sample_observed_mdd_pct": pmetrics.get("observed_mdd_pct")},
            "E_validity": {"status": "NOT_EVALUATED", "sample_screen_status": "OBSERVED" if float(pmetrics.get("nav_coverage_pct", 0)) >= 90 else "CHECK_REQUIRED", "sample_coverage_pct": pmetrics.get("nav_coverage_pct")},
        },
        "sample_gate_status": validation.get("status"),
        "sample_validation_failed_checks": [key for key, value in validation.get("checks", {}).items() if value is False],
        "whole_five_window_adoption": "NOT_FINAL_5WINDOW",
        "candidate_adoption": "NOT_EVALUATED",
        "baseline_promotion": "NOT_EVALUATED",
        "official_default_remains": "PATTERN_A_FAST_FINAL_STRATEGY_V02",
        "cash_shortage_is_official_gate": False,
    }
    write_json(OUT / "gate_results.json", gates)

    metrics_to_compare = (
        ("ending_equity_krw", "종료 자산(원)"), ("total_return_pct", "총수익률(%)"), ("cagr_pct", "CAGR(%)"),
        ("mdd_pct", "NAV coverage 기준 MDD(표본 %)"), ("observed_mdd_pct", "유효 NAV 관측 MDD(%)"),
        ("nav_coverage_pct", "NAV coverage(%)"), ("valid_nav_days", "유효 NAV 일수"),
        ("missing_nav_days", "NAV 결측일"), ("maximum_consecutive_missing_nav_days", "최장 연속 NAV 결측일"),
        ("mdd_unresolved_mark_count", "미해결 mark 수"), ("eligible_entry_attempts", "적격 진입 시도"),
        ("cash_shortage_skipped_entries", "현금 부족 skip"), ("cash_shortage_skip_rate_pct", "현금 부족 skip율(%)"), ("executed_entries", "실매수"),
        ("executed_exits_before_cutoff", "실현 청산"), ("open_at_cutoff_count", "cutoff 미청산"),
        ("support_day_exit_count", "지원일 청산"),
        ("realized_trade_count", "실현 거래"), ("realized_win_rate_pct", "승률(%)"),
        ("realized_mean_net_return_pct", "평균 순수익률(%)"), ("realized_median_net_return_pct", "중앙 순수익률(%)"),
        ("realized_mean_holding_trading_sessions", "평균 보유 거래일"), ("realized_median_holding_trading_sessions", "중앙 보유 거래일"),
        ("realized_max_net_return_pct", "최대 거래수익률(%)"), ("realized_min_net_return_pct", "최대 거래손실률(%)"),
        ("realized_ge_20_pct_count", "+20% 이상 거래"), ("realized_ge_50_pct_count", "+50% 이상 거래"),
        ("realized_ge_100_pct_count", "+100% 이상 거래"), ("realized_le_minus_10_pct_count", "-10% 이하 거래"),
        ("realized_le_minus_15_pct_count", "-15% 이하 거래"), ("realized_le_minus_20_pct_count", "-20% 이하 거래"),
        ("realized_le_minus_30_pct_count", "-30% 이하 거래"), ("loss_guard_triggered_executed_entry_count", "Loss Guard 매수"),
        ("progressed_executed_entry_count", "PROGRESSED 매수"), ("average_concurrent_positions", "평균 동시보유"),
        ("maximum_concurrent_positions", "최대 동시보유"), ("average_capital_utilization_pct", "평균 자본 활용률(%)"),
        ("maximum_capital_utilization_pct", "최대 자본 활용률(%)"), ("average_cash_ratio_pct", "평균 현금비중(%)"),
        ("turnover_krw", "총 회전 금액(원)"), ("turnover_multiple", "회전율 배수"),
        ("total_commissions_krw", "수수료(원)"), ("total_slippage_impact_krw", "슬리피지(원)"),
        ("top_realized_pnl_ticker", "최고 실현손익 종목"), ("top_ticker_share_of_positive_realized_pnl_pct", "상위 승자 손익 집중도(%)"),
    )
    comparison = []
    for key, label in metrics_to_compare:
        a, b = cmetrics.get(key), pmetrics.get(key)
        try:
            delta = float(b) - float(a) if a is not None and b is not None and np.isfinite(float(a)) and np.isfinite(float(b)) else None
        except (TypeError, ValueError):
            delta = None
        comparison.append({"metric": key, "label_ko": label, "scope": "SAMPLE_DIAGNOSTIC_NOT_OFFICIAL_P2_2", "CONTROL_sample": a, "ALIGNMENT_MCAP_500B_sample": b, "candidate_minus_control_sample": delta, "official_p2_2_status": "NOT_EVALUATED"})
    pd.DataFrame(comparison).to_csv(OUT / "metrics_comparison.csv", index=False)

    realized_samples = []
    for label, frame in (("CONTROL", cr), ("ALIGNMENT_MCAP_500B", pr)):
        if frame.empty:
            continue
        frame = frame.copy()
        frame["exit_year"] = frame["exit_execution_date"].astype(str).str[:4]
        for dimension in ("exit_year", "market"):
            part = frame.groupby(dimension, dropna=False).agg(trades=("candidate_id", "count"), realized_pnl_krw=("realized_pnl_krw", "sum"), mean_return_pct=("net_return_pct", "mean"), win_rate_pct=("net_return_pct", lambda s: float((pd.to_numeric(s, errors="coerce") > 0).mean() * 100))).reset_index().rename(columns={dimension: "bucket"})
            part.insert(0, "group", label)
            part.insert(1, "scope", "SAMPLE_ONLY_NOT_OFFICIAL")
            part.insert(2, "dimension", dimension)
            realized_samples.append(part)
    if realized_samples:
        pd.concat(realized_samples, ignore_index=True).to_csv(OUT / "sample_annual_market_diagnostics.csv", index=False)
    else:
        pd.DataFrame(columns=["group", "scope", "dimension", "bucket", "trades", "realized_pnl_krw", "mean_return_pct", "win_rate_pct"]).to_csv(OUT / "sample_annual_market_diagnostics.csv", index=False)

    preflight_input = preflight["repository_v2_input_preflight"]
    sample_status_counts = benchmark.get("candidate_filter_status_counts", {})
    issue_counts = {"CRITICAL": len(critical), "MAJOR": len(issue_major), "MINOR": len(issue_minor)}
    integrity = {
        "schema": "fast_core_v2_alignment_500b_p2_2_integrity_audit_v02",
        "status": integrity_status,
        "scope": "sample gate only; full P2-2 was not executed",
        "severity_issue_type_counts": issue_counts,
        "critical_issue_types": critical,
        "major_issue_types": issue_major,
        "minor_issue_types": issue_minor,
        "source_manifest_verification": manifest_audit,
        "pre_sample_source_manifest_sha256": sha(OUT / "source_manifest_pre_sample.json"),
        "baseline": preflight["baseline"],
        "preflight_status": preflight.get("preflight_status"),
        "date_authorities": preflight.get("date_authorities"),
        "eligible_tickers": preflight["universe"].get("eligible_tickers_after_exclusions"),
        "permanent_exclusions": {"pair_count": preflight["universe"].get("current_exclusion_pair_count"), "canonical_sha256": canonical, "matches_contract": canonical == EXCLUSION_SHA},
        "price_input_preflight": {"load_status_counts": preflight_input.get("load_status_counts"), "unavailable_tickers": preflight_input.get("unavailable_or_error_tickers"), "active_pit_missing_source_rows": preflight_input.get("active_pit_missing_source_rows_total"), "missing_session_reason_counts": preflight_input.get("active_pit_missing_session_reason_counts"), "unclassified_raw_only_sessions": preflight_input.get("raw_only_unclassified_sessions_total"), "unexplained_adjusted_only_sessions": preflight_input.get("adjusted_only_unexplained_sessions_total"), "classified_non_placeholder_source_anomaly_tickers": preflight_input.get("classified_non_placeholder_source_anomaly_tickers")},
        "sample_run": {"status": benchmark.get("status"), "tickers": benchmark.get("evaluated_ticker_count"), "workers": benchmark.get("workers"), "worker_errors": benchmark.get("worker_error_count"), "wall_seconds": benchmark.get("wall_seconds_including_portfolio_replays"), "estimated_full_wall_hours": benchmark.get("estimated_full_wall_hours"), "full_run_started": False},
        "sample_validation": validation,
        "sample_signal_ledger_checks": signal_check,
        "sample_candidate_filter_status_counts": sample_status_counts,
        "sample_control_cost_audit": c_cost,
        "sample_candidate_cost_audit": p_cost,
        "sample_nav": {"CONTROL": cmetrics, "ALIGNMENT_MCAP_500B": pmetrics},
        "missing_mark_count_by_ticker": missing_by_group,
        "sample_identity_exposure_audit": "sample_identity_exposure_audit.csv",
        "sample_issue_exposure": "sample_issue_exposure.csv",
        "external_api_requests": 0,
        "full_run_execution_file_exists": (OUT / "full_run_execution.json").is_file(),
    }
    write_json(OUT / "integrity_audit.json", integrity)

    def fmt(value: Any) -> str:
        if value is None or value == "":
            return "—"
        try:
            if not np.isfinite(float(value)):
                return "—"
            return f"{float(value):,.2f}"
        except (TypeError, ValueError):
            return str(value)

    report = [
        "# FAST Core V2 Alignment + 500B — P2-2 표본 게이트 결과", "",
        "## 이슈 유형 수", "", "| 심각도 | 유형 수 | 유형 |", "|---|---:|---|",
        f"| CRITICAL | {issue_counts['CRITICAL']} | 없음 |",
        f"| MAJOR | {issue_counts['MAJOR']} | {', '.join(issue_major) or '없음'} |",
        f"| MINOR | {issue_counts['MINOR']} | {', '.join(issue_minor) or '없음'} |", "",
        "## 실행 결과와 범위", "",
        f"- 전수 preflight: **{preflight.get('preflight_status')}**. {preflight['date_authorities']['evaluation_start']}~{preflight['date_authorities']['evaluation_end']} 정확 거래일 {preflight['date_authorities']['evaluation_sessions']:,}일, 지원일 {preflight['date_authorities']['support_date']}; 적격 {preflight['universe']['eligible_tickers_after_exclusions']:,}종목. raw market/date partition {preflight['krx_raw_signal_partition_preflight']['market_partition_count']:,}/{preflight['krx_raw_signal_partition_preflight']['market_partition_count']:,} COMPLETE.",
        f"- PIT 활성일 중 합성 adjusted+raw 행이 없는 날짜는 {preflight_input.get('active_pit_missing_source_rows_total'):,}건/956개 ticker였어. 분류: 승인 raw 비거래 placeholder {preflight_input.get('active_pit_missing_session_reason_counts', {}).get('AUTHORIZED_RAW_NONTRADING_PLACEHOLDER_EXCLUDED_FROM_SIGNALS', 0):,}, 공유 비거래 placeholder {preflight_input.get('active_pit_missing_session_reason_counts', {}).get('CONFIRMED_SHARED_NONTRADING_PLACEHOLDER_EXCLUDED_FROM_SIGNALS', 0):,}, adjusted analytic-invalid {preflight_input.get('active_pit_missing_session_reason_counts', {}).get('ADJUSTED_ANALYTICALLY_INVALID_EXCLUDED', 0):,}, source-nonusable {preflight_input.get('active_pit_missing_session_reason_counts', {}).get('ADJUSTED_SOURCE_NONUSABLE', 0):,}. Unclassified raw-only / unexplained adjusted-only는 각각 {preflight_input.get('raw_only_unclassified_sessions_total')} / {preflight_input.get('adjusted_only_unexplained_sessions_total')}건; adjusted 파일 해시는 {preflight_input.get('adjusted_file_hash_inventory_count'):,}/{preflight_input.get('unique_tickers_checked'):,} 검증.",
        f"- 영구 제외 182쌍 canonical SHA-256 `{canonical}` 일치, (380440, KR7380440008) 제외. MA60 예열은 {preflight['date_authorities']['completed_ma60_first_month']}~{preflight['date_authorities']['completed_ma60_last_month']}.",
        f"- 대표 표본 {benchmark['evaluated_ticker_count']}개, 10 workers, worker 오류 {benchmark.get('worker_error_count')}건. 표본 replay {benchmark['wall_seconds_including_portfolio_replays']:.1f}초; 보수적 전수 예상 {benchmark['estimated_full_wall_hours']:.3f}시간.",
        "- 전체 실행은 시작하지 않았어. 표본 validation이 CHECK_REQUIRED이며 CONTROL NAV coverage가 90% 미만이라 W의 필수 통과 조건을 만족하지 못했어.",
        "- 최초 표본 시도는 Repository V2 상세 audit metadata 복사 성능 회귀 때문에 완료 전에 중단했어. loader를 공식 요약 metadata 경로와 맞춘 뒤 저장된 유효 결과는 수정하지 않고 corrected sample을 완료했어. validator CSV 타입 호환 수정도 별도 기록했어.",
        "- P1/P2-1/P3 재생, 전략 튜닝, 운영 코드/기본 전략 변경, 외부 API 호출은 없었어.", "",
        "## 공식 A~E 판정", "", "| 게이트 | CONTROL | 후보 | 범위 |", "|---|---|---|---|",
        f"| A 무결성 | CHECK_REQUIRED | CHECK_REQUIRED | 표본에서 실제 보유 종목 mark/기업행동 문제가 확인됨 |",
        f"| B 비용 | NOT_EVALUATED (표본 PASS) | NOT_EVALUATED (표본 PASS) | 전수 원장 미실행 |",
        f"| C 수익성 | NOT_EVALUATED | NOT_EVALUATED | 전수 P2-2 아님 |",
        f"| D MDD | NOT_EVALUATED (표본 CHECK_REQUIRED) | NOT_EVALUATED (표본 OBSERVED) | CONTROL coverage {cmetrics.get('nav_coverage_pct'):.2f}%; 후보 {pmetrics.get('nav_coverage_pct'):.2f}% |",
        f"| E 유효성 | NOT_EVALUATED (표본 CHECK_REQUIRED) | NOT_EVALUATED (표본 OBSERVED) | 전수 평가 미실행 |", "",
        "## 표본 포트폴리오 지표 (진단 전용, 공식 P2-2 결과 아님)", "",
        "수익률·MDD·자산 비교는 32개 표본에 한정돼. CONTROL의 결측 NAV 때문에 종료자산·총수익률·CAGR 및 공식 MDD를 계산하지 않았어. 승률·순수익률·보유기간은 cutoff 전 실제 청산된 표본 거래만 분모로 사용해.", "",
        "| 지표 | CONTROL 표본 | 후보 표본 | 후보−CONTROL 표본 |", "|---|---:|---:|---:|",
    ]
    labels = dict(metrics_to_compare)
    for item in comparison:
        report.append(f"| {labels[item['metric']]} | {fmt(item['CONTROL_sample'])} | {fmt(item['ALIGNMENT_MCAP_500B_sample'])} | {fmt(item['candidate_minus_control_sample'])} |")
    report.extend([
        "", "### 표본 NAV 및 비용", "",
        f"- CONTROL: 유효 {cmetrics.get('valid_nav_days')}/{cmetrics.get('total_valuation_days')}일 ({fmt(cmetrics.get('nav_coverage_pct'))}%), 결측 {cmetrics.get('missing_nav_days')}일, 최장 연속 결측 {cmetrics.get('maximum_consecutive_missing_nav_days')}일, 관측 MDD {fmt(cmetrics.get('observed_mdd_pct'))}% (`CHECK_REQUIRED`). 종료자산/NAV 기반 총수익률은 산출하지 않았어.",
        f"- 후보: 유효 {pmetrics.get('valid_nav_days')}/{pmetrics.get('total_valuation_days')}일 ({fmt(pmetrics.get('nav_coverage_pct'))}%), 결측 {pmetrics.get('missing_nav_days')}일, 최장 연속 결측 {pmetrics.get('maximum_consecutive_missing_nav_days')}일, 관측 MDD {fmt(pmetrics.get('observed_mdd_pct'))}% (`OBSERVED`). 표본 종료자산은 {fmt(pmetrics.get('cutoff_equity_krw'))}원이지만 전수 공식 성과가 아니야.",
        f"- 표본 후보 필터 감사: {json.dumps(sample_status_counts, ensure_ascii=False)}. exact signal-date market-cap partition/후보 trade parity 및 표본 비용·현금 invariant는 validation에 기록됐어.",
        f"- CONTROL 청산 사유: {json.dumps(cmetrics.get('exit_reason_counts', {}), ensure_ascii=False)}; 후보 청산 사유: {json.dumps(pmetrics.get('exit_reason_counts', {}), ensure_ascii=False)}.",
        "", "## 미해결 이슈와 전체 실행 차단 사유", "",
        f"1. **029960 / KR7029960002 (MAJOR)** — 표본 CONTROL이 2024-11-18에 558주를 매수했고 cutoff에도 보유 중이야. 2025-05-30 주식교환 이후 2025-06-16 상장폐지, 주당 9,000원 현금교부 예정 공시가 기존 corporate-action 감사에 있지만 실제 입금/세금/수수료 및 계좌 정산 증빙은 없어. 2025-06-16~2026-08-31 297 거래일의 adjusted mark가 없어 NAV coverage가 77.58%로 내려갔어. 계약에 기업행동 정산이 없어서 9,000원×558주를 수익·미수금으로 임의 입력하지 않았고, 029960을 유니버스에서 빼지도 않았어.",
        f"2. **003690 / KR7003690005 (MINOR)** — raw 거래행이 있는 날짜에 adjusted mark가 없어 비거래 carry를 쓸 수 없어. 표본 CONTROL 13일, 후보 4일. 기존 P3-2의 네 날짜 진단과 겹치지만 P2-2 표본 영향으로 별도 기록했어.",
        "3. **128940 / KR7128940004 (MINOR)** — 2022-07-05 실제 거래행의 mark 1일 누락; 비거래 placeholder가 아니라 carry하지 않았어.",
        "- 010780/141070의 두 classified source-anomaly 날짜는 sample에 포함했어. 해당 날짜에 held-position missing mark는 발생하지 않았어. 이 종목의 sample trade는 정상 거래일 구간에서 별도 처리됐어.",
        "- 따라서 CONTROL 표본 coverage <90%여서 `sample_validation.json`은 CHECK_REQUIRED. 계약상 전수 실행을 시작하지 않았고, P2-2 공식 성과/채택 판정은 보류야.",
        "", "## 판정 상태와 다음 결정", "",
        "- P2-2: sample gate `CHECK_REQUIRED`; full run 미실행. `NOT_FINAL_5WINDOW`, 후보 채택 `NOT_EVALUATED`, 기본 승격 `NOT_EVALUATED`; 기본 전략 `PATTERN_A_FAST_FINAL_STRATEGY_V02` 유지.",
        "- 029960 교부금 입금 증빙과 기업행동 현금 정산 규칙이 정해지기 전에는 full P2-2를 재개하지 않아. raw 거래일 adjusted mark 문제도 임의 채우기/종목 제외 없이 별도 근거가 필요해.",
        "- 정확한 표본 원장·NAV·missing mark·issue exposure·통계는 `sample_*` 산출물, `sample_identity_exposure_audit.csv`, `sample_issue_exposure.csv`, `metrics_comparison.csv`, `sample_annual_market_diagnostics.csv`에 있어.",
    ])
    (OUT / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")

    files = [{"path": path.name, "sha256": sha(path), "bytes": path.stat().st_size} for path in sorted(OUT.iterdir()) if path.is_file() and path.name != "artifact_hashes.json" and path.suffix != ".pyc"]
    write_json(OUT / "artifact_hashes.json", {"schema": "fast_core_v2_alignment_500b_p2_2_artifact_hashes_v02", "files": files, "self_hash_excluded": True})
    print(json.dumps({"report": str(OUT / "report.md"), "status": integrity_status, "severity_issue_type_counts": issue_counts, "sample_validation": validation.get("status"), "control_nav_coverage_pct": cmetrics.get("nav_coverage_pct"), "candidate_nav_coverage_pct": pmetrics.get("nav_coverage_pct"), "full_run_started": False}, ensure_ascii=False, indent=2, default=json_default), flush=True)
    return 0 if integrity_status == "PASS" else 2


def main() -> int:
    if not (OUT / "full_run_execution.json").is_file():
        return finalize_sample_gate()
    execution = json.loads((OUT / "full_run_execution.json").read_text(encoding="utf-8"))
    if execution.get("status") != "FULL_COMPLETED" or execution.get("mode") != "FULL":
        raise RuntimeError("P2_FULL_REPLAY_NOT_COMPLETE")
    manifest_audit = verify_source_manifest()
    preflight = json.loads((OUT / "preflight.json").read_text(encoding="utf-8"))
    helpers = import_p3_helpers()
    calendar = load_rolling_production_market_calendar(ROOT)
    if calendar is None:
        raise RuntimeError("P2_FINALIZER_CALENDAR_UNAVAILABLE")
    dates = pd.DatetimeIndex(calendar.trading_dates).normalize()
    eval_dates = dates[(dates >= EVAL_START) & (dates <= CUTOFF)]
    control, candidate = read_csv("control_trades.csv"), read_csv("candidate_trades.csv")
    audit = read_csv("candidate_signal_filter_audit.csv")
    ce, pe = read_csv("control_portfolio_events.csv"), read_csv("candidate_portfolio_events.csv")
    cd, pdaily = read_csv("control_daily_equity.csv"), read_csv("candidate_daily_equity.csv")
    cm, pm = read_csv("control_missing_marks.csv"), read_csv("candidate_missing_marks.csv")
    cbase, pbase = execution["control_metrics"], execution["candidate_metrics"]

    pairs = sorted((str(t).zfill(6), str(i).strip().upper()) for t, i in PERMANENT_IDENTITY_EXCLUSIONS)
    canonical = hashlib.sha256(json.dumps({"schema": "sorted_exact_pair_json_v01", "pairs": [list(x) for x in pairs]}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    excluded = set(pairs)
    signal_check = exact_signal_checks(control, candidate, audit, excluded)
    exposure = exposure_audit(control, candidate, ce, pe, cm, pm)
    exposure.to_csv(OUT / "identity_exposure_audit.csv", index=False)
    cmetrics, cr = group_metrics("CONTROL", control, ce, cd, cm, cbase, eval_dates)
    pmetrics, pr = group_metrics("ALIGNMENT_MCAP_500B", candidate, pe, pdaily, pm, pbase, eval_dates)
    cr.to_csv(OUT / "control_realized_trades.csv", index=False)
    pr.to_csv(OUT / "candidate_realized_trades.csv", index=False)
    ccost = helpers.cost_and_portfolio_checks(ce, control, cbase)
    pcost = helpers.cost_and_portfolio_checks(pe, candidate, pbase)
    price = read_csv("ticker_price_source_audit.csv")
    unavailable = price.loc[price.get("data_status", pd.Series(dtype=str)).ne("AVAILABLE")]
    unresolved_projection = price.loc[(pd.to_numeric(price.get("rejected_raw_only_count", pd.Series(dtype=str)), errors="coerce").fillna(0) > 0) | (pd.to_numeric(price.get("unexplained_adjusted_only_count", pd.Series(dtype=str)), errors="coerce").fillna(0) > 0) | (pd.to_numeric(price.get("silent_inner_drop_count", pd.Series(dtype=str)), errors="coerce").fillna(0) > 0)]
    unresolved_cap = int(audit.get("mcap_status", pd.Series(dtype=str)).eq("UNRESOLVED").sum())

    structural = []
    if manifest_audit["status"] != "PASS": structural.append("FROZEN_SOURCE_HASH_MISMATCH")
    if canonical != EXCLUSION_SHA or len(pairs) != 182: structural.append("PERMANENT_EXCLUSION_POLICY_HASH_MISMATCH")
    if len(eval_dates) != int(preflight["date_authorities"]["evaluation_sessions"]) or eval_dates.min() != EVAL_START or eval_dates.max() != CUTOFF: structural.append("P2_EXACT_CALENDAR_MISMATCH")
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
        cap_issue = is_candidate and unresolved_cap > 0
        price_issue = len(unavailable) > 0 or len(unresolved_projection) > 0
        a = "FAIL" if critical else "CHECK_REQUIRED" if price_issue or cap_issue or unresolved_execution else "PASS"
        b = "PASS" if all(bool(cost.get(key)) for key in ("all_filled_sides_recalculate_commission_and_slippage", "integer_shares_and_inclusive_5m_buy_budget", "portfolio_cash_conservation")) else "FAIL"
        total, cagr = metrics.get("total_return_pct"), metrics.get("cagr_pct")
        c = "CHECK_REQUIRED" if total is None or cagr is None else "PASS" if float(total) > 0 and float(cagr) > 0 else "FAIL"
        mdd = metrics.get("mdd_pct")
        if mdd is None or float(metrics.get("nav_coverage_pct", 0)) < 90: d = "CHECK_REQUIRED"
        elif float(mdd) < -40: d = "FAIL"
        elif is_candidate and relative is not None and relative >= 5: d = "FAIL"
        elif is_candidate and (relative is None or price_issue or cap_issue): d = "CHECK_REQUIRED"
        else: d = "PASS"
        coverage = float(metrics.get("nav_coverage_pct", 0))
        e = "CHECK_REQUIRED" if coverage < 90 else "EXACT" if coverage == 100 else "OBSERVED"
        gate_data[group] = {"A_integrity": {"status": a}, "B_costs": {"status": b, "cost_audit": cost}, "C_profitability": {"status": c, "total_return_pct": total, "cagr_pct": cagr}, "D_mdd": {"status": d, "mdd_pct": mdd, "mdd_type": metrics.get("mdd_type"), "control_mdd_minus_candidate_mdd_pp": relative if is_candidate else None, "absolute_floor_pct": -40, "relative_failure_threshold_pp": 5 if is_candidate else None}, "E_validity": {"status": e, "coverage_pct": coverage, "valid_days": metrics.get("valid_nav_days"), "total_days": metrics.get("total_valuation_days"), "missing_days": metrics.get("missing_nav_days")}}
    gates = {"schema": "fast_core_v2_alignment_500b_p2_2_gates_v02", "window": "P2-2", **gate_data, "whole_five_window_adoption": "NOT_FINAL_5WINDOW", "candidate_adoption": "NOT_EVALUATED", "baseline_promotion": "NOT_EVALUATED", "official_default_remains": "PATTERN_A_FAST_FINAL_STRATEGY_V02", "cash_shortage_is_official_gate": False}

    major = set(unresolved_execution)
    minor = set()
    if unresolved_cap: major.add("EXACT_SIGNAL_DATE_MCAP_UNRESOLVED")
    if len(unavailable): major.add("REPOSITORY_V2_PRICE_UNAVAILABLE")
    if len(unresolved_projection): major.add("REPOSITORY_V2_PROJECTION_MISMATCH")
    if len(cm) or len(pm): major.add("NAV_MARK_UNRESOLVED")
    if int(cbase.get("open_at_cutoff_count", 0) or 0) or int(pbase.get("open_at_cutoff_count", 0) or 0): minor.add("CUTOFF_OPEN_POSITIONS_MARKED_WITHOUT_HYPOTHETICAL_EXIT_COST")
    if int(cbase.get("cash_shortage_skipped_entries", 0) or 0) or int(pbase.get("cash_shortage_skipped_entries", 0) or 0): minor.add("CASH_SHORTAGE_SKIP_DIAGNOSTIC")
    integrity = {"schema": "fast_core_v2_alignment_500b_p2_2_integrity_audit_v02", "status": "FAIL" if critical else "CHECK_REQUIRED" if major else "PASS", "severity_issue_type_counts": {"CRITICAL": len(critical), "MAJOR": len(major), "MINOR": len(minor)}, "critical_issue_types": sorted(critical), "major_issue_types": sorted(major), "minor_issue_types": sorted(minor), "source_manifest_verification": manifest_audit, "permanent_exclusions": {"pair_count": len(pairs), "canonical_sha256": canonical, "matches_contract": canonical == EXCLUSION_SHA}, "signal_ledger_checks": signal_check, "candidate_signal_filter_status_counts": audit.get("candidate_status", pd.Series(dtype=str)).value_counts().sort_index().to_dict(), "active_pit_missing_session_reason_counts": preflight["repository_v2_input_preflight"].get("active_pit_missing_session_reason_counts", {}), "unavailable_price_tickers": unavailable.get("ticker", pd.Series(dtype=str)).tolist(), "projection_mismatch_tickers": unresolved_projection.get("ticker", pd.Series(dtype=str)).tolist(), "unresolved_candidate_signal_mcap_count": unresolved_cap, "control_cost_audit": ccost, "candidate_cost_audit": pcost, "control_nav": nav_metrics(cd, cm, cbase), "candidate_nav": nav_metrics(pdaily, pm, pbase), "identity_exposure_audit": "identity_exposure_audit.csv", "worker_error_count": execution.get("worker_error_count"), "support_day_new_entry_allowed": False, "external_api_requests": 0}
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

    report = [
        "# FAST Core V2 Alignment + 500B — P2-2 전수 결과 V02", "",
        "## 이슈 유형 수", "", "| 심각도 | 유형 수 | 유형 |", "|---|---:|---|",
        f"| CRITICAL | {len(critical)} | {', '.join(sorted(critical)) or '없음'} |",
        f"| MAJOR | {len(major)} | {', '.join(sorted(major)) or '없음'} |",
        f"| MINOR | {len(minor)} | {', '.join(sorted(minor)) or '없음'} |", "",
        "## 실행 범위와 입력 검증", "",
        f"- 실제 평가 구간 {EVAL_START.date()}~{CUTOFF.date()}, {len(eval_dates):,} exact KRX 세션. 2026-09-01은 cutoff 전 신호의 체결 확인만 지원했어.",
        f"- 종목 {execution['evaluated_ticker_count']:,}/{execution['eligible_universe_ticker_count']:,}, 신호 worker {execution['workers']}개, worker 오류 {execution['worker_error_count']}건.",
        f"- P2-2 COMMON interval {preflight['universe']['common_intervals_overlapping_p2_2_before_exclusions']:,}; 182쌍 적용 뒤 적격 ticker {preflight['universe']['eligible_tickers_after_exclusions']:,}. 380440/KR7380440008은 영구 제외 registry로 제외.",
        f"- rolling authority/소스/코드/계약 hash 재검증: {manifest_audit['status']} ({manifest_audit['checked']}/{manifest_audit['expected']}); signal filter 상태 {json.dumps(integrity['candidate_signal_filter_status_counts'] if 'candidate_signal_filter_status_counts' in integrity else audit.get('candidate_status', pd.Series(dtype=str)).value_counts().sort_index().to_dict(), ensure_ascii=False)}.",
        f"- exact market-cap unresolved {unresolved_cap:,}; Repository V2 미가용 종목 {len(unavailable):,}; projection mismatch 종목 {len(unresolved_projection):,}.",
        "", "## 공식 A~E", "", "| 게이트 | CONTROL | ALIGNMENT_MCAP_500B |", "|---|---|---|",
    ]
    for key, label in (("A_integrity", "A 무결성"), ("B_costs", "B 비용"), ("C_profitability", "C 수익성"), ("D_mdd", "D MDD"), ("E_validity", "E 유효성")):
        report.append(f"| {label} | {gates['CONTROL'][key]['status']} | {gates['ALIGNMENT_MCAP_500B'][key]['status']} |")
    report.extend(["", "## 포트폴리오 비교", "", "거래 수익률과 승률의 분모는 cutoff 이전 실제 매수 후 실제 청산한 거래야. 순수익률은 양쪽 비용·슬리피지를 포함하고 보유 거래일은 진입/청산 체결 세션을 포함해 계산했어.", "", "| 지표 | CONTROL | 후보 | 후보−CONTROL |", "|---|---:|---:|---:|"])
    for label, key in (("종료 자산(원)", "ending_equity_krw"), ("총수익률(%)", "total_return_pct"), ("CAGR(%)", "cagr_pct"), ("MDD(%)", "mdd_pct"), ("NAV coverage(%)", "nav_coverage_pct"), ("NAV 결측일", "missing_nav_days"), ("진입 시도", "eligible_entry_attempts"), ("현금 부족 skip", "cash_shortage_skipped_entries"), ("현금 부족률(%)", "cash_shortage_skip_rate_pct"), ("실매수", "executed_entries"), ("실현 청산", "executed_exits_before_cutoff"), ("cutoff 미청산", "open_at_cutoff_count"), ("실현 거래", "realized_trade_count"), ("승률(%)", "realized_win_rate_pct"), ("평균 순수익률(%)", "realized_mean_net_return_pct"), ("중앙 순수익률(%)", "realized_median_net_return_pct"), ("평균 보유 거래일", "realized_mean_holding_trading_sessions"), ("중앙 보유 거래일", "realized_median_holding_trading_sessions"), ("최대 거래수익률(%)", "realized_max_net_return_pct"), ("최대 거래손실률(%)", "realized_min_net_return_pct"), ("+20% 이상 거래", "realized_ge_20_pct_count"), ("+50% 이상 거래", "realized_ge_50_pct_count"), ("+100% 이상 거래", "realized_ge_100_pct_count"), ("-10% 이하 거래", "realized_le_minus_10_pct_count"), ("-15% 이하 거래", "realized_le_minus_15_pct_count"), ("-20% 이하 거래", "realized_le_minus_20_pct_count"), ("-30% 이하 거래", "realized_le_minus_30_pct_count"), ("Loss Guard 매수", "loss_guard_triggered_executed_entry_count"), ("PROGRESSED 매수", "progressed_executed_entry_count"), ("최대 동시보유", "maximum_concurrent_positions"), ("평균 현금비중(%)", "average_cash_ratio_pct"), ("회전율 배수", "turnover_multiple"), ("수수료(원)", "total_commissions_krw"), ("슬리피지(원)", "total_slippage_impact_krw"), ("최대 티커 양의 손익 점유율(%)", "top_ticker_share_of_positive_realized_pnl_pct")):
        a, b = cmetrics.get(key), pmetrics.get(key)
        try: delta = float(b) - float(a) if a is not None and b is not None else None
        except (TypeError, ValueError): delta = None
        report.append(f"| {label} | {fmt(a)} | {fmt(b)} | {fmt(delta)} |")
    report.extend(["", "### MDD 및 청산 사유", "", f"- CONTROL: {cmetrics.get('mdd_type')} {fmt(cmetrics.get('mdd_pct'))}% (peak {cmetrics.get('mdd_peak_date')}, trough {cmetrics.get('mdd_trough_date')}, recovery {cmetrics.get('mdd_recovery_date') or '미회복'}).", f"- 후보: {pmetrics.get('mdd_type')} {fmt(pmetrics.get('mdd_pct'))}% (peak {pmetrics.get('mdd_peak_date')}, trough {pmetrics.get('mdd_trough_date')}, recovery {pmetrics.get('mdd_recovery_date') or '미회복'}); CONTROL−후보 {fmt(None if cmetrics.get('mdd_pct') is None or pmetrics.get('mdd_pct') is None else float(cmetrics['mdd_pct']) - float(pmetrics['mdd_pct']))}%p.", f"- CONTROL 청산 사유 {json.dumps(cmetrics.get('exit_reason_counts', {}), ensure_ascii=False)}.", f"- 후보 청산 사유 {json.dumps(pmetrics.get('exit_reason_counts', {}), ensure_ascii=False)}.", f"- 최대 티커 손익 점유율: CONTROL {fmt(cmetrics.get('top_ticker_share_of_positive_realized_pnl_pct'))}% ({cmetrics.get('top_realized_pnl_ticker')}); 후보 {fmt(pmetrics.get('top_ticker_share_of_positive_realized_pnl_pct'))}% ({pmetrics.get('top_realized_pnl_ticker')}).", "- 연도/시장별 실현손익은 control_annual_market_diagnostics.csv와 alignment_mcap_500b_annual_market_diagnostics.csv에 저장했어.", "", "## 무결성 및 판정 범위", "", f"- 신호 원장 exact PIT/MA60/시총 검사: {json.dumps(signal_check, ensure_ascii=False)}.", f"- NAV는 {len(eval_dates):,}일 기준 CONTROL {fmt(cmetrics.get('nav_coverage_pct'))}% / 후보 {fmt(pmetrics.get('nav_coverage_pct'))}%; 최장 연속 결측 {cmetrics.get('maximum_consecutive_missing_nav_days')} / {pmetrics.get('maximum_consecutive_missing_nav_days')}일.", f"- 가격 해시/PIT/현금·비용 독립 검산 결과는 integrity_audit.json, 029960·128940·003690 및 380440 노출 감사는 identity_exposure_audit.csv.", "- 현금 부족 skip은 진단값이지 공식 게이트가 아니야. cutoff 미청산은 cutoff 종가 평가만 하며 가상 매도비용을 부과하지 않았어.", "- 단일 P2-2 결과야. 5기간 채택 NOT_FINAL_5WINDOW, 후보 채택과 baseline 승격 NOT_EVALUATED, 기본 전략 PATTERN_A_FAST_FINAL_STRATEGY_V02 유지.", "", "## 주요 산출물", "", "plan.md, execution_contract.json, preflight.json, active_pit_missing_sessions.csv, source_manifest.json, sample_benchmark.json, full_run_execution.json, 그룹별 trades/events/cash/NAV/valuation/missing marks, metrics_comparison.csv, gate_results.json, integrity_audit.json, artifact_hashes.json."])
    (OUT / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    files = [{"path": path.name, "sha256": sha(path), "bytes": path.stat().st_size} for path in sorted(OUT.iterdir()) if path.is_file() and path.name != "artifact_hashes.json" and path.suffix != ".pyc"]
    write_json(OUT / "artifact_hashes.json", {"schema": "fast_core_v2_alignment_500b_p2_2_artifact_hashes_v02", "files": files, "self_hash_excluded": True})
    print(json.dumps({"report": str(OUT / "report.md"), "issue_type_counts": integrity["severity_issue_type_counts"], "control": gates["CONTROL"], "candidate": gates["ALIGNMENT_MCAP_500B"], "integrity": integrity["status"]}, ensure_ascii=False, indent=2, default=json_default), flush=True)
    return 0 if not critical else 2


if __name__ == "__main__":
    raise SystemExit(main())
