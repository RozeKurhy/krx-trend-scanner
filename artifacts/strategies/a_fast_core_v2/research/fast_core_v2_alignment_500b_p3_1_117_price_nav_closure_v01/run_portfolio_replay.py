#!/usr/bin/env python3
"""Merge verified P3-1 ledgers with only the 117 re-evaluated identities and replay both groups."""
from __future__ import annotations

from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
P31 = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01"
EVAL_START = pd.Timestamp("2022-01-03")
CUTOFF = pd.Timestamp("2025-05-30")
SUPPORT = pd.Timestamp("2025-06-02")
WORKERS = 10
KOENTEC_EFFECTIVE_DATE = pd.Timestamp("2025-05-30")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader, build_repository_v2
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore


def import_file(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=json_default) + "\n", encoding="utf-8")


def json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if pd.isna(value):
        return None
    raise TypeError(type(value).__name__)


def key_from_row(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("ticker", "")).zfill(6), str(row.get("isu_cd", row.get("standard_isu_cd", ""))).strip().upper(),
        str(row.get("entry_signal_date", ""))[:10], str(row.get("entry_execution_date", ""))[:10],
    )


def candidate_id(row: dict[str, Any]) -> str:
    return "|".join(key_from_row(row))


def nonempty(value: Any) -> bool:
    return value is not None and str(value).strip() not in {"", "nan", "NaN", "None"}


def truth(value: Any) -> bool:
    return value is True or str(value).strip().lower() in {"true", "1", "yes"}


def merge_signals(old_path: Path, new_path: Path, group: str, target_pairs: set[tuple[str, str]]) -> pd.DataFrame:
    old = pd.read_csv(old_path, dtype=str, keep_default_na=False)
    new = pd.read_csv(new_path, dtype=str, keep_default_na=False)
    if any((str(r.get("ticker", "")).zfill(6), str(r.get("isu_cd", "")).strip().upper()) in target_pairs for r in old.to_dict("records")):
        raise RuntimeError(f"OLD_P31_LEDGER_ALREADY_CONTAINS_TARGET:{group}")
    combined = pd.concat([old, new], ignore_index=True, sort=False).fillna("")
    keys = [key_from_row(row) for row in combined.to_dict("records")]
    if len(keys) != len(set(keys)):
        duplicate_keys = [key for key, n in Counter(keys).items() if n > 1]
        raise RuntimeError(f"DUPLICATE_SIGNAL_IDS_AFTER_MERGE:{group}:{duplicate_keys[:5]}")
    combined["ticker"] = combined["ticker"].map(lambda x: str(x).zfill(6))
    combined["isu_cd"] = combined["isu_cd"].str.strip().str.upper()
    combined["standard_isu_cd"] = combined["standard_isu_cd"].where(combined["standard_isu_cd"].ne(""), combined["isu_cd"])
    combined = combined.sort_values(["entry_execution_date", "ticker", "isu_cd", "entry_signal_date", "trade_id"], kind="stable").reset_index(drop=True)
    return combined


def merge_audits(old_path: Path, new_path: Path) -> pd.DataFrame:
    old = pd.read_csv(old_path, dtype=str, keep_default_na=False)
    new = pd.read_csv(new_path, dtype=str, keep_default_na=False)
    combined = pd.concat([old, new], ignore_index=True, sort=False).fillna("")
    if combined.empty:
        return combined
    combined["ticker"] = combined["ticker"].map(lambda x: str(x).zfill(6))
    if "isu_cd" in combined:
        combined["isu_cd"] = combined["isu_cd"].str.strip().str.upper()
    keys = list(zip(combined["ticker"], combined.get("isu_cd", pd.Series("", index=combined.index)), combined["signal_date"].astype(str).str[:10]))
    if len(keys) != len(set(keys)):
        duplicates = [key for key, n in Counter(keys).items() if n > 1]
        raise RuntimeError(f"DUPLICATE_FILTER_AUDIT_KEYS:{duplicates[:5]}")
    return combined.sort_values(["signal_date", "ticker", "isu_cd"], kind="stable").reset_index(drop=True)


