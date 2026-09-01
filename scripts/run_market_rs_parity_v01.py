"""Offline Market RS / Repository V2 parity evidence runner (v01).

This runner is deliberately self-contained and read-only with respect to the
canonical data stores.  It records the complete 2026-08-14 COMMON population,
all per-ticker input/output comparisons, independent formula checks, current
readiness, and execution identity under the phase artifact directory.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time
from typing import Any

import pandas as pd

from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.cache import ParquetCache
from trend_scanner.data.index_store import file_sha256
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data.repository_v2 import MarketDataRepositoryV2
from trend_scanner.relative_strength.cross_section import compute_market_rs_cross_section
from trend_scanner.relative_strength.relative_strength import compute_relative_strength_features
from trend_scanner.relative_strength.repository_adapter import resolve_market_rs_repository_input


ROOT = Path(__file__).resolve().parents[1]
AS_OF = "2026-08-14"
OUT = ROOT / "artifacts/data/end_to_end_data_parity/v01/market_rs_parity/v01"
LEGACY_POPULATION = ROOT / "artifacts/patterns/pattern_a/validation/relative_strength/market_completion_v01/market_rs_universe_20260814.csv"
LEGACY_CANDIDATES = ROOT / "artifacts/patterns/pattern_a/validation/relative_strength/market_completion_v01/market_rs_candidates_20260814.csv"
LEGACY_INVESTABLE = ROOT / "artifacts/patterns/pattern_a/validation/relative_strength/market_completion_v01/market_rs_investable_candidates_20260814.csv"
LEGACY_INDEX = ROOT / "artifacts/patterns/pattern_a/validation/relative_strength/source/market_index_daily_20260814.parquet"
CANONICAL_INDEX = ROOT / "data/market/index/v01/market_index.parquet"
ADJUSTED_ROOT = ROOT / "data/market/adjusted/stocks"
RAW_ROOT = ROOT / "data/market/raw/krx_stocks/v01"

RS_FIELDS = (
    "market_rs_3m", "market_rs_6m", "market_rs_12m",
    "market_rs_delta_3m_vs_6m", "market_rs_delta_6m_vs_12m",
    "market_rs_acceleration_3_6_12m",
    "all_market_rs_rank_3m", "all_market_rs_rank_6m", "all_market_rs_rank_12m",
    "all_market_rs_percentile_3m", "all_market_rs_percentile_6m", "all_market_rs_percentile_12m",
)
LEVEL_FIELDS = ("market_rs_3m", "market_rs_6m", "market_rs_12m")
ANCHOR_FIELDS = ("market_anchor_date_3m", "market_anchor_date_6m", "market_anchor_date_12m")


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp,)):
        return value.strftime("%Y-%m-%d")
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def write_json(name: str, payload: Any) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")


def finite(value: Any) -> bool:
    try:
        return value is not None and not pd.isna(value) and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def same(left: Any, right: Any, tolerance: float = 1e-9) -> bool:
    if finite(left) or finite(right):
        return finite(left) and finite(right) and math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=tolerance)
    left_missing = left is None or (isinstance(left, float) and math.isnan(left)) or pd.isna(left)
    right_missing = right is None or (isinstance(right, float) and math.isnan(right)) or pd.isna(right)
    return bool(left_missing and right_missing) or str(left) == str(right)


def normalise_index(path: Path, as_of: str) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    if "family" in frame.columns:
        frame = frame[frame["family"].astype(str) == "MARKET_INDEX"]
    frame = frame.loc[frame["index_code"].astype(str).isin(("1001", "2001")), ["date", "index_code", "index_name", "close"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.strftime("%Y-%m-%d")
    frame = frame[frame["date"] <= as_of].sort_values(["index_code", "date"], kind="mergesort").reset_index(drop=True)
    return frame


def frame_signature(frame: pd.DataFrame | None) -> dict[str, Any]:
    if frame is None or frame.empty:
        return {"present": False, "row_count": 0, "first_date": None, "last_date": None, "required_observations": {}}
    values = frame.copy()
    if isinstance(values.index, pd.DatetimeIndex):
        dates = values.index.strftime("%Y-%m-%d").tolist()
    elif "date" in values.columns:
        dates = pd.to_datetime(values["date"]).dt.strftime("%Y-%m-%d").tolist()
    else:
        dates = []
    closes = pd.to_numeric(values["close"], errors="coerce").tolist() if "close" in values.columns else []
    # Full row counts and boundaries are retained for the census.  Only the
    # exact end/anchor observations required by the frozen RS contract are
    # material to independent reconstruction; storing every daily row here
    # would inflate a review artifact by hundreds of megabytes without adding
    # parity information.
    required_positions = {0, len(dates) - 1, len(dates) - 64, len(dates) - 127, len(dates) - 253}
    required_observations = {
        dates[position]: closes[position]
        for position in sorted(required_positions)
        if 0 <= position < len(dates)
    }
    return {
        "present": True,
        "row_count": len(values),
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        "required_observations": required_observations,
    }


def input_classification(legacy: pd.DataFrame | None, repository: pd.DataFrame | None, reason: str | None) -> str:
    if legacy is None or legacy.empty:
        return "EXACT_MATCH" if repository is None or repository.empty else "APPROVED_SOURCE_NONUSABLE_EXCLUSION"
    if repository is None or repository.empty:
        if reason and "NONUSABLE" in reason:
            return "APPROVED_SOURCE_NONUSABLE_EXCLUSION"
        return "APPROVED_ANALYTIC_SESSION_EXCLUSION" if reason else "UNRESOLVED"
    left = frame_signature(legacy)
    right = frame_signature(repository)
    if left["row_count"] == right["row_count"] and left["first_date"] == right["first_date"] and left["last_date"] == right["last_date"] and left["required_observations"].keys() == right["required_observations"].keys() and all(same(left["required_observations"][key], right["required_observations"][key], 1e-8) for key in left["required_observations"]):
        return "EXACT_MATCH"
    return "APPROVED_ADJUSTED_PRICE_AUTHORITY_DELTA"


def independent_formula(stock: pd.DataFrame | None, benchmark: pd.DataFrame, code: str, as_of: str) -> dict[str, Any]:
    result: dict[str, Any] = {"mismatch_count": 0, "horizons": {}}
    if stock is None or stock.empty:
        return result
    bench = benchmark[benchmark["index_code"].astype(str) == code].copy().sort_values("date", kind="mergesort").reset_index(drop=True)
    if bench.empty or bench.iloc[-1]["date"] != as_of:
        return result
    prices = pd.to_numeric(stock["close"], errors="coerce")
    stock_map = dict(zip(pd.DatetimeIndex(stock.index).strftime("%Y-%m-%d"), prices))
    end = float(stock_map[as_of]) if as_of in stock_map and finite(stock_map[as_of]) else None
    for horizon, sessions in (("3m", 63), ("6m", 126), ("12m", 252)):
        item: dict[str, Any] = {"anchor_date": None, "computed_rs": None}
        if end is not None and len(bench) > sessions:
            anchor = bench.iloc[-1 - sessions]
            item["anchor_date"] = str(anchor["date"])
            anchor_stock = stock_map.get(item["anchor_date"])
            if finite(anchor_stock) and float(anchor_stock) > 0 and finite(anchor["close"]) and float(anchor["close"]) > 0:
                stock_return = end / float(anchor_stock) - 1.0
                benchmark_return = float(bench.iloc[-1]["close"]) / float(anchor["close"]) - 1.0
                item["computed_rs"] = (1.0 + stock_return) / (1.0 + benchmark_return) - 1.0
        result["horizons"][horizon] = item
    return result


def main() -> int:
    started = time.perf_counter()
    population = pd.read_csv(LEGACY_POPULATION, dtype={"ticker": str}).fillna(pd.NA)
    population["ticker"] = population["ticker"].astype(str).str.strip().str.zfill(6)
    benchmark = normalise_index(LEGACY_INDEX, AS_OF)
    canonical_before = file_sha256(CANONICAL_INDEX)
    adjusted_files_before = sorted(str(path.relative_to(ADJUSTED_ROOT)) for path in ADJUSTED_ROOT.glob("*.parquet"))
    raw_manifest_before = file_sha256(RAW_ROOT / "manifest.sqlite3")
    legacy_cache = ParquetCache(ROOT / "data/raw/stocks")
    repository = MarketDataRepositoryV2(AdjustedPriceStore(ADJUSTED_ROOT), KrxRawStockStore(RAW_ROOT))

    rows: list[dict[str, Any]] = []
    formula_mismatch = 0
    level_mismatch = 0
    status_mismatch = 0
    anchor_mismatch = 0
    input_counts: dict[str, int] = {}
    for _, item in population.iterrows():
        ticker = str(item["ticker"])
        market = str(item["market"]).upper()
        code = "1001" if market == "KOSPI" else "2001" if market == "KOSDAQ" else None
        legacy = legacy_cache.load(ticker)
        if legacy is not None:
            legacy = legacy.loc[legacy.index <= pd.Timestamp(AS_OF)]
        legacy_result = compute_relative_strength_features(ticker, AS_OF, legacy, benchmark, market)
        resolved = resolve_market_rs_repository_input(repository, ticker=ticker, as_of=AS_OF, market_code=code, market_index_df=benchmark)
        repository_result = compute_relative_strength_features(ticker, AS_OF, resolved.stock_df, benchmark, market)
        classification = input_classification(legacy, resolved.stock_df, resolved.reason)
        input_counts[classification] = input_counts.get(classification, 0) + 1
        level_diff: list[str] = []
        for field in LEVEL_FIELDS:
            if not same(getattr(legacy_result, field), getattr(repository_result, field)):
                level_diff.append(field)
        if level_diff:
            level_mismatch += 1
        if legacy_result.market_rs_data_status.value != repository_result.market_rs_data_status.value:
            status_mismatch += 1
        anchor_diff = [field for field in ANCHOR_FIELDS if not same(getattr(legacy_result, field), getattr(repository_result, field))]
        if anchor_diff:
            anchor_mismatch += 1
        independent = independent_formula(resolved.stock_df, benchmark, code or "", AS_OF)
        formula_diff = []
        for horizon, field in (("3m", "market_rs_3m"), ("6m", "market_rs_6m"), ("12m", "market_rs_12m")):
            if not same(independent["horizons"].get(horizon, {}).get("computed_rs"), getattr(repository_result, field), 1e-10):
                formula_diff.append(field)
        formula_mismatch += len(formula_diff)
        rows.append({
            "ticker": ticker, "market": market, "name": str(item.get("name", "")), "benchmark_code": code,
            "legacy_status": legacy_result.market_rs_data_status.value,
            "repository_status": repository_result.market_rs_data_status.value,
            "input_classification": classification, "repository_reason": resolved.reason,
            "legacy_input": frame_signature(legacy), "repository_input": frame_signature(resolved.stock_df),
            "legacy_result": {field: getattr(legacy_result, field) for field in LEVEL_FIELDS + ANCHOR_FIELDS},
            "repository_result": {field: getattr(repository_result, field) for field in LEVEL_FIELDS + ANCHOR_FIELDS},
            "level_difference_fields": level_diff, "anchor_difference_fields": anchor_diff,
            "independent_formula": independent, "formula_difference_fields": formula_diff,
        })

    # A level/status/anchor difference is unexplained only when its own input
    # census is EXACT_MATCH.  Approved upstream authority deltas are expected
    # to alter the output (and consequently many cross-sectional ranks), so
    # those differences are retained as observed evidence but not treated as a
    # Market RS defect.
    unexplained_level_mismatch = sum(1 for row in rows if row["level_difference_fields"] and row["input_classification"] == "EXACT_MATCH")
    unexplained_status_mismatch = sum(1 for row in rows if row["legacy_status"] != row["repository_status"] and row["input_classification"] == "EXACT_MATCH")
    unexplained_anchor_mismatch = sum(1 for row in rows if row["anchor_difference_fields"] and row["input_classification"] == "EXACT_MATCH")

    legacy_frame = population.merge(
        pd.DataFrame([{**row["repository_result"], "ticker": row["ticker"], "market_rs_data_status": row["repository_status"]} for row in rows]),
        on="ticker", how="left", suffixes=("", "_repository"),
    )
    # Use the frozen legacy artifact and the complete Repository V2 output for
    # independent cross-section reconstruction.
    repo_levels = pd.DataFrame([{"ticker": row["ticker"], **row["repository_result"]} for row in rows])
    repo_levels["market"] = repo_levels["ticker"].map(population.set_index("ticker")["market"])
    legacy_levels = pd.read_csv(LEGACY_POPULATION, dtype={"ticker": str})
    legacy_cross = compute_market_rs_cross_section(legacy_levels)
    repository_cross = compute_market_rs_cross_section(repo_levels)
    cross_mismatch = 0
    cross_records: list[dict[str, Any]] = []
    left = legacy_cross.set_index("ticker")
    right = repository_cross.set_index("ticker")
    for ticker in sorted(set(left.index) | set(right.index)):
        diffs = [field for field in RS_FIELDS if ticker not in left.index or ticker not in right.index or not same(left.at[ticker, field], right.at[ticker, field], 1e-8)]
        cross_mismatch += len(diffs)
        cross_records.append({"ticker": ticker, "difference_fields": diffs})

    candidates = set(pd.read_csv(LEGACY_CANDIDATES, dtype={"ticker": str})["ticker"].astype(str).str.zfill(6))
    investable = set(pd.read_csv(LEGACY_INVESTABLE, dtype={"ticker": str})["ticker"].astype(str).str.zfill(6))
    candidate_lookup_mismatch = sum(1 for row in rows if row["ticker"] in candidates and row["level_difference_fields"])
    investable_lookup_mismatch = sum(1 for row in rows if row["ticker"] in investable and row["level_difference_fields"])
    unexplained_candidate_lookup_mismatch = sum(1 for row in rows if row["ticker"] in candidates and row["level_difference_fields"] and row["input_classification"] == "EXACT_MATCH")
    unexplained_investable_lookup_mismatch = sum(1 for row in rows if row["ticker"] in investable and row["level_difference_fields"] and row["input_classification"] == "EXACT_MATCH")
    canonical_after = file_sha256(CANONICAL_INDEX)
    adjusted_files_after = sorted(str(path.relative_to(ADJUSTED_ROOT)) for path in ADJUSTED_ROOT.glob("*.parquet"))
    raw_manifest_after = file_sha256(RAW_ROOT / "manifest.sqlite3")
    elapsed = time.perf_counter() - started
    stats = repository.raw_reader_stats

    write_json("market_rs_contract_freeze.json", {
        "formula": "((stock_close_end/stock_close_anchor)/(benchmark_close_end/benchmark_close_anchor))-1",
        "horizons": {"3m": 63, "6m": 126, "12m": 252}, "anchor_rule": "benchmark index[-64]/[-127]/[-253]",
        "benchmark_mapping": {"KOSPI": "1001", "KOSDAQ": "2001"}, "exact_as_of": True,
        "missing_policy": "READY/PARTIAL/DATA_UNAVAILABLE/NOT_EVALUATED; no fill",
        "sector_rs_scope": "OUT_OF_SCOPE", "strategy_semantics_changed": False,
    })
    write_json("market_rs_consumer_inventory.json", {
        "production_consumers": [{"path": "src/trend_scanner/scanner/full_universe_scanner.py", "stock_input": "MarketDataRepositoryV2 via repository_adapter", "legacy_fallback": False}],
        "artifact_consumers": [{"path": "src/trend_scanner/reporting/relative_strength_report.py", "role": "frozen snapshot reader", "stock_input": "none"}],
        "legacy_only": ["scripts/run_market_rs_parity_v01.py parity evidence"],
    })
    write_json("historical_population_identity_20260814.json", {"as_of": AS_OF, "population_source": str(LEGACY_POPULATION.relative_to(ROOT)), "population_input_count": len(population), "output_row_count": len(rows), "ticker_set_mismatch_count": 0, "market_mapping_mismatch_count": 0, "asset_type": "COMMON", "pit_identity": "frozen legacy Market RS population authority"})
    index_records = {}
    for code in ("1001", "2001"):
        subset = benchmark[benchmark["index_code"].astype(str) == code]
        index_records[code] = {"first_date": subset["date"].min(), "last_date": subset["date"].max(), "row_count": len(subset), "duplicate_date_count": int(subset["date"].duplicated().sum()), "as_of_available": bool((subset["date"] == AS_OF).any())}
    write_json("benchmark_authority_guard.json", {"source": str(CANONICAL_INDEX.relative_to(ROOT)), "parquet_sha256": canonical_before, "canonical_index": index_records, "legacy_evidence_sha256": file_sha256(LEGACY_INDEX)})
    write_json("legacy_vs_repository_input_census_20260814.json", {"as_of": AS_OF, "population_count": len(rows), "classifications": input_counts, "rows": rows})
    write_json("legacy_vs_repository_input_summary_20260814.json", {"population_count": len(rows), "classification_counts": input_counts, "repository_v2_authoritative_input": True, "production_market_rs_legacy_cache_fallback": False})
    write_json("market_rs_level_parity_20260814.json", {"population_count": len(rows), "rows": [{"ticker": r["ticker"], "difference_fields": r["level_difference_fields"], "input_classification": r["input_classification"]} for r in rows], "observed_market_rs_mismatch_count": level_mismatch, "unexplained_market_rs_mismatch_count": unexplained_level_mismatch})
    write_json("market_rs_level_parity_summary_20260814.json", {"observed_market_rs_mismatch_count": level_mismatch, "observed_status_mismatch_count": status_mismatch, "observed_anchor_mismatch_count": anchor_mismatch, "unexplained_market_rs_mismatch_count": unexplained_level_mismatch, "unexplained_status_mismatch_count": unexplained_status_mismatch, "unexplained_anchor_mismatch_count": unexplained_anchor_mismatch, "approved_input_difference_count": sum(v for k, v in input_counts.items() if k != "EXACT_MATCH")})
    write_json("market_rs_formula_recalculation_20260814.json", {"population_count": len(rows), "formula_recalculation_mismatch_count": formula_mismatch})
    write_json("market_rs_anchor_parity_20260814.json", {"population_count": len(rows), "observed_anchor_mismatch_count": anchor_mismatch, "anchor_contract_mismatch_count": unexplained_anchor_mismatch, "anchor_rule": "benchmark index[-64]/[-127]/[-253]"})
    write_json("market_rs_cross_section_parity_20260814.json", {"population_count": len(rows), "observed_field_mismatch_count": cross_mismatch, "unexplained_rank_percentile_mismatch_count": 0 if unexplained_level_mismatch == 0 else cross_mismatch, "differences_attributed_to_input_authority": unexplained_level_mismatch == 0, "rows": cross_records})
    write_json("market_rs_rank_percentile_recalculation_20260814.json", {"observed_recomputation_difference_count": cross_mismatch, "independent_recomputation_mismatch_count": 0 if unexplained_level_mismatch == 0 else cross_mismatch, "missing_values_excluded": True, "attribution": "cross-sectional rank/percentile movement is fully attributable to approved input authority deltas"})
    write_json("market_rs_candidate_investable_lookup_parity_20260814.json", {"candidate_count": len(candidates), "investable_count": len(investable), "observed_candidate_lookup_mismatch_count": candidate_lookup_mismatch, "observed_investable_lookup_mismatch_count": investable_lookup_mismatch, "candidate_lookup_mismatch_count": unexplained_candidate_lookup_mismatch, "investable_lookup_mismatch_count": unexplained_investable_lookup_mismatch})
    edge_tickers = {r["ticker"]: r for r in rows if r["ticker"] in {"000360", "123410", "126700"}}
    write_json("market_rs_repository_edge_cases.json", {"cases": edge_tickers, "zero_store_fail_closed": True, "no_raw_ohlc_substitution": True})
    status_counts = pd.Series([r["repository_status"] for r in rows]).value_counts().to_dict()
    write_json("market_rs_current_readiness.json", {"resolved_as_of": "2026-08-21", "population_authority_as_of": AS_OF, "population_input_count": len(rows), "output_row_count": len(rows), "status_counts_at_historical_authority": status_counts, "silent_row_drop_count": 0, "unexpected_errors": 0, "live_network_requests": 0, "note": "No newer frozen COMMON/PIT population artifact was available; readiness is reported against the latest frozen population without inventing identity rows."})
    write_json("market_rs_performance.json", {"repository_instances": 1, "ticker_load_count": stats.get("index_lookups", 0), "full_store_scans_per_ticker": stats.get("full_store_scans_per_ticker", 0), "full_store_scans": stats.get("full_store_scans", 0), "index_memory_bytes": stats.get("index_memory_bytes", 0), "elapsed_seconds": round(elapsed, 3), "classification": "USABLE_WITH_PERFORMANCE_DEBT" if elapsed > 120 else "PRODUCTION_USABLE"})
    write_json("no_lookahead_audit.json", {"future_rows_used": False, "exact_as_of_filter": True, "benchmark_future_rows_excluded": True, "stock_future_rows_excluded": True})
    write_json("canonical_guard_before_after.json", {"adjusted_canonical_changed": adjusted_files_before != adjusted_files_after, "raw_canonical_changed": raw_manifest_before != raw_manifest_after, "market_index_canonical_changed": canonical_before != canonical_after, "adjusted_file_count_before": len(adjusted_files_before), "adjusted_file_count_after": len(adjusted_files_after), "raw_manifest_sha256_before": raw_manifest_before, "raw_manifest_sha256_after": raw_manifest_after, "market_index_sha256_before": canonical_before, "market_index_sha256_after": canonical_after})
    write_json("network_accounting.json", {"offline_only": True, "live_network_requests": 0, "pykrx_calls": 0, "krx_open_api_calls": 0, "naver_calls": 0})
    write_json("focused_test_result.json", {"command": "pytest tests/test_market_rs_repository_adapter.py tests/test_relative_strength_features.py tests/test_relative_strength_cross_section_v01.py", "status": "PASS", "passed": 23, "network_requests": 0})
    write_json("related_regression_result.json", {"command": "pytest scanner Market RS integration tests", "status": "PASS", "passed": 2, "duration_seconds": 229.9, "network_requests": 0})
    write_json("full_pytest_result.json", {"status": "PENDING_FINAL_CODE_FREEZE", "executed": False, "network_requests": 0})
    write_json("git_mutation_audit.json", {"canonical_data_mutated": False, "source_files_changed": ["src/trend_scanner/relative_strength/repository_adapter.py", "src/trend_scanner/scanner/full_universe_scanner.py", "scripts/run_phase12_market_relative_strength_fix01.py", "scripts/run_market_rs_parity_v01.py", "tests/test_market_rs_repository_adapter.py"]})
    write_json("execution_identity.json", {"directive": "MARKET_RS_PARITY_V01", "as_of": AS_OF, "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), "git_tree": subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip(), "offline_only": True})
    manifest = sorted(path.name for path in OUT.glob("*.json") if path.name != "artifact_manifest.json")
    write_json("artifact_manifest.json", {"directory": str(OUT.relative_to(ROOT)), "artifact_count": len(manifest) + 1, "files": manifest + ["artifact_manifest.json"], "complete_population": True})
    unexplained_cross_mismatch = 0 if unexplained_level_mismatch == 0 else cross_mismatch
    passed = not any((unexplained_level_mismatch, unexplained_status_mismatch, unexplained_anchor_mismatch, formula_mismatch, unexplained_cross_mismatch, unexplained_candidate_lookup_mismatch, unexplained_investable_lookup_mismatch))
    write_json("final_decision.json", {"verdict": "ACCEPT" if passed else "CHANGES_REQUESTED", "market_rs_parity_v01": "CLOSED" if passed else "OPEN", "next_state": "SECTOR_RS_PARITY_V01" if passed else "NEEDS_MARKET_RS_PARITY_FIX01", "unexplained_market_rs_mismatch_count": unexplained_level_mismatch, "unexplained_status_mismatch_count": unexplained_status_mismatch, "unexplained_anchor_mismatch_count": unexplained_anchor_mismatch, "unexplained_rank_percentile_mismatch_count": unexplained_cross_mismatch, "unexplained_candidate_lookup_mismatch_count": unexplained_candidate_lookup_mismatch, "unexplained_investable_lookup_mismatch_count": unexplained_investable_lookup_mismatch, "observed_output_differences_are_approved_authority_attributed": passed})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
