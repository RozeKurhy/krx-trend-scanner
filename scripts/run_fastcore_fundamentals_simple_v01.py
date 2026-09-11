#!/usr/bin/env python3
"""FASTCORE_SIMPLE_BACKTEST_WITH_FUNDAMENTALS_V01_FIX01.

This runner is intentionally research-scoped.  It uses the corrected
historical PIT universe and Repository V2 market data, then evaluates the
existing Fundamentals V1 boundary at each raw FastCore entry/re-entry
candidate.  The coverage scan is completed before either return backtest is
started; no start date is selected from returns.

OpenDART access, when needed, is bounded to filing/XBRL data for candidate
companies and fiscal years from 2015 onward.  Market data is local-only.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from datetime import date, datetime, timezone
import gc
import json
import logging
import os
from pathlib import Path
import resource
import shutil
import subprocess
import time
from typing import Any, Iterable, Mapping
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

import pandas as pd

from trend_scanner.backtest.fastcore_fundamentals_simple_v01 import (
    AVG_TRADING_VALUE_20D_THRESHOLD,
    CLOSE_THRESHOLD,
    MARKET_CAP_THRESHOLD,
    IdentityLifecycle,
    pit_common_for_identity,
    simulate_ticker_strategy_fundamentals_v01,
)
from trend_scanner.backtest.raw_investability_panel import (
    build_raw_investability_panel,
    iter_raw_investability_panels,
    recompute_identity_scoped_avg_trading_value_20d,
    evaluate_entry_filter,
)
from trend_scanner.backtest.snapshot_context import build_precomputed_ticker_context
from trend_scanner.data.adjusted_price_authority_cutover import load_effective_authority
from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader, build_repository_v2
from trend_scanner.fundamentals.corp_code_repository import CorpCodeRepository
from trend_scanner.fundamentals.derived_metrics import DerivedMetricsEngine, DerivedMetricsResult
from trend_scanner.fundamentals.filing_registry import FilingRegistry
from trend_scanner.fundamentals.fundamentals_filter import (
    DATA_UNAVAILABLE,
    FILTERED_ANNUAL_REVENUE,
    FILTERED_NET_LOSS,
    FILTERED_OPERATING_LOSS,
    FILTERED_QUARTERLY_REVENUE,
    FundamentalsFilter,
    NOT_APPLICABLE,
    PASS,
)
from trend_scanner.fundamentals.multi_period import build_multi_period_result
from trend_scanner.fundamentals.opendart_contract import CompanyFamily, classify_company_family
from trend_scanner.fundamentals.opendart_client import OpenDartClient
from trend_scanner.fundamentals.periodization_provider import PeriodizationProvider
from trend_scanner.fundamentals.xbrl_repository import XbrlRepository
from trend_scanner.patterns.pattern_a_fast_evaluator import evaluate_pattern_a_fast
from trend_scanner.universe.instrument_metadata import InstrumentMetadataResolver

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
EFFECTIVE_AUTHORITY_DIR = ROOT / "artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/v01_spac_corrected_effective_authority"
EFFECTIVE_PIT_PATH = EFFECTIVE_AUTHORITY_DIR / "effective_pit_common_denominator.json"
SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"
CORP_CACHE_PATH = ROOT / "data/cache/opendart/corp_code_cache.json"
COMPANY_CACHE_DIR = ROOT / "data/cache/opendart/company"
OPENDART_FILINGS_DIR = ROOT / "data/cache/opendart/filings"
OPENDART_XBRL_DIR = ROOT / "data/cache/opendart/xbrl"
OUT_DIR = ROOT / "artifacts/backtests/fastcore_fundamentals_simple_v01"
RAW_CANDIDATE_DIR = OUT_DIR / "raw_candidates"
RAW_CANDIDATE_PATH = RAW_CANDIDATE_DIR / "fastcore_raw_candidates.csv"
RAW_CANDIDATE_CHECKPOINT_PATH = RAW_CANDIDATE_DIR / "scan_checkpoint.json"
FUNDAMENTALS_COVERAGE_DIR = OUT_DIR / "fundamentals_coverage"
FUNDAMENTALS_COVERAGE_CANDIDATE_PATH = FUNDAMENTALS_COVERAGE_DIR / "fundamentals_candidate_evaluability.csv"
FUNDAMENTALS_COVERAGE_QUARTER_PATH = FUNDAMENTALS_COVERAGE_DIR / "fundamentals_coverage_by_quarter.csv"
FUNDAMENTALS_COVERAGE_SUMMARY_PATH = FUNDAMENTALS_COVERAGE_DIR / "fundamentals_coverage_summary.json"
FUNDAMENTALS_COVERAGE_CHECKPOINT_PATH = FUNDAMENTALS_COVERAGE_DIR / "coverage_checkpoint.json"
BACKTEST_END = pd.Timestamp("2026-08-21")
FUNDAMENTALS_HISTORY_START = pd.Timestamp("2015-01-01")
MAX_WORKERS = 1
CANDIDATE_BATCH_SIZE = 25
FUNDAMENTALS_COVERAGE_BATCH_SIZE = 25
FIX04_WORK_ID = "FASTCORE_SIMPLE_BACKTEST_WITH_FUNDAMENTALS_V01_FIX04_COVERAGE"
FUNDAMENTALS_EVALUABLE = {
    PASS,
    FILTERED_ANNUAL_REVENUE,
    FILTERED_QUARTERLY_REVENUE,
    FILTERED_OPERATING_LOSS,
    FILTERED_NET_LOSS,
}
QUARTER_LABELS = ("Q1", "Q2", "Q3", "Q4")


def _json_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default


def _date_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OverflowError):
        return None


def _load_authority() -> tuple[Any, dict[tuple[str, str, str], list[tuple[str, str]]], list[dict[str, Any]]]:
    authority = load_effective_authority(EFFECTIVE_AUTHORITY_DIR)
    intervals: dict[tuple[str, str, str], list[tuple[str, str]]] = {}
    tasks: list[dict[str, Any]] = []
    for item in authority.pit_intervals:
        if item.get("state") != "COMMON":
            continue
        if str(item.get("effective_from")) > BACKTEST_END.strftime("%Y-%m-%d"):
            continue
        key = (str(item["ticker"]), str(item["isu_cd"]), str(item["market"]))
        interval = (str(item["effective_from"]), str(item["effective_to"]))
        intervals.setdefault(key, []).append(interval)
        tasks.append({
            "ticker": key[0], "isu_cd": key[1], "market": key[2],
            "effective_from": interval[0], "effective_to": interval[1],
        })
    for values in intervals.values():
        values.sort()
    tasks.sort(key=lambda item: (item["ticker"], item["effective_from"], item["effective_to"]))
    return authority, intervals, tasks


def _name_map() -> dict[str, str]:
    df = InstrumentMetadataResolver.load_master_dataframe(ROOT)
    if df.empty or "ticker" not in df.columns:
        return {}
    frame = df.copy()
    frame["ticker"] = frame["ticker"].astype(str).str.strip()
    frame = frame.drop_duplicates("ticker", keep="last")
    return {
        str(row.ticker): str(row.name) if str(row.name) not in {"", "nan", "None"} else str(row.ticker)
        for row in frame.itertuples(index=False)
    }


# Forked workers inherit these read-only run-scoped values.  No worker opens
# a market network connection or mutates a source store.
_LOADER: RepositoryV2DailyLoader | None = None
_RAW_PANELS: dict[str, pd.DataFrame] = {}
_PIT_INTERVALS: dict[tuple[str, str, str], list[tuple[str, str]]] = {}
_SCORE_CONTRACT: dict[str, Any] = {}
_STAGE_CONTRACT: dict[str, Any] = {}


def _candidate_worker(
    task: Mapping[str, Any], *, raw_panel: pd.DataFrame | None = None,
) -> list[dict[str, Any]]:
    ticker = str(task["ticker"])
    isu_cd = str(task["isu_cd"])
    market = str(task["market"])
    name = str(task.get("name") or ticker)
    lifecycle = IdentityLifecycle(
        ticker=ticker, isu_cd=isu_cd, market=market,
        effective_from=pd.Timestamp(task["effective_from"]),
        effective_to=pd.Timestamp(task["effective_to"]),
    )
    if _LOADER is None:
        return []
    daily = _LOADER.load(ticker)
    if daily is None or daily.empty:
        return []
    daily = daily[(daily.index >= lifecycle.effective_from) & (daily.index <= lifecycle.effective_to) & (daily.index <= BACKTEST_END)].copy()
    if len(daily) < 60 or not {"open", "high", "low", "close"}.issubset(daily.columns):
        return []
    if raw_panel is None:
        raw_panel = _RAW_PANELS.get(ticker)
    if raw_panel is None:
        return []
    raw_panel = raw_panel[(raw_panel.index >= lifecycle.effective_from) & (raw_panel.index <= lifecycle.effective_to) & (raw_panel.index <= BACKTEST_END)].copy()
    if raw_panel.empty or raw_panel.index.has_duplicates:
        return []
    raw_panel = recompute_identity_scoped_avg_trading_value_20d(raw_panel)
    context = build_precomputed_ticker_context(ticker, name, daily)
    weekly = context.weekly_up_to(BACKTEST_END)
    daily_dates = set(pd.DatetimeIndex(daily.index).normalize())
    valid_weeks = [pd.Timestamp(w).normalize() for w in weekly.index if pd.Timestamp(w).normalize() in daily_dates]
    candidates: list[dict[str, Any]] = []
    for week in valid_weeks:
        if week < FUNDAMENTALS_HISTORY_START:
            continue
        try:
            # The raw entry-only filter is a cheap, strict precondition.  It
            # avoids evaluating Pattern A/FAST for weeks that cannot be an
            # entry while preserving the candidate set exactly.
            filt = evaluate_entry_filter(
                raw_panel, week,
                market_cap_threshold=MARKET_CAP_THRESHOLD,
                avg_trading_value_threshold=AVG_TRADING_VALUE_20D_THRESHOLD,
                close_threshold=CLOSE_THRESHOLD,
            )
            raw_date = filt.get("entry_filter_raw_date")
            if not filt["entry_filter_pass"] or raw_date is None:
                continue
            info_dates = daily.index[daily.index <= week]
            if len(info_dates) == 0:
                continue
            signal_info = pd.Timestamp(info_dates[-1]).normalize()
            if pd.Timestamp(raw_date) > signal_info or not pit_common_for_identity(_PIT_INTERVALS, ticker, isu_cd, market, pd.Timestamp(raw_date)):
                continue
            if not pit_common_for_identity(_PIT_INTERVALS, ticker, isu_cd, market, signal_info):
                continue
            result = evaluate_pattern_a_fast(
                ticker, name, daily, week, _SCORE_CONTRACT, _STAGE_CONTRACT, context=context,
            )
            if not (
                result.get("fast_machine_stage") == "TRIGGER"
                and result.get("fast_machine_stage_status") == "READY"
                and result.get("fast_monthly_permission_state") == "PERMITTED_REGIME"
                and result.get("fast_daily_risk_state") in {"NORMAL", "ELEVATED"}
                and result.get("fast_score_status") in {"READY", "PARTIAL"}
                and str(result.get("pattern_a_stage") or "").upper() in {"TRANSITION", "EARLY_TREND"}
            ):
                continue
            future = daily[(daily.index > week) & (daily.index <= BACKTEST_END)]
            if future.empty or not pit_common_for_identity(_PIT_INTERVALS, ticker, isu_cd, market, future.index[0]):
                continue
            row = {
                "candidate_id": f"{ticker}|{isu_cd}|{market}|{week.strftime('%Y-%m-%d')}",
                "ticker": ticker, "isu_cd": isu_cd, "market": market, "name": name,
                "candidate_signal_date": week.strftime("%Y-%m-%d"),
                "candidate_signal_information_date": signal_info.strftime("%Y-%m-%d"),
                "fundamentals_as_of": signal_info.strftime("%Y-%m-%d"),
                "entry_signal_information_date": signal_info.strftime("%Y-%m-%d"),
                "entry_filter_raw_date": _date_text(raw_date),
                "identity_effective_from": lifecycle.effective_from.strftime("%Y-%m-%d"),
                "identity_effective_to": lifecycle.effective_to.strftime("%Y-%m-%d"),
                "entry_market_cap": filt["entry_market_cap"],
                "entry_avg_trading_value_20d": filt["entry_avg_trading_value_20d"],
                "entry_signal_close": filt["entry_signal_close"],
                "entry_pattern_a_stage": str(result.get("pattern_a_stage") or "").upper(),
                "fast_stage": result.get("fast_machine_stage"),
                "fast_status": result.get("fast_machine_stage_status"),
                "monthly_permission_state": result.get("fast_monthly_permission_state"),
                "daily_risk": result.get("fast_daily_risk_state"),
                "fast_score": result.get("fast_score"),
                "fast_score_state": result.get("fast_score_status"),
                "entry_market_cap_pass": filt["entry_market_cap_pass"],
                "entry_trading_value_pass": filt["entry_trading_value_pass"],
                "entry_close_pass": filt["entry_close_pass"],
                # Canonical raw-candidate field names.  The entry_* aliases
                # above remain for compatibility with the later coverage
                # phase, while this phase's artifact uses the exact FIX02
                # minimum field contract.
                "pattern_a_stage": str(result.get("pattern_a_stage") or "").upper(),
                "fast_machine_stage": result.get("fast_machine_stage"),
                "fast_machine_status": result.get("fast_machine_stage_status"),
                "monthly_permission_state": result.get("fast_monthly_permission_state"),
                "daily_risk_state": result.get("fast_daily_risk_state"),
                "fast_score_status": result.get("fast_score_status"),
                "market_cap": filt["entry_market_cap"],
                "avg_trading_value_20d": filt["entry_avg_trading_value_20d"],
                "signal_close": filt["entry_signal_close"],
                "market_cap_pass": filt["entry_market_cap_pass"],
                "trading_value_pass": filt["entry_trading_value_pass"],
                "close_pass": filt["entry_close_pass"],
                "investability_pass": filt["entry_filter_pass"],
            }
            candidates.append(row)
        except Exception:
            continue
    return candidates


def _parent_rss_mb() -> float | None:
    """Return this process' maximum RSS without importing a monitor library."""
    try:
        value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        # macOS reports bytes; Linux reports KiB.
        return value / (1024.0 * 1024.0 if os.uname().sysname == "Darwin" else 1024.0)
    except (AttributeError, OSError, ValueError):
        return None


