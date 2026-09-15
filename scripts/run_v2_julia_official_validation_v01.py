#!/usr/bin/env python3
"""Stage 5 runner and execution-contract preflight for the V2 ↔ Julia check.

The default command only writes and validates the frozen execution contract.
It never runs a portfolio evaluation or writes result artifacts.  The runner
components below are intentionally wired to the effective Population/PIT
authority and Repository V2 so the next task can execute the three separately
reported result axes without reviving the historical research runner's
2022/current-list/proxy assumptions.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import math
import multiprocessing as mp
from pathlib import Path
import resource
import socket
import subprocess
import sys
from datetime import date, datetime
from statistics import mean, median
import time
from typing import Any, Iterator, Mapping, Sequence

import pandas as pd

from trend_scanner.backtest.fastcore_fundamentals_simple_v01 import (
    IdentityLifecycle,
    StrategyTradeRecord,
    clip_to_identity_lifecycle,
    is_qualifying_fast_entry,
    pit_common_for_identity,
    simulate_ticker_strategy_fundamentals_v01,
)
from trend_scanner.backtest.feature_cache import FastSnapshotCache, MonthlySnapshotCache
from trend_scanner.backtest.raw_investability_panel import (
    recompute_identity_scoped_avg_trading_value_20d,
)
from trend_scanner.backtest.snapshot_context import build_precomputed_ticker_context
from trend_scanner.data.adjusted_price_authority_cutover import load_effective_authority
from trend_scanner.data.index_store import IndexStore, MARKET_INDEX_FAMILY
from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader, build_repository_v2
from trend_scanner.data.repository_v2 import MarketDataRepositoryV2
from trend_scanner.data.resampler import to_weekly
from trend_scanner.patterns.pattern_a_fast_evaluator import evaluate_pattern_a_fast


ROOT = Path(__file__).resolve().parents[1]

WORK_ID = "V2_JULIA_OFFICIAL_VALIDATION_STAGE_5_V01"
BASE_STRATEGY_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V02"
JULIA_STRATEGY_ID = "JULIA_STRATEGY_V00"
START_DATE = pd.Timestamp("2021-01-01")
SIGNAL_CUTOFF = pd.Timestamp("2026-08-14")
EVALUATION_END = pd.Timestamp("2026-08-14")
EXECUTION_SUPPORT_END = pd.Timestamp("2026-08-14")
FINAL_VALUATION_DATE = pd.Timestamp("2026-08-14")

MARKET_CAP_THRESHOLD_KRW = 100_000_000_000.0
AVG_TRADING_VALUE_20D_THRESHOLD_KRW = 300_000_000.0
INITIAL_CAPITAL_KRW = 200_000_000.0
POSITION_CASH_BUDGET_KRW = 5_000_000.0
MAX_POSITIONS = 40
COMMISSION_RATE = 0.00015
SLIPPAGE_RATE = 0.001

EFFECTIVE_AUTHORITY_REL = Path(
    "artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/"
    "v01_spac_corrected_effective_authority"
)
POPULATION_REL = EFFECTIVE_AUTHORITY_REL / "effective_historical_common_population.json"
PIT_REL = EFFECTIVE_AUTHORITY_REL / "effective_pit_common_denominator.json"
EFFECTIVE_MANIFEST_REL = EFFECTIVE_AUTHORITY_REL / "effective_freeze_manifest.json"
AUTHORITY_CUTOVER_MANIFEST_REL = EFFECTIVE_AUTHORITY_REL / "authority_cutover_manifest.json"
SOURCE_ELIGIBILITY_REL = EFFECTIVE_AUTHORITY_REL / "effective_source_eligibility_authority.json"
STAGE4_PLAN_REL = Path("docs/strategies/julia/validation_plan_v01.md")
COMMON_CONDITIONS_REL = Path(
    "docs/patterns/pattern_a_fast/validation_plan/realistic_backtest_common_conditions_v01.md"
)
SCORE_CONTRACT_REL = Path(
    "artifacts/patterns/pattern_a_fast/production/contract_prototype/"
    "pattern_a_fast_score_prototype_v01.json"
)
STAGE_CONTRACT_REL = Path(
    "artifacts/patterns/pattern_a_fast/production/contract_prototype/"
    "pattern_a_fast_stage_prototype_v01.json"
)
INDEX_PARQUET_REL = Path("data/market/index/v01/market_index.parquet")
INDEX_META_REL = Path("data/market/index/v01/market_index.meta.json")
OUTPUT_DIR_REL = Path("artifacts/strategies/julia/official_validation_v01")
CONTRACT_REL = OUTPUT_DIR_REL / "execution_contract.json"

BENCHMARK_CODES = {"KOSPI": "1001", "KOSDAQ": "2001"}
OFFICIAL_RESULT_FILES = (
    "aggregate_summary.json",
    "matched_entry_comparison.csv",
    "sequential_comparison.csv",
    "failure_and_big_loss_cases.csv",
    "validation_report.md",
)
SUPPORT_RESULT_FILES = ("portfolio_event_ledger.csv", "portfolio_daily_equity.csv")

MATCHED_ENTRY_COLUMNS = (
    "ticker", "isu_cd", "market", "signal_date", "entry_execution_date", "entry_open",
    "entry_identity_equal", "entry_signal_date_equal", "entry_execution_date_equal",
    "entry_open_equal", "investability_equal",
    "v2_exit_type", "v2_exit_signal_date", "v2_exit_execution_date", "v2_exit_price",
    "julia_exit_type", "julia_exit_signal_date", "julia_exit_execution_date", "julia_exit_price",
    "v2_terminal_return", "julia_terminal_return", "return_delta",
    "v2_mae", "julia_mae", "v2_mfe", "julia_mfe",
    "v2_holding_period", "julia_holding_period",
    "v2_open_at_cutoff", "julia_open_at_cutoff", "pair_status",
)
SEQUENTIAL_COLUMNS = (
    "strategy_id", "ticker", "isu_cd", "market", "trade_id", "trade_sequence",
    "entry_signal_date", "entry_execution_date", "entry_open", "entry_market_cap",
    "entry_avg_trading_value_20d", "exit_signal_date", "exit_execution_date", "exit_type",
    "exit_price", "terminal_return", "mae", "mfe", "holding_trading_days", "holding_weeks",
    "trade_status", "cutoff_date", "cutoff_valuation_price", "mark_to_cutoff_return",
    "open_at_cutoff", "identity_effective_from", "identity_effective_to", "loss_guard_triggered",
)
FAILURE_COLUMNS = (
    "case_type", "strategy_id", "ticker", "isu_cd", "market", "trade_id",
    "signal_date", "entry_execution_date", "exit_execution_date", "terminal_return", "mae",
    "mfe", "loss_guard_triggered", "unresolved_reason", "case_status",
)
PORTFOLIO_EVENT_COLUMNS = (
    "strategy_id", "ticker", "isu_cd", "market", "position_id", "signal_date",
    "execution_date", "event_type", "event_status", "reference_open",
    "slippage_adjusted_price", "shares", "notional", "commission", "sell_tax",
    "cash_before", "cash_after", "pending_sale_proceeds", "entry_or_exit_reason",
    "market_cap_at_signal", "unresolved_reason", "open_at_cutoff",
)
PORTFOLIO_EQUITY_COLUMNS = (
    "date", "strategy_id", "cash", "pending_sale_proceeds", "invested_market_value",
    "equity", "exposure", "drawdown",
)

HISTORICAL_SELL_TAX_SCHEDULE = (
    {"start": "2021-01-01", "end": "2022-12-31", "KOSPI": 0.0023, "KOSDAQ": 0.0023},
    {"start": "2023-01-01", "end": "2023-12-31", "KOSPI": 0.0020, "KOSDAQ": 0.0020},
    {"start": "2024-01-01", "end": "2024-12-31", "KOSPI": 0.0018, "KOSDAQ": 0.0018},
    {"start": "2025-01-01", "end": "2025-12-31", "KOSPI": 0.0015, "KOSDAQ": 0.0015},
    {"start": "2026-01-01", "end": None, "KOSPI": 0.0020, "KOSDAQ": 0.0020},
)


class OfficialValidationError(RuntimeError):
    """Raised when the official Stage 5 contract cannot be resolved closed."""


@dataclass(frozen=True)
class IdentityTask:
    ticker: str
    isu_cd: str
    market: str
    effective_from: pd.Timestamp
    effective_to: pd.Timestamp

    @property
    def key(self) -> tuple[str, str, str]:
        return self.ticker, self.isu_cd, self.market

    def lifecycle(self) -> IdentityLifecycle:
        return IdentityLifecycle(
            ticker=self.ticker,
            isu_cd=self.isu_cd,
            market=self.market,
            effective_from=self.effective_from,
            effective_to=self.effective_to,
        )


@dataclass(frozen=True)
class EntrySignal:
    task: IdentityTask
    signal_date: pd.Timestamp
    execution_date: pd.Timestamp
    market_cap: float
    avg_trading_value_20d: float

    def key(self) -> tuple[str, str, str, str, str]:
        return (*self.task.key, self.signal_date.strftime("%Y-%m-%d"), self.execution_date.strftime("%Y-%m-%d"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _contract_digest(payload: Mapping[str, Any]) -> str:
    body = dict(payload)
    body.pop("contract_sha256", None)
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _repo_path(path: Path) -> str:
    path = Path(path)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(ROOT.resolve()).as_posix()
        except ValueError as exc:
            raise OfficialValidationError(f"PATH_OUTSIDE_REPOSITORY:{path}") from exc
    return path.as_posix()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise OfficialValidationError(f"JSON_UNREADABLE:{_repo_path(path)}") from exc


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _identity_intervals(authority: Any) -> dict[tuple[str, str, str], list[tuple[str, str]]]:
    result: dict[tuple[str, str, str], list[tuple[str, str]]] = {}
    for row in authority.pit_intervals:
        if row.get("state") != "COMMON":
            continue
        key = (str(row["ticker"]), str(row["isu_cd"]), str(row["market"]))
        # Preserve pre-2021 rows for indicator lookback.  Only lifecycles that
        # end before the official evaluation window are excluded from the
        # run-scoped task list.
        start = pd.Timestamp(row["effective_from"])
        end = min(pd.Timestamp(row["effective_to"]), EXECUTION_SUPPORT_END)
        if start <= end and end >= START_DATE:
            result.setdefault(key, []).append((start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")))
    for key, ranges in result.items():
        ranges.sort()
        for previous, current in zip(ranges, ranges[1:]):
            if current[0] <= previous[1]:
                raise OfficialValidationError(f"PIT_INTERVAL_OVERLAP:{key}")
    return result


def _population_identity_keys(authority: Any) -> set[tuple[str, str, str]]:
    keys: set[tuple[str, str, str]] = set()
    for row in authority.population:
        tick = str(row["ticker"])
        isus = row.get("isu_cd", ())
        markets = row.get("market", ())
        if isinstance(isus, str):
            isus = (isus,)
        if isinstance(markets, str):
            markets = (markets,)
        for isu in isus:
            for market in markets:
                keys.add((tick, str(isu), str(market)))
    return keys


def _identity_tasks(authority: Any) -> tuple[IdentityTask, ...]:
    intervals = _identity_intervals(authority)
    population_keys = _population_identity_keys(authority)
    if not set(intervals).issubset(population_keys):
        raise OfficialValidationError("PIT_IDENTITY_NOT_IN_EFFECTIVE_POPULATION")
    tasks: list[IdentityTask] = []
    for (ticker, isu_cd, market), ranges in sorted(intervals.items()):
        for start, end in ranges:
            # Keep each exact COMMON interval as its own lifecycle.  Merging
            # disjoint intervals would silently bridge a NOT_COMMON period.
            tasks.append(
                IdentityTask(
                    ticker=ticker,
                    isu_cd=isu_cd,
                    market=market,
                    effective_from=pd.Timestamp(start),
                    effective_to=pd.Timestamp(end),
                )
            )
    return tuple(tasks)


def select_performance_sample_tasks(
    tasks: Sequence[IdentityTask],
    sample_size: int,
) -> tuple[IdentityTask, ...]:
    """Select a deterministic, market-balanced nested performance sample.

    The per-market order prefers longer lifecycle intervals so a sample does
    not accidentally consist only of short-lived identities.  Round-robin
    interleaving makes the first N identities a stable subset of larger N
    samples while keeping both KOSPI and KOSDAQ represented.
    """
    if sample_size <= 0:
        raise OfficialValidationError("PERFORMANCE_SAMPLE_SIZE_MUST_BE_POSITIVE")
    if sample_size > len(tasks):
        raise OfficialValidationError(
            f"PERFORMANCE_SAMPLE_SIZE_EXCEEDS_IDENTITY_COUNT:{sample_size}>{len(tasks)}"
        )
    by_market: dict[str, list[IdentityTask]] = {}
    for task in tasks:
        by_market.setdefault(task.market, []).append(task)
    required_markets = {"KOSPI", "KOSDAQ"}
    if not required_markets.issubset(by_market):
        raise OfficialValidationError("PERFORMANCE_SAMPLE_MARKET_BALANCE_UNAVAILABLE")
    markets = tuple(sorted(by_market))
    ordered = {
        market: sorted(
            rows,
            key=lambda task: (
                -(task.effective_to - task.effective_from).days,
                task.ticker,
                task.isu_cd,
                task.effective_from,
                task.effective_to,
            ),
        )
        for market, rows in by_market.items()
    }
    cursors = {market: 0 for market in markets}
    selected: list[IdentityTask] = []
    while len(selected) < sample_size:
        progressed = False
        for market in markets:
            cursor = cursors[market]
            if cursor >= len(ordered[market]):
                continue
            selected.append(ordered[market][cursor])
            cursors[market] += 1
            progressed = True
            if len(selected) == sample_size:
                break
        if not progressed:
            raise OfficialValidationError("PERFORMANCE_SAMPLE_SELECTION_INCOMPLETE")
    return tuple(selected)


def _find_exact_raw_row(panel: pd.DataFrame, date: pd.Timestamp) -> pd.Series | None:
    day = pd.Timestamp(date).normalize()
    matches = panel.loc[panel.index == day]
    if len(matches) != 1:
        return None
    return matches.iloc[0]


def build_identity_raw_panel(ancillary: pd.DataFrame | None, task: IdentityTask) -> pd.DataFrame:
    """Build an identity-scoped raw panel with a reset 20D rolling window."""
    if ancillary is None or ancillary.empty:
        raise OfficialValidationError(f"RAW_ANCILLARY_UNAVAILABLE:{task.key}")
    frame = ancillary.copy()
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index, errors="coerce")).normalize()
    if frame.index.isna().any() or frame.index.has_duplicates:
        raise OfficialValidationError(f"RAW_ANCILLARY_DATE_AMBIGUOUS:{task.key}")
    frame = frame.sort_index()
    frame = clip_to_identity_lifecycle(frame, task.lifecycle())
    if frame is None or frame.empty:
        raise OfficialValidationError(f"RAW_ANCILLARY_OUTSIDE_IDENTITY:{task.key}")
    frame = recompute_identity_scoped_avg_trading_value_20d(frame)
    for required in ("market_cap", "trading_value", "avg_trading_value_20d"):
        if required not in frame.columns:
            raise OfficialValidationError(f"RAW_ANCILLARY_FIELD_MISSING:{required}")
    # No price floor is part of the official contract; the strategy's
    # adjusted OHLC remains in the separate Repository V2 daily frame.
    frame["close"] = float("nan")
    return frame.loc[:, ["market_cap", "avg_trading_value_20d", "close", "trading_value"]]


def _tax_rate(execution_date: pd.Timestamp | str, market: str) -> float:
    day = pd.Timestamp(execution_date).normalize()
    market_key = str(market).upper()
    if market_key not in {"KOSPI", "KOSDAQ"}:
        raise OfficialValidationError(f"SELL_TAX_MARKET_UNSUPPORTED:{market}")
    for row in HISTORICAL_SELL_TAX_SCHEDULE:
        if day >= pd.Timestamp(row["start"]) and (row["end"] is None or day <= pd.Timestamp(row["end"])):
            return float(row[market_key])
    raise OfficialValidationError(f"SELL_TAX_DATE_OUTSIDE_SCHEDULE:{day.date()}")


def _record_value(record: Any, field: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        return record.get(field, default)
    return getattr(record, field, default)


def _record_date(record: Any, field: str) -> pd.Timestamp | None:
    value = _record_value(record, field)
    if value in (None, ""):
        return None
    try:
        return pd.Timestamp(value).normalize()
    except (TypeError, ValueError, OverflowError):
        return None


def _record_lifecycle_contains(record: Any, day: pd.Timestamp) -> bool:
    effective_from = _record_date(record, "identity_effective_from")
    effective_to = _record_date(record, "identity_effective_to")
    if effective_from is None or effective_to is None or effective_from > effective_to:
        return False
    normalized = pd.Timestamp(day).normalize()
    return effective_from <= normalized <= effective_to


def _exact_frame_value(frame: pd.DataFrame | None, date: pd.Timestamp, column: str) -> float | None:
    if frame is None or frame.empty or column not in frame.columns:
        return None
    day = pd.Timestamp(date).normalize()
    index = frame.index
    if not isinstance(index, pd.DatetimeIndex):
        index = pd.DatetimeIndex(pd.to_datetime(index, errors="coerce")).normalize()
    if index.isna().any() or index.has_duplicates:
        return None
    try:
        location = index.get_loc(day)
    except KeyError:
        return None
    if not isinstance(location, int):
        return None
    value = pd.to_numeric(frame[column].iloc[location], errors="coerce")
    return None if pd.isna(value) else float(value)


def _exact_record_price(record: Any, frame: pd.DataFrame | None, day: pd.Timestamp, column: str) -> float | None:
    """Read one exact price only when the record identity owns the date."""
    normalized = pd.Timestamp(day).normalize()
    if not _record_lifecycle_contains(record, normalized):
        return None
    if frame is not None:
        return _exact_frame_value(frame, normalized, column)
    # Synthetic compatibility path remains exact-date and lifecycle-bound.
    if column == "open" and _record_date(record, "entry_execution_date") == normalized:
        value = _record_value(record, "entry_open")
        return None if value in (None, "") else float(value)
    if column == "open" and _record_date(record, "exit_execution_date") == normalized:
        value = _record_value(record, "exit_price")
        return None if value in (None, "") else float(value)
    if column == "close" and normalized == FINAL_VALUATION_DATE:
        value = _record_value(record, "cutoff_valuation_price")
        return None if value in (None, "") else float(value)
    return None


def _identity_key_from_record(record: Any) -> tuple[str, str, str]:
    return (
        str(_record_value(record, "ticker", "")),
        str(_record_value(record, "isu_cd", "") or ""),
        str(_record_value(record, "market", "")),
    )


def _normalise_portfolio_market_data(
    market_data_by_identity: Mapping[Any, pd.DataFrame] | None,
) -> dict[Any, pd.DataFrame]:
    if market_data_by_identity is None:
        return {}
    normalized: dict[Any, pd.DataFrame] = {}
    for key, frame in market_data_by_identity.items():
        if frame is None or frame.empty:
            normalized[key] = frame
            continue
        copy = frame.copy()
        index = pd.DatetimeIndex(pd.to_datetime(copy.index, errors="coerce")).normalize()
        if index.isna().any() or index.has_duplicates:
            raise OfficialValidationError(f"PORTFOLIO_MARKET_DATA_DATE_AMBIGUOUS:{key}")
        copy.index = index
        normalized[key] = copy.sort_index()
    return normalized


def build_execution_contract(root: Path = ROOT) -> dict[str, Any]:
    """Build the portable, hash-bound contract without running a backtest."""
    root = Path(root).resolve()
    authority = load_effective_authority(root / EFFECTIVE_AUTHORITY_REL)
    index_store = IndexStore(root / "data/market/index/v01")
    benchmark = index_store.verify_family(MARKET_INDEX_FAMILY)
    contract: dict[str, Any] = {
        "schema": "v2_julia_official_execution_contract_v01",
        "work_id": WORK_ID,
        "stage": "STAGE_5_EXECUTION_READY",
        "status": "READY_NOT_RUN",
        "contract_state": "FROZEN_BEFORE_RESULTS",
        "stage4_authority": {
            "validation_plan_path": _repo_path(root / STAGE4_PLAN_REL),
            "validation_plan_sha256": sha256_file(root / STAGE4_PLAN_REL),
            "common_conditions_path": _repo_path(root / COMMON_CONDITIONS_REL),
            "common_conditions_sha256": sha256_file(root / COMMON_CONDITIONS_REL),
        },
        "strategies": {
            "base_strategy_id": BASE_STRATEGY_ID,
            "candidate_strategy_id": JULIA_STRATEGY_ID,
            "one_delta_only": "PRE_PROGRESSED_LOSS_GUARD_ON_VS_OFF",
            "base_loss_guard": "ON (-15%)",
            "candidate_loss_guard": "OFF",
            "fundamentals_included": False,
            "candidate_status": "NOT_APPROVED",
            "current_default_strategy": BASE_STRATEGY_ID,
        },
        "period": {
            "evaluation_start": START_DATE.strftime("%Y-%m-%d"),
            "signal_cutoff": SIGNAL_CUTOFF.strftime("%Y-%m-%d"),
            "evaluation_end": EVALUATION_END.strftime("%Y-%m-%d"),
            "execution_support_end": EXECUTION_SUPPORT_END.strftime("%Y-%m-%d"),
            "final_valuation": f"{FINAL_VALUATION_DATE:%Y-%m-%d} CLOSE",
            "initial_position": "FLAT",
            "pre_start_data": "LOOKBACK_ONLY_NO_TRADES",
        },
        "population_pit_authority": {
            "effective_authority_dir": _repo_path(root / EFFECTIVE_AUTHORITY_REL),
            "population_path": _repo_path(root / POPULATION_REL),
            "population_sha256": authority.population_sha256,
            "population_count": authority.population_count,
            "pit_path": _repo_path(root / PIT_REL),
            "pit_sha256": authority.pit_sha256,
            "pit_interval_count": authority.pit_count,
            "effective_manifest_path": _repo_path(root / EFFECTIVE_MANIFEST_REL),
            "cutover_manifest_path": _repo_path(root / AUTHORITY_CUTOVER_MANIFEST_REL),
            "source_eligibility_path": _repo_path(root / SOURCE_ELIGIBILITY_REL),
            "identity_key": ["ticker", "isu_cd", "market"],
            "membership_semantics": "EXACT_DATE_COMMON_INTERVAL_FAIL_CLOSED",
        },
        "market_data": {
            "authority": "MarketDataRepositoryV2",
            "factory": "trend_scanner.data.repository_v2_loader.build_repository_v2",
            "adjusted_store_path": "data/market/adjusted/stocks",
            "raw_store_path": "data/market/raw/krx_stocks/v01",
            "fixed_cutoff": EXECUTION_SUPPORT_END.strftime("%Y-%m-%d"),
            "price_semantics": "ADJUSTED_OHLC_REPOSITORY_V2",
            "raw_semantics": "RAW_VOLUME_TRADING_VALUE_MARKET_CAP_REPOSITORY_V2",
            "legacy_fallbacks": False,
        },
        "investability": {
            "market_cap_min_krw": MARKET_CAP_THRESHOLD_KRW,
            "avg_trading_value_20d_min_krw": AVG_TRADING_VALUE_20D_THRESHOLD_KRW,
            "price_filter": "NONE",
            "market_cap_semantics": "EXACT_SIGNAL_CONFIRMATION_DATE_RAW_ANCILLARY",
            "trading_value_semantics": "IDENTITY_SCOPED_20_OBSERVATION_MEAN_THROUGH_SIGNAL_DATE",
            "missing_semantics": "FAIL_CLOSED_UNRESOLVED",
            "proxy_market_cap": False,
            "nearest_date_fallback": False,
            "current_or_future_market_cap": False,
        },
        "execution": {
            "entry": "NEXT_LOCAL_TRADING_DAY_OPEN_AFTER_COMPLETED_SIGNAL",
            "loss_guard": "COMPLETED_DAILY_CLOSE_THEN_NEXT_LOCAL_TRADING_DAY_OPEN",
            "exit3_exit4": "NEXT_LOCAL_TRADING_DAY_OPEN_AFTER_COMPLETED_MONTHLY_SIGNAL",
            "same_open_exit_reentry": False,
            "overlap_and_pyramiding": False,
            "open_at_cutoff": True,
        },
        "costs": {
            "buy_commission_rate": COMMISSION_RATE,
            "sell_commission_rate": COMMISSION_RATE,
            "buy_slippage_rate": SLIPPAGE_RATE,
            "sell_slippage_rate": SLIPPAGE_RATE,
            "sell_tax_applies_to": "SELL_EXECUTION_NOTIONAL_ONLY",
            "historical_sell_tax_schedule": list(HISTORICAL_SELL_TAX_SCHEDULE),
        },
        "portfolio": {
            "initial_capital_krw": INITIAL_CAPITAL_KRW,
            "per_symbol_cash_budget_krw": POSITION_CASH_BUDGET_KRW,
            "max_positions": MAX_POSITIONS,
            "max_initial_capital_weight": 0.025,
            "partial_fill": False,
            "same_open_sale_proceeds_reusable": False,
            "sale_proceeds_reusable_from": "NEXT_EVALUABLE_LOCAL_TRADING_DAY_OPEN",
            "same_open_signal_order": ["signal_confirmation_date_pit_market_cap_desc", "ticker_asc"],
        },
        "unresolved": {
            "missing_required_evidence": "UNRESOLVED",
            "run_status_if_unresolved_gt_zero": "INCOMPLETE_REQUIRES_REVIEW",
            "silent_exclusion": False,
            "zero_fill": False,
            "nearest_date": False,
        },
        "benchmarks": {
            "authority": "data/market/index/v01/market_index.parquet",
            "metadata_path": _repo_path(root / INDEX_META_REL),
            "index_store_family": MARKET_INDEX_FAMILY,
            "KOSPI_COMMON": "1001",
            "KOSDAQ_COMMON": "2001",
            "mixed_single_benchmark": False,
            "content_sha256": benchmark["content_sha256"],
        },
        "result_axes": ["Matched-entry", "Sequential", "Realistic 200M Portfolio"],
        "output": {
            "directory": _repo_path(root / OUTPUT_DIR_REL),
            "official_result_files": list(OFFICIAL_RESULT_FILES),
            "support_result_files": list(SUPPORT_RESULT_FILES),
            "execution_contract": _repo_path(root / CONTRACT_REL),
        },
    }
    contract["contract_sha256"] = _contract_digest(contract)
    return contract


def _walk_strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for child in value.values():
            yield from _walk_strings(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk_strings(child)


def _nested_value(payload: Mapping[str, Any], *keys: str) -> Any:
    value: Any = payload
    for key in keys:
        if not isinstance(value, Mapping) or key not in value:
            return None
        value = value[key]
    return value


def _validate_contract_against_runner_constants(contract: Mapping[str, Any]) -> None:
    checks = (
        (("strategies", "base_strategy_id"), BASE_STRATEGY_ID),
        (("strategies", "candidate_strategy_id"), JULIA_STRATEGY_ID),
        (("strategies", "one_delta_only"), "PRE_PROGRESSED_LOSS_GUARD_ON_VS_OFF"),
        (("strategies", "fundamentals_included"), False),
        (("period", "evaluation_start"), START_DATE.strftime("%Y-%m-%d")),
        (("period", "signal_cutoff"), SIGNAL_CUTOFF.strftime("%Y-%m-%d")),
        (("period", "evaluation_end"), EVALUATION_END.strftime("%Y-%m-%d")),
        (("period", "execution_support_end"), EXECUTION_SUPPORT_END.strftime("%Y-%m-%d")),
        (("period", "final_valuation"), f"{FINAL_VALUATION_DATE:%Y-%m-%d} CLOSE"),
        (("period", "initial_position"), "FLAT"),
        (("investability", "market_cap_min_krw"), MARKET_CAP_THRESHOLD_KRW),
        (("investability", "avg_trading_value_20d_min_krw"), AVG_TRADING_VALUE_20D_THRESHOLD_KRW),
        (("investability", "price_filter"), "NONE"),
        (("investability", "market_cap_semantics"), "EXACT_SIGNAL_CONFIRMATION_DATE_RAW_ANCILLARY"),
        (("investability", "proxy_market_cap"), False),
        (("investability", "nearest_date_fallback"), False),
        (("investability", "current_or_future_market_cap"), False),
        (("portfolio", "initial_capital_krw"), INITIAL_CAPITAL_KRW),
        (("portfolio", "per_symbol_cash_budget_krw"), POSITION_CASH_BUDGET_KRW),
        (("portfolio", "max_positions"), MAX_POSITIONS),
        (("portfolio", "max_initial_capital_weight"), 0.025),
        (("portfolio", "partial_fill"), False),
        (("portfolio", "same_open_sale_proceeds_reusable"), False),
        (("portfolio", "same_open_signal_order"), [
            "signal_confirmation_date_pit_market_cap_desc",
            "ticker_asc",
        ]),
        (("costs", "buy_commission_rate"), COMMISSION_RATE),
        (("costs", "sell_commission_rate"), COMMISSION_RATE),
        (("costs", "buy_slippage_rate"), SLIPPAGE_RATE),
        (("costs", "sell_slippage_rate"), SLIPPAGE_RATE),
        (("costs", "historical_sell_tax_schedule"), list(HISTORICAL_SELL_TAX_SCHEDULE)),
        (("benchmarks", "KOSPI_COMMON"), BENCHMARK_CODES["KOSPI"]),
        (("benchmarks", "KOSDAQ_COMMON"), BENCHMARK_CODES["KOSDAQ"]),
        (("result_axes",), ["Matched-entry", "Sequential", "Realistic 200M Portfolio"]),
    )
    for path, expected in checks:
        actual = _nested_value(contract, *path)
        if actual != expected:
            raise OfficialValidationError(
                f"CONTRACT_RUNNER_CONSTANT_MISMATCH:{'.'.join(path)}"
            )


def validate_execution_contract(contract: Mapping[str, Any], root: Path = ROOT) -> dict[str, Any]:
    root = Path(root).resolve()
    if _contract_digest(contract) != contract.get("contract_sha256"):
        raise OfficialValidationError("EXECUTION_CONTRACT_HASH_MISMATCH")
    if any(value.startswith("/") or value.startswith("~") or "\\" in value for value in _walk_strings(contract)):
        raise OfficialValidationError("EXECUTION_CONTRACT_ABSOLUTE_OR_WINDOWS_PATH")
    expected = {
        "schema": "v2_julia_official_execution_contract_v01",
        "stage": "STAGE_5_EXECUTION_READY",
        "status": "READY_NOT_RUN",
        "contract_state": "FROZEN_BEFORE_RESULTS",
    }
    for key, value in expected.items():
        if contract.get(key) != value:
            raise OfficialValidationError(f"EXECUTION_CONTRACT_{key.upper()}_MISMATCH")
    _validate_contract_against_runner_constants(contract)
    period = contract["period"]
    if tuple(period[key] for key in ("evaluation_start", "signal_cutoff", "evaluation_end", "execution_support_end")) != (
        "2021-01-01", "2026-08-14", "2026-08-14", "2026-08-14"
    ):
        raise OfficialValidationError("STAGE4_PERIOD_MISMATCH")
    if contract["strategies"]["one_delta_only"] != "PRE_PROGRESSED_LOSS_GUARD_ON_VS_OFF":
        raise OfficialValidationError("ONE_DELTA_ONLY_MISMATCH")
    if contract["result_axes"] != ["Matched-entry", "Sequential", "Realistic 200M Portfolio"]:
        raise OfficialValidationError("RESULT_AXES_MISMATCH")
    authority = load_effective_authority(root / EFFECTIVE_AUTHORITY_REL)
    authority_block = contract["population_pit_authority"]
    if (
        authority_block["population_sha256"] != authority.population_sha256
        or authority_block["pit_sha256"] != authority.pit_sha256
        or authority_block["population_count"] != authority.population_count
        or authority_block["pit_interval_count"] != authority.pit_count
    ):
        raise OfficialValidationError("EFFECTIVE_AUTHORITY_HASH_MISMATCH")
    for relative in (
        POPULATION_REL,
        PIT_REL,
        EFFECTIVE_MANIFEST_REL,
        AUTHORITY_CUTOVER_MANIFEST_REL,
        SOURCE_ELIGIBILITY_REL,
        STAGE4_PLAN_REL,
        COMMON_CONDITIONS_REL,
        SCORE_CONTRACT_REL,
        STAGE_CONTRACT_REL,
        INDEX_PARQUET_REL,
        INDEX_META_REL,
    ):
        if not (root / relative).exists():
            raise OfficialValidationError(f"REQUIRED_AUTHORITY_MISSING:{relative}")
    stage4_authority = contract["stage4_authority"]
    if stage4_authority["validation_plan_sha256"] != sha256_file(root / STAGE4_PLAN_REL):
        raise OfficialValidationError("STAGE4_VALIDATION_PLAN_SHA_MISMATCH")
    if stage4_authority["common_conditions_sha256"] != sha256_file(root / COMMON_CONDITIONS_REL):
        raise OfficialValidationError("STAGE4_COMMON_CONDITIONS_SHA_MISMATCH")
    benchmark = IndexStore(root / "data/market/index/v01").verify_family(MARKET_INDEX_FAMILY)
    if benchmark["index_codes"] != ["1001", "2001"]:
        raise OfficialValidationError("BENCHMARK_INDEX_CODES_MISMATCH")
    if benchmark["content_sha256"] != contract["benchmarks"]["content_sha256"]:
        raise OfficialValidationError("BENCHMARK_HASH_MISMATCH")
    if contract["strategies"]["fundamentals_included"] is not False:
        raise OfficialValidationError("FUNDAMENTALS_MUST_BE_EXCLUDED")
    return {
        "status": "PASS",
        "contract_sha256": contract["contract_sha256"],
        "population_count": authority.population_count,
        "pit_interval_count": authority.pit_count,
        "benchmark_codes": benchmark["index_codes"],
    }


def _result_artifacts_present(root: Path) -> list[str]:
    output_dir = root / OUTPUT_DIR_REL
    return [
        name
        for name in (*OFFICIAL_RESULT_FILES, *SUPPORT_RESULT_FILES)
        if (output_dir / name).exists()
    ]


def preflight(root: Path = ROOT, *, write_contract: bool = False) -> dict[str, Any]:
    """Validate all Stage 5 inputs without evaluating any ticker."""
    root = Path(root).resolve()
    contract_path = root / CONTRACT_REL
    if write_contract:
        if contract_path.exists():
            raise OfficialValidationError("FROZEN_EXECUTION_CONTRACT_OVERWRITE_FORBIDDEN")
        _write_json(contract_path, build_execution_contract(root))
    if not contract_path.exists():
        raise OfficialValidationError("FROZEN_EXECUTION_CONTRACT_MISSING")
    contract = _read_json(contract_path)
    validation = validate_execution_contract(contract, root)
    authority = load_effective_authority(root / EFFECTIVE_AUTHORITY_REL)
    identity_intervals = _identity_intervals(authority)
    identity_tasks = _identity_tasks(authority)
    adjusted_store = root / "data/market/adjusted/stocks"
    raw_store = root / "data/market/raw/krx_stocks/v01"
    if not adjusted_store.is_dir() or not raw_store.is_dir():
        raise OfficialValidationError("REPOSITORY_V2_STORE_PATH_MISSING")
    result_artifacts = _result_artifacts_present(root)
    if result_artifacts:
        raise OfficialValidationError(f"OFFICIAL_RESULT_ARTIFACT_PRESENT:{result_artifacts}")
    if not callable(OfficialValidationRunner.run_realistic_portfolio):
        raise OfficialValidationError("PORTFOLIO_ENGINE_NOT_CALLABLE")
    # Do not build the Repository V2 raw index during preflight.  Its
    # constructor validates every raw partition, which is an execution-time
    # authority load rather than a lightweight contract check.  The official
    # run-scoped runner below still constructs the real Repository V2 object.
    repository_wiring = {
        "repository_class": f"{MarketDataRepositoryV2.__module__}.{MarketDataRepositoryV2.__name__}",
        "factory": "trend_scanner.data.repository_v2_loader.build_repository_v2",
        "loader": "trend_scanner.data.repository_v2_loader.RepositoryV2DailyLoader",
        "adjusted_store_exists": True,
        "raw_store_exists": True,
        "network_requests": 0,
    }
    return {
        "status": "READY",
        "work_id": WORK_ID,
        "official_backtest_executed": False,
        "result_artifacts_generated": False,
        "contract_path": _repo_path(contract_path),
        "contract_validation": validation,
        "population_count": authority.population_count,
        "pit_interval_count": authority.pit_count,
        "identity_key_count": len(identity_intervals),
        "identity_lifecycle_count": len(identity_tasks),
        "repository_v2": repository_wiring,
        "portfolio_engine_callable": True,
        "loader_count": 0,
        "network_requests": 0,
        "result_artifacts": [],
    }


class OfficialValidationRunner:
    """Run-scoped official inputs for the next explicit backtest task."""

    def __init__(
        self,
        root: Path = ROOT,
        contract: Mapping[str, Any] | None = None,
        *,
        identity_limit: int | None = None,
        reuse_lifecycle_caches: bool = True,
    ) -> None:
        self.root = Path(root).resolve()
        self.contract = dict(contract or _read_json(self.root / CONTRACT_REL))
        validate_execution_contract(self.contract, self.root)
        self.identity_limit = identity_limit
        self.reuse_lifecycle_caches = reuse_lifecycle_caches
        self.authority = load_effective_authority(self.root / EFFECTIVE_AUTHORITY_REL)
        self.intervals = _identity_intervals(self.authority)
        self.repository = build_repository_v2(self.root, end=EXECUTION_SUPPORT_END)
        self.loader = RepositoryV2DailyLoader(self.repository, end=EXECUTION_SUPPORT_END)
        self.score_contract = _read_json(self.root / SCORE_CONTRACT_REL)
        self.stage_contract = _read_json(self.root / STAGE_CONTRACT_REL)
        self._daily_cache: dict[str, pd.DataFrame] = {}
        self._ancillary_cache: dict[str, pd.DataFrame] = {}
        self._lifecycle_daily_cache: dict[IdentityTask, pd.DataFrame] = {}
        self._lifecycle_context_cache: dict[IdentityTask, Any] = {}
        self._lifecycle_raw_panel_cache: dict[IdentityTask, pd.DataFrame] = {}
        self._lifecycle_fast_snapshot_caches: dict[IdentityTask, FastSnapshotCache] = {}
        self._lifecycle_monthly_snapshot_caches: dict[IdentityTask, MonthlySnapshotCache] = {}
        self._all_identity_tasks: tuple[IdentityTask, ...] | None = None
        self.diagnostic_counts: dict[str, int] = {
            "valid_week_count": 0,
            "candidate_matched_signal_count": 0,
            "matched_v2_strategy_invocation_count": 0,
            "matched_julia_strategy_invocation_count": 0,
            "sequential_v2_strategy_invocation_count": 0,
            "sequential_julia_strategy_invocation_count": 0,
        }
        self.diagnostic_seconds: dict[str, float] = {
            "matched_discovery_seconds": 0.0,
            "matched_strategy_seconds": 0.0,
        }

    def _ensure_diagnostics(self) -> None:
        if not hasattr(self, "diagnostic_counts"):
            self.diagnostic_counts = {
                "valid_week_count": 0,
                "candidate_matched_signal_count": 0,
                "matched_v2_strategy_invocation_count": 0,
                "matched_julia_strategy_invocation_count": 0,
                "sequential_v2_strategy_invocation_count": 0,
                "sequential_julia_strategy_invocation_count": 0,
            }
        if not hasattr(self, "diagnostic_seconds"):
            self.diagnostic_seconds = {
                "matched_discovery_seconds": 0.0,
                "matched_strategy_seconds": 0.0,
            }

    def _ensure_lifecycle_caches(self) -> None:
        if not hasattr(self, "reuse_lifecycle_caches"):
            self.reuse_lifecycle_caches = True
        if not hasattr(self, "_lifecycle_daily_cache"):
            self._lifecycle_daily_cache = {}
            self._lifecycle_context_cache = {}
            self._lifecycle_raw_panel_cache = {}
            self._lifecycle_fast_snapshot_caches = {}
            self._lifecycle_monthly_snapshot_caches = {}

    def _lifecycle_daily(self, task: IdentityTask) -> pd.DataFrame:
        self._ensure_lifecycle_caches()
        if self.reuse_lifecycle_caches and task in self._lifecycle_daily_cache:
            return self._lifecycle_daily_cache[task]
        daily, _ = self.load_identity_inputs(task)
        clipped = clip_to_identity_lifecycle(daily, task.lifecycle())
        if clipped is None:
            raise OfficialValidationError(f"REPOSITORY_V2_DAILY_UNAVAILABLE:{task.key}")
        if self.reuse_lifecycle_caches:
            self._lifecycle_daily_cache[task] = clipped
        return clipped

    def _lifecycle_context(self, task: IdentityTask):
        self._ensure_diagnostics()
        self._ensure_lifecycle_caches()
        if self.reuse_lifecycle_caches and task in self._lifecycle_context_cache:
            return self._lifecycle_context_cache[task]
        context = build_precomputed_ticker_context(task.ticker, task.ticker, self._lifecycle_daily(task))
        self.diagnostic_counts["context_build_count"] = self.diagnostic_counts.get("context_build_count", 0) + 1
        if self.reuse_lifecycle_caches:
            self._lifecycle_context_cache[task] = context
        return context

    def _lifecycle_fast_snapshot_cache(self, task: IdentityTask) -> FastSnapshotCache | None:
        self._ensure_lifecycle_caches()
        if not self.reuse_lifecycle_caches:
            return None
        return self._lifecycle_fast_snapshot_caches.setdefault(task, FastSnapshotCache())

    def _lifecycle_monthly_snapshot_cache(self, task: IdentityTask) -> MonthlySnapshotCache | None:
        self._ensure_lifecycle_caches()
        if not self.reuse_lifecycle_caches:
            return None
        return self._lifecycle_monthly_snapshot_caches.setdefault(task, MonthlySnapshotCache())

    def diagnostic_snapshot(self) -> dict[str, int]:
        self._ensure_diagnostics()
        self._ensure_lifecycle_caches()
        return {
            **self.diagnostic_counts,
            "fast_actual_evaluation_count": sum(
                cache.evaluation_count for cache in self._lifecycle_fast_snapshot_caches.values()
            ),
            "fast_cache_hit_count": sum(
                cache.cache_hit_count for cache in self._lifecycle_fast_snapshot_caches.values()
            ),
            "monthly_actual_evaluation_count": sum(
                cache.evaluation_count for cache in self._lifecycle_monthly_snapshot_caches.values()
            ),
            "monthly_cache_hit_count": sum(
                cache.cache_hit_count for cache in self._lifecycle_monthly_snapshot_caches.values()
            ),
            "context_build_count": int(self.diagnostic_counts.get("context_build_count", 0)),
            "raw_panel_build_count": int(self.diagnostic_counts.get("raw_panel_build_count", 0)),
        }

    def identity_tasks(self) -> tuple[IdentityTask, ...]:
        if self._all_identity_tasks is None:
            self._all_identity_tasks = _identity_tasks(self.authority)
        if self.identity_limit is None:
            return self._all_identity_tasks
        return select_performance_sample_tasks(self._all_identity_tasks, self.identity_limit)

    def load_identity_inputs(self, task: IdentityTask) -> tuple[pd.DataFrame, pd.DataFrame]:
        if task.ticker not in self._daily_cache:
            daily = self.loader.load(task.ticker)
            ancillary = self.loader.load_ancillary(task.ticker)
            if daily is None or daily.empty:
                raise OfficialValidationError(f"REPOSITORY_V2_DAILY_UNAVAILABLE:{task.key}")
            if ancillary is None or ancillary.empty:
                raise OfficialValidationError(f"REPOSITORY_V2_ANCILLARY_UNAVAILABLE:{task.key}")
            self._daily_cache[task.ticker] = daily
            self._ancillary_cache[task.ticker] = ancillary
        return self._daily_cache[task.ticker], self._ancillary_cache[task.ticker]

    def identity_raw_panel(self, task: IdentityTask) -> pd.DataFrame:
        self._ensure_diagnostics()
        self._ensure_lifecycle_caches()
        if self.reuse_lifecycle_caches and task in self._lifecycle_raw_panel_cache:
            return self._lifecycle_raw_panel_cache[task]
        _, ancillary = self.load_identity_inputs(task)
        panel = build_identity_raw_panel(ancillary, task)
        self.diagnostic_counts["raw_panel_build_count"] = self.diagnostic_counts.get("raw_panel_build_count", 0) + 1
        if self.reuse_lifecycle_caches:
            self._lifecycle_raw_panel_cache[task] = panel
        return panel

    def _entry_gate(self, task: IdentityTask, panel: pd.DataFrame):
        def gate(_as_of: pd.Timestamp, values: dict[str, Any]) -> dict[str, Any]:
            signal_date = pd.Timestamp(values["signal_date"]).normalize()
            row = _find_exact_raw_row(panel, signal_date)
            if row is None:
                return {"gate_pass": False, "gate_id": "EXACT_DATE_PIT_ANCILLARY"}
            if not pit_common_for_identity(self.intervals, task.ticker, task.isu_cd, task.market, signal_date):
                return {"gate_pass": False, "gate_id": "EXACT_DATE_PIT_MEMBERSHIP"}
            market_cap = pd.to_numeric(row.get("market_cap"), errors="coerce")
            avg_value = pd.to_numeric(row.get("avg_trading_value_20d"), errors="coerce")
            passed = bool(
                pd.notna(market_cap)
                and pd.notna(avg_value)
                and float(market_cap) >= MARKET_CAP_THRESHOLD_KRW
                and float(avg_value) >= AVG_TRADING_VALUE_20D_THRESHOLD_KRW
            )
            return {
                "gate_pass": passed,
                "gate_id": "EXACT_DATE_PIT_MCAP_AND_20D_TRADING_VALUE",
                "market_cap": None if pd.isna(market_cap) else float(market_cap),
                "avg_trading_value_20d": None if pd.isna(avg_value) else float(avg_value),
                "market_cap_source": "RepositoryV2DailyLoader.load_ancillary",
                "market_cap_exact_date": True,
                "proxy_market_cap": False,
                "nearest_date_fallback": False,
            }

        return gate

    def run_identity_strategy(
        self,
        task: IdentityTask,
        *,
        enable_loss_guard: bool,
        allowed_signal_dates: set[pd.Timestamp] | frozenset[pd.Timestamp] | None = None,
    ) -> list[StrategyTradeRecord]:
        daily, _ = self.load_identity_inputs(task)
        panel = self.identity_raw_panel(task)
        context = self._lifecycle_context(task) if self.reuse_lifecycle_caches else None
        strategy_id = BASE_STRATEGY_ID if enable_loss_guard else JULIA_STRATEGY_ID
        return simulate_ticker_strategy_fundamentals_v01(
            strategy_id=strategy_id,
            ticker=task.ticker,
            isu_cd=task.isu_cd,
            name=task.ticker,
            market=task.market,
            daily=daily,
            raw_panel=panel,
            score_contract=self.score_contract,
            stage_contract=self.stage_contract,
            loss_guard_enabled=enable_loss_guard,
            backtest_end=EXECUTION_SUPPORT_END,
            entry_eligible_from=START_DATE,
            allowed_signal_dates=allowed_signal_dates,
            snapshot_context=context,
            fast_snapshot_cache=self._lifecycle_fast_snapshot_cache(task),
            monthly_snapshot_cache=self._lifecycle_monthly_snapshot_cache(task),
            identity_lifecycle=task.lifecycle(),
            pit_membership=lambda ticker, isu_cd, market, value: pit_common_for_identity(
                self.intervals, ticker, isu_cd, market, value
            ),
            entry_gate=self._entry_gate(task, panel),
            fundamental_exit_callback=None,
            market_cap_threshold=MARKET_CAP_THRESHOLD_KRW,
            avg_trading_value_threshold=AVG_TRADING_VALUE_20D_THRESHOLD_KRW,
            close_threshold=None,
        )

    def discover_matched_entry_signals(self, task: IdentityTask) -> tuple[EntrySignal, ...]:
        """Create the strategy-neutral entry ledger used by Matched-entry.

        This scan does not call either strategy lifecycle.  It therefore cannot
        collapse Matched-entry into a Sequential intersection.
        """
        self._ensure_diagnostics()
        daily = self._lifecycle_daily(task)
        if daily is None or daily.empty:
            return ()
        context = self._lifecycle_context(task)
        weekly = context.weekly_up_to(EXECUTION_SUPPORT_END)
        daily_dates = set(pd.DatetimeIndex(daily.index).normalize())
        valid_weeks = [pd.Timestamp(w).normalize() for w in weekly.index if pd.Timestamp(w).normalize() in daily_dates]
        valid_weeks = [week for week in valid_weeks if START_DATE <= week <= SIGNAL_CUTOFF]
        self.diagnostic_counts["valid_week_count"] += len(valid_weeks)
        panel = self.identity_raw_panel(task)
        fast_snapshot_cache = self._lifecycle_fast_snapshot_cache(task)
        signals: list[EntrySignal] = []
        for week in valid_weeks:
            if fast_snapshot_cache is None:
                result = evaluate_pattern_a_fast(
                    task.ticker,
                    task.ticker,
                    daily,
                    week,
                    self.score_contract,
                    self.stage_contract,
                    context=context,
                )
            else:
                result = fast_snapshot_cache.get(
                    task.ticker,
                    task.ticker,
                    daily,
                    week,
                    self.score_contract,
                    self.stage_contract,
                    context=context,
                )
                if result is None:
                    continue
            if not is_qualifying_fast_entry(result):
                continue
            if not pit_common_for_identity(self.intervals, task.ticker, task.isu_cd, task.market, week):
                continue
            row = _find_exact_raw_row(panel, week)
            if row is None:
                continue
            mcap = pd.to_numeric(row["market_cap"], errors="coerce")
            avg_value = pd.to_numeric(row["avg_trading_value_20d"], errors="coerce")
            if pd.isna(mcap) or pd.isna(avg_value) or float(mcap) < MARKET_CAP_THRESHOLD_KRW or float(avg_value) < AVG_TRADING_VALUE_20D_THRESHOLD_KRW:
                continue
            positions = daily.index.searchsorted(week, side="right")
            if positions >= len(daily.index):
                continue
            execution_date = pd.Timestamp(daily.index[positions]).normalize()
            if execution_date > EXECUTION_SUPPORT_END or not pit_common_for_identity(self.intervals, task.ticker, task.isu_cd, task.market, execution_date):
                continue
            signals.append(EntrySignal(task, week, execution_date, float(mcap), float(avg_value)))
            self.diagnostic_counts["candidate_matched_signal_count"] += 1
        return tuple(signals)

    def run_matched_entry(self) -> dict[str, Any]:
        """Prepare matched pairs from an independent, strategy-neutral ledger."""
        self._ensure_diagnostics()
        pairs: list[dict[str, Any]] = []
        signal_count = 0
        for task in self.identity_tasks():
            discovery_started = time.perf_counter()
            signals = self.discover_matched_entry_signals(task)
            self.diagnostic_seconds["matched_discovery_seconds"] += time.perf_counter() - discovery_started
            signal_count += len(signals)
            for signal in signals:
                strategy_started = time.perf_counter()
                self.diagnostic_counts["matched_v2_strategy_invocation_count"] += 1
                base = self.run_identity_strategy(task, enable_loss_guard=True, allowed_signal_dates={signal.signal_date})
                self.diagnostic_counts["matched_julia_strategy_invocation_count"] += 1
                julia = self.run_identity_strategy(task, enable_loss_guard=False, allowed_signal_dates={signal.signal_date})
                self.diagnostic_seconds["matched_strategy_seconds"] += time.perf_counter() - strategy_started
                pairs.append({
                    "entry_key": signal.key(),
                    "signal": signal,
                    "base": base[0] if len(base) == 1 else None,
                    "julia": julia[0] if len(julia) == 1 else None,
                    "status": "PASS" if len(base) == len(julia) == 1 else "UNRESOLVED",
                })
        return {"axis": "Matched-entry", "candidate_signal_count": signal_count, "pairs": pairs}

    def run_sequential(self) -> dict[str, list[StrategyTradeRecord]]:
        """Run each strategy's independent re-entry path; never intersect it."""
        self._ensure_diagnostics()
        result = {BASE_STRATEGY_ID: [], JULIA_STRATEGY_ID: []}
        for task in self.identity_tasks():
            self.diagnostic_counts["sequential_v2_strategy_invocation_count"] += 1
            result[BASE_STRATEGY_ID].extend(self.run_identity_strategy(task, enable_loss_guard=True))
            self.diagnostic_counts["sequential_julia_strategy_invocation_count"] += 1
            result[JULIA_STRATEGY_ID].extend(self.run_identity_strategy(task, enable_loss_guard=False))
        return result

    def run_realistic_portfolio(
        self,
        records_by_strategy: Mapping[str, Sequence[StrategyTradeRecord]],
        *,
        market_data_by_identity: Mapping[Any, pd.DataFrame] | None = None,
    ) -> dict[str, Any]:
        """Execute each strategy's frozen 200M portfolio in memory.

        ``records_by_strategy`` must contain independent Sequential records.
        Official execution loads exact Repository V2 daily frames when no
        synthetic ``market_data_by_identity`` is supplied.  The method never
        writes result artifacts; it returns the event ledger, daily equity, and
        metrics needed by the next explicit official execution task.
        """
        records_by_strategy = {
            str(strategy_id): list(records)
            for strategy_id, records in records_by_strategy.items()
        }
        frames = _normalise_portfolio_market_data(market_data_by_identity)
        all_records = [record for records in records_by_strategy.values() for record in records]

        # The official path obtains valuation/fill prices from Repository V2.
        # Synthetic focused tests may pass exact-date frames directly.  The
        # record fields remain an exact-date input fallback only for the small
        # compatibility case where a test object has no loader or frame.
        if market_data_by_identity is None and hasattr(self, "loader"):
            tickers = sorted({str(_record_value(record, "ticker", "")) for record in all_records})
            for ticker in tickers:
                frame = self.loader.load(ticker)
                if frame is not None:
                    normalized = _normalise_portfolio_market_data({ticker: frame})
                    frames[ticker] = normalized[ticker]

        def frame_for(record: Any) -> pd.DataFrame | None:
            identity = _identity_key_from_record(record)
            ticker = identity[0]
            return frames.get(identity, frames.get(ticker))

        def exact_price(record: Any, day: pd.Timestamp, column: str) -> float | None:
            return _exact_record_price(record, frame_for(record), day, column)

        portfolio_dates: set[pd.Timestamp] = {FINAL_VALUATION_DATE}
        for record in all_records:
            for field in ("entry_execution_date", "exit_execution_date", "cutoff_date"):
                value = _record_date(record, field)
                if value is not None and START_DATE <= value <= FINAL_VALUATION_DATE:
                    portfolio_dates.add(value)
        for frame in frames.values():
            if frame is not None and not frame.empty:
                portfolio_dates.update(
                    day for day in pd.DatetimeIndex(frame.index).normalize()
                    if START_DATE <= day <= FINAL_VALUATION_DATE
                )
        dates = tuple(sorted(portfolio_dates))
        next_date = {day: dates[index + 1] for index, day in enumerate(dates[:-1])}

        def event_base(record: Any, strategy_id: str, day: pd.Timestamp, event_type: str) -> dict[str, Any]:
            return {
                "strategy_id": strategy_id,
                "ticker": str(_record_value(record, "ticker", "")),
                "isu_cd": _record_value(record, "isu_cd"),
                "market": str(_record_value(record, "market", "")),
                "position_id": str(_record_value(record, "trade_id", "")),
                "signal_date": (
                    _record_value(record, "entry_signal_date")
                    if event_type == "ENTRY"
                    else _record_value(record, "exit_signal_date")
                    if event_type == "EXIT"
                    else None
                ),
                "execution_date": day.strftime("%Y-%m-%d"),
                "event_type": event_type,
                "event_status": None,
                "reference_open": None,
                "slippage_adjusted_price": None,
                "shares": 0,
                "notional": 0.0,
                "commission": 0.0,
                "sell_tax": 0.0,
                "cash_before": None,
                "cash_after": None,
                "pending_sale_proceeds": 0.0,
                "entry_or_exit_reason": None,
                "market_cap_at_signal": _record_value(record, "entry_market_cap"),
                "unresolved_reason": None,
                "open_at_cutoff": False,
            }

        strategy_results: dict[str, Any] = {}
        for strategy_id, records in records_by_strategy.items():
            entries_by_date: dict[pd.Timestamp, list[Any]] = {}
            for record in records:
                entry_date = _record_date(record, "entry_execution_date")
                if entry_date is not None and START_DATE <= entry_date <= FINAL_VALUATION_DATE:
                    entries_by_date.setdefault(entry_date, []).append(record)

            cash = float(INITIAL_CAPITAL_KRW)
            pending_by_date: dict[pd.Timestamp, float] = {}
            terminal_pending = 0.0
            positions: dict[str, dict[str, Any]] = {}
            events: list[dict[str, Any]] = []
            daily_equity: list[dict[str, Any]] = []
            realized_returns: list[float] = []
            holding_days: list[int] = []
            total_commission = 0.0
            total_sell_tax = 0.0
            total_notional = 0.0
            slippage_impact = 0.0
            trade_count = 0
            unresolved_count = 0
            peak_equity = float(INITIAL_CAPITAL_KRW)
            cash_conservation_pass = True

            for day in dates:
                released = pending_by_date.pop(day, 0.0)
                cash += released
                exited_today: set[str] = set()

                # Existing positions always exit before any same-open entry.
                for ticker, position in sorted(list(positions.items())):
                    exit_date = position["exit_date"]
                    if exit_date is None or exit_date != day:
                        continue
                    exited_today.add(ticker)
                    record = position["record"]
                    event = event_base(record, strategy_id, day, "EXIT")
                    event["cash_before"] = cash
                    reference_open = exact_price(record, day, "open")
                    if reference_open is None:
                        event.update(
                            event_status="UNRESOLVED",
                            entry_or_exit_reason="EXIT",
                            unresolved_reason="MISSING_EXACT_EXIT_OPEN",
                            open_at_cutoff=False,
                            cash_after=cash,
                            pending_sale_proceeds=sum(pending_by_date.values()) + terminal_pending,
                        )
                        events.append(event)
                        unresolved_count += 1
                        continue

                    shares = int(position["shares"])
                    fill_price = reference_open * (1.0 - SLIPPAGE_RATE)
                    notional = fill_price * shares
                    commission = notional * COMMISSION_RATE
                    sell_tax = notional * _tax_rate(day, position["market"])
                    proceeds = notional - commission - sell_tax
                    cash_before = cash
                    release_date = next_date.get(day)
                    if release_date is None:
                        terminal_pending += proceeds
                    else:
                        pending_by_date[release_date] = pending_by_date.get(release_date, 0.0) + proceeds
                    del positions[ticker]
                    total_commission += commission
                    total_sell_tax += sell_tax
                    total_notional += notional
                    slippage_impact += abs(reference_open - fill_price) * shares
                    realized_returns.append((proceeds - position["buy_cost"]) / position["buy_cost"])
                    holding_days.append(max(0, int((day - position["entry_date"]).days)))
                    event.update(
                        event_status="EXECUTED",
                        reference_open=reference_open,
                        slippage_adjusted_price=fill_price,
                        shares=shares,
                        notional=notional,
                        commission=commission,
                        sell_tax=sell_tax,
                        cash_before=cash_before,
                        cash_after=cash,
                        pending_sale_proceeds=sum(pending_by_date.values()) + terminal_pending,
                        entry_or_exit_reason=str(_record_value(record, "exit_type", "EXIT")),
                    )
                    events.append(event)

                candidates = sorted(
                    entries_by_date.get(day, []),
                    key=lambda record: (
                        0 if _record_value(record, "entry_market_cap") is not None else 1,
                        -float(_record_value(record, "entry_market_cap"))
                        if _record_value(record, "entry_market_cap") is not None else 0.0,
                        str(_record_value(record, "ticker", "")),
                    ),
                )
                for record in candidates:
                    ticker = str(_record_value(record, "ticker", ""))
                    event = event_base(record, strategy_id, day, "ENTRY")
                    event["cash_before"] = cash
                    event["entry_or_exit_reason"] = "ENTRY"
                    market_cap = _record_value(record, "entry_market_cap")
                    if ticker in exited_today:
                        event.update(
                            event_status="SKIPPED_SAME_OPEN_EXIT_REENTRY",
                            unresolved_reason="SAME_OPEN_EXIT_REENTRY_FORBIDDEN",
                            cash_after=cash,
                            pending_sale_proceeds=sum(pending_by_date.values()) + terminal_pending,
                        )
                        events.append(event)
                        continue
                    if ticker in positions:
                        event.update(
                            event_status="SKIPPED_DUPLICATE_HOLDING",
                            unresolved_reason="DUPLICATE_HOLDING_FORBIDDEN",
                            cash_after=cash,
                            pending_sale_proceeds=sum(pending_by_date.values()) + terminal_pending,
                        )
                        events.append(event)
                        continue
                    if market_cap is None or pd.isna(market_cap):
                        event.update(
                            event_status="UNRESOLVED",
                            unresolved_reason="MISSING_EXACT_SIGNAL_MARKET_CAP",
                            cash_after=cash,
                            pending_sale_proceeds=sum(pending_by_date.values()) + terminal_pending,
                        )
                        events.append(event)
                        unresolved_count += 1
                        continue
                    if float(market_cap) < MARKET_CAP_THRESHOLD_KRW:
                        event.update(
                            event_status="UNRESOLVED",
                            unresolved_reason="SIGNAL_MARKET_CAP_BELOW_CONTRACT_THRESHOLD",
                            cash_after=cash,
                            pending_sale_proceeds=sum(pending_by_date.values()) + terminal_pending,
                        )
                        events.append(event)
                        unresolved_count += 1
                        continue
                    if len(positions) >= MAX_POSITIONS:
                        event.update(
                            event_status="SKIPPED_POSITION_LIMIT",
                            unresolved_reason="NO_EMPTY_SLOT",
                            cash_after=cash,
                            pending_sale_proceeds=sum(pending_by_date.values()) + terminal_pending,
                        )
                        events.append(event)
                        continue
                    reference_open = exact_price(record, day, "open")
                    if reference_open is None:
                        event.update(
                            event_status="UNRESOLVED",
                            unresolved_reason="MISSING_EXACT_ENTRY_OPEN",
                            cash_after=cash,
                            pending_sale_proceeds=sum(pending_by_date.values()) + terminal_pending,
                        )
                        events.append(event)
                        unresolved_count += 1
                        continue
                    fill_price = reference_open * (1.0 + SLIPPAGE_RATE)
                    budget = min(POSITION_CASH_BUDGET_KRW, INITIAL_CAPITAL_KRW * 0.025)
                    shares = int(math.floor((budget + 1e-9) / (fill_price * (1.0 + COMMISSION_RATE))))
                    if shares <= 0:
                        event.update(
                            event_status="SKIPPED_ZERO_SHARES",
                            unresolved_reason="MAX_INTEGER_SHARES_ZERO",
                            cash_after=cash,
                            pending_sale_proceeds=sum(pending_by_date.values()) + terminal_pending,
                        )
                        events.append(event)
                        continue
                    notional = fill_price * shares
                    commission = notional * COMMISSION_RATE
                    total_cost = notional + commission
                    if total_cost > cash + 1e-6:
                        event.update(
                            event_status="SKIPPED_CASH_UNAVAILABLE",
                            unresolved_reason="INSUFFICIENT_AVAILABLE_CASH",
                            cash_after=cash,
                            pending_sale_proceeds=sum(pending_by_date.values()) + terminal_pending,
                        )
                        events.append(event)
                        continue
                    cash_before = cash
                    cash -= total_cost
                    positions[ticker] = {
                        "record": record,
                        "ticker": ticker,
                        "market": str(_record_value(record, "market", "")),
                        "shares": shares,
                        "entry_date": day,
                        "entry_price": fill_price,
                        "buy_cost": total_cost,
                        "exit_date": _record_date(record, "exit_execution_date"),
                    }
                    total_commission += commission
                    total_notional += notional
                    slippage_impact += abs(fill_price - reference_open) * shares
                    trade_count += 1
                    event.update(
                        event_status="EXECUTED",
                        reference_open=reference_open,
                        slippage_adjusted_price=fill_price,
                        shares=shares,
                        notional=notional,
                        commission=commission,
                        cash_before=cash_before,
                        cash_after=cash,
                        pending_sale_proceeds=sum(pending_by_date.values()) + terminal_pending,
                    )
                    events.append(event)

                invested_value = 0.0
                valuation_missing = False
                for position in positions.values():
                    close = exact_price(position["record"], day, "close")
                    if close is None:
                        valuation_missing = True
                        continue
                    invested_value += position["shares"] * close
                pending_total = sum(pending_by_date.values()) + terminal_pending
                equity = None if valuation_missing else cash + pending_total + invested_value
                if equity is not None:
                    peak_equity = max(peak_equity, equity)
                    drawdown = equity / peak_equity - 1.0
                    exposure = invested_value / equity if equity else 0.0
                    cash_conservation_pass = cash_conservation_pass and abs(
                        equity - (cash + pending_total + invested_value)
                    ) <= 1e-6
                else:
                    drawdown = None
                    exposure = None
                daily_equity.append({
                    "date": day.strftime("%Y-%m-%d"),
                    "strategy_id": strategy_id,
                    "cash": cash,
                    "pending_sale_proceeds": pending_total,
                    "invested_market_value": invested_value if not valuation_missing else None,
                    "equity": equity,
                    "exposure": exposure,
                    "drawdown": drawdown,
                })

                if day == FINAL_VALUATION_DATE:
                    for position in positions.values():
                        event = event_base(position["record"], strategy_id, day, "VALUATION")
                        event["event_status"] = "EXECUTED"
                        event["entry_or_exit_reason"] = "OPEN_AT_CUTOFF_VALUATION"
                        event["open_at_cutoff"] = True
                        event["cash_before"] = cash
                        event["cash_after"] = cash
                        event["shares"] = int(position["shares"])
                        close = exact_price(position["record"], day, "close")
                        if close is None:
                            event["event_status"] = "UNRESOLVED"
                            lifecycle_ended = (
                                _record_value(position["record"], "trade_status") == "OPEN_AT_CUTOFF"
                                and _record_date(position["record"], "exit_execution_date") is None
                                and (
                                    _record_date(position["record"], "cutoff_date") is not None
                                    and _record_date(position["record"], "cutoff_date") < FINAL_VALUATION_DATE
                                )
                            )
                            event["unresolved_reason"] = (
                                "IDENTITY_LIFECYCLE_ENDED_BEFORE_FINAL_VALUATION"
                                if lifecycle_ended
                                else "MISSING_EXACT_CUTOFF_CLOSE"
                            )
                            unresolved_count += 1
                        else:
                            event["reference_open"] = close
                            event["slippage_adjusted_price"] = close
                            event["notional"] = close * position["shares"]
                        event["pending_sale_proceeds"] = pending_total
                        events.append(event)

            final_rows = [row for row in daily_equity if row["date"] == FINAL_VALUATION_DATE.strftime("%Y-%m-%d")]
            final_equity = final_rows[-1]["equity"] if final_rows and final_rows[-1]["equity"] is not None else None
            total_return = (final_equity / INITIAL_CAPITAL_KRW - 1.0) if final_equity is not None else None
            period_days = max(1, int((FINAL_VALUATION_DATE - START_DATE).days))
            cagr = (
                (1.0 + total_return) ** (365.25 / period_days) - 1.0
                if total_return is not None and total_return > -1.0
                else None
            )
            drawdowns = [row["drawdown"] for row in daily_equity if row["drawdown"] is not None]
            exposures = [row["exposure"] for row in daily_equity if row["exposure"] is not None]
            wins = [value for value in realized_returns if value > 0]
            losses = [value for value in realized_returns if value < 0]
            payoff_ratio = (
                (sum(wins) / len(wins)) / abs(sum(losses) / len(losses))
                if wins and losses and sum(losses) != 0
                else None
            )
            strategy_results[strategy_id] = {
                "status": "INCOMPLETE_REQUIRES_REVIEW" if unresolved_count else "PASS",
                "event_ledger": events,
                "daily_equity": daily_equity,
                "metrics": {
                    "total_return": total_return,
                    "cagr": cagr,
                    "mdd": min(drawdowns) if drawdowns else None,
                    "exposure": sum(exposures) / len(exposures) if exposures else None,
                    "turnover": total_notional / INITIAL_CAPITAL_KRW,
                    "trade_count": trade_count,
                    "holding_period_days": sum(holding_days) / len(holding_days) if holding_days else None,
                    "win_rate": len(wins) / len(realized_returns) if realized_returns else None,
                    "payoff_ratio": payoff_ratio,
                    "open_at_cutoff": len(positions),
                    "total_commission": total_commission,
                    "total_sell_tax": total_sell_tax,
                    "slippage_impact": slippage_impact,
                    "unresolved_count": unresolved_count,
                    "cash_conservation_pass": cash_conservation_pass,
                },
            }

        return {
            "axis": "Realistic 200M Portfolio",
            "ready": True,
            "engine": "IN_MEMORY_FROZEN_PORTFOLIO_V01",
            "strategy_ids": sorted(strategy_results),
            "initial_capital_krw": INITIAL_CAPITAL_KRW,
            "per_symbol_cash_budget_krw": POSITION_CASH_BUDGET_KRW,
            "max_positions": MAX_POSITIONS,
            "sell_tax_mapping": "execution_date_and_market",
            "same_open_sale_proceeds_reusable": False,
            "event_ledger_columns": [
                "strategy_id", "ticker", "isu_cd", "market", "position_id", "signal_date",
                "execution_date", "event_type", "event_status", "reference_open",
                "slippage_adjusted_price", "shares", "notional", "commission", "sell_tax",
                "cash_before", "cash_after", "pending_sale_proceeds", "entry_or_exit_reason",
                "market_cap_at_signal", "unresolved_reason", "open_at_cutoff",
            ],
            "daily_equity_columns": [
                "date", "strategy_id", "cash", "pending_sale_proceeds", "invested_market_value",
                "equity", "exposure", "drawdown",
            ],
            "records_received": {str(key): len(value) for key, value in records_by_strategy.items()},
            "strategies": strategy_results,
            "result_artifacts_written": False,
        }


