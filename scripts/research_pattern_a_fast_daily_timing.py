#!/usr/bin/env python
"""Phase 13F — Daily Timing Feature Research (RESEARCH ONLY, not Freeze).

Loads the 40 Human Calibration samples (weekly_stage_at_reference != UNLABELED
AND human_label != UNLABELED) from the frozen 13C Human Worksheet, computes
PIT-safe daily timing feature candidates (§7 of the Phase 13F w.md) for
each, and produces:

    artifacts/patterns/pattern_a_fast/research/feature_role/daily_timing_feature_matrix_v01.csv
    artifacts/patterns/pattern_a_fast/research/feature_role/daily_timing_feature_summary_v01.csv
    artifacts/patterns/pattern_a_fast/research/feature_role/daily_timing_feature_correlation_v01.csv
    artifacts/patterns/pattern_a_fast/research/feature_role/daily_timing_stage_summary_v01.csv
    artifacts/patterns/pattern_a_fast/research/feature_role/monthly_weekly_daily_research_join_v01.csv

This script reuses the frozen 13C loading conventions (ParquetCache-only)
without modifying them. Per w.md §10, it does NOT extend
``HistoricalSnapshot`` with a daily field — it slices the raw
``load_raw_daily()`` output directly (``daily[daily.index <= reference_date]``).
It does NOT decide a Daily Entry rule, a numeric threshold, a classifier, a
score, or an optimal entry date — see
docs/patterns/pattern_a_fast/research/daily_timing_features_v01.md.

Usage:
    uv run python scripts/research_pattern_a_fast_daily_timing.py
"""

from __future__ import annotations

import itertools
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.research.pattern_a_fast_daily_features import (
    DIAGNOSTIC_ONLY_FEATURES,
    FEATURE_NAMES,
    compute_daily_timing_features,
)
from trend_scanner.validation.pattern_a_fast_ground_truth import load_raw_daily

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("research_pattern_a_fast_daily_timing")

BASE_COMMIT = "415583ab97835d6d98c945476de45aafdd6371b7"
WORKSHEET_CSV = Path("artifacts/patterns/pattern_a_fast/validation/ground_truth/pattern_a_fast_human_review_v01.csv")
SOURCE_CSV = Path("artifacts/patterns/pattern_a_fast/validation/ground_truth/pattern_a_fast_ground_truth_source_v01.csv")
MONTHLY_MATRIX_CSV = Path("artifacts/patterns/pattern_a_fast/research/feature_role/monthly_regime_feature_matrix_v01.csv")
WEEKLY_MATRIX_CSV = Path("artifacts/patterns/pattern_a_fast/research/feature_role/weekly_trigger_feature_matrix_v01.csv")
OUTPUT_DIR = Path("artifacts/patterns/pattern_a_fast/research/feature_role")

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

# Phase 13D / 13E HIGH 후보(reference metadata로만 join, 이 스크립트에서 재계산하지 않음)
MONTHLY_HIGH_CANDIDATES = [
    "range_position_24m",
    "drawdown_from_12m_high",
    "close_vs_ma24_pct",
    "ma_alignment_score",
    "monthly_down_month_ratio_12m",
    "higher_monthly_low_count_12m",
    "recent_3m_return",
]
WEEKLY_HIGH_CANDIDATES = [
    "post_breakout_min_low_vs_level_pct_26w",
    "close_vs_wma200_pct",
    "distance_to_prior_26w_high_pct",
    "higher_weekly_low_count_13w",
    "wma52_slope_1w",
    "wma12_vs_wma26_pct",
    "rolling_low_4w_change",
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
    """median 차이와 pooled-IQR로 표준화한 effect size. 표준화 지표의
    분모는 두 그룹을 합친 전체 표본의 IQR이다 — 완벽 분리 시 분모 자체가
    커지므로 이 지표는 분리가 가장 좋을 때 오히려 작게 나올 수 있다
    (Cliff's Delta가 1차 근거인 이유, 13D/13E와 동일)."""
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

        pit_daily = daily[daily.index <= reference_date]
        # Leakage guard: PIT daily data must never extend past reference_date.
        assert pit_daily.empty or pit_daily.index.max() <= reference_date

        features = compute_daily_timing_features(pit_daily)
        missing_count = sum(1 for name in ANALYSIS_FEATURES if np.isnan(features.get(name, np.nan)))
        effective_as_of = pit_daily.index.max() if len(pit_daily) else None

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
            "daily_feature_status": "OK" if missing_count == 0 else "PARTIAL",
            "daily_feature_missing_count": missing_count,
            "completed_daily_bars_at_reference": len(pit_daily),
            "effective_daily_as_of": effective_as_of,
        }
        record.update(features)
        rows.append(record)

    matrix = pd.DataFrame(rows)
    assert matrix["sample_id"].nunique() == 40
    return matrix