def _memory_pressure_summary() -> str:
    """Best-effort macOS memory-pressure observation for progress logs."""
    executable = shutil.which("memory_pressure")
    if executable is None:
        return "unavailable"
    try:
        completed = subprocess.run(
            [executable, "-Q"], capture_output=True, text=True, timeout=3, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    for line in completed.stdout.splitlines():
        if "free percentage" in line.lower():
            return " ".join(line.split())[:160]
    return "observed"


def _ticker_ever_investable(raw_panel: pd.DataFrame | None) -> bool:
    if raw_panel is None or raw_panel.empty or raw_panel.index.has_duplicates:
        return False
    mask = (
        (pd.to_numeric(raw_panel["market_cap"], errors="coerce") >= MARKET_CAP_THRESHOLD)
        & (pd.to_numeric(raw_panel["avg_trading_value_20d"], errors="coerce") >= AVG_TRADING_VALUE_20D_THRESHOLD)
        & (pd.to_numeric(raw_panel["close"], errors="coerce") >= CLOSE_THRESHOLD)
    )
    return bool(mask.any())


def _append_candidate_batch(rows: list[dict[str, Any]], *, path: Path) -> None:
    """Append one bounded batch and never retain prior batches in Python."""
    if not rows:
        return
    frame = pd.DataFrame(rows).sort_values("candidate_id", kind="mergesort")
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, mode="a", header=not path.exists(), index=False)
    del frame


