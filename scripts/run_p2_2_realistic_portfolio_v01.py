#!/usr/bin/env python3
"""Run the frozen P2-2 strategy pair through the certified realistic portfolio engine."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import resource
import statistics
import sys
import threading
import time
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trend_scanner.data.rolling_market_data_refresh import (
    load_rolling_authority,
    validate_merged_authority_coherence,
)
from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
import scripts.run_fastcore_neg40_weak_protect_p2_1 as p2
import scripts.run_p2_1_realistic_portfolio_v01 as portfolio


RUN_ID = "run_20260926_realistic_mcap1t_worker10_v01"
OUT_DIR = ROOT / "artifacts/backtests/p2_2_neg40_weak_protect_v01" / RUN_ID
ROLLING_DIR = ROOT / "data/market/rolling_authority"
P2_1_SUMMARY = (
    ROOT
    / "artifacts/backtests/p2_1_neg40_weak_protect_v01"
    / "run_20260926_realistic_mcap1t_worker10_v01"
    / "summary.json"
)
WORKERS = 10
SAMPLE_TICKERS = 40
CALENDAR_START = "2021-01-01"
CALENDAR_END = "2026-08-31"

# Reuse the P2-1 execution engine while extending its frozen historical tax
# table by the already-checked 2026 schedule used elsewhere in this repository.
portfolio.SELL_TAX_SCHEDULE = (*portfolio.SELL_TAX_SCHEDULE, ("2026-01-01", "2026-12-31", 0.0020))

OUTPUTS = (
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


def _load_survivor_context(*, worker_count: int):
    manifest = load_rolling_authority(ROLLING_DIR)
    pit_payload, _calendar_payload = validate_merged_authority_coherence(manifest, ROLLING_DIR)
    as_of = str(pit_payload.get("target_as_of", ""))
    if not as_of or as_of != manifest.merged_pit_frontier:
        raise RuntimeError("LATEST_DAILY_UPDATE_PIT_FRONTIER_MISMATCH")

    gate = portfolio.ExactRawMcapGate(ROOT, pit_payload)
    run = p2._load_context("P2-2")
    p2_authority_preflight = p2._p2_2_identity_authority_preflight(run)
    original = [segment for group in run.segments_by_ticker.values() for segment in group]
    selected = [
        segment
        for segment in original
        if (segment.ticker, segment.isu_cd.upper(), segment.market.upper()) in gate.active_identity_keys
    ]
    selected_keys = {segment.key for segment in selected}
    grouped: dict[str, list[p2.IdentitySegment]] = {}
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
        "merged_pit_file_sha256": portfolio._sha256(ROLLING_DIR / "merged_pit_intervals.json"),
        "effective_pit_file_sha256": portfolio._sha256(run.authority.pit_path),
        "p2_2_identity_authority_preflight": p2_authority_preflight,
        "raw_market_cap_store": "data/market/raw/krx_stocks/v01",
        "raw_market_cap_threshold_krw": portfolio.MARKET_CAP_THRESHOLD,
        "worker_count": worker_count,
        "survivor_filter": "latest_daily_update COMMON by exact ticker + ISU + market identity",
        "network_calls": 0,
    }
    return filtered, gate, authority, pd.DataFrame(universe_rows), original


def _run_pool(run, gate, tickers: Sequence[str], *, workers: int):
    started = time.perf_counter()
    outcomes: list[dict[str, Any]] = []
    errors: list[str] = []

    def process(ticker: str):
        result = p2._process_ticker(ticker, run)
        result["worker_thread"] = threading.current_thread().name
        return result

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="p2-2-worker") as pool:
        futures = {pool.submit(process, ticker): ticker for ticker in tickers}
        for completed, future in enumerate(as_completed(futures), start=1):
            ticker = futures[future]
            try:
                outcomes.append(future.result())
            except Exception as exc:
                errors.append(f"{ticker}: {type(exc).__name__}: {exc}")
            if completed % 25 == 0 or completed == len(tickers):
                audit_count = len(gate.audit_frame())
                print(
                    f"P2-2 workers progress {completed}/{len(tickers)}; "
                    f"trades={sum(len(item['control_rows']) for item in outcomes)}; "
                    f"PIT candidates={audit_count}; elapsed={time.perf_counter() - started:.1f}s; "
                    f"errors={len(errors)}",
                    flush=True,
                )
    return outcomes, errors, time.perf_counter() - started


def _rollup(outcomes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_worker: dict[str, dict[str, Any]] = {}
    for outcome in outcomes:
        name = str(outcome["worker_thread"])
        entry = by_worker.setdefault(name, {"ticker_tasks": 0, "worker_task_seconds": 0.0})
        entry["ticker_tasks"] += 1
        entry["worker_task_seconds"] += float(outcome["elapsed_seconds"])
    return {
        "configured_workers": WORKERS,
        "observed_worker_threads": len(by_worker),
        "worker_threads": {
            name: {"ticker_tasks": data["ticker_tasks"], "worker_task_seconds": round(data["worker_task_seconds"], 3)}
            for name, data in sorted(by_worker.items())
        },
        "sum_worker_task_seconds": round(sum(float(item["elapsed_seconds"]) for item in outcomes), 3),
    }


def _raw_partition_coverage(trading_dates: Sequence[pd.Timestamp]) -> dict[str, Any]:
    dates = [
        pd.Timestamp(day).normalize().strftime("%Y-%m-%d")
        for day in trading_dates
        if CALENDAR_START <= pd.Timestamp(day).normalize().strftime("%Y-%m-%d") <= "2026-09-01"
    ]
    store = KrxRawStockStore(ROOT / "data/market/raw/krx_stocks/v01")
    result: dict[str, Any] = {"expected_trading_dates": len(dates), "markets": {}}
    for market in ("KOSPI", "KOSDAQ"):
        manifests = {
            row["date"]: row
            for row in store.list_manifest(market)
            if CALENDAR_START <= row["date"] <= "2026-09-01"
        }
        counts: dict[str, int] = {}
        for day in dates:
            status = str(manifests.get(day, {}).get("status", "MISSING_MANIFEST"))
            counts[status] = counts.get(status, 0) + 1
        missing = [day for day in dates if manifests.get(day, {}).get("status") != "COMPLETE"]
        result["markets"][market] = {
            "date_status_counts": counts,
            "non_complete_date_count": len(missing),
            "first_non_complete_dates": missing[:20],
        }
    result["all_expected_market_dates_complete"] = all(
        item["non_complete_date_count"] == 0 for item in result["markets"].values()
    )
    return result


def _sample(*, workers: int, sample_tickers: int) -> dict[str, Any]:
    if workers != WORKERS or sample_tickers != SAMPLE_TICKERS:
        raise RuntimeError("P2_2_PREFLIGHT_REQUIRES_40_TICKERS_AND_10_WORKERS")
    path = OUT_DIR / "sample_benchmark.json"
    if path.exists():
        raise RuntimeError(f"REFUSING_TO_OVERWRITE_SAMPLE:{path}")
    run, gate, authority, _universe, _original = _load_survivor_context(worker_count=workers)
    all_tickers = sorted(run.segments_by_ticker)
    selected = p2._sample_tickers(all_tickers, sample_tickers)
    if len(selected) != sample_tickers:
        raise RuntimeError(f"P2_2_PREFLIGHT_SAMPLE_TOO_SMALL:{len(selected)}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    outcomes, errors, sample_wall = _run_pool(run, gate, selected, workers=workers)
    gate_audit = gate.audit_frame()
    counts = gate_audit["status"].value_counts().to_dict() if not gate_audit.empty else {}
    estimate = run.setup_seconds + sample_wall * len(all_tickers) / len(selected)
    result = {
        "status": "COMPLETE" if not errors else "FAILED",
        "window_id": "P2-2",
        "run_id": RUN_ID,
        "worker_count": workers,
        "sample_ticker_count": len(selected),
        "sample_tickers": selected,
        "target_ticker_count": len(all_tickers),
        "survivor_identity_count": sum(len(rows) for rows in run.segments_by_ticker.values()),
        "latest_daily_update_as_of": authority["latest_daily_update_as_of"],
        "sample_wall_seconds": round(sample_wall, 3),
        "setup_seconds": round(run.setup_seconds, 3),
        "estimated_full_seconds": round(estimate, 3),
        "estimated_full_minutes": round(estimate / 60.0, 2),
        "sample_gate_signal_counts": {str(key): int(value) for key, value in counts.items()},
        "sample_mcap_unresolved_count": int(counts.get("UNRESOLVED", 0)),
        "worker_threads": _rollup(outcomes),
        "errors": errors,
        "p2_2_window": {
            "calendar_start": CALENDAR_START,
            "calendar_end": CALENDAR_END,
            "effective_start": run.window.effective_start.strftime("%Y-%m-%d"),
            "effective_end": run.window.effective_end.strftime("%Y-%m-%d"),
            "execution_support": run.window.execution_support.strftime("%Y-%m-%d"),
        },
        "preflight_elapsed_seconds_including_setup": round(time.perf_counter() - started, 3),
        "prior_unfiltered_p2_2_reference_seconds": 4110.038,
        "network_calls": 0,
    }
    _json_write(path, result)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return result


def _classify_carries(audit_rows: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    if not audit_rows:
        return pd.DataFrame(
            columns=["ticker", "identity", "market", "valuation_date", "gap_classification", "classification_status"]
        )
    raw_store = KrxRawStockStore(ROOT / "data/market/raw/krx_stocks/v01")
    adjusted_store = AdjustedPriceStore(ROOT / "data/market/adjusted/stocks")
    raw_cache: dict[tuple[str, str], tuple[dict[str, Any] | None, pd.DataFrame | None]] = {}
    adjusted_cache: dict[str, pd.DataFrame] = {}
    classified: list[dict[str, Any]] = []
    unique: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in audit_rows:
        key = (str(row["ticker"]).zfill(6), str(row["valuation_date"]))
        unique.setdefault(key, row)
    for (ticker, day), source in sorted(unique.items()):
        market = str(source.get("market", "")).upper()
        key = (market, day)
        if key not in raw_cache:
            manifest = raw_store.get_manifest(market, day) if market else None
            frame = raw_store.load_snapshot(market, day) if manifest and manifest.get("status") == "COMPLETE" else None
            raw_cache[key] = (manifest, frame)
        manifest, raw_frame = raw_cache[key]
        raw_match = (
            raw_frame.loc[raw_frame["ticker"].astype(str).str.zfill(6).eq(ticker)]
            if raw_frame is not None
            else pd.DataFrame()
        )
        classification = "UNCLASSIFIED"
        reason = "RAW_PARTITION_OR_TICKER_ROW_UNAVAILABLE"
        raw_placeholder = False
        invalid_relations: list[str] = []
        adjusted_row = None
        if len(raw_match) == 1:
            raw_row = raw_match.iloc[0]
            raw_placeholder = bool(
                int(raw_row["open"]) == 0
                and int(raw_row["high"]) == 0
                and int(raw_row["low"]) == 0
                and int(raw_row["close"]) > 0
                and int(raw_row["volume"]) == 0
                and int(raw_row["trading_value"]) == 0
            )
            if ticker not in adjusted_cache:
                adjusted_cache[ticker] = adjusted_store.load_daily_source(ticker)
            adjusted = adjusted_cache[ticker]
            if pd.Timestamp(day) in adjusted.index:
                adjusted_row = adjusted.loc[pd.Timestamp(day)]
                for field, violated in (
                    ("high_below_low", adjusted_row["high"] < adjusted_row["low"]),
                    ("high_below_open", adjusted_row["high"] < adjusted_row["open"]),
                    ("high_below_close", adjusted_row["high"] < adjusted_row["close"]),
                    ("low_above_open", adjusted_row["low"] > adjusted_row["open"]),
                    ("low_above_close", adjusted_row["low"] > adjusted_row["close"]),
                ):
                    if bool(violated):
                        invalid_relations.append(field)
            if raw_placeholder:
                classification, reason = "NON_TRADING_PLACEHOLDER", "RAW_ZERO_OHLCV_PLACEHOLDER"
            elif invalid_relations:
                classification, reason = "ADJUSTED_ANALYTICALLY_NONUSABLE", ";".join(invalid_relations)
            elif adjusted_row is None or pd.isna(adjusted_row.get("close")):
                classification, reason = "UNCLASSIFIED", "EXACT_ADJUSTED_ROW_HAS_NO_VALID_CLOSE"
            else:
                classification, reason = "UNCLASSIFIED", "EXACT_CLOSE_UNUSABLE_WITHOUT_KNOWN_GAP_CLASS"
        classified.append(
            {
                "ticker": ticker,
                "identity": source.get("identity"),
                "market": market,
                "valuation_date": day,
                "previous_valid_adjusted_close_date": source.get("last_valid_adjusted_close_date"),
                "carried_adjusted_close": source.get("carried_adjusted_close"),
                "stale_age_trading_days": source.get("stale_age_trading_days"),
                "stale_age_calendar_days": source.get("stale_age_calendar_days"),
                "gap_classification": classification,
                "classification_status": reason,
                "raw_partition_status": manifest.get("status") if manifest else None,
                "raw_partition_file_sha256": manifest.get("file_sha256") if manifest else None,
                "raw_ticker_row_count": len(raw_match),
                "raw_row_is_nontrading_placeholder": raw_placeholder,
                "adjusted_source_row_present": adjusted_row is not None,
                "adjusted_invalid_relation_fields": ";".join(invalid_relations),
                "valuation_only": True,
                "used_for_execution": False,
                "used_for_strategy_or_features": False,
            }
        )
    return pd.DataFrame(classified)


def _write_summary_csv(summary: Mapping[str, Any], path: Path) -> None:
    rows = []
    for strategy, metrics in (("CONTROL", summary["portfolio"]["control"]), ("CANDIDATE", summary["portfolio"]["candidate"])):
        rows.extend({"strategy": strategy, "metric": key, "value": value} for key, value in metrics.items() if not isinstance(value, (list, dict)))
    rows.extend(
        {"strategy": "CANDIDATE_MINUS_CONTROL", "metric": key, "value": value}
        for key, value in summary["portfolio"]["candidate_minus_control"].items()
    )
    pd.DataFrame(rows).to_csv(path, index=False)


def _comparison_report(summary: Mapping[str, Any]) -> str:
    control = summary["portfolio"]["control"]
    candidate = summary["portfolio"]["candidate"]
    delta = summary["portfolio"]["candidate_minus_control"]
    p21 = summary["p2_1_comparison"]["candidate"]
    p22_metrics = {
        "cumulative_return_pct": "누적수익률 (%)",
        "CAGR_pct": "CAGR (%)",
        "mdd_pct": "MDD (%)",
        "realized_return_le_neg_30_count": "실현 ≤ -30%",
        "realized_return_le_neg_40_count": "실현 ≤ -40%",
        "realized_return_le_neg_50_count": "실현 ≤ -50%",
        "realized_return_le_neg_60_count": "실현 ≤ -60%",
        "realized_return_ge_pos_50_count": "실현 ≥ +50%",
        "realized_return_ge_pos_100_count": "실현 ≥ +100%",
        "average_holding_trading_days": "평균 보유일",
        "turnover_multiple": "회전율 (배)",
        "cash_shortage_skipped_entries": "현금 부족 진입 skip",
    }
    rows = "\n".join(
        f"| {label} | {p21.get(key)} | {candidate.get(key)} | {candidate.get(key) - p21.get(key)} |"
        for key, label in p22_metrics.items()
    )
    return f"""# P2-2 현실적 포트폴리오 비교