_PARALLEL_RUNNER: OfficialValidationRunner | None = None


def _diagnostic_delta(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, int]:
    keys = set(before) | set(after)
    return {
        str(key): int(after.get(key, 0) or 0) - int(before.get(key, 0) or 0)
        for key in keys
    }


def _run_identity_task_bundle(
    official: OfficialValidationRunner,
    task: IdentityTask,
) -> dict[str, Any]:
    """Run every strategy path for one lifecycle with one cache scope."""
    before_counts = official.diagnostic_snapshot()
    discovery_started = time.perf_counter()
    signals = official.discover_matched_entry_signals(task)
    discovery_seconds = time.perf_counter() - discovery_started

    strategy_started = time.perf_counter()
    pairs: list[dict[str, Any]] = []
    for signal in signals:
        official.diagnostic_counts["matched_v2_strategy_invocation_count"] += 1
        base = official.run_identity_strategy(
            task,
            enable_loss_guard=True,
            allowed_signal_dates={signal.signal_date},
        )
        official.diagnostic_counts["matched_julia_strategy_invocation_count"] += 1
        julia = official.run_identity_strategy(
            task,
            enable_loss_guard=False,
            allowed_signal_dates={signal.signal_date},
        )
        pairs.append({
            "entry_key": signal.key(),
            "signal": signal,
            "base": base[0] if len(base) == 1 else None,
            "julia": julia[0] if len(julia) == 1 else None,
            "status": "PASS" if len(base) == len(julia) == 1 else "UNRESOLVED",
        })
    matched_strategy_seconds = time.perf_counter() - strategy_started

    sequential_started = time.perf_counter()
    official.diagnostic_counts["sequential_v2_strategy_invocation_count"] += 1
    base_sequential = official.run_identity_strategy(task, enable_loss_guard=True)
    official.diagnostic_counts["sequential_julia_strategy_invocation_count"] += 1
    julia_sequential = official.run_identity_strategy(task, enable_loss_guard=False)
    sequential_seconds = time.perf_counter() - sequential_started
    after_counts = official.diagnostic_snapshot()
    return {
        "task": task,
        "matched_signals": signals,
        "matched_pairs": pairs,
        "sequential": {
            BASE_STRATEGY_ID: base_sequential,
            JULIA_STRATEGY_ID: julia_sequential,
        },
        "timing": {
            "matched_discovery_seconds": discovery_seconds,
            "matched_strategy_seconds": matched_strategy_seconds,
            "matched_entry_seconds": discovery_seconds + matched_strategy_seconds,
            "sequential_seconds": sequential_seconds,
        },
        "diagnostic_counts": _diagnostic_delta(before_counts, after_counts),
    }