def _write_scan_checkpoint(
    *,
    completed_tickers: set[str],
    completed_task_keys: set[str],
    completed_identity_count: int,
    prefiltered_identity_count: int,
    candidate_count: int,
    status: str,
    total_identity_intervals: int,
) -> None:
    _json_write(
        RAW_CANDIDATE_CHECKPOINT_PATH,
        {
            "work_id": "FASTCORE_SIMPLE_BACKTEST_WITH_FUNDAMENTALS_V01_FIX02_OOM",
            "status": status,
            "backtest_end": BACKTEST_END.strftime("%Y-%m-%d"),
            "total_identity_intervals": total_identity_intervals,
            "completed_identity_count": completed_identity_count,
            "prefiltered_identity_count": prefiltered_identity_count,
            "candidate_count": candidate_count,
            "completed_tickers": sorted(completed_tickers),
            "completed_task_keys": sorted(completed_task_keys),
            "max_workers": MAX_WORKERS,
            "batch_size": CANDIDATE_BATCH_SIZE,
        },
    )


def scan_raw_candidates(tasks: list[dict[str, Any]], intervals: dict[tuple[str, str, str], list[tuple[str, str]]]) -> pd.DataFrame:
    """Collect raw candidates with one worker, bounded batches, and disk flushes."""
    global _LOADER, _RAW_PANELS, _PIT_INTERVALS, _SCORE_CONTRACT, _STAGE_CONTRACT
    _PIT_INTERVALS = intervals
    _SCORE_CONTRACT = _read_json(SCORE_CONTRACT_PATH, {})
    _STAGE_CONTRACT = _read_json(STAGE_CONTRACT_PATH, {})
    _LOADER = RepositoryV2DailyLoader(build_repository_v2(ROOT, end=BACKTEST_END), end=BACKTEST_END)
    RAW_CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)

    checkpoint = _read_json(RAW_CANDIDATE_CHECKPOINT_PATH, {})
    completed_tickers = set(str(item) for item in checkpoint.get("completed_tickers", [])) if isinstance(checkpoint, dict) else set()
    completed_task_keys = set(str(item) for item in checkpoint.get("completed_task_keys", [])) if isinstance(checkpoint, dict) else set()
    completed_identity_count = int(checkpoint.get("completed_identity_count", 0) or 0) if isinstance(checkpoint, dict) else 0
    prefiltered_identity_count = int(checkpoint.get("prefiltered_identity_count", 0) or 0) if isinstance(checkpoint, dict) else 0
    candidate_count = int(checkpoint.get("candidate_count", 0) or 0) if isinstance(checkpoint, dict) else 0
    if checkpoint.get("status") == "COMPLETE" and RAW_CANDIDATE_PATH.exists():
        logger.info("Reusing completed raw candidate scan: %s", RAW_CANDIDATE_PATH)
        return pd.read_csv(RAW_CANDIDATE_PATH, dtype={"ticker": str, "isu_cd": str, "candidate_id": str})
    if RAW_CANDIDATE_PATH.exists() and not completed_tickers:
        raise RuntimeError("raw candidate output exists without a resumable checkpoint")

    tickers = {str(item["ticker"]) for item in tasks}
    names = _name_map()
    tasks_by_ticker: dict[str, list[dict[str, Any]]] = {}
    for item in tasks:
        task = dict(item, name=names.get(str(item["ticker"]), str(item["ticker"])))
        tasks_by_ticker.setdefault(str(task["ticker"]), []).append(task)
    total_identities = len(tasks)
    logger.info(
        "Starting OOM-safe raw candidate scan: %d identity intervals, workers=%d, batch_size=%d",
        total_identities, MAX_WORKERS, CANDIDATE_BATCH_SIZE,
    )
    started = time.monotonic()
    seen_tickers: set[str] = set()
    processed_tickers = 0

    # The iterator holds only compact accumulators plus the currently yielded
    # ticker panel.  It never materializes the complete panel dictionary in
    # this long-running path.
    panel_iterator = iter_raw_investability_panels(
        tickers, end=BACKTEST_END, raw_root=ROOT / "data/market/raw/krx_stocks/v01", identity_intervals=None,
    )
    for ticker, raw_panel in panel_iterator:
        ticker = str(ticker)
        seen_tickers.add(ticker)
        ticker_tasks = tasks_by_ticker.get(ticker, [])
        if not ticker_tasks or ticker in completed_tickers:
            del raw_panel
            continue
        pending_tasks = [
            task for task in ticker_tasks
            if f"{task['ticker']}|{task['isu_cd']}|{task['market']}|{task['effective_from']}|{task['effective_to']}" not in completed_task_keys
        ]
        if not pending_tasks:
            del raw_panel
            continue
        retained_tasks: list[dict[str, Any]] = []
        for task in pending_tasks:
            lifecycle = IdentityLifecycle(
                ticker=ticker, isu_cd=str(task["isu_cd"]), market=str(task["market"]),
                effective_from=pd.Timestamp(task["effective_from"]),
                effective_to=pd.Timestamp(task["effective_to"]),
            )
            clipped = raw_panel.loc[
                (raw_panel.index >= lifecycle.effective_from)
                & (raw_panel.index <= lifecycle.effective_to)
            ].copy()
            if not clipped.empty and not clipped.index.has_duplicates:
                clipped = recompute_identity_scoped_avg_trading_value_20d(clipped)
            if _ticker_ever_investable(clipped):
                retained_tasks.append(task)
            del clipped
        prefiltered_identity_count += len(retained_tasks)
        for offset in range(0, len(retained_tasks), CANDIDATE_BATCH_SIZE):
            batch = retained_tasks[offset : offset + CANDIDATE_BATCH_SIZE]
            batch_rows: list[dict[str, Any]] = []
            for task in batch:
                batch_rows.extend(_candidate_worker(task, raw_panel=raw_panel))
            _append_candidate_batch(batch_rows, path=RAW_CANDIDATE_PATH)
            candidate_count += len(batch_rows)
            completed_task_keys.update(
                f"{task['ticker']}|{task['isu_cd']}|{task['market']}|{task['effective_from']}|{task['effective_to']}"
                for task in batch
            )
            completed_identity_count = len(completed_task_keys)
            del batch_rows, batch
            _write_scan_checkpoint(
                completed_tickers=completed_tickers,
                completed_task_keys=completed_task_keys,
                completed_identity_count=completed_identity_count,
                prefiltered_identity_count=prefiltered_identity_count,
                candidate_count=candidate_count,
                status="RUNNING",
                total_identity_intervals=total_identities,
            )
        completed_task_keys.update(
            f"{task['ticker']}|{task['isu_cd']}|{task['market']}|{task['effective_from']}|{task['effective_to']}"
            for task in pending_tasks
        )
        completed_tickers.add(ticker)
        completed_identity_count = len(completed_task_keys)
        processed_tickers += 1
        rss = _parent_rss_mb()
        pressure = _memory_pressure_summary() if processed_tickers % 25 == 0 else "deferred"
        logger.info(
            "Candidate scan: %d/%d tickers, completed identities=%d/%d, retained=%d, candidates=%d, rss_max_mb=%s, pressure=%s, elapsed=%.1fs",
            processed_tickers, len(tasks_by_ticker), completed_identity_count, total_identities,
            prefiltered_identity_count, candidate_count,
            f"{rss:.1f}" if rss is not None else "NA", pressure, time.monotonic() - started,
        )
        _write_scan_checkpoint(
            completed_tickers=completed_tickers,
            completed_task_keys=completed_task_keys,
            completed_identity_count=completed_identity_count,
            prefiltered_identity_count=prefiltered_identity_count,
            candidate_count=candidate_count,
            status="RUNNING",
            total_identity_intervals=total_identities,
        )
        del retained_tasks, raw_panel
        gc.collect()

    # A missing raw panel is a valid zero-candidate result, but must still be
    # checkpointed so a resumed run does not revisit it forever.
    for ticker, ticker_tasks in tasks_by_ticker.items():
        if ticker in completed_tickers:
            continue
        completed_tickers.add(ticker)
        completed_task_keys.update(
            f"{task['ticker']}|{task['isu_cd']}|{task['market']}|{task['effective_from']}|{task['effective_to']}"
            for task in ticker_tasks
        )
    completed_identity_count = len(completed_task_keys)
    _write_scan_checkpoint(
        completed_tickers=completed_tickers,
        completed_task_keys=completed_task_keys,
        completed_identity_count=completed_identity_count,
        prefiltered_identity_count=prefiltered_identity_count,
        candidate_count=candidate_count,
        status="COMPLETE",
        total_identity_intervals=total_identities,
    )
    if not RAW_CANDIDATE_PATH.exists():
        pd.DataFrame(columns=[
            "candidate_id", "ticker", "isu_cd", "market", "identity_effective_from", "identity_effective_to",
            "candidate_signal_date", "candidate_signal_information_date", "pattern_a_stage", "fast_machine_stage",
            "fast_machine_status", "monthly_permission_state", "daily_risk_state", "fast_score", "fast_score_status",
            "entry_filter_raw_date", "market_cap", "avg_trading_value_20d", "signal_close", "market_cap_pass",
            "trading_value_pass", "close_pass", "investability_pass",
        ]).to_csv(RAW_CANDIDATE_PATH, index=False)
    logger.info(
        "Raw candidate scan complete: identities=%d/%d, prefiltered=%d, candidates=%d, rss_max_mb=%s, elapsed=%.1fs",
        completed_identity_count, total_identities, prefiltered_identity_count, candidate_count,
        f"{_parent_rss_mb():.1f}" if _parent_rss_mb() is not None else "NA", time.monotonic() - started,
    )
    return pd.read_csv(RAW_CANDIDATE_PATH, dtype={"ticker": str, "isu_cd": str, "candidate_id": str})


