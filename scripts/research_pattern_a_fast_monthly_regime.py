#!/usr/bin/env python
"""Phase 13D — Monthly Regime Feature Research (RESEARCH ONLY, not Freeze).

Loads the 40 Human Calibration samples (weekly_stage_at_reference != UNLABELED
AND human_label != UNLABELED) from the frozen 13C Human Worksheet, computes
PIT-safe monthly regime feature candidates (§6 of the Phase 13D w.md) for
each, and produces:

    artifacts/pattern_a_fast/research/monthly_regime_feature_matrix_v01.csv
    artifacts/pattern_a_fast/research/monthly_regime_feature_summary_v01.csv

This script reuses the frozen 13C loading conventions (ParquetCache-only,
build_historical_snapshot for completed-period PIT slicing) without
modifying them. It does NOT decide a Monthly PASS/FAIL rule, a numeric
threshold, or a production Feature Set — see
docs/patterns/pattern_a_fast/research/monthly_regime_features_v01.md.

Usage:
    uv run python scripts/research_pattern_a_fast_monthly_regime.py
"""

from __future__ import annotations

import itertools
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.research.pattern_a_fast_monthly_features import (
    DIAGNOSTIC_ONLY_FEATURES,
    FEATURE_NAMES,
    compute_monthly_regime_features,
)
from trend_scanner.validation.historical_snapshot import build_historical_snapshot
from trend_scanner.validation.pattern_a_fast_ground_truth import load_raw_daily

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("research_pattern_a_fast_monthly_regime")

BASE_COMMIT = "2e5a87f8214fe91d6cd2dbfa2bdc03cc2453d696"
WORKSHEET_CSV = Path("artifacts/pattern_a_fast/ground_truth/pattern_a_fast_human_review_v01.csv")
SOURCE_CSV = Path("artifacts/pattern_a_fast/ground_truth/pattern_a_fast_ground_truth_source_v01.csv")
OUTPUT_DIR = Path("artifacts/pattern_a_fast/research")

ANALYSIS_FEATURES = [n for n in FEATURE_NAMES if n not in DIAGNOSTIC_ONLY_FEATURES]

RESEARCH_GROUPS = {
    "POSITIVE_STRUCTURE": {"GOOD_TRIGGER", "BORDERLINE_TRIGGER"},
    "FAILED_STRUCTURE": {"FALSE_TRIGGER"},
    "EARLY_OR_NONE": {"TOO_EARLY", "NO_SETUP"},
    "LATE_OR_EXTENDED": {"TOO_LATE", "TOO_EXTENDED"},
}

LABEL_PAIR_COMPARISONS = [
    ("GOOD_TRIGGER", "NO_SETUP"),
    ("GOOD_TRIGGER", "TOO_EARLY"),
    ("GOOD_TRIGGER", "FALSE_TRIGGER"),
    ("GOOD_TRIGGER", "TOO_EXTENDED"),
]

cache = ParquetCache()


def cliffs_delta(x: list[float], y: list[float]) -> float | None:
    """비모수 separation metric. x가 y보다 클수록 +1에 가깝다.
    n<2인 그룹이 하나라도 있으면 None(순위 산정 불가 — descriptive만 가능)."""
    x = [v for v in x if not np.isnan(v)]
    y = [v for v in y if not np.isnan(v)]
    if len(x) < 2 or len(y) < 2:
        return None
    gt = sum(1 for xi, yj in itertools.product(x, y) if xi > yj)
    lt = sum(1 for xi, yj in itertools.product(x, y) if xi < yj)
    return (gt - lt) / (len(x) * len(y))


def median_diff_and_standardized(x: list[float], y: list[float]) -> tuple[float | None, float | None]:
    """§12 요구사항: median 차이와 pooled-IQR로 표준화한 effect size.
    x_median - y_median, (x_median - y_median) / pooled_IQR(x+y).
    pooled_IQR==0(값이 상수)이거나 그룹 중 하나라도 비어 있으면 standardized는 None."""
    x = [v for v in x if not np.isnan(v)]
    y = [v for v in y if not np.isnan(v)]
    if not x or not y:
        return None, None
    med_diff = float(np.median(x) - np.median(y))
    pooled = np.array(x + y)
    iqr = float(np.quantile(pooled, 0.75) - np.quantile(pooled, 0.25))
    standardized = med_diff / iqr if iqr > 0 else None
    return med_diff, standardized


