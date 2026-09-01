"""Run the local-only Phase 12 FIX01 operational scanner validation."""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

import pandas as pd

from trend_scanner.scanner.full_universe_scanner import scan_pattern_a_universe
from trend_scanner.data.cache import ParquetCache
from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data.repository_v2 import MarketDataRepositoryV2


ROOT = Path(__file__).resolve().parents[1]
AS_OF = "2026-08-14"
START_HEAD = "ef458fb128139b1d624c1ec26edf1362c6cdf85d"
OUT_DIR = ROOT / "artifacts/patterns/pattern_a/validation/relative_strength/market_completion_v01"
AUTHORITY_PATH = OUT_DIR / "market_rs_universe_20260814.csv"
CANDIDATE_PATH = OUT_DIR / "market_rs_candidates_20260814.csv"
INVESTABLE_PATH = OUT_DIR / "market_rs_investable_candidates_20260814.csv"

MARKET_COLUMNS = (
    "market_rs_3m",
    "market_rs_6m",
    "market_rs_12m",
    "market_rs_delta_3m_vs_6m",
    "market_rs_delta_6m_vs_12m",
    "market_rs_acceleration_3_6_12m",
    "all_market_rs_rank_3m",
    "all_market_rs_rank_6m",
    "all_market_rs_rank_12m",
    "all_market_rs_percentile_3m",
    "all_market_rs_percentile_6m",
    "all_market_rs_percentile_12m",
)
STATUS_COLUMNS = ("market_rs_data_status",)
IDENTITY_COLUMNS = (
    "pattern_a_score",
    "official_stage",
    "candidate_state",
    "investability_status",
    "foreign_flow_data_status",
    "foreign_net_buy_value_1d",
    "foreign_net_buy_value_5d",
    "foreign_net_buy_value_20d",
    "foreign_net_buy_value_60d",
)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _finite(value: Any) -> bool:
    try:
        return value is not None and not pd.isna(value) and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _same(left: Any, right: Any, tolerance: float = 1e-9) -> bool:
    if _finite(left) or _finite(right):
        return _finite(left) and _finite(right) and math.isclose(
            float(left), float(right), rel_tol=0.0, abs_tol=tolerance
        )
    left_missing = left is None or (isinstance(left, float) and math.isnan(left)) or pd.isna(left)
    right_missing = right is None or (isinstance(right, float) and math.isnan(right)) or pd.isna(right)
    if left_missing and right_missing:
        return True
    return str(left) == str(right)


def _compare_columns(left: pd.DataFrame, right: pd.DataFrame, columns: tuple[str, ...]) -> int:
    left_map = left.drop_duplicates("ticker").set_index("ticker")
    right_map = right.drop_duplicates("ticker").set_index("ticker")
    mismatch = 0
    for ticker in sorted(set(left_map.index) | set(right_map.index)):
        if ticker not in left_map.index or ticker not in right_map.index:
            mismatch += 1
            continue
        for column in columns:
            if not _same(left_map.at[ticker, column], right_map.at[ticker, column]):
                mismatch += 1
    return mismatch


def _population_gate(frame: pd.DataFrame) -> tuple[int, int]:
    missing_rank = 0
    unexpected_rank = 0
    for horizon in ("3m", "6m", "12m"):
        rs = frame[f"market_rs_{horizon}"].map(_finite)
        rank = frame[f"all_market_rs_rank_{horizon}"].map(_finite)
        percentile = frame[f"all_market_rs_percentile_{horizon}"].map(_finite)
        missing_rank += int((rs & ~(rank & percentile)).sum())
        unexpected_rank += int((~rs & (rank | percentile)).sum())
    return missing_rank, unexpected_rank


