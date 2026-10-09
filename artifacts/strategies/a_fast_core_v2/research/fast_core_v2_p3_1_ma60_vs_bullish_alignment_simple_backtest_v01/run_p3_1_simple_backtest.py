#!/usr/bin/env python3
"""Fresh, offline P3-1 trade-level replay using exact permanent identity exclusions."""

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
spec = importlib.util.spec_from_file_location("p3_1_certified_simple_runner_utilities", BASE_RUNNER_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("P2_2_RUNNER_IMPORT_FAILED")
p2 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = p2
spec.loader.exec_module(p2)

WORK_ID = "FAST_CORE_V2_P3_1_MA60_VS_BULLISH_ALIGNMENT_SIMPLE_BACKTEST_V01"
FINAL_TOKEN = WORK_ID + "_PASS"
CHECK_TOKEN = WORK_ID + "_CHECK_REQUIRED"
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
        ("p3_1_execution_script", Path(__file__)),
    ):
        require(path.is_file(), f"INPUT_MISSING:{name}")
        hashes[name] = {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": sha256(path),
            "tracked_at_start": name != "p3_1_execution_script",
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
        require(context["effective_start"] == WINDOW["effective_start"], "P3_1_START_MISMATCH")
        require(context["effective_end"] == WINDOW["effective_end"], "P3_1_CUTOFF_MISMATCH")
        require(context["execution_support"] == WINDOW["execution_support"], "P3_1_SUPPORT_MISMATCH")
        require(context["survivor_identity_count"] == len(eligible), "P3_1_SURVIVOR_CONTEXT_MISMATCH")
        require(context["common_pit_segment_count"] == sum(map(len, run.segments_by_ticker.values())), "P3_1_SEGMENT_CONTEXT_MISMATCH")
        scoped_pairs = {
            (segment.ticker, segment.isu_cd.strip().upper())
            for rows in run.segments_by_ticker.values()
            for segment in rows
        }
        require(not (scoped_pairs & policy_pairs), "P3_1_WINDOW_PERMANENT_EXCLUSION_LEAK")
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
    identity_audit["p3_1_window_pit_overlap"] = [
        (ticker, isu_cd, str(market).strip().upper()) in window_keys
        for ticker, isu_cd, market in zip(identity_audit["ticker"], identity_audit["isu_cd"], identity_audit["market"])
    ]
    identity_audit["included_in_p3_1"] = (
        identity_audit["is_frozen_survivor"]
        & ~identity_audit["current_permanent_exclusion"]
        & identity_audit["p3_1_window_pit_overlap"]
    )
    for field in ("failure_class", "approval_scope", "approved_date", "reason"):
        identity_audit["permanent_exclusion_" + field] = [
            policy_by_identity.get((ticker, isu_cd), {}).get(field)
            for ticker, isu_cd in zip(identity_audit["ticker"], identity_audit["isu_cd"])
        ]
    require(int(identity_audit["included_in_p3_1"].sum()) == len(identity_keys), "IDENTITY_AUTHORITY_AUDIT_CONTEXT_COUNT_MISMATCH")

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
        "p3_1_window_pit_identity_key_count": len(identity_keys),
        "p3_1_window_pit_segment_count": sum(map(len, run.segments_by_ticker.values())),
        "p3_1_unique_ticker_count": context["unique_ticker_count"],
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


def markdown_report(metrics: pd.DataFrame, deltas: pd.DataFrame, exits: pd.DataFrame,
                    checks: dict[str, Any], pre: dict[str, Any], thresholds: pd.DataFrame) -> str:
    def f(value: Any, digits: int = 2) -> str:
        return "—" if value is None or pd.isna(value) else f"{float(value):.{digits}f}"
    lines = [
        "# FAST Core V2 P3-1 MA60 vs Bullish Alignment 단순 백테스트",
        "",
        "| 레벨 | 개수 | 내용 |",
        "|---|---:|---|",
        "| CRITICAL | 0 | 필수 무결성 검증 오류 없음 |",
        "| MAJOR | 0 | 결과 범위 안에서 확인된 중대 이슈 없음 |",
        "| MINOR | 1 | 거래 단위 결과이며 포트폴리오 MDD는 계산하지 않음 |",
        "",
        f"- 최종 판정: {FINAL_TOKEN}",
        "- 실제 거래 기간: 2022-01-03~2025-05-30. Execution support: 2025-06-02. Cutoff 이후 신규 진입은 허용하지 않았어.",
        f"- Frozen survivor roster {pre['survivor_identity_roster_count']:,}개에서 current permanent exclusion authority {pre['permanent_exclusion_registry_count']} exact pair를 적용했어. Roster와 겹친 {pre['survivor_permanent_exclusion_overlap_count']}개를 전략 재생 전에 제외해 공통 eligible roster {pre['eligible_survivor_identity_count']:,}개를 만들었어.",
        f"- P3-1 PIT 범위는 identity key {pre['p3_1_window_pit_identity_key_count']:,}개, segment {pre['p3_1_window_pit_segment_count']:,}개, ticker {pre['p3_1_unique_ticker_count']:,}개야. Exact (ticker, ISU) 매칭을 사용했고 ticker-only 매칭은 사용하지 않았어.",
        "- CONTROL, MA60 fail-closed, Bullish Alignment는 같은 filtered roster, PIT, calendar, lifecycle, cutoff, Repository V2 가격 및 exact-date MKTCAP 계약을 사용했어.",
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
        f"- 정확한 MKTCAP audit unresolved {checks['control_mcap_unresolved_count']}; CONTROL trade 진입 MKTCAP PASS {checks['control_mcap_trade_entry_pass']}.",
        f"- Permanent exclusion leakage: trade {checks['permanent_exclusion_trade_leakage_count']}, signal audit {checks['permanent_exclusion_signal_audit_leakage_count']}, MKTCAP audit {checks['permanent_exclusion_mcap_audit_leakage_count']}.",
        f"- MA60 공식·fail-closed {checks['ma60_filter_check']}; Alignment signal_day_close > MA20 > MA60·fail-closed {checks['alignment_filter_check']}; net terminal 재계산 불일치 {checks['net_terminal_recompute_mismatch_count']}.",
        f"- Frozen PIT SHA-256 {pre['frozen_pit_sha256']}; calendar {pre['frozen_calendar_sha256']}; survivor roster {pre['survivor_identity_roster_sha256']}; exclusion registry {pre['input_source_hashes']['permanent_identity_exclusion_registry']['sha256']}.",
        "- 이 문서는 P3-1 한 기간 안의 세 전략 비교만 담아. 다른 기간 성과와 교차 기간 비교, 포트폴리오 MDD, 공식 채택 판정은 포함하지 않아.",
        "",
        "## 산출물",
        "",
        f"- {OUT.relative_to(ROOT).as_posix()}/에 preflight, identity authority audit, 세 trade ledger, signal/MKTCAP/price audit, execution audit, PROGRESSED reconciliation, metrics, CONTROL delta, provenance, artifact manifest가 있어.",
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
                "eligible_survivor_identity_count": pre["eligible_survivor_identity_count"],
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

        mcap = pd.read_csv(OUT / "p3_1_control_pit_mcap_audit.csv", dtype={"ticker": str, "identity": str})
        unresolved = int(mcap.get("status", pd.Series(dtype=str)).astype(str).eq("UNRESOLVED").sum())
        require(unresolved == 0, f"CONTROL_MCAP_UNRESOLVED_ROWS:{unresolved}")
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
        write_frame(OUT / "p3_1_strategy_metrics.csv", metric_frame)
        write_frame(OUT / "p3_1_strategy_metrics_reconciled.csv", metric_frame)
        write_frame(OUT / "p3_1_deltas_vs_control.csv", deltas)
        write_frame(OUT / "p3_1_large_outcomes.csv", thresholds)
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
            "control_mcap_unresolved_count": unresolved,
            "control_mcap_trade_entry_pass": True,
            "permanent_exclusion_trade_leakage_count": total_trade_leaks,
            "permanent_exclusion_trade_leakage_by_strategy": trade_leaks,
            "permanent_exclusion_signal_audit_leakage_count": total_signal_leaks,
            "permanent_exclusion_signal_audit_leakage_by_strategy": signal_leaks,
            "permanent_exclusion_mcap_audit_leakage_count": mcap_leaks,
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
        require(total_trade_leaks == 0 and total_signal_leaks == 0 and mcap_leaks == 0, "PERMANENT_EXCLUSION_LEAKAGE")

        STAGE = "COMPRESS_AND_FINALIZE"
        compressed = []
        for filename in (
            "p3_1_control_pit_mcap_audit.csv",
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
            "eligible_survivor_identity_count": pre["eligible_survivor_identity_count"],
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
        (OUT / "report.md").write_text(markdown_report(metric_frame, deltas, exits, checks, pre, thresholds), encoding="utf-8")

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
                "survivor_identity_roster_sha256": pre["survivor_identity_roster_sha256"],
                "survivor_identity_roster_count": pre["survivor_identity_roster_count"],
                "permanent_exclusion_registry_count": pre["permanent_exclusion_registry_count"],
                "survivor_permanent_exclusion_overlap_count": pre["survivor_permanent_exclusion_overlap_count"],
                "eligible_survivor_identity_count": pre["eligible_survivor_identity_count"],
                "p3_1_window_pit_identity_key_count": pre["p3_1_window_pit_identity_key_count"],
                "p3_1_window_pit_segment_count": pre["p3_1_window_pit_segment_count"],
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
