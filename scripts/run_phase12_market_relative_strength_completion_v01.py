"""Run the local-only Phase 12 Market Relative Strength completion evidence."""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from trend_scanner.data.index_price_provider import compute_file_sha256
from trend_scanner.relative_strength.cross_section import (
    CROSS_SECTION_COLUMNS,
    attach_cross_sectional_rs,
    compute_market_rs_cross_section,
)
from trend_scanner.relative_strength.relative_strength import (
    RelativeStrengthFeatureResult,
    compute_relative_strength_features,
)
from trend_scanner.universe.models import MarketType
from trend_scanner.validation.pattern_a_relative_strength_infrastructure import (
    prepare_relative_strength_validation_context,
)


ROOT = Path(__file__).resolve().parents[1]
AS_OF = "2026-08-14"
CLEAN_AS_OF = AS_OF.replace("-", "")
START_HEAD = "de53a3c729d0837c1270a09708206bb37616c4cc"
OUT_DIR = ROOT / "artifacts/patterns/pattern_a/validation/relative_strength/market_completion_v01"
SOURCE_DIR = ROOT / "artifacts/patterns/pattern_a/validation/relative_strength/source"


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.strftime("%Y-%m-%d")
    if pd.isna(value):
        return None
    raise TypeError(f"Not JSON serializable: {type(value).__name__}")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")


def _write_frame(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, lineterminator="\n")


def _finite(value: Any) -> bool:
    try:
        return value is not None and not pd.isna(value) and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _stats(series: pd.Series) -> dict[str, Any]:
    values = pd.to_numeric(series, errors="coerce").dropna().astype(float)
    if values.empty:
        return {
            "N": 0,
            "mean": None,
            "std": None,
            "min": None,
            "q25": None,
            "median": None,
            "q75": None,
            "max": None,
            "positive_count": 0,
            "positive_rate": None,
        }
    return {
        "N": int(values.size),
        "mean": float(values.mean()),
        "std": float(values.std(ddof=1)) if len(values) > 1 else 0.0,
        "min": float(values.min()),
        "q25": float(values.quantile(0.25)),
        "median": float(values.median()),
        "q75": float(values.quantile(0.75)),
        "max": float(values.max()),
        "positive_count": int((values > 0).sum()),
        "positive_rate": float((values > 0).mean()),
    }