def _parallel_worker_chunk(tasks: tuple[IdentityTask, ...]) -> dict[str, Any]:
    """Process one deterministic lifecycle chunk in an inherited runner."""
    official = _PARALLEL_RUNNER
    if official is None:
        raise OfficialValidationError("PARALLEL_WORKER_RUNNER_UNAVAILABLE")
    started = time.perf_counter()
    usage_before = _resource_snapshot()
    bundles = [_run_identity_task_bundle(official, task) for task in tasks]
    usage_after = _resource_snapshot()
    return {
        "bundles": bundles,
        "worker_seconds": time.perf_counter() - started,
        "user_cpu_seconds": usage_after["user_cpu_seconds"] - usage_before["user_cpu_seconds"],
        "system_cpu_seconds": usage_after["system_cpu_seconds"] - usage_before["system_cpu_seconds"],
        "max_rss_mib": usage_after["max_rss_mib"],
    }


def run_parallel_lifecycle_sample(
    official: OfficialValidationRunner,
    tasks: Sequence[IdentityTask],
    *,
    workers: int,
) -> dict[str, Any]:
    """Run lifecycle bundles with the existing bounded process-pool pattern."""
    if workers not in {2, 4, 6}:
        raise OfficialValidationError(f"PARALLEL_WORKER_COUNT_UNSUPPORTED:{workers}")
    if not tasks:
        raise OfficialValidationError("PARALLEL_SAMPLE_HAS_NO_TASKS")
    effective_workers = min(workers, len(tasks))
    chunk_size = math.ceil(len(tasks) / effective_workers)
    chunks = tuple(
        tuple(tasks[offset : offset + chunk_size])
        for offset in range(0, len(tasks), chunk_size)
    )

    global _PARALLEL_RUNNER
    _PARALLEL_RUNNER = official
    pool_started = time.perf_counter()
    try:
        try:
            context = mp.get_context("fork")
        except ValueError as exc:
            raise OfficialValidationError("PARALLEL_FORK_CONTEXT_UNAVAILABLE") from exc
        with ProcessPoolExecutor(
            max_workers=effective_workers,
            mp_context=context,
        ) as executor:
            chunk_results = tuple(executor.map(_parallel_worker_chunk, chunks))
    finally:
        _PARALLEL_RUNNER = None
    pool_seconds = time.perf_counter() - pool_started

    matched_pairs: list[dict[str, Any]] = []
    candidate_signal_count = 0
    sequential_result: dict[str, list[StrategyTradeRecord]] = {
        BASE_STRATEGY_ID: [],
        JULIA_STRATEGY_ID: [],
    }
    diagnostic_counts: dict[str, int] = {}
    phase_work_seconds = {
        "matched_discovery_seconds": 0.0,
        "matched_strategy_seconds": 0.0,
        "matched_entry_seconds": 0.0,
        "sequential_seconds": 0.0,
    }
    phase_wall_seconds = {
        "matched_discovery_seconds": 0.0,
        "matched_strategy_seconds": 0.0,
        "matched_entry_seconds": 0.0,
        "sequential_seconds": 0.0,
    }
    for chunk_result in chunk_results:
        chunk_timing = {key: 0.0 for key in phase_work_seconds}
        for bundle in chunk_result["bundles"]:
            candidate_signal_count += len(bundle["matched_signals"])
            matched_pairs.extend(bundle["matched_pairs"])
            for strategy_id, records in bundle["sequential"].items():
                sequential_result[strategy_id].extend(records)
            for key, value in bundle["timing"].items():
                phase_work_seconds[key] += float(value)
                chunk_timing[key] += float(value)
            for key, value in bundle["diagnostic_counts"].items():
                diagnostic_counts[key] = diagnostic_counts.get(key, 0) + int(value)
        for key, value in chunk_timing.items():
            phase_wall_seconds[key] = max(phase_wall_seconds[key], value)

    worker_work_seconds = max(
        (float(chunk_result["worker_seconds"]) for chunk_result in chunk_results),
        default=0.0,
    )
    diagnostic_counts["candidate_matched_signal_count"] = candidate_signal_count
    official.diagnostic_counts.update(diagnostic_counts)
    official.diagnostic_seconds["matched_discovery_seconds"] = phase_wall_seconds[
        "matched_discovery_seconds"
    ]
    official.diagnostic_seconds["matched_strategy_seconds"] = phase_wall_seconds[
        "matched_strategy_seconds"
    ]
    return {
        "matched_result": {
            "axis": "Matched-entry",
            "candidate_signal_count": candidate_signal_count,
            "pairs": matched_pairs,
        },
        "sequential_result": sequential_result,
        "diagnostic_counts": diagnostic_counts,
        "timing": {
            "pool_seconds": pool_seconds,
            "worker_work_seconds": worker_work_seconds,
            "worker_startup_aggregation_overhead_seconds": max(
                0.0,
                pool_seconds - worker_work_seconds,
            ),
            "phase_work_seconds": phase_work_seconds,
            "phase_wall_seconds_estimate": phase_wall_seconds,
            "effective_workers": effective_workers,
        },
        "resource": {
            "user_cpu_seconds": sum(float(item["user_cpu_seconds"]) for item in chunk_results),
            "system_cpu_seconds": sum(float(item["system_cpu_seconds"]) for item in chunk_results),
            "max_rss_mib": max(float(item["max_rss_mib"]) for item in chunk_results),
        },
    }


