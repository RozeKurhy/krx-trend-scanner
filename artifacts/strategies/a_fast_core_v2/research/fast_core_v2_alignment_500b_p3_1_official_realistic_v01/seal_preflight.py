#!/usr/bin/env python3
"""Seal P3-1 authorities, exact dates, PIT/price bounds, and KRX partitions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data.market_calendar import load_rolling_production_market_calendar
from trend_scanner.data.rolling_market_data_refresh import (
    load_rolling_authority,
    validate_merged_authority_coherence,
)
from trend_scanner.universe.permanent_identity_exclusions import PERMANENT_IDENTITY_EXCLUSIONS

EVAL_START = pd.Timestamp("2022-01-03")
CUTOFF = pd.Timestamp("2025-05-30")
SUPPORT = pd.Timestamp("2025-06-02")
TARGET = ("380440", "KR7380440008")
PRICE_DIR = ROOT / "data/market/adjusted/stocks"
ROLLING = ROOT / "data/market/rolling_authority"
RAW_DIR = ROOT / "data/market/raw/krx_stocks/v01"

REFERENCE_PATHS = [
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


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    origin_main = subprocess.check_output(["git", "rev-parse", "origin/main"], cwd=ROOT, text=True).strip()
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()

    manifest = load_rolling_authority(ROLLING)
    pit_payload, calendar_payload = validate_merged_authority_coherence(manifest, ROLLING)
    calendar = load_rolling_production_market_calendar(ROOT)
    if calendar is None:
        raise RuntimeError("ROLLING_MARKET_CALENDAR_UNAVAILABLE")
    trading_dates = pd.DatetimeIndex(calendar.trading_dates).normalize()
    eval_dates = trading_dates[(trading_dates >= EVAL_START) & (trading_dates <= CUTOFF)]
    support_is_next = bool(len(trading_dates[trading_dates > CUTOFF]) and trading_dates[trading_dates > CUTOFF][0] == SUPPORT)

    exclusion_pairs = {
        (str(ticker).zfill(6), str(isu).strip().upper())
        for ticker, isu in PERMANENT_IDENTITY_EXCLUSIONS
    }
    canonical_payload = {
        "schema": "sorted_exact_pair_json_v01",
        "pairs": [list(pair) for pair in sorted(exclusion_pairs)],
    }
    canonical_text = json.dumps(canonical_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    canonical_sha256 = hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()

    common_rows = []
    target_rows = []
    for row in pit_payload.get("intervals", []):
        if row.get("state") != "COMMON":
            continue
        ticker = str(row.get("ticker", "")).zfill(6)
        isu = str(row.get("isu_cd", "")).strip().upper()
        start = pd.Timestamp(row["effective_from"]).normalize()
        end = pd.Timestamp(row["effective_to"]).normalize()
        if start > CUTOFF or end < EVAL_START:
            continue
        if (ticker, isu) == TARGET:
            target_rows.append(row)
        common_rows.append((ticker, isu, str(row.get("market", "")).upper(), start, end))
    common_before_exclusions = [row for row in common_rows if row[:2] not in exclusion_pairs or row[:2] == TARGET]
    common_after_exclusions = [row for row in common_rows if row[:2] not in exclusion_pairs]
    eligible_tickers = sorted({row[0] for row in common_after_exclusions})

    price_cache: dict[str, dict[str, object]] = {}
    bound_rows: list[dict[str, object]] = []
    for ticker, isu, market, start, end in common_after_exclusions:
        price_path = PRICE_DIR / f"{ticker}.parquet"
        cached = price_cache.get(ticker)
        if cached is None:
            if not price_path.is_file():
                cached = {"status": "MISSING_FILE", "path": str(price_path.relative_to(ROOT)), "first_date": None, "last_date": None, "sha256": None, "read_error": None}
            else:
                try:
                    dates = pd.to_datetime(pq.read_table(price_path, columns=["date"]).column("date").to_pandas(), errors="coerce").dropna()
                    cached = {
                        "status": "READABLE" if not dates.empty else "EMPTY_DATE_COLUMN",
                        "path": str(price_path.relative_to(ROOT)),
                        "first_date": None if dates.empty else dates.min().strftime("%Y-%m-%d"),
                        "last_date": None if dates.empty else dates.max().strftime("%Y-%m-%d"),
                        "sha256": sha(price_path),
                        "read_error": None,
                    }
                except Exception as exc:  # preserve failure class; no fallback source is attempted
                    cached = {"status": "READ_ERROR", "path": str(price_path.relative_to(ROOT)), "first_date": None, "last_date": None, "sha256": None, "read_error": type(exc).__name__}
            price_cache[ticker] = cached
        scoped_start = max(start, EVAL_START)
        scoped_end = min(end, CUTOFF)
        first = cached.get("first_date")
        last = cached.get("last_date")
        intersects = bool(first and last and pd.Timestamp(first) <= scoped_end and pd.Timestamp(last) >= scoped_start)
        bound_rows.append({
            "ticker": ticker,
            "isu_cd": isu,
            "market": market,
            "pit_effective_from": start.strftime("%Y-%m-%d"),
            "pit_effective_to": end.strftime("%Y-%m-%d"),
            "p3_1_window_from": scoped_start.strftime("%Y-%m-%d"),
            "p3_1_window_to": scoped_end.strftime("%Y-%m-%d"),
            "repository_v2_bounds_status": cached["status"],
            "repository_v2_first_date": first,
            "repository_v2_last_date": last,
            "repository_v2_range_intersects_p3_1_pit": intersects,
            "repository_v2_path": cached["path"],
            "repository_v2_file_sha256": cached["sha256"],
            "read_error_class": cached["read_error"],
        })
    pd.DataFrame(bound_rows).to_csv(OUT / "identity_repository_v2_bounds.csv", index=False)

    raw_store = KrxRawStockStore(RAW_DIR)
    partition_rows: list[dict[str, object]] = []
    for day in eval_dates:
        day_text = day.strftime("%Y-%m-%d")
        for market in ("KOSPI", "KOSDAQ"):
            entry = raw_store.get_manifest(market, day_text)
            partition_rows.append({
                "market": market,
                "partition_date": day_text,
                "status": None if entry is None else entry.get("status"),
                "file_path": None if entry is None else entry.get("file_path"),
                "file_sha256": None if entry is None else entry.get("file_sha256"),
                "content_sha256": None if entry is None else entry.get("content_sha256"),
            })
    pd.DataFrame(partition_rows).to_csv(OUT / "krx_signal_date_partition_preflight.csv", index=False)
    complete_partitions = sum(row["status"] == "COMPLETE" for row in partition_rows)

    completed_months = sorted({pd.Timestamp(x).to_period("M") for x in calendar.completed_month_ends if pd.Timestamp(x) < EVAL_START})
    warmup_60 = completed_months[-60:]
    source_rows = []
    missing_references = []
    for path_text in REFERENCE_PATHS:
        path = ROOT / path_text
        exists = path.is_file()
        if not exists:
            missing_references.append(path_text)
        source_rows.append({"path": path_text, "exists": exists, "sha256": sha(path) if exists else None, "bytes": path.stat().st_size if exists else None})

    status_text = subprocess.check_output(["git", "status", "--short", "-uno"], cwd=ROOT, text=True)
    preflight = {
        "schema": "fast_core_v2_alignment_500b_p3_1_preflight_v01",
        "work_id": "FAST_CORE_V2_ALIGNMENT_500B_P3_1_OFFICIAL_REALISTIC_PORTFOLIO_V01",
        "generated_at_local": "2026-10-12 Asia/Seoul",
        "head": head,
        "origin_main": origin_main,
        "branch": branch,
        "tracked_worktree_clean": not bool(status_text.strip()),
        "source_file_hashes": source_rows,
        "missing_required_sources": missing_references,
        "dates": {
            "evaluation_start": EVAL_START.strftime("%Y-%m-%d"),
            "signal_cutoff_and_last_session": None if eval_dates.empty else eval_dates.max().strftime("%Y-%m-%d"),
            "evaluation_sessions": int(len(eval_dates)),
            "expected_evaluation_sessions": 834,
            "support_session": SUPPORT.strftime("%Y-%m-%d"),
            "support_is_next_exact_trading_session": support_is_next,
            "no_post_cutoff_signal_or_entry": True,
        },
        "universe": {
            "authority": "validated rolling merged PIT intervals; COMMON only; exact signal-date identity",
            "common_pit_interval_count_before_shared_exclusions": len(common_rows),
            "common_pit_interval_count_after_shared_exclusions": len(common_after_exclusions),
            "unique_pit_tickers_before_shared_exclusions": len({row[0] for row in common_rows}),
            "unique_pit_tickers_after_shared_exclusions": len(eligible_tickers),
            "current_permanent_exclusion_pair_count": len(exclusion_pairs),
            "permanent_exclusion_registry_canonical_sha256": canonical_sha256,
            "permanent_exclusion_hash_scheme": canonical_payload["schema"],
            "previous_p3_2_preflight_canonical_sha256": "3420a34f41ffa9029fe1869ad80a98f0096b13e74139b413e50a0ad661187f57",
            "permanent_exclusion_registry_source_sha256": sha(ROOT / "src/trend_scanner/universe/permanent_identity_exclusions.py"),
            "380440_exact_pair_present_in_registry": TARGET in exclusion_pairs,
            "380440_pit_common_overlap_rows_before_exclusion": target_rows,
            "380440_price_file_exists": (PRICE_DIR / "380440.parquet").is_file(),
            "p3_1_common_pit_tickers_before_380440_exclusion": len({row[0] for row in common_before_exclusions}),
            "p3_1_common_pit_tickers_after_380440_and_all_shared_exclusions": len(eligible_tickers),
            "survivor_filter": False,
        },
        "repository_v2_price_bounds": {
            "identity_interval_rows_checked": len(bound_rows),
            "unique_tickers_checked": len(price_cache),
            "missing_file_tickers": sorted(ticker for ticker, item in price_cache.items() if item["status"] == "MISSING_FILE"),
            "unreadable_tickers": sorted(ticker for ticker, item in price_cache.items() if item["status"] in {"READ_ERROR", "EMPTY_DATE_COLUMN"}),
            "rows_with_file_range_intersecting_p3_1_pit": sum(bool(row["repository_v2_range_intersects_p3_1_pit"]) for row in bound_rows),
            "bounds_audit_csv": "identity_repository_v2_bounds.csv",
            "scope_note": "Each exact COMMON identity interval was compared with the local ticker-file date bounds before execution. Missing/out-of-range inputs remain visible; no alternate source or date range is substituted.",
        },
        "ma60_warmup": {
            "completed_prior_month_count": len(completed_months),
            "last_60_completed_months_available": len(warmup_60) == 60,
            "first_month": None if not warmup_60 else str(warmup_60[0]),
            "last_month": None if not warmup_60 else str(warmup_60[-1]),
            "january_2022_expected_window": ["2017-01", "2021-12"],
        },
        "exact_signal_date_krx_raw_partition_preflight": {
            "markets": ["KOSPI", "KOSDAQ"],
            "partition_rows": len(partition_rows),
            "complete_partition_rows": int(complete_partitions),
            "missing_or_noncomplete_partition_rows": int(len(partition_rows) - complete_partitions),
            "all_p3_1_date_market_partitions_complete": complete_partitions == len(partition_rows),
            "partition_manifest_csv": "krx_signal_date_partition_preflight.csv",
        },
        "control_reuse": {
            "reusable": False,
            "reason": "Existing P3-1 materials are simple per-trade backtests. They do not prove the current shared 182-pair exclusion policy, P3-1 portfolio cash/NAV, cost, T+1 settlement, or valuation contract. P3-2 uses a different window. Regenerate CONTROL under the same P3-1 contract.",
            "prior_simple_p3_1_results_used_for_metrics": False,
            "p3_2_metrics_or_trade_counts_reused": False,
        },
        "external_api_calls": 0,
        "checks": {
            "head_equals_origin_main": head == origin_main,
            "branch_is_main": branch == "main",
            "p3_1_calendar_exact_834_sessions": len(eval_dates) == 834 and eval_dates.min() == EVAL_START and eval_dates.max() == CUTOFF,
            "support_is_next_exact_session": support_is_next,
            "380440_pit_and_missing_price_issue_reproduced": bool(target_rows) and not (PRICE_DIR / "380440.parquet").is_file(),
            "380440_registered_before_sample_full": TARGET in exclusion_pairs,
            "registry_pair_count_is_182": len(exclusion_pairs) == 182,
            "ma60_warmup_covers_2017_01_through_2021_12": len(warmup_60) == 60 and str(warmup_60[0]) == "2017-01" and str(warmup_60[-1]) == "2021-12",
            "all_p3_1_date_market_cap_partitions_complete": complete_partitions == len(partition_rows),
            "all_required_source_files_present": not missing_references,
        },
    }
    write_json("preflight.json", preflight)
    prior_simple_dir = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p3_1_ma60_vs_bullish_alignment_simple_backtest_v01"
    prior_simple_paths = [
        "report.md", "preflight.json", "p3_1_execution_audit.json",
        "p3_1_control_trades.csv", "p3_1_alignment_trades.csv",
    ]
    write_json("control_reuse_audit.json", {
        "schema": "fast_core_v2_alignment_500b_p3_1_control_reuse_audit_v01",
        "reusable": False,
        "decision": "REGENERATE_CONTROL_AND_CANDIDATE_UNDER_SHARED_P3_1_PORTFOLIO_CONTRACT",
        "reason_codes": [
            "PRIOR_P3_1_USED_A_FROZEN_SURVIVOR_ROSTER_INSTEAD_OF_CURRENT_ROLLING_PIT_COMMON",
            "PRIOR_EXCLUSION_REGISTRY_COUNT_DIFFERED_FROM_CURRENT_POLICY",
            "PRIOR_OUTPUT_IS_PER_TRADE_ANALYSIS_WITHOUT_THIS_RUNS_CASH_SETTLEMENT_DAILY_NAV_OR_PORTFOLIO_MDD_LEDGER",
        ],
        "prior_report_explicitly_says_no_portfolio_mdd": True,
        "prior_identity_authority": "saved P3-2 exact survivor roster applied to frozen merged COMMON PIT intervals",
        "current_identity_authority": "validated current rolling merged COMMON PIT intervals, exact active identity, shared current permanent exclusions, no survivor filter",
        "prior_exclusion_registry_count": 181,
        "current_exclusion_registry_count": len(exclusion_pairs),
        "p3_1_window_matches": True,
        "portfolio_contract_differences": [
            "No persisted daily cash, pending-sale settlement, or deterministic portfolio event ledger is proven by the prior simple trade files.",
            "No daily portfolio NAV, valuation-missing-mark audit, or portfolio MDD is provided by the prior simple backtest.",
            "The prior report states its denominator used a frozen survivor roster; this task requires rolling PIT COMMON without survivor filtering.",
            "The current permanent exact-pair exclusion policy includes the additional P3-1-confirmed 380440 identity.",
        ],
        "prior_artifact_hashes": [
            {"path": f"artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p3_1_ma60_vs_bullish_alignment_simple_backtest_v01/{name}",
             "sha256": sha(prior_simple_dir / name)}
            for name in prior_simple_paths
        ],
        "prior_trade_files_used_as_p3_1_metrics": False,
        "p3_2_metrics_or_trades_reused": False,
    })
    source_manifest = {
        "schema": "fast_core_v2_alignment_500b_p3_1_source_manifest_v01",
        "work_id": preflight["work_id"],
        "baseline_head": head,
        "baseline_origin_main": origin_main,
        "plan_sha256": sha(OUT / "plan.md"),
        "execution_contract_sha256": sha(OUT / "execution_contract.json"),
        "preflight_source_paths": source_rows,
        "authority_files": [
            {"path": path, "sha256": sha(ROOT / path)}
            for path in (
                "data/market/rolling_authority/manifest.json",
                "data/market/rolling_authority/merged_pit_intervals.json",
                "data/market/rolling_authority/merged_trading_calendar.json",
                "data/market/raw/krx_stocks/v01/manifest.sqlite3",
            )
        ],
        "p3_1_identity_price_bounds_csv": "identity_repository_v2_bounds.csv",
        "p3_1_krx_partition_preflight_csv": "krx_signal_date_partition_preflight.csv",
        "p3_2_references_are_read_only": True,
    }
    write_json("source_manifest.json", source_manifest)
    print(json.dumps({
        "head": head,
        "origin_main": origin_main,
        "evaluation_sessions": len(eval_dates),
        "eligible_pit_tickers": len(eligible_tickers),
        "permanent_exclusion_count": len(exclusion_pairs),
        "permanent_exclusion_pair_hash": canonical_sha256,
        "price_missing_tickers": len(preflight["repository_v2_price_bounds"]["missing_file_tickers"]),
        "krx_partitions_complete": complete_partitions,
        "krx_partitions_total": len(partition_rows),
        "checks": preflight["checks"],
    }, ensure_ascii=False, indent=2), flush=True)
    return 0 if all(preflight["checks"].values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
