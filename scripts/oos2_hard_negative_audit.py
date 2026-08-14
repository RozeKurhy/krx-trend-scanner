"""Pattern A Score v0.2 OOS2 hard_negative_false_turn failure audit.

목적: OOS2(manifest는 commit b32f69d로 freeze, 결과는 commit 98594da)의
hard_negative_false_turn 4건이 왜 예상보다 높은 Score를 받았는지
component 단위로 분해한다. Score를 다시 고르지 않는다 — 이미 있는
manifest 4건 그대로, production `score_pattern_a()`/frozen
`_score_v01_baseline()`을 그대로 재사용해서 원인만 분해한다.

**이번 스크립트에서 하지 않는 것**: pattern_a_score.py 수정, manifest
수정(snapshot 추가/삭제), threshold/curve/weight/penalty 변경. 전부
이미 계산된 값을 다시 계산하고 파생 지표(counterfactual)만 추가로
계산한다.

**counterfactual 정의**(이번 재리뷰에서 요청된 것):
    final_without_alignment = clip(balanced_core_score - progressed_penalty, 0, 100)
    alignment_lift = pattern_a_score - final_without_alignment
    raw_final_before_clip = balanced_core_score + alignment_bonus - progressed_penalty  (clip 전)
    confirmation_share = confirmation_bonus / transition_score  (transition_score>0일 때만)

이 4개는 `pattern_a_score.py`의 `_compute_transition`/`score_pattern_a`
계산을 그대로 재현하는 게 아니라, 이미 계산된 결과 필드(balanced_core_score/
alignment_bonus/progressed_penalty/confirmation_bonus/transition_score/
pattern_a_score)로부터 사후에 유도하는 순수 함수다 — production
공식을 재구현하지 않는다.

실행 (repo 루트에서, `pip install -e ".[dev]"` 이후):
    python scripts/oos2_hard_negative_audit.py

CSV: data/processed/oos2_hard_negative_audit.csv (로컬 전용, data/
전체가 gitignore).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.patterns.pattern_a_score import score_pattern_a
from trend_scanner.validation.historical_snapshot import build_historical_snapshot
from trend_scanner.validation.oos_v02_manifest import OOS_V02_VALIDATION_SNAPSHOTS

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "data" / "raw" / "stocks"
OUTPUT_CSV = REPO_ROOT / "data" / "processed" / "oos2_hard_negative_audit.csv"

_COMPARE_SCRIPT_PATH = REPO_ROOT / "scripts" / "score_v02_candidate_compare.py"
_spec = importlib.util.spec_from_file_location("score_v02_candidate_compare", _COMPARE_SCRIPT_PATH)
_compare = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules[_spec.name] = _compare
_spec.loader.exec_module(_compare)

TARGET_GROUPS = ("hard_negative_false_turn", "strong_core_failure")

RAW_FEATURE_COLUMNS = [
    "range_36m", "avg_price_change_12m", "ma_spread",
    "ma24_slope", "weekly_ma12_slope", "ma24_slope_acceleration", "range_position",
]


def final_without_alignment(balanced_core_score: float, progressed_penalty: float) -> float:
    return max(0.0, min(100.0, balanced_core_score - progressed_penalty))


def alignment_lift(pattern_a_score: float, without_alignment: float) -> float:
    return pattern_a_score - without_alignment


def raw_final_before_clip(balanced_core_score: float, alignment_bonus: float, progressed_penalty: float) -> float:
    return balanced_core_score + alignment_bonus - progressed_penalty


def confirmation_share(confirmation_bonus: float, transition_score: float) -> float | None:
    if transition_score is None or transition_score <= 0:
        return None
    return confirmation_bonus / transition_score


def main() -> None:
    cache = ParquetCache(base_dir=CACHE_DIR)

    rows: list[dict] = []
    for spec in OOS_V02_VALIDATION_SNAPSHOTS:
        if spec.case_group not in TARGET_GROUPS:
            continue
        daily = cache.load(spec.ticker)
        snap = build_historical_snapshot(
            spec.ticker, spec.name, daily, spec.snapshot_date, include_incomplete_periods=False
        )
        result = score_pattern_a(snap.features)
        fv = _compare._feature_values(snap.features)
        v01 = _compare._score_v01_baseline(fv)

        row: dict = {
            "case_group": spec.case_group,
            "ticker": spec.ticker,
            "name": spec.name,
            "snapshot_date": spec.snapshot_date,
            "selection_reason": spec.selection_reason,
            "expected_behavior": spec.expected_behavior,
        }
        for col in RAW_FEATURE_COLUMNS:
            row[col] = getattr(snap.features, col)
        row.update(
            {
                "base_score": result.base_score,
                "core_score": result.core_score,
                "support_score": result.support_score,
                "confirmation_bonus": result.confirmation_bonus,
                "transition_score": result.transition_score,
                "balanced_core_score": result.balanced_core_score,
                "alignment_bonus": result.alignment_bonus,
                "progressed_evidence_count": result.progressed_evidence_count,
                "progressed_penalty": result.progressed_penalty,
                "pattern_a_score": result.pattern_a_score,
                "stage": result.stage.value if result.stage is not None else None,
                "v01_pattern_a_score": v01.pattern_a_score,
            }
        )
        wo_align = final_without_alignment(result.balanced_core_score, result.progressed_penalty)
        row["final_without_alignment"] = wo_align
        row["alignment_lift"] = alignment_lift(result.pattern_a_score, wo_align)
        row["raw_final_before_clip"] = raw_final_before_clip(
            result.balanced_core_score, result.alignment_bonus, result.progressed_penalty
        )
        row["confirmation_share"] = confirmation_share(result.confirmation_bonus, result.transition_score)
        row["v02_minus_v01"] = result.pattern_a_score - v01.pattern_a_score
        rows.append(row)

    df = pd.DataFrame(rows)
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"CSV saved: {OUTPUT_CSV} ({len(df)} rows)")
    print()

    hn = df[df.case_group == "hard_negative_false_turn"]
    print("=" * 100)
    print("[hard_negative_false_turn] 4건 개별 component")
    print("=" * 100)
    display_cols = [
        "ticker", "name", "snapshot_date", "ma24_slope", "weekly_ma12_slope", "ma24_slope_acceleration",
        "range_position", "base_score", "core_score", "support_score", "confirmation_bonus",
        "transition_score", "balanced_core_score", "alignment_bonus", "progressed_evidence_count",
        "progressed_penalty", "pattern_a_score", "final_without_alignment", "alignment_lift",
        "raw_final_before_clip", "confirmation_share", "v01_pattern_a_score", "v02_minus_v01", "stage",
    ]
    with pd.option_context("display.max_columns", None, "display.width", 320):
        print(hn[display_cols].to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print()

    print("=" * 100)
    print("hard_negative_false_turn vs strong_core_failure 비교")
    print("=" * 100)
    comp_cols = ["case_group", "ticker", "name", "base_score", "core_score", "support_score",
                 "transition_score", "alignment_bonus", "progressed_penalty", "pattern_a_score"]
    with pd.option_context("display.max_columns", None, "display.width", 260):
        print(df[comp_cols].sort_values(["case_group", "pattern_a_score"]).to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    print()
    stats = df.groupby("case_group")["pattern_a_score"].agg(["count", "min", "median", "max"])
    print(stats.to_string(float_format=lambda v: f"{v:.2f}"))
    print()
    for col in ["base_score", "core_score", "support_score", "transition_score"]:
        medians = df.groupby("case_group")[col].median()
        print(f"{col} median: {medians.to_dict()}")


if __name__ == "__main__":
    main()