def _json_safe(value: Any) -> Any:
    """Convert result values to deterministic JSON/CSV-safe scalar structures."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    if isinstance(value, Mapping):
        return {str(key): _json_safe(child) for key, child in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(child) for child in value]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _json_safe(value.to_dict())
    if hasattr(value, "item") and callable(value.item):
        try:
            return _json_safe(value.item())
        except (TypeError, ValueError):
            pass
    return str(value)


def _safe_scalar(value: Any) -> Any:
    safe = _json_safe(value)
    return safe if not isinstance(safe, (Mapping, list)) else None


def _mean_median(values: Sequence[float]) -> dict[str, float | None]:
    finite = [float(value) for value in values if math.isfinite(float(value))]
    return {
        "mean": mean(finite) if finite else None,
        "median": median(finite) if finite else None,
    }


def _trade_summary(records: Sequence[Any]) -> dict[str, Any]:
    realized = [record for record in records if _record_value(record, "trade_status") == "REALIZED"]
    open_at_cutoff = [record for record in records if _record_value(record, "trade_status") == "OPEN_AT_CUTOFF"]
    returns = [
        float(value)
        for record in records
        for value in [_record_value(record, "terminal_return")]
        if isinstance(value, (int, float)) and math.isfinite(float(value))
    ]
    realized_returns = [
        float(value)
        for record in realized
        for value in [_record_value(record, "terminal_return")]
        if isinstance(value, (int, float)) and math.isfinite(float(value))
    ]
    maes = [
        float(value)
        for record in records
        for value in [_record_value(record, "mae")]
        if isinstance(value, (int, float)) and math.isfinite(float(value))
    ]
    mfes = [
        float(value)
        for record in records
        for value in [_record_value(record, "mfe")]
        if isinstance(value, (int, float)) and math.isfinite(float(value))
    ]
    holding_days = [
        float(value)
        for record in records
        for value in [_record_value(record, "holding_trading_days")]
        if isinstance(value, (int, float)) and math.isfinite(float(value))
    ]
    return_stats = _mean_median(returns)
    mae_stats = _mean_median(maes)
    mfe_stats = _mean_median(mfes)
    holding_stats = _mean_median(holding_days)
    return {
        "trade_count": len(records),
        "realized_count": len(realized),
        "open_count": len(open_at_cutoff),
        "mean_terminal_return": return_stats["mean"],
        "median_terminal_return": return_stats["median"],
        "win_rate": len([value for value in realized_returns if value > 0]) / len(realized_returns)
        if realized_returns else None,
        "mean_mae": mae_stats["mean"],
        "median_mae": mae_stats["median"],
        "deepest_mae": min(maes) if maes else None,
        "mean_mfe": mfe_stats["mean"],
        "median_mfe": mfe_stats["median"],
        "mean_holding_period": holding_stats["mean"],
        "median_holding_period": holding_stats["median"],
        "negative_return_count": len([value for value in returns if value < 0]),
        "return_le_minus_20_count": len([value for value in returns if value <= -20.0]),
        "return_le_minus_30_count": len([value for value in returns if value <= -30.0]),
    }


def _signal_task_value(signal: Any, field: str, default: Any = None) -> Any:
    task = _record_value(signal, "task")
    return _record_value(task, field, default)


def _matched_rows(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pair in result.get("pairs", ()):
        signal = pair.get("signal")
        base = pair.get("base")
        julia = pair.get("julia")
        base_identity = _identity_key_from_record(base) if base is not None else None
        julia_identity = _identity_key_from_record(julia) if julia is not None else None
        signal_identity = (
            str(_signal_task_value(signal, "ticker", "")),
            str(_signal_task_value(signal, "isu_cd", "") or ""),
            str(_signal_task_value(signal, "market", "")),
        )
        base_entry_open = _safe_scalar(_record_value(base, "entry_open")) if base is not None else None
        julia_entry_open = _safe_scalar(_record_value(julia, "entry_open")) if julia is not None else None
        entry_open = base_entry_open if base_entry_open is not None else julia_entry_open
        base_signal_date = _record_value(base, "entry_signal_date") if base is not None else None
        julia_signal_date = _record_value(julia, "entry_signal_date") if julia is not None else None
        base_execution_date = _record_value(base, "entry_execution_date") if base is not None else None
        julia_execution_date = _record_value(julia, "entry_execution_date") if julia is not None else None
        base_mcap = _record_value(base, "entry_market_cap") if base is not None else None
        julia_mcap = _record_value(julia, "entry_market_cap") if julia is not None else None
        base_avg_value = _record_value(base, "entry_avg_trading_value_20d") if base is not None else None
        julia_avg_value = _record_value(julia, "entry_avg_trading_value_20d") if julia is not None else None
        rows.append({
            "ticker": signal_identity[0],
            "isu_cd": signal_identity[1],
            "market": signal_identity[2],
            "signal_date": _safe_scalar(_record_value(signal, "signal_date")),
            "entry_execution_date": _safe_scalar(_record_value(signal, "execution_date")),
            "entry_open": entry_open,
            "entry_identity_equal": base_identity == julia_identity == signal_identity,
            "entry_signal_date_equal": (
                base_signal_date is not None and base_signal_date == julia_signal_date
                and base_signal_date == _record_value(signal, "signal_date")
            ),
            "entry_execution_date_equal": (
                base_execution_date is not None and base_execution_date == julia_execution_date
                and base_execution_date == _record_value(signal, "execution_date")
            ),
            "entry_open_equal": (
                base_entry_open is not None and julia_entry_open is not None
                and math.isclose(float(base_entry_open), float(julia_entry_open), rel_tol=0.0, abs_tol=1e-12)
            ),
            "investability_equal": (
                base_mcap is not None and julia_mcap is not None
                and float(base_mcap) == float(julia_mcap)
                and base_avg_value is not None and julia_avg_value is not None
                and float(base_avg_value) == float(julia_avg_value)
            ),
            "v2_exit_type": _safe_scalar(_record_value(base, "exit_type")),
            "v2_exit_signal_date": _safe_scalar(_record_value(base, "exit_signal_date")),
            "v2_exit_execution_date": _safe_scalar(_record_value(base, "exit_execution_date")),
            "v2_exit_price": _safe_scalar(_record_value(base, "exit_price")),
            "julia_exit_type": _safe_scalar(_record_value(julia, "exit_type")),
            "julia_exit_signal_date": _safe_scalar(_record_value(julia, "exit_signal_date")),
            "julia_exit_execution_date": _safe_scalar(_record_value(julia, "exit_execution_date")),
            "julia_exit_price": _safe_scalar(_record_value(julia, "exit_price")),
            "v2_terminal_return": _safe_scalar(_record_value(base, "terminal_return")),
            "julia_terminal_return": _safe_scalar(_record_value(julia, "terminal_return")),
            "return_delta": (
                float(_record_value(julia, "terminal_return")) - float(_record_value(base, "terminal_return"))
                if base is not None and julia is not None
                and _record_value(base, "terminal_return") is not None
                and _record_value(julia, "terminal_return") is not None
                else None
            ),
            "v2_mae": _safe_scalar(_record_value(base, "mae")),
            "julia_mae": _safe_scalar(_record_value(julia, "mae")),
            "v2_mfe": _safe_scalar(_record_value(base, "mfe")),
            "julia_mfe": _safe_scalar(_record_value(julia, "mfe")),
            "v2_holding_period": _safe_scalar(_record_value(base, "holding_trading_days")),
            "julia_holding_period": _safe_scalar(_record_value(julia, "holding_trading_days")),
            "v2_open_at_cutoff": _record_value(base, "trade_status") == "OPEN_AT_CUTOFF",
            "julia_open_at_cutoff": _record_value(julia, "trade_status") == "OPEN_AT_CUTOFF",
            "pair_status": str(pair.get("status", "UNRESOLVED")),
        })
    return [{key: _safe_scalar(row.get(key)) for key in MATCHED_ENTRY_COLUMNS} for row in rows]


def _sequential_rows(result: Mapping[str, Sequence[Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for strategy_id, records in result.items():
        for record in records:
            rows.append({
                "strategy_id": str(_record_value(record, "strategy_id", strategy_id) or strategy_id),
                "ticker": _safe_scalar(_record_value(record, "ticker")),
                "isu_cd": _safe_scalar(_record_value(record, "isu_cd")),
                "market": _safe_scalar(_record_value(record, "market")),
                "trade_id": _safe_scalar(_record_value(record, "trade_id")),
                "trade_sequence": _safe_scalar(_record_value(record, "trade_sequence")),
                "entry_signal_date": _safe_scalar(_record_value(record, "entry_signal_date")),
                "entry_execution_date": _safe_scalar(_record_value(record, "entry_execution_date")),
                "entry_open": _safe_scalar(_record_value(record, "entry_open")),
                "entry_market_cap": _safe_scalar(_record_value(record, "entry_market_cap")),
                "entry_avg_trading_value_20d": _safe_scalar(_record_value(record, "entry_avg_trading_value_20d")),
                "exit_signal_date": _safe_scalar(_record_value(record, "exit_signal_date")),
                "exit_execution_date": _safe_scalar(_record_value(record, "exit_execution_date")),
                "exit_type": _safe_scalar(_record_value(record, "exit_type")),
                "exit_price": _safe_scalar(_record_value(record, "exit_price")),
                "terminal_return": _safe_scalar(_record_value(record, "terminal_return")),
                "mae": _safe_scalar(_record_value(record, "mae")),
                "mfe": _safe_scalar(_record_value(record, "mfe")),
                "holding_trading_days": _safe_scalar(_record_value(record, "holding_trading_days")),
                "holding_weeks": _safe_scalar(_record_value(record, "holding_weeks")),
                "trade_status": _safe_scalar(_record_value(record, "trade_status")),
                "cutoff_date": _safe_scalar(_record_value(record, "cutoff_date")),
                "cutoff_valuation_price": _safe_scalar(_record_value(record, "cutoff_valuation_price")),
                "mark_to_cutoff_return": _safe_scalar(_record_value(record, "mark_to_cutoff_return")),
                "open_at_cutoff": _record_value(record, "trade_status") == "OPEN_AT_CUTOFF",
                "identity_effective_from": _safe_scalar(_record_value(record, "identity_effective_from")),
                "identity_effective_to": _safe_scalar(_record_value(record, "identity_effective_to")),
                "loss_guard_triggered": bool(_record_value(record, "loss_guard_triggered", False)),
            })
    return [{key: row.get(key) for key in SEQUENTIAL_COLUMNS} for row in rows]


def _portfolio_rows(result: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    daily: list[dict[str, Any]] = []
    for strategy_id, strategy_result in result.get("strategies", {}).items():
        for event in strategy_result.get("event_ledger", ()):
            events.append({key: _safe_scalar(event.get(key)) for key in PORTFOLIO_EVENT_COLUMNS})
        for row in strategy_result.get("daily_equity", ()):
            daily.append({key: _safe_scalar(row.get(key)) for key in PORTFOLIO_EQUITY_COLUMNS})
    return events, daily


def _benchmark_summary(root: Path) -> dict[str, Any]:
    frame = IndexStore(root / "data/market/index/v01").load_family(
        MARKET_INDEX_FAMILY,
        start=START_DATE.strftime("%Y-%m-%d"),
        end=FINAL_VALUATION_DATE.strftime("%Y-%m-%d"),
        index_codes=list(BENCHMARK_CODES.values()),
    )
    result: dict[str, Any] = {}
    for label, code in BENCHMARK_CODES.items():
        subset = frame[frame["index_code"].astype(str) == code].sort_values("date")
        closes = pd.to_numeric(subset["close"], errors="coerce") if not subset.empty else pd.Series(dtype="float64")
        if subset.empty or closes.empty or closes.isna().any() or float(closes.iloc[0]) <= 0:
            result[label] = {"index_code": code, "status": "UNRESOLVED"}
            continue
        start_close = float(closes.iloc[0])
        end_close = float(closes.iloc[-1])
        result[label] = {
            "index_code": code,
            "status": "PASS",
            "period": {
                "requested_start": START_DATE.strftime("%Y-%m-%d"),
                "requested_end": FINAL_VALUATION_DATE.strftime("%Y-%m-%d"),
                "first_available_date": str(subset.iloc[0]["date"]),
                "last_available_date": str(subset.iloc[-1]["date"]),
            },
            "start_close": start_close,
            "end_close": end_close,
            "total_return_pct": (end_close / start_close - 1.0) * 100.0,
        }
    return result


def _git_head(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> None:
    frame = pd.DataFrame(
        [{column: _safe_scalar(row.get(column)) for column in columns} for row in rows],
        columns=list(columns),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8", lineterminator="\n", na_rep="")


def _fmt(value: Any, *, percent: bool = False, digits: int = 2) -> str:
    if value is None or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return "N/A"
    number = float(value) * 100.0 if percent else float(value)
    return f"{number:.{digits}f}{'%' if percent else ''}"


def _failure_rows(
    matched_result: Mapping[str, Any],
    matched_rows: Sequence[Mapping[str, Any]],
    sequential_rows: Sequence[Mapping[str, Any]],
    portfolio_result: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def add(case_type: str, row: Mapping[str, Any], *, strategy_id: Any = None, reason: Any = None) -> None:
        rows.append({
            "case_type": case_type,
            "strategy_id": strategy_id if strategy_id is not None else row.get("strategy_id"),
            "ticker": row.get("ticker"),
            "isu_cd": row.get("isu_cd"),
            "market": row.get("market"),
            "trade_id": row.get("trade_id"),
            "signal_date": row.get("signal_date", row.get("entry_signal_date")),
            "entry_execution_date": row.get("entry_execution_date"),
            "exit_execution_date": row.get("exit_execution_date"),
            "terminal_return": row.get("terminal_return"),
            "mae": row.get("mae"),
            "mfe": row.get("mfe"),
            "loss_guard_triggered": row.get("loss_guard_triggered"),
            "unresolved_reason": reason if reason is not None else row.get("unresolved_reason"),
            "case_status": row.get("trade_status", row.get("pair_status", "OBSERVED")),
        })

    for row in sequential_rows:
        if row.get("strategy_id") != JULIA_STRATEGY_ID:
            continue
        terminal_return = row.get("terminal_return")
        mae = row.get("mae")
        if isinstance(terminal_return, (int, float)) and terminal_return <= -30.0:
            add("JULIA_TERMINAL_RETURN_LE_MINUS_30_PCT", row)
        if isinstance(terminal_return, (int, float)) and terminal_return <= -20.0:
            add("JULIA_TERMINAL_RETURN_LE_MINUS_20_PCT", row)
        if isinstance(mae, (int, float)) and mae < 0.0:
            add("JULIA_NEGATIVE_MAE", row)

    for pair, row in zip(matched_result.get("pairs", ()), matched_rows):
        if row.get("pair_status") != "PASS":
            add("UNRESOLVED_MATCHED_ENTRY", row, strategy_id="MATCHED_ENTRY", reason="PAIR_UNRESOLVED")
        base = pair.get("base")
        julia = pair.get("julia")
        if base is not None and bool(_record_value(base, "loss_guard_triggered", False)):
            continued = _record_value(julia, "terminal_return") if julia is not None else None
            if continued is not None:
                add(
                    "MATCHED_V2_GUARD_JULIA_CONTINUED",
                    {
                        "ticker": row.get("ticker"),
                        "isu_cd": row.get("isu_cd"),
                        "market": row.get("market"),
                        "signal_date": row.get("signal_date"),
                        "entry_execution_date": row.get("entry_execution_date"),
                        "terminal_return": continued,
                        "mae": row.get("julia_mae"),
                        "mfe": row.get("julia_mfe"),
                        "loss_guard_triggered": True,
                        "pair_status": row.get("pair_status"),
                    },
                    strategy_id=JULIA_STRATEGY_ID,
                    reason="V2_LOSS_GUARD_TRIGGERED",
                )

    for strategy_id, strategy_result in portfolio_result.get("strategies", {}).items():
        for event in strategy_result.get("event_ledger", ()):
            if event.get("event_status") == "UNRESOLVED":
                add(
                    "UNRESOLVED_PORTFOLIO_EVENT",
                    event,
                    strategy_id=strategy_id,
                    reason=event.get("unresolved_reason"),
                )
    return [{column: _safe_scalar(row.get(column)) for column in FAILURE_COLUMNS} for row in rows]


def _validation_report(
    summary: Mapping[str, Any],
    matched_rows: Sequence[Mapping[str, Any]],
    sequential_rows: Sequence[Mapping[str, Any]],
) -> str:
    matched = summary["matched_entry"]
    sequential = summary["sequential"]
    portfolio = summary["realistic_200m_portfolio"]
    status = summary["status"]
    lines = [
        "# V2 ↔ Julia 공식 백테스트 V01 결과",
        "",
        f"- 실행 상태: `{status}`",
        f"- Frozen execution contract SHA-256: `{summary['execution_contract_sha256']}`",
        f"- Source HEAD: `{summary['source_head']}`",
        f"- 평가 기간: `{START_DATE:%Y-%m-%d} ~ {FINAL_VALUATION_DATE:%Y-%m-%d}`",
        f"- Population/PIT: `{summary['population_count']:,}` / `{summary['pit_interval_count']:,}`",
        "",
        "## Matched-entry",
        "",
        f"- pair count: `{matched['pair_count']:,}`; unresolved: `{matched['unresolved_count']:,}`",
        f"- V2 평균/중앙 terminal return: `{_fmt(matched['V2']['mean_terminal_return'])}%` / `{_fmt(matched['V2']['median_terminal_return'])}%`",
        f"- Julia 평균/중앙 terminal return: `{_fmt(matched['Julia']['mean_terminal_return'])}%` / `{_fmt(matched['Julia']['median_terminal_return'])}%`",
        f"- 평균/중앙 return delta (Julia - V2): `{_fmt(matched['mean_return_delta'])}%` / `{_fmt(matched['median_return_delta'])}%`",
        "",
        "## Sequential",
        "",
        "| 전략 | 거래 수 | 실현 | cutoff open | 평균 return | 평균 MAE | 평균 보유일 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for strategy_id in (BASE_STRATEGY_ID, JULIA_STRATEGY_ID):
        item = sequential[strategy_id]
        lines.append(
            f"| {strategy_id} | {item['trade_count']:,} | {item['realized_count']:,} | "
            f"{item['open_count']:,} | {_fmt(item['mean_terminal_return'])}% | "
            f"{_fmt(item['mean_mae'])}% | {_fmt(item['mean_holding_period'])} |"
        )
    lines.extend([
        "",
        "## Realistic 200M Portfolio",
        "",
        "| 전략 | final equity | total return | CAGR | MDD | exposure | turnover | unresolved |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for strategy_id in (BASE_STRATEGY_ID, JULIA_STRATEGY_ID):
        item = portfolio[strategy_id]
        lines.append(
            f"| {strategy_id} | {_fmt(item['final_equity'])} | {_fmt(item['total_return'], percent=True)} | "
            f"{_fmt(item['cagr'], percent=True)} | {_fmt(item['mdd'], percent=True)} | "
            f"{_fmt(item['exposure'], percent=True)} | {_fmt(item['turnover'])} | {item['unresolved_count']:,} |"
        )
    lines.extend([
        "",
        "## Benchmark",
        "",
        f"- KOSPI `1001`: `{_fmt(summary['benchmarks']['KOSPI'].get('total_return_pct'))}%`",
        f"- KOSDAQ `2001`: `{_fmt(summary['benchmarks']['KOSDAQ'].get('total_return_pct'))}%`",
        "",
        "## 확인 및 주의사항",
        "",
        f"- Matched-entry rows: `{len(matched_rows):,}`; Sequential rows: `{len(sequential_rows):,}`.",
        f"- 전체 unresolved: `{summary['unresolved_count']:,}`.",
        "- V2와 Julia의 차이는 frozen contract의 Pre-PROGRESSED Loss Guard ON/OFF로 제한했다.",
        "- 이번 작업에서는 Julia 승인, 전략 선정, parameter tuning, robustness 추가 실험을 수행하지 않았다.",
        "",
        "## 다음 단계",
        "",
        "`Strategy Robustness Comparison`.",
        "",
    ])
    return "\n".join(lines)


def persist_official_results(
    root: Path,
    contract: Mapping[str, Any],
    matched_result: Mapping[str, Any],
    sequential_result: Mapping[str, Sequence[Any]],
    portfolio_result: Mapping[str, Any],
    *,
    source_head: str,
    benchmark_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist one completed frozen run as scalar, auditable artifacts."""
    root = Path(root).resolve()
    output_dir = root / OUTPUT_DIR_REL
    present = _result_artifacts_present(root)
    if present:
        raise OfficialValidationError(f"OFFICIAL_RESULT_ARTIFACT_PRESENT:{present}")
    matched = _matched_rows(matched_result)
    sequential = _sequential_rows(sequential_result)
    events, daily = _portfolio_rows(portfolio_result)
    failures = _failure_rows(matched_result, matched, sequential, portfolio_result)

    matched_pairs = list(matched_result.get("pairs", ()))
    v2_records = [pair["base"] for pair in matched_pairs if pair.get("base") is not None]
    julia_records = [pair["julia"] for pair in matched_pairs if pair.get("julia") is not None]
    matched_delta = [
        float(row["return_delta"])
        for row in matched
        if isinstance(row.get("return_delta"), (int, float)) and math.isfinite(float(row["return_delta"]))
    ]
    v2_higher = sum(
        1 for row in matched
        if isinstance(row.get("v2_terminal_return"), (int, float))
        and isinstance(row.get("julia_terminal_return"), (int, float))
        and row["v2_terminal_return"] > row["julia_terminal_return"]
    )
    julia_higher = sum(
        1 for row in matched
        if isinstance(row.get("v2_terminal_return"), (int, float))
        and isinstance(row.get("julia_terminal_return"), (int, float))
        and row["julia_terminal_return"] > row["v2_terminal_return"]
    )
    compared_pairs = v2_higher + julia_higher + sum(
        1 for row in matched
        if isinstance(row.get("v2_terminal_return"), (int, float))
        and isinstance(row.get("julia_terminal_return"), (int, float))
        and row["v2_terminal_return"] == row["julia_terminal_return"]
    )
    matched_summary = {
        "pair_count": len(matched_pairs),
        "unresolved_count": sum(1 for row in matched if row.get("pair_status") != "PASS"),
        "V2": _trade_summary(v2_records),
        "Julia": _trade_summary(julia_records),
        "v2_higher_return_count": v2_higher,
        "julia_higher_return_count": julia_higher,
        "tie_count": compared_pairs - v2_higher - julia_higher,
        "compared_pair_count": compared_pairs,
        "mean_return_delta": _mean_median(matched_delta)["mean"],
        "median_return_delta": _mean_median(matched_delta)["median"],
    }

    sequential_summary: dict[str, Any] = {}
    for strategy_id in (BASE_STRATEGY_ID, JULIA_STRATEGY_ID):
        records = list(sequential_result.get(strategy_id, ()))
        sequential_summary[strategy_id] = _trade_summary(records)
        sequential_summary[strategy_id]["unresolved_count"] = sum(
            1 for record in records
            if _record_value(record, "trade_status") not in {"REALIZED", "OPEN_AT_CUTOFF"}
        )

    portfolio_summary: dict[str, Any] = {}
    portfolio_unresolved = 0
    cash_conservation_failures: list[str] = []
    for strategy_id in (BASE_STRATEGY_ID, JULIA_STRATEGY_ID):
        strategy_result = portfolio_result.get("strategies", {}).get(strategy_id, {})
        metrics = dict(strategy_result.get("metrics", {}))
        final_rows = [row for row in strategy_result.get("daily_equity", ()) if row.get("date") == FINAL_VALUATION_DATE.strftime("%Y-%m-%d")]
        final_equity = final_rows[-1].get("equity") if final_rows else None
        metrics["final_equity"] = final_equity
        metrics["average_holding_period_days"] = metrics.get("holding_period_days")
        portfolio_summary[strategy_id] = metrics
        portfolio_unresolved += int(metrics.get("unresolved_count") or 0)
        if metrics.get("cash_conservation_pass") is not True:
            cash_conservation_failures.append(strategy_id)

    sequential_unresolved = sum(int(item.get("unresolved_count") or 0) for item in sequential_summary.values())
    matched_unresolved = int(matched_summary["unresolved_count"])
    unresolved_count = matched_unresolved + sequential_unresolved + portfolio_unresolved
    benchmark = dict(benchmark_summary or {})
    benchmark_unresolved = sum(1 for item in benchmark.values() if item.get("status") != "PASS")
    unresolved_count += benchmark_unresolved
    integrity_issues = [
        f"CASH_CONSERVATION_FAIL:{strategy_id}" for strategy_id in cash_conservation_failures
    ]
    if len(matched) != matched_summary["pair_count"]:
        integrity_issues.append("MATCHED_ROW_COUNT_MISMATCH")
    if len(sequential) != sum(item["trade_count"] for item in sequential_summary.values()):
        integrity_issues.append("SEQUENTIAL_ROW_COUNT_MISMATCH")
    status = "INCOMPLETE_REQUIRES_REVIEW" if unresolved_count or integrity_issues else "COMPLETE"
    summary: dict[str, Any] = {
        "schema": "v2_julia_official_aggregate_summary_v01",
        "status": status,
        "execution_contract_sha256": contract["contract_sha256"],
        "source_head": source_head,
        "period": {
            "evaluation_start": START_DATE.strftime("%Y-%m-%d"),
            "signal_cutoff": SIGNAL_CUTOFF.strftime("%Y-%m-%d"),
            "evaluation_end": EVALUATION_END.strftime("%Y-%m-%d"),
            "execution_support_end": EXECUTION_SUPPORT_END.strftime("%Y-%m-%d"),
            "final_valuation": f"{FINAL_VALUATION_DATE:%Y-%m-%d} CLOSE",
        },
        "population_count": int(contract["population_pit_authority"]["population_count"]),
        "pit_interval_count": int(contract["population_pit_authority"]["pit_interval_count"]),
        "unresolved_count": unresolved_count,
        "unresolved_counts": {
            "matched_entry": matched_unresolved,
            "sequential": sequential_unresolved,
            "realistic_200m_portfolio": portfolio_unresolved,
            "benchmark": benchmark_unresolved,
        },
        "integrity_issues": integrity_issues,
        "matched_entry": matched_summary,
        "sequential": sequential_summary,
        "realistic_200m_portfolio": portfolio_summary,
        "benchmarks": benchmark,
        "counts": {
            "matched_entry_rows": len(matched),
            "sequential_rows": len(sequential),
            "failure_and_big_loss_rows": len(failures),
            "portfolio_event_rows": len(events),
            "portfolio_daily_equity_rows": len(daily),
        },
        "artifacts": [*OFFICIAL_RESULT_FILES, *SUPPORT_RESULT_FILES],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "matched_entry_comparison.csv", matched, MATCHED_ENTRY_COLUMNS)
    _write_csv(output_dir / "sequential_comparison.csv", sequential, SEQUENTIAL_COLUMNS)
    _write_csv(output_dir / "failure_and_big_loss_cases.csv", failures, FAILURE_COLUMNS)
    _write_csv(output_dir / "portfolio_event_ledger.csv", events, PORTFOLIO_EVENT_COLUMNS)
    _write_csv(output_dir / "portfolio_daily_equity.csv", daily, PORTFOLIO_EQUITY_COLUMNS)
    (output_dir / "validation_report.md").write_text(
        _validation_report(summary, matched, sequential), encoding="utf-8"
    )
    _write_json(output_dir / "aggregate_summary.json", summary)
    return {
        "status": status,
        "contract_sha256": contract["contract_sha256"],
        "source_head": source_head,
        "unresolved_count": unresolved_count,
        "integrity_issues": integrity_issues,
        "counts": summary["counts"],
        "result_artifacts": list(summary["artifacts"]),
    }