def _pair_stats(matrix: pd.DataFrame, feature: str, xa: list[float], xb: list[float], suffix: str) -> dict:
    delta = cliffs_delta(xa, xb)
    med_diff, standardized = median_diff_and_standardized(xa, xb)
    return {
        f"cliffs_delta_{suffix}": delta,
        f"median_diff_{suffix}": med_diff,
        f"standardized_effect_{suffix}": standardized,
    }


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
            row[f"{label}_n"] = int(len(g))
            row[f"{label}_median"] = g.median() if len(g) else np.nan
            row[f"{label}_iqr"] = (g.quantile(0.75) - g.quantile(0.25)) if len(g) else np.nan
        for stage, group in matrix.groupby("weekly_stage_at_reference"):
            g = group[feature].dropna()
            row[f"STAGE_{stage}_n"] = int(len(g))
            row[f"STAGE_{stage}_median"] = g.median() if len(g) else np.nan
            row[f"STAGE_{stage}_iqr"] = (g.quantile(0.75) - g.quantile(0.25)) if len(g) else np.nan
        for group_name, labels in RESEARCH_GROUPS.items():
            g = matrix.loc[matrix["human_label"].isin(labels), feature].dropna()
            row[f"GROUP_{group_name}_n"] = int(len(g))
            row[f"GROUP_{group_name}_median"] = g.median() if len(g) else np.nan
            row[f"GROUP_{group_name}_iqr"] = (g.quantile(0.75) - g.quantile(0.25)) if len(g) else np.nan
        for label_a, label_b in LABEL_PAIR_COMPARISONS:
            xa = matrix.loc[matrix["human_label"] == label_a, feature].tolist()
            xb = matrix.loc[matrix["human_label"] == label_b, feature].tolist()
            row.update(_pair_stats(matrix, feature, xa, xb, f"{label_a}_vs_{label_b}"))
        setup_good = matrix.loc[
            (matrix["weekly_stage_at_reference"] == "SETUP") & (matrix["human_label"] == "GOOD_TRIGGER"),
            feature,
        ].tolist()
        watch_early_none = matrix.loc[
            (matrix["weekly_stage_at_reference"] == "WATCH")
            & (matrix["human_label"].isin({"TOO_EARLY", "NO_SETUP"})),
            feature,
        ].tolist()
        row.update(_pair_stats(matrix, feature, setup_good, watch_early_none, "SETUP_GOOD_vs_WATCH_EARLY_NONE"))
        row["n_SETUP_GOOD"] = sum(1 for v in setup_good if not np.isnan(v))
        row["n_WATCH_EARLY_NONE"] = sum(1 for v in watch_early_none if not np.isnan(v))

        positive = matrix.loc[matrix["human_label"].isin(RESEARCH_GROUPS["POSITIVE_STRUCTURE"]), feature].tolist()
        early_none = matrix.loc[matrix["human_label"].isin(RESEARCH_GROUPS["EARLY_OR_NONE"]), feature].tolist()
        row.update(_pair_stats(matrix, feature, positive, early_none, "POSITIVE_STRUCTURE_vs_EARLY_OR_NONE"))
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


