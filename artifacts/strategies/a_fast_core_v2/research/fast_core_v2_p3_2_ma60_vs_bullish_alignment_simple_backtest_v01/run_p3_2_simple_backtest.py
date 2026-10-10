#!/usr/bin/env python3
"""Fresh, offline P3-2 trade-level replay using exact permanent identity exclusions."""

from __future__ import annotations

import importlib.util
import json
import math
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from trend_scanner.universe.permanent_identity_exclusions import PERMANENT_IDENTITY_EXCLUSIONS

OUT = Path(__file__).resolve().parent
BASE_RUNNER_PATH = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p2_2_ma60_vs_bullish_alignment_simple_backtest_v01/run_p2_2_simple_backtest.py"
spec = importlib.util.spec_from_file_location("p3_2_certified_simple_runner_utilities", BASE_RUNNER_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("P2_2_RUNNER_IMPORT_FAILED")
p2 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = p2
spec.loader.exec_module(p2)

WORK_ID = "FAST_CORE_V2_P3_2_MA60_VS_BULLISH_ALIGNMENT_SIMPLE_BACKTEST_V01"
FINAL_TOKEN = WORK_ID + "_PASS"
CHECK_TOKEN = WORK_ID + "_CHECK_REQUIRED"
WINDOW_ID = "P3-2"
WINDOW = {"effective_start": "2022-01-03", "effective_end": "2026-08-31", "execution_support": "2026-09-01"}
WORKERS = 10
STRATEGIES = {
    "CONTROL": ("PATTERN_A_FAST_FINAL_STRATEGY_V02", "p3_2_control_trades.csv"),
    "MA60": ("PATTERN_A_FAST_FINAL_STRATEGY_V02_MA60_ENTRY_FILTER", "p3_2_ma60_trades.csv"),
    "ALIGNMENT": ("PATTERN_A_FAST_FINAL_STRATEGY_V02_MONTHLY_MA20_MA60_BULLISH_ALIGNMENT", "p3_2_alignment_trades.csv"),
}
STAGE = "STARTUP"
REPLAY_STARTED = False

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


def source_hashes_for(module: Any) -> dict[str, Any]:
    hashes = {}
    for name, path in p2.source_paths(module).items():
        require(path.is_file(), f"INPUT_MISSING:{name}:{path}")
        relative = path.relative_to(ROOT).as_posix()
        digest = sha256(path)
        committed = subprocess.run(
            ["git", "show", f"HEAD:{relative}"], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        require(committed.returncode == 0 and committed.stdout == path.read_bytes(), f"INPUT_HASH_DIFFERS_FROM_HEAD:{name}")
        hashes[name] = {"path": relative, "sha256": digest}
    for name, path in (
        ("certified_p2_2_runner_utilities", BASE_RUNNER_PATH),
        ("p3_2_execution_script", Path(__file__)),
    ):
        require(path.is_file(), f"INPUT_MISSING:{name}")
        hashes[name] = {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": sha256(path),
            "tracked_at_start": name != "p3_2_execution_script",
        }
    return hashes


def preflight(module: Any):
    allowed = {Path(__file__).name, "__pycache__"}
    unexpected = sorted(item.name for item in OUT.iterdir() if item.name not in allowed)
    require(not unexpected, "REFUSING_TO_OVERWRITE_EXISTING_OUTPUTS:" + ",".join(unexpected))
    require(git("branch", "--show-current") == "main", "EXPECTED_MAIN_BRANCH")
    head, origin = git("rev-parse", "HEAD"), git("rev-parse", "origin/main")
    require(head == origin, "START_HEAD_NOT_ORIGIN_MAIN")
    require(git("rev-list", "--left-right", "--count", "origin/main...HEAD") == "0\t0", "START_AHEAD_BEHIND_NOT_ZERO")
    require(git_clean_tracked(), "TRACKED_WORKTREE_OR_INDEX_NOT_CLEAN")

    input_hashes = source_hashes_for(module)
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
    require(sha256(survivor_path) == "313bca3d5dbc28672cb505c18b61af40a9b4b827c11af56b30f45160cdba1506", "FROZEN_SURVIVOR_ROSTER_HASH_MISMATCH")

    network = module.network_guard()
    try:
        frozen, base_run, base_gate, universe, authority, roster = module.load_frozen_context()
        require(len(roster) == 2539, "FROZEN_SURVIVOR_IDENTITY_COUNT_MISMATCH")
        roster_pairs = {(item[0], item[1]) for item in roster}
        excluded = frozenset(item for item in roster if (item[0], item[1]) in policy_pairs)
        eligible = frozenset(roster - excluded)
        overlap_pairs = roster_pairs & policy_pairs
        require(len(excluded) == len(overlap_pairs), "PERMANENT_EXCLUSION_ROSTER_PAIR_NOT_UNIQUE")
        require(len(overlap_pairs) == 115, "FROZEN_ROSTER_EXCLUSION_OVERLAP_MISMATCH")
        require(len(eligible) == 2424, "ELIGIBLE_SURVIVOR_COUNT_MISMATCH")
        require(not any((item[0], item[1]) in policy_pairs for item in eligible), "PERMANENT_EXCLUSION_FILTER_LEAK")
        run, scoped_gate, context = module.context_for_window(base_run, base_gate, eligible, WINDOW_ID)
        require(context["effective_start"] == WINDOW["effective_start"], "P3_2_START_MISMATCH")
        require(context["effective_end"] == WINDOW["effective_end"], "P3_2_CUTOFF_MISMATCH")
        require(context["execution_support"] == WINDOW["execution_support"], "P3_2_SUPPORT_MISMATCH")
        require(context["survivor_identity_count"] == len(eligible), "P3_2_SURVIVOR_CONTEXT_MISMATCH")
        require(context["common_pit_segment_count"] == sum(map(len, run.segments_by_ticker.values())), "P3_2_SEGMENT_CONTEXT_MISMATCH")
        require(math.isclose(float(module.COMM_RATE), 0.00015, rel_tol=0, abs_tol=1e-12), "BUY_OR_SELL_FEE_CONTRACT_MISMATCH")
        require(math.isclose(float(module.SLIP_RATE), 0.001, rel_tol=0, abs_tol=1e-12), "BUY_OR_SELL_SLIPPAGE_CONTRACT_MISMATCH")
        scoped_pairs = {
            (segment.ticker, segment.isu_cd.strip().upper())
            for rows in run.segments_by_ticker.values()
            for segment in rows
        }
        require(not (scoped_pairs & policy_pairs), "P3_2_WINDOW_PERMANENT_EXCLUSION_LEAK")
        require(network[2]["calls"] == 0, "NETWORK_CALLS_DURING_PREFLIGHT")
    finally:
        module.restore_network_guard(network)

    identity_keys = {
        (segment.ticker, segment.isu_cd, segment.market)
        for rows in run.segments_by_ticker.values()
        for segment in rows
    }
    identity_audit = universe.copy()
    identity_audit["ticker"] = identity_audit["ticker"].astype(str).str.zfill(6)
    identity_audit["isu_cd"] = identity_audit["isu_cd"].astype(str).str.strip().str.upper()
    identity_audit["is_frozen_survivor"] = identity_audit["status"].astype(str).eq("SURVIVOR_COMMON_IDENTITY")
    identity_audit["current_permanent_exclusion"] = [
        (ticker, isu_cd) in policy_by_identity
        for ticker, isu_cd in zip(identity_audit["ticker"], identity_audit["isu_cd"])
    ]
    window_keys = {
        (segment.ticker, segment.isu_cd.strip().upper(), segment.market.strip().upper())
        for rows in run.segments_by_ticker.values()
        for segment in rows
    }
    identity_audit["p3_2_window_pit_overlap"] = [
        (ticker, isu_cd, str(market).strip().upper()) in window_keys
        for ticker, isu_cd, market in zip(identity_audit["ticker"], identity_audit["isu_cd"], identity_audit["market"])
    ]
    identity_audit["included_in_p3_2"] = (
        identity_audit["is_frozen_survivor"]
        & ~identity_audit["current_permanent_exclusion"]
        & identity_audit["p3_2_window_pit_overlap"]
    )
    for field in ("failure_class", "approval_scope", "approved_date", "reason"):
        identity_audit["permanent_exclusion_" + field] = [
            policy_by_identity.get((ticker, isu_cd), {}).get(field)
            for ticker, isu_cd in zip(identity_audit["ticker"], identity_audit["isu_cd"])
        ]
    require(int(identity_audit["included_in_p3_2"].sum()) == len(identity_keys), "IDENTITY_AUTHORITY_AUDIT_CONTEXT_COUNT_MISMATCH")

    pre = {
        "status": "PASS",
        "work_id": WORK_ID,
        "window_id": WINDOW_ID,
        "branch": "main",
        "start_head": head,
        "start_origin_main": origin,
        "head_equals_origin_main": True,
        "ahead_behind": "0\t0",
        "tracked_worktree_clean": True,
        **context,
        "workers": WORKERS,
        "strategy_ids": {name: values[0] for name, values in STRATEGIES.items()},
        "survivor_identity_roster_count": len(roster),
        "survivor_identity_roster_sha256": sha256(survivor_path),
        "permanent_exclusion_registry_count": raw_registry_count,
        "permanent_exclusion_duplicate_exact_pair_count": raw_registry_count - len(policy_by_identity),
        "permanent_exclusion_ticker_only_matching_used": False,
        "survivor_permanent_exclusion_overlap_count": len(overlap_pairs),
        "eligible_survivor_identity_count": len(eligible),
        "p3_2_window_pit_identity_key_count": len(identity_keys),
        "p3_2_window_pit_segment_count": sum(map(len, run.segments_by_ticker.values())),
        "p3_2_unique_ticker_count": context["unique_ticker_count"],
        "permanent_exclusions_applied_before_strategy_replay_by_exact_ticker_isu": True,
        "eligible_survivor_exclusion_residue_count": 0,
        "excluded_survivor_identities": [
            {"ticker": ticker, "isu_cd": isu_cd, "market": market, **policy_by_identity[(ticker, isu_cd)]}
            for ticker, isu_cd, market in sorted(excluded)
        ],
        "frozen_authority": json_value(authority),
        "frozen_manifest_sha256": sha256(manifest_path),
        "frozen_pit_sha256": sha256(base_run.authority.pit_path),
        "frozen_calendar_sha256": sha256(pit_dir / "merged_trading_calendar.json"),
        "input_source_hashes": input_hashes,
        "price_source": "Local Repository V2 adjusted/raw stores; MA inputs from hash-verified adjusted stock partitions",
        "market_cap_source": "Local exact-date KRX raw Stock Daily MKTCAP snapshots with manifest and hash validation",
        "cost_contract": {
            "buy_commission_rate": module.COMM_RATE,
            "sell_commission_rate": module.COMM_RATE,
            "buy_slippage_rate": module.SLIP_RATE,
            "sell_slippage_rate": module.SLIP_RATE,
            "transaction_tax_in_returns": False,
        },
        "result_reuse": {
            "prior_performance_results": False,
            "p1_results": False,
            "p2_1_results": False,
            "p2_2_results": False,
            "p3_1_results": False,
            "p3_2_results": False,
            "frozen_pit_calendar_reused_as_authority": True,
            "frozen_survivor_identity_roster_reused_as_authority": True,
        },
        "network_calls": 0,
    }
    return pre, frozen, base_run, base_gate, eligible, identity_audit


def pair_leak_count(frame: pd.DataFrame, pairs: set[tuple[str, str]], ticker_col: str, isu_col: str) -> int:
    require({ticker_col, isu_col}.issubset(frame.columns), f"EXCLUSION_AUDIT_IDENTITY_COLUMNS_MISSING:{ticker_col}:{isu_col}")
    values = zip(frame[ticker_col].astype(str).str.zfill(6), frame[isu_col].astype(str).str.strip().str.upper())
    return sum((ticker, isu_cd) in pairs for ticker, isu_cd in values)


def markdown_report(
    metrics: pd.DataFrame,
    deltas: pd.DataFrame,
    exits: pd.DataFrame,
    checks: dict[str, Any],
    pre: dict[str, Any],
    thresholds: pd.DataFrame,
    frequency: pd.DataFrame,
    elapsed_seconds: float,
) -> str:
    def f(value: Any, digits: int = 2) -> str:
        return "—" if value is None or pd.isna(value) else f"{float(value):.{digits}f}"

    unresolved = int(checks["control_mcap_unresolved_count"])
    major_count = int(unresolved > 0)
    major_detail = (
        f"정확한 날짜의 MKTCAP을 확인할 수 없어 fail-closed로 막힌 신호 {unresolved}건"
        if unresolved else "미해결 exact-date MKTCAP 신호 없음"
    )
    lines = [
        "# FAST Core V2 P3-2 MA60 vs Bullish Alignment 단순 백테스트",
        "",
        "| 레벨 | 개수 | 내용 |",
        "|---|---:|---|",
        "| CRITICAL | 0 | 필수 무결성 검증 불일치 없이 집계 완료 |",
        f"| MAJOR | {major_count} | {major_detail} |",
        "| MINOR | 1 | 거래 단위 분석이며 포트폴리오 MDD는 범위 밖 |",
        "",
        "## 1. 최종 판정",
        "",
        f"- 판정: `{FINAL_TOKEN}`",
        f"- 기간: {WINDOW['effective_start']}~{WINDOW['effective_end']}; 실행 지원일: {WINDOW['execution_support']}. 기간 종료 뒤 신규 진입은 0건이야.",
        "- P3-2 한 기간의 CONTROL, MA60, Bullish Alignment 거래 단위 비교야. 다른 기간 결과 비교나 전략 승격 판단은 하지 않았어.",
        "",
        "## 2. Authority / universe",
        "",
        f"- 영구 제외 정책: {pre['permanent_exclusion_registry_count']}개 exact `(ticker, ISU)` pair, 중복 {pre['permanent_exclusion_duplicate_exact_pair_count']}개.",
        f"- Frozen survivor: {pre['survivor_identity_roster_count']:,}; 현재 제외와 교집합 {pre['survivor_permanent_exclusion_overlap_count']}; replay 전 필터된 공통 eligible universe {pre['eligible_survivor_identity_count']:,}.",
        f"- P3-2 PIT overlap: identity {pre['p3_2_window_pit_identity_key_count']:,}, segment {pre['p3_2_window_pit_segment_count']:,}, ticker {pre['p3_2_unique_ticker_count']:,}.",
        "- 제외 적용은 exact `(ticker, ISU)` pair 기준이고 ticker-only 매칭은 사용하지 않았어.",
        "- 세 전략은 같은 survivor roster, PIT interval, 거래 캘린더, 가격 authority, lifecycle, cutoff와 비용 조건을 공유했어.",
        "",
        "## 3. PIT / lifecycle 무결성",
        "",
        f"- Permanent-exclusion leakage: trades {checks['permanent_exclusion_trade_leakage_count']}, signal audits {checks['permanent_exclusion_signal_audit_leakage_count']}, MKTCAP audit {checks['permanent_exclusion_mcap_audit_leakage_count']}.",
        f"- Exact-date MKTCAP unresolved {unresolved}건; reason 분포 {checks['control_mcap_unresolved_reason_counts']}; gate를 통과한 CONTROL 진입의 MKTCAP 확인 {checks['control_mcap_trade_entry_pass']}. UNRESOLVED 신호는 진입시키지 않았어.",
        f"- Worker 10개/전략, worker 오류 {checks['worker_error_count']}, 네트워크 호출 {checks['network_calls']}; 처리 ticker 수 일치 {checks['same_universe_count_match']}.",
        f"- Signal↔trade accepted parity {checks['candidate_signal_parity']}; MA60 fail-closed/formula {checks['ma60_filter_check']}; Alignment fail-closed/formula {checks['alignment_filter_check']}.",
        f"- Duplicate trade key {checks['duplicate_trade_key_count']}; post-cutoff entry {checks['post_cutoff_entry_count']}; terminal return 재계산 불일치 {checks['net_terminal_recompute_mismatch_count']}.",
        f"- PIT SHA-256 `{pre['frozen_pit_sha256']}`; calendar `{pre['frozen_calendar_sha256']}`; survivor roster `{pre['survivor_identity_roster_sha256']}`; exclusion registry `{pre['input_source_hashes']['permanent_identity_exclusion_registry']['sha256']}`.",
        "- Net 수익률은 매수/매도 수수료 각 0.015%, 슬리피지 각 0.10%를 반영했고 거래세는 제외했어.",
        "",
        "## 4. 전략별 핵심 결과",
        "",
        "| 전략 | 거래 | 실현 | 생애주기 정산 | cutoff 미종료 | terminal 결과 | 실현 승률 % | terminal 양수율 % | terminal 평균 % | terminal 중앙 % | realized 평균 % | realized 중앙 % | 평균 보유일 | 중앙 보유일 | Loss Guard 건수/율 | PROGRESSED 건수/율 | 최대 수익 % | 최대 손실 % |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in metrics.to_dict("records"):
        lines.append(
            f"| {row['strategy']} | {row['trade_count']} | {row['realized_count']} | {row['lifecycle_settled_count']} | {row['open_at_cutoff_count']} ({f(row['open_at_cutoff_rate_pct'])}%) | "
            f"{row['terminal_return_available_count']} | {f(row['realized_win_rate_pct'])} | {f(row['terminal_positive_rate_pct'])} | {f(row['average_terminal_return_pct'])} | {f(row['median_terminal_return_pct'])} | "
            f"{f(row['average_realized_return_pct'])} | {f(row['median_realized_return_pct'])} | {f(row['average_holding_days'])} | {f(row['median_holding_days'])} | "
            f"{row['loss_guard_exit_count']} ({f(row['loss_guard_rate_pct'])}%) | {row['progressed_count']} ({f(row['progressed_rate_pct'])}%) | {f(row['max_terminal_return_pct'])} | {f(row['min_terminal_return_pct'])} |"
        )
    lines += [
        "",
        "## 5. CONTROL 대비 delta",
        "",
        "| 후보 | 거래 수 Δ | 거래 감소율 % | 실현 승률 Δ %p | terminal 양수율 Δ %p | terminal 평균/중앙 Δ %p | realized 평균/중앙 Δ %p | 평균 보유일 Δ | +20/+50/+100% 건수 Δ | +20/+50/+100% 비율 Δ %p | -10/-15/-20/-30% 건수 Δ | 손실 비율 Δ %p | Loss Guard 건수/율 Δ | PROGRESSED 건수/율 Δ | cutoff 미종료 건수/율 Δ |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in deltas.to_dict("records"):
        wins_count = "/".join(str(row[f"terminal_ge_{n}_count_delta"]) for n in (20, 50, 100))
        wins_rate = "/".join(f(row[f"terminal_ge_{n}_rate_delta_pp"]) for n in (20, 50, 100))
        loss_count = "/".join(str(row[f"terminal_le_neg_{n}_count_delta"]) for n in (10, 15, 20, 30))
        loss_rate = "/".join(f(row[f"terminal_le_neg_{n}_rate_delta_pp"]) for n in (10, 15, 20, 30))
        lines.append(
            f"| {row['candidate']} | {row['trade_count_delta']} | {f(row['trade_count_reduction_pct'])} | {f(row['realized_win_rate_delta_pp'])} | {f(row['terminal_positive_rate_delta_pp'])} | "
            f"{f(row['average_terminal_delta_pp'])}/{f(row['median_terminal_delta_pp'])} | {f(row['average_realized_delta_pp'])}/{f(row['median_realized_delta_pp'])} | {f(row['average_holding_days_delta'])} | "
            f"{wins_count} | {wins_rate} | {loss_count} | {loss_rate} | {row['loss_guard_count_delta']}/{f(row['loss_guard_rate_delta_pp'])}%p | "
            f"{row['progressed_count_delta']}/{f(row['progressed_rate_delta_pp'])}%p | {row['cutoff_open_count_delta']}/{f(row['cutoff_open_rate_delta_pp'])}%p |"
        )
    lines += [
        "",
        "## 6. 수익 / 손실 구간",
        "",
        "| 전략 | 구간 | 건수 | 전체 거래 대비 % |",
        "|---|---|---:|---:|",
    ]
    for row in thresholds.to_dict("records"):
        lines.append(f"| {row['strategy']} | {row['threshold']} | {row['count']} | {f(row['rate_pct_of_all_trades'])} |")
    lines += [
        "",
        "## 7. 거래 빈도",
        "",
        "진입 신호일 기준 연도별 거래 수야. 2026년은 8월 31일까지의 부분 연도야.",
        "",
        "| 전략 | 연도 | 진입 건수 |",
        "|---|---:|---:|",
    ]
    for row in frequency.to_dict("records"):
        lines.append(f"| {row['strategy']} | {row['year']} | {row['entry_count']} |")
    lines += ["", "## 8. 주요 관찰점", ""]
    lines += ["### Exit reason 분포", "", "| 전략 | Exit reason | 건수 |", "|---|---|---:|"]
    for row in exits.to_dict("records"):
        lines.append(f"| {row['strategy']} | {row['exit_type']} | {row['count']} |")
    lines.append("")
    if not metrics.empty:
        valid_avg = metrics.dropna(subset=["average_terminal_return_pct"])
        valid_median = metrics.dropna(subset=["median_terminal_return_pct"])
        if not valid_avg.empty:
            row = valid_avg.sort_values("average_terminal_return_pct", ascending=False).iloc[0]
            lines.append(f"- 이 세 전략 중 terminal 평균 수익률이 가장 높은 전략은 {row['strategy']} ({f(row['average_terminal_return_pct'])}%)이야.")
        if not valid_median.empty:
            row = valid_median.sort_values("median_terminal_return_pct", ascending=False).iloc[0]
            lines.append(f"- terminal 중앙값이 가장 높은 전략은 {row['strategy']} ({f(row['median_terminal_return_pct'])}%)이야.")
    for row in deltas.to_dict("records"):
        lines.append(
            f"- {row['candidate']}는 CONTROL보다 거래가 {row['trade_count_delta']}건 변했고, 거래 수 변화율은 {f(row['trade_count_reduction_pct'])}%야. "
            f"terminal 평균/중앙 변화는 {f(row['average_terminal_delta_pp'])}/{f(row['median_terminal_delta_pp'])}%p야."
        )
    lines += [
        "",
        "## 9. 제한사항",
        "",
        "- 결과는 단일 기간의 동일 가중 거래 단위 집계야. 동시 보유, 자본 제약, 포트폴리오 equity curve/MDD는 계산하지 않았어.",
        "- 이번 결과만으로 다기간 반복성, 공식 전략 승격, FAST Core V2 교체 또는 포트폴리오 우위를 결론 내리지 않아.",
        "- PROGRESSED는 authoritative lifecycle event와 realized/cutoff/settlement boundary를 대조한 거래별 audit 기준이야. Exit reason 분포는 아래 산출물과 `p3_2_exit_reason_distribution.csv`에 있어.",
        "",
        "## 10. 실행시간",
        "",
        f"전체 사전점검·재생·무결성 검증·보고서 생성 시간: {elapsed_seconds / 60:.1f}분 ({elapsed_seconds:.1f}초).",
        "",
        "## 11. 생성 artifact 목록",
        "",
        f"전용 폴더: `{OUT.relative_to(ROOT).as_posix()}/`",
        "- `run_p3_2_simple_backtest.py`, `preflight.json`, `identity_authority_audit.csv`",
        "- CONTROL/MA60/Alignment 거래 원장, 후보 signal audit, CONTROL exact-date MKTCAP audit, 가격 파티션 audit",
        "- `p3_2_strategy_metrics.csv`, `p3_2_strategy_metrics_reconciled.csv`, `p3_2_deltas_vs_control.csv`, `p3_2_large_outcomes.csv`, `p3_2_trade_frequency_by_year.csv`",
        "- `p3_2_progressed_reconciliation_audit.csv`, `p3_2_exit_reason_distribution.csv`, `p3_2_execution_audit.json`, `p3_2_provenance.json`, `artifact_manifest.json`, `report.md`",
        f"- 결과 토큰: `{FINAL_TOKEN}`",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    global STAGE, REPLAY_STARTED, FINAL_TOKEN
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
                "eligible_survivor_identity_count": pre["eligible_survivor_identity_count"],
                "window_identity_key_count": pre["p3_2_window_pit_identity_key_count"],
                "window_segment_count": pre["p3_2_window_pit_segment_count"],
                "unique_ticker_count": pre["p3_2_unique_ticker_count"],
                "network_calls": 0,
                "replay_started": False,
            }, ensure_ascii=False, indent=2))
            return 0

        write_frame(OUT / "identity_authority_audit.csv", identity_audit)
        write_json(OUT / "preflight.json", pre)
        prices = module.HELPER.PriceCache()
        metrics_raw: list[dict[str, Any]] = []
        STAGE = "P3_2_FULL_REPLAY"
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
        require(len(metrics_raw) == 3 and {row["strategy"] for row in metrics_raw} == set(STRATEGIES), "P3_2_METRICS_INCOMPLETE")
        for name, result in execution["execution"].items():
            require(result.get("worker_count") == WORKERS, f"{name}_WORKER_COUNT_MISMATCH")
            require(result.get("worker_errors") == [], f"{name}_WORKER_ERRORS")
            require(result.get("ticker_count") == pre["p3_2_unique_ticker_count"], f"{name}_PROCESSED_TICKER_COUNT_MISMATCH")

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
                    name, OUT / f"p3_2_{name.lower()}_signal_audit.csv", ledger
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
            signal = pd.read_csv(OUT / f"p3_2_{name.lower()}_signal_audit.csv", dtype={"ticker": str, "isu_cd": str})
            signal_leaks[name] = pair_leak_count(signal, policy_pairs, "ticker", "isu_cd")
        total_signal_leaks = sum(signal_leaks.values())
        require(total_signal_leaks == 0, f"PERMANENT_EXCLUSION_SIGNAL_AUDIT_LEAKAGE:{total_signal_leaks}")

        mcap = pd.read_csv(OUT / "p3_2_control_pit_mcap_audit.csv", dtype={"ticker": str, "identity": str})
        unresolved = int(mcap.get("status", pd.Series(dtype=str)).astype(str).eq("UNRESOLVED").sum())
        unresolved_reason_counts = (
            mcap.loc[mcap["status"].astype(str).eq("UNRESOLVED"), "reason"].fillna("(missing)").astype(str).value_counts().to_dict()
            if "reason" in mcap.columns else {}
        )
        require(not mcap.empty, "CONTROL_MCAP_AUDIT_EMPTY")
        mcap_keys = ["ticker", "identity", "market", "signal_date"]
        require(all(column in mcap.columns for column in mcap_keys), "CONTROL_MCAP_AUDIT_KEY_MISSING")
        for column in mcap_keys:
            mcap[column] = mcap[column].astype(str)
        mcap_leaks = pair_leak_count(mcap, policy_pairs, "ticker", "identity")
        require(mcap_leaks == 0, f"PERMANENT_EXCLUSION_MKTCAP_AUDIT_LEAKAGE:{mcap_leaks}")
        require(not mcap.duplicated(mcap_keys).any(), "CONTROL_MCAP_AUDIT_DUPLICATE_SIGNAL")
        status_by_key = mcap.set_index(mcap_keys)["status"].astype(str)
        for row in ledgers["CONTROL"].to_dict("records"):
            key = (
                str(row["ticker"]).zfill(6),
                str(row["isu_cd"]).strip().upper(),
                str(row["market"]).strip().upper(),
                str(row["entry_signal_date"]),
            )
            require(key in status_by_key.index and status_by_key.loc[key] == "PASS", "CONTROL_TRADE_WITHOUT_EXACT_MCAP_PASS")

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
        write_frame(OUT / "p3_2_strategy_metrics.csv", metric_frame)
        write_frame(OUT / "p3_2_strategy_metrics_reconciled.csv", metric_frame)
        write_frame(OUT / "p3_2_deltas_vs_control.csv", deltas)
        write_frame(OUT / "p3_2_large_outcomes.csv", thresholds)
        progressed = pd.concat(progression_frames, ignore_index=True) if progression_frames else pd.DataFrame()
        write_frame(OUT / "p3_2_progressed_reconciliation_audit.csv", progressed)

        frequency_rows = []
        for name, ledger in ledgers.items():
            entry_dates = pd.to_datetime(ledger["entry_signal_date"], errors="coerce")
            require(entry_dates.notna().all(), f"{name}_ENTRY_SIGNAL_DATE_INVALID_FOR_FREQUENCY")
            yearly = entry_dates.dt.year.value_counts()
            for year in range(2022, 2027):
                frequency_rows.append({"strategy": name, "year": year, "entry_count": int(yearly.get(year, 0))})
        frequency = pd.DataFrame(frequency_rows)
        write_frame(OUT / "p3_2_trade_frequency_by_year.csv", frequency)

        exit_rows = []
        for name, frame in ledgers.items():
            counts = frame.get("exit_type", pd.Series(index=frame.index, dtype=object)).fillna("(none)").astype(str).value_counts()
            exit_rows.extend({"strategy": name, "exit_type": key, "count": int(value)} for key, value in counts.items())
        exits = pd.DataFrame(exit_rows)
        write_frame(OUT / "p3_2_exit_reason_distribution.csv", exits)
        price_audit = pd.DataFrame(prices.audit.values())
        write_frame(OUT / "p3_2_price_store_audit.csv", price_audit)

        worker_error_counts = {name: len(execution["execution"][name].get("worker_errors", [])) for name in STRATEGIES}
        worker_counts = {name: int(execution["execution"][name].get("worker_count", 0)) for name in STRATEGIES}
        processed_counts = {name: int(execution["execution"][name].get("ticker_count", 0)) for name in STRATEGIES}
        checks = {
            "worker_error_count": int(sum(worker_error_counts.values())),
            "strategy_worker_error_counts": worker_error_counts,
            "strategy_worker_counts": worker_counts,
            "processed_ticker_counts": processed_counts,
            "same_universe_count_match": len(set(processed_counts.values())) == 1 and all(
                value == pre["p3_2_unique_ticker_count"] for value in processed_counts.values()
            ),
            "duplicate_trade_key_count": int(sum(frame["pair_id"].astype(str).duplicated().sum() for frame in ledgers.values())),
            "candidate_signal_parity": all(item.get("accepted_signal_trade_parity") for item in audit_checks.values()),
            "ma60_filter_check": audit_checks.get("MA60", {}).get("filter_formula_and_fail_closed", False),
            "alignment_filter_check": audit_checks.get("ALIGNMENT", {}).get("filter_formula_and_fail_closed", False),
            "net_terminal_recompute_mismatch_count": int(metric_frame["net_terminal_recompute_mismatch_count"].sum()),
            "post_cutoff_entry_count": int(sum(pd.to_datetime(frame["entry_signal_date"], errors="coerce").gt(cutoff).sum() for frame in ledgers.values())),
            "post_cutoff_entry_execution_count": int(sum(pd.to_datetime(frame["entry_execution_date"], errors="coerce").gt(cutoff).sum() for frame in ledgers.values())),
            "control_mcap_unresolved_count": unresolved,
            "control_mcap_unresolved_reason_counts": unresolved_reason_counts,
            "control_mcap_status_counts": mcap["status"].astype(str).value_counts().to_dict(),
            "control_mcap_unresolved_fail_closed": True,
            "control_mcap_trade_entry_pass": True,
            "permanent_exclusion_trade_leakage_count": total_trade_leaks,
            "permanent_exclusion_trade_leakage_by_strategy": trade_leaks,
            "permanent_exclusion_signal_audit_leakage_count": total_signal_leaks,
            "permanent_exclusion_signal_audit_leakage_by_strategy": signal_leaks,
            "permanent_exclusion_mcap_audit_leakage_count": mcap_leaks,
            "network_calls": network_calls,
            "processed_ticker_count_each_strategy": pre["p3_2_unique_ticker_count"],
            "identity_key_count": pre["p3_2_window_pit_identity_key_count"],
            "identity_segment_count": pre["p3_2_window_pit_segment_count"],
            "candidate_audits": audit_checks,
            "trade_file_hashes": trade_hashes,
            "price_partition_count": int(len(price_audit)),
            "price_partition_hash_metadata_checks_pass": bool(price_audit.empty or (
                price_audit["metadata_row_count_matches"].astype(bool).all()
                and price_audit["metadata_date_range_matches"].astype(bool).all()
            )),
        }
        require(checks["worker_error_count"] == 0 and all(value == WORKERS for value in worker_counts.values()), "STRATEGY_WORKER_COMPLETION_INTEGRITY_FAILURE")
        require(checks["same_universe_count_match"], "STRATEGY_COMMON_UNIVERSE_PROCESSING_MISMATCH")
        require(checks["candidate_signal_parity"] and checks["ma60_filter_check"] and checks["alignment_filter_check"], "CANDIDATE_SIGNAL_OR_FILTER_INTEGRITY_FAILURE")
        require(checks["price_partition_hash_metadata_checks_pass"], "PRICE_PARTITION_HASH_METADATA_CHECK_FAILED")
        require(checks["duplicate_trade_key_count"] == 0, "DUPLICATE_TRADE_KEY")
        require(checks["post_cutoff_entry_count"] == 0 and checks["post_cutoff_entry_execution_count"] == 0, "POST_CUTOFF_ENTRY")
        require(total_trade_leaks == 0 and total_signal_leaks == 0 and mcap_leaks == 0, "PERMANENT_EXCLUSION_LEAKAGE")

        if unresolved:
            FINAL_TOKEN = CHECK_TOKEN
            p2.FINAL_TOKEN = FINAL_TOKEN
        final_status = "PASS" if FINAL_TOKEN.endswith("_PASS") else "CHECK_REQUIRED"
        elapsed_seconds = time.perf_counter() - started

        STAGE = "COMPRESS_AND_FINALIZE"
        compressed = []
        for filename in (
            "p3_2_control_pit_mcap_audit.csv",
            "p3_2_ma60_signal_audit.csv",
            "p3_2_alignment_signal_audit.csv",
            "p3_2_price_store_audit.csv",
        ):
            compressed.append(p2.compress_verified(OUT / filename).name)

        execution.update({
            "status": final_status,
            "final_token": FINAL_TOKEN,
            "worker_count": WORKERS,
            "worker_errors": [],
            "eligible_survivor_identity_count": pre["eligible_survivor_identity_count"],
            "identity_key_count": pre["p3_2_window_pit_identity_key_count"],
            "identity_segment_count": pre["p3_2_window_pit_segment_count"],
            "processed_ticker_count_each_strategy": pre["p3_2_unique_ticker_count"],
            "strategy_trade_counts": {name: int(len(frame)) for name, frame in ledgers.items()},
            "progressed_counts_authoritative": {str(row["strategy"]): int(row["progressed_count"]) for row in metrics},
            "checks": checks,
            "compressed_verified_audits": compressed,
            "elapsed_seconds": time.perf_counter() - started,
        })
        write_json(OUT / "p3_2_execution_audit.json", execution)
        (OUT / "report.md").write_text(
            markdown_report(metric_frame, deltas, exits, checks, pre, thresholds, frequency, elapsed_seconds),
            encoding="utf-8",
        )

        provenance = {
            "status": final_status,
            "final_token": FINAL_TOKEN,
            "work_id": WORK_ID,
            "scope": "P3-2 single-window trade-level simple backtest only",
            "window": WINDOW,
            "worker_count": WORKERS,
            "network_calls": network_calls,
            "result_reuse": pre["result_reuse"],
            "authority": {
                "frozen_pit_sha256": pre["frozen_pit_sha256"],
                "frozen_calendar_sha256": pre["frozen_calendar_sha256"],
                "frozen_manifest_sha256": pre["frozen_manifest_sha256"],
                "survivor_identity_roster_sha256": pre["survivor_identity_roster_sha256"],
                "survivor_identity_roster_count": pre["survivor_identity_roster_count"],
                "permanent_exclusion_registry_count": pre["permanent_exclusion_registry_count"],
                "survivor_permanent_exclusion_overlap_count": pre["survivor_permanent_exclusion_overlap_count"],
                "eligible_survivor_identity_count": pre["eligible_survivor_identity_count"],
                "p3_2_window_pit_identity_key_count": pre["p3_2_window_pit_identity_key_count"],
                "p3_2_window_pit_segment_count": pre["p3_2_window_pit_segment_count"],
            },
            "source_hashes": pre["input_source_hashes"],
            "execution_script_sha256": sha256(Path(__file__)),
            "adjusted_price_store_partition_hashes": price_audit[[column for column in (
                "ticker", "relative_path", "sha256", "metadata_relative_path", "metadata_sha256",
                "source_authority_id", "source_semantics", "authority_type", "row_count", "actual_date_min", "actual_date_max"
            ) if column in price_audit.columns]].to_dict("records"),
            "exact_raw_mcap_partition_audit": {
                "audit_rows": int(len(mcap)),
                "unresolved_rows": unresolved,
                "statuses": mcap["status"].astype(str).value_counts().to_dict(),
                "partition_sha256_values": sorted(set(mcap["partition_file_sha256"].dropna().astype(str))) if "partition_file_sha256" in mcap else [],
                "gate_load_snapshot_hash_validation": "PASS",
            },
            "cost_contract": pre["cost_contract"],
            "metrics_progressed_basis": "entry execution <= event <= exit signal for REALIZED; <= effective cutoff for OPEN_AT_CUTOFF; <= settlement date for LIFECYCLE_SETTLED",
            "no_portfolio_mdd": True,
            "integrity": checks,
            "artifact_sha256": {
                path.name: sha256(path)
                for path in sorted(OUT.iterdir())
                if path.is_file() and path.name not in {"p3_2_provenance.json", "artifact_manifest.json"}
            },
            "elapsed_seconds": elapsed_seconds,
        }
        write_json(OUT / "p3_2_provenance.json", provenance)
        manifest_files = {
            path.name: sha256(path)
            for path in sorted(OUT.iterdir())
            if path.is_file() and path.name != "artifact_manifest.json"
        }
        write_json(OUT / "artifact_manifest.json", {"status": final_status, "final_token": FINAL_TOKEN, "files": manifest_files})
        manifest = json.loads((OUT / "artifact_manifest.json").read_text(encoding="utf-8"))
        require(all(sha256(OUT / name) == digest for name, digest in manifest["files"].items()), "ARTIFACT_MANIFEST_HASH_MISMATCH")
        return 0 if final_status == "PASS" else 2
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
