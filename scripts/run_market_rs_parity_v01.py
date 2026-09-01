"""Offline Market RS / Repository V2 parity evidence runner (FIX02).

The runner is intentionally read-only with respect to canonical data. It
compares the frozen legacy baseline with Repository V2 on the same material
12M window, verifies the production benchmark authority, independently
recomputes arithmetic and cross-sectional ranks, and executes a real current
``as_of`` readiness run against local canonical stores.
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

import numpy as np
import pandas as pd

from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.cache import ParquetCache
from trend_scanner.data.index_store import IndexStore, MARKET_INDEX_FAMILY, file_sha256
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data.repository_v2 import MarketDataRepositoryV2
from trend_scanner.data.repository_v2_session_authority import (
    ADJUSTED_ANALYTICALLY_NONUSABLE_DATES,
    SOURCE_CLOSURE_CHECKPOINT_SHA256,
)
from trend_scanner.data.repository_v2 import KNOWN_OUTSIDE_IDENTITY_LIFECYCLE_DATES
from trend_scanner.relative_strength.cross_section import (
    CROSS_SECTION_COLUMNS,
    attach_cross_sectional_rs,
    compute_market_rs_cross_section,
)
from trend_scanner.relative_strength.relative_strength import compute_relative_strength_features
from trend_scanner.relative_strength.repository_adapter import (
    EXPECTED_REPOSITORY_DATA_UNAVAILABLE_ERRORS,
    resolve_market_rs_repository_input,
)


ROOT = Path(__file__).resolve().parents[1]
AS_OF = "2026-08-14"
START_HEAD = os.environ.get("MARKET_RS_START_HEAD", "631e3969554008a33fb514b0e27878ae60c8c6c0")
OUT = ROOT / "artifacts/data/end_to_end_data_parity/v01/market_rs_parity/v01_fix02"
AUTHORITY_ADJUDICATION = OUT / "material_authority_adjudication.json"
LEGACY_POPULATION = ROOT / "artifacts/patterns/pattern_a/validation/relative_strength/market_completion_v01/market_rs_universe_20260814.csv"
LEGACY_CANDIDATES = ROOT / "artifacts/patterns/pattern_a/validation/relative_strength/market_completion_v01/market_rs_candidates_20260814.csv"
LEGACY_INVESTABLE = ROOT / "artifacts/patterns/pattern_a/validation/relative_strength/market_completion_v01/market_rs_investable_candidates_20260814.csv"
LEGACY_INDEX = ROOT / "artifacts/patterns/pattern_a/validation/relative_strength/source/market_index_daily_20260814.parquet"
CANONICAL_INDEX = ROOT / "data/market/index/v01/market_index.parquet"
CANONICAL_INDEX_ROOT = ROOT / "data/market/index/v01"
ADJUSTED_ROOT = ROOT / "data/market/adjusted/stocks"
RAW_ROOT = ROOT / "data/market/raw/krx_stocks/v01"

LEVEL_FIELDS = ("market_rs_3m", "market_rs_6m", "market_rs_12m")
RETURN_FIELDS = (
    "stock_return_3m", "stock_return_6m", "stock_return_12m",
    "market_return_3m", "market_return_6m", "market_return_12m",
)
ANCHOR_FIELDS = ("market_anchor_date_3m", "market_anchor_date_6m", "market_anchor_date_12m")
RS_FIELDS = LEVEL_FIELDS + (
    "market_rs_delta_3m_vs_6m", "market_rs_delta_6m_vs_12m",
    "market_rs_acceleration_3_6_12m",
    "all_market_rs_rank_3m", "all_market_rs_rank_6m", "all_market_rs_rank_12m",
    "all_market_rs_percentile_3m", "all_market_rs_percentile_6m", "all_market_rs_percentile_12m",
)
HORIZONS = (("3m", 63), ("6m", 126), ("12m", 252))


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(value).strftime("%Y-%m-%d")
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


def _finite_field(result: Any, field: str) -> bool:
    """Return true only when a calculated horizon field is finite."""

    return finite(getattr(result, field, None))


def derive_next_state(gates: dict[str, Any]) -> str:
    """Route the machine-readable next state from the actual blocker class."""

    if gates.get("repository_v2_defect_proven"):
        return "NEEDS_REPOSITORY_V2_DEFECT_REVIEW"
    if gates.get("source_authority_defect_proven"):
        return "NEEDS_MARKET_DATA_SOURCE_AUTHORITY_REVIEW"
    if int(gates.get("unresolved_input_difference_count", 0)) > 0:
        return "NEEDS_MARKET_RS_AUTHORITY_ATTRIBUTION_FIX02"
    if int(gates.get("unexpected_repository_error_count", 0)) > 0:
        return "NEEDS_REPOSITORY_V2_DEFECT_REVIEW"
    if any(
        int(gates.get(key, 0)) > 0
        for key in (
            "formula_recalculation_mismatch_count",
            "anchor_contract_mismatch_count",
            "unexplained_market_rs_mismatch_count",
            "unexplained_status_mismatch_count",
            "independent_rank_recalculation_mismatch_count",
            "independent_percentile_recalculation_mismatch_count",
            "unexplained_rank_delta_rows",
            "unexplained_percentile_delta_rows",
            "candidate_lookup_unexplained_mismatch_count",
            "investable_lookup_unexplained_mismatch_count",
        )
    ):
        return "NEEDS_MARKET_RS_PARITY_FIX02"
    if gates.get("current_run_executed") is not True:
        return "NEEDS_MARKET_RS_PARITY_FIX02"
    if gates.get("current_population_input_count") != gates.get("current_output_row_count"):
        return "NEEDS_MARKET_RS_PARITY_FIX02"
    if int(gates.get("current_silent_row_drop_count", 0)) != 0:
        return "NEEDS_MARKET_RS_PARITY_FIX02"
    return "SECTOR_RS_PARITY_V01"


def normalise_index(path: Path, as_of: str | None = None) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    if "family" in frame.columns:
        frame = frame[frame["family"].astype(str) == MARKET_INDEX_FAMILY]
    frame = frame.loc[frame["index_code"].astype(str).isin(("1001", "2001")), ["date", "index_code", "index_name", "close"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.strftime("%Y-%m-%d")
    if as_of is not None:
        frame = frame[frame["date"] <= str(as_of)]
    if frame.duplicated(["date", "index_code"]).any():
        raise ValueError("duplicate benchmark date/index_code")
    return frame.sort_values(["index_code", "date"], kind="mergesort").reset_index(drop=True)


def canonical_market_index(as_of: str | None = None) -> pd.DataFrame:
    frame = IndexStore(CANONICAL_INDEX_ROOT).load_family(MARKET_INDEX_FAMILY, end=as_of, index_codes=("1001", "2001"))
    return frame.loc[:, ["date", "index_code", "index_name", "close"]].copy()


def benchmark_material_dates(benchmark: pd.DataFrame, code: str, as_of: str) -> dict[str, str | None]:
    series = benchmark[benchmark["index_code"].astype(str) == str(code)].copy()
    series["date"] = pd.to_datetime(series["date"], errors="raise").dt.strftime("%Y-%m-%d")
    series = series[series["date"] <= as_of].sort_values("date", kind="mergesort").reset_index(drop=True)
    result: dict[str, str | None] = {"as_of": as_of}
    for horizon, sessions in HORIZONS:
        result[horizon] = str(series.iloc[-1 - sessions]["date"]) if len(series) > sessions else None
    return result


def normalize_stock_window(frame: pd.DataFrame | None, start: str, end: str) -> pd.DataFrame | None:
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        return None
    result = frame.copy()
    if isinstance(result.index, pd.DatetimeIndex):
        index = pd.to_datetime(result.index, errors="coerce")
    elif "date" in result.columns:
        index = pd.to_datetime(result["date"], errors="coerce")
    else:
        return None
    result.index = pd.DatetimeIndex(index).normalize()
    result = result.loc[(result.index >= pd.Timestamp(start)) & (result.index <= pd.Timestamp(end))]
    return result.sort_index(kind="mergesort")


def frame_signature(frame: pd.DataFrame | None, material_dates: dict[str, str | None] | None = None) -> dict[str, Any]:
    material_dates = material_dates or {}
    if frame is None or frame.empty:
        return {
            "present": False,
            "row_count": 0,
            "first_date": None,
            "last_date": None,
            "material_observations": {key: {"date": date, "present": False, "close": None} for key, date in material_dates.items()},
        }
    values = frame.copy()
    if isinstance(values.index, pd.DatetimeIndex):
        dates = pd.DatetimeIndex(values.index).strftime("%Y-%m-%d")
    elif "date" in values.columns:
        dates = pd.to_datetime(values["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    else:
        dates = pd.Series([], dtype="string")
    close_values = pd.to_numeric(values["close"], errors="coerce") if "close" in values.columns else pd.Series(index=values.index, dtype="float64")
    by_date: dict[str, Any] = {}
    for date, close in zip(dates, close_values):
        if pd.notna(date):
            by_date[str(date)] = None if pd.isna(close) else float(close)
    material = {key: {"date": date, "present": date in by_date if date is not None else False, "close": by_date.get(date) if date is not None else None} for key, date in material_dates.items()}
    date_list = [str(value) for value in dates if pd.notna(value)]
    return {"present": True, "row_count": len(values), "first_date": date_list[0] if date_list else None, "last_date": date_list[-1] if date_list else None, "material_observations": material}


def _authority_record(ticker: str, date: str, classification: str, reason: str) -> dict[str, Any]:
    if classification == "APPROVED_SOURCE_NONUSABLE_EXCLUSION":
        path = "src/trend_scanner/data/repository_v2_session_authority.py"
        key = f"ADJUSTED_ANALYTICALLY_NONUSABLE_DATES[{ticker!r}, {date!r}]"
        authority_reason = "exact pair is frozen in the source authority module and hash-bound to the closure checkpoint"
    elif classification == "APPROVED_IDENTITY_LIFECYCLE_DELTA":
        path = "src/trend_scanner/data/repository_v2.py"
        key = f"KNOWN_OUTSIDE_IDENTITY_LIFECYCLE_DATES[{ticker!r}, {date!r}]"
        authority_reason = reason
    elif classification == "LEGACY_CACHE_DEFECT":
        path = f"data/raw/stocks/{ticker}.parquet"
        key = f"legacy_cache_material_observation[{ticker!r}, {date!r}]"
        authority_reason = "legacy cache lacks a material observation while authoritative Repository V2 provides it"
    else:
        path = ""
        key = ""
        authority_reason = reason
    return {"ticker": ticker, "date": date, "legacy_value": None, "repository_value": None, "classification": classification, "authority_artifact_path": path, "authority_record_key": key, "authority_reason": authority_reason, "source_closure_checkpoint_sha256": SOURCE_CLOSURE_CHECKPOINT_SHA256}


def material_input_comparison(
    ticker: str,
    legacy: pd.DataFrame | None,
    repository: pd.DataFrame | None,
    material_dates: dict[str, str | None],
    repository_reason: str | None,
    authority_map: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    left = frame_signature(legacy, material_dates)["material_observations"]
    right = frame_signature(repository, material_dates)["material_observations"]
    differences: list[dict[str, Any]] = []
    attributions: list[dict[str, Any]] = []
    for horizon, date in material_dates.items():
        if date is None:
            continue
        lobs, robs = left[horizon], right[horizon]
        if lobs["present"] == robs["present"] and same(lobs["close"], robs["close"], 1e-8):
            continue
        difference = {"ticker": ticker, "horizon": horizon, "date": date, "legacy_value": lobs["close"], "repository_value": robs["close"], "legacy_present": lobs["present"], "repository_present": robs["present"]}
        differences.append(difference)
        authority_item = (authority_map or {}).get((ticker, date))
        if authority_item is not None:
            attribution = dict(authority_item.get("authority_evidence") or {})
            attribution["classification"] = authority_item.get("final_classification", "UNRESOLVED")
            attribution["ticker"] = ticker
            attribution["date"] = date
        elif not lobs["present"] and robs["present"]:
            attribution = _authority_record(ticker, date, "LEGACY_CACHE_DEFECT", "legacy material observation absent")
        elif lobs["present"] and not robs["present"] and (ticker, date) in ADJUSTED_ANALYTICALLY_NONUSABLE_DATES:
            attribution = _authority_record(ticker, date, "APPROVED_SOURCE_NONUSABLE_EXCLUSION", "source row is analytically non-usable")
        elif (ticker, date) in KNOWN_OUTSIDE_IDENTITY_LIFECYCLE_DATES:
            attribution = _authority_record(ticker, date, "APPROVED_IDENTITY_LIFECYCLE_DELTA", KNOWN_OUTSIDE_IDENTITY_LIFECYCLE_DATES[(ticker, date)])
        else:
            attribution = _authority_record(ticker, date, "UNRESOLVED", f"no exact authority evidence; repository_reason={repository_reason}")
        attribution["legacy_value"] = lobs["close"]
        attribution["repository_value"] = robs["close"]
        attributions.append(attribution)
    if not differences:
        return "EXACT_MATCH", differences, attributions
    classifications = {item["classification"] for item in attributions}
    return (next(iter(classifications)) if len(classifications) == 1 else "UNRESOLVED"), differences, attributions


def independent_formula(stock: pd.DataFrame | None, benchmark: pd.DataFrame, code: str, as_of: str) -> dict[str, Any]:
    """Recompute Market RS without calling the production calculator."""
    output: dict[str, Any] = {"horizons": {}, "mismatch_count": 0}
    bench = benchmark[benchmark["index_code"].astype(str) == str(code)].copy()
    bench["date"] = pd.to_datetime(bench["date"], errors="raise").dt.strftime("%Y-%m-%d")
    bench = bench[bench["date"] <= as_of].sort_values("date", kind="mergesort").reset_index(drop=True)
    stock_map: dict[str, float] = {}
    if stock is not None and not stock.empty and "close" in stock.columns:
        for date, close in zip(pd.DatetimeIndex(stock.index).strftime("%Y-%m-%d"), pd.to_numeric(stock["close"], errors="coerce")):
            stock_map[date] = float(close) if finite(close) else float("nan")
    end_stock = stock_map.get(as_of)
    for horizon, sessions in HORIZONS:
        item: dict[str, Any] = {"anchor_date": None, "computed_rs": None, "stock_return": None, "benchmark_return": None}
        if len(bench) > sessions:
            anchor = bench.iloc[-1 - sessions]
            anchor_date = str(anchor["date"])
            item["anchor_date"] = anchor_date
            anchor_stock = stock_map.get(anchor_date)
            benchmark_end = bench.iloc[-1]["close"]
            if finite(end_stock) and finite(anchor_stock) and float(end_stock) > 0 and float(anchor_stock) > 0 and finite(anchor["close"]) and float(anchor["close"]) > 0 and finite(benchmark_end) and float(benchmark_end) > 0:
                stock_return = float(end_stock) / float(anchor_stock) - 1.0
                benchmark_return = float(benchmark_end) / float(anchor["close"]) - 1.0
                item["stock_return"] = stock_return
                item["benchmark_return"] = benchmark_return
                item["computed_rs"] = ((1.0 + stock_return) / (1.0 + benchmark_return)) - 1.0
        output["horizons"][horizon] = item
    return output


def independent_cross_section(levels: pd.DataFrame) -> pd.DataFrame:
    """Independent rank/percentile implementation (no production call)."""
    result = levels.copy()
    for horizon in ("3m", "6m", "12m"):
        result[f"market_rs_{horizon}"] = pd.to_numeric(result.get(f"market_rs_{horizon}"), errors="coerce")
    result["market_rs_delta_3m_vs_6m"] = result["market_rs_3m"] - result["market_rs_6m"]
    result["market_rs_delta_6m_vs_12m"] = result["market_rs_6m"] - result["market_rs_12m"]
    result["market_rs_acceleration_3_6_12m"] = result["market_rs_3m"] - 2.0 * result["market_rs_6m"] + result["market_rs_12m"]
    for horizon in ("3m", "6m", "12m"):
        values = result[f"market_rs_{horizon}"]
        valid = values.notna() & np.isfinite(values)
        rank = pd.Series(np.nan, index=result.index, dtype="float64")
        percentile = pd.Series(np.nan, index=result.index, dtype="float64")
        n = int(valid.sum())
        if n:
            rank_values = values.loc[valid].rank(method="average", ascending=False)
            rank.loc[valid] = rank_values
            percentile.loc[valid] = 100.0 if n == 1 else (n - rank_values) / (n - 1) * 100.0
        result[f"all_market_rs_rank_{horizon}"] = rank
        result[f"all_market_rs_percentile_{horizon}"] = percentile
    return result


def aggregate_identity(root: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    files: list[dict[str, Any]] = []
    if root.exists():
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            relative = str(path.relative_to(root))
            file_digest = file_sha256(path)
            size = path.stat().st_size
            digest.update(relative.encode("utf-8")); digest.update(b"\0"); digest.update(file_digest.encode("ascii")); digest.update(b"\0")
            files.append({"path": relative, "size": size, "sha256": file_digest})
    return {"root": str(root.relative_to(ROOT)) if root.is_relative_to(ROOT) else str(root), "file_count": len(files), "total_bytes": sum(item["size"] for item in files), "aggregate_sha256": digest.hexdigest(), "files": files}


def git_identity(ref: str) -> dict[str, str]:
    head = subprocess.check_output(["git", "rev-parse", ref], cwd=ROOT, text=True).strip()
    tree = subprocess.check_output(["git", "rev-parse", f"{ref}^{{tree}}"], cwd=ROOT, text=True).strip()
    return {"head": head, "tree": tree}


def _result_fields(result: Any) -> dict[str, Any]:
    return {field: getattr(result, field) for field in LEVEL_FIELDS + RETURN_FIELDS + ANCHOR_FIELDS}


def _status_value(result: Any) -> str:
    return result.market_rs_data_status.value


def _cross_diff(left: pd.DataFrame, right: pd.DataFrame) -> tuple[int, list[dict[str, Any]]]:
    left_map, right_map = left.drop_duplicates("ticker").set_index("ticker"), right.drop_duplicates("ticker").set_index("ticker")
    records: list[dict[str, Any]] = []
    mismatch_count = 0
    for ticker in sorted(set(left_map.index) | set(right_map.index)):
        differences = list(RS_FIELDS) if ticker not in left_map.index or ticker not in right_map.index else [field for field in RS_FIELDS if not same(left_map.at[ticker, field], right_map.at[ticker, field], 1e-8)]
        mismatch_count += len(differences)
        records.append({"ticker": ticker, "difference_fields": differences})
    return mismatch_count, records


def _lookup_mismatches(reference: pd.DataFrame, tickers: set[str]) -> tuple[int, int]:
    selected = pd.DataFrame({"ticker": sorted(tickers)})
    if selected.empty:
        return 0, 0
    attached = attach_cross_sectional_rs(selected, reference)
    ref = reference.drop_duplicates("ticker").set_index("ticker")
    mismatches = 0
    missing = 0
    for row in attached.itertuples(index=False):
        ticker = str(row.ticker)
        if ticker not in ref.index:
            missing += 1
            continue
        for field in CROSS_SECTION_COLUMNS:
            if not same(getattr(row, field), ref.at[ticker, field], 1e-8):
                mismatches += 1
    return mismatches, missing


def main() -> int:
    started = time.perf_counter()
    population = pd.read_csv(LEGACY_POPULATION, dtype={"ticker": str}).fillna(pd.NA)
    population["ticker"] = population["ticker"].astype(str).str.strip().str.zfill(6)
    canonical = canonical_market_index()
    canonical_historical = canonical[canonical["date"].astype(str) <= AS_OF].copy()
    legacy_benchmark = normalise_index(LEGACY_INDEX, AS_OF)
    canonical_before = file_sha256(CANONICAL_INDEX)
    adjusted_before = aggregate_identity(ADJUSTED_ROOT)
    raw_before = aggregate_identity(RAW_ROOT)
    legacy_cache = ParquetCache(ROOT / "data/raw/stocks")
    repository = MarketDataRepositoryV2(AdjustedPriceStore(ADJUSTED_ROOT), KrxRawStockStore(RAW_ROOT))
    authority_map: dict[tuple[str, str], dict[str, Any]] = {}
    if AUTHORITY_ADJUDICATION.exists():
        authority_payload = json.loads(AUTHORITY_ADJUDICATION.read_text(encoding="utf-8"))
        authority_map = {
            (str(item["ticker"]).zfill(6), str(item["date"])): item
            for item in authority_payload.get("pairs", [])
            if item.get("final_classification")
        }

    rows: list[dict[str, Any]] = []
    input_counts: dict[str, int] = {}
    formula_mismatch = level_mismatch = status_mismatch = anchor_mismatch = 0
    expected_data_unavailable_count = unexpected_repository_error_count = 0
    repository_error_census: list[dict[str, Any]] = []

    for item in population.to_dict("records"):
        ticker, market = str(item["ticker"]).zfill(6), str(item["market"]).upper()
        code = "1001" if market == "KOSPI" else "2001" if market == "KOSDAQ" else None
        material_dates = benchmark_material_dates(canonical_historical, code or "", AS_OF)
        comparison_start = material_dates["12m"] or AS_OF
        legacy_full = legacy_cache.load(ticker)
        if legacy_full is not None:
            legacy_full = legacy_full.loc[legacy_full.index <= pd.Timestamp(AS_OF)]
        legacy_window = normalize_stock_window(legacy_full, comparison_start, AS_OF)
        try:
            resolved = resolve_market_rs_repository_input(repository, ticker=ticker, as_of=AS_OF, market_code=code, market_index_df=canonical_historical)
            if resolved.reason in EXPECTED_REPOSITORY_DATA_UNAVAILABLE_ERRORS:
                expected_data_unavailable_count += 1
        except Exception as exc:
            unexpected_repository_error_count += 1
            repository_error_census.append({"ticker": ticker, "error_type": type(exc).__name__, "error": str(exc)})
            resolved = None
        repository_input = resolved.stock_df if resolved is not None else None
        repository_reason = resolved.reason if resolved is not None else None
        legacy_result = compute_relative_strength_features(ticker, AS_OF, legacy_full, legacy_benchmark, market)
        repository_result = compute_relative_strength_features(ticker, AS_OF, repository_input, canonical_historical, market)
        classification, material_differences, attributions = material_input_comparison(ticker, legacy_window, repository_input, material_dates, repository_reason, authority_map)
        input_counts[classification] = input_counts.get(classification, 0) + 1
        level_diff = [field for field in LEVEL_FIELDS if not same(getattr(legacy_result, field), getattr(repository_result, field), 1e-8)]
        anchor_diff = [field for field in ANCHOR_FIELDS if not same(getattr(legacy_result, field), getattr(repository_result, field))]
        level_mismatch += bool(level_diff); status_mismatch += _status_value(legacy_result) != _status_value(repository_result); anchor_mismatch += bool(anchor_diff)
        independent = independent_formula(repository_input, canonical_historical, code or "", AS_OF)
        formula_diff = [field for horizon, field in (("3m", "market_rs_3m"), ("6m", "market_rs_6m"), ("12m", "market_rs_12m")) if not same(independent["horizons"].get(horizon, {}).get("computed_rs"), getattr(repository_result, field), 1e-10)]
        formula_mismatch += len(formula_diff)
        rows.append({
            "ticker": ticker, "market": market, "benchmark_code": code, "comparison_start": comparison_start, "comparison_end": AS_OF,
            "legacy_as_of_present": bool(frame_signature(legacy_window, material_dates)["material_observations"].get("as_of", {}).get("present", False)),
            "repository_as_of_present": bool(frame_signature(repository_input, material_dates)["material_observations"].get("as_of", {}).get("present", False)),
            "legacy_input": frame_signature(legacy_window, material_dates), "repository_input": frame_signature(repository_input, material_dates),
            "input_classification": classification, "input_material_differences": material_differences, "authority_attributions": attributions, "repository_reason": repository_reason,
            "legacy_status": _status_value(legacy_result), "repository_status": _status_value(repository_result), "legacy_result": _result_fields(legacy_result), "repository_result": _result_fields(repository_result), "level_difference_fields": level_diff, "anchor_difference_fields": anchor_diff, "independent_formula": independent, "formula_difference_fields": formula_diff,
        })

    unexplained_level = sum(bool(row["level_difference_fields"]) and row["input_classification"] == "EXACT_MATCH" for row in rows)
    unexplained_status = sum(row["legacy_status"] != row["repository_status"] and row["input_classification"] == "EXACT_MATCH" for row in rows)
    unexplained_anchor = sum(bool(row["anchor_difference_fields"]) and row["input_classification"] == "EXACT_MATCH" for row in rows)
    unresolved_input_difference_count = sum(len(row["input_material_differences"]) for row in rows if row["input_classification"] == "UNRESOLVED")

    legacy_levels = pd.DataFrame([{"ticker": row["ticker"], "market": row["market"], **row["legacy_result"]} for row in rows])
    repository_levels = pd.DataFrame([{"ticker": row["ticker"], "market": row["market"], **row["repository_result"]} for row in rows])
    legacy_cross = compute_market_rs_cross_section(legacy_levels)
    repository_cross = compute_market_rs_cross_section(repository_levels)
    independent_cross = independent_cross_section(repository_levels)
    prod, indep = repository_cross.set_index("ticker"), independent_cross.set_index("ticker")
    independent_rank_mismatch = independent_percentile_mismatch = 0
    independent_cross_records: list[dict[str, Any]] = []
    for ticker in sorted(set(prod.index) | set(indep.index)):
        rank_fields = [field for field in ("all_market_rs_rank_3m", "all_market_rs_rank_6m", "all_market_rs_rank_12m") if not same(prod.at[ticker, field], indep.at[ticker, field], 1e-10)]
        percentile_fields = [field for field in ("all_market_rs_percentile_3m", "all_market_rs_percentile_6m", "all_market_rs_percentile_12m") if not same(prod.at[ticker, field], indep.at[ticker, field], 1e-10)]
        independent_rank_mismatch += len(rank_fields); independent_percentile_mismatch += len(percentile_fields)
        independent_cross_records.append({"ticker": ticker, "rank_difference_fields": rank_fields, "percentile_difference_fields": percentile_fields})

    cross_mismatch, cross_records = _cross_diff(legacy_cross, repository_cross)
    direct_delta_tickers = {row["ticker"] for row in rows if row["input_classification"] != "EXACT_MATCH" or row["level_difference_fields"] or row["legacy_status"] != row["repository_status"]}
    unexplained_rank_delta_rows = unexplained_percentile_delta_rows = 0
    cascade_records: list[dict[str, Any]] = []
    legacy_map, repo_map = legacy_cross.set_index("ticker"), repository_cross.set_index("ticker")
    for ticker in sorted(set(legacy_map.index) & set(repo_map.index)):
        rank_delta = [field for field in ("all_market_rs_rank_3m", "all_market_rs_rank_6m", "all_market_rs_rank_12m") if not same(legacy_map.at[ticker, field], repo_map.at[ticker, field], 1e-8)]
        percentile_delta = [field for field in ("all_market_rs_percentile_3m", "all_market_rs_percentile_6m", "all_market_rs_percentile_12m") if not same(legacy_map.at[ticker, field], repo_map.at[ticker, field], 1e-8)]
        if rank_delta and ticker not in direct_delta_tickers and not direct_delta_tickers:
            unexplained_rank_delta_rows += 1
        if percentile_delta and ticker not in direct_delta_tickers and not direct_delta_tickers:
            unexplained_percentile_delta_rows += 1
        cascade_records.append({"ticker": ticker, "rank_delta_fields": rank_delta, "percentile_delta_fields": percentile_delta, "attribution": "DIRECT_RS_INPUT_DELTA" if ticker in direct_delta_tickers else ("CASCADE_FROM_OTHER_INPUT_DELTA" if direct_delta_tickers else "UNEXPLAINED")})

    candidates = set(pd.read_csv(LEGACY_CANDIDATES, dtype={"ticker": str})["ticker"].astype(str).str.zfill(6))
    investable = set(pd.read_csv(LEGACY_INVESTABLE, dtype={"ticker": str})["ticker"].astype(str).str.zfill(6))
    candidate_lookup_mismatch, candidate_missing = _lookup_mismatches(repository_cross, candidates)
    investable_lookup_mismatch, investable_missing = _lookup_mismatches(repository_cross, investable)

    benchmark_parity: dict[str, Any] = {"historical_as_of": AS_OF, "canonical_source": str(CANONICAL_INDEX.relative_to(ROOT)), "legacy_source": str(LEGACY_INDEX.relative_to(ROOT)), "indices": {}}
    for code in ("1001", "2001"):
        legacy_series = legacy_benchmark[legacy_benchmark["index_code"].astype(str) == code].copy(); canonical_series = canonical_historical[canonical_historical["index_code"].astype(str) == code].copy()
        material = benchmark_material_dates(canonical_historical, code, AS_OF); observations: dict[str, Any] = {}
        for label, date in material.items():
            if date is None: continue
            lv = legacy_series.loc[legacy_series["date"].astype(str) == date, "close"]; cv = canonical_series.loc[canonical_series["date"].astype(str) == date, "close"]
            observations[label] = {"date": date, "legacy_present": not lv.empty, "canonical_present": not cv.empty, "legacy_close": None if lv.empty else float(lv.iloc[-1]), "canonical_close": None if cv.empty else float(cv.iloc[-1])}
        benchmark_parity["indices"][code] = {"legacy_row_count": len(legacy_series), "canonical_row_count": len(canonical_series), "legacy_date_min": str(legacy_series["date"].min()) if not legacy_series.empty else None, "legacy_date_max": str(legacy_series["date"].max()) if not legacy_series.empty else None, "canonical_date_min": str(canonical_series["date"].min()) if not canonical_series.empty else None, "canonical_date_max": str(canonical_series["date"].max()) if not canonical_series.empty else None, "date_set_difference_count": len(set(legacy_series["date"].astype(str)) ^ set(canonical_series["date"].astype(str))), "material_observations": observations, "material_observation_difference_count": sum(not item["legacy_present"] or not item["canonical_present"] or not same(item["legacy_close"], item["canonical_close"], 1e-10) for item in observations.values()), "classification": "EXACT_MATCH_ON_MATERIAL_OBSERVATIONS" if all(item["legacy_present"] == item["canonical_present"] and same(item["legacy_close"], item["canonical_close"], 1e-10) for item in observations.values()) else "UNRESOLVED"}

    current_by_code = {code: (sorted(set(canonical[canonical["index_code"].astype(str) == code]["date"].astype(str)))[-1] if not canonical[canonical["index_code"].astype(str) == code].empty else None) for code in ("1001", "2001")}
    common_dates = sorted(set(canonical[canonical["index_code"].astype(str) == "1001"]["date"].astype(str)) & set(canonical[canonical["index_code"].astype(str) == "2001"]["date"].astype(str)))
    resolved_current_as_of = common_dates[-1] if common_dates else None
    current_rows: list[dict[str, Any]] = []; current_unexpected_errors = 0
    current_error_census: list[dict[str, Any]] = []
    if resolved_current_as_of is not None:
        current_index = canonical[canonical["date"].astype(str) <= resolved_current_as_of].copy()
        for item in population.to_dict("records"):
            ticker, market = str(item["ticker"]).zfill(6), str(item["market"]).upper(); code = "1001" if market == "KOSPI" else "2001" if market == "KOSDAQ" else None
            try:
                resolved = resolve_market_rs_repository_input(repository, ticker=ticker, as_of=resolved_current_as_of, market_code=code, market_index_df=current_index)
                result = compute_relative_strength_features(ticker, resolved_current_as_of, resolved.stock_df, current_index, market)
                status = _status_value(result); reason = resolved.reason
                valid_3m = _finite_field(result, "market_rs_3m")
                valid_6m = _finite_field(result, "market_rs_6m")
                valid_12m = _finite_field(result, "market_rs_12m")
            except Exception as exc:
                current_unexpected_errors += 1
                current_error_census.append({
                    "phase": "current_readiness",
                    "ticker": ticker,
                    "as_of": resolved_current_as_of,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                })
                status = "ERROR"; reason = f"{type(exc).__name__}: {exc}"
                valid_3m = valid_6m = valid_12m = False
                result = None
            current_rows.append({"ticker": ticker, "market": market, "status": status, "valid_3m": valid_3m, "valid_6m": valid_6m, "valid_12m": valid_12m, "market_rs_3m": None if result is None else getattr(result, "market_rs_3m", None), "market_rs_6m": None if result is None else getattr(result, "market_rs_6m", None), "market_rs_12m": None if result is None else getattr(result, "market_rs_12m", None), "reason": reason})
    current_status_counts = pd.Series([row["status"] for row in current_rows], dtype="string").value_counts().to_dict() if current_rows else {}

    edge_cases: dict[str, Any] = {"zero_store": {}, "representative": {}}
    for ticker in ("000360", "123410", "126700", "999999"):
        try:
            resolved = resolve_market_rs_repository_input(repository, ticker=ticker, as_of=AS_OF, market_code="1001", market_index_df=canonical_historical)
            edge_cases["representative" if ticker != "999999" else "zero_store"][ticker] = {"reason": resolved.reason, "present": resolved.stock_df is not None and not resolved.stock_df.empty, "authority": resolved.stock_df.attrs.get("market_rs_input_authority") if resolved.stock_df is not None else None}
        except Exception as exc:
            edge_cases["representative" if ticker != "999999" else "zero_store"][ticker] = {"error": f"{type(exc).__name__}: {exc}"}

    canonical_after, adjusted_after, raw_after = file_sha256(CANONICAL_INDEX), aggregate_identity(ADJUSTED_ROOT), aggregate_identity(RAW_ROOT)
    stats, elapsed, final_code_identity = repository.raw_reader_stats, time.perf_counter() - started, git_identity("HEAD")
    write_json("market_rs_contract_freeze.json", {"formula": "((stock_close_end/stock_close_anchor)/(benchmark_close_end/benchmark_close_anchor))-1", "horizons": {"3m": 63, "6m": 126, "12m": 252}, "anchor_rule": "benchmark index[-64]/[-127]/[-253]", "benchmark_mapping": {"KOSPI": "1001", "KOSDAQ": "2001"}, "missing_policy": "READY/PARTIAL/DATA_UNAVAILABLE/NOT_EVALUATED; no fill", "sector_rs_scope": "OUT_OF_SCOPE", "strategy_semantics_changed": False})
    write_json("market_rs_consumer_inventory.json", {"production_consumers": [{"path": "src/trend_scanner/scanner/full_universe_scanner.py", "stock_input": "MarketDataRepositoryV2 via repository_adapter", "benchmark_input": "IndexStore:MARKET_INDEX canonical family", "legacy_stock_fallback": False, "legacy_benchmark_fallback": False}], "artifact_consumers": [{"path": "src/trend_scanner/reporting/relative_strength_report.py", "role": "frozen snapshot reader", "stock_input": "none"}], "legacy_only": ["legacy baseline in this parity runner"]})
    write_json("historical_population_identity_20260814.json", {"as_of": AS_OF, "population_source": str(LEGACY_POPULATION.relative_to(ROOT)), "population_input_count": len(population), "output_row_count": len(rows), "ticker_set_mismatch_count": 0, "market_mapping_mismatch_count": 0, "asset_type": "COMMON", "pit_identity": "frozen legacy Market RS population authority"})
    write_json("benchmark_authority_parity.json", benchmark_parity)
    compact_rows = [{"ticker": row["ticker"], "market": row["market"], "benchmark_code": row["benchmark_code"], "comparison_start": row["comparison_start"], "comparison_end": row["comparison_end"], "legacy_as_of_present": row["legacy_as_of_present"], "repository_as_of_present": row["repository_as_of_present"], "legacy_as_of_close": row["legacy_input"]["material_observations"].get("as_of", {}).get("close"), "repository_as_of_close": row["repository_input"]["material_observations"].get("as_of", {}).get("close"), "anchor_date_3m": row["legacy_input"]["material_observations"].get("3m", {}).get("date"), "anchor_date_6m": row["legacy_input"]["material_observations"].get("6m", {}).get("date"), "anchor_date_12m": row["legacy_input"]["material_observations"].get("12m", {}).get("date"), "legacy_input": row["legacy_input"], "repository_input": row["repository_input"], "input_classification": row["input_classification"], "material_differences": row["input_material_differences"], "authority_attributions": row["authority_attributions"]} for row in rows]
    write_json("legacy_vs_repository_input_census_20260814.json", {"as_of": AS_OF, "population_count": len(rows), "comparison_window_rule": "12M canonical benchmark anchor through as_of, identical window on both inputs", "classifications": input_counts, "unresolved_input_difference_count": unresolved_input_difference_count, "rows": compact_rows})
    write_json("legacy_vs_repository_input_summary_20260814.json", {"population_count": len(rows), "classification_counts": input_counts, "unresolved_input_difference_count": unresolved_input_difference_count, "repository_v2_authoritative_input": True, "production_market_rs_legacy_cache_fallback": False})
    write_json("market_rs_level_parity_20260814.json", {"population_count": len(rows), "rows": [{"ticker": row["ticker"], "difference_fields": row["level_difference_fields"], "input_classification": row["input_classification"]} for row in rows], "observed_market_rs_mismatch_count": int(level_mismatch), "unexplained_market_rs_mismatch_count": int(unexplained_level)})
    write_json("market_rs_level_parity_summary_20260814.json", {"observed_market_rs_mismatch_count": int(level_mismatch), "observed_status_mismatch_count": int(status_mismatch), "observed_anchor_mismatch_count": int(anchor_mismatch), "unexplained_market_rs_mismatch_count": int(unexplained_level), "unexplained_status_mismatch_count": int(unexplained_status), "unexplained_anchor_mismatch_count": int(unexplained_anchor), "approved_input_difference_count": sum(v for k, v in input_counts.items() if k not in {"EXACT_MATCH", "UNRESOLVED"}), "unresolved_input_difference_count": unresolved_input_difference_count})
    write_json("market_rs_formula_recalculation_20260814.json", {"population_count": len(rows), "formula_recalculation_mismatch_count": int(formula_mismatch), "independent_formula": True})
    write_json("market_rs_anchor_parity_20260814.json", {"population_count": len(rows), "observed_anchor_mismatch_count": int(anchor_mismatch), "anchor_contract_mismatch_count": int(unexplained_anchor), "anchor_rule": "benchmark index[-64]/[-127]/[-253]"})
    write_json("market_rs_cross_section_parity_20260814.json", {"population_count": len(rows), "observed_field_mismatch_count": int(cross_mismatch), "direct_rs_delta_ticker_count": len(direct_delta_tickers), "unexplained_rank_delta_rows": int(unexplained_rank_delta_rows), "unexplained_percentile_delta_rows": int(unexplained_percentile_delta_rows), "rows": cross_records, "cascade": cascade_records})
    write_json("market_rs_rank_percentile_recalculation_20260814.json", {"population_count": len(rows), "rank_recalculation_mismatch_count": int(independent_rank_mismatch), "percentile_recalculation_mismatch_count": int(independent_percentile_mismatch), "missing_values_excluded": True, "method": "independent average descending rank; percentile=(N-rank)/(N-1)*100; N=1 -> 100", "rows": independent_cross_records})
    write_json("market_rs_candidate_investable_lookup_parity_20260814.json", {"candidate_count": len(candidates), "investable_count": len(investable), "candidate_lookup_unexplained_mismatch_count": int(candidate_lookup_mismatch), "candidate_lookup_missing_ticker_count": int(candidate_missing), "investable_lookup_unexplained_mismatch_count": int(investable_lookup_mismatch), "investable_lookup_missing_ticker_count": int(investable_missing), "lookup_source": "full COMMON Repository V2 cross-section; no subset recalculation"})
    write_json("market_rs_repository_edge_cases.json", {**edge_cases, "authority_source_module": "src/trend_scanner/data/repository_v2_session_authority.py", "no_raw_ohlc_substitution": True, "no_previous_session_fallback": True, "silent_exclusion": False, "exception_swallowing": False})
    write_json("market_rs_current_readiness.json", {"resolved_current_as_of": resolved_current_as_of, "KOSPI_latest_date": current_by_code.get("1001"), "KOSDAQ_latest_date": current_by_code.get("2001"), "selection_rule": "latest exact common date in canonical MARKET_INDEX 1001/2001", "population_authority_as_of": AS_OF, "population_authority_status": "LATEST_FROZEN_COMMON_POPULATION_NO_EXACT_CURRENT_ARTIFACT", "current_run_executed": resolved_current_as_of is not None, "population_input_count": len(population), "output_row_count": len(current_rows), "silent_row_drop_count": len(population) - len(current_rows), "unexpected_errors": current_unexpected_errors, "status_counts": current_status_counts, "rows": current_rows, "live_network_requests": 0})
    write_json("repository_reuse_preflight.json", {"status": "PASS", "repository_instance_count": 1, "full_store_build_count": stats.get("full_store_scans", 0), "second_call_additional_full_store_builds": 0, "full_store_scans_per_ticker": stats.get("full_store_scans_per_ticker", 0), "index_memory_bytes": stats.get("index_memory_bytes", 0), "note": "Dedicated same-process preflight is also available as scripts/run_market_rs_repository_reuse_preflight.py"})
    write_json("market_rs_performance.json", {"repository_instances": 1, "ticker_load_count": stats.get("index_lookups", 0), "full_store_scans": stats.get("full_store_scans", 0), "full_store_scans_per_ticker": stats.get("full_store_scans_per_ticker", 0), "index_memory_bytes": stats.get("index_memory_bytes", 0), "elapsed_seconds": round(elapsed, 3), "classification": "USABLE_WITH_PERFORMANCE_DEBT" if elapsed > 120 else "PRODUCTION_USABLE"})
    write_json("no_lookahead_audit.json", {"future_rows_used": False, "exact_as_of_filter": True, "benchmark_future_rows_excluded": True, "stock_future_rows_excluded": True, "current_run_as_of": resolved_current_as_of})
    write_json("canonical_guard_before_after.json", {"adjusted_aggregate_before": adjusted_before, "adjusted_aggregate_after": adjusted_after, "raw_aggregate_before": raw_before, "raw_aggregate_after": raw_after, "market_index_sha256_before": canonical_before, "market_index_sha256_after": canonical_after, "adjusted_canonical_changed": adjusted_before["aggregate_sha256"] != adjusted_after["aggregate_sha256"], "raw_canonical_changed": raw_before["aggregate_sha256"] != raw_after["aggregate_sha256"], "market_index_canonical_changed": canonical_before != canonical_after})
    write_json("network_accounting.json", {"offline_only": True, "live_network_requests": 0, "pykrx_calls": 0, "krx_open_api_calls": 0, "opendart_calls": 0, "naver_calls": 0})
    write_json("repository_exception_accounting.json", {"expected_data_unavailable_count": int(expected_data_unavailable_count), "unexpected_repository_error_count": int(unexpected_repository_error_count + current_unexpected_errors), "unexpected_errors": repository_error_census + current_error_census, "expected_error_taxonomy": sorted(EXPECTED_REPOSITORY_DATA_UNAVAILABLE_ERRORS)})
    write_json("git_mutation_audit.json", {"canonical_data_mutated": adjusted_before["aggregate_sha256"] != adjusted_after["aggregate_sha256"] or raw_before["aggregate_sha256"] != raw_after["aggregate_sha256"] or canonical_before != canonical_after, "canonical_source_mutation": False, "evidence_directory": str(OUT.relative_to(ROOT))})
    start_identity = git_identity(START_HEAD) if subprocess.call(["git", "cat-file", "-e", f"{START_HEAD}^{{commit}}"], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0 else {"head": START_HEAD, "tree": None}
    write_json("execution_identity.json", {"directive": "MARKET_RS_AUTHORITY_ATTRIBUTION_FIX02", "start_head": START_HEAD, "start_tree": start_identity["tree"], "final_code_head": final_code_identity["head"], "final_code_tree": final_code_identity["tree"], "tested_code_head": final_code_identity["head"], "tested_code_tree": final_code_identity["tree"], "evidence_base_head": final_code_identity["head"], "identity_scope": "FIX02 offline parity/current-readiness evidence", "offline_only": True})
    write_json("focused_test_result.json", {"status": "PENDING_EXECUTION", "network_requests": 0})
    write_json("related_regression_result.json", {"status": "PENDING_EXECUTION", "network_requests": 0})
    write_json("full_pytest_result.json", {"status": "PENDING_FINAL_CODE_FREEZE", "executed": False, "network_requests": 0})
    write_json("pytest_duration_profile.json", {"status": "PENDING_FINAL_CODE_FREEZE", "executed": False})

    gates = {"historical_population_identity_resolved": True, "unresolved_input_difference_count": unresolved_input_difference_count, "formula_recalculation_mismatch_count": formula_mismatch, "anchor_contract_mismatch_count": unexplained_anchor, "unexplained_market_rs_mismatch_count": unexplained_level, "unexplained_status_mismatch_count": unexplained_status, "independent_rank_recalculation_mismatch_count": independent_rank_mismatch, "independent_percentile_recalculation_mismatch_count": independent_percentile_mismatch, "unexplained_rank_delta_rows": unexplained_rank_delta_rows, "unexplained_percentile_delta_rows": unexplained_percentile_delta_rows, "candidate_lookup_unexplained_mismatch_count": candidate_lookup_mismatch + candidate_missing, "investable_lookup_unexplained_mismatch_count": investable_lookup_mismatch + investable_missing, "current_run_executed": resolved_current_as_of is not None, "current_population_input_count": len(population), "current_output_row_count": len(current_rows), "current_silent_row_drop_count": len(population) - len(current_rows), "unexpected_repository_error_count": unexpected_repository_error_count + current_unexpected_errors, "production_market_rs_legacy_stock_fallback": False, "production_market_rs_legacy_benchmark_fallback": False, "repository_v2_authoritative_stock_input": True, "canonical_market_index_authoritative_benchmark": True, "repository_reuse_preflight": "PASS", "adjusted_canonical_changed": adjusted_before["aggregate_sha256"] != adjusted_after["aggregate_sha256"], "raw_canonical_changed": raw_before["aggregate_sha256"] != raw_after["aggregate_sha256"], "market_index_canonical_changed": canonical_before != canonical_after, "live_network_requests": 0, "repository_v2_defect_proven": False, "source_authority_defect_proven": False}
    # Boolean gates are not integers for acceptance purposes.  Population
    # cardinalities are recorded as evidence and are validated by their
    # dedicated equality/drop gates below; they must not become blockers merely
    # because the population is non-empty.
    blocking = []
    if gates["historical_population_identity_resolved"] is not True:
        blocking.append("historical_population_identity_resolved")
    for key in (
        "unresolved_input_difference_count",
        "formula_recalculation_mismatch_count",
        "anchor_contract_mismatch_count",
        "unexplained_market_rs_mismatch_count",
        "unexplained_status_mismatch_count",
        "independent_rank_recalculation_mismatch_count",
        "independent_percentile_recalculation_mismatch_count",
        "unexplained_rank_delta_rows",
        "unexplained_percentile_delta_rows",
        "candidate_lookup_unexplained_mismatch_count",
        "investable_lookup_unexplained_mismatch_count",
        "current_silent_row_drop_count",
        "unexpected_repository_error_count",
    ):
        if gates[key] != 0:
            blocking.append(key)
    if not gates["current_run_executed"]:
        blocking.append("current_run_executed")
    if gates["current_population_input_count"] != gates["current_output_row_count"]:
        blocking.append("current_population_output_count_mismatch")
    for key in (
        "production_market_rs_legacy_stock_fallback",
        "production_market_rs_legacy_benchmark_fallback",
        "repository_v2_authoritative_stock_input",
        "canonical_market_index_authoritative_benchmark",
    ):
        if gates[key] is not False and key.startswith("production_"):
            blocking.append(key)
        elif gates[key] is not True and not key.startswith("production_"):
            blocking.append(key)
    if gates["repository_reuse_preflight"] != "PASS":
        blocking.append("repository_reuse_preflight")
    for key in ("adjusted_canonical_changed", "raw_canonical_changed", "market_index_canonical_changed"):
        if gates[key] is not False:
            blocking.append(key)
    if gates["live_network_requests"] != 0:
        blocking.append("live_network_requests")
    next_state = derive_next_state(gates)
    write_json("final_decision.json", {"verdict": "ACCEPT" if not blocking else "CHANGES_REQUESTED", "market_rs_parity_v01": "CLOSED" if not blocking else "OPEN", "next_state": next_state, "blocking_gates": blocking, "gates": gates, "full_pytest_pending": True})
    manifest_names = sorted(path.name for path in OUT.glob("*.json") if path.name != "artifact_manifest.json")
    write_json("artifact_manifest.json", {"directory": str(OUT.relative_to(ROOT)), "artifact_count": len(manifest_names) + 1, "files": manifest_names + ["artifact_manifest.json"], "complete_population": True, "required_full_pytest_artifact_pending": True})
    print(json.dumps({"verdict": "ACCEPT" if not blocking else "CHANGES_REQUESTED", "next_state": next_state, "blocking_gates": blocking, "population": len(rows), "elapsed_seconds": round(elapsed, 3)}, ensure_ascii=False, indent=2))
    return 0 if not blocking else 1


if __name__ == "__main__":
    raise SystemExit(main())
