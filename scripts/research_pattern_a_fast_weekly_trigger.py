#!/usr/bin/env python
"""Phase 13E — Weekly Trigger Feature Research (RESEARCH ONLY, not Freeze).

Loads the 40 Human Calibration samples (weekly_stage_at_reference != UNLABELED
AND human_label != UNLABELED) from the frozen 13C Human Worksheet, computes
PIT-safe weekly trigger feature candidates (§7 of the Phase 13E w.md) for
each, and produces:

    artifacts/patterns/pattern_a_fast/research/feature_role/weekly_trigger_feature_matrix_v01.csv
    artifacts/patterns/pattern_a_fast/research/feature_role/weekly_trigger_feature_summary_v01.csv
    artifacts/patterns/pattern_a_fast/research/feature_role/weekly_trigger_feature_correlation_v01.csv
    artifacts/patterns/pattern_a_fast/research/feature_role/weekly_trigger_stage_summary_v01.csv
    artifacts/patterns/pattern_a_fast/research/feature_role/monthly_weekly_research_join_v01.csv

This script reuses the frozen 13C loading conventions (ParquetCache-only,
build_historical_snapshot for completed-period PIT slicing) without
modifying them. It does NOT decide a Weekly Trigger rule, a numeric
threshold, a classifier, or a score — see
docs/patterns/pattern_a_fast/research/weekly_trigger_features_v01.md.

Usage:
    uv run python scripts/research_pattern_a_fast_weekly_trigger.py
"""

from __future__ import annotations

import itertools
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.research.pattern_a_fast_weekly_features import (
    DIAGNOSTIC_ONLY_FEATURES,
    FEATURE_NAMES,
    compute_weekly_trigger_features,
)
from trend_scanner.validation.historical_snapshot import build_historical_snapshot
from trend_scanner.validation.pattern_a_fast_ground_truth import load_raw_daily

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("research_pattern_a_fast_weekly_trigger")

BASE_COMMIT = "6917b1341553b58fa42390ba1507fc9b80551fee"
WORKSHEET_CSV = Path("artifacts/patterns/pattern_a_fast/validation/ground_truth/pattern_a_fast_human_review_v01.csv")
SOURCE_CSV = Path("artifacts/patterns/pattern_a_fast/validation/ground_truth/pattern_a_fast_ground_truth_source_v01.csv")
MONTHLY_MATRIX_CSV = Path("artifacts/patterns/pattern_a_fast/research/feature_role/monthly_regime_feature_matrix_v01.csv")
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

# Phase 13D HIGH 후보(reference metadata로만 join, 이 스크립트에서 재계산하지 않음)
MONTHLY_HIGH_CANDIDATES = [
    "range_position_24m",
    "drawdown_from_12m_high",
    "close_vs_ma24_pct",
    "ma_alignment_score",
    "monthly_down_month_ratio_12m",
    "higher_monthly_low_count_12m",
    "recent_3m_return",
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
    """§13 요구사항: median 차이와 pooled-IQR로 표준화한 effect size.
    표준화 지표의 분모는 두 그룹을 합친 전체 표본의 IQR이다 — 완벽 분리 시
    합친 분포가 bimodal이 되어 분모 자체가 커지므로, 이 지표는 분리가 가장
    좋을 때 오히려 작게 나올 수 있다(Cliff's Delta가 1차 근거인 이유)."""
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
        # Leakage guard: PIT weekly data must never extend past reference_date.
        assert snapshot.weekly.empty or snapshot.weekly.index.max() <= reference_date

        features = compute_weekly_trigger_features(snapshot.weekly)
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
            "weekly_feature_status": "OK" if missing_count == 0 else "PARTIAL",
            "weekly_feature_missing_count": missing_count,
            "completed_weekly_bars_at_reference": len(snapshot.weekly),
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
    """PIT Weekly Stage(WATCH/SETUP/TRIGGER/TREND/EXTENDED)별 n과, 각
    stage가 어떤 human_label로 발전했는지 분포. TRIGGER n=1이므로 이
    표는 descriptive 참고용이다(§28 Known Small-N Guard)."""
    rows = []
    for stage, group in matrix.groupby("weekly_stage_at_reference"):
        row = {"weekly_stage_at_reference": stage, "n": len(group)}
        for label, count in group["human_label"].value_counts().items():
            row[f"outcome_{label}"] = int(count)
        rows.append(row)
    return pd.DataFrame(rows)


def build_monthly_weekly_join(matrix: pd.DataFrame) -> pd.DataFrame | None:
    """§15 권장 join view: 13D matrix(frozen, 재계산하지 않음)를 읽어
    HIGH 후보만 골라 13E matrix에 sample_id 기준으로 붙인다."""
    if not MONTHLY_MATRIX_CSV.exists():
        logger.warning("Monthly matrix not found at %s -> join skipped", MONTHLY_MATRIX_CSV)
        return None
    monthly = pd.read_csv(MONTHLY_MATRIX_CSV)
    monthly_cols = ["sample_id"] + [c for c in MONTHLY_HIGH_CANDIDATES if c in monthly.columns]
    monthly_slim = monthly[monthly_cols].rename(
        columns={c: f"MONTHLY_{c}" for c in MONTHLY_HIGH_CANDIDATES if c in monthly.columns}
    )
    join = matrix.merge(monthly_slim, on="sample_id", how="left")
    assert len(join) == len(matrix)
    return join


def main() -> None:
    labeled = load_labeled_samples()
    logger.info("Loaded %d Human Calibration samples (weekly_stage & human_label both != UNLABELED)", len(labeled))

    matrix = build_feature_matrix(labeled)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    matrix_path = OUTPUT_DIR / "weekly_trigger_feature_matrix_v01.csv"
    matrix.to_csv(matrix_path, index=False)

    summary = build_summary(matrix)
    summary_path = OUTPUT_DIR / "weekly_trigger_feature_summary_v01.csv"
    summary.to_csv(summary_path, index=False)

    corr_df = correlation_findings(matrix)
    corr_path = OUTPUT_DIR / "weekly_trigger_feature_correlation_v01.csv"
    corr_df.to_csv(corr_path, index=False)

    stage_summary = build_stage_summary(matrix)
    stage_path = OUTPUT_DIR / "weekly_trigger_stage_summary_v01.csv"
    stage_summary.to_csv(stage_path, index=False)

    join = build_monthly_weekly_join(matrix)
    join_path = OUTPUT_DIR / "monthly_weekly_research_join_v01.csv"
    if join is not None:
        join.to_csv(join_path, index=False)

    logger.info("==================================================")
    logger.info("Feature matrix: %s (%d rows, %d feature columns)", matrix_path, len(matrix), len(ANALYSIS_FEATURES))
    logger.info("Feature summary: %s (%d features)", summary_path, len(summary))
    logger.info("High-correlation (|spearman|>=0.85) pairs: %d -> %s", len(corr_df), corr_path)
    logger.info("Stage summary: %s (%d stages)", stage_path, len(stage_summary))
    logger.info("Monthly+Weekly join: %s", join_path if join is not None else "NOT GENERATED")
    logger.info("weekly_feature_status counts: %s", matrix["weekly_feature_status"].value_counts().to_dict())
    logger.info("Total missing feature cells: %d", matrix["weekly_feature_missing_count"].sum())
    logger.info("==================================================")


if __name__ == "__main__":
    main()