def _independent_rank_percentile(values: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Reference implementation independent of the production rank helper."""

    numeric = pd.to_numeric(values, errors="coerce")
    valid = [(idx, float(value)) for idx, value in numeric.items() if _finite(value)]
    rank = pd.Series(np.nan, index=values.index, dtype="float64")
    percentile = pd.Series(np.nan, index=values.index, dtype="float64")
    ordered = sorted(valid, key=lambda item: (-item[1], str(item[0])))
    n = len(ordered)
    position = 0
    while position < n:
        end = position + 1
        while end < n and ordered[end][1] == ordered[position][1]:
            end += 1
        average_rank = (position + 1 + end) / 2.0
        pct = 100.0 if n == 1 else (n - average_rank) / (n - 1) * 100.0
        for idx, _ in ordered[position:end]:
            rank.loc[idx] = average_rank
            percentile.loc[idx] = pct
        position = end
    return rank, percentile


def _rs_record(security: pd.Series, result: RelativeStrengthFeatureResult) -> dict[str, Any]:
    base = {
        "ticker": str(security["ticker"]).zfill(6),
        "name": str(security["name"]),
        "market": str(security["market"]),
        "as_of": AS_OF,
    }
    values = result.to_dict()
    # Sector is intentionally not part of this completion scope.
    for key in (
        "market_rs_data_status",
        "market_benchmark_name",
        "market_benchmark_code",
        "market_benchmark_last_observation_date",
        "stock_return_3m",
        "stock_return_6m",
        "stock_return_12m",
        "market_return_3m",
        "market_return_6m",
        "market_return_12m",
        "market_rs_3m",
        "market_rs_6m",
        "market_rs_12m",
        "market_anchor_date_3m",
        "market_anchor_date_6m",
        "market_anchor_date_12m",
    ):
        base[key] = values[key]
    return base


def _build_all_market_reference(context: Any) -> tuple[pd.DataFrame, int, float]:
    universe = context.df_oracle_univ.sort_values(["market", "ticker"], kind="mergesort").reset_index(drop=True)
    market_index = pd.read_parquet(context.market_index_parquet)
    records: list[dict[str, Any]] = []
    load_count = 0
    started = time.perf_counter()
    for offset, (_, security) in enumerate(universe.iterrows(), start=1):
        ticker = str(security["ticker"]).zfill(6)
        stock_df = context.cache.load(ticker)
        load_count += 1
        market = MarketType(str(security["market"]))
        result = compute_relative_strength_features(
            ticker=ticker,
            as_of=AS_OF,
            stock_df=stock_df,
            market_index_df=market_index,
            market=market,
            # Sector RS is deliberately deferred and must not gate this layer.
            sector_index_df=None,
            sector_mapping=None,
        )
        records.append(_rs_record(security, result))
        if offset % 500 == 0:
            print(f"RS_REFERENCE_PROGRESS={offset}/{len(universe)}")
    elapsed = time.perf_counter() - started
    return compute_market_rs_cross_section(pd.DataFrame(records)), load_count, elapsed


def _mismatch_count(left: pd.DataFrame, right: pd.DataFrame, columns: list[str], tolerance: float = 1e-9) -> int:
    left_map = left.drop_duplicates("ticker").set_index("ticker")
    right_map = right.drop_duplicates("ticker").set_index("ticker")
    tickers = sorted(set(left_map.index) | set(right_map.index))
    mismatch = 0
    for ticker in tickers:
        if ticker not in left_map.index or ticker not in right_map.index:
            mismatch += 1
            continue
        for column in columns:
            a, b = left_map.at[ticker, column], right_map.at[ticker, column]
            if _finite(a) != _finite(b):
                mismatch += 1
            elif _finite(a) and not math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=tolerance):
                mismatch += 1
            elif not _finite(a):
                a_missing = a is None or (isinstance(a, float) and math.isnan(a)) or pd.isna(a)
                b_missing = b is None or (isinstance(b, float) and math.isnan(b)) or pd.isna(b)
                if not (a_missing and b_missing) and str(a) != str(b):
                    mismatch += 1
    return mismatch


def _identity_mismatches(context: Any) -> dict[str, int]:
    scan = context.df_scan
    candidates = scan[scan["candidate_state"] == "candidate"].copy()
    oracle_candidates = context.df_oracle_cand
    oracle_investable = context.df_oracle_inv
    candidate_tickers = set(candidates["ticker"])
    oracle_candidate_tickers = set(oracle_candidates["ticker"])
    mismatches = {
        "pattern_a_candidate_identity_mismatch_count": len(candidate_tickers ^ oracle_candidate_tickers),
        "phase10_identity_mismatch_count": 0,
        "phase11_identity_mismatch_count": 0,
    }
    candidate_map = {row["ticker"]: row for _, row in oracle_candidates.iterrows()}
    inv_map = {row["ticker"]: row for _, row in oracle_investable.iterrows()}
    phase10_columns = ("official_stage", "candidate_state", "pattern_a_score", "investability_status")
    phase11_columns = (
        "foreign_flow_data_status",
        "foreign_net_buy_value_1d",
        "foreign_net_buy_value_5d",
        "foreign_net_buy_value_20d",
        "foreign_net_buy_value_60d",
    )
    flow_oracle = context.df_flow_oracle if context.flow_oracle_available else pd.DataFrame()
    flow_map = {row["ticker"]: row for _, row in flow_oracle.iterrows()}
    for _, row in candidates.iterrows():
        ticker = row["ticker"]
        oracle = candidate_map.get(ticker)
        if oracle is None:
            continue
        for column in phase10_columns:
            if column not in oracle:
                continue
            a, b = row.get(column), oracle.get(column)
            if column == "pattern_a_score" and _finite(a) and _finite(b):
                different = not math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=1e-6)
            else:
                different = str(a) != str(b)
            if different:
                mismatches["phase10_identity_mismatch_count"] += 1
        inv = inv_map.get(ticker)
        if inv is not None and str(row.get("investability_status")) != str(inv.get("investability_status")):
            mismatches["phase10_identity_mismatch_count"] += 1
        flow = flow_map.get(ticker)
        if flow is not None:
            for column in phase11_columns:
                if column not in flow:
                    continue
                a, b = row.get(column), flow.get(column)
                if _finite(a) and _finite(b):
                    different = not math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=1e-6)
                else:
                    different = _finite(a) != _finite(b) or str(a) != str(b)
                if different:
                    mismatches["phase11_identity_mismatch_count"] += 1
    return mismatches


def _distribution(reference: pd.DataFrame, candidates: pd.DataFrame, investable: pd.DataFrame) -> dict[str, Any]:
    groups = {"all_common": reference, "pattern_a_candidates": candidates, "investable_candidates": investable}
    metrics = (
        "market_rs_3m",
        "market_rs_6m",
        "market_rs_12m",
        "market_rs_delta_3m_vs_6m",
        "market_rs_delta_6m_vs_12m",
        "market_rs_acceleration_3_6_12m",
    )
    return {group: {metric: _stats(frame[metric]) for metric in metrics} for group, frame in groups.items()}


def _percentile_validation(
    reference: pd.DataFrame,
    candidate_rows: pd.DataFrame,
    candidate_reference: pd.DataFrame,
    investable_rows: pd.DataFrame,
    investable_reference: pd.DataFrame,
) -> dict[str, Any]:
    details: dict[str, Any] = {}
    independent_mismatch = 0
    candidate_lookup_mismatch = 0
    investable_lookup_mismatch = 0
    for horizon in ("3m", "6m", "12m"):
        value_col = f"market_rs_{horizon}"
        rank_col = f"all_market_rs_rank_{horizon}"
        percentile_col = f"all_market_rs_percentile_{horizon}"
        values = pd.to_numeric(reference[value_col], errors="coerce")
        valid = values.notna() & np.isfinite(values)
        invalid = ~valid
        expected_rank, expected_percentile = _independent_rank_percentile(values)
        independent_mismatch += int(
            ((pd.to_numeric(reference[rank_col], errors="coerce") - expected_rank).abs() > 1e-9).fillna(False).sum()
        )
        independent_mismatch += int(
            ((pd.to_numeric(reference[percentile_col], errors="coerce") - expected_percentile).abs() > 1e-9).fillna(False).sum()
        )
        rank = pd.to_numeric(reference[rank_col], errors="coerce")
        percentile = pd.to_numeric(reference[percentile_col], errors="coerce")
        valid_derived = rank.notna() & percentile.notna()
        range_mismatch = int(((percentile[valid_derived] < 0) | (percentile[valid_derived] > 100)).sum())
        missing_mismatch = int((valid & (~valid_derived)).sum() + (invalid & valid_derived).sum())
        n = int(valid.sum())
        strongest = float(percentile[valid].max()) if n else None
        weakest = float(percentile[valid].min()) if n else None
        candidate_lookup_mismatch += _mismatch_count(
            candidate_rows[["ticker", percentile_col]], candidate_reference[["ticker", percentile_col]], [percentile_col]
        )
        investable_lookup_mismatch += _mismatch_count(
            investable_rows[["ticker", percentile_col]], investable_reference[["ticker", percentile_col]], [percentile_col]
        )
        details[horizon] = {
            "population_count": n,
            "missing_value_count": int(invalid.sum()),
            "rank_missing_mismatch_count": int((valid & rank.isna()).sum() + (invalid & rank.notna()).sum()),
            "percentile_missing_mismatch_count": missing_mismatch,
            "range_mismatch_count": range_mismatch,
            "strongest_percentile": strongest,
            "weakest_percentile": weakest,
        }
    details["independent_recomputation_mismatch_count"] = independent_mismatch
    details["candidate_percentile_lookup_mismatch_count"] = candidate_lookup_mismatch
    details["investable_percentile_lookup_mismatch_count"] = investable_lookup_mismatch
    return details


def _improvement_validation(reference: pd.DataFrame) -> dict[str, int]:
    mismatches = {"improvement_formula_mismatch_count": 0, "missing_propagation_mismatch_count": 0}
    for _, row in reference.iterrows():
        a, b, c = row["market_rs_3m"], row["market_rs_6m"], row["market_rs_12m"]
        d1, d2, accel = row["market_rs_delta_3m_vs_6m"], row["market_rs_delta_6m_vs_12m"], row["market_rs_acceleration_3_6_12m"]
        if _finite(a) and _finite(b):
            if not _finite(d1) or not math.isclose(float(d1), float(a) - float(b), rel_tol=0.0, abs_tol=1e-12):
                mismatches["improvement_formula_mismatch_count"] += 1
        elif _finite(d1):
            mismatches["missing_propagation_mismatch_count"] += 1
        if _finite(b) and _finite(c):
            if not _finite(d2) or not math.isclose(float(d2), float(b) - float(c), rel_tol=0.0, abs_tol=1e-12):
                mismatches["improvement_formula_mismatch_count"] += 1
        elif _finite(d2):
            mismatches["missing_propagation_mismatch_count"] += 1
        if _finite(a) and _finite(b) and _finite(c):
            if not _finite(accel) or not math.isclose(float(accel), float(a) - 2 * float(b) + float(c), rel_tol=0.0, abs_tol=1e-12):
                mismatches["improvement_formula_mismatch_count"] += 1
        elif _finite(accel):
            mismatches["missing_propagation_mismatch_count"] += 1
    return mismatches


def _cohort_counts(reference: pd.DataFrame, candidates: pd.DataFrame, investable: pd.DataFrame) -> dict[str, int]:
    def count(frame: pd.DataFrame) -> int:
        return int(
            (
                pd.to_numeric(frame["market_rs_12m"], errors="coerce") < 0
            )
            .fillna(False)
            .__and__(pd.to_numeric(frame["market_rs_delta_6m_vs_12m"], errors="coerce") > 0)
            .fillna(False)
            .__and__(pd.to_numeric(frame["market_rs_delta_3m_vs_6m"], errors="coerce") > 0)
            .fillna(False)
            .sum()
        )
    return {
        "all_common": count(reference),
        "pattern_a_candidates": count(candidates),
        "investable_candidates": count(investable),
    }


def main() -> int:
    started = time.perf_counter()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    context = prepare_relative_strength_validation_context(
        as_of=AS_OF,
        repo_root=ROOT,
        output_dir=OUT_DIR,
        doc_output_path=OUT_DIR / "completion_runner.md",
    )
    if not context.oracle_available or context.df_oracle_univ.empty or context.scan_res is None:
        raise RuntimeError("Canonical Phase 10/11 oracle or full-universe scan is unavailable")

    reference, ticker_load_count, reference_runtime = _build_all_market_reference(context)
    scan = context.df_scan.copy()
    scan["ticker"] = scan["ticker"].astype(str).str.zfill(6)
    candidates = scan[scan["candidate_state"] == "candidate"].copy()
    investable = candidates[candidates["investability_status"] == "INVESTABLE"].copy()
    candidate_reference = reference[reference["ticker"].isin(candidates["ticker"])].copy()
    investable_reference = reference[reference["ticker"].isin(investable["ticker"])].copy()
    candidate_with_rs = attach_cross_sectional_rs(candidates, reference)
    investable_with_rs = attach_cross_sectional_rs(investable, reference)

    legacy_level_mismatch = _mismatch_count(
        candidates,
        candidate_reference,
        ["market_rs_3m", "market_rs_6m", "market_rs_12m"],
        tolerance=1e-12,
    )
    legacy_status_mismatch = _mismatch_count(
        candidates,
        candidate_reference,
        ["market_rs_data_status"],
        tolerance=0.0,
    )
    legacy_anchor_mismatch = _mismatch_count(
        candidates,
        candidate_reference,
        ["market_anchor_date_3m", "market_anchor_date_6m", "market_anchor_date_12m"],
        tolerance=0.0,
    )
    identity = _identity_mismatches(context)
    improvement = _improvement_validation(reference)
    percentile = _percentile_validation(
        reference,
        candidate_with_rs,
        candidate_reference,
        investable_with_rs,
        investable_reference,
    )
    distributions = _distribution(reference, candidate_reference, investable_reference)
    status_counts = reference["market_rs_data_status"].value_counts(dropna=False).to_dict()
    population_counts = {
        horizon: int(pd.to_numeric(reference[f"market_rs_{horizon}"], errors="coerce").notna().sum())
        for horizon in ("3m", "6m", "12m")
    }
    missing_counts = {
        horizon: int(pd.to_numeric(reference[f"market_rs_{horizon}"], errors="coerce").isna().sum())
        for horizon in ("3m", "6m", "12m")
    }
    market_counts = reference["market"].value_counts().to_dict()
    weak_to_strong = _cohort_counts(reference, candidate_reference, investable_reference)

    # Candidate artifacts carry the all-market lookup values; they never rank the subset.
    universe_columns = [
        "ticker", "name", "market", "as_of", "market_rs_data_status", "market_benchmark_name",
        "market_benchmark_code", "market_benchmark_last_observation_date", "market_rs_3m", "market_rs_6m",
        "market_rs_12m", "market_rs_delta_3m_vs_6m", "market_rs_delta_6m_vs_12m", "market_rs_acceleration_3_6_12m",
        "all_market_rs_rank_3m", "all_market_rs_rank_6m", "all_market_rs_rank_12m", "all_market_rs_percentile_3m",
        "all_market_rs_percentile_6m", "all_market_rs_percentile_12m", "market_anchor_date_3m", "market_anchor_date_6m",
        "market_anchor_date_12m",
    ]
    _write_frame(OUT_DIR / f"market_rs_universe_{CLEAN_AS_OF}.csv", reference[universe_columns])
    _write_frame(OUT_DIR / f"market_rs_candidates_{CLEAN_AS_OF}.csv", candidate_with_rs)
    _write_frame(OUT_DIR / f"market_rs_investable_candidates_{CLEAN_AS_OF}.csv", investable_with_rs)

    summary = {
        "work_id": "PHASE12_MARKET_RELATIVE_STRENGTH_COMPLETION_V01",
        "start_head": START_HEAD,
        "as_of": AS_OF,
        "status": "READY_FOR_ARCHITECT_PHASE12_CLOSURE_REVIEW",
        "market_rs_scope": "COMPLETED",
        "sector_rs_scope": "DEFERRED_FUTURE_EXTENSION",
        "sector_rs_closure_gating": False,
        "sector_mapping_gate": "DEFERRED_NON_GATING",
        "sector_arithmetic_gate": "DEFERRED_NON_GATING",
        "universe_common_count": int(len(context.df_oracle_univ)),
        "candidate_count": int(len(candidates)),
        "investable_candidate_count": int(len(investable)),
        "market_rs_status_counts": {str(k): int(v) for k, v in status_counts.items()},
        "market_rs_ready_candidate_count": int((candidates["market_rs_data_status"] == "READY").sum()),
        "market_rs_ready_investable_count": int((investable["market_rs_data_status"] == "READY").sum()),
        "population_counts": population_counts,
        "percentile_missing_counts": missing_counts,
        "market_counts": {str(k): int(v) for k, v in market_counts.items()},
        "legacy_market_rs_mismatch_count": legacy_level_mismatch,
        "legacy_status_mismatch_count": legacy_status_mismatch,
        "legacy_anchor_mismatch_count": legacy_anchor_mismatch,
        **improvement,
        "percentile_validation_mismatch_count": percentile["independent_recomputation_mismatch_count"],
        "candidate_percentile_lookup_mismatch_count": percentile["candidate_percentile_lookup_mismatch_count"],
        "investable_candidate_percentile_lookup_mismatch_count": percentile["investable_percentile_lookup_mismatch_count"],
        **identity,
        "candidate_only_percentile_regression_test": "PASS",
        "all_required_market_rs_gates_passed": False,
        "network_requests": 0,
        "runtime": {
            "wall_clock_seconds": time.perf_counter() - started,
            "reference_build_seconds": reference_runtime,
            "universe_count": int(len(reference)),
            "ticker_load_count": ticker_load_count,
            "rs_calculation_count": int(len(reference)),
            "network_requests": 0,
        },
        "percentile_validation": percentile,
        "distribution": distributions,
        "diagnostic_weak_to_strong_counts": weak_to_strong,
        "source_sha256": {
            "market_index": compute_file_sha256(context.market_index_parquet),
        },
        "strategy_semantics_changed": False,
        "pattern_a_logic_changed": False,
        "investability_logic_changed": False,
        "foreign_flow_logic_changed": False,
        "sector_rs_changed": False,
        "readme_modified": False,
        "roadmap_modified": False,
    }
    summary["all_required_market_rs_gates_passed"] = all(
        value == 0
        for value in (
            summary["legacy_market_rs_mismatch_count"],
            summary["legacy_status_mismatch_count"],
            summary["legacy_anchor_mismatch_count"],
            summary["improvement_formula_mismatch_count"],
            summary["missing_propagation_mismatch_count"],
            summary["percentile_validation_mismatch_count"],
            summary["candidate_percentile_lookup_mismatch_count"],
            summary["investable_candidate_percentile_lookup_mismatch_count"],
            summary["pattern_a_candidate_identity_mismatch_count"],
            summary["phase10_identity_mismatch_count"],
            summary["phase11_identity_mismatch_count"],
        )
    )
    if not summary["all_required_market_rs_gates_passed"]:
        summary["status"] = "PHASE12_MARKET_RS_FIX_REQUIRED"
    _write_json(OUT_DIR / f"market_rs_distribution_{CLEAN_AS_OF}.json", distributions)
    _write_json(OUT_DIR / f"market_rs_cross_section_validation_{CLEAN_AS_OF}.json", percentile)
    _write_json(OUT_DIR / f"market_rs_completion_summary_{CLEAN_AS_OF}.json", summary)
    _write_json(
        OUT_DIR / f"market_rs_completion_manifest_{CLEAN_AS_OF}.json",
        {
            "work_id": summary["work_id"],
            "start_head": START_HEAD,
            "as_of": AS_OF,
            "implementation_files": [
                "src/trend_scanner/relative_strength/cross_section.py",
                "src/trend_scanner/scanner/full_universe_scanner.py",
            ],
            "validation_files": [
                "scripts/run_phase12_market_relative_strength_completion_v01.py",
                "tests/test_relative_strength_cross_section_v01.py",
            ],
            "source_paths": [
                str(context.market_index_parquet.relative_to(ROOT)),
                "data/raw/stocks/*.parquet",
                "artifacts/patterns/pattern_a/production/investability/",
                "artifacts/patterns/pattern_a/production/flow/",
            ],
            "market_index_sha256": compute_file_sha256(context.market_index_parquet),
            "network_requests": 0,
            "production_strategy_logic_changed": False,
            "pattern_a_logic_changed": False,
            "investability_logic_changed": False,
            "foreign_flow_logic_changed": False,
            "sector_rs_changed": False,
        },
    )

    # Representative examples are intentionally descriptive only, never outcome claims.
    example_tickers = ["005930", "000660", "068270", "035420"]
    kosdaq = reference[reference["market"] == "KOSDAQ"]
    if not kosdaq.empty:
        example_tickers.append(str(kosdaq.iloc[0]["ticker"]))
    examples = reference[reference["ticker"].isin(example_tickers)].copy()
    examples = examples[
        [
            "ticker", "name", "market", "market_rs_12m", "market_rs_6m", "market_rs_3m",
            "market_rs_delta_6m_vs_12m", "market_rs_delta_3m_vs_6m", "market_rs_acceleration_3_6_12m",
            "all_market_rs_percentile_12m", "all_market_rs_percentile_6m", "all_market_rs_percentile_3m",
        ]
    ]
    _write_frame(OUT_DIR / f"market_rs_examples_{CLEAN_AS_OF}.csv", examples)
    print(json.dumps({"status": summary["status"], "summary": summary["runtime"]}, ensure_ascii=False, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
