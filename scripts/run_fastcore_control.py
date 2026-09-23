#!/usr/bin/env python3
"""Generate the local-only FastCore CONTROL baseline for FIX05.

This runner deliberately consumes the frozen raw candidate artifact and the
canonical local Repository V2 only.  It does not import or call Fundamentals,
OpenDART, KRX, PyKRX, Naver, or any other network-backed source.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass, fields
import hashlib
import json
from pathlib import Path
import socket
import time
from typing import Any, Iterator, Mapping, Sequence
import warnings

import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

from trend_scanner.backtest.fastcore_fundamentals_simple_v01 import (
    IdentityLifecycle,
    StrategyTradeRecord,
    pit_common_for_identity,
    simulate_ticker_strategy_fundamentals_v01,
)
from trend_scanner.data.adjusted_price_authority_cutover import load_effective_authority
from trend_scanner.data.market_calendar import MarketCalendarAuthority, load_rolling_production_market_calendar
from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader, build_repository_v2
from trend_scanner.backtest.standard_windows import (
    STANDARD_BACKTEST_WINDOWS,
    ResolvedBacktestWindow,
    resolve_standard_backtest_window,
)


ROOT = Path(__file__).resolve().parents[1]
RAW_CANDIDATE_PATH = ROOT / "artifacts/backtests/fastcore_fundamentals_simple_v01/raw_candidates/fastcore_raw_candidates.csv"
FUNDAMENTALS_SUMMARY_PATH = ROOT / "artifacts/backtests/fastcore_fundamentals_simple_v01/fundamentals_coverage/fundamentals_coverage_summary.json"
EFFECTIVE_AUTHORITY_DIR = ROOT / "artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/v01_spac_corrected_effective_authority"
SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"
CONTROL_DIR = ROOT / "artifacts/backtests/fastcore_fundamentals_simple_v01/control"
CONTROL_TRADES_PATH = CONTROL_DIR / "control_trades.csv"
CONTROL_SUMMARY_PATH = CONTROL_DIR / "control_summary.json"

WORK_ID = "FASTCORE_SIMPLE_BACKTEST_WITH_FUNDAMENTALS_V01_CONTROL"
STRATEGY_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V02_CONTROL"
COMMON_START_DATE = pd.Timestamp("2021-04-01")
SIGNAL_END_DATE = pd.Timestamp("2026-08-14")
EXECUTION_SUPPORT_END_DATE = pd.Timestamp("2026-08-21")
EXPECTED_RAW_ROWS = 9_754
EXPECTED_RAW_SHA256 = "6f79fdaf7a341ec81c1fff4f2034b29f690651c7a08f1569c8cda82367114591"


@dataclass(frozen=True)
class RunnerWindow:
    window_id: str
    resolution: ResolvedBacktestWindow
    market_calendar: MarketCalendarAuthority
    output_dir: Path

    @property
    def common_start_date(self) -> pd.Timestamp:
        return self.resolution.effective_start

    @property
    def signal_end_date(self) -> pd.Timestamp:
        return self.resolution.effective_end

    @property
    def execution_support_end_date(self) -> pd.Timestamp:
        return self.resolution.execution_support


def resolve_runner_window(window_id: str) -> RunnerWindow:
    calendar = load_rolling_production_market_calendar(ROOT)
    resolved = resolve_standard_backtest_window(window_id, calendar)
    if calendar is None:
        # resolve_standard_backtest_window already fails closed; this narrows
        # the type for the immutable RunnerWindow below.
        raise RuntimeError("ROLLING_MARKET_CALENDAR_UNAVAILABLE")
    return RunnerWindow(
        window_id=window_id,
        resolution=resolved,
        market_calendar=calendar,
        output_dir=CONTROL_DIR / "windows" / window_id,
    )


def candidate_artifact_window_readiness(
    candidates: pd.DataFrame,
    run_window: RunnerWindow,
) -> dict[str, Any]:
    dates = pd.to_datetime(candidates["candidate_signal_date"], errors="raise").dt.normalize()
    artifact_start, artifact_end = dates.min(), dates.max()
    missing: list[str] = []
    if artifact_start > run_window.common_start_date:
        missing.append("candidate artifact starts after effective window start")
    if artifact_end < run_window.signal_end_date:
        missing.append("candidate artifact ends before effective window end")
    return {
        "status": "READY" if not missing else "BLOCKED_CANDIDATE_ARTIFACT_RANGE",
        "artifact_first_signal_date": artifact_start.strftime("%Y-%m-%d"),
        "artifact_last_signal_date": artifact_end.strftime("%Y-%m-%d"),
        "required_first_signal_date": run_window.common_start_date.strftime("%Y-%m-%d"),
        "required_last_signal_date": run_window.signal_end_date.strftime("%Y-%m-%d"),
        "reasons": missing,
    }


class NetworkRequestBlocked(RuntimeError):
    """Raised if the local-only CONTROL accidentally opens a socket."""


class NetworkAudit:
    def __init__(self) -> None:
        self.request_count = 0


@contextmanager
def network_guard(audit: NetworkAudit) -> Iterator[None]:
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def blocked_connect(self: socket.socket, address: Any) -> None:
        audit.request_count += 1
        raise NetworkRequestBlocked(f"offline CONTROL guard blocked socket connect: {address!r}")

    def blocked_connect_ex(self: socket.socket, address: Any) -> int:
        audit.request_count += 1
        raise NetworkRequestBlocked(f"offline CONTROL guard blocked socket connect_ex: {address!r}")

    socket.socket.connect = blocked_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = blocked_connect_ex  # type: ignore[method-assign]
    try:
        yield
    finally:
        socket.socket.connect = original_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = original_connect_ex  # type: ignore[method-assign]


def _json_read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frozen_candidate_id(ticker: str, isu_cd: str, market: str, signal_date: Any) -> str:
    return f"{ticker}|{isu_cd}|{market}|{pd.Timestamp(signal_date).strftime('%Y-%m-%d')}"


def validate_frozen_inputs() -> pd.DataFrame:
    if sha256_file(RAW_CANDIDATE_PATH) != EXPECTED_RAW_SHA256:
        raise RuntimeError("raw candidate artifact SHA-256 mismatch")
    candidates = pd.read_csv(RAW_CANDIDATE_PATH, dtype={"ticker": str, "isu_cd": str, "candidate_id": str})
    if len(candidates) != EXPECTED_RAW_ROWS:
        raise RuntimeError(f"raw candidate row mismatch: {len(candidates)}")
    if candidates["candidate_id"].nunique() != EXPECTED_RAW_ROWS:
        raise RuntimeError("raw candidate IDs are not unique")
    date_series = pd.to_datetime(candidates["candidate_signal_information_date"], errors="raise")
    if date_series.min() != pd.Timestamp("2015-01-02") or date_series.max() != SIGNAL_END_DATE:
        raise RuntimeError("raw candidate date range mismatch")

    coverage = _json_read(FUNDAMENTALS_SUMMARY_PATH)
    expected_coverage = {
        "common_start_date": "2021-04-01",
        "nonfinancial_candidates": 8_619,
        "evaluable_nonfinancial_candidates": 4_256,
        "true_data_unavailable_nonfinancial_candidates": 4_363,
        "evaluation_error_nonfinancial_candidates": 0,
    }
    for key, expected in expected_coverage.items():
        if coverage.get(key) != expected:
            raise RuntimeError(f"FIX05 authority mismatch for {key}: {coverage.get(key)!r}")
    return candidates


def _authority_intervals(
    authority: Any,
    execution_support_end_date: pd.Timestamp = EXECUTION_SUPPORT_END_DATE,
) -> dict[tuple[str, str, str], list[tuple[str, str]]]:
    intervals: dict[tuple[str, str, str], list[tuple[str, str]]] = {}
    for item in authority.pit_intervals:
        if item.get("state") != "COMMON":
            continue
        start = str(item["effective_from"])
        stop = str(item["effective_to"])
        if start > execution_support_end_date.strftime("%Y-%m-%d"):
            continue
        key = (str(item["ticker"]), str(item["isu_cd"]), str(item["market"]))
        intervals.setdefault(key, []).append((start, stop))
    for values in intervals.values():
        values.sort()
    return intervals


def _tasks_by_ticker(
    candidates: pd.DataFrame,
    common_start_date: pd.Timestamp = COMMON_START_DATE,
    signal_end_date: pd.Timestamp = SIGNAL_END_DATE,
) -> dict[str, list[dict[str, Any]]]:
    group_columns = ["ticker", "isu_cd", "market", "identity_effective_from", "identity_effective_to"]
    result: dict[str, list[dict[str, Any]]] = {}
    for key, group in candidates.groupby(group_columns, sort=True, dropna=False):
        ticker, isu_cd, market, effective_from, effective_to = key
        allowed = frozenset(
            frozen_candidate_id(ticker, isu_cd, market, value)
            for value in group["candidate_signal_date"].tolist()
            if common_start_date <= pd.Timestamp(value) <= signal_end_date
        )
        raw_dates = pd.to_datetime(group["entry_filter_raw_date"], errors="coerce")
        if raw_dates.isna().any():
            raise RuntimeError(f"raw candidate entry filter date missing for {ticker}/{isu_cd}")
        raw_panel = pd.DataFrame(
            {
                "close": pd.to_numeric(group["entry_signal_close"], errors="coerce").to_numpy(),
                "market_cap": pd.to_numeric(group["entry_market_cap"], errors="coerce").to_numpy(),
                "avg_trading_value_20d": pd.to_numeric(group["entry_avg_trading_value_20d"], errors="coerce").to_numpy(),
            },
            index=pd.DatetimeIndex(raw_dates),
        ).sort_index(kind="mergesort")
        if raw_panel.index.has_duplicates:
            duplicate_rows = raw_panel.loc[raw_panel.index.duplicated(keep=False)]
            if duplicate_rows.nunique(dropna=False).gt(1).any():
                raise RuntimeError(f"conflicting frozen raw values for {ticker}/{isu_cd}")
            raw_panel = raw_panel.loc[~raw_panel.index.duplicated(keep="last")]
        result.setdefault(str(ticker), []).append({
            "ticker": str(ticker),
            "isu_cd": str(isu_cd),
            "market": str(market),
            "name": str(group.iloc[0].get("name") or ticker),
            "effective_from": str(effective_from),
            "effective_to": str(effective_to),
            "allowed_candidate_ids": allowed,
            "allowed_signal_dates": frozenset(
                pd.Timestamp(value).normalize()
                for value in group["candidate_signal_date"].tolist()
                if common_start_date <= pd.Timestamp(value) <= signal_end_date
            ),
            "raw_panel": raw_panel,
        })
    return result


def _candidate_gate(
    *,
    ticker: str,
    isu_cd: str,
    market: str,
    allowed_candidate_ids: frozenset[str],
    common_start_date: pd.Timestamp = COMMON_START_DATE,
    signal_end_date: pd.Timestamp = SIGNAL_END_DATE,
):
    def gate(_as_of: pd.Timestamp, context: dict[str, Any]) -> dict[str, Any]:
        signal_date = pd.Timestamp(context["signal_date"]).normalize()
        candidate_id = frozen_candidate_id(ticker, isu_cd, market, signal_date)
        return {
            "gate_pass": candidate_id in allowed_candidate_ids
            and common_start_date <= signal_date <= signal_end_date,
            "gate_id": "FROZEN_RAW_CANDIDATE_MEMBERSHIP",
        }

    return gate


def _record_event_dates(record: StrategyTradeRecord) -> list[str]:
    return [
        value for value in (
            record.entry_signal_date,
            record.entry_signal_information_date,
            record.entry_execution_date,
            record.first_progressed_date,
            record.first_progressed_effective_trading_date,
            record.loss_guard_signal_date,
            record.loss_guard_execution_date,
            record.exit_signal_date,
            record.exit_execution_date,
            record.cutoff_date,
        ) if value
    ]


def _validate_records(
    records: list[StrategyTradeRecord],
    *,
    daily: pd.DataFrame,
    lifecycle: IdentityLifecycle,
    intervals: dict[tuple[str, str, str], list[tuple[str, str]]],
    common_start_date: pd.Timestamp = COMMON_START_DATE,
    signal_end_date: pd.Timestamp = SIGNAL_END_DATE,
    execution_support_end_date: pd.Timestamp = EXECUTION_SUPPORT_END_DATE,
) -> dict[str, int]:
    violations = {
        "pre_start_entry_violations": 0,
        "post_end_signal_violations": 0,
        "identity_violations": 0,
        "execution_next_day_violations": 0,
        "pit_membership_violations": 0,
    }
    identity_daily = daily.loc[
        (daily.index >= lifecycle.effective_from)
        & (daily.index <= lifecycle.effective_to)
        & (daily.index <= execution_support_end_date)
    ]
    for record in records:
        info_date = pd.Timestamp(record.entry_signal_information_date)
        signal_date = pd.Timestamp(record.entry_signal_date)
        if info_date < common_start_date:
            violations["pre_start_entry_violations"] += 1
        if info_date > signal_end_date:
            violations["post_end_signal_violations"] += 1
        if any(not lifecycle.contains(value) for value in _record_event_dates(record)):
            violations["identity_violations"] += 1
        expected_execution = identity_daily.index[identity_daily.index > signal_date]
        if expected_execution.empty or expected_execution[0].strftime("%Y-%m-%d") != record.entry_execution_date:
            violations["execution_next_day_violations"] += 1
        if not pit_common_for_identity(intervals, record.ticker, record.isu_cd, record.market, info_date):
            violations["pit_membership_violations"] += 1
    return violations


def _overlap_count(records: list[StrategyTradeRecord]) -> int:
    if not records:
        return 0
    rows = []
    for record in records:
        end = record.exit_execution_date or record.cutoff_date or EXECUTION_SUPPORT_END_DATE.strftime("%Y-%m-%d")
        rows.append((record.ticker, pd.Timestamp(record.entry_execution_date), pd.Timestamp(end)))
    rows.sort(key=lambda item: (item[0], item[1], item[2]))
    count = 0
    previous_by_ticker: dict[str, pd.Timestamp] = {}
    for ticker, start, end in rows:
        previous_end = previous_by_ticker.get(ticker)
        if previous_end is not None and start <= previous_end:
            count += 1
        if previous_end is None or end > previous_end:
            previous_by_ticker[ticker] = end
    return count


def _numeric_stats(frame: pd.DataFrame, column: str) -> tuple[float | None, float | None]:
    if frame.empty:
        return None, None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    if values.empty:
        return None, None
    return round(float(values.mean()), 6), round(float(values.median()), 6)


def _trade_rows(records: list[StrategyTradeRecord]) -> pd.DataFrame:
    columns = [item.name for item in fields(StrategyTradeRecord)]
    frame = pd.DataFrame([record.to_dict() for record in records], columns=columns)
    if frame.empty:
        return frame
    return frame.sort_values(
        ["ticker", "entry_signal_information_date", "trade_sequence", "trade_id"],
        kind="mergesort",
    ).reset_index(drop=True)


def _summary(
    frame: pd.DataFrame,
    *,
    raw_sha256: str,
    validation: Mapping[str, Any],
    network_requests: int,
    loader_count: int,
    authority_sha256: str,
    authority_interval_count: int,
    common_start_date: pd.Timestamp = COMMON_START_DATE,
    signal_end_date: pd.Timestamp = SIGNAL_END_DATE,
    execution_support_end_date: pd.Timestamp = EXECUTION_SUPPORT_END_DATE,
    output_dir: Path = CONTROL_DIR,
    window_id: str | None = None,
) -> dict[str, Any]:
    total = len(frame)
    terminal = pd.to_numeric(frame["terminal_return"], errors="coerce") if total else pd.Series(dtype=float)
    mean_return, median_return = _numeric_stats(frame, "terminal_return")
    mean_mfe, median_mfe = _numeric_stats(frame, "mfe")
    mean_mae, median_mae = _numeric_stats(frame, "mae")
    mean_holding, median_holding = _numeric_stats(frame, "holding_trading_days")
    positive = int((terminal > 0).sum()) if total else 0
    negative = int((terminal < 0).sum()) if total else 0
    zero = int((terminal == 0).sum()) if total else 0
    sequence = pd.to_numeric(frame["trade_sequence"], errors="coerce") if total else pd.Series(dtype=float)
    exits = frame["exit_type"].value_counts().sort_index().to_dict() if total else {}
    tail = {
        "terminal_return_le_neg_15_pct_points": int((terminal <= -15.0).sum()) if total else 0,
        "terminal_return_le_neg_20_pct_points": int((terminal <= -20.0).sum()) if total else 0,
        "terminal_return_le_neg_30_pct_points": int((terminal <= -30.0).sum()) if total else 0,
        "terminal_return_le_neg_40_pct_points": int((terminal <= -40.0).sum()) if total else 0,
    }
    winners = {
        "terminal_return_ge_pos_30_pct_points": int((terminal >= 30.0).sum()) if total else 0,
        "terminal_return_ge_pos_50_pct_points": int((terminal >= 50.0).sum()) if total else 0,
        "terminal_return_ge_pos_100_pct_points": int((terminal >= 100.0).sum()) if total else 0,
    }
    validation_payload = dict(validation)
    validation_payload.update({
        "fundamentals_references": 0,
        "network_calls": network_requests,
    })
    summary = {
        "work_id": WORK_ID,
        "status": "COMPLETE" if network_requests == 0 and all(value == 0 for value in validation.values()) else "BLOCKED",
        "common_start_date": common_start_date.strftime("%Y-%m-%d"),
        "signal_end_date": signal_end_date.strftime("%Y-%m-%d"),
        "execution_support_end_date": execution_support_end_date.strftime("%Y-%m-%d"),
        "raw_candidate_count": EXPECTED_RAW_ROWS,
        "raw_candidate_sha256": raw_sha256,
        "strategy_id": STRATEGY_ID,
        "loss_guard_enabled": True,
        "fundamentals_gate": "OFF",
        "experimental_investability_conditions": {
            "market_cap_min_krw": 300_000_000_000,
            "avg_trading_value_20d_min_krw": 300_000_000,
            "close_min_krw": 5_000,
        },
        "execution_semantics": "next local trading day open",
        "reentry_semantics": "V2 re-entry after realized exit; no overlap or pyramiding",
        "return_unit": "percentage_points",
        "total_trades": total,
        "unique_tickers": int(frame["ticker"].nunique()) if total else 0,
        "first_entry_count": int((sequence == 1).sum()) if total else 0,
        "reentry_count": int((sequence > 1).sum()) if total else 0,
        "closed_trade_count": int((frame["trade_status"] == "REALIZED").sum()) if total else 0,
        "open_at_cutoff_count": int((frame["trade_status"] == "OPEN_AT_CUTOFF").sum()) if total else 0,
        "positive_trade_count": positive,
        "negative_trade_count": negative,
        "zero_trade_count": zero,
        "positive_trade_rate": round(positive / total * 100, 6) if total else None,
        "mean_terminal_return": mean_return,
        "median_terminal_return": median_return,
        "mean_mfe": mean_mfe,
        "median_mfe": median_mfe,
        "mean_mae": mean_mae,
        "median_mae": median_mae,
        "mean_holding_trading_days": mean_holding,
        "median_holding_trading_days": median_holding,
        "loss_guard_trade_count": int(frame["loss_guard_triggered"].fillna(False).astype(bool).sum()) if total else 0,
        "exit_type_counts": {str(key): int(value) for key, value in exits.items()},
        "tail_counts": tail,
        "winner_counts": winners,
        "network_call_counts": {
            "krx_open_api": 0,
            "opendart": 0,
            "pykrx": 0,
            "naver": 0,
            "krx_html": 0,
            "socket_attempts": network_requests,
            "repository_v2_local_loads": loader_count,
        },
        "authority": {
            "effective_pit_sha256": authority_sha256,
            "effective_pit_interval_count": authority_interval_count,
        },
        "validation": validation_payload,
        "determinism": {"status": "PENDING"},
        "artifacts": {
            "control_trades_csv": str((output_dir / "control_trades.csv").relative_to(ROOT)),
            "control_summary_json": str((output_dir / "control_summary.json").relative_to(ROOT)),
        },
    }
    if window_id is not None:
        summary["window_id"] = window_id
        summary["window_calendar_start"] = STANDARD_BACKTEST_WINDOWS[window_id].calendar_start.strftime("%Y-%m-%d")
        summary["window_calendar_end"] = STANDARD_BACKTEST_WINDOWS[window_id].calendar_end.strftime("%Y-%m-%d")
    return summary


def run_pipeline(run_window: RunnerWindow | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    common_start_date = run_window.common_start_date if run_window else COMMON_START_DATE
    signal_end_date = run_window.signal_end_date if run_window else SIGNAL_END_DATE
    execution_support_end_date = run_window.execution_support_end_date if run_window else EXECUTION_SUPPORT_END_DATE
    market_calendar = run_window.market_calendar if run_window else None
    output_dir = run_window.output_dir if run_window else CONTROL_DIR
    candidates = validate_frozen_inputs()
    if run_window is not None:
        readiness = candidate_artifact_window_readiness(candidates, run_window)
        if readiness["status"] != "READY":
            raise RuntimeError(
                f"{readiness['status']}: {run_window.window_id}: "
                f"{'; '.join(readiness['reasons'])}"
            )
    authority = load_effective_authority(EFFECTIVE_AUTHORITY_DIR)
    intervals = _authority_intervals(authority, execution_support_end_date)
    tasks_by_ticker = _tasks_by_ticker(candidates, common_start_date, signal_end_date)
    score_contract = _json_read(SCORE_CONTRACT_PATH)
    stage_contract = _json_read(STAGE_CONTRACT_PATH)
    repository = build_repository_v2(ROOT, end=execution_support_end_date)
    loader = RepositoryV2DailyLoader(repository, end=execution_support_end_date)
    records: list[StrategyTradeRecord] = []
    validation = {
        "pre_start_entry_violations": 0,
        "post_end_signal_violations": 0,
        "identity_violations": 0,
        "execution_next_day_violations": 0,
        "overlapping_positions": 0,
        "pit_future_membership_fallback": 0,
        "fundamentals_references": 0,
    }
    tickers = set(tasks_by_ticker)
    started = time.monotonic()
    processed = 0
    for ticker in sorted(tickers):
        tasks = tasks_by_ticker.get(str(ticker), [])
        daily = loader.load(str(ticker))
        if daily is None or daily.empty:
            raise RuntimeError(f"missing Repository V2 daily data for raw candidate ticker {ticker}")
        for task in tasks:
            lifecycle = IdentityLifecycle(
                ticker=str(task["ticker"]),
                isu_cd=str(task["isu_cd"]),
                market=str(task["market"]),
                effective_from=pd.Timestamp(task["effective_from"]),
                effective_to=pd.Timestamp(task["effective_to"]),
            )
            raw_panel = task["raw_panel"]
            gate = _candidate_gate(
                ticker=lifecycle.ticker,
                isu_cd=lifecycle.isu_cd,
                market=lifecycle.market,
                allowed_candidate_ids=task["allowed_candidate_ids"],
                common_start_date=common_start_date,
                signal_end_date=signal_end_date,
            )
            task_records = simulate_ticker_strategy_fundamentals_v01(
                strategy_id=STRATEGY_ID,
                ticker=lifecycle.ticker,
                isu_cd=lifecycle.isu_cd,
                name=str(task["name"]),
                market=lifecycle.market,
                daily=daily,
                raw_panel=raw_panel,
                score_contract=score_contract,
                stage_contract=stage_contract,
                loss_guard_enabled=True,
                backtest_end=execution_support_end_date,
                entry_eligible_from=common_start_date,
                allowed_signal_dates=task["allowed_signal_dates"],
                identity_lifecycle=lifecycle,
                pit_membership=lambda ticker_value, isu_value, market_value, value: pit_common_for_identity(
                    intervals, ticker_value, isu_value, market_value, value,
                ),
                entry_gate=gate,
                market_calendar=market_calendar,
            )
            task_validation = _validate_records(
                task_records,
                daily=daily,
                lifecycle=lifecycle,
                intervals=intervals,
                common_start_date=common_start_date,
                signal_end_date=signal_end_date,
                execution_support_end_date=execution_support_end_date,
            )
            for key in ("pre_start_entry_violations", "post_end_signal_violations", "identity_violations", "execution_next_day_violations", "pit_membership_violations"):
                target = "pit_future_membership_fallback" if key == "pit_membership_violations" else key
                validation[target] += task_validation[key]
            records.extend(task_records)
            del raw_panel
        processed += 1
        if processed % 50 == 0:
            print(f"CONTROL progress: {processed}/{len(tickers)} tickers, trades={len(records)}, elapsed={time.monotonic() - started:.1f}s", flush=True)
        del daily

    validation["overlapping_positions"] = _overlap_count(records)
    frame = _trade_rows(records)
    summary = _summary(
        frame,
        raw_sha256=sha256_file(RAW_CANDIDATE_PATH),
        validation=validation,
        network_requests=0,
        loader_count=loader.load_count,
        authority_sha256=authority.pit_sha256,
        authority_interval_count=authority.pit_count,
        common_start_date=common_start_date,
        signal_end_date=signal_end_date,
        execution_support_end_date=execution_support_end_date,
        output_dir=output_dir,
        window_id=run_window.window_id if run_window else None,
    )
    print(f"CONTROL complete: tickers={processed}, trades={len(frame)}, elapsed={time.monotonic() - started:.1f}s", flush=True)
    return frame, summary


def write_outputs(frame: pd.DataFrame, summary: Mapping[str, Any]) -> None:
    trades_path = ROOT / str(summary["artifacts"]["control_trades_csv"])
    summary_path = ROOT / str(summary["artifacts"]["control_summary_json"])
    trades_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(trades_path, index=False, lineterminator="\n")
    _json_write(summary_path, summary)


def verify_determinism(run_window: RunnerWindow | None = None) -> int:
    output_dir = run_window.output_dir if run_window else CONTROL_DIR
    trades_path = output_dir / "control_trades.csv"
    summary_path = output_dir / "control_summary.json"
    expected_trades = trades_path.read_bytes()
    expected_summary = _json_read(summary_path)
    frame, replay_summary = run_pipeline(run_window)
    replay_csv = frame.to_csv(index=False, lineterminator="\n").encode("utf-8")
    trade_content_same = replay_csv == expected_trades
    summary_keys = [key for key in replay_summary if key != "determinism"]
    summary_core_same = all(replay_summary.get(key) == expected_summary.get(key) for key in summary_keys)
    if not trade_content_same or not summary_core_same or replay_summary.get("status") != "COMPLETE":
        result = {
            "status": "FAIL",
            "trade_row_count_same": len(frame) == len(pd.read_csv(trades_path)),
            "trade_content_same": trade_content_same,
            "summary_core_same": summary_core_same,
        }
        print(f"CONTROL determinism: {json.dumps(result, ensure_ascii=False)}", flush=True)
        return 1
    result = {
        "status": "PASS",
        "trade_row_count_same": True,
        "trade_content_same": True,
        "summary_core_same": True,
    }
    print(f"CONTROL determinism: {json.dumps(result, ensure_ascii=False)}", flush=True)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-determinism", action="store_true")
    parser.add_argument("--window", choices=tuple(STANDARD_BACKTEST_WINDOWS))
    parser.add_argument(
        "--resolve-only",
        action="store_true",
        help="Resolve one standard window and inspect frozen candidate date coverage without running the backtest.",
    )
    args = parser.parse_args(argv)
    if args.resolve_only and not args.window:
        parser.error("--resolve-only requires --window")
    audit = NetworkAudit()
    try:
        with network_guard(audit):
            run_window = resolve_runner_window(args.window) if args.window else None
            if args.resolve_only:
                candidates = validate_frozen_inputs()
                readiness = candidate_artifact_window_readiness(candidates, run_window)
                resolution = run_window.resolution
                print(json.dumps({
                    "window_id": run_window.window_id,
                    "calendar_start": resolution.window.calendar_start.strftime("%Y-%m-%d"),
                    "effective_start": resolution.effective_start.strftime("%Y-%m-%d"),
                    "calendar_end": resolution.window.calendar_end.strftime("%Y-%m-%d"),
                    "effective_end": resolution.effective_end.strftime("%Y-%m-%d"),
                    "execution_support": resolution.execution_support.strftime("%Y-%m-%d"),
                    "calendar_authority": run_window.market_calendar.source_name,
                    "calendar_certified_through": run_window.market_calendar.metadata.get("certified_through"),
                    "warmup_policy": "Repository V2 ticker history before effective_start is retained; identity lifecycle remains authoritative.",
                    "runner_accepts_window": True,
                    "runner_readiness": readiness,
                    "backtest_executed": False,
                }, ensure_ascii=False, sort_keys=True))
                return 0
            if args.verify_determinism:
                return verify_determinism(run_window)
            frame, summary = run_pipeline(run_window)
            summary["network_call_counts"]["socket_attempts"] = audit.request_count
            summary["validation"]["network_calls"] = audit.request_count
            if audit.request_count:
                summary["status"] = "BLOCKED"
            write_outputs(frame, summary)
            return 0 if summary["status"] == "COMPLETE" else 1
    except Exception as exc:
        print(f"CONTROL BLOCKED: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