판정: `{summary['status']}`  
대상: P2-2 only, {summary['window']['effective_start']} ~ {summary['window']['effective_end']} (execution support {summary['window']['execution_support']})  
최신 Daily Update: {summary['universe']['latest_daily_update_as_of']}  
Universe는 해당 기준일 현재 COMMON identity survivor만 포함한 의도적 survivorship-filtered 모집단이야.

## CONTROL vs Candidate

| 지표 | CONTROL | Candidate | Candidate − CONTROL |
|---|---:|---:|---:|
| 최종 자산 | {control['final_equity']:,.0f} | {candidate['final_equity']:,.0f} | {delta['final_equity']:,.0f} |
| 누적수익률 | {control['cumulative_return_pct']:.4f}% | {candidate['cumulative_return_pct']:.4f}% | {delta['cumulative_return_pct']:.4f}%p |
| CAGR | {control['CAGR_pct']:.4f}% | {candidate['CAGR_pct']:.4f}% | {delta['CAGR_pct']:.4f}%p |
| MDD | {control['mdd_pct']:.4f}% | {candidate['mdd_pct']:.4f}% | {delta['mdd_pct']:.4f}%p |
| 체결 거래 / 승률 | {control['trade_count']} / {control['win_rate_pct']:.2f}% | {candidate['trade_count']} / {candidate['win_rate_pct']:.2f}% | {delta['trade_count']} / {delta['win_rate_pct']:.2f}%p |
| 평균 / 중앙 보유일 | {control['average_holding_trading_days']:.2f} / {control['median_holding_trading_days']:.2f} | {candidate['average_holding_trading_days']:.2f} / {candidate['median_holding_trading_days']:.2f} | {delta['average_holding_trading_days']:.2f} / {delta['median_holding_trading_days']:.2f} |
| 동시보유 평균 / 최대 | {control['average_concurrent_positions']:.2f} / {control['maximum_concurrent_positions']} | {candidate['average_concurrent_positions']:.2f} / {candidate['maximum_concurrent_positions']} | {delta['average_concurrent_positions']:.2f} / {delta['maximum_concurrent_positions']} |
| 자본사용 평균 / 최대 | {control['average_capital_utilization_pct']:.2f}% / {control['maximum_capital_utilization_pct']:.2f}% | {candidate['average_capital_utilization_pct']:.2f}% / {candidate['maximum_capital_utilization_pct']:.2f}% | {delta['average_capital_utilization_pct']:.2f}%p / {delta['maximum_capital_utilization_pct']:.2f}%p |
| 평균 현금 비율 | {control['average_cash_ratio_pct']:.2f}% | {candidate['average_cash_ratio_pct']:.2f}% | {delta['average_cash_ratio_pct']:.2f}%p |
| 회전율 | {control['turnover_multiple']:.4f}x | {candidate['turnover_multiple']:.4f}x | {delta['turnover_multiple']:.4f}x |
| 수수료 / 거래세 / 슬리피지 | {control['total_commissions_krw']:,.0f} / {control['total_sell_tax_krw']:,.0f} / {control['slippage_impact_krw']:,.0f} | {candidate['total_commissions_krw']:,.0f} / {candidate['total_sell_tax_krw']:,.0f} / {candidate['slippage_impact_krw']:,.0f} | {delta['total_commissions_krw']:,.0f} / {delta['total_sell_tax_krw']:,.0f} / {delta['slippage_impact_krw']:,.0f} |
| 현금 부족 skip / cutoff open | {control['cash_shortage_skipped_entries']} / {control['open_at_effective_cutoff_count']} | {candidate['cash_shortage_skipped_entries']} / {candidate['open_at_effective_cutoff_count']} | {delta['cash_shortage_skipped_entries']} / {delta['open_at_effective_cutoff_count']} |
| 실현 ≤ -30/-40/-50/-60% | {control['realized_return_le_neg_30_count']}/{control['realized_return_le_neg_40_count']}/{control['realized_return_le_neg_50_count']}/{control['realized_return_le_neg_60_count']} | {candidate['realized_return_le_neg_30_count']}/{candidate['realized_return_le_neg_40_count']}/{candidate['realized_return_le_neg_50_count']}/{candidate['realized_return_le_neg_60_count']} | {delta['realized_return_le_neg_30_count']}/{delta['realized_return_le_neg_40_count']}/{delta['realized_return_le_neg_50_count']}/{delta['realized_return_le_neg_60_count']} |
| 실현 ≥ +50/+100% | {control['realized_return_ge_pos_50_count']}/{control['realized_return_ge_pos_100_count']} | {candidate['realized_return_ge_pos_50_count']}/{candidate['realized_return_ge_pos_100_count']} | {delta['realized_return_ge_pos_50_count']}/{delta['realized_return_ge_pos_100_count']} |