def run_official(root: Path = ROOT) -> dict[str, Any]:
    """Fail closed until the bounded performance gate authorizes Full Run."""
    root = Path(root).resolve()
    with network_guard():
        preflight_result = preflight(root, write_contract=False)
        if preflight_result.get("status") != "READY":
            raise OfficialValidationError("OFFICIAL_PREFLIGHT_NOT_READY")
        raise OfficialValidationError("OFFICIAL_FULL_RUN_BLOCKED_BY_PERFORMANCE_GATE")


def _resource_snapshot() -> dict[str, float]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    rss_divisor = 1024.0 * 1024.0 if sys.platform == "darwin" else 1024.0
    return {
        "user_cpu_seconds": float(usage.ru_utime),
        "system_cpu_seconds": float(usage.ru_stime),
        "max_rss_mib": float(usage.ru_maxrss) / rss_divisor,
    }


def _sample_unresolved_counts(
    matched_result: Mapping[str, Any],
    sequential_result: Mapping[str, Sequence[Any]],
    portfolio_result: Mapping[str, Any],
) -> dict[str, int]:
    matched = sum(1 for pair in matched_result.get("pairs", ()) if pair.get("status") != "PASS")
    sequential = sum(
        1
        for records in sequential_result.values()
        for record in records
        if _record_value(record, "trade_status") not in {"REALIZED", "OPEN_AT_CUTOFF"}
    )
    portfolio = sum(
        int(strategy_result.get("metrics", {}).get("unresolved_count") or 0)
        for strategy_result in portfolio_result.get("strategies", {}).values()
    )
    return {
        "matched_entry": matched,
        "sequential": sequential,
        "realistic_200m_portfolio": portfolio,
        "total": matched + sequential + portfolio,
    }