def build_stage_summary(matrix: pd.DataFrame) -> pd.DataFrame:
    """PIT Weekly Stage별 n과, 각 stage가 어떤 human_label로 발전했는지
    분포. TRIGGER n=1이므로 이 표는 descriptive 참고용이다(w.md §32)."""
    rows = []
    for stage, group in matrix.groupby("weekly_stage_at_reference"):
        row = {"weekly_stage_at_reference": stage, "n": len(group)}
        for label, count in group["human_label"].value_counts().items():
            row[f"outcome_{label}"] = int(count)
        rows.append(row)
    return pd.DataFrame(rows)


def build_monthly_weekly_daily_join(matrix: pd.DataFrame) -> pd.DataFrame | None:
    """w.md §17 권장 join view: 13D/13E frozen matrix(재계산하지 않음)를
    읽어 각각의 HIGH 후보만 골라 13F matrix에 sample_id 기준으로 붙인다."""
    if not MONTHLY_MATRIX_CSV.exists() or not WEEKLY_MATRIX_CSV.exists():
        logger.warning(
            "Monthly(%s) or Weekly(%s) matrix not found -> join skipped",
            MONTHLY_MATRIX_CSV, WEEKLY_MATRIX_CSV,
        )
        return None
    monthly = pd.read_csv(MONTHLY_MATRIX_CSV)
    monthly_cols = ["sample_id"] + [c for c in MONTHLY_HIGH_CANDIDATES if c in monthly.columns]
    monthly_slim = monthly[monthly_cols].rename(
        columns={c: f"MONTHLY_{c}" for c in MONTHLY_HIGH_CANDIDATES if c in monthly.columns}
    )
    weekly = pd.read_csv(WEEKLY_MATRIX_CSV)
    weekly_cols = ["sample_id"] + [c for c in WEEKLY_HIGH_CANDIDATES if c in weekly.columns]
    weekly_slim = weekly[weekly_cols].rename(
        columns={c: f"WEEKLY_{c}" for c in WEEKLY_HIGH_CANDIDATES if c in weekly.columns}
    )
    join = matrix.merge(monthly_slim, on="sample_id", how="left").merge(weekly_slim, on="sample_id", how="left")
    assert len(join) == len(matrix)
    return join


def main() -> None:
    labeled = load_labeled_samples()
    logger.info("Loaded %d Human Calibration samples (weekly_stage & human_label both != UNLABELED)", len(labeled))

    matrix = build_feature_matrix(labeled)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    matrix_path = OUTPUT_DIR / "daily_timing_feature_matrix_v01.csv"
    matrix.to_csv(matrix_path, index=False)

    summary = build_summary(matrix)
    summary_path = OUTPUT_DIR / "daily_timing_feature_summary_v01.csv"
    summary.to_csv(summary_path, index=False)

    corr_df = correlation_findings(matrix)
    corr_path = OUTPUT_DIR / "daily_timing_feature_correlation_v01.csv"
    corr_df.to_csv(corr_path, index=False)

    stage_summary = build_stage_summary(matrix)
    stage_path = OUTPUT_DIR / "daily_timing_stage_summary_v01.csv"
    stage_summary.to_csv(stage_path, index=False)

    join = build_monthly_weekly_daily_join(matrix)
    join_path = OUTPUT_DIR / "monthly_weekly_daily_research_join_v01.csv"
    if join is not None:
        join.to_csv(join_path, index=False)

    logger.info("==================================================")
    logger.info("Feature matrix: %s (%d rows, %d feature columns)", matrix_path, len(matrix), len(ANALYSIS_FEATURES))
    logger.info("Feature summary: %s (%d features)", summary_path, len(summary))
    logger.info("High-correlation (|spearman|>=0.85) pairs: %d -> %s", len(corr_df), corr_path)
    logger.info("Stage summary: %s (%d stages)", stage_path, len(stage_summary))
    logger.info("Monthly+Weekly+Daily join: %s", join_path if join is not None else "NOT GENERATED")
    logger.info("daily_feature_status counts: %s", matrix["daily_feature_status"].value_counts().to_dict())
    logger.info("Total missing feature cells: %d", matrix["daily_feature_missing_count"].sum())
    logger.info("==================================================")


if __name__ == "__main__":
    main()