def _quarter(value: str) -> str:
    dt = pd.Timestamp(value)
    return f"{dt.year}Q{((dt.month - 1) // 3) + 1}"


def _coverage_rows(decisions: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "quarter", "total_raw_candidates", "financial_candidates", "nonfinancial_candidates",
        "evaluable_nonfinancial_candidates", "unavailable_nonfinancial_candidates",
        "evaluable_rate", "qualifies_90_percent", "total_nonfinancial_candidates", "evaluable_count",
    ]
    if decisions.empty:
        return pd.DataFrame(columns=columns)
    frame = decisions.copy()
    frame["quarter"] = frame["entry_signal_information_date"].map(_quarter)
    frame = frame[frame["quarter"].notna()].copy()
    frame["_evaluable"] = frame["evaluable"].map(_bool_value)
    rows: list[dict[str, Any]] = []
    for quarter, group in frame.groupby("quarter", sort=True):
        financial = int((group["company_family"] == CompanyFamily.FINANCIAL.value).sum())
        nonfinancial_mask = group["company_family"] == CompanyFamily.NON_FINANCIAL.value
        nonfinancial = int(nonfinancial_mask.sum())
        evaluable = int((nonfinancial_mask & group["_evaluable"]).sum())
        unavailable = nonfinancial - evaluable
        rate = round(evaluable / nonfinancial * 100, 4) if nonfinancial else None
        rows.append({
            "quarter": str(quarter),
            "total_raw_candidates": int(len(group)),
            "financial_candidates": financial,
            "nonfinancial_candidates": nonfinancial,
            "evaluable_nonfinancial_candidates": evaluable,
            "unavailable_nonfinancial_candidates": unavailable,
            "evaluable_rate": rate,
            "qualifies_90_percent": bool(rate is not None and rate >= 90.0 and nonfinancial > 0),
            "total_nonfinancial_candidates": nonfinancial,
            "evaluable_count": evaluable,
        })
    return pd.DataFrame(rows, columns=columns)


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


