#!/usr/bin/env python3
"""Run the frozen V2 evaluator and portfolio replay for P2-2 V02 only."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import resource
import subprocess
import sys
import time
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
P31 = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01"
PREFLIGHT = OUT / "preflight.json"
SAMPLE_SELECTION = OUT / "sample_tickers.json"
EVAL_START = pd.Timestamp("2021-01-04")
CUTOFF = pd.Timestamp("2026-08-31")
SUPPORT = pd.Timestamp("2026-09-01")
WORKERS = 10

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader, build_repository_v2
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore


def json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    if pd.isna(value):
        return None
    raise TypeError(type(value).__name__)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=json_default) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_engine():
    source = P31 / "run_official_realistic_replay.py"
    spec = importlib.util.spec_from_file_location("p2_2_frozen_v2_reference_engine", source)
    if spec is None or spec.loader is None:
        raise RuntimeError("P3_REFERENCE_RUNNER_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.OUT = OUT
    module.EVAL_START = EVAL_START
    module.CUTOFF = CUTOFF
    module.SUPPORT = SUPPORT
    module.WORKERS = WORKERS
    module.MARKET_CAP_FLOOR = 500_000_000_000
    return module


class BoundedRepositoryLoader:
    """Keep Repository V2 inputs bounded to available price/PIT dates."""

    def __init__(self, repository: Any, segments: dict[str, tuple[Any, ...]], preflight: pd.DataFrame):
        self.repository = repository
        self.segments = segments
        self.meta = {str(row["ticker"]).zfill(6): row for row in preflight.to_dict("records")}
        self.audit: dict[str, dict[str, Any]] = {}

    def load(self, ticker: str) -> pd.DataFrame | None:
        ticker = str(ticker).zfill(6)
        meta = self.meta.get(ticker)
        if meta is None or meta.get("adjusted_first_date") in (None, "") or meta.get("adjusted_last_date") in (None, ""):
            self.audit[ticker] = {"ticker": ticker, "load_status": "ADJUSTED_FILE_UNAVAILABLE"}
            return None
        first = max(pd.Timestamp(meta["adjusted_first_date"]).normalize(), min(seg.effective_from for seg in self.segments[ticker]))
        last = SUPPORT
        if first > last:
            self.audit[ticker] = {"ticker": ticker, "load_status": "EMPTY_BOUNDED_RANGE", "bounded_start": first.strftime("%Y-%m-%d"), "bounded_end": last.strftime("%Y-%m-%d")}
            return None
        try:
            daily = self.repository.get_daily(ticker, first.strftime("%Y-%m-%d"), last.strftime("%Y-%m-%d"))
        except Exception as exc:
            self.audit[ticker] = {"ticker": ticker, "load_status": "ERROR", "first_error": f"{type(exc).__name__}:{str(exc)[:250]}", "bounded_start": first.strftime("%Y-%m-%d"), "bounded_end": last.strftime("%Y-%m-%d")}
            return None
        if daily is None or daily.empty:
            self.audit[ticker] = {"ticker": ticker, "load_status": "EMPTY", "bounded_start": first.strftime("%Y-%m-%d"), "bounded_end": last.strftime("%Y-%m-%d")}
            return None
        projection = daily.attrs.get("session_projection_audit", {})
        self.audit[ticker] = {
            "ticker": ticker,
            "load_status": "AVAILABLE",
            "bounded_start": first.strftime("%Y-%m-%d"),
            "bounded_end": last.strftime("%Y-%m-%d"),
            "repository_v2_rows": int(len(daily)),
            "repository_v2_first_date": daily.index.min().strftime("%Y-%m-%d"),
            "repository_v2_last_date": daily.index.max().strftime("%Y-%m-%d"),
            "adjusted_file_sha256": meta.get("adjusted_file_sha256"),
            "adjusted_only_count": len(projection.get("adjusted_only_dates", ())),
            "unexplained_adjusted_only_count": len(projection.get("unexplained_adjusted_only_dates", ())),
            "raw_only_count": len(projection.get("raw_only_dates", ())),
            "rejected_raw_only_count": len(projection.get("rejected_raw_only_dates", ())),
            "silent_inner_drop_count": int(projection.get("silent_inner_drop_count", 0) or 0),
            "unexplained_adjusted_only_dates": ";".join(pd.Timestamp(day).strftime("%Y-%m-%d") for day in projection.get("unexplained_adjusted_only_dates", ())),
            "rejected_raw_only_dates": ";".join(pd.Timestamp(day).strftime("%Y-%m-%d") for day in projection.get("rejected_raw_only_dates", ())),
        }
        # Match RepositoryV2DailyLoader's consumer contract: retaining the
        # full row-level projection audit in DataFrame.attrs makes pandas
        # propagate/deep-copy megabytes of metadata through every weekly and
        # monthly aggregation in the frozen V2 evaluator.
        daily = daily.copy()
        daily.attrs = {
            "data_authority": "MarketDataRepositoryV2",
            "session_projection_summary": {
                "adjusted_only_count": len(projection.get("adjusted_only_dates", ())),
                "raw_only_count": len(projection.get("raw_only_dates", ())),
                "explicit_exclusion_count": sum(
                    int(projection.get(key, 0) or 0)
                    for key in (
                        "explicit_placeholder_projection_count",
                        "explicit_known_gap_exclusion_count",
                        "explicit_outside_identity_lifecycle_exclusion_count",
                        "explicit_adjusted_source_nonusable_exclusion_count",
                        "explicit_analytic_invalid_exclusion_count",
                    )
                ),
                "silent_inner_drop_count": int(projection.get("silent_inner_drop_count", 0) or 0),
            },
            "requested_start": first.strftime("%Y-%m-%d"),
            "requested_end": last.strftime("%Y-%m-%d"),
            "effective_as_of": daily.index.max().strftime("%Y-%m-%d"),
        }
        return daily


def make_portfolio_context(engine: Any, calendar: Any, segments: dict[str, tuple[Any, ...]], repository: Any) -> Any:
    portfolio = engine.portfolio
    run = SimpleNamespace(
        window=SimpleNamespace(window_id="P2-2", effective_start=EVAL_START, effective_end=CUTOFF, execution_support=SUPPORT),
        calendar=calendar,
        loader=RepositoryV2DailyLoader(repository, end=SUPPORT),
        segments_by_ticker=segments,
        lifecycle_settlements=(),
    )
    return portfolio.WindowContext(
        window_id="P2-2", run=run, source_rows=[], source_details={}, data_frames={}, frame_hashes={},
        segment_by_key={}, typed_lifecycle_by_id={}, legacy_lifecycle=(),
        raw_store=KrxRawStockStore(ROOT / "data/market/raw/krx_stocks/v01"), raw_partition_cache={},
    )


def install_bounded_portfolio_loader(engine: Any, preflight: pd.DataFrame) -> None:
    portfolio = engine.portfolio
    meta = {str(row["ticker"]).zfill(6): row for row in preflight.to_dict("records")}

    def bounded_frame(ctx: Any, key: tuple[str, str, str, str, str]):
        ticker, isu, _market, _start, _end = key
        ticker = str(ticker).zfill(6)
        row = meta.get(ticker)
        segment = ctx.segment_by_key.get(key) or portfolio.find_segment(ctx.run, key)
        if row is None or segment is None or segment.isu_cd.strip().upper() != str(isu).strip().upper():
            raise RuntimeError(f"P2_PORTFOLIO_EXACT_PIT_OR_PRICE_METADATA_MISSING:{key}")
        start = max(pd.Timestamp(row["adjusted_first_date"]).normalize(), segment.effective_from, EVAL_START)
        end = SUPPORT
        if start > end:
            raise RuntimeError(f"P2_PORTFOLIO_EMPTY_BOUNDED_RANGE:{ticker}:{start}:{end}")
        loader = RepositoryV2DailyLoader(ctx.run.loader.repository, start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))
        daily = loader.load(ticker)
        if daily is None or daily.empty:
            raise RuntimeError(f"P2_PORTFOLIO_PRICE_UNAVAILABLE:{ticker}:{isu}:{start}:{end}")
        daily = daily.sort_index()
        if daily.index.has_duplicates or not daily.index.is_monotonic_increasing:
            raise RuntimeError(f"P2_PORTFOLIO_DAILY_INDEX_INVALID:{ticker}")
        daily = daily.loc[:, ["open", "high", "low", "close"]].copy()
        return daily, portfolio.canonical_frame_hash(daily)

    portfolio._load_identity_frame_uncached = bounded_frame


def write_group_outputs(prefix: str, group: str, result: dict[str, Any]) -> None:
    stem = f"{prefix}{group.lower()}"
    for field, suffix in (
        ("events", "portfolio_events"), ("daily_equity", "daily_equity"),
        ("cash_events", "cash_events"), ("valuation_carry_audit", "valuation_audit"),
        ("missing_marks", "missing_marks"),
        ("issues", "issues"), ("unresolved_trade_events", "unresolved_trade_events"),
        ("lifecycle_diagnostics", "lifecycle_diagnostics"),
    ):
        pd.DataFrame(result[field]).to_csv(OUT / f"{stem}_{suffix}.csv", index=False)
    skipped = [row for row in result["events"] if str(row.get("event_status", "")).startswith("SKIPPED")]
    pd.DataFrame(skipped).to_csv(OUT / f"{stem}_skipped_entries.csv", index=False)


def run_group(engine: Any, calendar: Any, segments: dict[str, tuple[Any, ...]], repository: Any, rows: list[dict[str, Any]]) -> dict[str, Any]:
    ctx = make_portfolio_context(engine, calendar, segments, repository)
    scoped, issues = engine.portfolio.scope_streams(ctx, rows, CUTOFF)
    scoped_count = sum(len(items) for items in scoped.values())
    if scoped_count != len(rows):
        raise RuntimeError(f"P2_PORTFOLIO_SCOPE_ROW_COUNT_MISMATCH:{scoped_count}:{len(rows)}")
    result = engine.portfolio.portfolio_replay(ctx, scoped, issues)
    result["metrics"].update(engine.observed_nav_metrics(result["daily_equity"], result["missing_marks"]))
    result["scope_issues"] = issues
    return result


def evaluate_tickers(engine: Any, tickers: list[str], loader: BoundedRepositoryLoader, calendar: Any, segments: dict[str, tuple[Any, ...]], score: dict[str, Any], stage: dict[str, Any], mcap: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    engine.install_per_ticker_evaluation_cache()
    outcomes: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    def work(ticker: str) -> dict[str, Any]:
        return engine.evaluator_rows_for_ticker(ticker, loader=loader, calendar=calendar, segments_by_ticker=segments, score_contract=score, stage_contract=stage, mcap_resolver=mcap)

    with ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="p2-2-v2-eval") as pool:
        future_to_ticker = {pool.submit(work, ticker): ticker for ticker in tickers}
        for done, future in enumerate(as_completed(future_to_ticker), start=1):
            ticker = future_to_ticker[future]
            try:
                outcome = future.result()
            except Exception as exc:
                errors.append({"ticker": ticker, "worker_error": f"{type(exc).__name__}:{str(exc)[:400]}"})
                outcome = {"ticker": ticker, "data_status": "WORKER_ERROR", "errors": [errors[-1]["worker_error"]], "control_trades": [], "candidate_trades": [], "audits": []}
            outcomes.append(outcome)
            if done % 100 == 0 or done == len(tickers):
                print(f"signal evaluation progress: {done}/{len(tickers)}", flush=True)
    outcomes.sort(key=lambda row: str(row.get("ticker", "")))
    errors.sort(key=lambda row: row["ticker"])
    return outcomes, errors


def main() -> int:
    mode = "FULL" if "--full" in sys.argv else "SAMPLE"
    started = time.perf_counter()
    cpu_started = time.process_time()
    OUT.mkdir(parents=True, exist_ok=True)
    preflight = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    if preflight.get("preflight_status") != "PASS":
        raise RuntimeError(f"P2_PREFLIGHT_NOT_PASS:{preflight.get('preflight_status')}")
    frozen_manifest = json.loads((OUT / "source_manifest.json").read_text(encoding="utf-8"))
    expected_manifest_status = "FROZEN_BEFORE_SAMPLE" if mode == "SAMPLE" else "FROZEN_BEFORE_FULL"
    if frozen_manifest.get("status") != expected_manifest_status:
        raise RuntimeError(f"P2_SOURCE_MANIFEST_STATUS_NOT_{expected_manifest_status}")
    for source in frozen_manifest.get("files", []):
        path = Path(source["absolute_path"]) if source.get("absolute_path") else ROOT / source["path"]
        if not path.is_file() or sha(path) != source.get("sha256") or path.stat().st_size != int(source.get("bytes", -1)):
            raise RuntimeError(f"P2_FROZEN_SOURCE_CHANGED:{source.get('path')}")
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    origin = subprocess.check_output(["git", "rev-parse", "origin/main"], cwd=ROOT, text=True).strip()
    if branch != "main" or head != origin or head != preflight["baseline"]["head"]:
        raise RuntimeError(f"P2_BASELINE_CHANGED_AFTER_PREFLIGHT:{branch}:{head}:{origin}")

    engine = load_engine()
    authority_started = time.perf_counter()
    calendar, _pit_payload, _calendar_payload, segments = engine.build_authority()
    authority_seconds = time.perf_counter() - authority_started
    eligible = sorted(segments)
    if len(eligible) != int(preflight["universe"]["eligible_tickers_after_exclusions"]):
        raise RuntimeError(f"P2_UNIVERSE_TICKER_COUNT_CHANGED:{len(eligible)}")
    if mode == "SAMPLE":
        selection = json.loads(SAMPLE_SELECTION.read_text(encoding="utf-8"))
        tickers = list(selection["tickers"])
        if len(tickers) < 20 or not set(tickers) <= set(eligible):
            raise RuntimeError(f"P2_SAMPLE_SELECTION_INVALID:{len(tickers)}")
    else:
        sample_validation_path = OUT / "sample_validation.json"
        sample_benchmark_path = OUT / "sample_benchmark.json"
        if not sample_validation_path.is_file() or not sample_benchmark_path.is_file():
            raise RuntimeError("P2_V02_REUSED_SAMPLE_EVIDENCE_MISSING; FULL_RUN_NOT_STARTED")
        sample_validation = json.loads(sample_validation_path.read_text(encoding="utf-8"))
        sample_benchmark = json.loads(sample_benchmark_path.read_text(encoding="utf-8"))
        allowed_coverage_only_failure = "control_nav_coverage_at_least_90_percent"
        failed_checks = sorted(key for key, value in sample_validation.get("checks", {}).items() if value is not True)
        if sample_validation.get("status") != "CHECK_REQUIRED" or failed_checks != [allowed_coverage_only_failure]:
            raise RuntimeError(f"P2_V02_SAMPLE_HAS_OTHER_FAILED_CHECKS:{failed_checks}; FULL_RUN_NOT_STARTED")
        sample_ok = (
            sample_benchmark.get("status") == "SAMPLE_COMPLETED"
            and int(sample_benchmark.get("evaluated_ticker_count", -1)) == int(sample_benchmark.get("sample_ticker_count", -2))
            and int(sample_benchmark.get("available_price_ticker_count", -1)) == int(sample_benchmark.get("evaluated_ticker_count", -2))
            and int(sample_benchmark.get("worker_error_count", -1)) == 0
            and int(sample_benchmark.get("workers", -1)) == WORKERS
            and float(sample_benchmark.get("estimated_full_wall_seconds", float("inf"))) < 7200
            and bool(sample_benchmark.get("full_run_authorized_by_sample_contract"))
        )
        if not sample_ok:
            raise RuntimeError("P2_V02_REUSED_SAMPLE_PERFORMANCE_OR_INTEGRITY_GATE_FAILED; FULL_RUN_NOT_STARTED")
        tickers = eligible

    preflight_prices = pd.read_csv(OUT / "identity_price_preflight.csv", dtype=str, keep_default_na=False)
    repository_started = time.perf_counter()
    repository = build_repository_v2(ROOT, end=SUPPORT)
    loader = BoundedRepositoryLoader(repository, segments, preflight_prices)
    mcap = engine.ExactSignalMcap()
    repository_setup_seconds = time.perf_counter() - repository_started
    score = json.loads(engine.SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    stage = json.loads(engine.STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))

    print(f"Starting P2-2 {mode}: {len(tickers)} tickers / workers={WORKERS}", flush=True)
    evaluation_started = time.perf_counter()
    outcomes, worker_errors = evaluate_tickers(engine, tickers, loader, calendar, segments, score, stage, mcap)
    evaluation_seconds = time.perf_counter() - evaluation_started
    control_rows = [row for result in outcomes for row in result.get("control_trades", [])]
    candidate_rows = [row for result in outcomes for row in result.get("candidate_trades", [])]
    audits = [row for result in outcomes for row in result.get("audits", [])]
    audits.sort(key=lambda row: (str(row.get("signal_date", "")), str(row.get("ticker", "")), str(row.get("isu_cd") or "")))
    control_rows.sort(key=lambda row: (row["entry_execution_date"], row["ticker"], row["isu_cd"], row["entry_signal_date"], row["trade_id"]))
    candidate_rows.sort(key=lambda row: (row["entry_execution_date"], row["ticker"], row["isu_cd"], row["entry_signal_date"], row["trade_id"]))

    prefix = "sample_" if mode == "SAMPLE" else ""
    pd.DataFrame(control_rows).to_csv(OUT / f"{prefix}control_trades.csv", index=False)
    pd.DataFrame(candidate_rows).to_csv(OUT / f"{prefix}candidate_trades.csv", index=False)
    pd.DataFrame(audits).to_csv(OUT / f"{prefix}candidate_signal_filter_audit.csv", index=False)
    pd.DataFrame(worker_errors).to_csv(OUT / f"{prefix}worker_errors.csv", index=False)
    pd.DataFrame([{**row, **loader.audit.get(str(row.get("ticker", "")).zfill(6), {})} for row in outcomes]).to_csv(OUT / f"{prefix}ticker_price_source_audit.csv", index=False)

    if worker_errors:
        summary = {"mode": mode, "status": "INCOMPLETE_WORKER_ERRORS", "workers": WORKERS, "worker_errors": worker_errors, "outcome_count": len(outcomes), "trade_rows_saved": True}
        write_json(OUT / f"{prefix}execution_summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
        return 2

    control_seconds_started = time.perf_counter()
    install_bounded_portfolio_loader(engine, preflight_prices)
    control = run_group(engine, calendar, segments, repository, control_rows)
    control_seconds = time.perf_counter() - control_seconds_started
    candidate_seconds_started = time.perf_counter()
    candidate = run_group(engine, calendar, segments, repository, candidate_rows)
    candidate_seconds = time.perf_counter() - candidate_seconds_started
    for group, result in (("control", control), ("candidate", candidate)):
        write_group_outputs(prefix, group, result)

    if mode == "FULL":
        partition_rows = []
        for (market, day), (manifest_row, _rows, error) in sorted(mcap.cache.items()):
            partition_rows.append({"market": market, "partition_date": day, "status": None if manifest_row is None else manifest_row.get("status"), "file_path": None if manifest_row is None else manifest_row.get("file_path"), "file_sha256": None if manifest_row is None else manifest_row.get("file_sha256"), "content_sha256": None if manifest_row is None else manifest_row.get("content_sha256"), "resolution_error": error})
        pd.DataFrame(partition_rows).to_csv(OUT / "signal_date_krx_partition_hashes.csv", index=False)
        price_rows = [{"ticker": row["ticker"], "path": f"data/market/adjusted/stocks/{row['ticker']}.parquet", "sha256": row.get("adjusted_file_sha256")} for row in preflight_prices.to_dict("records")]
        pd.DataFrame(price_rows).to_csv(OUT / "repository_v2_adjusted_price_file_hashes.csv", index=False)

    wall = time.perf_counter() - started
    rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_mb = rss_bytes / (1024 * 1024)
    cpu = time.process_time() - cpu_started
    samples = max(1, math.ceil(len(tickers) / WORKERS))
    all_batches = max(1, math.ceil(len(eligible) / WORKERS))
    estimated_eval = evaluation_seconds * all_batches / samples if mode == "SAMPLE" else evaluation_seconds
    portfolio_scale = max(1.0, len(eligible) / max(1, len(tickers))) if mode == "SAMPLE" else 1.0
    estimated_portfolio = (control_seconds + candidate_seconds) * portfolio_scale
    estimated_wall = authority_seconds + repository_setup_seconds + estimated_eval + estimated_portfolio if mode == "SAMPLE" else wall
    counts = pd.Series([row.get("candidate_status") for row in audits], dtype="string").value_counts().sort_index().to_dict()
    available_count = sum(row.get("data_status") == "AVAILABLE" for row in outcomes)
    benchmark = {
        "schema": "fast_core_v2_alignment_500b_p2_2_execution_v01", "mode": mode,
        "status": "SAMPLE_COMPLETED" if mode == "SAMPLE" else "FULL_COMPLETED",
        "sample_ticker_count": len(tickers) if mode == "SAMPLE" else None,
        "evaluated_ticker_count": len(outcomes), "eligible_universe_ticker_count": len(eligible),
        "available_price_ticker_count": available_count, "worker_error_count": len(worker_errors), "workers": WORKERS,
        "authority_setup_seconds": round(authority_seconds, 3), "repository_setup_seconds": round(repository_setup_seconds, 3),
        "signal_generation_seconds": round(evaluation_seconds, 3), "control_portfolio_replay_seconds": round(control_seconds, 3),
        "candidate_portfolio_replay_seconds": round(candidate_seconds, 3), "wall_seconds_including_portfolio_replays": round(wall, 3),
        "cpu_seconds": round(cpu, 3), "max_rss_mb": round(rss_mb, 2),
        "control_signal_trade_count": len(control_rows), "candidate_signal_trade_count": len(candidate_rows),
        "candidate_signal_filter_audit_count": len(audits), "candidate_filter_status_counts": counts,
        "frozen_weekly_evaluation_cache_hits": sum(int(row.get("evaluation_cache_hits", 0) or 0) for row in outcomes),
        "frozen_weekly_evaluation_cache_misses": sum(int(row.get("evaluation_cache_misses", 0) or 0) for row in outcomes),
        "loaded_exact_signal_date_mcap_partitions": len(mcap.cache), "control_metrics": control["metrics"], "candidate_metrics": candidate["metrics"],
        "scope_issue_counts": {"CONTROL": len(control.get("scope_issues", [])), "ALIGNMENT_MCAP_500B": len(candidate.get("scope_issues", []))},
        "portfolio_replay_workers": 1, "support_day_exit_only": True, "support_day_in_cutoff_nav": False,
        "estimated_full_evaluation_seconds": round(estimated_eval, 3),
        "estimated_full_portfolio_seconds_conservative_linear": round(estimated_portfolio, 3),
        "estimated_full_wall_seconds": round(estimated_wall, 3), "estimated_full_wall_hours": round(estimated_wall / 3600, 4),
        "source_input_status_counts": pd.Series([loader.audit.get(t, {}).get("load_status", "NOT_LOADED") for t in tickers], dtype="string").value_counts().sort_index().to_dict(),
        "full_run_authorized_by_sample_contract": bool(
            (mode == "SAMPLE" and not worker_errors and available_count == len(outcomes) and len(control.get("scope_issues", [])) == 0 and len(candidate.get("scope_issues", [])) == 0 and estimated_wall <= 7200)
            or (mode == "FULL" and json.loads((OUT / "sample_benchmark.json").read_text(encoding="utf-8")).get("full_run_authorized_by_sample_contract") is True)
        ),
        "sample_gate_override_policy": "V02 full-run authorization ignores only control_nav_coverage_at_least_90_percent from the reused representative sample; official full-run E below 90 percent remains CHECK_REQUIRED.",
        "sample_gate_override_used": mode == "FULL",
        "sample_gate_failed_checks": ["control_nav_coverage_at_least_90_percent"] if mode == "FULL" else [],
        "signal_evaluation_run_count": 1 if mode == "FULL" else 0,
        "automatic_full_run_retry": False,
    }
    output = OUT / ("sample_benchmark.json" if mode == "SAMPLE" else "full_run_execution.json")
    write_json(output, benchmark)
    print(json.dumps({k: benchmark[k] for k in ("mode", "status", "evaluated_ticker_count", "eligible_universe_ticker_count", "workers", "control_signal_trade_count", "candidate_signal_trade_count", "candidate_filter_status_counts", "wall_seconds_including_portfolio_replays", "cpu_seconds", "max_rss_mb", "estimated_full_wall_hours", "full_run_authorized_by_sample_contract")}, ensure_ascii=False, indent=2, default=json_default), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
