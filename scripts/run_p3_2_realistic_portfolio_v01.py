#!/usr/bin/env python3
"""Run the certified P3-2 strategy pair through the realistic portfolio engine."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import inspect
import json
from pathlib import Path
import resource
import subprocess
import sys
import threading
import time
from typing import Any, Mapping, Sequence

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trend_scanner.data.rolling_market_data_refresh import (
    load_rolling_authority,
    validate_merged_authority_coherence,
)
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.universe.permanent_identity_exclusions import PERMANENT_IDENTITY_EXCLUSIONS
import scripts.run_fastcore_neg40_weak_protect_p2_1 as strategy
import scripts.run_p2_1_realistic_portfolio_v01 as portfolio
import scripts.run_p2_2_realistic_portfolio_v01 as engine


RUN_ID = "run_20260926_realistic_mcap1t_worker10_v01"
OUT_DIR = ROOT / "artifacts/backtests/p3_2_neg40_weak_protect_v01" / RUN_ID
CERTIFIED_P3_2_DIR = (
    ROOT / "artifacts/backtests/p3_2_neg40_weak_protect_v01"
    / "run_20260925_p3_2_worker10_corrective_v01"
)
ROLLING_DIR = ROOT / "data/market/rolling_authority"
P2_1_SUMMARY = (
    ROOT / "artifacts/backtests/p2_1_neg40_weak_protect_v01"
    / "run_20260926_realistic_mcap1t_worker10_v01/summary.json"
)
P2_2_SUMMARY = (
    ROOT / "artifacts/backtests/p2_2_neg40_weak_protect_v01"
    / "run_20260926_realistic_mcap1t_worker10_v01/summary.json"
)
WORKERS = 10
SAMPLE_TICKERS = 40
CALENDAR_START = "2022-01-01"
CALENDAR_END = "2026-08-31"

# P2's frozen cost model has a historical tax schedule through 2025. Reuse the
# already verified 2026 schedule from the official validator, as P2-2 does.
if not any(row[0] == "2026-01-01" for row in portfolio.SELL_TAX_SCHEDULE):
    portfolio.SELL_TAX_SCHEDULE = (
        *portfolio.SELL_TAX_SCHEDULE,
        ("2026-01-01", "2026-12-31", 0.0020),
    )

_LAST_AUTHORITY: dict[str, Any] = {}

ENGINE_OUTPUTS = (
    "execution_contract.json",
    "survivor_universe_audit.csv",
    "pit_mcap_audit.csv",
    "control_strategy_trades.csv",
    "candidate_strategy_trades.csv",
    "p2_2_soft_events.csv",
    "matching_audit.json",
    "preflight_pit_partition_coverage.json",
    "control_portfolio_events.csv",
    "candidate_portfolio_events.csv",
    "control_daily_equity.csv",
    "candidate_daily_equity.csv",
    "valuation_carry_audit.csv",
    "skipped_entries.csv",
    "hidden_position_cap_audit.json",
    "summary.json",
    "summary.csv",
    "comparison_report.md",
)


def _json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def _require_synchronized_main() -> str:
    head = _head()
    remote = subprocess.check_output(
        ["git", "rev-parse", "origin/main"], cwd=ROOT, text=True
    ).strip()
    if head != remote:
        raise RuntimeError(f"HEAD_ORIGIN_MAIN_MISMATCH:{head}:{remote}")
    return head


def _validate_authoritative_contract() -> dict[str, Any]:
    cert_path = CERTIFIED_P3_2_DIR / "p3_2_summary.json"
    cert = json.loads(cert_path.read_text(encoding="utf-8"))
    expected_window = {
        "calendar_start": "2022-01-01",
        "calendar_end": "2026-08-31",
        "effective_start": "2022-01-03",
        "effective_end": "2026-08-31",
        "execution_support": "2026-09-01",
    }
    if cert.get("status") != "COMPLETE" or cert.get("window_id") != "P3-2":
        raise RuntimeError("P3_2_AUTHORITATIVE_CERTIFICATION_NOT_COMPLETE")
    if cert.get("window") != expected_window:
        raise RuntimeError("P3_2_AUTHORITATIVE_WINDOW_CONTRACT_MISMATCH")
    if cert.get("strategy_ids") != {
        "control": strategy.V2_STRATEGY_ID,
        "candidate": strategy.CANDIDATE_STRATEGY_ID,
    }:
        raise RuntimeError("P3_2_AUTHORITATIVE_STRATEGY_IDS_MISMATCH")
    approved = {
        (str(item.get("ticker", "")).zfill(6), str(item.get("isu_cd", "")).upper())
        for item in cert.get("population", {})
        .get("permanent_identity_exclusion_recertification", {})
        .get("excluded_identities", [])
    }
    missing = sorted(approved - set(PERMANENT_IDENTITY_EXCLUSIONS))
    if missing:
        raise RuntimeError(f"P3_2_CERTIFIED_EXCLUSIONS_MISSING_FROM_CURRENT_REGISTRY:{missing}")
    return {
        "status": "PASS",
        "window": expected_window,
        "strategy_ids": cert["strategy_ids"],
        "certification_summary_sha256": _sha256(cert_path),
        "certified_permanent_exclusion_count": len(approved),
        "current_registry_policy_version": "permanent_identity_exclusions_v01",
        "certified_exclusion_keys_present_in_registry": True,
    }


def _load_survivor_context(*, worker_count: int):
    global _LAST_AUTHORITY
    certified_contract = _validate_authoritative_contract()
    manifest = load_rolling_authority(ROLLING_DIR)
    pit_payload, _calendar_payload = validate_merged_authority_coherence(manifest, ROLLING_DIR)
    as_of = str(pit_payload.get("target_as_of", ""))
    if not as_of or as_of != manifest.merged_pit_frontier:
        raise RuntimeError("LATEST_DAILY_UPDATE_PIT_FRONTIER_MISMATCH")

    gate = engine.portfolio.ExactRawMcapGate(ROOT, pit_payload)
    run = strategy._load_context("P3-2")
    population_preflight = strategy._p3_1_population_preflight(run)
    if population_preflight.get("status") != "PASS":
        raise RuntimeError(
            "P3_2_POPULATION_PREFLIGHT_FAILED:" + json.dumps(population_preflight, ensure_ascii=False)
        )
    original = [segment for group in run.segments_by_ticker.values() for segment in group]
    selected = [
        segment
        for segment in original
        if (segment.ticker, segment.isu_cd.upper(), segment.market.upper()) in gate.active_identity_keys
    ]
    selected_keys = {segment.key for segment in selected}
    grouped: dict[str, list[strategy.IdentitySegment]] = {}
    for segment in selected:
        grouped.setdefault(segment.ticker, []).append(segment)
    filtered = replace(
        run,
        segments_by_ticker={
            ticker: tuple(sorted(rows, key=lambda row: (row.effective_from, row.effective_to, row.isu_cd)))
            for ticker, rows in sorted(grouped.items())
        },
        entry_signal_gate=gate,
    )

    universe_rows = []
    for segment in original:
        survives = segment.key in selected_keys
        universe_rows.append(
            {
                "ticker": segment.ticker,
                "isu_cd": segment.isu_cd,
                "market": segment.market,
                "effective_from": segment.effective_from.strftime("%Y-%m-%d"),
                "effective_to": segment.effective_to.strftime("%Y-%m-%d"),
                "latest_daily_update_as_of": as_of,
                "status": "SURVIVOR_COMMON_IDENTITY" if survives else "EXCLUDED_NOT_CURRENT_COMMON_IDENTITY",
                "reason": "EXACT_TICKER_ISU_MARKET_ACTIVE_AT_LATEST_DAILY_UPDATE"
                if survives
                else "IDENTITY_NOT_COMMON_AT_LATEST_DAILY_UPDATE",
            }
        )
    seen_exclusions: set[tuple[str, str]] = set()
    for item in run.permanent_identity_exclusions:
        key = (str(item.get("ticker", "")).zfill(6), str(item.get("isu_cd", "")).upper())
        if key in seen_exclusions:
            continue
        seen_exclusions.add(key)
        universe_rows.append(
            {
                "ticker": key[0],
                "isu_cd": key[1],
                "market": item.get("market"),
                "effective_from": None,
                "effective_to": None,
                "latest_daily_update_as_of": as_of,
                "status": "EXCLUDED_EXISTING_PERMANENT_IDENTITY_POLICY",
                "reason": item.get("reason"),
            }
        )
    authority = {
        "latest_daily_update_as_of": as_of,
        "latest_daily_update_source_frontier": pit_payload.get("source_basic_info_frontier"),
        "rolling_manifest_certified_through": manifest.certified_through,
        "rolling_manifest_sha256": manifest.manifest_sha256,
        "merged_pit_digest": manifest.merged_pit_digest,
        "merged_pit_file_sha256": _sha256(ROLLING_DIR / "merged_pit_intervals.json"),
        "effective_pit_file_sha256": _sha256(run.authority.pit_path),
        "p3_2_population_preflight": population_preflight,
        "p3_2_authoritative_contract": certified_contract,
        "p3_2_certification_summary_sha256": _sha256(CERTIFIED_P3_2_DIR / "p3_2_summary.json"),
        "raw_market_cap_store": "data/market/raw/krx_stocks/v01",
        "raw_market_cap_threshold_krw": portfolio.MARKET_CAP_THRESHOLD,
        "worker_count": worker_count,
        "survivor_filter": "latest_daily_update COMMON by exact ticker + ISU + market identity",
        "permanent_identity_exclusions": list(run.permanent_identity_exclusions),
        "network_calls": 0,
    }
    _LAST_AUTHORITY = authority
    return filtered, gate, authority, pd.DataFrame(universe_rows), original


def _run_pool(run, gate, tickers: Sequence[str], *, workers: int):
    started = time.perf_counter()
    outcomes: list[dict[str, Any]] = []
    errors: list[str] = []

    def process(ticker: str):
        result = strategy._process_ticker(ticker, run)
        result["worker_thread"] = threading.current_thread().name
        return result

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="p3-2-worker") as pool:
        futures = {pool.submit(process, ticker): ticker for ticker in tickers}
        for completed, future in enumerate(as_completed(futures), start=1):
            ticker = futures[future]
            try:
                outcomes.append(future.result())
            except Exception as exc:
                errors.append(f"{ticker}: {type(exc).__name__}: {exc}")
            if completed % 25 == 0 or completed == len(tickers):
                print(
                    f"P3-2 workers progress {completed}/{len(tickers)}; "
                    f"trades={sum(len(item['control_rows']) for item in outcomes)}; "
                    f"PIT candidates={len(gate.audit_frame())}; "
                    f"elapsed={time.perf_counter() - started:.1f}s; errors={len(errors)}",
                    flush=True,
                )
    return outcomes, errors, time.perf_counter() - started


def _memory_snapshot() -> dict[str, Any]:
    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    snapshot: dict[str, Any] = {
        "process_peak_rss_reported": peak,
        "process_peak_rss_units": "bytes on macOS; KiB on Linux",
    }
    try:
        import psutil

        process = psutil.Process()
        snapshot["process_rss_bytes_at_snapshot"] = int(process.memory_info().rss)
        vm = psutil.virtual_memory()
        snapshot["system_memory"] = {
            "total_bytes": int(vm.total),
            "available_bytes": int(vm.available),
            "used_percent": float(vm.percent),
        }
    except ImportError:
        snapshot["system_memory"] = "psutil unavailable; process peak RSS recorded"
    return snapshot


def _adapt_sample(sample: dict[str, Any]) -> dict[str, Any]:
    sample["window_id"] = "P3-2"
    sample["scope"] = "P3-2 only; realistic portfolio preflight"
    sample["p3_2_window"] = sample.pop("p2_2_window", {})
    sample.pop("prior_unfiltered_p2_2_reference_seconds", None)
    sample["p3_2_population_preflight"] = _LAST_AUTHORITY.get("p3_2_population_preflight")
    sample["memory"] = _memory_snapshot()
    replay_source = inspect.getsource(portfolio._portfolio_replay)
    sample["no_hidden_position_cap_preflight"] = {
        "status": "PASS" if "SLOT_CAP" not in replay_source else "CHECK_REQUIRED",
        "portfolio_engine_source_has_slot_cap_branch": "SLOT_CAP" in replay_source,
        "position_cap_configured": None,
        "position_cap_applied": False,
    }
    sample["worker_count"] = WORKERS
    sample["sample_ticker_count"] = SAMPLE_TICKERS
    return sample


def _check_engine_freshness() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    existing = [path.name for path in OUT_DIR.iterdir()]
    if existing:
        raise RuntimeError("REFUSING_TO_OVERWRITE_P3_2_RUN_DIRECTORY:" + ",".join(sorted(existing)))


def _configure_engine() -> None:
    engine.RUN_ID = RUN_ID
    engine.OUT_DIR = OUT_DIR
    engine.CALENDAR_START = CALENDAR_START
    engine.CALENDAR_END = CALENDAR_END
    engine.WORKERS = WORKERS
    engine.SAMPLE_TICKERS = SAMPLE_TICKERS
    engine.OUTPUTS = ENGINE_OUTPUTS
    engine.P2_1_SUMMARY = P2_1_SUMMARY
    engine._load_survivor_context = _load_survivor_context
    engine._run_pool = _run_pool


def _sample() -> dict[str, Any]:
    _require_synchronized_main()
    _check_engine_freshness()
    _configure_engine()
    sample = engine._sample(workers=WORKERS, sample_tickers=SAMPLE_TICKERS)
    sample = _adapt_sample(sample)
    sample_path = OUT_DIR / "sample_benchmark.json"
    _json_write(sample_path, sample)
    _json_write(OUT_DIR / "preflight_summary.json", sample)
    return sample


def _event_trade_ledger(path: Path, output: Path) -> None:
    events = pd.read_csv(path)
    trades = events.loc[events["event_type"].astype(str).isin({"ENTRY", "EXIT"})].copy()
    trades.to_csv(output, index=False)


def _paired_identity_audit(control: pd.DataFrame, candidate: pd.DataFrame) -> pd.DataFrame:
    columns = ["pair_id", "trade_id", "ticker", "isu_cd", "market", "entry_signal_date", "entry_execution_date"]
    left = control[[column for column in columns if column in control]].rename(
        columns={column: f"control_{column}" for column in columns if column != "pair_id"}
    )
    right = candidate[[column for column in columns if column in candidate]].rename(
        columns={column: f"candidate_{column}" for column in columns if column != "pair_id"}
    )
    paired = left.merge(right, on="pair_id", how="outer", validate="one_to_one", indicator=True)
    paired["identity_and_entry_match"] = (
        paired["_merge"].eq("both")
        & paired.get("control_trade_id", pd.Series(index=paired.index, dtype=object)).eq(
            paired.get("candidate_trade_id", pd.Series(index=paired.index, dtype=object))
        )
        & paired.get("control_ticker", pd.Series(index=paired.index, dtype=object)).eq(
            paired.get("candidate_ticker", pd.Series(index=paired.index, dtype=object))
        )
        & paired.get("control_entry_signal_date", pd.Series(index=paired.index, dtype=object)).eq(
            paired.get("candidate_entry_signal_date", pd.Series(index=paired.index, dtype=object))
        )
        & paired.get("control_entry_execution_date", pd.Series(index=paired.index, dtype=object)).eq(
            paired.get("candidate_entry_execution_date", pd.Series(index=paired.index, dtype=object))
        )
    )
    return paired.drop(columns="_merge")


def _metric_value(metrics: Mapping[str, Any], key: str, events: pd.DataFrame | None = None) -> Any:
    if key == "buy_fees_krw" and events is not None:
        return float(events.loc[events["event_type"].eq("ENTRY"), "commission"].sum())
    if key == "sell_fees_krw" and events is not None:
        return float(events.loc[events["event_type"].eq("EXIT"), "commission"].sum())
    return metrics.get(key)


def _comparison_report(summary: Mapping[str, Any], p21: Mapping[str, Any], p22: Mapping[str, Any]) -> str:
    control = summary["portfolio"]["control"]
    candidate = summary["portfolio"]["candidate"]
    delta = summary["portfolio"]["candidate_minus_control"]
    labels = (
        ("final_equity", "최종 자산 (KRW)"),
        ("cumulative_return_pct", "누적수익률 (%)"),
        ("CAGR_pct", "CAGR (%)"),
        ("mdd_pct", "MDD (%)"),
        ("trade_count", "체결 진입 거래 수"),
        ("win_rate_pct", "실현 승률 (%)"),
        ("average_holding_trading_days", "평균 보유 거래일"),
        ("median_holding_trading_days", "중앙 보유 거래일"),
        ("average_concurrent_positions", "평균 동시 보유"),
        ("maximum_concurrent_positions", "최대 동시 보유"),
        ("average_capital_utilization_pct", "평균 자본 사용률 (%)"),
        ("average_cash_ratio_pct", "평균 현금 비율 (%)"),
        ("turnover_multiple", "회전율 (x)"),
        ("total_commissions_krw", "총 수수료 (KRW)"),
        ("total_buy_commissions_krw", "매수 수수료 (KRW)"),
        ("total_sell_commissions_krw", "매도 수수료 (KRW)"),
        ("total_sell_tax_krw", "매도 거래세 (KRW)"),
        ("slippage_impact_krw", "슬리피지 영향 (KRW)"),
        ("cash_shortage_skipped_entries", "현금 부족 진입 skip"),
        ("open_at_effective_cutoff_count", "cutoff 미청산 보유 수"),
        ("realized_return_le_neg_30_count", "실현 ≤ -30%"),
        ("realized_return_le_neg_40_count", "실현 ≤ -40%"),
        ("realized_return_le_neg_50_count", "실현 ≤ -50%"),
        ("realized_return_le_neg_60_count", "실현 ≤ -60%"),
        ("realized_return_ge_pos_50_count", "실현 ≥ +50%"),
        ("realized_return_ge_pos_100_count", "실현 ≥ +100%"),
    )

    def display(value: Any) -> str:
        if value is None:
            return "—"
        if isinstance(value, (int, float)):
            return f"{value:,.4f}" if isinstance(value, float) else f"{value:,}"
        return str(value)

    rows = []
    for key, label in labels:
        left = control.get(key)
        right = candidate.get(key)
        difference = delta.get(key)
        rows.append(f"| {label} | {display(left)} | {display(right)} | {display(difference)} |")
    rows.extend(
        [
            f"| MDD peak / trough / recovery | {control.get('peak_date')} / {control.get('trough_date')} / {control.get('recovery_date')} | {candidate.get('peak_date')} / {candidate.get('trough_date')} / {candidate.get('recovery_date')} | — |",
        ]
    )
    c1 = p21["portfolio"]["candidate"]
    c2 = p22["portfolio"]["candidate"]
    c3 = candidate
    three_window = "\n".join(
        f"| {label} | {display(c1.get(key))} | {display(c2.get(key))} | {display(c3.get(key))} |"
        for key, label in (("cumulative_return_pct", "누적수익률 (%)"), ("CAGR_pct", "CAGR (%)"), ("mdd_pct", "MDD (%)"))
    )
    return f"""# P3-2 현실적 포트폴리오 백테스트