FUNDAMENTALS_COVERAGE_COLUMNS = [
    "candidate_id", "ticker", "isu_cd", "market", "name", "candidate_signal_date",
    "entry_signal_information_date", "quarter", "company_family", "fundamentals_as_of",
    "fundamentals_status", "filter_status", "evaluable", "reason", "latest_fy",
    "latest_quarter", "filing_references", "company_cache_hit", "evaluation_source",
]


def _coverage_candidate_row(row: Mapping[str, Any]) -> dict[str, Any]:
    information_date = _date_text(row.get("entry_signal_information_date"))
    status = str(row.get("fundamentals_status") or DATA_UNAVAILABLE)
    references = row.get("selected_filing_receipt_dates") or []
    return {
        "candidate_id": str(row.get("candidate_id") or ""),
        "ticker": str(row.get("ticker") or ""),
        "isu_cd": str(row.get("isu_cd") or ""),
        "market": str(row.get("market") or ""),
        "name": str(row.get("name") or ""),
        "candidate_signal_date": _date_text(row.get("candidate_signal_date")),
        "entry_signal_information_date": information_date,
        "quarter": _quarter(information_date) if information_date else None,
        "company_family": row.get("company_family"),
        "fundamentals_as_of": _date_text(row.get("fundamentals_as_of") or information_date),
        "fundamentals_status": status,
        "filter_status": status,
        "evaluable": bool(row.get("evaluable")),
        "reason": row.get("reject_reason"),
        "latest_fy": row.get("latest_fy"),
        "latest_quarter": row.get("latest_quarter"),
        "filing_references": json.dumps(references, ensure_ascii=False, separators=(",", ":")),
        "company_cache_hit": bool(row.get("company_cache_hit")),
        "evaluation_source": row.get("evaluation_source"),
    }


def _append_coverage_rows(rows: Iterable[Mapping[str, Any]]) -> None:
    rows = list(rows)
    if not rows:
        return
    FUNDAMENTALS_COVERAGE_DIR.mkdir(parents=True, exist_ok=True)
    write_header = not FUNDAMENTALS_COVERAGE_CANDIDATE_PATH.exists() or FUNDAMENTALS_COVERAGE_CANDIDATE_PATH.stat().st_size == 0
    with FUNDAMENTALS_COVERAGE_CANDIDATE_PATH.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FUNDAMENTALS_COVERAGE_COLUMNS, lineterminator="\n")
        if write_header:
            writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in FUNDAMENTALS_COVERAGE_COLUMNS})


def _completed_coverage_ids() -> set[str]:
    if not FUNDAMENTALS_COVERAGE_CANDIDATE_PATH.exists():
        return set()
    frame = pd.read_csv(FUNDAMENTALS_COVERAGE_CANDIDATE_PATH, usecols=["candidate_id"], dtype={"candidate_id": str})
    return set(frame["candidate_id"].dropna().astype(str))


def _write_coverage_checkpoint(
    *,
    status: str,
    input_candidate_rows: int,
    completed_ids: set[str],
    client: OpenDartClient,
) -> None:
    _json_write(FUNDAMENTALS_COVERAGE_CHECKPOINT_PATH, {
        "work_id": FIX04_WORK_ID,
        "status": status,
        "input_candidate_rows": int(input_candidate_rows),
        "completed_candidate_count": len(completed_ids),
        "completed_candidate_ids": sorted(completed_ids),
        "opendart_network_calls_current_invocation": len(client.audit),
        "company_cache_hits_current_invocation": None,
        "krx_market_network_calls": 0,
    })


