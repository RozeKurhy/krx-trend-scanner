#!/usr/bin/env python3
"""Fresh, offline P3-1 trade-level replay using exact permanent identity exclusions."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import math
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[6]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from trend_scanner.universe.permanent_identity_exclusions import PERMANENT_IDENTITY_EXCLUSIONS

OUT = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_simple_backtest_universe_mcap_contract_fix_v01/p3_1"
BASE_RUNNER_PATH = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p2_2_ma60_vs_bullish_alignment_simple_backtest_v01/run_p2_2_simple_backtest.py"
spec = importlib.util.spec_from_file_location("p3_1_certified_simple_runner_utilities", BASE_RUNNER_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("P2_2_RUNNER_IMPORT_FAILED")
p2 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = p2
spec.loader.exec_module(p2)

WORK_ID = "FAST_CORE_V2_SIMPLE_BACKTEST_UNIVERSE_MCAP_CONTRACT_FIX_V01_P3_1"
FINAL_TOKEN = "FAST_CORE_V2_SIMPLE_BACKTEST_UNIVERSE_MCAP_CONTRACT_FIX_V01_PASS"
CHECK_TOKEN = "FAST_CORE_V2_SIMPLE_BACKTEST_UNIVERSE_MCAP_CONTRACT_FIX_V01_CHECK_REQUIRED"
WINDOW_ID = "P3-1"
WINDOW = {"effective_start": "2022-01-03", "effective_end": "2025-05-30", "execution_support": "2025-06-02"}
WORKERS = 10
STRATEGIES = {
    "CONTROL": ("PATTERN_A_FAST_FINAL_STRATEGY_V02", "p3_1_control_trades.csv"),
    "MA60": ("PATTERN_A_FAST_FINAL_STRATEGY_V02_MA60_ENTRY_FILTER", "p3_1_ma60_trades.csv"),
    "ALIGNMENT": ("PATTERN_A_FAST_FINAL_STRATEGY_V02_MONTHLY_MA20_MA60_BULLISH_ALIGNMENT", "p3_1_alignment_trades.csv"),
}
STAGE = "STARTUP"
REPLAY_STARTED = False
EXPECTED_TRACKED_WORKTREE_CHANGES = {
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_ma60_vs_bullish_alignment_5window_simple_backtest_v01/run_5window_simple_backtest.py",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_lifecycle_prefix_invariance_fix_v01/p3_1/run_p3_1_lifecycle_prefix_invariance_fix_v01.py",
}
TARGETED_TEST_PATH = "tests/test_fastcore_simple_backtest_universe_contract_v01.py"

# Reuse only the certified P2-2 runner's deterministic ledger validation and
# metric functions. No prior-period performance files are opened or compared.
p2.OUT = OUT
p2.WORK_ID = WORK_ID
p2.FINAL_TOKEN = FINAL_TOKEN
p2.CHECK_TOKEN = CHECK_TOKEN
p2.WINDOW_ID = WINDOW_ID
p2.WINDOW = WINDOW
p2.WORKERS = WORKERS
p2.STRATEGIES = STRATEGIES


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RuntimeError(code)


def sha256(path: Path) -> str:
    return p2.sha256(path)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def git_clean_tracked() -> bool:
    return all(
        subprocess.run(["git", *args], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        for args in (("diff", "--quiet"), ("diff", "--cached", "--quiet"))
    )


def json_value(value: Any) -> Any:
    return p2.json_value(value)


def write_json(path: Path, payload: Any) -> None:
    p2.write_json(path, payload)


def write_frame(path: Path, frame: pd.DataFrame) -> None:
    p2.write_frame(path, frame)


def load_shared():
    return p2.load_shared()


def source_hashes_for(module: Any, tracked_changes: set[str]) -> dict[str, Any]:
    hashes = {}
    source_paths = p2.source_paths(module)
    source_paths.pop("exact_mcap_gate", None)
    source_paths.pop("survivor_identity_roster_authority", None)
    for name, path in source_paths.items():
        require(path.is_file(), f"INPUT_MISSING:{name}:{path}")
        relative = path.relative_to(ROOT).as_posix()
        digest = sha256(path)
        committed = subprocess.run(
            ["git", "show", f"HEAD:{relative}"], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        require(committed.returncode == 0, f"INPUT_NOT_TRACKED_AT_START:{name}")
        head_digest = hashlib.sha256(committed.stdout).hexdigest()
        require(
            (relative in tracked_changes) or committed.stdout == path.read_bytes(),
            f"INPUT_HASH_DIFFERS_FROM_HEAD:{name}",
        )
        hashes[name] = {
            "path": relative,
            "sha256": digest,
            "head_sha256": head_digest,
            "working_tree_modified": relative in tracked_changes,
        }
    for name, path in (
        ("certified_p2_2_runner_utilities", BASE_RUNNER_PATH),
        ("p3_1_execution_script", Path(__file__)),
    ):
        require(path.is_file(), f"INPUT_MISSING:{name}")
        hashes[name] = {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": sha256(path),
            "tracked_at_start": True,
            "head_sha256": hashlib.sha256(
                subprocess.check_output(["git", "show", f"HEAD:{path.relative_to(ROOT).as_posix()}"], cwd=ROOT)
            ).hexdigest(),
            "working_tree_modified": path.relative_to(ROOT).as_posix() in tracked_changes,
        }
    test_path = ROOT / TARGETED_TEST_PATH
    require(test_path.is_file(), "TARGETED_REGRESSION_TEST_MISSING")
    hashes["targeted_regression_test"] = {
        "path": TARGETED_TEST_PATH,
        "sha256": sha256(test_path),
        "tracked_at_start": False,
    }
    return hashes


def preflight(module: Any):
    OUT.mkdir(parents=True, exist_ok=True)
    unexpected = sorted(item.name for item in OUT.iterdir())
    require(not unexpected, "REFUSING_TO_OVERWRITE_EXISTING_OUTPUTS:" + ",".join(unexpected))
    require(git("branch", "--show-current") == "main", "EXPECTED_MAIN_BRANCH")
    head, origin = git("rev-parse", "HEAD"), git("rev-parse", "origin/main")
    require(head == origin, "START_HEAD_NOT_ORIGIN_MAIN")
    require(git("rev-list", "--left-right", "--count", "origin/main...HEAD") == "0\t0", "START_AHEAD_BEHIND_NOT_ZERO")
    tracked_changes = sorted(set(git("diff", "--name-only").splitlines()) | set(git("diff", "--cached", "--name-only").splitlines()))
    require(set(tracked_changes) == EXPECTED_TRACKED_WORKTREE_CHANGES, "UNEXPECTED_TRACKED_WORKTREE_CHANGES")
    require((ROOT / TARGETED_TEST_PATH).is_file(), "TARGETED_REGRESSION_TEST_MISSING")

    input_hashes = source_hashes_for(module, set(tracked_changes))
    pit_dir = ROOT / "artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/p2_2_identity_authority_extension_v01"
    survivor_path = ROOT / "artifacts/backtests/p3_2_neg40_weak_protect_v01/run_20260926_realistic_mcap1t_worker10_v01/survivor_universe_audit.csv"
    manifest_path = pit_dir / "p2_2_identity_authority_extension_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(manifest.get("status") == "PASS", "FROZEN_AUTHORITY_MANIFEST_NOT_PASS")
    require(sha256(pit_dir / "merged_trading_calendar.json") == manifest.get("merged_calendar_file_sha256"), "FROZEN_CALENDAR_HASH_MISMATCH")

    raw_registry_count = len(PERMANENT_IDENTITY_EXCLUSIONS)
    policy_by_identity = {
        (str(ticker).zfill(6), str(isu_cd).strip().upper()): metadata
        for (ticker, isu_cd), metadata in PERMANENT_IDENTITY_EXCLUSIONS.items()
    }
    require(raw_registry_count == 181, "CURRENT_PERMANENT_EXCLUSION_COUNT_MISMATCH")
    require(len(policy_by_identity) == raw_registry_count, "PERMANENT_EXCLUSION_IDENTITY_COLLISION")
    policy_pairs = set(policy_by_identity)

    prior_provenance_path = Path(__file__).resolve().parent / "p3_1_provenance.json"
    prior_provenance = json.loads(prior_provenance_path.read_text(encoding="utf-8"))
    expected_survivor_hash = prior_provenance.get("authority", {}).get("survivor_identity_roster_sha256")
    require(expected_survivor_hash is not None, "PRIOR_SURVIVOR_HASH_REFERENCE_MISSING")
    require(sha256(survivor_path) == expected_survivor_hash, "CURRENT_SURVIVOR_COMPARISON_SOURCE_HASH_MISMATCH")
    previous_source_hashes = prior_provenance.get("source_hashes", {})
    unchanged_rule_sources = ("core_strategy_runner", "canonical_strategy", "ma60_helper", "alignment_helper")
    for name in unchanged_rule_sources:
        require(name in input_hashes and name in previous_source_hashes, f"PRIOR_RULE_SOURCE_HASH_MISSING:{name}")
        require(
            input_hashes[name]["sha256"] == previous_source_hashes[name].get("sha256"),
            f"STRATEGY_OR_LIFECYCLE_RULE_SOURCE_CHANGED:{name}",
        )

    prior_metrics_path = Path(__file__).resolve().parent / "p3_1_strategy_metrics.csv"
    prior_metrics = pd.read_csv(prior_metrics_path)
    prior_trade_counts = {
        str(row["strategy"]): int(row["trade_count"])
        for row in prior_metrics.to_dict("records")
    }
    require(prior_trade_counts == {"CONTROL": 247, "MA60": 207, "ALIGNMENT": 119}, "PRIOR_UNAUTHORIZED_RESULT_COUNTS_MISMATCH")
    input_hashes["prior_p3_1_metrics_comparison_only"] = {
        "path": prior_metrics_path.relative_to(ROOT).as_posix(),
        "sha256": sha256(prior_metrics_path),
        "used_for_replay": False,
    }

    network = module.network_guard()
    try:
        frozen, base_run, _base_gate, _universe, authority, historical_context_keys = module.load_historical_frozen_context()
        require(base_run.entry_signal_gate is None, "BASE_CONTEXT_HAS_MARKET_CAP_GATE")
        common_rows = module.historical_common_rows(
            base_run.authority.pit_intervals,
            WINDOW["effective_start"],
            WINDOW["effective_end"],
        )
        common_keys = {(row["ticker"], row["isu_cd"], row["market"]) for row in common_rows}
        require(set(historical_context_keys) == common_keys, "HISTORICAL_CONTEXT_IDENTITY_SET_MISMATCH")
        eligible_rows = module.apply_exact_permanent_exclusions(common_rows, frozenset(policy_pairs))
        eligible = frozenset((row["ticker"], row["isu_cd"], row["market"]) for row in eligible_rows)
        require(not any((ticker, isu_cd) in policy_pairs for ticker, isu_cd, _market in eligible), "PERMANENT_EXCLUSION_FILTER_LEAK")
        run, scoped_gate, context = module.context_for_window(base_run, None, frozenset(), WINDOW_ID)
        require(context["effective_start"] == WINDOW["effective_start"], "P3_1_START_MISMATCH")
        require(context["effective_end"] == WINDOW["effective_end"], "P3_1_CUTOFF_MISMATCH")
        require(context["execution_support"] == WINDOW["execution_support"], "P3_1_SUPPORT_MISMATCH")
        require(scoped_gate is None and run.entry_signal_gate is None, "P3_1_MARKET_CAP_GATE_INJECTED")
        require(context["historical_common_identity_key_count"] == len(common_keys), "P3_1_HISTORICAL_COMMON_COUNT_MISMATCH")
        require(context["eligible_historical_identity_key_count"] == len(eligible), "P3_1_ELIGIBLE_HISTORICAL_COUNT_MISMATCH")
        require(context["market_cap_filter"] == "NONE" and context["market_cap_based_reject_count"] == 0, "P3_1_MARKET_CAP_FILTER_NOT_NONE")
        require(context["current_survivor_membership_used"] is False, "P3_1_CURRENT_SURVIVOR_MEMBERSHIP_USED")
        require(context["common_pit_segment_count"] == sum(map(len, run.segments_by_ticker.values())), "P3_1_SEGMENT_CONTEXT_MISMATCH")
        scoped_keys = {
            (segment.ticker, segment.isu_cd.strip().upper(), segment.market.strip().upper())
            for rows in run.segments_by_ticker.values()
            for segment in rows
        }
        require(scoped_keys == set(eligible), "P3_1_CORRECTED_UNIVERSE_CONTEXT_MISMATCH")
        require(not any((segment.ticker, segment.isu_cd.strip().upper()) in policy_pairs
                        for rows in run.segments_by_ticker.values() for segment in rows), "P3_1_WINDOW_PERMANENT_EXCLUSION_LEAK")
        require(len(common_keys) == 2626, "P3_1_HISTORICAL_COMMON_IDENTITY_KEY_COUNT_MISMATCH")
        require(len(eligible) == 2467, "P3_1_ELIGIBLE_HISTORICAL_IDENTITY_KEY_COUNT_MISMATCH")
        require(network[2]["calls"] == 0, "NETWORK_CALLS_DURING_PREFLIGHT")
    finally:
        module.restore_network_guard(network)

    survivor_universe = pd.read_csv(survivor_path, dtype={"ticker": str, "isu_cd": str, "market": str})
    survivor_rows = survivor_universe.loc[survivor_universe["status"].astype(str).eq("SURVIVOR_COMMON_IDENTITY")]
    current_survivor_keys = {
        (str(row.ticker).zfill(6), str(row.isu_cd).strip().upper(), str(row.market).strip().upper())
        for row in survivor_rows.itertuples(index=False)
    }
    require(len(current_survivor_keys) == 2539, "CURRENT_SURVIVOR_COMPARISON_COUNT_MISMATCH")
    current_survivor_omitted = set(eligible) - current_survivor_keys
    legacy_filtered = set(eligible) & current_survivor_keys
    require(len(current_survivor_omitted) == 131, "CURRENT_SURVIVOR_OMISSION_SET_DIFFERENCE_MISMATCH")
    require(len(legacy_filtered) == 2336, "LEGACY_CURRENT_SURVIVOR_FILTER_COUNT_MISMATCH")

    rows_by_key: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in common_rows:
        key = (row["ticker"], row["isu_cd"], row["market"])
        rows_by_key.setdefault(key, []).append(row)
    identity_audit = pd.DataFrame([
        {
            "ticker": ticker,
            "isu_cd": isu_cd,
            "market": market,
            "historical_common_segment_count": len(rows_by_key[(ticker, isu_cd, market)]),
            "historical_effective_from": ";".join(sorted(row["effective_from"].strftime("%Y-%m-%d") for row in rows_by_key[(ticker, isu_cd, market)])),
            "historical_effective_to": ";".join(sorted(row["effective_to"].strftime("%Y-%m-%d") for row in rows_by_key[(ticker, isu_cd, market)])),
            "current_permanent_exclusion_exact_pair": (ticker, isu_cd) in policy_pairs,
            "current_survivor_projection_member_compare_only": (ticker, isu_cd, market) in current_survivor_keys,
            "would_be_omitted_by_legacy_current_survivor_filter": (ticker, isu_cd, market) in current_survivor_omitted,
            "excluded_by_current_survivor_in_corrected_run": False,
            "included_in_corrected_p3_1": (ticker, isu_cd, market) in eligible,
            "permanent_exclusion_failure_class": policy_by_identity.get((ticker, isu_cd), {}).get("failure_class"),
            "permanent_exclusion_approval_scope": policy_by_identity.get((ticker, isu_cd), {}).get("approval_scope"),
            "permanent_exclusion_approved_date": policy_by_identity.get((ticker, isu_cd), {}).get("approved_date"),
            "permanent_exclusion_reason": policy_by_identity.get((ticker, isu_cd), {}).get("reason"),
        }
        for ticker, isu_cd, market in sorted(common_keys)
    ])
    require(len(identity_audit) == len(common_keys), "IDENTITY_AUTHORITY_AUDIT_ROW_COUNT_MISMATCH")
    identity_keys = set(eligible)
    require(int(identity_audit["included_in_corrected_p3_1"].sum()) == len(identity_keys), "IDENTITY_AUTHORITY_AUDIT_CONTEXT_COUNT_MISMATCH")
    require(int(identity_audit["would_be_omitted_by_legacy_current_survivor_filter"].sum()) == len(current_survivor_omitted), "CURRENT_SURVIVOR_OMISSION_AUDIT_MISMATCH")

    input_hashes["historical_pit_authority"] = {
        "path": base_run.authority.pit_path.relative_to(ROOT).as_posix(),
        "sha256": sha256(base_run.authority.pit_path),
    }
    input_hashes["frozen_calendar_authority"] = {
        "path": (pit_dir / "merged_trading_calendar.json").relative_to(ROOT).as_posix(),
        "sha256": sha256(pit_dir / "merged_trading_calendar.json"),
    }
    input_hashes["frozen_authority_manifest"] = {
        "path": manifest_path.relative_to(ROOT).as_posix(),
        "sha256": sha256(manifest_path),
    }
    input_hashes["current_survivor_comparison_only"] = {
        "path": survivor_path.relative_to(ROOT).as_posix(),
        "sha256": sha256(survivor_path),
        "used_for_eligibility": False,
    }

    pre = {
        "status": "PASS",
        "work_id": WORK_ID,
        "window_id": WINDOW_ID,
        "branch": "main",
        "start_head": head,
        "start_origin_main": origin,
        "head_equals_origin_main": True,
        "ahead_behind": "0\t0",
        "tracked_changes_at_preflight": tracked_changes,
        "initial_baseline_tracked_worktree_clean": True,
        "targeted_regression_test_path": TARGETED_TEST_PATH,
        **context,
        "workers": WORKERS,
        "strategy_ids": {name: values[0] for name, values in STRATEGIES.items()},
        "historical_common_identity_key_count": len(common_keys),
        "eligible_historical_identity_key_count": len(eligible),
        "historical_common_segment_count": len(common_rows),
        "permanent_exclusion_removed_historical_identity_key_count": len(common_keys) - len(eligible),
        "permanent_exclusion_registry_count": raw_registry_count,
        "permanent_exclusion_duplicate_exact_pair_count": raw_registry_count - len(policy_by_identity),
        "permanent_exclusion_ticker_only_matching_used": False,
        "current_survivor_projection_count_compare_only": len(current_survivor_keys),
        "current_survivor_projection_sha256_compare_only": sha256(survivor_path),
        "current_survivor_omitted_historical_identity_key_count_compare_only": len(current_survivor_omitted),
        "legacy_current_survivor_filtered_identity_key_count": len(legacy_filtered),
        "current_survivor_based_exclusion_count_in_corrected_run": 0,
        "market_cap_filter": "NONE",
        "market_cap_gate_injected": False,
        "market_cap_based_reject_count": 0,
        "eligible_historical_identity_key_count": len(eligible),
        "p3_1_window_pit_identity_key_count": len(identity_keys),
        "p3_1_window_pit_segment_count": context["common_pit_segment_count"],
        "p3_1_unique_ticker_count": context["unique_ticker_count"],
        "permanent_exclusions_applied_before_strategy_replay_by_exact_ticker_isu": True,
        "eligible_permanent_exclusion_residue_count": 0,
        "frozen_authority": json_value(authority),
        "frozen_manifest_sha256": sha256(manifest_path),
        "frozen_pit_sha256": sha256(base_run.authority.pit_path),
        "frozen_calendar_sha256": sha256(pit_dir / "merged_trading_calendar.json"),
        "input_source_hashes": input_hashes,
        "price_source": "Local Repository V2 adjusted/raw stores; MA inputs from hash-verified adjusted stock partitions",
        "market_cap_source": "Not read for simple-backtest entry eligibility; MARKET_CAP_FILTER=NONE",
        "cost_contract": {
            "buy_commission_rate": module.COMM_RATE,
            "sell_commission_rate": module.COMM_RATE,
            "buy_slippage_rate": module.SLIP_RATE,
            "sell_slippage_rate": module.SLIP_RATE,
            "transaction_tax_in_returns": False,
        },
        "result_reuse": {
            "prior_performance_results_used_for_replay": False,
            "prior_p3_1_performance_metrics_read_for_comparison_only": True,
            "p1_results": False,
            "p2_1_results": False,
            "p2_2_results": False,
            "p3_2_results": False,
            "frozen_pit_calendar_reused_as_authority": True,
            "current_survivor_roster_used_for_eligibility": False,
            "current_survivor_roster_used_for_comparison_only": True,
        },
        "previous_result_classification": "UNAUTHORIZED_MCAP1T_AND_CURRENT_SURVIVOR_FILTERED_RESULT",
        "previous_result_metrics_path": (Path(__file__).resolve().parent / "p3_1_strategy_metrics.csv").relative_to(ROOT).as_posix(),
        "previous_result_metrics_sha256": sha256(Path(__file__).resolve().parent / "p3_1_strategy_metrics.csv"),
        "previous_result_trade_counts": prior_trade_counts,
        "lifecycle_and_candidate_rule_sources_unchanged_vs_previous_result": True,
        "unchanged_rule_source_names": list(unchanged_rule_sources),
        "network_calls": 0,
    }
    return pre, frozen, base_run, None, frozenset(eligible), identity_audit

def pair_leak_count(frame: pd.DataFrame, pairs: set[tuple[str, str]], ticker_col: str, isu_col: str) -> int:
    require({ticker_col, isu_col}.issubset(frame.columns), f"EXCLUSION_AUDIT_IDENTITY_COLUMNS_MISSING:{ticker_col}:{isu_col}")
    values = zip(frame[ticker_col].astype(str).str.zfill(6), frame[isu_col].astype(str).str.strip().str.upper())
    return sum((ticker, isu_cd) in pairs for ticker, isu_cd in values)


def markdown_report(metrics: pd.DataFrame, deltas: pd.DataFrame, exits: pd.DataFrame,
                    checks: dict[str, Any], pre: dict[str, Any], thresholds: pd.DataFrame,
                    previous_comparison: pd.DataFrame) -> str:
    def f(value: Any, digits: int = 2) -> str:
        return "—" if value is None or pd.isna(value) else f"{float(value):.{digits}f}"
    lines = [
        "# FAST Core V2 P3-1 단순 백테스트 universe / 시총 계약 수정",
        "",
        "| 레벨 | 개수 | 내용 |",
        "|---|---:|---|",
        "| CRITICAL | 0 | 필수 무결성 검증 오류 없음 |",
        "| MAJOR | 0 | 결과 범위 안에서 확인된 중대 이슈 없음 |",
        "| MINOR | 0 | simple trade-level 범위 밖인 포트폴리오 MDD는 미평가 항목으로 분류하지 않음 |",
        "",
        f"- 최종 판정: {FINAL_TOKEN}",
        "- 실제 거래 기간: 2022-01-03~2025-05-30. Execution support: 2025-06-02. Cutoff 이후 신규 진입은 허용하지 않았어.",
        "- 수정 전 계약은 승인되지 않은 MKTCAP ≥ 1조 진입 게이트와 2026-09-21 current survivor 교집합을 historical P3-1 eligibility에 적용했어. 이전 결과는 `UNAUTHORIZED_MCAP1T_AND_CURRENT_SURVIVOR_FILTERED_RESULT`로 분류했어.",
        f"- 수정 후 계약은 `MARKET_CAP_FILTER=NONE`이야. Frozen historical PIT의 P3-1 COMMON {pre['historical_common_identity_key_count']:,} identity key에서 current permanent exclusion registry의 exact (ticker, ISU) {pre['permanent_exclusion_registry_count']}쌍만 적용해 {pre['eligible_historical_identity_key_count']:,} key를 만들었어.",
        f"- Current survivor roster 때문에 과거에 제외됐을 non-permanent identity는 set difference로 {pre['current_survivor_omitted_historical_identity_key_count_compare_only']:,}개야. 수정 run의 survivor 기반 제외는 {checks['current_survivor_based_exclusion_count']}개야.",
        f"- 공통 universe는 identity key {pre['p3_1_window_pit_identity_key_count']:,}개, COMMON segment {pre['p3_1_window_pit_segment_count']:,}개, ticker {pre['p3_1_unique_ticker_count']:,}개야. 제외 키에 market과 ticker-only matching을 사용하지 않았어.",
        "- CONTROL, MA60 fail-closed, Bullish Alignment는 같은 corrected historical universe, PIT, calendar, lifecycle, cutoff, Repository V2 가격 및 비용 계약을 사용했어.",
        "- 매수/매도 수수료 각 0.015%, 매수/매도 슬리피지 각 0.10%, 거래세 제외. 수익률은 net 기준이야.",
        "",
        "## 전략별 핵심 지표",
        "",
        "| 전략 | 거래 | 실현 | cutoff 미종료 | 미종료율 % | 실현 승률 % | terminal 양수율 % | terminal 평균 % | terminal 중앙 % | realized 평균 % | realized 중앙 % | 보유 평균 일 | 보유 중앙 일 | 최대 수익 % | 최대 손실 % | Loss Guard 건수/율 | PROGRESSED 건수/율 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in metrics.to_dict("records"):
        lines.append(
            f"| {row['strategy']} | {row['trade_count']} | {row['realized_count']} | {row['open_at_cutoff_count']} | {f(row['open_at_cutoff_rate_pct'])} | "
            f"{f(row['realized_win_rate_pct'])} | {f(row['terminal_positive_rate_pct'])} | {f(row['average_terminal_return_pct'])} | {f(row['median_terminal_return_pct'])} | "
            f"{f(row['average_realized_return_pct'])} | {f(row['median_realized_return_pct'])} | {f(row['average_holding_days'])} | {f(row['median_holding_days'])} | "
            f"{f(row['max_terminal_return_pct'])} | {f(row['min_terminal_return_pct'])} | {row['loss_guard_exit_count']} ({f(row['loss_guard_rate_pct'])}%) | "
            f"{row['progressed_count']} ({f(row['progressed_rate_pct'])}%) |"
        )
    lines += ["", "## 대형 승리·손실 분포", "", "| 전략 | 구간 | 건수 | 전체 거래 대비 % |", "|---|---|---:|---:|"]
    for row in thresholds.to_dict("records"):
        lines.append(f"| {row['strategy']} | {row['threshold']} | {row['count']} | {f(row['rate_pct_of_all_trades'])} |")
    lines += [
        "", "## CONTROL 대비 변화", "",
        "| 후보 | 거래수 Δ | 거래 감소 % | 승률 Δ %p | terminal 양수율 Δ %p | terminal 평균/중앙 Δ %p | realized 평균/중앙 Δ %p | 보유 평균/중앙 Δ 일 | +20/+50/+100% 비율 Δ %p | -10/-15/-20/-30% 비율 Δ %p | Loss Guard 건수/율 Δ | PROGRESSED 건수/율 Δ | cutoff-open 건수/율 Δ |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in deltas.to_dict("records"):
        winners = "/".join(f(row[f"terminal_ge_{n}_rate_delta_pp"]) for n in (20, 50, 100))
        losers = "/".join(f(row[f"terminal_le_neg_{n}_rate_delta_pp"]) for n in (10, 15, 20, 30))
        lines.append(
            f"| {row['candidate']} | {row['trade_count_delta']} | {f(row['trade_count_reduction_pct'])} | {f(row['realized_win_rate_delta_pp'])} | "
            f"{f(row['terminal_positive_rate_delta_pp'])} | {f(row['average_terminal_delta_pp'])}/{f(row['median_terminal_delta_pp'])} | "
            f"{f(row['average_realized_delta_pp'])}/{f(row['median_realized_delta_pp'])} | {f(row['average_holding_days_delta'])}/{f(row['median_holding_days_delta'])} | "
            f"{winners} | {losers} | {row['loss_guard_count_delta']} / {f(row['loss_guard_rate_delta_pp'])}%p | "
            f"{row['progressed_count_delta']} / {f(row['progressed_rate_delta_pp'])}%p | "
            f"{row['cutoff_open_count_delta']} / {f(row['cutoff_open_rate_delta_pp'])}%p |"
        )
    lines += [
        "", "## 이전 오염 결과와 비교", "",
        "이전 성과 파일은 replay 입력에 사용하지 않았어. 아래 비교표만 만들기 위해 읽었고, 이전 결과는 official simple baseline으로 쓰지 않아.",
        "",
        "| 전략 | 이전 거래 | 수정 거래 | 거래 Δ | 이전 terminal 평균 % | 수정 terminal 평균 % | 평균 Δ %p | 이전 terminal 중앙 % | 수정 terminal 중앙 % | 중앙 Δ %p | 승률 Δ %p | 평균 보유기간 Δ 일 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in previous_comparison.to_dict("records"):
        lines.append(
            f"| {row['strategy']} | {row['previous_trade_count']} | {row['corrected_trade_count']} | {row['trade_count_delta']} | "
            f"{f(row['previous_average_terminal_return_pct'])} | {f(row['corrected_average_terminal_return_pct'])} | {f(row['average_terminal_return_delta_pp'])} | "
            f"{f(row['previous_median_terminal_return_pct'])} | {f(row['corrected_median_terminal_return_pct'])} | {f(row['median_terminal_return_delta_pp'])} | "
            f"{f(row['realized_win_rate_delta_pp'])} | {f(row['average_holding_days_delta'])} |"
        )
    lines += ["", "## Exit reason 분포", "", "| 전략 | exit reason | 건수 |", "|---|---|---:|"]
    for row in exits.to_dict("records"):
        lines.append(f"| {row['strategy']} | {row['exit_type']} | {row['count']} |")
    lines += [
        "",
        "## PROGRESSED 판정",
        "",
        "PROGRESSED는 raw 날짜 존재만으로 세지 않았어. 실현 거래는 entry execution부터 exit signal까지, cutoff 미종료 거래는 entry execution부터 cutoff까지, lifecycle 정산은 settlement date까지 대조했어. Trade별 근거는 p3_1_progressed_reconciliation_audit.csv에 있어.",
        "",
        "## 실행·무결성·provenance",
        "",
        f"- 전략별 worker는 {WORKERS}개, worker 오류 합계 {checks['worker_error_count']}건, 네트워크 호출 {checks['network_calls']}회.",
        f"- 전략별 처리 ticker {pre['p3_1_unique_ticker_count']:,}개; 공통 PIT identity key {pre['p3_1_window_pit_identity_key_count']:,}개.",
        f"- Accepted signal↔trade parity {checks['candidate_signal_parity']}; duplicate trade key {checks['duplicate_trade_key_count']}; cutoff 이후 신규 진입 {checks['post_cutoff_entry_count']}.",
        f"- 시총 진입 필터 적용 {checks['market_cap_filter_applied']}; 시총 기반 reject {checks['market_cap_based_reject_count']}; current survivor 기반 제외 {checks['current_survivor_based_exclusion_count']}.",
        f"- Permanent exclusion leakage: trade {checks['permanent_exclusion_trade_leakage_count']}, signal audit {checks['permanent_exclusion_signal_audit_leakage_count']}. 등록 exact pair {pre['permanent_exclusion_registry_count']}, 중복 pair {pre['permanent_exclusion_duplicate_exact_pair_count']}, residue {pre['eligible_permanent_exclusion_residue_count']}.",
        f"- MA60 공식·fail-closed {checks['ma60_filter_check']}; Alignment signal_day_close > MA20 > MA60·fail-closed {checks['alignment_filter_check']}; net terminal 재계산 불일치 {checks['net_terminal_recompute_mismatch_count']}.",
        f"- MA60/Alignment 공식과 lifecycle causal fix source hash가 이전 결과와 같아: {pre['lifecycle_and_candidate_rule_sources_unchanged_vs_previous_result']} ({', '.join(pre['unchanged_rule_source_names'])}).",
        f"- Frozen PIT SHA-256 {pre['frozen_pit_sha256']}; calendar {pre['frozen_calendar_sha256']}; exclusion registry {pre['input_source_hashes']['permanent_identity_exclusion_registry']['sha256']}.",
        f"- Current survivor 비교 전용 SHA-256 {pre['current_survivor_projection_sha256_compare_only']}; 이전 metrics 비교 전용 SHA-256 {pre['previous_result_metrics_sha256']}.",
        "- 이 문서는 P3-1 단일 기간 simple trade-level 결과야. P2-1/P2-2/P3-2/P1/5-window synthesis는 실행하지 않았어. 포트폴리오 MDD와 공식 채택 판정은 포함하지 않아.",
        "",
        "## 산출물",
        "",
        f"- {OUT.relative_to(ROOT).as_posix()}/에 preflight, identity authority audit, 세 trade ledger, signal/no-cap contract/price audit, execution audit, PROGRESSED reconciliation, metrics, CONTROL delta, previous-result comparison, provenance, artifact manifest가 있어.",
        f"- 결과 토큰: {FINAL_TOKEN}",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    global STAGE, REPLAY_STARTED
    started = time.perf_counter()
    module = None
    network_calls = 0
    try:
        STAGE = "PREFLIGHT"
        module = load_shared()
        pre, frozen, base_run, base_gate, eligible, identity_audit = preflight(module)
        if "--preflight-only" in sys.argv:
            print(json.dumps({
                "status": "PASS",
                "work_id": WORK_ID,
                "window_id": WINDOW_ID,
                "eligible_historical_identity_key_count": pre["eligible_historical_identity_key_count"],
                "window_identity_key_count": pre["p3_1_window_pit_identity_key_count"],
                "window_segment_count": pre["p3_1_window_pit_segment_count"],
                "unique_ticker_count": pre["p3_1_unique_ticker_count"],
                "network_calls": 0,
                "replay_started": False,
            }, ensure_ascii=False, indent=2))
            return 0

        write_frame(OUT / "identity_authority_audit.csv", identity_audit)
        write_json(OUT / "preflight.json", pre)
        prices = module.HELPER.PriceCache()
        metrics_raw: list[dict[str, Any]] = []
        STAGE = "P3_1_FULL_REPLAY"
        REPLAY_STARTED = True
        net = module.network_guard()
        try:
            execution = module.run_full_window(WINDOW_ID, base_run, base_gate, eligible, prices, metrics_raw)
            network_calls = int(net[2]["calls"])
        finally:
            module.restore_network_guard(net)
        require(network_calls == 0, "NETWORK_CALLS_DURING_REPLAY")
        require(execution["window_id"] == WINDOW_ID, "EXECUTION_WINDOW_ID_MISMATCH")
        require(execution["worker_count"] == WORKERS, "EXECUTION_WORKER_COUNT_MISMATCH")
        require(execution["worker_errors"] == [], "EXECUTION_WORKER_ERRORS")
        require(len(metrics_raw) == 3 and {row["strategy"] for row in metrics_raw} == set(STRATEGIES), "P3_1_METRICS_INCOMPLETE")
        for name, result in execution["execution"].items():
            require(result.get("worker_count") == WORKERS, f"{name}_WORKER_COUNT_MISMATCH")
            require(result.get("worker_errors") == [], f"{name}_WORKER_ERRORS")
            require(result.get("ticker_count") == pre["p3_1_unique_ticker_count"], f"{name}_PROCESSED_TICKER_COUNT_MISMATCH")

        STAGE = "RESULT_INTEGRITY"
        cutoff = pd.Timestamp(WINDOW["effective_end"])
        metrics, ledgers, progression_frames = [], {}, []
        audit_checks = {}
        trade_hashes = []
        for name, (_strategy_id, filename) in STRATEGIES.items():
            path = OUT / filename
            metric, ledger, progressed = p2.validate_ledger(name, path, module, cutoff)
            metrics.append(metric)
            ledgers[name] = ledger
            if len(progressed):
                progression_frames.append(progressed)
            trade_hashes.append({"strategy": name, "trade_file": filename, "sha256": sha256(path)})
            if name != "CONTROL":
                audit_checks[name] = p2.candidate_audit_check(
                    name, OUT / f"p3_1_{name.lower()}_signal_audit.csv", ledger
                )

        policy_pairs = {
            (str(ticker).zfill(6), str(isu_cd).strip().upper())
            for ticker, isu_cd in PERMANENT_IDENTITY_EXCLUSIONS
        }
        trade_leaks = {
            name: pair_leak_count(frame, policy_pairs, "ticker", "isu_cd")
            for name, frame in ledgers.items()
        }
        total_trade_leaks = sum(trade_leaks.values())
        require(total_trade_leaks == 0, f"PERMANENT_EXCLUSION_TRADE_LEAKAGE:{total_trade_leaks}")

        signal_leaks = {}
        for name in ("MA60", "ALIGNMENT"):
            signal = pd.read_csv(OUT / f"p3_1_{name.lower()}_signal_audit.csv", dtype={"ticker": str, "isu_cd": str})
            signal_leaks[name] = pair_leak_count(signal, policy_pairs, "ticker", "isu_cd")
        total_signal_leaks = sum(signal_leaks.values())
        require(total_signal_leaks == 0, f"PERMANENT_EXCLUSION_SIGNAL_AUDIT_LEAKAGE:{total_signal_leaks}")

        cap_contract = pd.read_csv(OUT / "p3_1_market_cap_filter_audit.csv")
        require(len(cap_contract) == 1, "MARKET_CAP_CONTRACT_AUDIT_ROW_COUNT")
        require(not cap_contract["market_cap_filter_applied"].astype(bool).any(), "MARKET_CAP_FILTER_WAS_APPLIED")
        require(int(cap_contract["market_cap_based_reject_count"].sum()) == 0, "MARKET_CAP_REJECT_COUNT_NONZERO")
        require(cap_contract["market_cap_threshold"].isna().all(), "MARKET_CAP_THRESHOLD_PRESENT")
        for name in ("MA60", "ALIGNMENT"):
            signal = pd.read_csv(OUT / f"p3_1_{name.lower()}_signal_audit.csv", dtype={"ticker": str, "isu_cd": str})
            require(not signal["market_cap_filter_applied"].astype(bool).any(), f"{name}_MARKET_CAP_FILTER_AUDIT_TRUE")
            require(not signal["current_survivor_membership_used"].astype(bool).any(), f"{name}_SURVIVOR_MEMBERSHIP_AUDIT_TRUE")
            require(signal["pit_mcap_pass"].astype(bool).all(), f"{name}_NO_GATE_PIT_PASSTHROUGH_FALSE")

        metric_frame = pd.DataFrame(metrics)
        require(metric_frame["trade_count"].eq(
            metric_frame["realized_count"] + metric_frame["open_at_cutoff_count"] + metric_frame["lifecycle_settled_count"]
        ).all(), "TRADE_STATUS_COUNT_MISMATCH")
        require(metric_frame["terminal_return_available_count"].eq(metric_frame["trade_count"]).all(), "MISSING_TERMINAL_RETURN")
        require(metric_frame["net_terminal_recompute_mismatch_count"].eq(0).all(), "NET_TERMINAL_RECOMPUTE_MISMATCH")
        deltas, thresholds = p2.metric_tables(metric_frame)
        by_strategy = {str(row["strategy"]): row for row in metric_frame.to_dict("records")}
        control_open_count = int(by_strategy["CONTROL"]["open_at_cutoff_count"])
        deltas["cutoff_open_count_delta"] = [
            int(by_strategy[str(candidate)]["open_at_cutoff_count"]) - control_open_count
            for candidate in deltas["candidate"]
        ]
        previous_metrics_path = Path(__file__).resolve().parent / "p3_1_strategy_metrics.csv"
        previous_metrics = pd.read_csv(previous_metrics_path)
        previous_by_strategy = {str(row["strategy"]): row for row in previous_metrics.to_dict("records")}
        previous_comparison_rows = []
        comparison_fields = (
            "trade_count", "realized_count", "open_at_cutoff_count", "realized_win_rate_pct",
            "terminal_positive_rate_pct", "average_terminal_return_pct", "median_terminal_return_pct",
            "average_realized_return_pct", "median_realized_return_pct", "average_holding_days",
            "median_holding_days", "loss_guard_exit_count", "progressed_count",
        )
        for current in metric_frame.to_dict("records"):
            name = str(current["strategy"])
            previous = previous_by_strategy[name]
            row = {"strategy": name}
            for field in comparison_fields:
                before = pd.to_numeric(pd.Series([previous.get(field)]), errors="coerce").iloc[0]
                after = pd.to_numeric(pd.Series([current.get(field)]), errors="coerce").iloc[0]
                row[f"previous_{field}"] = None if pd.isna(before) else float(before)
                row[f"corrected_{field}"] = None if pd.isna(after) else float(after)
                row[f"{field}_delta"] = None if pd.isna(before) or pd.isna(after) else float(after - before)
            row["previous_trade_count"] = int(previous["trade_count"])
            row["corrected_trade_count"] = int(current["trade_count"])
            row["trade_count_delta"] = int(current["trade_count"]) - int(previous["trade_count"])
            row["average_terminal_return_delta_pp"] = row["average_terminal_return_pct_delta"]
            row["median_terminal_return_delta_pp"] = row["median_terminal_return_pct_delta"]
            row["realized_win_rate_delta_pp"] = row["realized_win_rate_pct_delta"]
            previous_comparison_rows.append(row)
        previous_comparison = pd.DataFrame(previous_comparison_rows)
        write_frame(OUT / "p3_1_strategy_metrics.csv", metric_frame)
        write_frame(OUT / "p3_1_strategy_metrics_reconciled.csv", metric_frame)
        write_frame(OUT / "p3_1_deltas_vs_control.csv", deltas)
        write_frame(OUT / "p3_1_large_outcomes.csv", thresholds)
        write_frame(OUT / "p3_1_comparison_vs_unauthorized_previous.csv", previous_comparison)
        progressed = pd.concat(progression_frames, ignore_index=True) if progression_frames else pd.DataFrame()
        write_frame(OUT / "p3_1_progressed_reconciliation_audit.csv", progressed)

        exit_rows = []
        for name, frame in ledgers.items():
            counts = frame.get("exit_type", pd.Series(index=frame.index, dtype=object)).fillna("(none)").astype(str).value_counts()
            exit_rows.extend({"strategy": name, "exit_type": key, "count": int(value)} for key, value in counts.items())
        exits = pd.DataFrame(exit_rows)
        write_frame(OUT / "p3_1_exit_reason_distribution.csv", exits)
        price_audit = pd.DataFrame(prices.audit.values())
        write_frame(OUT / "p3_1_price_store_audit.csv", price_audit)

        worker_error_counts = {name: len(execution["execution"][name].get("worker_errors", [])) for name in STRATEGIES}
        worker_counts = {name: int(execution["execution"][name].get("worker_count", 0)) for name in STRATEGIES}
        processed_counts = {name: int(execution["execution"][name].get("ticker_count", 0)) for name in STRATEGIES}
        checks = {
            "worker_error_count": int(sum(worker_error_counts.values())),
            "strategy_worker_error_counts": worker_error_counts,
            "strategy_worker_counts": worker_counts,
            "processed_ticker_counts": processed_counts,
            "duplicate_trade_key_count": int(sum(frame["pair_id"].astype(str).duplicated().sum() for frame in ledgers.values())),
            "candidate_signal_parity": all(item.get("accepted_signal_trade_parity") for item in audit_checks.values()),
            "ma60_filter_check": audit_checks.get("MA60", {}).get("filter_formula_and_fail_closed", False),
            "alignment_filter_check": audit_checks.get("ALIGNMENT", {}).get("filter_formula_and_fail_closed", False),
            "net_terminal_recompute_mismatch_count": int(metric_frame["net_terminal_recompute_mismatch_count"].sum()),
            "post_cutoff_entry_count": int(sum(pd.to_datetime(frame["entry_signal_date"], errors="coerce").gt(cutoff).sum() for frame in ledgers.values())),
            "post_cutoff_entry_execution_count": int(sum(pd.to_datetime(frame["entry_execution_date"], errors="coerce").gt(cutoff).sum() for frame in ledgers.values())),
            "market_cap_filter_applied": False,
            "market_cap_threshold": None,
            "market_cap_based_reject_count": int(cap_contract["market_cap_based_reject_count"].sum()),
            "current_survivor_based_exclusion_count": pre["current_survivor_based_exclusion_count_in_corrected_run"],
            "permanent_exclusion_trade_leakage_count": total_trade_leaks,
            "permanent_exclusion_trade_leakage_by_strategy": trade_leaks,
            "permanent_exclusion_signal_audit_leakage_count": total_signal_leaks,
            "permanent_exclusion_signal_audit_leakage_by_strategy": signal_leaks,
            "network_calls": network_calls,
            "processed_ticker_count_each_strategy": pre["p3_1_unique_ticker_count"],
            "identity_key_count": pre["p3_1_window_pit_identity_key_count"],
            "identity_segment_count": pre["p3_1_window_pit_segment_count"],
            "candidate_audits": audit_checks,
            "trade_file_hashes": trade_hashes,
            "price_partition_count": int(len(price_audit)),
            "price_partition_hash_metadata_checks_pass": bool(price_audit.empty or (
                price_audit["metadata_row_count_matches"].astype(bool).all()
                and price_audit["metadata_date_range_matches"].astype(bool).all()
            )),
        }
        require(checks["worker_error_count"] == 0 and all(value == WORKERS for value in worker_counts.values()), "STRATEGY_WORKER_COMPLETION_INTEGRITY_FAILURE")
        require(all(value == pre["p3_1_unique_ticker_count"] for value in processed_counts.values()), "STRATEGY_COMMON_UNIVERSE_PROCESSING_MISMATCH")
        require(checks["candidate_signal_parity"] and checks["ma60_filter_check"] and checks["alignment_filter_check"], "CANDIDATE_SIGNAL_OR_FILTER_INTEGRITY_FAILURE")
        require(checks["price_partition_hash_metadata_checks_pass"], "PRICE_PARTITION_HASH_METADATA_CHECK_FAILED")
        require(checks["duplicate_trade_key_count"] == 0, "DUPLICATE_TRADE_KEY")
        require(checks["post_cutoff_entry_count"] == 0 and checks["post_cutoff_entry_execution_count"] == 0, "POST_CUTOFF_ENTRY")
        require(total_trade_leaks == 0 and total_signal_leaks == 0, "PERMANENT_EXCLUSION_LEAKAGE")
        require(checks["market_cap_filter_applied"] is False and checks["market_cap_based_reject_count"] == 0, "MARKET_CAP_GATE_INTEGRITY_FAILURE")
        require(checks["current_survivor_based_exclusion_count"] == 0, "CURRENT_SURVIVOR_LOOKAHEAD_INTEGRITY_FAILURE")

        STAGE = "COMPRESS_AND_FINALIZE"
        compressed = []
        for filename in (
            "p3_1_market_cap_filter_audit.csv",
            "p3_1_ma60_signal_audit.csv",
            "p3_1_alignment_signal_audit.csv",
            "p3_1_price_store_audit.csv",
        ):
            compressed.append(p2.compress_verified(OUT / filename).name)

        execution.update({
            "status": "PASS",
            "final_token": FINAL_TOKEN,
            "worker_count": WORKERS,
            "worker_errors": [],
            "eligible_historical_identity_key_count": pre["eligible_historical_identity_key_count"],
            "identity_key_count": pre["p3_1_window_pit_identity_key_count"],
            "identity_segment_count": pre["p3_1_window_pit_segment_count"],
            "processed_ticker_count_each_strategy": pre["p3_1_unique_ticker_count"],
            "strategy_trade_counts": {name: int(len(frame)) for name, frame in ledgers.items()},
            "progressed_counts_authoritative": {str(row["strategy"]): int(row["progressed_count"]) for row in metrics},
            "checks": checks,
            "compressed_verified_audits": compressed,
            "elapsed_seconds": time.perf_counter() - started,
        })
        write_json(OUT / "p3_1_execution_audit.json", execution)
        (OUT / "report.md").write_text(markdown_report(metric_frame, deltas, exits, checks, pre, thresholds, previous_comparison), encoding="utf-8")

        provenance = {
            "status": "PASS",
            "final_token": FINAL_TOKEN,
            "work_id": WORK_ID,
            "scope": "P3-1 single-window trade-level simple backtest only",
            "window": WINDOW,
            "worker_count": WORKERS,
            "network_calls": network_calls,
            "result_reuse": pre["result_reuse"],
            "authority": {
                "frozen_pit_sha256": pre["frozen_pit_sha256"],
                "frozen_calendar_sha256": pre["frozen_calendar_sha256"],
                "frozen_manifest_sha256": pre["frozen_manifest_sha256"],
                "historical_common_identity_key_count": pre["historical_common_identity_key_count"],
                "historical_common_segment_count": pre["historical_common_segment_count"],
                "current_survivor_projection_sha256_compare_only": pre["current_survivor_projection_sha256_compare_only"],
                "current_survivor_projection_count_compare_only": pre["current_survivor_projection_count_compare_only"],
                "current_survivor_used_for_eligibility": False,
                "permanent_exclusion_registry_count": pre["permanent_exclusion_registry_count"],
                "permanent_exclusion_duplicate_exact_pair_count": pre["permanent_exclusion_duplicate_exact_pair_count"],
                "eligible_historical_identity_key_count": pre["eligible_historical_identity_key_count"],
                "current_survivor_omitted_historical_identity_key_count_compare_only": pre["current_survivor_omitted_historical_identity_key_count_compare_only"],
                "current_survivor_based_exclusion_count_in_corrected_run": checks["current_survivor_based_exclusion_count"],
                "market_cap_filter": "NONE",
                "market_cap_based_reject_count": checks["market_cap_based_reject_count"],
                "p3_1_window_pit_identity_key_count": pre["p3_1_window_pit_identity_key_count"],
                "p3_1_window_pit_segment_count": pre["p3_1_window_pit_segment_count"],
            },
            "source_hashes": pre["input_source_hashes"],
            "execution_script_sha256": sha256(Path(__file__)),
            "adjusted_price_store_partition_hashes": price_audit[[column for column in (
                "ticker", "relative_path", "sha256", "metadata_relative_path", "metadata_sha256",
                "source_authority_id", "source_semantics", "authority_type", "row_count", "actual_date_min", "actual_date_max"
            ) if column in price_audit.columns]].to_dict("records"),
            "previous_result_comparison_only": {
                "classification": pre["previous_result_classification"],
                "metrics_path": pre["previous_result_metrics_path"],
                "metrics_sha256": pre["previous_result_metrics_sha256"],
                "used_for_replay": False,
                "comparison_artifact": "p3_1_comparison_vs_unauthorized_previous.csv",
            },
            "market_cap_filter_contract_audit": {
                "audit_file": "p3_1_market_cap_filter_audit.csv",
                "filter_applied": False,
                "threshold": None,
                "market_cap_based_reject_count": 0,
                "market_cap_partitions_read_for_eligibility": False,
            },
            "cost_contract": pre["cost_contract"],
            "metrics_progressed_basis": "entry execution <= event <= exit signal for REALIZED; <= effective cutoff for OPEN_AT_CUTOFF; <= settlement date for LIFECYCLE_SETTLED",
            "no_portfolio_mdd": True,
            "integrity": checks,
            "artifact_sha256": {
                path.name: sha256(path)
                for path in sorted(OUT.iterdir())
                if path.is_file() and path.name not in {"p3_1_provenance.json", "artifact_manifest.json"}
            },
            "elapsed_seconds": time.perf_counter() - started,
        }
        write_json(OUT / "p3_1_provenance.json", provenance)
        manifest_files = {
            path.name: sha256(path)
            for path in sorted(OUT.iterdir())
            if path.is_file() and path.name != "artifact_manifest.json"
        }
        write_json(OUT / "artifact_manifest.json", {"status": "PASS", "final_token": FINAL_TOKEN, "files": manifest_files})
        manifest = json.loads((OUT / "artifact_manifest.json").read_text(encoding="utf-8"))
        require(all(sha256(OUT / name) == digest for name, digest in manifest["files"].items()), "ARTIFACT_MANIFEST_HASH_MISMATCH")
        return 0
    except Exception as exc:
        try:
            OUT.mkdir(parents=True, exist_ok=True)
            write_json(OUT / "failure.json", {
                "status": "CHECK_REQUIRED",
                "final_token": CHECK_TOKEN,
                "stage": STAGE,
                "replay_started": REPLAY_STARTED,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "automatic_retry": False,
                "partial_output_is_final_result": False,
                "next_action": "stop and report; do not rerun or interpret partial metrics",
            })
        except Exception:
            pass
        raise


if __name__ == "__main__":
    raise SystemExit(main())