## P2-1 Candidate 대비 P2-2 Candidate

| 지표 | P2-1 인증 Candidate | P2-2 Candidate | P2-2 − P2-1 |
|---|---:|---:|---:|
{rows}

## 해석 질문

- V2 대비 CAGR: Candidate−CONTROL은 {delta['CAGR_pct']:.4f}%p.
- 상승장 포함 구간 winner 보존: ≥+50% 거래 {candidate['realized_return_ge_pos_50_count']}건, ≥+100% {candidate['realized_return_ge_pos_100_count']}건.
- Candidate tail 결과(≤-30/-40/-50/-60%): {candidate['realized_return_le_neg_30_count']}/{candidate['realized_return_le_neg_40_count']}/{candidate['realized_return_le_neg_50_count']}/{candidate['realized_return_le_neg_60_count']}건.
- V2 대비 MDD 차이: {delta['mdd_pct']:.4f}%p (음수면 Candidate의 drawdown이 더 깊음).
- 보유기간/회전율/현금 부족 skip: 평균 보유 {candidate['average_holding_trading_days']:.2f}일, 회전율 {candidate['turnover_multiple']:.4f}x, 현금 부족 skip {candidate['cash_shortage_skipped_entries']}건.

## 실행 경계 및 재검산

- 기존 frozen V2/V2.1 신호 생성 코드와 P2-2 effective/execution-support authority만 사용했어. 2026-08-31 이후 신규 진입은 금지하고 2026-09-01은 이미 발생한 신호의 체결 지원만 허용했어.
- 최신 Daily Update CURRENT COMMON identity survivor 필터와 exact signal-date KRX raw `MKTCAP >= 1조원` gate를 전략 평가 전에 적용했어. proxy·인접일·보간·과거 ledger 사후 필터는 사용하지 않았어.
- 포트폴리오 replay는 단일 deterministic 순서고, 최대 동시보유 종목수 cap은 없어. 종목별 총 매수 예산은 500만원 고정이야.
- 조정종가 carry는 valuation-only이며 상세 gap class와 직전 가격·날짜·stale age는 [valuation_carry_audit.csv](valuation_carry_audit.csv)에 기록했어.
- 모든 산출물 및 validation은 [summary.json](summary.json), 두 전략 ledger, pair audit, event ledger, daily equity, exact-date PIT audit로 재검산할 수 있어.
"""


def _full_run(*, workers: int) -> dict[str, Any]:
    sample_path = OUT_DIR / "sample_benchmark.json"
    if not sample_path.is_file():
        raise RuntimeError("P2_2_FULL_RUN_REQUIRES_SAME_PATH_PREFLIGHT_SAMPLE")
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    if workers != WORKERS or sample.get("worker_count") != workers:
        raise RuntimeError("P2_2_FULL_RUN_WORKER_COUNT_MISMATCH_EXPECTED_10")
    if sample.get("status") != "COMPLETE" or sample.get("errors"):
        raise RuntimeError("P2_2_FULL_RUN_REQUIRES_PASSING_SAMPLE")
    existing = [name for name in OUTPUTS if (OUT_DIR / name).exists()]
    if existing:
        raise RuntimeError("REFUSING_TO_OVERWRITE_EXISTING_OUTPUTS:" + ",".join(existing))

    started = time.perf_counter()
    started_at = datetime.now(timezone.utc).isoformat()
    run, gate, authority, universe, original = _load_survivor_context(worker_count=workers)
    tickers = sorted(run.segments_by_ticker)
    if not tickers:
        raise RuntimeError("P2_2_CURRENT_COMMON_SURVIVOR_UNIVERSE_EMPTY")
    partition_coverage = _raw_partition_coverage(run.calendar.trading_dates)
    if not partition_coverage["all_expected_market_dates_complete"]:
        _json_write(OUT_DIR / "preflight_pit_partition_coverage.json", partition_coverage)
        raise RuntimeError("P2_2_PIT_RAW_MARKET_DATE_COVERAGE_INCOMPLETE")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    strategy_started = time.perf_counter()
    outcomes, errors, _ = _run_pool(run, gate, tickers, workers=workers)
    strategy_wall = time.perf_counter() - strategy_started
    if errors:
        _json_write(
            OUT_DIR / "full_failure.json",
            {
                "status": "FAILED",
                "errors": errors,
                "completed_tickers": len(outcomes),
                "target_tickers": len(tickers),
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "workers": workers,
            },
        )
        raise RuntimeError(f"P2_2_FULL_TICKER_ERRORS:{len(errors)}")

    control = pd.DataFrame([row for item in outcomes for row in item["control_rows"]])
    candidate = pd.DataFrame([row for item in outcomes for row in item["candidate_rows"]])
    control = control.sort_values(["ticker", "identity_effective_from", "trade_sequence"], kind="mergesort").reset_index(drop=True)
    candidate = candidate.sort_values(["ticker", "identity_effective_from", "trade_sequence"], kind="mergesort").reset_index(drop=True)
    matching = portfolio._validate_entry_pairing(control, candidate)
    frames: dict[str, pd.DataFrame] = {}
    for item in outcomes:
        frames.update(item["market_data_by_identity"])
    pit_audit = gate.audit_frame()
    if pit_audit.empty:
        raise RuntimeError("P2_2_PIT_MCAP_GATE_PRODUCED_NO_SIGNAL_AUDIT")
    unresolved_mcap = pit_audit.loc[pit_audit["status"].astype(str).eq("UNRESOLVED")]

    all_dates = tuple(pd.to_datetime(run.calendar.trading_dates).normalize())
    start = pd.Timestamp(run.window.effective_start).normalize()
    end = pd.Timestamp(run.window.effective_end).normalize()
    support = pd.Timestamp(run.window.execution_support).normalize()
    replay_started = time.perf_counter()
    results = {
        "CONTROL": portfolio._portfolio_replay(
            control.to_dict(orient="records"), frames, all_dates,
            strategy_id=p2.V2_STRATEGY_ID,
            effective_start=start, effective_end=end, execution_support=support,
        ),
        "CANDIDATE": portfolio._portfolio_replay(
            candidate.to_dict(orient="records"), frames, all_dates,
            strategy_id=p2.CANDIDATE_STRATEGY_ID,
            effective_start=start, effective_end=end, execution_support=support,
        ),
    }
    replay_wall = time.perf_counter() - replay_started
    carries = _classify_carries(
        results["CONTROL"]["valuation_gap_audit"] + results["CANDIDATE"]["valuation_gap_audit"]
    )
    metrics = {
        "control": results["CONTROL"]["metrics"],
        "candidate": results["CANDIDATE"]["metrics"],
    }
    comparison = portfolio._comparison(metrics["control"], metrics["candidate"])
    for metric in ("maximum_capital_utilization_pct",):
        comparison["candidate_minus_control"][metric] = (
            metrics["candidate"][metric] - metrics["control"][metric]
        )
    soft_events = pd.DataFrame(
        [event for item in outcomes for diagnostic in item["diagnostics"] for event in diagnostic["soft_events"]]
    )
    skipped = pd.DataFrame(results["CONTROL"]["skipped"] + results["CANDIDATE"]["skipped"])
    unresolved_portfolio = int(metrics["control"]["unresolved_count"] + metrics["candidate"]["unresolved_count"])
    unclassified_carries = int(carries["gap_classification"].isin(["UNCLASSIFIED"]).sum()) if not carries.empty else 0
    daily_expected = len([day for day in all_dates if start <= day <= support])
    curves_complete = all(len(results[key]["daily_equity"]) == daily_expected for key in ("CONTROL", "CANDIDATE"))
    for key in ("CONTROL", "CANDIDATE"):
        curve = pd.DataFrame(results[key]["daily_equity"])
        last_equity = float(curve.dropna(subset=["equity"]).iloc[-1]["equity"])
        reproduced_return = (last_equity / portfolio.INITIAL_CAPITAL - 1.0) * 100.0
        if abs(reproduced_return - metrics[key.lower()]["cumulative_return_pct"]) > 0.1:
            raise RuntimeError(f"P2_2_RETURN_REPRODUCTION_OUTSIDE_0_1PP:{key}")
        if not metrics[key.lower()]["cash_conservation_pass"]:
            raise RuntimeError(f"P2_2_CASH_CONSERVATION_FAILED:{key}")

    pairing_pass = bool(
        matching["pair_id_unique"]
        and matching["pair_id_sets_equal"]
        and matching["source_trade_id_equal_by_pair"]
    )
    mcap_counts = {str(key): int(value) for key, value in pit_audit["status"].value_counts().items()}
    worker_info = _rollup(outcomes)
    validation = {
        **matching,
        "matching_pass": pairing_pass,
        "mcap_unresolved_count": int(len(unresolved_mcap)),
        "mcap_signal_status_counts": mcap_counts,
        "portfolio_unresolved_count": unresolved_portfolio,
        "valuation_carry_audit_rows": int(len(carries)),
        "unclassified_valuation_carry_count": unclassified_carries,
        "control_cash_conservation": bool(metrics["control"]["cash_conservation_pass"]),
        "candidate_cash_conservation": bool(metrics["candidate"]["cash_conservation_pass"]),
        "daily_equity_complete": curves_complete,
        "no_hidden_position_cap": True,
        "network_calls": 0,
        "aggregate_return_tolerance_pp": 0.1,
    }
    certified = (
        pairing_pass
        and validation["mcap_unresolved_count"] == 0
        and unresolved_portfolio == 0
        and unclassified_carries == 0
        and curves_complete
        and validation["control_cash_conservation"]
        and validation["candidate_cash_conservation"]
    )
    execution = {
        "worker_count": workers,
        "observed_worker_threads": worker_info["observed_worker_threads"],
        "worker_threads": worker_info["worker_threads"],
        "sum_worker_task_seconds": worker_info["sum_worker_task_seconds"],
        "strategy_evaluation_wall_seconds": round(strategy_wall, 3),
        "portfolio_event_replay_wall_seconds": round(replay_wall, 3),
        "total_wall_seconds": round(time.perf_counter() - started, 3),
        "setup_seconds": round(run.setup_seconds, 3),
        "python_process_max_rss_reported_by_resource": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
        "rss_units": "bytes on macOS; KiB on Linux",
        "processed_tickers": len(outcomes),
        "target_tickers": len(tickers),
        "market_data_frames_retained_for_portfolio": len(frames),
        "portfolio_replay_deterministic_sequential": True,
    }
    segment_count = sum(len(group) for group in run.segments_by_ticker.values())
    original_segments = len(original)
    summary: dict[str, Any] = {
        "status": "P2_2_REALISTIC_PORTFOLIO_BACKTEST_CERTIFIED" if certified else "P2_2_REALISTIC_PORTFOLIO_BACKTEST_REVIEW_REQUIRED",
        "work_id": "P2_2_V2_VS_NEG40_WEAK_PROTECT_REALISTIC_PORTFOLIO_V01",
        "window_id": "P2-2",
        "run_id": RUN_ID,
        "started_at": started_at,
        "head": p2.subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "strategy_ids": {"control": p2.V2_STRATEGY_ID, "candidate": p2.CANDIDATE_STRATEGY_ID},
        "window": {
            "calendar_start": CALENDAR_START,
            "calendar_end": CALENDAR_END,
            "effective_start": start.strftime("%Y-%m-%d"),
            "effective_end": end.strftime("%Y-%m-%d"),
            "execution_support": support.strftime("%Y-%m-%d"),
        },
        "universe": {
            "latest_daily_update_as_of": authority["latest_daily_update_as_of"],
            "latest_daily_update_source_frontier": authority["latest_daily_update_source_frontier"],
            "source_common_identity_segment_count_after_existing_policy": original_segments,
            "survivor_common_identity_segment_count": segment_count,
            "survivor_ticker_count": len(tickers),
            "survivor_unique_isu_count": len({row.isu_cd for group in run.segments_by_ticker.values() for row in group}),
            "survivor_only_filter_is_intentional": True,
            "excluded_non_survivor_segment_count": original_segments - segment_count,
            "existing_permanent_identity_policy_exclusion_count": len(run.permanent_identity_exclusions),
        },
        "market_cap_filter": {
            "threshold_krw": portfolio.MARKET_CAP_THRESHOLD,
            "source": "KRX Open API Stock Daily MKTCAP in exact-date immutable raw store",
            "exact_entry_signal_date_only": True,
            "same_date_raw_rows_verified_by_store_manifest_hash": True,
            "no_proxy_nearest_date_or_fill": True,
            "qualified_fast_signal_attempt_count": int(len(pit_audit)),
            "status_counts": mcap_counts,
            "exact_raw_partitions_used": int(pit_audit[["market", "signal_date"]].drop_duplicates().shape[0]),
            "unresolved_count": int(len(unresolved_mcap)),
            "rejected_signals_do_not_consume_reentry_state": True,
        },
        "portfolio_contract": {
            "initial_capital_krw": portfolio.INITIAL_CAPITAL,
            "per_ticker_total_buy_cash_budget_krw": portfolio.POSITION_BUDGET,
            "position_cap": None,
            "duplicate_active_identity_forbidden": True,
            "pyramiding": False,
            "partial_fill": False,
            "cash_shortage_policy": "SKIP_FULL_TARGET_ORDER",
            "same_open_exit_proceeds_reusable": False,
            "same_open_entry_priority": ["PIT market_cap descending", "ticker ascending"],
            "buy_commission_rate": portfolio.COMMISSION_RATE,
            "sell_commission_rate": portfolio.COMMISSION_RATE,
            "buy_slippage_rate": portfolio.SLIPPAGE_RATE,
            "sell_slippage_rate": portfolio.SLIPPAGE_RATE,
            "sell_tax_schedule": [
                {"start": begin, "end": finish, "KOSPI": rate, "KOSDAQ": rate}
                for begin, finish, rate in portfolio.SELL_TAX_SCHEDULE
            ],
            "cash_release": "next certified local trading session after sale execution; execution-support proceeds remain pending",
            "cutoff_valuation": "effective-end exact close; no support-date close is used for open positions",
            "valuation_carry": "most recent earlier valid adjusted close for portfolio MTM only",
        },
        "data_authority": authority,
        "raw_pit_partition_coverage": partition_coverage,
        "population": {
            "control_trade_rows": int(len(control)),
            "candidate_trade_rows": int(len(candidate)),
            "matched_pair_count": int(len(control)),
            "soft_event_rows": int(len(soft_events)),
            "market_data_identity_frames": len(frames),
        },
        "execution": execution,
        "portfolio": comparison,
        "p2_1_comparison": {"run_id": json.loads(P2_1_SUMMARY.read_text(encoding="utf-8"))["run_id"], "candidate": json.loads(P2_1_SUMMARY.read_text(encoding="utf-8"))["portfolio"]["candidate"]},
        "validation": validation,
        "artifacts": {name: f"artifacts/backtests/p2_2_neg40_weak_protect_v01/{RUN_ID}/{name}" for name in OUTPUTS},
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _json_write(
        OUT_DIR / "execution_contract.json",
        {
            "schema": "p2_2_realistic_portfolio_execution_contract_v01",
            "frozen_before_result_review": True,
            "scope": "P2-2 only",
            "head_at_start": summary["head"],
            "authority": authority,
            "strategy_ids": summary["strategy_ids"],
            "window": summary["window"],
            "portfolio": summary["portfolio_contract"],
            "market_cap_filter": summary["market_cap_filter"],
            "strategy_entry_contract": "V2 and Candidate share the same entry signal path after pre-evaluation survivor and exact raw PIT mcap gates; frozen Candidate exit overlay only",
            "network_calls": 0,
        },
    )
    universe.to_csv(OUT_DIR / "survivor_universe_audit.csv", index=False)
    pit_audit.to_csv(OUT_DIR / "pit_mcap_audit.csv", index=False)
    control.to_csv(OUT_DIR / "control_strategy_trades.csv", index=False)
    candidate.to_csv(OUT_DIR / "candidate_strategy_trades.csv", index=False)
    soft_events.to_csv(OUT_DIR / "p2_2_soft_events.csv", index=False)
    _json_write(OUT_DIR / "matching_audit.json", matching)
    _json_write(OUT_DIR / "preflight_pit_partition_coverage.json", partition_coverage)
    pd.DataFrame(results["CONTROL"]["events"]).to_csv(OUT_DIR / "control_portfolio_events.csv", index=False)
    pd.DataFrame(results["CANDIDATE"]["events"]).to_csv(OUT_DIR / "candidate_portfolio_events.csv", index=False)
    pd.DataFrame(results["CONTROL"]["daily_equity"]).to_csv(OUT_DIR / "control_daily_equity.csv", index=False)
    pd.DataFrame(results["CANDIDATE"]["daily_equity"]).to_csv(OUT_DIR / "candidate_daily_equity.csv", index=False)
    carries.to_csv(OUT_DIR / "valuation_carry_audit.csv", index=False)
    skipped.to_csv(OUT_DIR / "skipped_entries.csv", index=False)
    audit_rows = results["CONTROL"]["entry_candidate_audit"] + results["CANDIDATE"]["entry_candidate_audit"]
    _json_write(
        OUT_DIR / "hidden_position_cap_audit.json",
        {
            "position_cap_configured": None,
            "position_cap_applied": False,
            "max_concurrent_positions_observed": max(metrics["maximum_concurrent_positions"] for metrics in metrics.values()),
            "candidate_entry_audit_rows": len(audit_rows),
            "slot_cap_would_block_count": sum(bool(row.get("slot_cap_would_block")) for row in audit_rows),
            "cash_insufficient_decisions": sum(row.get("decision") == "CASH_INSUFFICIENT" for row in audit_rows),
        },
    )
    _json_write(OUT_DIR / "summary.json", summary)
    _write_summary_csv(summary, OUT_DIR / "summary.csv")
    (OUT_DIR / "comparison_report.md").write_text(_comparison_report(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str), flush=True)
    return summary


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("sample", "full"), required=True)
    parser.add_argument("--workers", type=int, default=WORKERS)
    parser.add_argument("--sample-tickers", type=int, default=SAMPLE_TICKERS)
    args = parser.parse_args()
    if args.mode == "sample":
        _sample(workers=args.workers, sample_tickers=args.sample_tickers)
    else:
        _full_run(workers=args.workers)


if __name__ == "__main__":
    main()
