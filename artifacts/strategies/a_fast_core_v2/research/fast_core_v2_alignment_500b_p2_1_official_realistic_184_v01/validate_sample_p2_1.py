#!/usr/bin/env python3
"""Check the saved representative P2-1 evaluator and portfolio sample before full run."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
P31 = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01"
EXPECTED_START = "2021-01-04"
EXPECTED_END = "2025-05-30"
EXPECTED_SESSIONS = int(json.loads((OUT / "preflight.json").read_text(encoding="utf-8"))["date_authorities"]["evaluation_sessions"])


def import_helpers():
    path = P31 / "finalize_research_artifacts.py"
    spec = importlib.util.spec_from_file_location("p2_1_sample_p3_helpers", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("P3_FINALIZER_HELPER_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def read_csv(name: str) -> pd.DataFrame:
    try:
        return pd.read_csv(OUT / name, dtype=str, keep_default_na=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def main() -> int:
    benchmark = json.loads((OUT / "sample_benchmark.json").read_text(encoding="utf-8"))
    selection = json.loads((OUT / "sample_tickers.json").read_text(encoding="utf-8"))
    expected_tickers = set(selection["tickers"])
    control = read_csv("sample_control_trades.csv")
    candidate = read_csv("sample_candidate_trades.csv")
    events = {group: read_csv(f"sample_{group}_portfolio_events.csv") for group in ("control", "candidate")}
    daily = {group: read_csv(f"sample_{group}_daily_equity.csv") for group in ("control", "candidate")}
    price = read_csv("sample_ticker_price_source_audit.csv")
    errors = read_csv("sample_worker_errors.csv")
    helpers = import_helpers()
    checks: dict[str, Any] = {
        "sample_status_completed": benchmark.get("status") == "SAMPLE_COMPLETED",
        "evaluated_ticker_count_matches_selection": int(benchmark.get("evaluated_ticker_count", 0)) == len(expected_tickers),
        "sample_source_tickers_match_selection": set(price.get("ticker", pd.Series(dtype=str)).astype(str).str.zfill(6)) == expected_tickers,
        "worker_error_count_zero": int(benchmark.get("worker_error_count", 0)) == 0 and errors.empty,
        "all_sample_prices_available": bool(len(price) == len(expected_tickers) and price.get("data_status", pd.Series(dtype=str)).eq("AVAILABLE").all()),
        "estimated_full_wall_under_2_hours": float(benchmark.get("estimated_full_wall_seconds", 9e99)) <= 7200,
        "control_scope_issues_zero": int(benchmark.get("scope_issue_counts", {}).get("CONTROL", -1)) == 0,
        "candidate_scope_issues_zero": int(benchmark.get("scope_issue_counts", {}).get("ALIGNMENT_MCAP_500B", -1)) == 0,
    }
    cost_audits = {}
    coverage_by_group = {}
    for group, trades in (("CONTROL", control), ("ALIGNMENT_MCAP_500B", candidate)):
        group_key = "control" if group == "CONTROL" else "candidate"
        event = events[group_key]
        equity_values = pd.to_numeric(daily[group_key].get("equity", pd.Series(dtype=str)), errors="coerce")
        nav_coverage = 100.0 * equity_values.notna().sum() / len(daily[group_key]) if len(daily[group_key]) else 0.0
        checks[f"{group.lower()}_nav_has_exact_session_count"] = len(daily[group_key]) == EXPECTED_SESSIONS
        # Sample coverage is diagnostic; W says coverage below 90% alone
        # must not block a full P2-1 run.
        coverage_by_group[group] = nav_coverage
        checks[f"{group.lower()}_nav_starts_and_ends_on_p2_dates"] = bool(len(daily[group_key]) and daily[group_key]["date"].iloc[0] == EXPECTED_START and daily[group_key]["date"].iloc[-1] == EXPECTED_END)
        checks[f"{group.lower()}_support_day_not_in_cutoff_nav"] = not daily[group_key]["date"].astype(str).str[:10].eq("2025-06-02").any()
        audit_event = event.copy()
        if "shares" in audit_event:
            numeric_shares = pd.to_numeric(audit_event["shares"], errors="coerce")
            executed_mask = audit_event.get("event_status", pd.Series(dtype=str)).eq("EXECUTED")
            executed_shares = numeric_shares.loc[executed_mask]
            checks[f"{group.lower()}_executed_share_values_are_integer"] = bool(
                executed_shares.notna().all()
                and (executed_shares.mod(1).eq(0)).all()
            )
            # CSV may serialize integer share counts as e.g. "285.0" when
            # other event rows have blanks; normalize to numeric before the
            # shared checker performs its integer assertion.
            audit_event["shares"] = numeric_shares.fillna(-1).astype(float)
        audit = helpers.cost_and_portfolio_checks(audit_event, trades, benchmark["control_metrics" if group == "CONTROL" else "candidate_metrics"])
        cost_audits[group] = audit
        checks[f"{group.lower()}_cost_cash_invariants_pass"] = all(bool(audit.get(key)) for key in ("entry_attempt_events_equal_prefixed_trade_rows", "executed_entry_events_match_summary", "all_filled_sides_recalculate_commission_and_slippage", "entry_and_exit_fill_prices_match_v2_trade_ledger", "integer_shares_and_inclusive_5m_buy_budget", "sale_proceeds_remain_pending_on_exit_execution_day", "portfolio_cash_conservation", "no_hidden_position_cap_skip", "no_same_ticker_overlap_or_unmatched_exit", "event_cost_totals_match_summary"))
        entries = event.loc[event.get("event_type", pd.Series(dtype=str)).eq("ENTRY")] if not event.empty else pd.DataFrame()
        checks[f"{group.lower()}_each_signal_attempt_has_one_entry_event"] = len(entries) == len(trades)
    candidate_audit = read_csv("sample_candidate_signal_filter_audit.csv")
    pass_rows = candidate_audit.loc[
        candidate_audit.get("candidate_status", pd.Series(dtype=str)).eq("PASS")
        & candidate_audit.get("signal_date", pd.Series(dtype=str)).astype(str).lt(EXPECTED_END)
    ]
    accepted_keys = {(str(row.get("ticker", "")).zfill(6), str(row.get("isu_cd", "")).strip().upper(), str(row.get("entry_signal_date", ""))[:10]) for row in candidate.to_dict("records")}
    audit_keys = {(str(row.get("ticker", "")).zfill(6), str(row.get("isu_cd", "")).strip().upper(), str(row.get("signal_date", ""))[:10]) for row in pass_rows.to_dict("records")}
    checks["candidate_passed_filter_rows_match_candidate_signal_trades"] = accepted_keys == audit_keys
    checks["candidate_passes_have_exact_market_cap_partition"] = bool(pass_rows.get("mcap_partition_status", pd.Series(dtype=str)).eq("COMPLETE").all() and pass_rows.get("mcap_source_date", pd.Series(dtype=str)).eq(pass_rows.get("signal_date", pd.Series(dtype=str))).all())
    result = {"schema": "fast_core_v2_alignment_500b_p2_1_sample_validation_v01", "status": "PASS" if all(checks.values()) else "CHECK_REQUIRED", "checks": checks, "nav_coverage_pct_by_group": coverage_by_group, "nav_coverage_below_90_is_diagnostic_only": True, "control_cost_audit": cost_audits.get("CONTROL"), "candidate_cost_audit": cost_audits.get("ALIGNMENT_MCAP_500B"), "candidate_filter_status_counts": candidate_audit.get("candidate_status", pd.Series(dtype=str)).value_counts().sort_index().to_dict(), "candidate_cutoff_day_pass_signals_excluded_from_order_ledger": int((candidate_audit.get("candidate_status", pd.Series(dtype=str)).eq("PASS") & candidate_audit.get("signal_date", pd.Series(dtype=str)).astype(str).ge(EXPECTED_END)).sum()), "estimated_full_wall_hours": benchmark.get("estimated_full_wall_hours"), "full_run_allowed": bool(all(checks.values())), "full_run_requires_zero_structural_findings_and_estimated_wall_under_2h": True}
    (OUT / "sample_validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str), flush=True)
    return 0 if result["full_run_allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
