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

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import socket
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
    }
    for key, value in expected.items():
        if contract.get(key) != value:
            raise OfficialValidationError(f"EXECUTION_CONTRACT_{key.upper()}_MISMATCH")
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
    if authority_block["population_sha256"] != authority.population_sha256 or authority_block["pit_sha256"] != authority.pit_sha256:
        raise OfficialValidationError("EFFECTIVE_AUTHORITY_HASH_MISMATCH")
    for relative in (POPULATION_REL, PIT_REL, EFFECTIVE_MANIFEST_REL, AUTHORITY_CUTOVER_MANIFEST_REL, SOURCE_ELIGIBILITY_REL, STAGE4_PLAN_REL, COMMON_CONDITIONS_REL, SCORE_CONTRACT_REL, STAGE_CONTRACT_REL, INDEX_PARQUET_REL, INDEX_META_REL):
        if not (root / relative).exists():
            raise OfficialValidationError(f"REQUIRED_AUTHORITY_MISSING:{relative}")
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


def preflight(root: Path = ROOT, *, write_contract: bool = True) -> dict[str, Any]:
    """Validate all Stage 5 inputs without evaluating any ticker."""
    root = Path(root).resolve()
    contract = build_execution_contract(root)
    contract_path = root / CONTRACT_REL
    if write_contract:
        _write_json(contract_path, contract)
    validation = validate_execution_contract(contract, root)
    authority = load_effective_authority(root / EFFECTIVE_AUTHORITY_REL)
    identity_intervals = _identity_intervals(authority)
    identity_tasks = _identity_tasks(authority)
    adjusted_store = root / "data/market/adjusted/stocks"
    raw_store = root / "data/market/raw/krx_stocks/v01"
    if not adjusted_store.is_dir() or not raw_store.is_dir():
        raise OfficialValidationError("REPOSITORY_V2_STORE_PATH_MISSING")
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
        "loader_count": 0,
        "network_requests": 0,
    }


class OfficialValidationRunner:
    """Run-scoped official inputs for the next explicit backtest task."""

    def __init__(self, root: Path = ROOT, contract: Mapping[str, Any] | None = None) -> None:
        self.root = Path(root).resolve()
        self.contract = dict(contract or _read_json(self.root / CONTRACT_REL))
        validate_execution_contract(self.contract, self.root)
        self.authority = load_effective_authority(self.root / EFFECTIVE_AUTHORITY_REL)
        self.intervals = _identity_intervals(self.authority)
        self.repository = build_repository_v2(self.root, end=EXECUTION_SUPPORT_END)
        self.loader = RepositoryV2DailyLoader(self.repository, end=EXECUTION_SUPPORT_END)
        self.score_contract = _read_json(self.root / SCORE_CONTRACT_REL)
        self.stage_contract = _read_json(self.root / STAGE_CONTRACT_REL)
        self._daily_cache: dict[str, pd.DataFrame] = {}
        self._ancillary_cache: dict[str, pd.DataFrame] = {}

    def identity_tasks(self) -> tuple[IdentityTask, ...]:
        return _identity_tasks(self.authority)

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
        _, ancillary = self.load_identity_inputs(task)
        return build_identity_raw_panel(ancillary, task)

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
        daily, _ = self.load_identity_inputs(task)
        daily = clip_to_identity_lifecycle(daily, task.lifecycle())
        if daily is None or daily.empty:
            return ()
        context = build_precomputed_ticker_context(task.ticker, task.ticker, daily)
        weekly = context.weekly_up_to(EXECUTION_SUPPORT_END)
        daily_dates = set(pd.DatetimeIndex(daily.index).normalize())
        valid_weeks = [pd.Timestamp(w).normalize() for w in weekly.index if pd.Timestamp(w).normalize() in daily_dates]
        panel = self.identity_raw_panel(task)
        signals: list[EntrySignal] = []
        for week in valid_weeks:
            if not START_DATE <= week <= SIGNAL_CUTOFF:
                continue
            result = evaluate_pattern_a_fast(
                task.ticker,
                task.ticker,
                daily,
                week,
                self.score_contract,
                self.stage_contract,
                context=context,
            )
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
        return tuple(signals)

    def run_matched_entry(self) -> dict[str, Any]:
        """Prepare matched pairs from an independent, strategy-neutral ledger."""
        pairs: list[dict[str, Any]] = []
        signal_count = 0
        for task in self.identity_tasks():
            signals = self.discover_matched_entry_signals(task)
            signal_count += len(signals)
            for signal in signals:
                base = self.run_identity_strategy(task, enable_loss_guard=True, allowed_signal_dates={signal.signal_date})
                julia = self.run_identity_strategy(task, enable_loss_guard=False, allowed_signal_dates={signal.signal_date})
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
        result = {BASE_STRATEGY_ID: [], JULIA_STRATEGY_ID: []}
        for task in self.identity_tasks():
            result[BASE_STRATEGY_ID].extend(self.run_identity_strategy(task, enable_loss_guard=True))
            result[JULIA_STRATEGY_ID].extend(self.run_identity_strategy(task, enable_loss_guard=False))
        return result

    def run_realistic_portfolio(self, records_by_strategy: Mapping[str, Sequence[StrategyTradeRecord]]) -> dict[str, Any]:
        """Return the portfolio execution hook without writing result files.

        The next task supplies the records from the selected result axis and
        requests persistence.  Keeping this method in the official runner
        ensures the frozen C0/q/N, costs, tax mapping, and event ordering are
        not reimplemented in the historical runner.
        """
        return {
            "axis": "Realistic 200M Portfolio",
            "ready": True,
            "strategy_ids": sorted(str(key) for key in records_by_strategy),
            "initial_capital_krw": INITIAL_CAPITAL_KRW,
            "per_symbol_cash_budget_krw": POSITION_CASH_BUDGET_KRW,
            "max_positions": MAX_POSITIONS,
            "sell_tax_mapping": "execution_date_and_market",
            "same_open_sale_proceeds_reusable": False,
            "event_ledger_columns": [
                "strategy_id", "identity", "signal_date", "execution_date", "reference_open",
                "slippage_adjusted_price", "shares", "notional", "commission", "sell_tax",
                "cash_before", "cash_after", "entry_or_exit_reason", "position_id", "OPEN_AT_CUTOFF",
            ],
            "daily_equity_columns": ["date", "strategy_id", "cash", "invested_market_value", "equity", "exposure", "drawdown"],
            "records_received": {str(key): len(value) for key, value in records_by_strategy.items()},
            "result_artifacts_written": False,
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
    parser.add_argument("--preflight-only", action="store_true", help="write/validate the contract only")
    args = parser.parse_args()
    # No official execution flag exists in this preparation task.  Keeping the
    # CLI preflight-only by construction prevents an accidental full run.
    if not args.preflight_only:
        print("Stage 5 preparation is preflight-only; pass --preflight-only explicitly.")
    with network_guard():
        result = preflight(ROOT, write_contract=True)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