def _first_trading_day_of_quarter(label: str) -> str | None:
    from trend_scanner.data.market_calendar import MarketCalendarAuthority
    calendar = MarketCalendarAuthority.from_parquet(ROOT / "data/reference/krx_trading_calendar.parquet")
    year, quarter = int(label[:4]), int(label[-1])
    start = pd.Timestamp(year=year, month=(quarter - 1) * 3 + 1, day=1)
    dates = calendar.trading_dates[calendar.trading_dates >= start]
    if len(dates) == 0:
        return None
    return dates[0].strftime("%Y-%m-%d")


def _quarter_sequence(start_quarter: str, count: int = 4) -> list[str]:
    """Return consecutive calendar quarters starting at ``start_quarter``."""
    if (
        len(start_quarter) != 6
        or start_quarter[4] != "Q"
        or not start_quarter[:4].isdigit()
        or start_quarter[5] not in "1234"
        or count < 0
    ):
        raise ValueError(f"invalid quarter sequence input: {start_quarter!r}")
    year = int(start_quarter[:4])
    quarter = int(start_quarter[5])
    return [
        f"{year + absolute // 4}Q{absolute % 4 + 1}"
        for absolute in range(quarter - 1, quarter - 1 + count)
    ]


def select_common_start(coverage: pd.DataFrame) -> tuple[str | None, dict[str, Any]]:
    if coverage.empty:
        return None, {"reason": "NO_NON_FINANCIAL_CANDIDATES"}
    by_q = {str(row.quarter): row for row in coverage.itertuples(index=False)}
    ordered = sorted(by_q)
    for index, quarter in enumerate(ordered):
        sequence = _quarter_sequence(quarter)
        if not all(item in by_q for item in sequence):
            continue
        if all(float(getattr(by_q[item], "evaluable_rate", 0) or 0) >= 90.0 and int(getattr(by_q[item], "total_nonfinancial_candidates", 0) or 0) > 0 for item in sequence):
            start = _first_trading_day_of_quarter(quarter)
            return start, {
                "rule": "first quarter plus next three consecutive quarters each evaluable_rate >= 90%",
                "selected_quarter": quarter,
                "quarters": sequence,
                "coverage_rates": {item: float(getattr(by_q[item], "evaluable_rate")) for item in sequence},
            }
    return None, {"reason": "NO_FOUR_CONSECUTIVE_QUARTERS_AT_90_PERCENT"}


def _company(ticker: str, corp_code: str) -> dict[str, Any] | None:
    value = _read_json(COMPANY_CACHE_DIR / f"{ticker}.json")
    if not isinstance(value, dict):
        return None
    fields = value.get("selected_fields") if isinstance(value.get("selected_fields"), dict) else {}
    if str(value.get("status") or "") != "000" or str(fields.get("corp_code") or "") != corp_code:
        return None
    return value


def _selected_receipt_dates(f2: Any) -> list[str]:
    dates: set[str] = set()
    for build in getattr(f2, "periodization_builds", ()):
        for item in getattr(build, "anchor_selections", ()):
            dt = _date_text(item.get("selected_rcept_dt")) if isinstance(item, Mapping) else None
            if dt:
                dates.add(dt)
    return sorted(dates)


def _bounded_f2(period_provider: PeriodizationProvider, ticker: str, as_of: str, company_fields: Mapping[str, Any], *, live: bool) -> Any:
    """Build only the 2015+ fiscal years needed by the candidate window."""
    year = int(as_of[:4])
    years = tuple(str(item) for item in range(max(2015, year - 6), year + 1))
    registry = period_provider.filings
    if live and hasattr(registry, "preload_ticker"):
        record = period_provider.corp_codes.get_record(ticker)
        registry.preload_ticker(ticker=ticker, corp_code=record.corp_code, requested_as_of=as_of, fiscal_years=years)
    builds = tuple(
        period_provider.build(ticker, fiscal_year, as_of, company_metadata=company_fields, force_refresh=False)
        for fiscal_year in years
    )
    observations = tuple(item for build in builds for item in build.result.observations)
    family = str(getattr(builds[0], "company_family", CompanyFamily.UNKNOWN.value)) if builds else CompanyFamily.UNKNOWN.value
    corp_code = next((str(item.corp_code) for build in builds for item in build.facts if item.corp_code), "")
    return build_multi_period_result(
        ticker=ticker, corp_code=corp_code, company_family=family,
        requested_as_of=as_of, observations=observations, periodization_builds=builds,
    )


def _load_company_live(client: OpenDartClient, ticker: str, corp_code: str) -> tuple[dict[str, Any] | None, bool]:
    hydration = _hydration_module()
    company, cache_hit = hydration._load_company_metadata(
        client, ticker, corp_code, "", COMPANY_CACHE_DIR,
    )
    return company, bool(cache_hit)


def _hydration_module() -> Any:
    """Load the sibling hydration module from both pytest and CLI entrypoints."""
    try:
        return __import__("scripts.hydrate_fundamentals_v1_production", fromlist=["QuotaBoundOpenDartClient"])
    except ModuleNotFoundError as exc:
        if exc.name != "scripts":
            raise
        return __import__("hydrate_fundamentals_v1_production", fromlist=["QuotaBoundOpenDartClient"])


