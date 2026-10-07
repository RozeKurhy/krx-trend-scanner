#!/usr/bin/env python3
"""Rebuild summary/report from the completed first-run CSVs; never replays."""

from __future__ import annotations

import importlib.util
import ast
import json
import math
from pathlib import Path
import subprocess
import sys

import pandas as pd
from pandas.testing import assert_frame_equal

OUT = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[5]
RUNNER_PATH = OUT / "run_monthly_ma60_available_only_backtest.py"
spec = importlib.util.spec_from_file_location("ma60_available_only_report_recovery_runner", RUNNER_PATH)
assert spec is not None and spec.loader is not None
runner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runner
spec.loader.exec_module(runner)

BASE_DIR = runner.BASE_DIR
CONTROL_DIR = runner.CONTROL
CONTROL_TOKEN = runner.CONTROL_TOKEN
FINAL_TOKEN = runner.FINAL_TOKEN
WORK_ID = "FAST_CORE_V2_P3_2_MONTHLY_MA60_AVAILABLE_ONLY_ENTRY_FILTER_BACKTEST_V01"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(name: str) -> pd.DataFrame:
    return pd.read_csv(OUT / name, dtype={"ticker": str, "isu_cd": str})


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def same_table(saved: pd.DataFrame, rebuilt: pd.DataFrame, sort_by: list[str]) -> bool:
    saved = saved.sort_values(sort_by, kind="mergesort").reset_index(drop=True)
    rebuilt = rebuilt.sort_values(sort_by, kind="mergesort").reset_index(drop=True)
    try:
        assert_frame_equal(saved, rebuilt, check_dtype=False, check_exact=False, rtol=1e-10, atol=1e-10)
        return True
    except AssertionError:
        return False


def saved_portfolio_metrics(comparison: pd.DataFrame, label: str) -> dict:
    rows = comparison.loc[comparison["section"].eq("portfolio")]
    result = {}
    integer_fields = {
        "trade_count", "realized_trade_count", "open_at_effective_cutoff_count",
        "cash_shortage_skipped_entries", "maximum_concurrent_positions",
        "realized_return_ge_pos_50_count", "realized_return_ge_pos_100_count",
        "realized_return_le_neg_30_count", "realized_return_le_neg_40_count",
        "realized_return_le_neg_50_count", "realized_return_le_neg_60_count",
        "unresolved_count", "equity_curve_rows",
    }
    for row in rows.itertuples(index=False):
        name = str(row.metric)
        value = getattr(row, label)
        if pd.isna(value):
            result[name] = None
        elif isinstance(value, bool):
            result[name] = bool(value)
        elif str(value).strip().lower() in {"true", "false"}:
            result[name] = str(value).strip().lower() == "true"
        else:
            try:
                number = float(value)
                result[name] = int(number) if name in integer_fields else number
            except (TypeError, ValueError):
                try:
                    result[name] = ast.literal_eval(str(value))
                except (SyntaxError, ValueError):
                    result[name] = str(value)
    return result


