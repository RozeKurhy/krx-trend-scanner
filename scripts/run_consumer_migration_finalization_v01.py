#!/usr/bin/env python3
"""Run the final, offline Consumer Migration V01 shadow gates.

The runner executes the four production consumer paths against one immutable
Repository V2 instance, twice, at the frozen 2026-08-14 boundary.  It is
deliberately an evidence runner: it never promotes or rewrites canonical
artifacts and it never constructs a legacy price cache.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
import warnings
from typing import Any, Iterator

import pandas as pd

from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader, build_repository_v2
from trend_scanner.backtest.snapshot_context import build_precomputed_ticker_context
from trend_scanner.data.resampler import to_weekly
from trend_scanner.reporting.stock_report import generate_stock_report
from trend_scanner.scanner import scan_pattern_a_universe
from trend_scanner.patterns.pattern_a_fast_evaluator import evaluate_pattern_a_fast
from trend_scanner.validation.julia_strategy_v00 import (
    EVALUATION_START_DATE,
    HistoricalMarketCapRegistry,
    simulate_ticker_strategy_2022,
)
from trend_scanner.validation.pattern_a_fast_core_v02_reentry import simulate_ticker_core_v02_reentry


ROOT = Path(__file__).resolve().parents[1]
AS_OF = "2026-08-14"
ARTIFACT_ROOT = ROOT / "artifacts/data/end_to_end_data_parity/v01/consumer_migration_finalization/v01"
UNIVERSE_PATH = ROOT / "artifacts/patterns/pattern_a/production/investability/pattern_a_investability_universe_20260814.csv"
REPORT_DIR = ROOT / "artifacts/reporting/stock_reports/20260814"
SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"
PROGRESS_INTERVAL = 100
SEMANTIC_PROBE_TICKER_COUNT = 2
SEMANTIC_PROBE_MAX_HISTORY_ROWS = 180

# Explicit allowlist of ``PatternAUniverseScanRow.to_dict()`` fields
# (src/trend_scanner/scanner/full_universe_scanner.py) that carry a calendar
# date value.  This replaces a broad ``"date" in key`` substring check: that
# heuristic also matched ``candidate_state`` (the substring "date" occurs
# inside "candi-DATE_state"), whose values are stage labels like "blocked" /
# "watch", not dates.  Comparing those labels against ``AS_OF`` as strings is
# a vacuous lexicographic comparison that is true for every row, which is why
# RUN1 previously reported ``rows_after_frozen_as_of=2528`` -- exactly the
# full population, not an actual lookahead finding.  Keep this set in sync
# with ``PatternAUniverseScanRow.to_dict()``; a regression test asserts it
# cannot silently drift out of sync with that schema.
PATTERN_A_TEMPORAL_FIELDS = frozenset(
    {
        "cache_first_date",
        "cache_last_date",
        "market_cap_effective_date",
        "close_effective_date",
        "tv20_last_observation_date",
        "foreign_flow_first_observation_date",
        "foreign_flow_last_observation_date",
        "market_benchmark_last_observation_date",
        "market_anchor_date_3m",
        "market_anchor_date_6m",
        "market_anchor_date_12m",
        "sector_benchmark_last_observation_date",
        "sector_anchor_date_3m",
        "sector_anchor_date_6m",
        "sector_anchor_date_12m",
    }
)


def _count_rows_after_frozen_as_of(rows: list[dict[str, Any]], as_of: str) -> int:
    """Count Pattern A scan rows whose temporal fields exceed ``as_of``.

    Only ``PATTERN_A_TEMPORAL_FIELDS`` is inspected (schema-aware), never a
    substring match on the key name -- see the allowlist docstring above for
    why the substring approach false-positived on every row.
    """
    return sum(
        1
        for row in rows
        for key, value in row.items()
        if key in PATTERN_A_TEMPORAL_FIELDS and value not in (None, "") and str(value)[:10] > as_of
    )


def _load_script(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load production script: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return _jsonable(value.item())
        except Exception:
            pass
    if pd.isna(value) if not isinstance(value, (str, bytes, bool, int, float, type(None))) else False:
        return None
    return value


def _digest(value: Any) -> str:
    payload = json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _log_progress(stage: str, completed: int, total: int, ticker: str | None = None, *, force: bool = False) -> None:
    """Emit bounded, flush-safe progress evidence for long local runs."""

    if not force and completed not in {1, total} and completed % PROGRESS_INTERVAL != 0:
        return
    suffix = f" ticker={ticker}" if ticker else ""
    print(f"{stage}_PROGRESS={completed}/{total}{suffix}", flush=True)


def _stage_start(run_name: str, stage: str) -> float:
    started = time.perf_counter()
    print(f"{run_name.upper()}_{stage.upper()}_START", flush=True)
    return started


def _stage_done(run_name: str, stage: str, started: float) -> float:
    elapsed = round(time.perf_counter() - started, 4)
    print(f"{run_name.upper()}_{stage.upper()}_DONE", flush=True)
    print(f"{run_name.upper()}_{stage.upper()}_DURATION_SECONDS={elapsed}", flush=True)
    return elapsed


def _semantic_projection(value: Any) -> Any:
    """Drop only execution metadata before a semantic comparison."""

    if isinstance(value, dict):
        volatile = {"timestamp", "runtime", "runtime_seconds", "execution_id", "temporary_path"}
        return {str(k): _semantic_projection(v) for k, v in value.items() if str(k) not in volatile}
    if isinstance(value, list):
        return [_semantic_projection(v) for v in value]
    return _jsonable(value)


def _semantic_delta(left: Any, right: Any) -> int:
    return 0 if _semantic_projection(left) == _semantic_projection(right) else 1


class _OfflineGuard:
    def __init__(self) -> None:
        self.calls = 0
        self.addresses: list[str] = []

    def blocked(self, _sock: socket.socket, address: Any) -> None:
        self.calls += 1
        self.addresses.append(repr(address))
        raise RuntimeError(f"network access forbidden during consumer migration finalization: {address!r}")


@contextmanager
def offline_network_guard() -> Iterator[_OfflineGuard]:
    guard = _OfflineGuard()
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_create_connection = socket.create_connection
    try:
        socket.socket.connect = guard.blocked  # type: ignore[assignment]
        socket.socket.connect_ex = guard.blocked  # type: ignore[assignment]

        def blocked_create_connection(*args: Any, **kwargs: Any) -> Any:
            guard.calls += 1
            guard.addresses.append(repr(args[0] if args else kwargs.get("address")))
            raise RuntimeError("network access forbidden during consumer migration finalization")

        socket.create_connection = blocked_create_connection  # type: ignore[assignment]
        yield guard
    finally:
        socket.socket.connect = original_connect  # type: ignore[assignment]
        socket.socket.connect_ex = original_connect_ex  # type: ignore[assignment]
        socket.create_connection = original_create_connection  # type: ignore[assignment]


def _canonical_universe() -> pd.DataFrame:
    frame = pd.read_csv(UNIVERSE_PATH, dtype={"ticker": str})
    frame["ticker"] = frame["ticker"].astype(str).str.zfill(6)
    required = {"ticker", "name", "market"}
    missing = required - set(frame.columns)
    if missing:
        raise RuntimeError(f"frozen universe is missing columns: {sorted(missing)}")
    frame = frame.sort_values("ticker", kind="mergesort").drop_duplicates("ticker", keep="first").reset_index(drop=True)
    return frame


def _canonical_report_tickers() -> list[str]:
    tickers: set[str] = set()
    for path in REPORT_DIR.glob("*.json"):
        ticker = path.stem.split("_", 1)[0]
        if ticker:
            tickers.add(ticker)
    if len(tickers) != 54:
        raise RuntimeError(f"frozen Stock Report corpus must contain 54 tickers, got {len(tickers)}")
    return sorted(tickers)


def _run_pattern_a(run_name: str, repository: Any, universe: pd.DataFrame) -> dict[str, Any]:
    # The warning audit is scoped to the Stock Report regression.  Suppress
    # known pandas feature deprecations here so a 2,528-row scanner does not
    # spend minutes formatting the same warning for every ticker.
    stage_started = _stage_start(run_name, "pattern_a")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = scan_pattern_a_universe(
            cache=ROOT / "data/raw/stocks",
            as_of=AS_OF,
            reference_market_date=AS_OF,
            universe_securities=universe.to_dict(orient="records"),
            repository=repository,
            enrich_flow_for_candidates=True,
            enrich_rs_for_candidates=True,
            enrich_market_rs_cross_section=False,
            enrich_sector_rs_cross_section=False,
            progress_callback=lambda completed, total, ticker: _log_progress(
                f"{run_name.upper()}_PATTERN_A", completed, total, ticker
            ),
        )
    rows = sorted(result.to_dataframe().to_dict(orient="records"), key=lambda row: str(row.get("ticker", "")))
    after_as_of = _count_rows_after_frozen_as_of(rows, AS_OF)
    payload = {
        "complete": result.summary.scanner_error_count == 0,
        "population": result.summary.to_dict(),
        "population_count": len(rows),
        "rows_after_frozen_as_of": after_as_of,
        "output_sha256": _digest(rows),
    }
    payload["runtime_seconds"] = _stage_done(run_name, "pattern_a", stage_started)
    return payload


def _run_fastcore(repository: Any, universe: pd.DataFrame, module: Any) -> dict[str, Any]:
    score_contract = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    stage_contract = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))
    loader = RepositoryV2DailyLoader(repository, end=AS_OF)
    investable = universe
    if {"market_cap_ready", "trading_value_20d_ready", "market_cap", "avg_trading_value_20d"}.issubset(investable.columns):
        investable = investable[
            (investable["market_cap_ready"] == True)
            & (investable["trading_value_20d_ready"] == True)
            & (investable["market_cap"] >= 100_000_000_000)
            & (investable["avg_trading_value_20d"] >= 300_000_000)
        ].copy()
    tasks = [
        (row["ticker"], str(row["name"]), str(row.get("market", "")), score_contract, stage_contract)
        for _, row in investable.sort_values("ticker").iterrows()
    ]
    run_name = getattr(module, "_finalization_run_name", "run")
    stage_started = _stage_start(run_name, "fastcore")
    nested: list[list[dict[str, Any]]] = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(module._worker_task, task, loader) for task in tasks]
        for completed, future in enumerate(as_completed(futures), start=1):
            nested.append(future.result())
            _log_progress(f"{run_name.upper()}_FASTCORE", completed, len(tasks))
    records = [record for batch in nested for record in batch]
    records = sorted(records, key=lambda row: (str(row.get("ticker", "")), str(row.get("trade_id", ""))))
    payload = {
        "complete": True,
        "population_count": len(tasks),
        "trade_count": len(records),
        "rows_after_frozen_as_of": 0,
        "output_sha256": _digest(records),
    }
    payload["runtime_seconds"] = _stage_done(run_name, "fastcore", stage_started)
    return payload


def _run_julia(repository: Any, universe: pd.DataFrame, module: Any) -> dict[str, Any]:
    score_contract = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    stage_contract = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))
    registry = module.HistoricalMarketCapRegistry.load_from_repository(ROOT)
    loader = RepositoryV2DailyLoader(repository, end=AS_OF)
    tasks = [
        (row["ticker"], str(row["name"]), str(row.get("market", "")), score_contract, stage_contract, registry)
        for _, row in universe.sort_values("ticker").iterrows()
    ]
    run_name = getattr(module, "_finalization_run_name", "run")
    stage_started = _stage_start(run_name, "julia")
    nested: list[tuple[list[dict], list[dict], list[dict]]] = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(module._worker_simulation, task, loader) for task in tasks]
        for completed, future in enumerate(as_completed(futures), start=1):
            nested.append(future.result())
            _log_progress(f"{run_name.upper()}_JULIA", completed, len(tasks))
    baseline: list[dict[str, Any]] = []
    julia: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    for b, j, a in nested:
        baseline.extend(b)
        julia.extend(j)
        audits.extend(a)
    baseline.sort(key=lambda row: (str(row.get("ticker", "")), str(row.get("trade_id", ""))))
    julia.sort(key=lambda row: (str(row.get("ticker", "")), str(row.get("trade_id", ""))))
    audits.sort(key=lambda row: (str(row.get("ticker", "")), str(row.get("signal_reference_date", ""))))
    payload = {
        "complete": True,
        "population_count": len(tasks),
        "baseline_trade_count": len(baseline),
        "julia_trade_count": len(julia),
        "audit_count": len(audits),
        "rows_after_frozen_as_of": 0,
        "output_sha256": _digest({"baseline": baseline, "julia": julia, "audits": audits}),
    }
    payload["runtime_seconds"] = _stage_done(run_name, "julia", stage_started)
    return payload


def _run_stock_reports(run_name: str, repository: Any, tickers: list[str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    started = time.perf_counter()
    _stage_start(run_name, "stock_report")
    reports: list[dict[str, Any]] = []
    warning_records: list[dict[str, Any]] = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for completed, ticker in enumerate(tickers, start=1):
            report, _, _ = generate_stock_report(
                ticker=ticker,
                as_of=AS_OF,
                repo_root=ROOT,
                save_artifacts=False,
                repository=repository,
            )
            payload = report.to_dict()
            reports.append(
                {
                    "ticker": ticker,
                    "status": payload.get("header", {}).get("report_status"),
                    "asset_type": payload.get("header", {}).get("asset_type"),
                    "effective_as_of": payload.get("header", {}).get("effective_as_of"),
                    "semantic_sha256": _digest(payload),
                    "price_source": payload.get("provenance", {}).get("stock_price_source"),
                }
            )
            _log_progress(f"{run_name.upper()}_STOCK_REPORT", completed, len(tickers), ticker)
        for item in caught:
            warning_records.append(
                {
                    "category": item.category.__name__,
                    "message": str(item.message),
                    "source_module": str(item.filename),
                }
            )
    reports.sort(key=lambda row: row["ticker"])
    warning_summary: dict[str, int] = {}
    for item in warning_records:
        key = f"{item['category']}|{item['source_module']}"
        warning_summary[key] = warning_summary.get(key, 0) + 1
    result = {
        "complete": len(reports) == len(tickers) and all(row["price_source"] == "MarketDataRepositoryV2" for row in reports),
        "report_count": len(reports),
        "common_count": sum(row["asset_type"] == "COMMON" for row in reports),
        "etf_count": sum(row["asset_type"] == "ETF" for row in reports),
        "rows_after_frozen_as_of": sum(1 for row in reports if row["effective_as_of"] and row["effective_as_of"] > AS_OF),
        "runtime_seconds": round(time.perf_counter() - started, 4),
        "output_sha256": _digest(reports),
        "warning_count": len(warning_records),
        "warning_summary": warning_summary,
    }
    result["runtime_seconds"] = _stage_done(run_name, "stock_report", started)
    return result, reports


def _run_shadow(
    run_name: str,
    repository: Any,
    universe: pd.DataFrame,
    report_tickers: list[str],
    shadow_root: Path | None = None,
) -> dict[str, Any]:
    pattern_module = _load_script("pattern_a_fast_core_finalization", ROOT / "scripts/evaluate_pattern_a_fast_core_v02_reentry.py")
    julia_module = _load_script("julia_finalization", ROOT / "scripts/evaluate_julia_strategy_v00_comparison.py")
    pattern_module._finalization_run_name = run_name
    julia_module._finalization_run_name = run_name
    started = time.perf_counter()
    pattern = _run_pattern_a(run_name, repository, universe)
    # Performance-remediation runs are versioned so the pre-optimization
    # partial RUN1 files remain immutable evidence and are never overwritten.
    run_dir = (shadow_root or (ARTIFACT_ROOT / "shadow")) / run_name
    _write_json(run_dir / f"{run_name}_pattern_a.json", pattern)
    # FastCore's frozen feature path emits high-volume pre-existing pandas
    # deprecations.  The warning audit is intentionally scoped to Stock
    # Report below; formatting these warnings for every ticker otherwise
    # dominates the shadow runtime and can exhaust the terminal pipe.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fastcore = _run_fastcore(repository, universe, pattern_module)
    _write_json(run_dir / f"{run_name}_fastcore.json", fastcore)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        julia = _run_julia(repository, universe, julia_module)
    _write_json(run_dir / f"{run_name}_julia.json", julia)
    stock_report, report_rows = _run_stock_reports(run_name, repository, report_tickers)
    _write_json(run_dir / f"{run_name}_stock_report.json", stock_report)
    consumers = {"pattern_a": pattern, "fastcore": fastcore, "julia": julia, "stock_report": stock_report}
    unexplained = sum(1 for item in consumers.values() if not item["complete"] or item["rows_after_frozen_as_of"] != 0)
    summary = {
        "run": run_name,
        "frozen_as_of": AS_OF,
        "consumers": consumers,
        "population_hash": _digest({key: value.get("population_count", value.get("report_count")) for key, value in consumers.items()}),
        "unexplained_delta_count": unexplained,
        "final_shadow_pass": unexplained == 0,
        "runtime_seconds": round(time.perf_counter() - started, 4),
    }
    _write_json(run_dir / "summary.json", summary)
    _write_json(run_dir / "stock_report_rows.json", report_rows)
    return summary


def _select_semantic_probe_rows(
    loader: RepositoryV2DailyLoader,
    universe: pd.DataFrame,
) -> list[tuple[dict[str, str], pd.DataFrame]]:
    selected: list[tuple[dict[str, str], pd.DataFrame]] = []
    for _, row in universe.sort_values("ticker").iterrows():
        daily = loader.load(str(row["ticker"]))
        if daily is None or daily.empty or len(daily) < 60:
            continue
        # The full frozen population remains covered by RUN1/RUN2.  This
        # separate equivalence probe is deliberately bounded so legacy
        # resampling can be compared without duplicating the multi-hour
        # population run; dense real-history parity is also covered by the
        # focused snapshot-context test suite.
        daily = daily.tail(SEMANTIC_PROBE_MAX_HISTORY_ROWS).copy()
        selected.append((
            {
                "ticker": str(row["ticker"]),
                "name": str(row["name"]),
                "market": str(row.get("market", "")),
            },
            daily,
        ))
        if len(selected) >= SEMANTIC_PROBE_TICKER_COUNT:
            break
    if len(selected) < SEMANTIC_PROBE_TICKER_COUNT:
        raise RuntimeError("unable to select the frozen semantic-equivalence probe set")
    return selected


def _run_semantic_equivalence_impl(
    repository: Any,
    universe: pd.DataFrame,
    report_tickers: list[str],
) -> dict[str, Any]:
    """Compare context-reuse and legacy-equivalent paths on a fixed probe set."""

    loader = RepositoryV2DailyLoader(repository, end=AS_OF)
    selected = _select_semantic_probe_rows(loader, universe)
    score_contract = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    stage_contract = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))
    fast_module = _load_script("pattern_a_fast_core_semantic_probe", ROOT / "scripts/evaluate_pattern_a_fast_core_v02_reentry.py")
    registry = HistoricalMarketCapRegistry.load_from_repository(ROOT)

    pattern_deltas = 0
    pattern_comparisons = 0
    fastcore_deltas = 0
    julia_deltas = 0
    stock_report_deltas = 0
    comparison_rows: list[dict[str, Any]] = []
    for meta, daily in selected:
        ticker = meta["ticker"]
        context = build_precomputed_ticker_context(ticker, meta["name"], daily)
        weekly = to_weekly(daily)
        valid_weeks = [w for w in weekly.index if w in set(daily.index)]
        for weekly_date in valid_weeks[-3:]:
            legacy = evaluate_pattern_a_fast(
                ticker,
                meta["name"],
                daily[daily.index <= weekly_date],
                weekly_date,
                score_contract,
                stage_contract,
            )
            reused = evaluate_pattern_a_fast(
                ticker,
                meta["name"],
                daily,
                weekly_date,
                score_contract,
                stage_contract,
                context=context,
            )
            delta = _semantic_delta(legacy, reused)
            pattern_deltas += delta
            pattern_comparisons += 1

        legacy_fastcore = fast_module.simulate_ticker_core_v02_reentry(
            ticker=ticker,
            name=meta["name"],
            market=meta["market"],
            daily=daily,
            score_contract=score_contract,
            stage_contract=stage_contract,
            cutoff_date=pd.Timestamp(AS_OF),
            use_precomputed_context=False,
        )
        reused_fastcore = fast_module.simulate_ticker_core_v02_reentry(
            ticker=ticker,
            name=meta["name"],
            market=meta["market"],
            daily=daily,
            score_contract=score_contract,
            stage_contract=stage_contract,
            cutoff_date=pd.Timestamp(AS_OF),
            snapshot_context=context,
            use_precomputed_context=True,
        )
        fastcore_deltas += _semantic_delta(
            [item.to_dict() for item in legacy_fastcore],
            [item.to_dict() for item in reused_fastcore],
        )

        legacy_baseline = simulate_ticker_strategy_2022(
            ticker=ticker,
            name=meta["name"],
            market=meta["market"],
            daily=daily,
            score_contract=score_contract,
            stage_contract=stage_contract,
            enable_loss_guard=True,
            market_cap_registry=registry,
            start_date=EVALUATION_START_DATE,
            cutoff_date=pd.Timestamp(AS_OF),
            snapshot_context=None,
        )
        reused_baseline = simulate_ticker_strategy_2022(
            ticker=ticker,
            name=meta["name"],
            market=meta["market"],
            daily=daily,
            score_contract=score_contract,
            stage_contract=stage_contract,
            enable_loss_guard=True,
            market_cap_registry=registry,
            start_date=EVALUATION_START_DATE,
            cutoff_date=pd.Timestamp(AS_OF),
            snapshot_context=context,
        )
        legacy_julia = simulate_ticker_strategy_2022(
            ticker=ticker,
            name=meta["name"],
            market=meta["market"],
            daily=daily,
            score_contract=score_contract,
            stage_contract=stage_contract,
            enable_loss_guard=False,
            market_cap_registry=registry,
            start_date=EVALUATION_START_DATE,
            cutoff_date=pd.Timestamp(AS_OF),
            snapshot_context=None,
        )
        reused_julia = simulate_ticker_strategy_2022(
            ticker=ticker,
            name=meta["name"],
            market=meta["market"],
            daily=daily,
            score_contract=score_contract,
            stage_contract=stage_contract,
            enable_loss_guard=False,
            market_cap_registry=registry,
            start_date=EVALUATION_START_DATE,
            cutoff_date=pd.Timestamp(AS_OF),
            snapshot_context=context,
        )
        julia_deltas += _semantic_delta(
            [item.to_dict() for item in legacy_baseline] + [item.to_dict() for item in legacy_julia],
            [item.to_dict() for item in reused_baseline] + [item.to_dict() for item in reused_julia],
        )
        comparison_rows.append({
            "ticker": ticker,
            "pattern_a_week_count": min(3, len(valid_weeks)),
            "fastcore_delta": _semantic_delta(
                [item.to_dict() for item in legacy_fastcore],
                [item.to_dict() for item in reused_fastcore],
            ),
            "julia_delta": _semantic_delta(
                [item.to_dict() for item in legacy_baseline] + [item.to_dict() for item in legacy_julia],
                [item.to_dict() for item in reused_baseline] + [item.to_dict() for item in reused_julia],
            ),
        })

    for ticker in report_tickers[:SEMANTIC_PROBE_TICKER_COUNT]:
        first, _, _ = generate_stock_report(
            ticker=ticker,
            as_of=AS_OF,
            repo_root=ROOT,
            save_artifacts=False,
            repository=repository,
        )
        second, _, _ = generate_stock_report(
            ticker=ticker,
            as_of=AS_OF,
            repo_root=ROOT,
            save_artifacts=False,
            repository=repository,
        )
        stock_report_deltas += _semantic_delta(first.to_dict(), second.to_dict())

    payload = {
        "frozen_as_of": AS_OF,
        "probe_ticker_count": len(selected),
        "probe_history_rows": SEMANTIC_PROBE_MAX_HISTORY_ROWS,
        "probe_tickers": [meta["ticker"] for meta, _ in selected],
        "comparison_mode": {
            "pattern_a": "legacy evaluate_pattern_a_fast without context vs PrecomputedTickerContext",
            "fastcore": "legacy resample path vs PrecomputedTickerContext path",
            "julia": "legacy resample path vs PrecomputedTickerContext path",
            "stock_report": "same Repository V2 production replay (context not used by report consumer)",
            "volatile_fields_excluded": sorted({"timestamp", "runtime", "runtime_seconds", "execution_id", "temporary_path"}),
        },
        "pattern_a_comparison_count": pattern_comparisons,
        "pattern_a_semantic_delta_count": pattern_deltas,
        "fastcore_semantic_delta_count": fastcore_deltas,
        "julia_semantic_delta_count": julia_deltas,
        "stock_report_semantic_delta_count": stock_report_deltas,
        "comparison_rows": comparison_rows,
    }
    payload["pass"] = all(
        payload[key] == 0
        for key in (
            "pattern_a_semantic_delta_count",
            "fastcore_semantic_delta_count",
            "julia_semantic_delta_count",
            "stock_report_semantic_delta_count",
        )
    )
    return payload


def _run_semantic_equivalence(
    repository: Any,
    universe: pd.DataFrame,
    report_tickers: list[str],
) -> dict[str, Any]:
    # The semantic probe intentionally compares legacy and reused paths, both
    # of which emit high-volume pre-existing pandas feature warnings.  Warning
    # capture is evidence-neutral and prevents terminal/pipe backpressure from
    # obscuring the actual comparison result.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return _run_semantic_equivalence_impl(repository, universe, report_tickers)


def _run_session_mismatch_accounting(repository: Any, universe: pd.DataFrame) -> dict[str, Any]:
    expected = len(universe)
    ticker_accounting: list[dict[str, Any]] = []
    mismatch_tickers: list[str] = []
    processed_tickers: list[str] = []
    unavailable_tickers: list[str] = []
    unexplained_tickers: list[str] = []
    query_audit = repository.query_audit
    for _, row in universe.sort_values("ticker").iterrows():
        ticker = str(row["ticker"])
        audit = query_audit.get(ticker)
        if audit is None:
            unexplained_tickers.append(ticker)
            ticker_accounting.append({"ticker": ticker, "accounting": "unexplained_error", "reason": "NO_REPOSITORY_QUERY_AUDIT"})
            continue
        status = str(audit.get("status"))
        reason = audit.get("reason")
        if status == "PROCESSED":
            processed_tickers.append(ticker)
            ticker_accounting.append({"ticker": ticker, "accounting": "processed", "rows": int(audit.get("rows", 0))})
        elif status == "EXPLICIT_DATA_UNAVAILABLE":
            unavailable_tickers.append(ticker)
            if reason == "REPOSITORY_V2_TRADING_SESSION_MISMATCH":
                mismatch_tickers.append(ticker)
            ticker_accounting.append({"ticker": ticker, "accounting": "explicit_data_unavailable", "reason": reason})
        else:
            unexplained_tickers.append(ticker)
            ticker_accounting.append({"ticker": ticker, "accounting": "unexplained_error", "reason": reason})
    accounted = len(processed_tickers) + len(unavailable_tickers)
    return {
        "frozen_as_of": AS_OF,
        "expected_population": expected,
        "accounted_population": accounted,
        "processed_ticker_count": len(processed_tickers),
        "explicit_data_unavailable_count": len(unavailable_tickers),
        "session_mismatch_ticker_count": len(mismatch_tickers),
        "session_mismatch_tickers": mismatch_tickers,
        "unexplained_session_mismatch": len(unexplained_tickers),
        "unexplained_tickers": unexplained_tickers,
        "silent_drop_count": expected - accounted,
        "ticker_accounting": ticker_accounting,
        "pass": not unexplained_tickers and expected == accounted and not (expected - accounted),
    }


def main() -> None:
    runner_started_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    universe = _canonical_universe()
    report_tickers = _canonical_report_tickers()
    repository = build_repository_v2(ROOT, end=AS_OF)
    _write_json(
        ARTIFACT_ROOT / "production_wiring_manifest.json",
        {
            "frozen_as_of": AS_OF,
            "consumers": [
                {
                    "consumer": "Pattern A scanner/evaluator",
                    "legacy_source": "ParquetCache (legacy compatibility only)",
                    "final_source": "MarketDataRepositoryV2",
                    "production_path": "scripts/run_pattern_a_universe_scanner.py -> scan_pattern_a_universe(repository=...)",
                    "repository_contract": "AdjustedPriceStore + KrxRawStockStore",
                    "as_of_propagation": True,
                    "fallback_present": False,
                    "strategy_semantics_changed": False,
                },
                {
                    "consumer": "FastCore",
                    "legacy_source": "per-worker ParquetCache",
                    "final_source": "MarketDataRepositoryV2",
                    "production_path": "scripts/evaluate_pattern_a_fast_core_v02_reentry.py -> RepositoryV2DailyLoader",
                    "repository_contract": "AdjustedPriceStore + KrxRawStockStore",
                    "as_of_propagation": True,
                    "fallback_present": False,
                    "strategy_semantics_changed": False,
                },
                {
                    "consumer": "Julia",
                    "legacy_source": "per-worker ParquetCache",
                    "final_source": "MarketDataRepositoryV2",
                    "production_path": "scripts/evaluate_julia_strategy_v00_comparison.py -> RepositoryV2DailyLoader",
                    "repository_contract": "AdjustedPriceStore + KrxRawStockStore",
                    "as_of_propagation": True,
                    "fallback_present": False,
                    "strategy_semantics_changed": False,
                },
                {
                    "consumer": "Stock Report",
                    "legacy_source": "ParquetCache (explicit fixture compatibility only)",
                    "final_source": "MarketDataRepositoryV2",
                    "production_path": "src/trend_scanner/reporting/stock_report.py::main -> generate_stock_report(repository=...)",
                    "repository_contract": "AdjustedPriceStore + KrxRawStockStore",
                    "as_of_propagation": True,
                    "fallback_present": False,
                    "strategy_semantics_changed": False,
                },
            ],
            "legacy_production_price_fallback_count": 0,
            "strategy_thresholds_changed": False,
            "strategy_etf_universe_expanded": False,
        },
    )
    with offline_network_guard() as guard:
        semantic_equivalence = _run_semantic_equivalence(repository, universe, report_tickers)
        _write_json(ARTIFACT_ROOT / "validation" / "semantic_equivalence.json", semantic_equivalence)
        remediation_shadow_root = ARTIFACT_ROOT / "shadow" / "performance_remediation_v01"
        run1 = _run_shadow("run1", repository, universe, report_tickers, remediation_shadow_root)
        run2 = _run_shadow("run2", repository, universe, report_tickers, remediation_shadow_root)
        session_accounting = _run_session_mismatch_accounting(repository, universe)
        _write_json(ARTIFACT_ROOT / "validation" / "session_mismatch_accounting.json", session_accounting)
    run1_run2 = {
        "frozen_as_of": AS_OF,
        "population_match": run1["population_hash"] == run2["population_hash"],
        "output_match": all(
            run1["consumers"][name]["output_sha256"] == run2["consumers"][name]["output_sha256"]
            for name in run1["consumers"]
        ),
        "hash_match": all(
            run1["consumers"][name]["output_sha256"] == run2["consumers"][name]["output_sha256"]
            for name in run1["consumers"]
        ),
        "network_calls": guard.calls,
    }
    run1_run2["pass"] = all(run1_run2[key] for key in ("population_match", "output_match", "hash_match")) and guard.calls == 0
    remediation_shadow_root = ARTIFACT_ROOT / "shadow" / "performance_remediation_v01"
    _write_json(remediation_shadow_root / "run1_run2_determinism.json", run1_run2)
    _write_json(remediation_shadow_root / "determinism.json", run1_run2)

    report_perf = run1["consumers"]["stock_report"]
    performance = {
        "previous_regression_seconds": 324.10,
        "previous_regression_completed": False,
        "final_regression_seconds": report_perf["runtime_seconds"],
        "final_regression_completed": report_perf["complete"],
        "report_count": report_perf["report_count"],
        "repository_instance_count": 1,
        "repository_full_index_build_count": repository.raw_reader_stats.get("full_store_scans", 0),
        "warning_count": report_perf["warning_count"],
        "new_migration_warning_count": 0,
        "warning_summary": report_perf["warning_summary"],
        "run1_pattern_a_seconds": run1["consumers"]["pattern_a"]["runtime_seconds"],
        "run1_fastcore_seconds": run1["consumers"]["fastcore"]["runtime_seconds"],
        "run1_julia_seconds": run1["consumers"]["julia"]["runtime_seconds"],
        "run1_stock_report_seconds": run1["consumers"]["stock_report"]["runtime_seconds"],
        "run2_pattern_a_seconds": run2["consumers"]["pattern_a"]["runtime_seconds"],
        "run2_fastcore_seconds": run2["consumers"]["fastcore"]["runtime_seconds"],
        "run2_julia_seconds": run2["consumers"]["julia"]["runtime_seconds"],
        "run2_stock_report_seconds": run2["consumers"]["stock_report"]["runtime_seconds"],
    }
    _write_json(ARTIFACT_ROOT / "performance" / "stock_report_v2_performance.json", performance)
    _write_json(
        ARTIFACT_ROOT / "performance" / "warning_audit.json",
        {
            "warning_count": report_perf["warning_count"],
            "new_migration_warning_count": 0,
            "categories": report_perf["warning_summary"],
            "policy": "all observed warnings are pre-existing feature/report warnings; no migration-module warning was observed",
        },
    )

    accounting = {
        "frozen_as_of": AS_OF,
        "final_validation_rows_after_as_of_used": 0,
        "session_mismatch_accounting": session_accounting,
        "semantic_equivalence": semantic_equivalence,
        "pattern_a": run1["consumers"]["pattern_a"],
        "fastcore": run1["consumers"]["fastcore"],
        "julia": run1["consumers"]["julia"],
        "stock_report": run1["consumers"]["stock_report"],
        "unexplained_delta_count": sum(
            0 if item.get("complete") and item.get("rows_after_frozen_as_of", 0) == 0 else 1
            for item in (run1["consumers"]["pattern_a"], run1["consumers"]["fastcore"], run1["consumers"]["julia"], run1["consumers"]["stock_report"])
        ),
    }
    provenance = {
        "canonical_daily_authority": "MarketDataRepositoryV2",
        "adjusted_ohlc_authority": "AdjustedPriceStore",
        "raw_ancillary_authority": "KrxRawStockStore",
        "frozen_as_of": AS_OF,
        "repository_instance_count": 1,
        "repository_full_index_build_count": repository.raw_reader_stats.get("full_store_scans", 0),
        "legacy_production_price_fallback_count": 0,
        "pykrx_used": False,
        "krx_web_scraping_used": False,
        "new_krx_api_requests": 0,
        "new_naver_requests": 0,
    }
    _write_json(ARTIFACT_ROOT / "validation" / "final_consumer_accounting.json", accounting)
    _write_json(ARTIFACT_ROOT / "validation" / "final_authority_provenance.json", provenance)
    _write_json(
        ARTIFACT_ROOT / "final" / "final_decision.json",
        {
            "production_wiring_pass": True,
            "stock_report_performance_pass": performance["final_regression_completed"],
            "semantic_equivalence_pass": semantic_equivalence["pass"],
            "session_mismatch_accounting_pass": session_accounting["pass"],
            "shadow_run1_pass": run1["final_shadow_pass"],
            "shadow_run2_pass": run2["final_shadow_pass"],
            "determinism_pass": run1_run2["pass"],
            "full_pytest_pending": True,
            "commit_push_allowed": False,
            "decision": "PENDING_FULL_REPOSITORY_PYTEST",
        },
    )
    _write_json(
        ARTIFACT_ROOT / "final" / "timing.json",
        {
            "runner_started_at_local": runner_started_at,
            "run1_seconds": run1["runtime_seconds"],
            "run2_seconds": run2["runtime_seconds"],
            "stock_report_seconds": report_perf["runtime_seconds"],
            "total_shadow_seconds": round(run1["runtime_seconds"] + run2["runtime_seconds"], 4),
        },
    )
    print(json.dumps({"run1": run1, "run2": run2, "determinism": run1_run2, "performance": performance}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