def _sample_parity_payload(
    matched_result: Mapping[str, Any],
    sequential_result: Mapping[str, Sequence[Any]],
    portfolio_result: Mapping[str, Any],
) -> dict[str, Any]:
    matched_pairs = list(matched_result.get("pairs", ()))
    return {
        "matched_signal_keys": [pair.get("entry_key") for pair in matched_pairs],
        "matched_v2_trades": [pair.get("base") for pair in matched_pairs],
        "matched_julia_trades": [pair.get("julia") for pair in matched_pairs],
        "sequential_v2_trades": list(sequential_result.get(BASE_STRATEGY_ID, ())),
        "sequential_julia_trades": list(sequential_result.get(JULIA_STRATEGY_ID, ())),
        "unresolved_counts": _sample_unresolved_counts(
            matched_result,
            sequential_result,
            portfolio_result,
        ),
        "portfolio_output": portfolio_result,
    }


def run_performance_sample(
    root: Path = ROOT,
    *,
    sample_size: int,
    workers: int = 1,
    reuse_lifecycle_caches: bool = True,
    _return_parity_payload: bool = False,
) -> dict[str, Any] | tuple[dict[str, Any], dict[str, Any]]:
    """Measure one bounded sample without persisting official result artifacts."""
    root = Path(root).resolve()
    if workers not in {1, 2, 4, 6}:
        raise OfficialValidationError(f"PERFORMANCE_WORKER_COUNT_UNSUPPORTED:{workers}")
    if workers > 1 and not reuse_lifecycle_caches:
        raise OfficialValidationError("PARALLEL_SAMPLE_REQUIRES_LIFECYCLE_CACHE_REUSE")
    with network_guard():
        preflight_started = time.perf_counter()
        preflight_result = preflight(root, write_contract=False)
        preflight_seconds = time.perf_counter() - preflight_started
        if preflight_result.get("status") != "READY":
            raise OfficialValidationError("PERFORMANCE_SAMPLE_PREFLIGHT_NOT_READY")

        contract_path = root / CONTRACT_REL
        contract_before = contract_path.read_bytes()
        contract = _read_json(contract_path)
        usage_before = _resource_snapshot()
        total_started = time.perf_counter()

        runner_started = time.perf_counter()
        official = OfficialValidationRunner(
            root,
            contract,
            identity_limit=sample_size,
            reuse_lifecycle_caches=reuse_lifecycle_caches,
        )
        runner_initialization_seconds = time.perf_counter() - runner_started
        tasks = official.identity_tasks()
        task_markets: dict[str, int] = {}
        for task in tasks:
            task_markets[task.market] = task_markets.get(task.market, 0) + 1

        parallel_result: dict[str, Any] | None = None
        if workers == 1:
            matched_started = time.perf_counter()
            matched_result = official.run_matched_entry()
            matched_seconds = time.perf_counter() - matched_started

            sequential_started = time.perf_counter()
            sequential_result = official.run_sequential()
            sequential_seconds = time.perf_counter() - sequential_started
        else:
            parallel_result = run_parallel_lifecycle_sample(
                official,
                tasks,
                workers=workers,
            )
            matched_result = parallel_result["matched_result"]
            sequential_result = parallel_result["sequential_result"]
            parallel_phase_wall = parallel_result["timing"]["phase_wall_seconds_estimate"]
            matched_seconds = float(parallel_phase_wall["matched_entry_seconds"])
            sequential_seconds = float(parallel_phase_wall["sequential_seconds"])

        portfolio_started = time.perf_counter()
        portfolio_result = official.run_realistic_portfolio(sequential_result)
        portfolio_seconds = time.perf_counter() - portfolio_started

        if contract_path.read_bytes() != contract_before:
            raise OfficialValidationError("FROZEN_EXECUTION_CONTRACT_CHANGED_DURING_SAMPLE")
        usage_after = _resource_snapshot()
        total_seconds = time.perf_counter() - total_started

    matched_pairs = list(matched_result.get("pairs", ()))
    sequential_trade_counts = {
        strategy_id: len(records)
        for strategy_id, records in sequential_result.items()
    }
    portfolio_trade_counts = {
        strategy_id: int(strategy_result.get("metrics", {}).get("trade_count") or 0)
        for strategy_id, strategy_result in portfolio_result.get("strategies", {}).items()
    }
    unresolved_counts = _sample_unresolved_counts(
        matched_result,
        sequential_result,
        portfolio_result,
    )
    diagnostic_counts = (
        official.diagnostic_snapshot()
        if hasattr(official, "diagnostic_snapshot")
        else dict(official.diagnostic_counts)
    )
    if parallel_result is not None:
        diagnostic_counts.update(parallel_result["diagnostic_counts"])
        parent_user_cpu = usage_after["user_cpu_seconds"] - usage_before["user_cpu_seconds"]
        parent_system_cpu = usage_after["system_cpu_seconds"] - usage_before["system_cpu_seconds"]
        resource_payload = {
            "process_model": "fork_process_pool",
            "workers": workers,
            "user_cpu_seconds": parent_user_cpu + parallel_result["resource"]["user_cpu_seconds"],
            "system_cpu_seconds": parent_system_cpu + parallel_result["resource"]["system_cpu_seconds"],
            "max_rss_mib": max(
                usage_after["max_rss_mib"],
                parallel_result["resource"]["max_rss_mib"],
            ),
        }
    else:
        resource_payload = {
            "process_model": "single_process",
            "workers": 1,
            "user_cpu_seconds": usage_after["user_cpu_seconds"] - usage_before["user_cpu_seconds"],
            "system_cpu_seconds": usage_after["system_cpu_seconds"] - usage_before["system_cpu_seconds"],
            "max_rss_mib": usage_after["max_rss_mib"],
        }
    result = {
        "schema": "v2_julia_performance_sample_v01",
        "status": "COMPLETE",
        "sample_size_requested": sample_size,
        "identity_count": len(tasks),
        "market_counts": dict(sorted(task_markets.items())),
        "population_identity_lifecycle_count": len(_identity_tasks(official.authority)),
        "preflight_seconds": preflight_seconds,
        "runner_initialization_seconds": runner_initialization_seconds,
        "stages": {
            "matched_entry_seconds": matched_seconds,
            "matched_discovery_seconds": official.diagnostic_seconds["matched_discovery_seconds"],
            "matched_strategy_seconds": official.diagnostic_seconds["matched_strategy_seconds"],
            "sequential_seconds": sequential_seconds,
            "realistic_200m_portfolio_seconds": portfolio_seconds,
            "total_seconds": total_seconds,
        },
        "counts": {
            **diagnostic_counts,
            "candidate_matched_signal_count": int(matched_result.get("candidate_signal_count", 0)),
            "matched_pair_count": len(matched_pairs),
            "sequential_trade_counts": sequential_trade_counts,
            "sequential_trade_count_total": sum(sequential_trade_counts.values()),
            "portfolio_trade_counts": portfolio_trade_counts,
            "portfolio_trade_count_total": sum(portfolio_trade_counts.values()),
            "generated_trade_count": {
                "sequential_records_total": sum(sequential_trade_counts.values()),
                "portfolio_executed_positions_total": sum(portfolio_trade_counts.values()),
            },
        },
        "unresolved_counts": unresolved_counts,
        "resource": resource_payload,
        "cache_observation": {
            "lifecycle_cache_reuse_enabled": reuse_lifecycle_caches,
            "fast_snapshot_cache_used": reuse_lifecycle_caches,
            "monthly_snapshot_cache_used": reuse_lifecycle_caches,
            "precomputed_ticker_context_used": True,
            "runner_path": (
                "lifecycle-scoped context/raw panel/FastSnapshotCache/MonthlySnapshotCache"
                if workers == 1
                else "bounded fork ProcessPoolExecutor lifecycle bundles with the same caches"
            ),
        },
        "parallel": None if parallel_result is None else parallel_result["timing"],
        "official_backtest_executed": False,
        "official_result_artifacts": _result_artifacts_present(root),
        "network_requests": 0,
        "execution_contract_sha256": contract["contract_sha256"],
    }
    if _return_parity_payload:
        return result, _sample_parity_payload(
            matched_result,
            sequential_result,
            portfolio_result,
        )
    return result


