"""Pattern A Stage Classifier v0.1 — Stage OOS Truth Set 35건 Validation Run.

`src/trend_scanner/patterns/pattern_a_stage.py`(classify_pattern_a_stage)를
`pattern_a_stage_oos_v01_manifest.py`의 35건 OOS manual truth set에 처음으로 실행하여
외부 challenge OOS 성능 및 failure mode를 검증한다.

[STRICT BLIND CHRONOLOGY]
1. Stage Classifier v0.1 frozen: 43ee01c
2. OOS Truth Set frozen: e3506be / 875afa7 / 93f26a0
3. First Classifier Prediction Run: 본 스크립트 실행 시점

실행 (repo 루트에서):
    python scripts/pattern_a_stage_oos_v01_validate.py

CSV 출력: data/processed/pattern_a_stage_oos_v01_validation.csv
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.patterns.pattern_a_feature_set import PatternAStage
from trend_scanner.patterns.pattern_a_stage import classify_pattern_a_stage
from trend_scanner.validation.historical_snapshot import build_historical_snapshot
from trend_scanner.validation.pattern_a_stage_oos_v01_manifest import (
    PATTERN_A_STAGE_OOS_V01_LABELS,
    STAGE_OOS_V01_DATASET_VERSION,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "data" / "raw" / "stocks"
OUTPUT_CSV = REPO_ROOT / "data" / "processed" / "pattern_a_stage_oos_v01_validation.csv"

_STAGE_ORDER = {
    PatternAStage.WEAK: 0,
    PatternAStage.BASE: 1,
    PatternAStage.TRANSITION: 2,
    PatternAStage.EARLY_TREND: 3,
    PatternAStage.PROGRESSED: 4,
}

_ALL_STAGES = [
    PatternAStage.WEAK,
    PatternAStage.BASE,
    PatternAStage.TRANSITION,
    PatternAStage.EARLY_TREND,
    PatternAStage.PROGRESSED,
]


def _match_type(predicted: PatternAStage | None, manual: PatternAStage) -> str:
    if predicted is None:
        return "NODATA"
    if predicted == manual:
        return "EXACT"
    distance = abs(_STAGE_ORDER[predicted] - _STAGE_ORDER[manual])
    return "ADJACENT" if distance == 1 else "SEVERE"


def run_validation() -> pd.DataFrame:
    cache = ParquetCache(base_dir=CACHE_DIR)
    rows: list[dict] = []

    for spec in PATTERN_A_STAGE_OOS_V01_LABELS:
        daily = cache.load(spec.ticker)
        if daily is None or daily.empty:
            rows.append({
                "ticker": spec.ticker,
                "name": spec.name,
                "snapshot_date": spec.snapshot_date,
                "selection_group": spec.selection_group,
                "manual_stage": spec.manual_stage.value,
                "predicted_stage": None,
                "match_type": "NODATA",
                "reason_codes": "",
                "manual_confidence": spec.manual_confidence,
                "active_decline": None,
                "core_turning_positive": None,
                "weekly_turning_positive": None,
                "breakout_like_structure": None,
                "near_resistance": None,
                "expansion_present": None,
                "price_extended": None,
                "insufficient_data": True,
                "prior_expansion_detected": None,
                "episode_broken_after_expansion": None,
                "last_expansion_month": None,
                "months_since_expansion": None,
                "previously_expanded_in_current_episode": None,
            })
            continue

        snapshot = build_historical_snapshot(
            ticker=spec.ticker,
            name=spec.name,
            daily=daily,
            snapshot_date=spec.snapshot_date,
            include_incomplete_periods=False,
        )
        result = classify_pattern_a_stage(snapshot)
        predicted = result.stage
        match = _match_type(predicted, spec.manual_stage)

        ev = result.evidence
        ctx = result.context

        rows.append({
            "ticker": spec.ticker,
            "name": spec.name,
            "snapshot_date": spec.snapshot_date,
            "selection_group": spec.selection_group,
            "manual_stage": spec.manual_stage.value,
            "predicted_stage": predicted.value if predicted is not None else None,
            "match_type": match,
            "reason_codes": ";".join(result.reason_codes),
            "manual_confidence": spec.manual_confidence,
            "active_decline": ev.active_decline,
            "core_turning_positive": ev.core_turning_positive,
            "weekly_turning_positive": ev.weekly_turning_positive,
            "breakout_like_structure": ev.breakout_like_structure,
            "near_resistance": ev.near_resistance,
            "expansion_present": ev.expansion_present,
            "price_extended": ev.price_extended,
            "insufficient_data": ev.insufficient_data,
            "prior_expansion_detected": ctx.prior_expansion_detected,
            "episode_broken_after_expansion": ctx.episode_broken_after_expansion,
            "last_expansion_month": ctx.last_expansion_month,
            "months_since_expansion": ctx.months_since_expansion,
            "previously_expanded_in_current_episode": ctx.previously_expanded_in_current_episode,
        })

    df = pd.DataFrame(rows)
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False)
    return df


def main() -> None:
    print(f"=== Pattern A Stage Classifier v0.1 OOS Validation Run ===")
    print(f"Dataset Version: {STAGE_OOS_V01_DATASET_VERSION} ({len(PATTERN_A_STAGE_OOS_V01_LABELS)} snapshots)")
    print()

    df = run_validation()
    n = len(df)
    exact_cnt = sum(df["match_type"] == "EXACT")
    adjacent_cnt = sum(df["match_type"] == "ADJACENT")
    severe_cnt = sum(df["match_type"] == "SEVERE")
    nodata_cnt = sum(df["match_type"] == "NODATA")

    print(f"[Overall Results]")
    print(f"  Total (n)  : {n}")
    print(f"  EXACT      : {exact_cnt:2d} / {n} ({exact_cnt / n * 100:.1f}%)")
    print(f"  ADJACENT   : {adjacent_cnt:2d} / {n} ({adjacent_cnt / n * 100:.1f}%)")
    print(f"  SEVERE     : {severe_cnt:2d} / {n} ({severe_cnt / n * 100:.1f}%)")
    print(f"  NODATA     : {nodata_cnt:2d} / {n} ({nodata_cnt / n * 100:.1f}%)")
    print()

    # Confusion Matrix
    print(f"[Confusion Matrix (rows=Manual Truth, cols=Predicted)]")
    stage_vals = [s.value for s in _ALL_STAGES]
    header = f"{'Manual / Pred':<15} | " + " | ".join(f"{s:>11}" for s in stage_vals) + " | Total"
    print(header)
    print("-" * len(header))
    for m_st in stage_vals:
        row_str = f"{m_st:<15} | "
        sub = df[df["manual_stage"] == m_st]
        for p_st in stage_vals:
            cnt = sum(sub["predicted_stage"] == p_st)
            row_str += f"{cnt:11d} | "
        row_str += f"{len(sub):5d}"
        print(row_str)
    print()

    # Per Stage Breakdown
    print(f"[Per Stage Breakdown]")
    for st in stage_vals:
        sub = df[df["manual_stage"] == st]
        s_n = len(sub)
        s_ex = sum(sub["match_type"] == "EXACT")
        s_adj = sum(sub["match_type"] == "ADJACENT")
        s_sev = sum(sub["match_type"] == "SEVERE")
        print(f"  {st:<12} (n={s_n}): EXACT {s_ex}/{s_n} ({s_ex/s_n*100:.1f}%), ADJACENT {s_adj}/{s_n}, SEVERE {s_sev}/{s_n}")
    print()

    # All Mismatches
    mismatches = df[df["match_type"] != "EXACT"]
    print(f"[Mismatches: {len(mismatches)} cases]")
    for _, row in mismatches.iterrows():
        print(f"  [{row['match_type']:<8}] {row['ticker']} {row['name']:8s} ({row['snapshot_date']}) "
              f"Truth={row['manual_stage']:<11} -> Pred={str(row['predicted_stage']):<11} | "
              f"Group={row['selection_group']} | Reasons={row['reason_codes']}")
    print()

    # CSV path
    print(f"Validation CSV saved to: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