판정: `{summary['status']}`

기간: P3-2 effective {summary['window']['effective_start']} ~ {summary['window']['effective_end']} (execution support {summary['window']['execution_support']})

최신 Daily Update: {summary['universe']['latest_daily_update_as_of']}

전략: CONTROL `{summary['strategy_ids']['control']}` / Candidate `{summary['strategy_ids']['candidate']}`. Candidate는 공식 V2.1로 승격하지 않았어.

## CONTROL vs Candidate

| 지표 | CONTROL | Candidate | Candidate − CONTROL |
|---|---:|---:|---:|
{chr(10).join(rows)}

매수/매도 수수료는 portfolio event ledger의 진입/청산별 commission 합계로 재검산 가능해. 포트폴리오 거래 원장과 일별 equity는 별도 CSV로 저장했어.

## 세 window의 Candidate 결과

| 지표 | P2-1 | P2-2 | P3-2 |
|---|---:|---:|---:|
{three_window}

세 window는 서로 다른 기간·모집단 조건의 독립 결과라서 차이를 기간 효과 하나로만 단정하지 않아.

## 실행 및 검증

- 파이프라인: PIT COMMON → latest Daily Update COMMON identity survivor → entry signal date의 exact raw KRX `MKTCAP >= 1조원` → 나머지에만 frozen FAST 신호 평가 → deterministic sequential portfolio replay.
- 기준 시점 이전/이후의 시총 대체값, 인접일, 보간, 전략 ledger 사후 필터는 사용하지 않았어. unresolved exact-cap signal은 인증 불가 조건이야.
- 초기 자본 2억원, 종목별 고정 매수예산 500만원, 종목 수 cap 없음, 현금 부족 시 전량 진입 skip, 기존 수수료/슬리피지/거래세와 valuation-only adjusted-close carry 계약을 적용했어.
- worker {summary['execution']['observed_worker_threads']}/{summary['execution']['worker_count']}; 전략 평가 {summary['execution']['strategy_evaluation_wall_seconds']:.1f}s, 순차 포트폴리오 재생 {summary['execution']['portfolio_event_replay_wall_seconds']:.1f}s, 총 {summary['execution']['total_wall_seconds']:.1f}s; peak RSS {summary['execution']['memory']['process_peak_rss_reported']} ({summary['execution']['memory']['process_peak_rss_units']}).
- `validation`의 entry parity, exact MKTCAP, valuation carry, unresolved, daily-equity completeness, cash conservation, no-hidden-cap 검증을 모두 만족할 때만 인증 판정이야.
"""


def _certified(summary: Mapping[str, Any], hidden_audit: Mapping[str, Any]) -> bool:
    validation = summary["validation"]
    return bool(
        validation.get("matching_pass")
        and validation.get("mcap_unresolved_count") == 0
        and validation.get("portfolio_unresolved_count") == 0
        and validation.get("unclassified_valuation_carry_count") == 0
        and validation.get("daily_equity_complete")
        and validation.get("control_cash_conservation")
        and validation.get("candidate_cash_conservation")
        and hidden_audit.get("slot_cap_would_block_count") == 0
        and not hidden_audit.get("portfolio_engine_source_has_slot_cap_branch", True)
        and summary.get("raw_pit_partition_coverage", {}).get("all_expected_market_dates_complete")
    )


def _full_run() -> dict[str, Any]:
    head = _require_synchronized_main()
    _configure_engine()
    sample_path = OUT_DIR / "sample_benchmark.json"
    if not sample_path.is_file():
        raise RuntimeError("P3_2_FULL_RUN_REQUIRES_SAME_PATH_40_TICKER_PREFLIGHT")
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    if (
        sample.get("status") != "COMPLETE"
        or sample.get("window_id") != "P3-2"
        or sample.get("worker_count") != WORKERS
        or sample.get("worker_threads", {}).get("observed_worker_threads") != WORKERS
        or sample.get("sample_ticker_count") != SAMPLE_TICKERS
        or sample.get("sample_mcap_unresolved_count") != 0
        or sample.get("p3_2_population_preflight", {}).get("status") != "PASS"
        or sample.get("no_hidden_position_cap_preflight", {}).get("status") != "PASS"
    ):
        raise RuntimeError("P3_2_FULL_RUN_BLOCKED_BY_PREFLIGHT")
    if P2_1_SUMMARY.is_file() is False or P2_2_SUMMARY.is_file() is False:
        raise RuntimeError("P3_2_THREE_WINDOW_COMPARISON_SUMMARY_MISSING")

    _json_write(
        OUT_DIR / "run_manifest.json",
        {
            "status": "RUNNING",
            "run_id": RUN_ID,
            "window_id": "P3-2",
            "head_at_start": head,
            "runner_sha256": _sha256(Path(__file__).resolve()),
            "p3_2_authority_summary": str(CERTIFIED_P3_2_DIR / "p3_2_summary.json"),
            "p3_2_authority_summary_sha256": _sha256(CERTIFIED_P3_2_DIR / "p3_2_summary.json"),
            "sample_benchmark": str(sample_path.relative_to(ROOT)),
            "workers": WORKERS,
            "scope": "P3-2 only; no other window run",
            "network_calls": 0,
        },
    )
    try:
        summary = engine._full_run(workers=WORKERS)
    except BaseException as exc:
        failure = {
            "status": "FAILED",
            "run_id": RUN_ID,
            "window_id": "P3-2",
            "head_at_start": head,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
        _json_write(OUT_DIR / "full_failure.json", failure)
        manifest = json.loads((OUT_DIR / "run_manifest.json").read_text(encoding="utf-8"))
        manifest.update(failure)
        _json_write(OUT_DIR / "run_manifest.json", manifest)
        raise

    contract_path = OUT_DIR / "execution_contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract.update(
        {
            "schema": "p3_2_realistic_portfolio_execution_contract_v01",
            "scope": "P3-2 only",
            "strategy_entry_contract": "CONTROL and Candidate use identical P3-2 survivor and exact raw PIT MKTCAP-qualified entry universe; only frozen Candidate exit overlay differs",
            "network_calls": 0,
        }
    )
    _json_write(contract_path, contract)

    soft_source = OUT_DIR / "p2_2_soft_events.csv"
    soft_target = OUT_DIR / "p3_2_soft_events.csv"
    if soft_source.is_file():
        soft_source.replace(soft_target)
    for strategy_name in ("control", "candidate"):
        _event_trade_ledger(
            OUT_DIR / f"{strategy_name}_portfolio_events.csv",
            OUT_DIR / f"{strategy_name}_portfolio_trades.csv",
        )

    control = pd.read_csv(OUT_DIR / "control_strategy_trades.csv")
    candidate = pd.read_csv(OUT_DIR / "candidate_strategy_trades.csv")
    identity_audit = _paired_identity_audit(control, candidate)
    identity_audit.to_csv(OUT_DIR / "paired_identity_audit.csv", index=False)
    identity_pass = bool(identity_audit["identity_and_entry_match"].all())
    hidden_path = OUT_DIR / "hidden_position_cap_audit.json"
    hidden_audit = json.loads(hidden_path.read_text(encoding="utf-8"))
    replay_source = inspect.getsource(portfolio._portfolio_replay)
    hidden_audit.update(
        {
            "portfolio_engine_source_has_slot_cap_branch": "SLOT_CAP" in replay_source,
            "position_cap_configured": None,
            "position_cap_applied": False,
            "paired_identity_audit_pass": identity_pass,
            "scope": "P3-2 realistic portfolio replay; no max-position count limit",
        }
    )
    if hidden_audit["portfolio_engine_source_has_slot_cap_branch"]:
        hidden_audit["slot_cap_would_block_count"] = max(1, int(hidden_audit.get("slot_cap_would_block_count", 0)))
    _json_write(hidden_path, hidden_audit)

    p21 = json.loads(P2_1_SUMMARY.read_text(encoding="utf-8"))
    p22 = json.loads(P2_2_SUMMARY.read_text(encoding="utf-8"))
    summary["status"] = (
        "P3_2_REALISTIC_PORTFOLIO_BACKTEST_CERTIFIED"
        if _certified(summary, hidden_audit) and identity_pass
        else "P3_2_REALISTIC_PORTFOLIO_BACKTEST_CHECK_REQUIRED"
    )
    summary["work_id"] = "P3_2_V2_VS_NEG40_WEAK_PROTECT_REALISTIC_PORTFOLIO_V01"
    summary["run_id"] = RUN_ID
    summary["window_id"] = "P3-2"
    summary["head_at_start"] = head
    summary["head_at_finish"] = _head()
    summary["strategy_ids"] = {
        "control": strategy.V2_STRATEGY_ID,
        "candidate": strategy.CANDIDATE_STRATEGY_ID,
    }
    summary["p2_1_comparison"] = {
        "run_id": p21["run_id"],
        "candidate": p21["portfolio"]["candidate"],
    }
    summary["p2_2_comparison"] = {
        "run_id": p22["run_id"],
        "candidate": p22["portfolio"]["candidate"],
    }
    summary["universe"]["latest_daily_update_only_survivors"] = True
    summary["universe"]["permanent_identity_exclusions_applied_from_registry"] = True
    summary["execution"]["memory"] = _memory_snapshot()
    control_events = pd.read_csv(OUT_DIR / "control_portfolio_events.csv")
    candidate_events = pd.read_csv(OUT_DIR / "candidate_portfolio_events.csv")
    for name, event_frame in (("control", control_events), ("candidate", candidate_events)):
        summary["portfolio"][name]["total_buy_commissions_krw"] = float(
            event_frame.loc[event_frame["event_type"].eq("ENTRY"), "commission"].sum()
        )
        summary["portfolio"][name]["total_sell_commissions_krw"] = float(
            event_frame.loc[event_frame["event_type"].eq("EXIT"), "commission"].sum()
        )
    summary["portfolio"]["candidate_minus_control"]["total_buy_commissions_krw"] = (
        summary["portfolio"]["candidate"]["total_buy_commissions_krw"]
        - summary["portfolio"]["control"]["total_buy_commissions_krw"]
    )
    summary["portfolio"]["candidate_minus_control"]["total_sell_commissions_krw"] = (
        summary["portfolio"]["candidate"]["total_sell_commissions_krw"]
        - summary["portfolio"]["control"]["total_sell_commissions_krw"]
    )
    summary["execution"]["sample_benchmark"] = {
        "worker_count": sample["worker_count"],
        "observed_worker_threads": sample["worker_threads"]["observed_worker_threads"],
        "setup_seconds": sample["setup_seconds"],
        "sample_wall_seconds": sample["sample_wall_seconds"],
        "estimated_full_seconds": sample["estimated_full_seconds"],
        "estimated_full_minutes": sample["estimated_full_minutes"],
        "memory": sample["memory"],
    }
    summary["validation"]["paired_identity_audit_pass"] = identity_pass
    summary["validation"]["no_hidden_position_cap"] = not hidden_audit["portfolio_engine_source_has_slot_cap_branch"] and hidden_audit.get("slot_cap_would_block_count") == 0
    summary["validation"]["certification_gate_pass"] = summary["status"] == "P3_2_REALISTIC_PORTFOLIO_BACKTEST_CERTIFIED"
    summary["artifacts"] = {
        name: f"artifacts/backtests/p3_2_neg40_weak_protect_v01/{RUN_ID}/{name}"
        for name in (
            "run_manifest.json", "preflight_summary.json", "sample_benchmark.json",
            "execution_contract.json", "survivor_universe_audit.csv", "pit_mcap_audit.csv",
            "control_strategy_trades.csv", "candidate_strategy_trades.csv", "paired_identity_audit.csv",
            "matching_audit.json", "p3_2_soft_events.csv", "control_portfolio_trades.csv",
            "candidate_portfolio_trades.csv", "control_portfolio_events.csv", "candidate_portfolio_events.csv",
            "control_daily_equity.csv", "candidate_daily_equity.csv", "valuation_carry_audit.csv",
            "skipped_entries.csv", "hidden_position_cap_audit.json", "summary.json", "final_report.md",
        )
    }
    _json_write(OUT_DIR / "summary.json", summary)
    engine._write_summary_csv(summary, OUT_DIR / "summary.csv")
    report = _comparison_report(summary, p21, p22)
    (OUT_DIR / "comparison_report.md").write_text(report, encoding="utf-8")
    (OUT_DIR / "final_report.md").write_text(report, encoding="utf-8")

    manifest = json.loads((OUT_DIR / "run_manifest.json").read_text(encoding="utf-8"))
    manifest.update(
        {
            "status": summary["status"],
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "head_at_finish": _head(),
            "strategy_evaluation_wall_seconds": summary["execution"]["strategy_evaluation_wall_seconds"],
            "portfolio_event_replay_wall_seconds": summary["execution"]["portfolio_event_replay_wall_seconds"],
            "total_wall_seconds": summary["execution"]["total_wall_seconds"],
            "worker_count": summary["execution"]["worker_count"],
            "observed_worker_threads": summary["execution"]["observed_worker_threads"],
            "max_rss": summary["execution"]["memory"],
            "artifacts": summary["artifacts"],
        }
    )
    _json_write(OUT_DIR / "run_manifest.json", manifest)
    return summary


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("sample", "full"), required=True)
    args = parser.parse_args()
    result = _sample() if args.mode == "sample" else _full_run()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str), flush=True)


if __name__ == "__main__":
    main()