def run_performance_parity_sample(root: Path = ROOT, *, sample_size: int) -> dict[str, Any]:
    """Compare uncached and lifecycle-cache sample outputs for exact equality."""
    baseline, baseline_payload = run_performance_sample(
        root,
        sample_size=sample_size,
        reuse_lifecycle_caches=False,
        _return_parity_payload=True,
    )
    optimized, optimized_payload = run_performance_sample(
        root,
        sample_size=sample_size,
        reuse_lifecycle_caches=True,
        _return_parity_payload=True,
    )
    checks = {
        key: baseline_payload[key] == optimized_payload[key]
        for key in baseline_payload
    }
    return {
        "schema": "v2_julia_performance_parity_sample_v01",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "sample_size": sample_size,
        "checks": checks,
        "baseline": baseline,
        "optimized": optimized,
        "official_backtest_executed": False,
        "network_requests": 0,
    }


def run_parallel_performance_parity_sample(
    root: Path = ROOT,
    *,
    sample_size: int,
    workers: int,
) -> dict[str, Any]:
    """Compare the optimized workers=1 path with one bounded worker count."""
    baseline, baseline_payload = run_performance_sample(
        root,
        sample_size=sample_size,
        workers=1,
        reuse_lifecycle_caches=True,
        _return_parity_payload=True,
    )
    parallel, parallel_payload = run_performance_sample(
        root,
        sample_size=sample_size,
        workers=workers,
        reuse_lifecycle_caches=True,
        _return_parity_payload=True,
    )
    checks = {
        key: baseline_payload[key] == parallel_payload[key]
        for key in baseline_payload
    }
    return {
        "schema": "v2_julia_parallel_performance_parity_sample_v01",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "sample_size": sample_size,
        "workers": workers,
        "checks": checks,
        "workers_1": baseline,
        "workers_parallel": parallel,
        "official_backtest_executed": False,
        "network_requests": 0,
    }