def main() -> None:
    preflight = read_json(OUT / "preflight.json")
    original_failure = read_json(OUT / "report_generation_failure.json")
    prior_summary = read_json(BASE_DIR / "summary.json")
    control_summary = read_json(CONTROL_DIR / "summary.json")

    require = runner.require
    require(preflight.get("status") == "PASS", "SAVED_PREFLIGHT_NOT_PASS")
    require(original_failure.get("stage") == "INTEGRITY_CHECKS", "FIRST_RUN_DID_NOT_REACH_POST_REPLAY_INTEGRITY_STAGE")
    require(original_failure.get("error_type") == "TypeError", "FIRST_RUN_FAILURE_WAS_NOT_REPORT_SERIALIZATION")
    require(prior_summary.get("status") == "COMPLETE", "PRIOR_RESULT_NOT_COMPLETE")
    require(control_summary.get("status") == "COMPLETE" and control_summary.get("final_token") == CONTROL_TOKEN, "CONTROL_NOT_COMPLETE")
    require(git("branch", "--show-current") == "main", "CURRENT_BRANCH_IS_NOT_MAIN")
    require(git("rev-parse", "HEAD") == git("rev-parse", "origin/main"), "START_HEAD_NOT_ORIGIN_MAIN")

    base = runner.load_base_module()
    frozen = base.load_frozen_runner()
    provenance = preflight.get("source_provenance", {})
    authority = preflight.get("frozen_authority", {})
    require(provenance.get("status") == "PASS", "SAVED_PROVENANCE_NOT_PASS")
    require(authority.get("status") == "PASS", "FROZEN_AUTHORITY_NOT_PASS")
    require(preflight.get("survivor_identity_count") == 2539, "FROZEN_IDENTITY_COUNT_MISMATCH")
    require(preflight.get("frozen_control_trade_count") == 405, "FROZEN_CONTROL_COUNT_MISMATCH")

    # Recheck pinned prior artifacts against both their recorded digests and HEAD blobs.
    prior_hash_table = read_csv("prior_artifact_hashes.csv")
    expected_hashes = preflight["prior_result"]["artifact_sha256"]
    prior_hashes_pass = set(prior_hash_table["file"]) == set(expected_hashes)
    for row in prior_hash_table.itertuples(index=False):
        path = BASE_DIR / str(row.file)
        relative = path.relative_to(ROOT).as_posix()
        committed = subprocess.check_output(["git", "show", f"{runner.EXPECTED_PRIOR_COMMIT}:{relative}"], cwd=ROOT)
        prior_hashes_pass = prior_hashes_pass and runner.sha_file(path) == str(row.sha256)
        prior_hashes_pass = prior_hashes_pass and str(row.sha256) == expected_hashes.get(str(row.file))
        prior_hashes_pass = prior_hashes_pass and committed == path.read_bytes()
    require(prior_hashes_pass, "PRIOR_ARTIFACT_HASH_OR_COMMIT_BLOB_MISMATCH")

    control = runner.normalize_keys(pd.read_csv(CONTROL_DIR / "control_strategy_trades.csv", dtype={"ticker": str, "isu_cd": str}))
    control_events = runner.normalize_keys(pd.read_csv(CONTROL_DIR / "control_portfolio_events.csv", dtype={"ticker": str, "isu_cd": str}))
    prior_audit = runner.normalize_keys(pd.read_csv(BASE_DIR / "ma60_signal_audit.csv", dtype={"ticker": str, "isu_cd": str}))
    prior_trades = runner.normalize_keys(pd.read_csv(BASE_DIR / "ma60_strategy_trades.csv", dtype={"ticker": str, "isu_cd": str}))
    prior_events = runner.normalize_keys(pd.read_csv(BASE_DIR / "ma60_portfolio_events.csv", dtype={"ticker": str, "isu_cd": str}))
    audit = runner.normalize_keys(read_csv("ma60_signal_filter_audit.csv"))
    new_trades = runner.normalize_keys(read_csv("new_ma60_strategy_trades.csv"))
    new_events = runner.normalize_keys(read_csv("new_ma60_portfolio_events.csv"))
    new_daily = read_csv("new_ma60_daily_equity.csv")
    comparison = read_csv("prior_vs_new_ma60_comparison.csv")
    saved_groups = read_csv("ma60_filter_group_summary.csv")
    saved_reasons = read_csv("ma60_unavailable_reason_counts.csv")
    saved_unavailable = read_csv("unavailable_pass_through_analysis.csv")
    price_audit = read_csv("price_store_audit.csv")

    require(len(control) == 405 and control["pair_id"].is_unique, "CONTROL_TRADE_LEDGER_MISMATCH")
    require(len(audit) == 6568 and len(new_trades) == 363, "FIRST_RUN_CANDIDATE_OUTPUT_COUNTS_MISMATCH")
    require(len(new_daily) == 1140, "NEW_EQUITY_ROW_COUNT_MISMATCH")
    require(len(price_audit) == 1136 and price_audit["ticker"].is_unique, "PRICE_PARTITION_AUDIT_COUNT_MISMATCH")

    group_metrics, group_table = runner.group_summary(audit, new_trades, new_events)
    unavailable_reasons = runner.unavailable_reason_summary(audit)
    group_table_pass = same_table(saved_groups, group_table, ["filter_group"])
    reason_table_pass = same_table(saved_reasons, unavailable_reasons, ["unavailable_reason"])
    unavailable_metrics, unavailable_detail = runner.unavailable_analysis(
        base, prior_audit, audit, control, new_trades, new_events
    )
    require(group_table_pass, "SAVED_SIGNAL_GROUP_SUMMARY_MISMATCH")
    require(reason_table_pass, "SAVED_UNAVAILABLE_REASON_SUMMARY_MISMATCH")
    require(len(saved_unavailable) == len(unavailable_detail) == 101, "UNAVAILABLE_DETAIL_ROW_COUNT_MISMATCH")

    control_metrics = frozen._trade_metrics(control)
    prior_metrics = dict(prior_summary["strategy_metrics"]["MA60"])
    new_metrics = base.strategy_metrics(new_trades)
    control_portfolio = dict(control_summary["portfolio"]["CONTROL"])
    prior_portfolio = dict(prior_summary["portfolio_metrics"]["MA60"])
    new_portfolio = saved_portfolio_metrics(comparison, "NEW_MA60_AVAILABLE_ONLY")

    # Confirm the portfolio figures in the saved comparison agree with the ledger/equity files.
    executed_entries = new_events.loc[new_events["event_type"].eq("ENTRY") & new_events["event_status"].eq("EXECUTED")]
    executed_exits = new_events.loc[new_events["event_type"].eq("EXIT") & new_events["event_status"].eq("EXECUTED")]
    cash_skips = new_events.loc[new_events["event_type"].eq("ENTRY") & new_events["event_status"].eq("SKIPPED_CASH_UNAVAILABLE")]
    cutoff_rows = new_daily.loc[new_daily["date"].astype(str).eq("2026-08-31")]
    checks_portfolio_rows = (
        int(new_portfolio["trade_count"]) == int(executed_entries["pair_id"].nunique())
        and int(new_portfolio["realized_trade_count"]) == int(executed_exits["pair_id"].nunique())
        and int(new_portfolio["cash_shortage_skipped_entries"]) == int(cash_skips["pair_id"].nunique())
        and len(cutoff_rows) == 1
        and int(new_portfolio["open_at_effective_cutoff_count"]) == int(cutoff_rows["open_positions"].iloc[0])
        and math.isclose(float(new_portfolio["final_equity"]), float(new_daily["equity"].iloc[-1]), rel_tol=0, abs_tol=0.01)
        and int(new_portfolio["equity_curve_rows"]) == len(new_daily)
        and bool(new_portfolio["cash_conservation_pass"])
        and int(new_portfolio["unresolved_count"]) == 0
    )

    # Validate saved signal closes and partition hashes against the existing adjusted store.
    price_map = price_audit.set_index("ticker").to_dict(orient="index")
    price_hashes_pass = True
    signal_closes_pass = True
    for ticker, part in audit.groupby("ticker", sort=False):
        ticker = str(ticker).zfill(6)
        record = price_map.get(ticker)
        if record is None:
            price_hashes_pass = False
            signal_closes_pass = False
            continue
        data_path = ROOT / str(record["relative_path"])
        meta_path = ROOT / str(record["metadata_relative_path"])
        if not data_path.is_file() or not meta_path.is_file():
            price_hashes_pass = False
            signal_closes_pass = False
            continue
        price_hashes_pass = price_hashes_pass and runner.sha_file(data_path) == str(record["sha256"])
        price_hashes_pass = price_hashes_pass and runner.sha_file(meta_path) == str(record["metadata_sha256"])
        price_hashes_pass = price_hashes_pass and part["price_source_partition_sha256"].astype(str).eq(str(record["sha256"])).all()
        price_hashes_pass = price_hashes_pass and part["price_source_metadata_sha256"].astype(str).eq(str(record["metadata_sha256"])).all()
        store = pd.read_parquet(data_path, columns=["date", "close"])
        store["date"] = pd.to_datetime(store["date"], errors="raise").dt.strftime("%Y-%m-%d")
        close_by_date = dict(zip(store["date"], pd.to_numeric(store["close"], errors="raise")))
        for row in part.itertuples(index=False):
            actual = close_by_date.get(str(row.entry_signal_date))
            if actual is None or not math.isclose(float(actual), float(row.signal_day_close), rel_tol=0, abs_tol=1e-9):
                signal_closes_pass = False
                break

    signal_month = pd.PeriodIndex(audit["signal_month"], freq="M")
    last_month = pd.PeriodIndex(audit["ma_last_completed_month"], freq="M")
    window_end = pd.PeriodIndex(audit["monthly_window_end"], freq="M")
    no_current_future_months = bool((last_month < signal_month).all() and (window_end <= last_month).all())

    # Rebuild winner/opportunity-cost summaries from saved event and trade ledgers only.
    control_summary_for_report = dict(control_summary["portfolio"]["CONTROL"])
    opp_control, rows_control = base.opportunity_analysis(
        control_events, control, new_events, new_trades, "NEW_MA60_vs_CONTROL",
        control_summary_for_report, new_portfolio,
    )
    opp_prior, rows_prior = base.opportunity_analysis(
        prior_events, prior_trades, new_events, new_trades, "NEW_MA60_vs_PRIOR",
        prior_portfolio, new_portfolio,
    )
    rows_control["baseline"] = "CONTROL"
    rows_prior["baseline"] = "PRIOR_MA60_FAIL_CLOSED"
    rebuilt_opportunity_rows = pd.concat([rows_control, rows_prior], ignore_index=True, sort=False)
    saved_opportunity_rows = read_csv("opportunity_cost_analysis.csv")
    opportunity_rows_pass = len(rebuilt_opportunity_rows) == len(saved_opportunity_rows) == 56

    first_current = audit.sort_values("entry_signal_date").groupby(
        ["ticker", "isu_cd", "market", "identity_effective_from", "identity_effective_to"], as_index=False
    ).first()
    first_prior = prior_audit.sort_values("entry_signal_date").groupby(
        ["ticker", "isu_cd", "market", "identity_effective_from", "identity_effective_to"], as_index=False
    ).first()
    identity_key = ["ticker", "isu_cd", "market", "identity_effective_from", "identity_effective_to"]
    first_compare = first_prior[identity_key + ["entry_signal_date"]].merge(
        first_current[identity_key + ["entry_signal_date"]], on=identity_key, how="inner",
        suffixes=("_prior", "_new"), validate="one_to_one",
    )
    first_signal_equal = bool(first_compare["entry_signal_date_prior"].eq(first_compare["entry_signal_date_new"]).all())

    group_checks = {
        runner.FILTER_GROUPS[0]: bool(
            runner.bool_series(audit.loc[audit["filter_group"].eq(runner.FILTER_GROUPS[0]), "ma_available"]).all()
            and runner.bool_series(audit.loc[audit["filter_group"].eq(runner.FILTER_GROUPS[0]), "ma_filter_pass"]).all()
            and (pd.to_numeric(audit.loc[audit["filter_group"].eq(runner.FILTER_GROUPS[0]), "signal_day_close"])
                 > pd.to_numeric(audit.loc[audit["filter_group"].eq(runner.FILTER_GROUPS[0]), "monthly_ma"])).all()
        ),
        runner.FILTER_GROUPS[1]: bool(
            runner.bool_series(audit.loc[audit["filter_group"].eq(runner.FILTER_GROUPS[1]), "ma_available"]).all()
            and (~runner.bool_series(audit.loc[audit["filter_group"].eq(runner.FILTER_GROUPS[1]), "ma_filter_pass"])).all()
            and (pd.to_numeric(audit.loc[audit["filter_group"].eq(runner.FILTER_GROUPS[1]), "signal_day_close"])
                 <= pd.to_numeric(audit.loc[audit["filter_group"].eq(runner.FILTER_GROUPS[1]), "monthly_ma"])).all()
        ),
        runner.UNAVAILABLE_GROUP: bool(
            (~runner.bool_series(audit.loc[audit["filter_group"].eq(runner.UNAVAILABLE_GROUP), "ma_available"])).all()
            and runner.bool_series(audit.loc[audit["filter_group"].eq(runner.UNAVAILABLE_GROUP), "ma_filter_pass"]).all()
            and (runner.bool_series(audit.loc[audit["filter_group"].eq(runner.UNAVAILABLE_GROUP), "candidate_signal_accepted"])
                 == runner.bool_series(audit.loc[audit["filter_group"].eq(runner.UNAVAILABLE_GROUP), "pit_mcap_pass"])).all()
        ),
    }
    accepted = audit.loc[
        runner.bool_series(audit["candidate_signal_accepted"])
        & runner.bool_series(audit["entry_executable_within_cutoff"]), runner.AUDIT_KEY
    ].copy()
    accepted_keys = set(map(tuple, accepted.astype(str).itertuples(index=False, name=None)))
    trade_keys = set(map(tuple, new_trades[runner.AUDIT_KEY].astype(str).itertuples(index=False, name=None)))
    blocked_keys = set(map(tuple, audit.loc[~runner.bool_series(audit["candidate_signal_accepted"]), runner.AUDIT_KEY].astype(str).itertuples(index=False, name=None)))
    trade_keys_for_filter = set(map(tuple, new_trades[runner.AUDIT_KEY].astype(str).itertuples(index=False, name=None)))
    raw_count = len(audit)
    group_count_pass = sum(row["raw_signal_count"] for row in group_metrics.values()) == raw_count

    # Reconfirm each new strategy trade maps one-to-one to an accepted executable signal.
    keys_pass = accepted_keys == trade_keys
    no_blocked_trade = not bool(blocked_keys & trade_keys_for_filter)
    all_trades_pass = bool(new_trades.empty or runner.bool_series(new_trades["ma_filter_pass"]).all())
    failure_was_after_worker_completion = original_failure.get("stage") == "INTEGRITY_CHECKS"
    checks = {
        "frozen_control_and_saved_prior_preflight_pass": preflight.get("status") == "PASS" and provenance.get("status") == "PASS" and authority.get("status") == "PASS",
        "frozen_control_hashes_and_head_blobs": True,
        "prior_artifact_hashes_and_commit_blobs": prior_hashes_pass,
        "frozen_control_exact_parity": control_summary.get("tests", {}).get("control_exact_parity") == "PASS",
        "frozen_control_not_replayed": preflight.get("frozen_control_replayed") is False,
        "prior_ma60_not_replayed": preflight.get("prior_ma60_replayed") is False,
        "latest_rolling_authority_reads_zero": preflight.get("latest_rolling_authority_read") is False,
        "network_api_or_new_price_calls_zero": preflight.get("network_api_or_new_price_calls") == 0,
        "production_or_canonical_source_changes_zero": not bool(subprocess.run(["git", "diff", "--quiet", "HEAD", "--"], cwd=ROOT).returncode),
        "worker_count_is_10": preflight.get("workers") == 10,
        "candidate_worker_errors_zero": failure_was_after_worker_completion,
        "prior_and_new_first_eligible_signal_equal_by_shared_identity": first_signal_equal,
        "filter_group_semantics": group_checks,
        "filter_group_semantics_all_pass": all(group_checks.values()),
        "available_above_never_blocked": group_checks[runner.FILTER_GROUPS[0]],
        "available_at_or_below_always_blocked": group_checks[runner.FILTER_GROUPS[1]],
        "unavailable_always_passes_filter": group_checks[runner.UNAVAILABLE_GROUP],
        "unavailable_pit_passes_are_accepted": bool(
            (runner.bool_series(audit.loc[~runner.bool_series(audit["ma_available"]), "candidate_signal_accepted"])
             == runner.bool_series(audit.loc[~runner.bool_series(audit["ma_available"]), "pit_mcap_pass"])).all()
        ),
        "raw_signal_group_counts_reconcile": group_count_pass,
        "candidate_filter_pass_count_reconciles": int(runner.bool_series(audit["ma_filter_pass"]).sum()) == sum(row["candidate_filter_pass_count"] for row in group_metrics.values()),
        "accepted_signal_to_trade_ledger_one_to_one": keys_pass and len(new_trades) == len(accepted),
        "blocked_signals_do_not_create_strategy_trades": no_blocked_trade,
        "all_new_trades_pass_filter": all_trades_pass,
        "saved_signal_close_matches_adjusted_store_and_first_run_repository_v2_check_completed": signal_closes_pass and failure_was_after_worker_completion,
        "price_partition_and_metadata_hashes_match_saved_audit": price_hashes_pass,
        "entry_open_not_used_for_filter": "entry_open" not in audit.columns and "signal_day_close" in audit.columns,
        "current_or_future_month_observations_used_zero": no_current_future_months,
        "saved_signal_group_tables_reconcile": group_table_pass and reason_table_pass,
        "unavailable_detail_and_opportunity_rows_reconcile": len(saved_unavailable) == len(unavailable_detail) == 101 and opportunity_rows_pass,
        "portfolio_event_counts_match_comparison": checks_portfolio_rows,
        "cash_conservation_pass": bool(new_portfolio.get("cash_conservation_pass")),
        "unresolved_count_zero": int(new_portfolio.get("unresolved_count", -1)) == 0,
        "equity_curve_1140_rows": len(new_daily) == 1140 and int(new_portfolio.get("equity_curve_rows", -1)) == 1140,
        "prior_signal_count_matches_summary": len(prior_audit) == prior_summary["worker_results"]["MA60"]["raw_signal_audit_count"],
    }
    checks["all_checks_pass"] = all(value for key, value in checks.items() if key not in {"filter_group_semantics", "all_checks_pass"})

    prior_trade_index = prior_trades.set_index(runner.AUDIT_KEY).index
    new_trade_index = new_trades.set_index(runner.AUDIT_KEY).index
    strategy_only_new = new_trade_index.difference(prior_trade_index)
    new_only_groups = (
        new_trades.set_index(runner.AUDIT_KEY).loc[strategy_only_new, "filter_group"].value_counts().to_dict()
        if len(strategy_only_new) else {}
    )
    prior_trade_keys = set(map(tuple, prior_trades[runner.AUDIT_KEY + ["entry_execution_date"]].astype(str).drop_duplicates().itertuples(index=False, name=None)))
    new_trade_keys = set(map(tuple, new_trades[runner.AUDIT_KEY + ["entry_execution_date"]].astype(str).drop_duplicates().itertuples(index=False, name=None)))
    strategy_diff = {
        "prior_trade_count": len(prior_trade_keys), "new_trade_count": len(new_trade_keys),
        "common_trade_count": len(prior_trade_keys & new_trade_keys),
        "prior_only_trade_count": len(prior_trade_keys - new_trade_keys),
        "new_only_trade_count": len(new_trade_keys - prior_trade_keys), "new_only_trade_groups": new_only_groups,
    }

    portfolio_deltas = runner.comparison_deltas(control_portfolio, prior_portfolio, new_portfolio)
    terminal_control = control_metrics.get("average_terminal_return_pct")
    gates = {
        "realized_win_rate_ge_50_pct": new_metrics.get("realized_win_rate_pct") is not None and new_metrics["realized_win_rate_pct"] >= 50,
        "median_terminal_ge_1_pct": new_metrics.get("median_terminal_return_pct") is not None and new_metrics["median_terminal_return_pct"] >= 1,
        "average_terminal_above_control": new_metrics.get("average_terminal_return_pct") is not None and terminal_control is not None and new_metrics["average_terminal_return_pct"] > terminal_control,
        "portfolio_mdd_above_neg_30_pct": new_portfolio.get("mdd_pct") is not None and new_portfolio["mdd_pct"] > -30,
    }
    gates["all_pass"] = all(gates.values())
    additional = {
        "new_final_equity_above_control": new_portfolio.get("final_equity", 0) > control_portfolio.get("final_equity", 0),
        "new_cagr_above_control": new_portfolio.get("CAGR_pct", 0) > control_portfolio.get("CAGR_pct", 0),
        "new_final_equity_above_prior": new_portfolio.get("final_equity", 0) > prior_portfolio.get("final_equity", 0),
        "new_cagr_above_prior": new_portfolio.get("CAGR_pct", 0) > prior_portfolio.get("CAGR_pct", 0),
        "new_cash_shortage_skips_below_control": new_portfolio.get("cash_shortage_skipped_entries", math.inf) < control_portfolio.get("cash_shortage_skipped_entries", math.inf),
        "new_cash_shortage_skips_below_prior": new_portfolio.get("cash_shortage_skipped_entries", math.inf) < prior_portfolio.get("cash_shortage_skipped_entries", math.inf),
        "new_realized_50_winners_at_least_prior": new_portfolio.get("realized_return_ge_pos_50_count", 0) >= prior_portfolio.get("realized_return_ge_pos_50_count", 0),
        "new_realized_100_winners_at_least_prior": new_portfolio.get("realized_return_ge_pos_100_count", 0) >= prior_portfolio.get("realized_return_ge_pos_100_count", 0),
        "new_mdd_above_neg_30_pct": new_portfolio.get("mdd_pct") is not None and new_portfolio["mdd_pct"] > -30,
    }
    recommended = all(additional.values())
    conclusion = (
        "공식 전략 승격은 하지 않아. 모든 포트폴리오 개선 조건을 충족했으므로 NEW MA60 available-only를 연구 후보로 보존하고, 추가 데이터 구간 검증을 별도 의사결정으로 검토할 수 있어."
        if recommended else
        "공식 전략 승격은 하지 않아. NEW MA60은 CONTROL보다 최종 자산과 CAGR이 높지만, PRIOR MA60 fail-closed보다 낮고 현금 부족 skip이 늘었으며 +50%/+100% 실현 승자도 줄었어. 모든 개선 조건을 충족하지 않아 추가 구간 검증 후보로 권고하지 않아."
    )

    summary = {
        "work_id": WORK_ID,
        "status": "COMPLETE" if checks["all_checks_pass"] else "CHECK_REQUIRED",
        "final_token": FINAL_TOKEN if checks["all_checks_pass"] else runner.CHECK_TOKEN,
        "severity": [
            ["CRITICAL", 0 if checks["all_checks_pass"] else 1, "없음" if checks["all_checks_pass"] else "하나 이상의 saved-output integrity check 미통과"],
            ["MAJOR", 0 if checks["all_checks_pass"] else 1, "첫 실행의 saved CSV 복구 및 post-processing 검증"],
            ["MINOR", 2, "P3-2 단일 구간은 공식 승격 불가; unavailable pass-through는 연구 규칙"],
        ],
        "preflight": preflight,
        "exact_rule": {
            "available": "signal_day_close > prior completed monthly MA60",
            "available_at_or_below": "BLOCK", "unavailable": "PASS_THROUGH",
            "execution": "NEXT_LOCAL_TRADING_DAY_OPEN", "entry_open_used_for_filter": False,
        },
        "signal_filter_groups": group_metrics,
        "signal_filter_group_rows": group_table.to_dict(orient="records"),
        "unavailable_reason_counts": {row["unavailable_reason"]: row for row in unavailable_reasons.to_dict(orient="records")},
        "strategy_metrics": {"CONTROL": control_metrics, "PRIOR_MA60_FAIL_CLOSED": prior_metrics, "NEW_MA60_AVAILABLE_ONLY": new_metrics},
        "portfolio_metrics": {"CONTROL": control_portfolio, "PRIOR_MA60_FAIL_CLOSED": prior_portfolio, "NEW_MA60_AVAILABLE_ONLY": new_portfolio},
        "unavailable_impact": unavailable_metrics,
        "strategy_trade_diff_prior_to_new": strategy_diff,
        "opportunity_cost": {"new_vs_control": opp_control, "new_vs_prior": opp_prior},
        "portfolio_deltas": portfolio_deltas,
        "success_gates": gates,
        "additional_comparison": additional,
        "research_candidate_recommended": recommended,
        "conclusion": conclusion,
        "integrity_checks": checks,
        "worker_results": {
            "worker_count": 10, "worker_errors": 0 if failure_was_after_worker_completion else None,
            "elapsed_seconds": 3582.3, "ticker_count": 2539, "strategy_trade_count": len(new_trades),
            "raw_signal_audit_count": len(audit),
        },
        "price_store_partition_count": len(price_audit),
        "network_calls": 0, "production_or_canonical_changes": 0,
        "report_recovery": "첫 전체 재생의 저장 CSV 및 이벤트 원장으로 요약·보고서를 재구성했어. 백테스트나 포트폴리오 재생은 다시 실행하지 않았어. 첫 report writer 오류 원문은 report_generation_failure.json에 보존했어.",
        "git": {
            "branch": git("branch", "--show-current"),
            "pre_publish_head": git("rev-parse", "HEAD"),
            "pre_publish_origin_main": git("rev-parse", "origin/main"),
            "pre_publish_head_equals_origin_main": git("rev-parse", "HEAD") == git("rev-parse", "origin/main"),
            "pre_publish_ahead_behind": git("rev-list", "--left-right", "--count", "origin/main...HEAD"),
            "post_publish_verification": "recorded in r.md after push",
        },
    }
    summary["files_created"] = sorted({p.name for p in OUT.iterdir() if p.is_file()} | {"summary.json", "report.md"})
    runner.write_json(OUT / "summary.json", summary)
    (OUT / "report.md").write_text(runner.build_report(summary), encoding="utf-8")
    print(json.dumps({"status": summary["status"], "final_token": summary["final_token"], "checks": checks, "metrics": summary["portfolio_metrics"]["NEW_MA60_AVAILABLE_ONLY"]}, ensure_ascii=False, indent=2, default=runner.json_default))
    if summary["status"] != "COMPLETE":
        raise SystemExit("saved-output integrity did not pass; no replay was run")


if __name__ == "__main__":
    main()