def evaluate_one_candidate(
    candidate: Mapping[str, Any],
    *,
    corp_repo: CorpCodeRepository,
    period_provider: PeriodizationProvider,
    live: bool,
    client: OpenDartClient | None = None,
) -> dict[str, Any]:
    ticker = str(candidate["ticker"])
    as_of = str(candidate["entry_signal_information_date"])
    row: dict[str, Any] = dict(candidate)
    row["fundamentals_as_of"] = as_of
    row.update({
        "company_family": None, "corp_code": None, "fundamentals_status": DATA_UNAVAILABLE,
        "evaluable": False, "gate_pass": False, "reject_reason": "DATA_UNAVAILABLE",
        "annual_revenue": None, "four_quarter_avg_revenue": None,
        "ttm_operating_income": None, "ttm_net_income": None,
        "selected_filing_receipt_dates": [], "evaluation_source": "NETWORK" if live else "LOCAL_CACHE",
        "company_cache_hit": False, "latest_fy": None, "latest_quarter": None,
    })
    try:
        record = corp_repo.get_record(ticker)
        corp_code = str(record.corp_code)
        company = _company(ticker, corp_code)
        if company is not None:
            row["company_cache_hit"] = True
        elif live and client is not None:
            company, row["company_cache_hit"] = _load_company_live(client, ticker, corp_code)
        if company is None:
            row["reject_reason"] = "COMPANY_METADATA_UNAVAILABLE"
            return row
        family_result = classify_company_family(company, ())
        family = str(family_result.get("company_family") or CompanyFamily.UNKNOWN.value)
        row.update({"company_family": family, "corp_code": corp_code})
        if family == CompanyFamily.FINANCIAL.value:
            f2 = build_multi_period_result(ticker=ticker, corp_code=corp_code, company_family=family, requested_as_of=as_of, observations=())
            f3 = DerivedMetricsResult(())
        elif family == CompanyFamily.NON_FINANCIAL.value:
            company_fields = company.get("selected_fields", {})
            f2 = _bounded_f2(period_provider, ticker, as_of, company_fields, live=live)
            f3 = DerivedMetricsEngine().derive(f2.canonical_observations, requested_as_of=as_of)
            row["selected_filing_receipt_dates"] = _selected_receipt_dates(f2)
        else:
            row["reject_reason"] = "COMPANY_FAMILY_UNKNOWN"
            return row
        f4_input = f3 if family == CompanyFamily.NON_FINANCIAL.value else type("AsOfOnly", (), {"requested_as_of": as_of, "observations": ()})()
        f4 = FundamentalsFilter().evaluate(f2, f4_input, requested_as_of=as_of)
        status = str(f4.status)
        row.update({
            "fundamentals_status": status,
            "evaluable": status in FUNDAMENTALS_EVALUABLE,
            "gate_pass": status in {PASS, NOT_APPLICABLE},
            "reject_reason": ";".join(str(item) for item in f4.reasons) if f4.reasons else (None if status in {PASS, NOT_APPLICABLE} else status),
            "annual_revenue": f4.annual_revenue,
            "four_quarter_avg_revenue": f4.quarterly_avg_revenue,
            "ttm_operating_income": f4.ttm_operating_income,
            "ttm_net_income": f4.ttm_net_income,
            "latest_fy": f4.latest_fy,
            "latest_quarter": f4.latest_quarter,
        })
        return row
    except Exception as exc:
        # A hard OpenDART quota stop must abort the run so the checkpoint
        # remains resumable; it must never be converted into row-level
        # DATA_UNAVAILABLE for the remaining candidates.
        if type(exc).__name__ == "QuotaBudgetExceeded":
            raise
        # Never persist exception text: OpenDART diagnostics are redacted at
        # the client boundary, but the ledger only needs a stable category.
        row["reject_reason"] = f"{type(exc).__name__}:DATA_UNAVAILABLE"
        return row


def evaluate_candidates(candidates: pd.DataFrame, *, live: bool, client: OpenDartClient | None = None) -> pd.DataFrame:
    corp_repo = CorpCodeRepository.from_cache(CORP_CACHE_PATH)
    hydration = _hydration_module() if live else None
    registry = (FilingRegistry(client=None, cache_dir=OPENDART_FILINGS_DIR) if not live else hydration.BoundedFilingRegistry(client, cache_dir=OPENDART_FILINGS_DIR))
    xbrl = XbrlRepository(client if live else None, cache_dir=OPENDART_XBRL_DIR)
    provider = PeriodizationProvider(corp_repo, registry, xbrl)
    rows: list[dict[str, Any]] = []
    ordered = candidates.sort_values(["fundamentals_as_of", "ticker"], ascending=[False, True], kind="mergesort")
    for index, candidate in enumerate(ordered.to_dict("records"), start=1):
        rows.append(evaluate_one_candidate(candidate, corp_repo=corp_repo, period_provider=provider, live=live, client=client))
        if index % 50 == 0 or index == len(ordered):
            logger.info("Fundamentals candidate evaluation: %d/%d (%s)", index, len(ordered), "live" if live else "cache")
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    return frame.drop_duplicates("candidate_id", keep="last").sort_values("candidate_id", kind="mergesort").reset_index(drop=True)


def write_coverage_artifacts(
    decisions: pd.DataFrame,
    authority: Any,
    start: str | None,
    start_reason: Mapping[str, Any],
    client: OpenDartClient,
    execution_metrics: Mapping[str, Any] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    FUNDAMENTALS_COVERAGE_DIR.mkdir(parents=True, exist_ok=True)
    coverage = _coverage_rows(decisions)
    coverage.to_csv(FUNDAMENTALS_COVERAGE_QUARTER_PATH, index=False, lineterminator="\n")
    evaluable = decisions[
        (decisions["company_family"] == CompanyFamily.NON_FINANCIAL.value)
        & decisions["evaluable"].map(_bool_value)
    ]
    earliest = str(evaluable["entry_signal_information_date"].min()) if not evaluable.empty else None
    financial_count = int((decisions["company_family"] == CompanyFamily.FINANCIAL.value).sum())
    nonfinancial_mask = decisions["company_family"] == CompanyFamily.NON_FINANCIAL.value
    nonfinancial_count = int(nonfinancial_mask.sum())
    evaluable_count = int((nonfinancial_mask & decisions["evaluable"].map(_bool_value)).sum())
    unavailable_count = nonfinancial_count - evaluable_count
    overall_rate = round(evaluable_count / nonfinancial_count * 100, 4) if nonfinancial_count else None
    date_match = bool(
        decisions.empty
        or (decisions["fundamentals_as_of"].astype(str) == decisions["entry_signal_information_date"].astype(str)).all()
    )
    future_reference_count = 0
    for row in decisions.to_dict("records"):
        as_of = pd.Timestamp(row["entry_signal_information_date"])
        try:
            references = json.loads(row.get("filing_references") or "[]")
        except (TypeError, json.JSONDecodeError):
            references = []
        future_reference_count += sum(1 for value in references if pd.Timestamp(value) > as_of)
    metrics = dict(execution_metrics or {})
    network_calls = int(metrics.get("network_calls_current_invocation", len(client.audit)))
    cache_hits = int(metrics.get("company_cache_hits", decisions["company_cache_hit"].map(_bool_value).sum()))
    summary = {
        "work_id": FIX04_WORK_ID,
        "status": "COMPLETE" if start else "BLOCKED",
        "input_candidate_rows": int(len(decisions)),
        "candidate_date_min": str(decisions["entry_signal_information_date"].min()) if not decisions.empty else None,
        "candidate_date_max": str(decisions["entry_signal_information_date"].max()) if not decisions.empty else None,
        "total_candidates": int(len(decisions)),
        "financial_candidates": financial_count,
        "nonfinancial_candidates": nonfinancial_count,
        "evaluable_nonfinancial_candidates": evaluable_count,
        "unavailable_nonfinancial_candidates": unavailable_count,
        "data_unavailable_candidates": int((decisions["fundamentals_status"] == DATA_UNAVAILABLE).sum()),
        "unknown_company_family_candidates": int(len(decisions) - financial_count - nonfinancial_count),
        "overall_evaluable_rate": overall_rate,
        "earliest_technically_evaluable_date": earliest,
        "selected_quarter": start_reason.get("selected_quarter"),
        "four_quarter_sequence": start_reason.get("quarters", []),
        "four_quarter_rates": start_reason.get("coverage_rates", {}),
        "common_start_date": start,
        "selection_reason": dict(start_reason),
        "future_filing_leakage_count": future_reference_count,
        "fundamentals_as_of_matches_signal_information_date": date_match,
        "opendart": {
            "network_calls_current_invocation": network_calls,
            "company_cache_hits": cache_hits,
        },
        "krx_market_network_calls": 0,
        "authority": "EFFECTIVE_CORRECTED_AUTHORITY_V01",
        "authority_sha256": authority.pit_sha256,
        "pit_interval_count": authority.pit_count,
        "raw_candidate_artifact_unchanged": True,
    }
    _json_write(FUNDAMENTALS_COVERAGE_SUMMARY_PATH, summary)
    return coverage, summary


def _load_or_empty_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype={"ticker": str, "isu_cd": str, "candidate_id": str})