def main() -> int:
    started = time.perf_counter()
    authority = pd.read_csv(AUTHORITY_PATH, dtype={"ticker": str}).fillna(pd.NA)
    candidates = pd.read_csv(CANDIDATE_PATH, dtype={"ticker": str}).fillna(pd.NA)
    investable = pd.read_csv(INVESTABLE_PATH, dtype={"ticker": str}).fillna(pd.NA)
    authority["ticker"] = authority["ticker"].astype(str).str.zfill(6)
    candidates["ticker"] = candidates["ticker"].astype(str).str.zfill(6)
    investable["ticker"] = investable["ticker"].astype(str).str.zfill(6)

    scanner_result = scan_pattern_a_universe(
        cache=ParquetCache(ROOT / "data/raw/stocks"),
        as_of=AS_OF,
        market_rs_repository=MarketDataRepositoryV2(
            AdjustedPriceStore(ROOT / "data/market/adjusted/stocks"),
            KrxRawStockStore(ROOT / "data/market/raw/krx_stocks/v01"),
        ),
        enrich_market_rs_cross_section=True,
    )
    scanner = scanner_result.to_dataframe()
    scanner["ticker"] = scanner["ticker"].astype(str).str.zfill(6)

    ticker_set_mismatch_count = len(set(scanner["ticker"]) ^ set(authority["ticker"]))
    status_mismatch_count = _compare_columns(scanner, authority, STATUS_COLUMNS)
    market_rs_level_mismatch_count = _compare_columns(
        scanner,
        authority,
        ("market_rs_3m", "market_rs_6m", "market_rs_12m"),
    )
    improvement_mismatch_count = _compare_columns(
        scanner,
        authority,
        (
            "market_rs_delta_3m_vs_6m",
            "market_rs_delta_6m_vs_12m",
            "market_rs_acceleration_3_6_12m",
        ),
    )
    rank_mismatch_count = _compare_columns(
        scanner,
        authority,
        ("all_market_rs_rank_3m", "all_market_rs_rank_6m", "all_market_rs_rank_12m"),
    )
    percentile_mismatch_count = _compare_columns(
        scanner,
        authority,
        (
            "all_market_rs_percentile_3m",
            "all_market_rs_percentile_6m",
            "all_market_rs_percentile_12m",
        ),
    )

    candidate_tickers = set(candidates["ticker"])
    investable_tickers = set(investable["ticker"])
    scanner_candidates = scanner[scanner["ticker"].isin(candidate_tickers)].copy()
    scanner_investable = scanner[scanner["ticker"].isin(investable_tickers)].copy()
    candidate_lookup_mismatch_count = _compare_columns(
        scanner_candidates, authority[authority["ticker"].isin(candidate_tickers)], MARKET_COLUMNS
    )
    investable_lookup_mismatch_count = _compare_columns(
        scanner_investable, authority[authority["ticker"].isin(investable_tickers)], MARKET_COLUMNS
    )
    valid_value_missing_rank_count, missing_value_unexpected_rank_count = _population_gate(scanner)

    identity_source = candidates[candidates["ticker"].isin(candidate_tickers)]
    phase10_identity_mismatch_count = _compare_columns(
        scanner_candidates, identity_source, IDENTITY_COLUMNS[:4]
    )
    phase11_identity_mismatch_count = _compare_columns(
        scanner_candidates, identity_source, IDENTITY_COLUMNS[4:]
    )
    pattern_a_candidate_identity_mismatch_count = len(
        set(scanner[scanner["candidate_state"] == "candidate"]["ticker"]) ^ candidate_tickers
    )

    validation = {
        "work_id": "PHASE12_MARKET_RELATIVE_STRENGTH_COMPLETION_V01_FIX01",
        "as_of": AS_OF,
        "universe_common_count": 2528,
        "scanner_output_count": int(len(scanner)),
        "reference_output_count": int(len(authority)),
        "ticker_set_mismatch_count": ticker_set_mismatch_count,
        "market_rs_level_mismatch_count": market_rs_level_mismatch_count,
        "improvement_mismatch_count": improvement_mismatch_count,
        "rank_mismatch_count": rank_mismatch_count,
        "percentile_mismatch_count": percentile_mismatch_count,
        "status_mismatch_count": status_mismatch_count,
        "candidate_lookup_mismatch_count": candidate_lookup_mismatch_count,
        "investable_lookup_mismatch_count": investable_lookup_mismatch_count,
        "valid_value_missing_rank_count": valid_value_missing_rank_count,
        "missing_value_unexpected_rank_count": missing_value_unexpected_rank_count,
        "phase10_identity_mismatch_count": phase10_identity_mismatch_count,
        "phase11_identity_mismatch_count": phase11_identity_mismatch_count,
        "pattern_a_candidate_identity_mismatch_count": pattern_a_candidate_identity_mismatch_count,
        "network_requests": 0,
    }
    mismatch_keys = tuple(key for key in validation if key.endswith("_mismatch_count")) + (
        "valid_value_missing_rank_count",
        "missing_value_unexpected_rank_count",
    )
    validation["overall_operational_parity"] = all(validation[key] == 0 for key in mismatch_keys)
    validation["runtime_seconds"] = round(time.perf_counter() - started, 3)
    _write_json(OUT_DIR / "market_rs_operational_scanner_validation_20260814.json", validation)

    summary = {
        "work_id": validation["work_id"],
        "start_head": START_HEAD,
        "root_causes_fixed": [
            "scanner_cross_section_operational_wiring",
            "sector_mapping_lazy_import_regression",
            "closure_manifest_provenance",
        ],
        "phase12_market_rs_math_changed": False,
        "market_rs_formula_changed": False,
        "rank_formula_changed": False,
        "percentile_formula_changed": False,
        "strategy_semantics_changed": False,
        "sector_rs_scope": "DEFERRED_FUTURE_EXTENSION",
        "network_requests": 0,
        "scanner_summary": scanner_result.summary.to_dict(),
        "operational_validation": validation,
        "ready_for_architect_review": bool(validation["overall_operational_parity"]),
        "legacy_reference_artifact_preserved": True,
        "original_completion_manifest_incomplete_file_list": True,
        "original_completion_commit": START_HEAD,
    }
    _write_json(OUT_DIR / "market_rs_fix01_summary_20260814.json", summary)

    manifest = {
        "work_id": validation["work_id"],
        "start_head": START_HEAD,
        "fix01_implementation_files": [
            "src/trend_scanner/relative_strength/cross_section.py",
            "src/trend_scanner/scanner/full_universe_scanner.py",
            "src/trend_scanner/data/index_price_provider.py",
        ],
        "fix01_validation_files": [
            "scripts/run_phase12_market_relative_strength_fix01.py",
            "tests/test_full_universe_scanner.py",
            "tests/test_index_price_provider.py",
        ],
        "supporting_prior_completion_files": [
            "src/trend_scanner/data/foreign_flow_provider.py",
            "src/trend_scanner/validation/pattern_a_investability_audit.py",
        ],
        "original_completion_manifest_incomplete_file_list": True,
        "original_completion_commit": START_HEAD,
        "network_requests": 0,
        "sector_rs_scope": "DEFERRED_FUTURE_EXTENSION",
        "strategy_semantics_changed": False,
    }
    _write_json(OUT_DIR / "market_rs_fix01_manifest_20260814.json", manifest)

    print(json.dumps(validation, ensure_ascii=False, indent=2))
    return 0 if validation["overall_operational_parity"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