def load_labeled_samples() -> pd.DataFrame:
    review = pd.read_csv(WORKSHEET_CSV, dtype=str, keep_default_na=False)
    source = pd.read_csv(SOURCE_CSV, dtype=str, keep_default_na=False)
    labeled = review[
        (review["weekly_stage_at_reference"] != "UNLABELED")
        & (review["human_label"] != "UNLABELED")
    ].copy()
    assert len(labeled) == 40, f"expected 40 labeled samples, got {len(labeled)}"
    assert labeled["sample_id"].nunique() == 40, "duplicate sample_id in labeled set"
    merged = labeled.merge(
        source[["sample_id", "source_cohort", "source_reason"]], on="sample_id", how="left"
    )
    assert len(merged) == 40
    return merged


def build_feature_matrix(labeled: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for _, row in labeled.iterrows():
        ticker = row["ticker"]
        reference_date = pd.Timestamp(row["reference_date"])
        daily = load_raw_daily(ticker, cache)
        if daily is None:
            raise RuntimeError(f"CACHE_MISSING for frozen sample {row['sample_id']} — should never happen")

        snapshot = build_historical_snapshot(
            ticker, row["name"], daily, reference_date, include_incomplete_periods=False
        )
        # Leakage guard: PIT monthly data must never extend past reference_date.
        assert snapshot.monthly.empty or snapshot.monthly.index.max() <= reference_date

        features = compute_monthly_regime_features(snapshot.monthly)
        missing_count = sum(1 for name in ANALYSIS_FEATURES if np.isnan(features.get(name, np.nan)))

        record = {
            "sample_id": row["sample_id"],
            "ticker": ticker,
            "name": row["name"],
            "reference_date": row["reference_date"],
            "weekly_stage_at_reference": row["weekly_stage_at_reference"],
            "human_label": row["human_label"],
            "human_confidence": row["human_confidence"],
            "source_cohort": row["source_cohort"],
            "source_reason": row["source_reason"],
            "monthly_feature_status": "OK" if missing_count == 0 else "PARTIAL",
            "monthly_feature_missing_count": missing_count,
        }
        record.update(features)
        rows.append(record)

    matrix = pd.DataFrame(rows)
    assert matrix["sample_id"].nunique() == 40
    return matrix


def build_summary(matrix: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for feature in ANALYSIS_FEATURES:
        col = matrix[feature]
        valid = col.dropna()
        row = {
            "feature_name": feature,
            "count": int(valid.count()),
            "missing_count": int(col.isna().sum()),
            "mean": valid.mean() if len(valid) else np.nan,
            "median": valid.median() if len(valid) else np.nan,
            "std": valid.std() if len(valid) else np.nan,
            "min": valid.min() if len(valid) else np.nan,
            "max": valid.max() if len(valid) else np.nan,
            "p25": valid.quantile(0.25) if len(valid) else np.nan,
            "p75": valid.quantile(0.75) if len(valid) else np.nan,
        }
        for label, group in matrix.groupby("human_label"):
            g = group[feature].dropna()
            row[f"{label}_n"] = int(len(group[feature]))
            row[f"{label}_median"] = g.median() if len(g) else np.nan
            row[f"{label}_iqr"] = (g.quantile(0.75) - g.quantile(0.25)) if len(g) else np.nan
        for group_name, labels in RESEARCH_GROUPS.items():
            g = matrix.loc[matrix["human_label"].isin(labels), feature].dropna()
            row[f"GROUP_{group_name}_n"] = int(matrix["human_label"].isin(labels).sum())
            row[f"GROUP_{group_name}_median"] = g.median() if len(g) else np.nan
            row[f"GROUP_{group_name}_iqr"] = (g.quantile(0.75) - g.quantile(0.25)) if len(g) else np.nan
        for label_a, label_b in LABEL_PAIR_COMPARISONS:
            xa = matrix.loc[matrix["human_label"] == label_a, feature].tolist()
            xb = matrix.loc[matrix["human_label"] == label_b, feature].tolist()
            delta = cliffs_delta(xa, xb)
            med_diff, standardized = median_diff_and_standardized(xa, xb)
            row[f"cliffs_delta_{label_a}_vs_{label_b}"] = delta
            row[f"median_diff_{label_a}_vs_{label_b}"] = med_diff
            row[f"standardized_effect_{label_a}_vs_{label_b}"] = standardized
        # SETUP->GOOD_TRIGGER vs WATCH->TOO_EARLY/NO_SETUP
        setup_good = matrix.loc[
            (matrix["weekly_stage_at_reference"] == "SETUP") & (matrix["human_label"] == "GOOD_TRIGGER"),
            feature,
        ].tolist()
        watch_early_none = matrix.loc[
            (matrix["weekly_stage_at_reference"] == "WATCH")
            & (matrix["human_label"].isin({"TOO_EARLY", "NO_SETUP"})),
            feature,
        ].tolist()
        setup_watch_med_diff, setup_watch_standardized = median_diff_and_standardized(setup_good, watch_early_none)
        row["cliffs_delta_SETUP_GOOD_vs_WATCH_EARLY_NONE"] = cliffs_delta(setup_good, watch_early_none)
        row["median_diff_SETUP_GOOD_vs_WATCH_EARLY_NONE"] = setup_watch_med_diff
        row["standardized_effect_SETUP_GOOD_vs_WATCH_EARLY_NONE"] = setup_watch_standardized
        row["n_SETUP_GOOD"] = len(setup_good)
        row["n_WATCH_EARLY_NONE"] = len(watch_early_none)
        rows.append(row)
    return pd.DataFrame(rows)


def correlation_findings(matrix: pd.DataFrame, threshold: float = 0.85) -> pd.DataFrame:
    corr = matrix[ANALYSIS_FEATURES].corr(method="spearman")
    findings = []
    for i, a in enumerate(ANALYSIS_FEATURES):
        for b in ANALYSIS_FEATURES[i + 1 :]:
            value = corr.loc[a, b]
            if pd.notna(value) and abs(value) >= threshold:
                findings.append({"feature_a": a, "feature_b": b, "spearman_corr": value})
    return pd.DataFrame(findings).sort_values("spearman_corr", key=abs, ascending=False) if findings else pd.DataFrame(
        columns=["feature_a", "feature_b", "spearman_corr"]
    )


def main() -> None:
    labeled = load_labeled_samples()
    logger.info("Loaded %d Human Calibration samples (weekly_stage & human_label both != UNLABELED)", len(labeled))

    matrix = build_feature_matrix(labeled)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    matrix_path = OUTPUT_DIR / "monthly_regime_feature_matrix_v01.csv"
    matrix.to_csv(matrix_path, index=False)

    summary = build_summary(matrix)
    summary_path = OUTPUT_DIR / "monthly_regime_feature_summary_v01.csv"
    summary.to_csv(summary_path, index=False)

    corr_df = correlation_findings(matrix)
    corr_path = OUTPUT_DIR / "monthly_regime_feature_correlation_v01.csv"
    corr_df.to_csv(corr_path, index=False)

    logger.info("==================================================")
    logger.info("Feature matrix: %s (%d rows, %d feature columns)", matrix_path, len(matrix), len(ANALYSIS_FEATURES))
    logger.info("Feature summary: %s (%d features)", summary_path, len(summary))
    logger.info("High-correlation (|spearman|>=0.85) pairs: %d -> %s", len(corr_df), corr_path)
    logger.info("monthly_feature_status counts: %s", matrix["monthly_feature_status"].value_counts().to_dict())
    logger.info("Total missing feature cells: %d", matrix["monthly_feature_missing_count"].sum())
    logger.info("==================================================")


if __name__ == "__main__":
    main()