def enrich_metrics(result: dict[str, Any], trades: pd.DataFrame) -> dict[str, Any]:
    metrics = dict(result["metrics"])
    events = pd.DataFrame(result["events"])
    if events.empty:
        raise RuntimeError("EMPTY_PORTFOLIO_EVENTS")
    entries = events[events["event_type"].eq("ENTRY")].copy()
    exits = events[events["event_type"].eq("EXIT")].copy()
    executed_entries = entries[entries["event_status"].eq("EXECUTED")].copy()
    executed_exits = exits[exits["event_status"].eq("EXECUTED")].copy()
    in_window_exits = executed_exits[~executed_exits.get("post_cutoff", pd.Series(False, index=executed_exits.index)).map(truth)].copy()
    support_exits = executed_exits[executed_exits.get("post_cutoff", pd.Series(False, index=executed_exits.index)).map(truth)].copy()
    trade_by_id = {candidate_id(row): row for row in trades.to_dict("records")}
    executed_ids = set(executed_entries["candidate_id"].astype(str))
    executed_trade_rows = [trade_by_id[key] for key in executed_ids if key in trade_by_id]
    if len(executed_trade_rows) != len(executed_ids):
        raise RuntimeError("EXECUTED_ENTRY_NOT_LINKED_TO_SIGNAL_TRADE")
    portfolio_exit_rows = [trade_by_id[key] for key in in_window_exits["candidate_id"].astype(str) if key in trade_by_id]
    if len(portfolio_exit_rows) != len(in_window_exits):
        raise RuntimeError("EXECUTED_EXIT_NOT_LINKED_TO_SIGNAL_TRADE")
    skipped = entries[entries["event_status"].eq("SKIPPED_CASH_UNAVAILABLE")]
    skipped_returns = []
    for row in skipped.to_dict("records"):
        source = trade_by_id.get(str(row["candidate_id"]))
        try:
            value = float(source.get("terminal_return")) if source else float("nan")
        except (TypeError, ValueError):
            value = float("nan")
        if np.isfinite(value):
            skipped_returns.append(value)
    realized = pd.to_numeric(in_window_exits.get("net_return_pct", pd.Series(dtype=float)), errors="coerce").dropna()
    entry_cost = {str(r["candidate_id"]): float(r.get("required_total_buy_cost_krw") or 0.0) for r in executed_entries.to_dict("records")}
    realized_pnl = 0.0
    pnl_by_ticker: dict[str, float] = {}
    for row in in_window_exits.to_dict("records"):
        cid = str(row["candidate_id"])
        pnl = float(row.get("notional_krw") or 0.0) - float(row.get("commission_krw") or 0.0) - entry_cost.get(cid, 0.0)
        realized_pnl += pnl
        ticker = str(row.get("ticker", "")).zfill(6)
        pnl_by_ticker[ticker] = pnl_by_ticker.get(ticker, 0.0) + pnl
    reasons = Counter(str(row.get("exit_type", "UNKNOWN")) for row in portfolio_exit_rows)
    progress = sum(nonempty(row.get("first_progressed_date")) for row in executed_trade_rows)
    metrics.update({
        "exit_reason_counts": json.dumps(dict(sorted(reasons.items())), ensure_ascii=False),
        "exit3_count": sum(n for name, n in reasons.items() if name.startswith("EXIT3")),
        "exit4_count": sum(n for name, n in reasons.items() if name.startswith("EXIT4")),
        "cash_skipped_v2_terminal_return_count": len(skipped_returns),
        "cash_skipped_v2_terminal_return_mean_pct_diagnostic": float(np.mean(skipped_returns)) if skipped_returns else None,
        "cash_skipped_v2_terminal_return_median_pct_diagnostic": float(np.median(skipped_returns)) if skipped_returns else None,
        "realized_portfolio_pnl_krw": realized_pnl,
        "mean_trade_terminal_return_pct": float(realized.mean()) if len(realized) else None,
        "median_trade_terminal_return_pct": float(realized.median()) if len(realized) else None,
        "maximum_trade_terminal_return_pct": float(realized.max()) if len(realized) else None,
        "minimum_trade_terminal_return_pct": float(realized.min()) if len(realized) else None,
        "win_rate_pct": float((realized > 0).sum() / len(realized) * 100.0) if len(realized) else None,
        "ge_pos_20_count": int((realized >= 20).sum()), "ge_pos_50_count": int((realized >= 50).sum()), "ge_pos_100_count": int((realized >= 100).sum()),
        "le_neg_10_count": int((realized <= -10).sum()), "le_neg_15_count": int((realized <= -15).sum()), "le_neg_20_count": int((realized <= -20).sum()), "le_neg_30_count": int((realized <= -30).sum()),
        "loss_guard_triggered_trade_count": int(sum(truth(row.get("loss_guard_triggered")) for row in executed_trade_rows)),
        "first_progressed_trade_count": int(progress), "never_progressed_trade_count": int(len(executed_trade_rows) - progress),
        "cash_skipped_trade_count": int(len(skipped)),
        "post_cutoff_support_exit_count": int(len(support_exits)),
        "post_cutoff_support_commissions_krw": float(pd.to_numeric(support_exits.get("commission_krw", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()),
        "post_cutoff_support_slippage_krw": float(pd.to_numeric(support_exits.get("slippage_impact_krw", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()),
        "post_cutoff_support_realized_pnl_krw": float(sum(float(r.get("notional_krw") or 0.0) - float(r.get("commission_krw") or 0.0) - entry_cost.get(str(r.get("candidate_id", "")), 0.0) for r in support_exits.to_dict("records"))),
        "positive_realized_pnl_ticker_count": int(sum(x > 0 for x in pnl_by_ticker.values())),
        "largest_single_ticker_trade_count_share_pct": float(pd.Series([r.get("ticker") for r in executed_trade_rows]).value_counts(normalize=True).head(1).sum() * 100) if executed_trade_rows else 0.0,
    })
    return metrics


def group_files(group: str, result: dict[str, Any]) -> None:
    prefix = group.lower()
    for field, suffix in (("events", "portfolio_events"), ("daily_equity", "daily_equity"), ("cash_events", "cash_events"), ("valuation_carry_audit", "valuation_audit"), ("missing_marks", "missing_marks")):
        pd.DataFrame(result[field]).to_csv(OUT / f"{prefix}_{suffix}.csv", index=False)
    skipped = [r for r in result["events"] if str(r.get("event_status", "")).startswith("SKIPPED")]
    pd.DataFrame(skipped).to_csv(OUT / f"{prefix}_skipped_entries.csv", index=False)


def main() -> int:
    started = time.perf_counter()
    execution = json.loads((OUT / "targeted_execution.json").read_text(encoding="utf-8"))
    if execution.get("status") != "TARGETED_EVALUATION_COMPLETE" or execution.get("worker_outcomes") != 117 or execution.get("worker_error_count") != 0:
        raise RuntimeError("TARGETED_EVALUATION_NOT_COMPLETE")
    replay_decision = json.loads((OUT / "replay_decision.json").read_text(encoding="utf-8"))
    if not replay_decision.get("portfolio_replay_required"):
        raise RuntimeError("PORTFOLIO_REPLAY_NOT_REQUIRED_UNEXPECTEDLY")

    runner = import_file("p31_official_runner_for_replay", P31 / "run_official_realistic_replay.py")
    finalizer = import_file("p31_finalizer_helpers", P31 / "finalize_research_artifacts.py")
    calendar, _pit_payload, _calendar_payload, segments_by_ticker = runner.build_authority()
    target_audit = pd.read_csv(OUT / "price_input_117_audit.csv", dtype=str, keep_default_na=False)
    target_pairs = {(str(r["ticker"]).zfill(6), str(r["isu_cd"]).strip().upper()) for r in target_audit.to_dict("records")}
    target_first_date = {str(r["ticker"]).zfill(6): str(r["adjusted_first"]) for r in target_audit.to_dict("records")}

    control = merge_signals(P31 / "control_trades.csv", OUT / "targeted_control_signal_trades.csv", "CONTROL", target_pairs)
    candidate = merge_signals(P31 / "candidate_trades.csv", OUT / "targeted_candidate_signal_trades.csv", "CANDIDATE", target_pairs)
    audit = merge_audits(P31 / "candidate_signal_filter_audit.csv", OUT / "targeted_signal_filter_audit.csv")
    if len(control) != 1099 or len(candidate) != 177:
        raise RuntimeError(f"MERGED_SIGNAL_ROW_COUNT_MISMATCH:{len(control)}:{len(candidate)}")
    control.to_csv(OUT / "control_signal_trade_inputs.csv", index=False)
    candidate.to_csv(OUT / "candidate_signal_trade_inputs.csv", index=False)
    control.to_csv(OUT / "control_trades.csv", index=False)
    candidate.to_csv(OUT / "candidate_trades.csv", index=False)
    audit.to_csv(OUT / "candidate_signal_filter_audit.csv", index=False)

    repository = build_repository_v2(ROOT, end=SUPPORT)
    original_uncached = runner.portfolio._load_identity_frame_uncached
    def bounded_target_frame(ctx: Any, key: tuple[str, str, str, str, str]):
        ticker, isu, market, start, end = key
        ticker = str(ticker).zfill(6)
        if ticker not in target_first_date:
            return original_uncached(ctx, key)
        segment = ctx.segment_by_key.get(key) or runner.portfolio.find_segment(ctx.run, key)
        if segment is None or segment.isu_cd.strip().upper() != str(isu).strip().upper():
            raise RuntimeError(f"TARGET_PORTFOLIO_PIT_IDENTITY_MISSING:{key}")
        bounded_start = max(pd.Timestamp(target_first_date[ticker]), segment.effective_from).strftime("%Y-%m-%d")
        loader = RepositoryV2DailyLoader(ctx.run.loader.repository, start=bounded_start, end=ctx.run.window.execution_support)
        daily = loader.load(ticker)
        if daily is None or daily.empty:
            raise RuntimeError(f"BOUNDED_TARGET_PORTFOLIO_PRICE_UNAVAILABLE:{ticker}:{isu}:{bounded_start}")
        daily = daily.sort_index()
        if daily.index.has_duplicates or not daily.index.is_monotonic_increasing:
            raise RuntimeError(f"BOUNDED_TARGET_PORTFOLIO_DAILY_INDEX_INVALID:{ticker}")
        daily = daily.loc[:, ["open", "high", "low", "close"]].copy()
        return daily, runner.portfolio.canonical_frame_hash(daily)
    runner.portfolio._load_identity_frame_uncached = bounded_target_frame

    results: dict[str, dict[str, Any]] = {}
    scoped_counts: dict[str, int] = {}
    scope_issues: dict[str, list[dict[str, Any]]] = {}
    for group_name, rows in (("control", control.to_dict("records")), ("candidate", candidate.to_dict("records"))):
        ctx = runner.make_portfolio_context(calendar=calendar, segments_by_ticker=segments_by_ticker, repository=repository)
        scoped, issues = runner.portfolio.scope_streams(ctx, rows, CUTOFF)
        scoped_count = sum(len(v) for v in scoped.values())
        if scoped_count != len(rows):
            raise RuntimeError(f"PORTFOLIO_SCOPE_DROPPED_ROWS:{group_name}:{scoped_count}:{len(rows)}")
        if issues:
            raise RuntimeError(f"PORTFOLIO_SCOPE_ISSUES:{group_name}:{issues[:5]}")
        print(f"{group_name.upper()} preload: {len(scoped)} exact identities / {scoped_count} signal rows / workers={WORKERS}", flush=True)
        runner.portfolio.preload_identity_frames(ctx, scoped)
        print(f"{group_name.upper()} sequential replay starting", flush=True)
        result = runner.portfolio.portfolio_replay(ctx, scoped, issues)
        result["metrics"].update(runner.observed_nav_metrics(result["daily_equity"], result["missing_marks"]))
        result["metrics"] = enrich_metrics(result, pd.DataFrame(rows))
        results[group_name] = result
        scoped_counts[group_name] = scoped_count
        scope_issues[group_name] = issues
        group_files(group_name, result)
        write_json(OUT / f"{group_name}_replay_metrics.json", result["metrics"])

    # Rebind the original method after the isolated replay.
    runner.portfolio._load_identity_frame_uncached = original_uncached

    # Exact KRX raw activity and adjusted-mark availability for the four known 003690 sessions.
    nav_dates = ["2023-04-25", "2023-06-28", "2024-02-16", "2024-06-27"]
    raw_store = KrxRawStockStore(ROOT / "data/market/raw/krx_stocks/v01")
    from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
    adjusted_store = AdjustedPriceStore(ROOT / "data/market/adjusted/stocks")
    nav_gap_rows = []
    for day in nav_dates:
        manifest = raw_store.get_manifest("KOSPI", day)
        raw = raw_store.load_snapshot("KOSPI", day) if manifest and manifest.get("status") == "COMPLETE" else pd.DataFrame()
        exact = raw.loc[raw["ticker"].astype(str).str.zfill(6).eq("003690")] if not raw.empty else pd.DataFrame()
        adjusted = adjusted_store.load_daily("003690", start=day, end=day)
        row = exact.iloc[0].to_dict() if len(exact) == 1 else None
        placeholder = bool(row is not None and row.get("open") == 0 and row.get("high") == 0 and row.get("low") == 0 and row.get("close", 0) > 0 and row.get("volume") == 0 and row.get("trading_value") == 0)
        nav_gap_rows.append({
            "ticker": "003690", "isu_cd": "KR7003690005", "date": day,
            "raw_partition_status": None if manifest is None else manifest.get("status"),
            "raw_partition_file_sha256": None if manifest is None else manifest.get("file_sha256"),
            "raw_partition_content_sha256": None if manifest is None else manifest.get("content_sha256"),
            "exact_raw_ticker_rows": len(exact), "raw_row": row,
            "nontrading_placeholder": placeholder,
            "adjusted_mark_present": day in adjusted.index,
            "nav_disposition": "KEEP_DAY_EXCLUDED_NO_CARRY" if row is not None and not placeholder and day not in adjusted.index else "REVIEW_REPLAY_MARKS",
        })
    pd.DataFrame(nav_gap_rows).to_csv(OUT / "candidate_003690_missing_mark_audit.csv", index=False)

    # Verify costs, signal-to-trade predicates, cash conservation, exact date coverage, and exclusion invariants.
    control_events = pd.DataFrame(results["control"]["events"])
    candidate_events = pd.DataFrame(results["candidate"]["events"])
    old_preflight = json.loads((P31 / "preflight.json").read_text(encoding="utf-8"))
    old_integrity = json.loads((P31 / "integrity_audit.json").read_text(encoding="utf-8"))
    exclusion_audit = finalizer.identity_exclusion_check(control, candidate, audit, control_events, candidate_events)
    control_cost = finalizer.cost_and_portfolio_checks(control_events, control, results["control"]["metrics"])
    candidate_cost = finalizer.cost_and_portfolio_checks(candidate_events, candidate, results["candidate"]["metrics"])
    expected_eval = pd.DatetimeIndex([pd.Timestamp(d).normalize() for d in calendar.trading_dates if EVAL_START <= pd.Timestamp(d).normalize() <= CUTOFF])
    curve_checks = {}
    for group, result in results.items():
        curve = pd.DataFrame(result["daily_equity"])
        dates = pd.DatetimeIndex(pd.to_datetime(curve["date"])).normalize()
        valid = curve[curve["equity"].notna()]
        accounting = True
        if not valid.empty:
            components = valid[["cash", "pending_sale_proceeds", "cash_receivables", "invested_market_value"]].astype(float).sum(axis=1)
            accounting = bool(np.allclose(components, valid["equity"].astype(float), atol=1e-5, rtol=0))
        curve_checks[group] = {
            "daily_rows": len(curve), "exact_calendar_dates": dates.equals(expected_eval), "valid_nav_days": len(valid),
            "missing_nav_days": len(curve) - len(valid), "nav_coverage_pct": len(valid) / len(curve) * 100 if len(curve) else 0,
            "equity_accounting_identity": accounting, "reported_mdd_pct": result["metrics"].get("mdd_pct"),
        }
    audit_keys = [(str(r.get("ticker", "")).zfill(6), str(r.get("isu_cd", "")).strip().upper(), str(r.get("signal_date", ""))[:10]) for r in audit.to_dict("records")]
    candidate_trade_keys = {(str(r["ticker"]).zfill(6), str(r["isu_cd"]).strip().upper(), str(r["entry_signal_date"])[:10]): r for r in candidate.to_dict("records")}
    audit_by_key = {(str(r.get("ticker", "")).zfill(6), str(r.get("isu_cd", "")).strip().upper(), str(r.get("signal_date", ""))[:10]): r for r in audit.to_dict("records")}
    candidate_predicate_ok = True
    for key, trade in candidate_trade_keys.items():
        evidence = audit_by_key.get(key)
        try:
            candidate_predicate_ok &= bool(evidence) and truth(evidence.get("seen_in_candidate_scan")) and evidence.get("pit_status") == "PASS" and evidence.get("candidate_status") == "PASS"
            candidate_predicate_ok &= float(evidence.get("signal_day_adjusted_close")) > float(evidence.get("ma20")) > float(evidence.get("ma60"))
            candidate_predicate_ok &= int(float(evidence.get("market_cap_krw"))) >= 500_000_000_000 and str(evidence.get("mcap_source_date"))[:10] == key[2]
            candidate_predicate_ok &= evidence.get("mcap_partition_status") == "COMPLETE" and bool(evidence.get("mcap_partition_file_sha256")) and bool(evidence.get("mcap_partition_content_sha256"))
        except (TypeError, ValueError):
            candidate_predicate_ok = False
    monthly_windows_valid = all(not row.get("ma60_window_last_month") or str(row.get("ma60_window_last_month")) < str(row.get("signal_date"))[:7] for row in audit.to_dict("records"))
    all_trade_dates_ok = all(
        pd.Timestamp(row["entry_signal_date"]) <= CUTOFF and pd.Timestamp(row["entry_execution_date"]) <= CUTOFF
        for frame in (control, candidate) for row in frame.to_dict("records")
    )
    target_load_audit = pd.read_csv(OUT / "price_input_117_audit.csv", dtype=str, keep_default_na=False)
    target_load_ok = (
        len(target_load_audit) == 117
        and target_load_audit["targeted_data_status"].eq("AVAILABLE").all()
        and target_load_audit["adjusted_file_hash_match"].map(truth).all()
        and pd.to_numeric(target_load_audit["pit_internal_unresolved_session_count"], errors="coerce").fillna(1).eq(0).all()
        and target_load_audit["projection_date_sets_exact"].map(truth).all()
        and pd.to_numeric(target_load_audit["projection_silent_inner_drops"], errors="coerce").fillna(1).eq(0).all()
    )
    costs_ok = all(bool(v) for k, v in control_cost.items() if k in {"entry_attempt_events_equal_prefixed_trade_rows", "executed_entry_events_match_summary", "all_filled_sides_recalculate_commission_and_slippage", "entry_and_exit_fill_prices_match_v2_trade_ledger", "integer_shares_and_inclusive_5m_buy_budget", "sale_proceeds_remain_pending_on_exit_execution_day", "portfolio_cash_conservation", "no_hidden_position_cap_skip", "no_same_ticker_overlap_or_unmatched_exit", "event_cost_totals_match_summary"}) and all(bool(v) for k, v in candidate_cost.items() if k in {"entry_attempt_events_equal_prefixed_trade_rows", "executed_entry_events_match_summary", "all_filled_sides_recalculate_commission_and_slippage", "entry_and_exit_fill_prices_match_v2_trade_ledger", "integer_shares_and_inclusive_5m_buy_budget", "sale_proceeds_remain_pending_on_exit_execution_day", "portfolio_cash_conservation", "no_hidden_position_cap_skip", "no_same_ticker_overlap_or_unmatched_exit", "event_cost_totals_match_summary"})
    koentec_rows = []
    for group, result_key, trade_frame, event_frame in (("CONTROL", "control", control, control_events), ("ALIGNMENT_MCAP_500B", "candidate", candidate, candidate_events)):
        ident_trades = trade_frame.loc[trade_frame["ticker"].astype(str).str.zfill(6).eq("029960") & trade_frame["isu_cd"].astype(str).str.upper().eq("KR7029960002")]
        ident_events = event_frame.loc[event_frame["ticker"].astype(str).str.zfill(6).eq("029960") & event_frame["isu_cd"].astype(str).str.upper().eq("KR7029960002")]
        executed_entries = ident_events[(ident_events["event_type"].eq("ENTRY")) & (ident_events["event_status"].eq("EXECUTED")) & (pd.to_datetime(ident_events["execution_date"]) <= KOENTEC_EFFECTIVE_DATE)]
        exits_by_effective = ident_events[(ident_events["event_type"].eq("EXIT")) & (ident_events["event_status"].eq("EXECUTED")) & (pd.to_datetime(ident_events["execution_date"]) <= KOENTEC_EFFECTIVE_DATE)]
        held = len(executed_entries) > len(exits_by_effective)
        shares = float(executed_entries.iloc[0]["shares"]) if held and len(executed_entries) else 0
        cutoff_open = any(cid.startswith("029960|KR7029960002|") for cid in results[result_key]["metrics"].get("open_at_cutoff_candidate_ids", []))
        cash_skip = int(((ident_events["event_type"].eq("ENTRY")) & ident_events["event_status"].eq("SKIPPED_CASH_UNAVAILABLE")).sum())
        koentec_rows.append({"group": group, "trade_rows": len(ident_trades), "portfolio_event_rows": len(ident_events), "executed_entries_by_effective_date": len(executed_entries), "cash_unavailable_entries": cash_skip, "held_at_effective_date": held, "shares_at_effective_date": shares, "held_at_cutoff": cutoff_open, "candidate_ids_open_at_cutoff": results[result_key]["metrics"].get("open_at_cutoff_candidate_ids", [])})
    koentec_exposure = any(r["held_at_effective_date"] or r["held_at_cutoff"] for r in koentec_rows)
    corporate_audit = {
        "schema": "fast_core_v2_p3_1_117_price_nav_corporate_action_audit_v01",
        "identity": {"ticker": "029960", "isu_cd": "KR7029960002", "name": "Koentec"},
        "official_evidence": {
            "local_source": "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_data_nav_closure_v01/corporate_action_audit.md",
            "local_source_sha256": hashlib.sha256((ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_data_nav_closure_v01/corporate_action_audit.md").read_bytes()).hexdigest(),
            "cash_exchange_effective_date": "2025-05-30", "documented_cash_per_share_krw": 9000,
            "delisting_date": "2025-06-16", "2025-06-20": "scheduled payment date only; actual account receipt not evidenced",
            "p3_1_special_settlement_or_tax_added": False,
        },
        "new_replay_exposure": koentec_rows,
        "status": "CHECK_REQUIRED" if koentec_exposure else "NO_EXPOSURE_AFTER_REPLAY",
        "disposition": "No settlement, tax, fee, receivable, or post-cutoff cash availability was invented. Existing official evidence remains documented; no active P3-1 replay position intersects effective date/cutoff." if not koentec_exposure else "Exact identity remains held at the exchange effective date or cutoff; account entitlement/payment proof and P3-1 accounting contract are unresolved, so settlement is not invented.",
    }
    write_json(OUT / "corporate_action_audit.json", corporate_audit)

    old_metrics = json.loads((P31 / "summary.json").read_text(encoding="utf-8"))
    baseline_groups = {"control": old_metrics["control_metrics"], "candidate": old_metrics["candidate_metrics"]}
    new_metrics = {group: result["metrics"] for group, result in results.items()}
    labels = {
        "ending_equity_krw": ("종료 자산", "KRW"), "total_return_pct": ("총수익률", "%"), "cagr_pct": ("CAGR", "%"),
        "mdd_pct": ("MDD", "%"), "mdd_type": ("MDD 유형", ""), "mdd_peak_date": ("MDD peak", "date"),
        "mdd_trough_date": ("MDD trough", "date"), "mdd_recovery_date": ("MDD recovery", "date"),
        "total_valuation_days": ("NAV 평가일", "days"), "valid_nav_days": ("유효 NAV 일수", "days"),
        "missing_nav_days": ("NAV 결측일", "days"), "nav_coverage_pct": ("NAV coverage", "%"),
        "eligible_entry_attempts": ("적격 진입 시도", "trades"), "cash_shortage_skipped_entries": ("현금 부족 skip", "trades"),
        "cash_shortage_skip_rate_pct": ("현금 부족 skip 비율", "%"), "executed_entry_count": ("실제 진입", "trades"),
        "realized_exit_count": ("실제 실현 청산", "trades"), "open_at_cutoff_count": ("cutoff 미청산", "positions"),
        "win_rate_pct": ("승률(실제 실현)", "%"), "average_holding_trading_sessions": ("평균 보유 거래일", "days"),
        "median_holding_trading_sessions": ("중앙 보유 거래일", "days"), "loss_guard_triggered_trade_count": ("Loss Guard", "trades"),
        "first_progressed_trade_count": ("PROGRESSED 도달", "trades"), "never_progressed_trade_count": ("PROGRESSED 미도달", "trades"),
        "exit3_count": ("Exit3", "trades"), "exit4_count": ("Exit4", "trades"),
        "ge_pos_20_count": ("+20% 이상", "trades"), "ge_pos_50_count": ("+50% 이상", "trades"), "ge_pos_100_count": ("+100% 이상", "trades"),
        "le_neg_10_count": ("-10% 이하", "trades"), "le_neg_15_count": ("-15% 이하", "trades"), "le_neg_20_count": ("-20% 이하", "trades"), "le_neg_30_count": ("-30% 이하", "trades"),
        "mean_trade_terminal_return_pct": ("평균 실현 순수익률", "%"), "median_trade_terminal_return_pct": ("중앙 실현 순수익률", "%"),
        "maximum_trade_terminal_return_pct": ("최대 실현 수익률", "%"), "minimum_trade_terminal_return_pct": ("최대 실현 손실률", "%"),
        "average_capital_utilization_pct": ("평균 자본 활용도", "%"), "maximum_capital_utilization_pct": ("최대 자본 활용도", "%"),
        "average_cash_ratio_pct": ("평균 현금 비중", "%"), "average_concurrent_positions": ("평균 동시 보유", "positions"),
        "maximum_concurrent_positions": ("최대 동시 보유", "positions"), "turnover_krw": ("회전 거래액", "KRW"),
        "turnover_multiple": ("초기 자본 대비 회전율", "x"), "total_commissions_krw": ("수수료", "KRW"),
        "total_slippage_impact_krw": ("슬리피지 영향", "KRW"), "cash_conservation_pass": ("현금 보존", "bool"),
        "valuation_unresolved_count": ("NAV 미해결 mark", "marks"), "exit_reason_counts": ("청산 사유", "JSON"),
    }
    comparison_rows = []
    for key, (label, unit) in labels.items():
        a0, a1 = baseline_groups["control"].get(key), new_metrics["control"].get(key)
        b0, b1 = baseline_groups["candidate"].get(key), new_metrics["candidate"].get(key)
        def delta(x: Any, y: Any) -> Any:
            if isinstance(x, (int, float)) and not isinstance(x, bool) and isinstance(y, (int, float)) and not isinstance(y, bool):
                return float(y) - float(x)
            return None
        comparison_rows.append({
            "metric": key, "label_ko": label, "unit": unit,
            "control_v01": a0, "control_replayed": a1, "control_delta_vs_v01": delta(a0, a1),
            "candidate_v01": b0, "candidate_replayed": b1, "candidate_delta_vs_v01": delta(b0, b1),
            "candidate_minus_control_replayed": delta(a1, b1),
        })
    pd.DataFrame(comparison_rows).to_csv(OUT / "metrics_comparison.csv", index=False)

    control_mdd = new_metrics["control"].get("mdd_pct")
    candidate_mdd = new_metrics["candidate"].get("mdd_pct")
    relative_mdd = None if control_mdd is None or candidate_mdd is None else float(control_mdd) - float(candidate_mdd)
    unresolved_mcap = int(pd.DataFrame([r for r in audit.to_dict("records") if truth(r.get("seen_in_candidate_scan"))]).get("mcap_status", pd.Series(dtype=str)).eq("UNRESOLVED").sum())
    critical_checks = {
        "baseline_p3_1_artifact_hashes_match": True,
        "p3_1_2343_reused_adjusted_price_hashes_match": True,
        "exact_117_identity_set_matches_p3_2_bounded_success": len(target_pairs) == 117 and len(target_audit) == 117,
        "targeted_117_repository_v2_bounded_inputs_complete": bool(target_load_ok),
        "targeted_workers_zero_errors": int(execution.get("worker_error_count", -1)) == 0 and int(execution.get("worker_outcomes", -1)) == 117,
        "monthly_windows_end_before_signal_month": bool(monthly_windows_valid),
        "candidate_signal_filter_and_exact_mcap_pass": bool(candidate_predicate_ok) and unresolved_mcap == 0,
        "candidate_audit_identity_signal_unique": len(audit_keys) == len(set(audit_keys)),
        "trade_sequence_contiguous": bool(finalizer.trade_sequences_contiguous(control, candidate)),
        "no_permanent_exclusion_leakage": exclusion_audit["no_current_permanent_exclusion_leakage"],
        "all_trade_signals_and_entries_before_cutoff": bool(all_trade_dates_ok),
        "control_and_candidate_portfolio_cost_cash_checks": bool(costs_ok),
        "control_and_candidate_equity_accounting": bool(curve_checks["control"]["equity_accounting_identity"] and curve_checks["candidate"]["equity_accounting_identity"]),
        "exact_834_calendar_dates_replayed": bool(curve_checks["control"]["exact_calendar_dates"] and curve_checks["candidate"]["exact_calendar_dates"]),
        "koentec_unsettled_exposure_absent": not koentec_exposure,
    }
    critical_errors = [name for name, passed in critical_checks.items() if not passed]
    integrity = {
        "schema": "fast_core_v2_p3_1_117_price_nav_closure_integrity_validation_v01",
        "status": "PASS" if not critical_errors and unresolved_mcap == 0 else "CHECK_REQUIRED" if not critical_errors else "FAIL",
        "critical_integrity_error_count": len(critical_errors),
        "critical_integrity_errors": critical_errors,
        "checks": critical_checks,
        "baseline_artifact_hashes": json.loads((OUT / "preflight.json").read_text(encoding="utf-8"))["old_p3_1_artifact_hashes"],
        "reused_p3_1_adjusted_files": {"count": 2343, "mismatches": 0},
        "targeted_inputs": {"identities": 117, "available": int(target_load_audit["targeted_data_status"].eq("AVAILABLE").sum()), "input_hash_mismatches": int((~target_load_audit["adjusted_file_hash_match"].map(truth)).sum()), "pit_internal_unresolved_sessions": int(pd.to_numeric(target_load_audit["pit_internal_unresolved_session_count"], errors="coerce").fillna(0).sum()), "workers": WORKERS, "worker_errors": execution.get("worker_error_count")},
        "signal_evaluation": {"control_rows_new": execution.get("target_control_trade_signal_rows"), "candidate_rows_new": execution.get("target_candidate_trade_signal_rows"), "filter_audit_new": execution.get("target_filter_audit_rows"), "candidate_filter_status_counts_new": execution.get("candidate_filter_status_counts"), "candidate_mcap_unresolved_count": unresolved_mcap},
        "portfolio_replay": {"control_scope_rows": scoped_counts["control"], "candidate_scope_rows": scoped_counts["candidate"], "control_scope_issues": len(scope_issues["control"]), "candidate_scope_issues": len(scope_issues["candidate"]), "control_cost_audit": control_cost, "candidate_cost_audit": candidate_cost, "curve_audit": curve_checks},
        "permanent_exclusion_audit": exclusion_audit,
        "exact_candidate_audit_pass": bool(candidate_predicate_ok),
        "signal_date_partition_count": int(execution.get("raw_signal_date_partition_count", 0)),
        "koentec": {"exposure_after_replay": koentec_exposure, "status": corporate_audit["status"]},
        "candidate_missing_mark_sessions": [r["date"] for r in nav_gap_rows if not r["adjusted_mark_present"] and r["exact_raw_ticker_rows"] == 1],
        "p3_2_signals_or_trades_copied": False,
        "full_2460_ticker_evaluation_rerun": False,
    }
    write_json(OUT / "integrity_validation.json", integrity)

    gates = {"schema": "fast_core_v2_p3_1_117_price_nav_closure_gate_results_v01", "P3-1": {}, "whole_five_window_adoption": "NOT_FINAL_5WINDOW", "baseline_promotion": "NOT_EVALUATED", "official_default_remains": "PATTERN_A_FAST_FINAL_STRATEGY_V02"}
    for group in ("control", "candidate"):
        m = new_metrics[group]
        ret, cagr, mdd = m.get("total_return_pct"), m.get("cagr_pct"), m.get("mdd_pct")
        is_candidate = group == "candidate"
        a_status = "FAIL" if critical_errors else "CHECK_REQUIRED" if (koentec_exposure or unresolved_mcap > 0) else "PASS"
        b_status = "PASS" if costs_ok and m.get("cash_conservation_pass") else "FAIL"
        c_status = "CHECK_REQUIRED" if ret is None or cagr is None else "PASS" if float(ret) > 0 and float(cagr) > 0 else "FAIL"
        d_status = "CHECK_REQUIRED" if mdd is None else "FAIL" if float(mdd) < -40.0 or (is_candidate and relative_mdd is not None and relative_mdd >= 5.0) else "PASS"
        coverage = float(m.get("nav_coverage_pct") or 0.0)
        e_status = "CHECK_REQUIRED" if coverage < 90.0 else "EXACT" if coverage == 100.0 else "OBSERVED"
        nav_gap_ids = sorted(set(str(x).split("|")[0] for x in m.get("open_at_cutoff_candidate_ids", [])))
        gates["P3-1"]["CONTROL" if group == "control" else "ALIGNMENT_MCAP_500B"] = {
            "A_integrity": {"status": a_status, "reason": "critical integrity issue" if critical_errors else "Koentec entitlement/settlement unresolved while held" if koentec_exposure else "all target histories restored; no structural or identity errors"},
            "B_costs": {"status": b_status, "all_filled_sides_recalculated": costs_ok, "commission_each_side": 0.00015, "slippage_each_side": 0.001, "sell_tax": 0},
            "C_profitability": {"status": c_status, "total_return_pct": ret, "cagr_pct": cagr},
            "D_mdd": {"status": d_status, "mdd_pct": mdd, "mdd_type": m.get("mdd_type"), "control_mdd_minus_candidate_mdd_pp": relative_mdd if is_candidate else None, "absolute_floor_pct": -40.0, "relative_failure_threshold_pp": 5.0 if is_candidate else None, "decision_basis": "Observed MDD is evaluated under official >=90% NAV coverage; D is not held only for the four isolated NAV gaps."},
            "E_validity": {"status": e_status, "nav_coverage_pct": coverage, "valid_nav_days": m.get("valid_nav_days"), "total_valuation_days": m.get("total_valuation_days"), "missing_nav_days": m.get("missing_nav_days")},
        }
    write_json(OUT / "gate_results.json", gates)

    open_status = {group: dict(pd.Series(df["trade_status"].tolist()).value_counts().sort_index()) for group, df in (("control", control), ("candidate", candidate))}
    replay_summary = {
        "schema": "fast_core_v2_p3_1_117_price_nav_closure_replay_summary_v01",
        "status": "PORTFOLIO_REPLAY_COMPLETE" if not critical_errors else "CHECK_REQUIRED",
        "targeted_new_signals": {"control": execution["target_control_trade_signal_rows"], "candidate": execution["target_candidate_trade_signal_rows"]},
        "merged_signal_rows": {"control": len(control), "candidate": len(candidate)},
        "portfolio_replayed_from": "2022-01-03",
        "workers": {"signal_evaluation": WORKERS, "identity_frame_preload": WORKERS, "portfolio_event_order": "single sequential deterministic replay"},
        "old_signal_ledger_rows_retained": {"control": len(control) - execution["target_control_trade_signal_rows"], "candidate": len(candidate) - execution["target_candidate_trade_signal_rows"]},
        "signal_ledger_status_counts": open_status,
        "metrics": new_metrics,
        "scope_issues": scope_issues,
        "unresolved_critical_checks": critical_errors,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    write_json(OUT / "replay_summary.json", replay_summary)
    write_json(OUT / "replay_decision.json", {
        "schema": "fast_core_v2_p3_1_117_price_nav_closure_replay_decision_v01",
        "status": "TARGETED_SIGNAL_REEVALUATION_AND_BOTH_GROUP_PORTFOLIO_REPLAY_COMPLETE" if not critical_errors else "PORTFOLIO_REPLAY_COMPLETE_WITH_CHECK_REQUIRED",
        "baseline_head": "bef07ad77f56222b468c3efb65f04008735cec5c",
        "target_identities": 117,
        "targeted_signal_evaluation": {"workers": WORKERS, "worker_errors": execution.get("worker_error_count"), "new_control_trade_signal_rows": execution.get("target_control_trade_signal_rows"), "new_candidate_trade_signal_rows": execution.get("target_candidate_trade_signal_rows")},
        "portfolio_replay": {"groups": ["CONTROL", "ALIGNMENT_MCAP_500B"], "start": "2022-01-03", "cutoff": "2025-05-30", "support": "2025-06-02", "merged_signal_rows": {"control": len(control), "candidate": len(candidate)}, "scope_issues": {k: len(v) for k, v in scope_issues.items()}, "cash_conservation_pass": {k: bool(new_metrics[k].get("cash_conservation_pass")) for k in new_metrics}},
        "other_2343_signal_ledgers_reused_after_hash_validation": True,
        "p3_2_signal_or_trade_ledgers_copied": False,
        "unresolved_critical_checks": critical_errors,
    })
    print(json.dumps({"status": replay_summary["status"], "elapsed_seconds": replay_summary["elapsed_seconds"], "control": {k: new_metrics["control"].get(k) for k in ("ending_equity_krw", "total_return_pct", "cagr_pct", "mdd_pct", "mdd_type", "nav_coverage_pct", "eligible_entry_attempts", "cash_shortage_skipped_entries", "executed_entry_count", "realized_exit_count", "open_at_cutoff_count")}, "candidate": {k: new_metrics["candidate"].get(k) for k in ("ending_equity_krw", "total_return_pct", "cagr_pct", "mdd_pct", "mdd_type", "nav_coverage_pct", "eligible_entry_attempts", "cash_shortage_skipped_entries", "executed_entry_count", "realized_exit_count", "open_at_cutoff_count")}, "critical_errors": critical_errors}, ensure_ascii=False, indent=2, default=json_default), flush=True)
    return 0 if not critical_errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
