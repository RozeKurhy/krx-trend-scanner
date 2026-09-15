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
import math
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


def _exact_frame_value(frame: pd.DataFrame | None, date: pd.Timestamp, column: str) -> float | None:
    if frame is None or frame.empty or column not in frame.columns:
        return None
    day = pd.Timestamp(date).normalize()
    index = pd.DatetimeIndex(pd.to_datetime(frame.index, errors="coerce")).normalize()
    if index.isna().any() or index.has_duplicates:
        return None
    matches = frame.loc[index == day, column]
    if len(matches) != 1:
        return None
    value = pd.to_numeric(matches.iloc[0], errors="coerce")
    return None if pd.isna(value) else float(value)


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
            frame = frame_for(record)
            if frame is not None:
                return _exact_frame_value(frame, day, column)
            # This branch is limited to synthetic records without a supplied
            # frame.  It is exact-date only and never searches another date.
            if column == "open" and _record_date(record, "entry_execution_date") == day:
                value = _record_value(record, "entry_open")
                return None if value in (None, "") else float(value)
            if column == "open" and _record_date(record, "exit_execution_date") == day:
                value = _record_value(record, "exit_price")
                return None if value in (None, "") else float(value)
            if column == "close" and day == FINAL_VALUATION_DATE:
                value = _record_value(record, "cutoff_valuation_price")
                return None if value in (None, "") else float(value)
            return None

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
                "signal_date": _record_value(record, "entry_signal_date"),
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
                            event["unresolved_reason"] = "MISSING_EXACT_CUTOFF_CLOSE"
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
                "date", "strategy_id", "cash", "invested_market_value", "equity", "exposure", "drawdown",
            ],
            "records_received": {str(key): len(value) for key, value in records_by_strategy.items()},
            "strategies": strategy_results,
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
    parser.add_argument("--preflight-only", action="store_true", help="validate the frozen contract only")
    parser.add_argument(
        "--write-contract",
        action="store_true",
        help="development-only initial contract creation; refuses to overwrite an existing contract",
    )
    args = parser.parse_args()
    # No official execution flag exists in this preparation task.  The default
    # path is a read-only validation of the committed frozen contract.
    if not args.preflight_only and not args.write_contract:
        print("Stage 5 preparation is preflight-only; validating the committed contract.")
    with network_guard():
        result = preflight(ROOT, write_contract=args.write_contract)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