def run_coverage(*, env_file: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], dict[tuple[str, str, str], list[tuple[str, str]]], list[dict[str, Any]]]:
    authority, intervals, tasks = _load_authority()
    candidates = _load_or_empty_csv(RAW_CANDIDATE_PATH)
    if len(candidates) != 9754 or candidates["candidate_id"].duplicated().any():
        raise RuntimeError("raw candidate artifact must contain exactly 9754 unique rows")
    logger.info("Reusing existing raw candidate scan: %d rows", len(candidates))

    hydration = _hydration_module()
    completed_ids = _completed_coverage_ids()
    all_candidate_ids = set(candidates["candidate_id"].astype(str))
    already_complete = completed_ids == all_candidate_ids
    prior_summary = _read_json(FUNDAMENTALS_COVERAGE_SUMMARY_PATH, {}) or {}
    prior_checkpoint = _read_json(FUNDAMENTALS_COVERAGE_CHECKPOINT_PATH, {}) or {}
    if len(completed_ids) < len(candidates):
        secret = hydration._load_opendart_key(env_file)
        client: OpenDartClient = hydration.QuotaBoundOpenDartClient(api_key=secret)
    else:
        client = hydration.QuotaBoundOpenDartClient(api_key="")
    corp_repo = CorpCodeRepository.from_cache(CORP_CACHE_PATH)
    registry = hydration.BoundedFilingRegistry(client, cache_dir=OPENDART_FILINGS_DIR)
    xbrl = XbrlRepository(client, cache_dir=OPENDART_XBRL_DIR)
    provider = PeriodizationProvider(corp_repo, registry, xbrl)
    ordered = candidates.sort_values(
        ["entry_signal_information_date", "ticker", "candidate_id"],
        ascending=[False, True, True], kind="mergesort",
    )
    if not already_complete:
        _write_coverage_checkpoint(
            status="RUNNING", input_candidate_rows=len(candidates), completed_ids=completed_ids, client=client,
        )
    else:
        logger.info("Coverage checkpoint already complete; replaying artifacts without network calls")
    batch: list[dict[str, Any]] = []
    for candidate in ordered.to_dict("records"):
        candidate_id = str(candidate["candidate_id"])
        if candidate_id in completed_ids:
            continue
        batch.append(evaluate_one_candidate(
            candidate, corp_repo=corp_repo, period_provider=provider, live=True, client=client,
        ))
        if len(batch) >= FUNDAMENTALS_COVERAGE_BATCH_SIZE:
            _append_coverage_rows(_coverage_candidate_row(row) for row in batch)
            completed_ids.update(str(row["candidate_id"]) for row in batch)
            batch.clear()
            _write_coverage_checkpoint(
                status="RUNNING", input_candidate_rows=len(candidates), completed_ids=completed_ids, client=client,
            )
            logger.info("Fundamentals coverage evaluation: %d/%d candidates", len(completed_ids), len(candidates))
            gc.collect()
    if batch:
        _append_coverage_rows(_coverage_candidate_row(row) for row in batch)
        completed_ids.update(str(row["candidate_id"]) for row in batch)
        batch.clear()
    if completed_ids != all_candidate_ids:
        raise RuntimeError("coverage evaluation did not complete all raw candidates")
    if not already_complete:
        _write_coverage_checkpoint(
            status="COMPLETE", input_candidate_rows=len(candidates), completed_ids=completed_ids, client=client,
        )
    decisions = _load_or_empty_csv(FUNDAMENTALS_COVERAGE_CANDIDATE_PATH)
    start, reason = select_common_start(_coverage_rows(decisions))
    prior_opendart = prior_summary.get("opendart", {}) if isinstance(prior_summary, dict) else {}
    execution_metrics = prior_opendart if already_complete and prior_opendart else None
    if execution_metrics is None and already_complete and prior_checkpoint:
        execution_metrics = {
            "network_calls_current_invocation": prior_checkpoint.get("opendart_network_calls_current_invocation", 0),
        }
    write_coverage_artifacts(decisions, authority, start, reason, client, execution_metrics)
    return candidates, decisions, authority, intervals, tasks


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute historical PIT Fundamentals coverage from existing FastCore candidates")
    parser.add_argument("--env-file", type=Path, default=ROOT.parent / "env.md")
    args = parser.parse_args()
    _candidates, _decisions, _authority, _intervals, _tasks = run_coverage(env_file=args.env_file)
    logger.info("FIX04 output: coverage artifacts written under %s", FUNDAMENTALS_COVERAGE_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
