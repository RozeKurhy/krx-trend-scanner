"""Phase 3C exact-date Market RS universe snapshot builder.

Reuses the existing Market RS calculation engine
(:func:`compute_relative_strength_features`,
:func:`compute_market_rs_cross_section`) unchanged. This module only adds the
thin orchestration Phase 3C needs: resolve one explicit ``target_as_of`` to
the Phase 1 rolling-PIT COMMON denominator (KOSPI+KOSDAQ), load stock/
benchmark history through the production (rolling-authority-bound)
Repository V2 and IndexStore, and publish
``market_rs_universe_{YYYYMMDD}.csv`` at the existing exact-date consumer
path.

No new RS formula, no new authority parser, no sector RS. See
docs/architecture/daily_update_phase3_analysis_inputs_contract_v01.md §4.3.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import tempfile
from typing import Any

import pandas as pd

from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.index_store import DEFAULT_INDEX_STORE_ROOT, IndexStore, MARKET_INDEX_FAMILY
from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader, build_production_repository_v2
from trend_scanner.data.rolling_market_data_refresh import (
    DEFAULT_MERGED_PIT_PATH,
    DEFAULT_ROLLING_AUTHORITY_DIR,
    RollingAuthorityError,
    load_rolling_authority,
    resolve_current_identity,
)
from trend_scanner.relative_strength.cross_section import compute_market_rs_cross_section
from trend_scanner.relative_strength.relative_strength import compute_relative_strength_features
from trend_scanner.universe.models import MarketType


ROOT = Path(__file__).resolve().parents[1]

PASS = "PASS"
NOOP_ALREADY_COMPLETE = "NOOP_ALREADY_COMPLETE"
BLOCKED = "BLOCKED"
FAILED = "FAILED"

OUTPUT_DIR = Path(
    "artifacts/patterns/pattern_a/validation/relative_strength/market_completion_v01"
)
OUTPUT_TEMPLATE = "market_rs_universe_{date}.csv"

MARKET_INDEX_CODES = {"KOSPI": "1001", "KOSDAQ": "2001"}
BENCHMARK_HORIZON_SESSIONS_12M = 252

OUTPUT_COLUMNS = (
    "ticker",
    "market",
    "as_of",
    "market_rs_data_status",
    "market_benchmark_name",
    "market_benchmark_code",
    "market_benchmark_last_observation_date",
    "stock_return_2w",
    "stock_return_1m",
    "stock_return_3m",
    "stock_return_6m",
    "stock_return_12m",
    "market_return_2w",
    "market_return_1m",
    "market_return_3m",
    "market_return_6m",
    "market_return_12m",
    "market_rs_2w",
    "market_rs_1m",
    "market_rs_3m",
    "market_rs_6m",
    "market_rs_12m",
    "market_anchor_date_2w",
    "market_anchor_date_1m",
    "market_anchor_date_3m",
    "market_anchor_date_6m",
    "market_anchor_date_12m",
    "market_rs_delta_3m_vs_6m",
    "market_rs_delta_6m_vs_12m",
    "market_rs_acceleration_3_6_12m",
    "all_market_rs_rank_2w",
    "all_market_rs_rank_1m",
    "all_market_rs_rank_3m",
    "all_market_rs_rank_6m",
    "all_market_rs_rank_12m",
    "all_market_rs_percentile_2w",
    "all_market_rs_percentile_1m",
    "all_market_rs_percentile_3m",
    "all_market_rs_percentile_6m",
    "all_market_rs_percentile_12m",
)


class MarketRsSnapshotError(RuntimeError):
    """An unexpected, non-fail-closed implementation error (maps to FAILED)."""


@dataclass(frozen=True)
class MarketRsSnapshotResult:
    status: str
    reason: str | None
    target_as_of: str
    output_path: str | None
    row_count: int
    ticker_count: int
    repository_ticker_loads: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _output_path(repo_root: Path, target_as_of: str) -> Path:
    return repo_root / OUTPUT_DIR / OUTPUT_TEMPLATE.format(date=target_as_of.replace("-", ""))


def _load_pit_common_population(repo_root: Path, target_as_of: str) -> list[dict[str, str]]:
    """Return the full Phase 1 rolling-PIT COMMON KOSPI/KOSDAQ population as of target.

    Raises ``MarketRsSnapshotError`` (structural/unreadable authority; maps to
    FAILED) or a distinguishable ``_AmbiguousIdentityError`` (maps to BLOCKED)
    when the denominator itself cannot be resolved unambiguously.
    """

    pit_path = repo_root / DEFAULT_MERGED_PIT_PATH
    try:
        payload = json.loads(pit_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MarketRsSnapshotError(f"PIT_AUTHORITY_UNREADABLE:{exc}") from exc

    intervals_by_ticker: dict[str, list[dict[str, Any]]] = {}
    for interval in payload.get("intervals", []):
        if interval.get("state") != "COMMON":
            continue
        ticker = str(interval.get("ticker", "")).zfill(6)
        if not ticker:
            continue
        intervals_by_ticker.setdefault(ticker, []).append(dict(interval))

    population: list[dict[str, str]] = []
    for ticker in sorted(intervals_by_ticker):
        resolution = resolve_current_identity(ticker, target_as_of, intervals_by_ticker)
        if resolution.status == "AMBIGUOUS":
            raise _AmbiguousIdentityError(ticker)
        if resolution.status != "RESOLVED" or resolution.interval is None:
            continue
        interval = resolution.interval
        if not (str(interval.get("effective_from", "")) <= target_as_of <= str(interval.get("effective_to", ""))):
            continue
        market = str(interval.get("market", "")).upper()
        if market not in MARKET_INDEX_CODES:
            continue
        population.append({"ticker": ticker, "market": market})

    return sorted(population, key=lambda row: (row["market"], row["ticker"]))


class _AmbiguousIdentityError(RuntimeError):
    def __init__(self, ticker: str) -> None:
        super().__init__(f"PIT_IDENTITY_AMBIGUOUS:{ticker}")
        self.ticker = ticker


def _validate_existing_artifact(
    path: Path, target_as_of: str, population_tickers: set[str]
) -> tuple[str, str | None]:
    """Return (state, invalid_reason). state is NOT_EXISTS / VALID / INVALID."""

    if not path.exists():
        return "NOT_EXISTS", None
    try:
        frame = pd.read_csv(path, dtype={"ticker": str})
    except Exception:  # noqa: BLE001 - any read failure is an invalid artifact
        return "INVALID", "UNREADABLE"
    missing_columns = [column for column in OUTPUT_COLUMNS if column not in frame.columns]
    if missing_columns:
        return "INVALID", f"SCHEMA_INVALID:{missing_columns}"
    frame["ticker"] = frame["ticker"].astype(str).str.zfill(6)
    if frame["ticker"].duplicated().any():
        return "INVALID", "DUPLICATE_TICKER"
    if not frame["as_of"].astype(str).eq(target_as_of).all():
        return "INVALID", "WRONG_AS_OF"
    if not frame["market"].astype(str).isin(MARKET_INDEX_CODES).all():
        return "INVALID", "INVALID_MARKET"
    if set(frame["ticker"]) != population_tickers:
        return "INVALID", "TICKER_SET_MISMATCH"
    return "VALID", None


def _repository_query_start(index_store: IndexStore, target_as_of: str) -> str:
    """Compute the single repository query start covering the 12M anchor for both benchmarks."""

    candidate_starts: list[str] = []
    for code in MARKET_INDEX_CODES.values():
        history = index_store.load_family(MARKET_INDEX_FAMILY, end=target_as_of, index_codes=[code])
        if history.empty:
            continue
        dates = history["date"].tolist()
        if len(dates) > BENCHMARK_HORIZON_SESSIONS_12M:
            anchor_date = dates[len(dates) - 1 - BENCHMARK_HORIZON_SESSIONS_12M]
        else:
            anchor_date = dates[0]
        candidate_starts.append(str(anchor_date))
    if not candidate_starts:
        return target_as_of
    return min(candidate_starts)


def _benchmark_exact_target_available(index_store: IndexStore, target_as_of: str) -> bool:
    exact_target_available: list[bool] = []
    for code in MARKET_INDEX_CODES.values():
        history = index_store.load_family(MARKET_INDEX_FAMILY, end=target_as_of, index_codes=[code])
        exact_target_available.append(
            not history.empty and str(history["date"].iloc[-1]) == target_as_of
        )
    return all(exact_target_available)


def _rs_record(ticker: str, market: str, target_as_of: str, result_dict: dict[str, Any]) -> dict[str, Any]:
    record: dict[str, Any] = {"ticker": ticker, "market": market, "as_of": target_as_of}
    for column in OUTPUT_COLUMNS:
        if column in ("ticker", "market", "as_of"):
            continue
        record[column] = result_dict.get(column)
    return record


def build_market_rs_snapshot(target_as_of: str, *, repo_root: Path = ROOT) -> MarketRsSnapshotResult:
    target = str(target_as_of).strip()
    try:
        target = pd.Timestamp(target).strftime("%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid --as-of value: {target_as_of!r}") from exc

    output_path = _output_path(repo_root, target)

    try:
        manifest = load_rolling_authority(repo_root / DEFAULT_ROLLING_AUTHORITY_DIR)
    except Exception as exc:  # noqa: BLE001 - missing/invalid authority is a structural block
        return MarketRsSnapshotResult(
            status=BLOCKED,
            reason=f"PHASE1_AUTHORITY_UNAVAILABLE:{exc}",
            target_as_of=target,
            output_path=None,
            row_count=0,
            ticker_count=0,
            repository_ticker_loads=0,
        )
    if target > manifest.certified_through:
        return MarketRsSnapshotResult(
            status=BLOCKED,
            reason="TARGET_BEYOND_PHASE1_CERTIFIED_BOUNDARY",
            target_as_of=target,
            output_path=None,
            row_count=0,
            ticker_count=0,
            repository_ticker_loads=0,
        )

    try:
        population = _load_pit_common_population(repo_root, target)
    except _AmbiguousIdentityError as exc:
        return MarketRsSnapshotResult(
            status=BLOCKED,
            reason=str(exc),
            target_as_of=target,
            output_path=None,
            row_count=0,
            ticker_count=0,
            repository_ticker_loads=0,
        )
    except MarketRsSnapshotError as exc:
        return MarketRsSnapshotResult(
            status=FAILED,
            reason=str(exc),
            target_as_of=target,
            output_path=None,
            row_count=0,
            ticker_count=0,
            repository_ticker_loads=0,
        )

    population_tickers = {row["ticker"] for row in population}
    artifact_state, invalid_reason = _validate_existing_artifact(output_path, target, population_tickers)
    if artifact_state == "VALID":
        return MarketRsSnapshotResult(
            status=NOOP_ALREADY_COMPLETE,
            reason="NOOP_ALREADY_COMPLETE",
            target_as_of=target,
            output_path=str(output_path),
            row_count=len(population_tickers),
            ticker_count=len(population_tickers),
            repository_ticker_loads=0,
        )
    if artifact_state == "INVALID":
        return MarketRsSnapshotResult(
            status=BLOCKED,
            reason=f"EXISTING_EXACT_ARTIFACT_INVALID:{invalid_reason}",
            target_as_of=target,
            output_path=str(output_path),
            row_count=0,
            ticker_count=0,
            repository_ticker_loads=0,
        )

    index_store = IndexStore(root=repo_root / DEFAULT_INDEX_STORE_ROOT)
    try:
        if not _benchmark_exact_target_available(index_store, target):
            return MarketRsSnapshotResult(
                status=BLOCKED,
                reason="MARKET_INDEX_TARGET_UNAVAILABLE",
                target_as_of=target,
                output_path=None,
                row_count=0,
                ticker_count=0,
                repository_ticker_loads=0,
            )
        market_index_df = index_store.load_family(MARKET_INDEX_FAMILY, end=target)
        repo_start = _repository_query_start(index_store, target)
    except MarketDataError as exc:
        return MarketRsSnapshotResult(
            status=BLOCKED,
            reason=f"MARKET_INDEX_AUTHORITY_ERROR:{exc}",
            target_as_of=target,
            output_path=None,
            row_count=0,
            ticker_count=0,
            repository_ticker_loads=0,
        )

    repository = build_production_repository_v2(repo_root, end=target)
    loader = RepositoryV2DailyLoader(repository, start=repo_start, end=target)

    try:
        records: list[dict[str, Any]] = []
        for row in population:
            ticker, market = row["ticker"], row["market"]
            stock_df = loader.load(ticker)
            result = compute_relative_strength_features(
                ticker=ticker,
                as_of=target,
                stock_df=stock_df,
                market_index_df=market_index_df,
                market=MarketType(market),
                sector_index_df=None,
                sector_mapping=None,
            )
            records.append(_rs_record(ticker, market, target, result.to_dict()))
    except RollingAuthorityError as exc:
        return MarketRsSnapshotResult(
            status=BLOCKED,
            reason=f"PHASE1_AUTHORITY_ERROR:{exc}",
            target_as_of=target,
            output_path=None,
            row_count=0,
            ticker_count=0,
            repository_ticker_loads=loader.load_count,
        )
    except MarketDataError as exc:
        return MarketRsSnapshotResult(
            status=FAILED,
            reason=f"UNEXPECTED_REPOSITORY_ERROR:{exc}",
            target_as_of=target,
            output_path=None,
            row_count=0,
            ticker_count=0,
            repository_ticker_loads=loader.load_count,
        )

    frame = pd.DataFrame(records, columns=list(OUTPUT_COLUMNS))
    cross = compute_market_rs_cross_section(frame)
    cross = cross.loc[:, list(OUTPUT_COLUMNS)]

    result_tickers = set(cross["ticker"].astype(str))
    if (
        result_tickers != population_tickers
        or cross["ticker"].duplicated().any()
        or not cross["as_of"].astype(str).eq(target).all()
        or not cross["market"].astype(str).isin(MARKET_INDEX_CODES).all()
    ):
        return MarketRsSnapshotResult(
            status=FAILED,
            reason="ROW_SET_INVARIANT_VIOLATION",
            target_as_of=target,
            output_path=None,
            row_count=len(cross),
            ticker_count=len(result_tickers),
            repository_ticker_loads=loader.load_count,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{output_path.name}.", suffix=".tmp", dir=output_path.parent)
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        cross.to_csv(tmp_path, index=False, lineterminator="\n")
        readback = pd.read_csv(tmp_path, dtype={"ticker": str})
        readback["ticker"] = readback["ticker"].astype(str).str.zfill(6)
        if len(readback) != len(cross) or set(readback["ticker"]) != population_tickers:
            raise MarketRsSnapshotError("ATOMIC_PUBLISH_READBACK_MISMATCH")
        os.replace(tmp_path, output_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    return MarketRsSnapshotResult(
        status=PASS,
        reason="EXACT_TARGET_SNAPSHOT_PUBLISHED",
        target_as_of=target,
        output_path=str(output_path),
        row_count=len(cross),
        ticker_count=len(result_tickers),
        repository_ticker_loads=loader.load_count,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build one exact-date Market RS universe snapshot")
    parser.add_argument(
        "--as-of",
        required=True,
        help="inclusive YYYY-MM-DD target; there is no system-date default",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = build_market_rs_snapshot(args.as_of, repo_root=ROOT)
    print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result.status in {PASS, NOOP_ALREADY_COMPLETE} else 1


if __name__ == "__main__":
    raise SystemExit(main())
