#!/usr/bin/env python3
"""Generate the local-only FastCore CONTROL baseline for FIX05.

This runner deliberately consumes the frozen raw candidate artifact and the
canonical local Repository V2 only.  It does not import or call Fundamentals,
OpenDART, KRX, PyKRX, Naver, or any other network-backed source.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import fields
import hashlib
import json
from pathlib import Path
import socket
import time
from typing import Any, Iterator, Mapping
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
from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader, build_repository_v2


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


def _authority_intervals(authority: Any) -> dict[tuple[str, str, str], list[tuple[str, str]]]:
    intervals: dict[tuple[str, str, str], list[tuple[str, str]]] = {}
    for item in authority.pit_intervals:
        if item.get("state") != "COMMON":
            continue
        start = str(item["effective_from"])
        stop = str(item["effective_to"])
        if start > EXECUTION_SUPPORT_END_DATE.strftime("%Y-%m-%d"):
            continue
        key = (str(item["ticker"]), str(item["isu_cd"]), str(item["market"]))
        intervals.setdefault(key, []).append((start, stop))
    for values in intervals.values():
        values.sort()
    return intervals


def _tasks_by_ticker(candidates: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    group_columns = ["ticker", "isu_cd", "market", "identity_effective_from", "identity_effective_to"]
    result: dict[str, list[dict[str, Any]]] = {}
    for key, group in candidates.groupby(group_columns, sort=True, dropna=False):
        ticker, isu_cd, market, effective_from, effective_to = key
        allowed = frozenset(
            frozen_candidate_id(ticker, isu_cd, market, value)
            for value in group["candidate_signal_date"].tolist()
            if COMMON_START_DATE <= pd.Timestamp(value) <= SIGNAL_END_DATE
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
                if COMMON_START_DATE <= pd.Timestamp(value) <= SIGNAL_END_DATE
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
):
    def gate(_as_of: pd.Timestamp, context: dict[str, Any]) -> dict[str, Any]:
        signal_date = pd.Timestamp(context["signal_date"]).normalize()
        candidate_id = frozen_candidate_id(ticker, isu_cd, market, signal_date)
        return {
            "gate_pass": candidate_id in allowed_candidate_ids
            and COMMON_START_DATE <= signal_date <= SIGNAL_END_DATE,
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
        & (daily.index <= EXECUTION_SUPPORT_END_DATE)
    ]
    for record in records:
        info_date = pd.Timestamp(record.entry_signal_information_date)
        signal_date = pd.Timestamp(record.entry_signal_date)
        if info_date < COMMON_START_DATE:
            violations["pre_start_entry_violations"] += 1
        if info_date > SIGNAL_END_DATE:
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
    return {
        "work_id": WORK_ID,
        "status": "COMPLETE" if network_requests == 0 and all(value == 0 for value in validation.values()) else "BLOCKED",
        "common_start_date": COMMON_START_DATE.strftime("%Y-%m-%d"),
        "signal_end_date": SIGNAL_END_DATE.strftime("%Y-%m-%d"),
        "execution_support_end_date": EXECUTION_SUPPORT_END_DATE.strftime("%Y-%m-%d"),
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
            "control_trades_csv": str(CONTROL_TRADES_PATH.relative_to(ROOT)),
            "control_summary_json": str(CONTROL_SUMMARY_PATH.relative_to(ROOT)),
        },
    }


def run_pipeline() -> tuple[pd.DataFrame, dict[str, Any]]:
    candidates = validate_frozen_inputs()
    authority = load_effective_authority(EFFECTIVE_AUTHORITY_DIR)
    intervals = _authority_intervals(authority)
    tasks_by_ticker = _tasks_by_ticker(candidates)
    score_contract = _json_read(SCORE_CONTRACT_PATH)
    stage_contract = _json_read(STAGE_CONTRACT_PATH)
    repository = build_repository_v2(ROOT, end=EXECUTION_SUPPORT_END_DATE)
    loader = RepositoryV2DailyLoader(repository, end=EXECUTION_SUPPORT_END_DATE)
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
                backtest_end=EXECUTION_SUPPORT_END_DATE,
                entry_eligible_from=COMMON_START_DATE,
                allowed_signal_dates=task["allowed_signal_dates"],
                identity_lifecycle=lifecycle,
                pit_membership=lambda ticker_value, isu_value, market_value, value: pit_common_for_identity(
                    intervals, ticker_value, isu_value, market_value, value,
                ),
                entry_gate=gate,
            )
            task_validation = _validate_records(task_records, daily=daily, lifecycle=lifecycle, intervals=intervals)
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
    )
    print(f"CONTROL complete: tickers={processed}, trades={len(frame)}, elapsed={time.monotonic() - started:.1f}s", flush=True)
    return frame, summary


def write_outputs(frame: pd.DataFrame, summary: Mapping[str, Any]) -> None:
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_csv(CONTROL_TRADES_PATH, index=False, lineterminator="\n")
    _json_write(CONTROL_SUMMARY_PATH, summary)


def verify_determinism() -> int:
    expected_trades = CONTROL_TRADES_PATH.read_bytes()
    expected_summary = _json_read(CONTROL_SUMMARY_PATH)
    frame, replay_summary = run_pipeline()
    replay_csv = frame.to_csv(index=False, lineterminator="\n").encode("utf-8")
    trade_content_same = replay_csv == expected_trades
    summary_keys = [key for key in replay_summary if key != "determinism"]
    summary_core_same = all(replay_summary.get(key) == expected_summary.get(key) for key in summary_keys)
    if not trade_content_same or not summary_core_same or replay_summary.get("status") != "COMPLETE":
        expected_summary["status"] = "BLOCKED"
        expected_summary["determinism"] = {
            "status": "FAIL",
            "trade_row_count_same": len(frame) == len(pd.read_csv(CONTROL_TRADES_PATH)),
            "trade_content_same": trade_content_same,
            "summary_core_same": summary_core_same,
        }
        _json_write(CONTROL_SUMMARY_PATH, expected_summary)
        return 1
    expected_summary["determinism"] = {
        "status": "PASS",
        "trade_row_count_same": True,
        "trade_content_same": True,
        "summary_core_same": True,
    }
    _json_write(CONTROL_SUMMARY_PATH, expected_summary)
    print("CONTROL determinism: PASS", flush=True)
    return 0


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-determinism", action="store_true")
    args = parser.parse_args()
    audit = NetworkAudit()
    try:
        with network_guard(audit):
            if args.verify_determinism:
                return verify_determinism()
            frame, summary = run_pipeline()
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