@contextmanager
def network_guard() -> Iterator[None]:
    """Block accidental sockets during local preflight and focused tests."""
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def blocked_connect(self: socket.socket, address: Any) -> None:
        raise OfficialValidationError(f"NETWORK_REQUEST_BLOCKED:{address!r}")

    def blocked_connect_ex(self: socket.socket, address: Any) -> int:
        raise OfficialValidationError(f"NETWORK_REQUEST_BLOCKED:{address!r}")

    socket.socket.connect = blocked_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = blocked_connect_ex  # type: ignore[method-assign]
    try:
        yield
    finally:
        socket.socket.connect = original_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = original_connect_ex  # type: ignore[method-assign]


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true", help="validate the frozen contract only")
    parser.add_argument(
        "--run-official",
        action="store_true",
        help="run the one frozen official Matched-entry/Sequential/Portfolio validation",
    )
    parser.add_argument(
        "--run-performance-sample",
        action="store_true",
        help="run one bounded N-identity performance sample without official artifacts",
    )
    parser.add_argument(
        "--run-performance-parity-sample",
        action="store_true",
        help="compare uncached and lifecycle-cache sample outputs exactly",
    )
    parser.add_argument(
        "--run-parallel-performance-parity-sample",
        action="store_true",
        help="compare optimized workers=1 output with a bounded parallel worker count",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        help="identity count for --run-performance-sample",
    )
    parser.add_argument(
        "--workers",
        type=int,
        choices=(1, 2, 4, 6),
        default=1,
        help="bounded worker count for performance samples",
    )
    parser.add_argument(
        "--disable-lifecycle-reuse",
        action="store_true",
        help="performance-diagnostic baseline only; disable lifecycle-scoped cache reuse",
    )
    parser.add_argument(
        "--write-contract",
        action="store_true",
        help="development-only initial contract creation; refuses to overwrite an existing contract",
    )
    args = parser.parse_args()
    if args.run_official and (
        args.preflight_only or args.write_contract or args.run_performance_sample
        or args.run_performance_parity_sample or args.run_parallel_performance_parity_sample
    ):
        parser.error("--run-official cannot be combined with preflight, contract, or sample modes")
    sample_modes = (
        args.run_performance_sample,
        args.run_performance_parity_sample,
        args.run_parallel_performance_parity_sample,
    )
    if any(sample_modes) and (args.preflight_only or args.write_contract):
        parser.error("performance sample modes cannot be combined with --preflight-only or --write-contract")
    if sum(bool(mode) for mode in sample_modes) > 1:
        parser.error("choose only one performance sample mode")
    if args.sample_size is not None and not any(sample_modes):
        parser.error("--sample-size requires a performance sample mode")
    if args.disable_lifecycle_reuse and not args.run_performance_sample:
        parser.error("--disable-lifecycle-reuse requires --run-performance-sample")
    if any(sample_modes) and args.sample_size is None:
        parser.error("performance sample modes require --sample-size")
    if args.run_parallel_performance_parity_sample and args.workers == 1:
        parser.error("parallel parity requires --workers 2, 4, or 6")
    if args.run_official:
        result = run_official(ROOT)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.run_performance_sample:
        result = run_performance_sample(
            ROOT,
            sample_size=args.sample_size,
            workers=args.workers,
            reuse_lifecycle_caches=not args.disable_lifecycle_reuse,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.run_performance_parity_sample:
        result = run_performance_parity_sample(ROOT, sample_size=args.sample_size)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.run_parallel_performance_parity_sample:
        result = run_parallel_performance_parity_sample(
            ROOT,
            sample_size=args.sample_size,
            workers=args.workers,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if not args.preflight_only and not args.write_contract:
        print("Stage 5 preparation is preflight-only; validating the committed contract.")
    with network_guard():
        result = preflight(ROOT, write_contract=args.write_contract)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
