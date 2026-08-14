"""Pattern A Stage Classifier v0.1 — Stage Truth Set 46건 Validation.

`src/trend_scanner/patterns/pattern_a_stage.py`(classify_pattern_a_stage)를
`pattern_a_stage_manifest.py`의 46건 manual truth set에 그대로 적용해서
predicted_stage/audited_stage를 비교한다.

**Score를 쓰지 않는다**: 이 스크립트는 pattern_a_score를 import하지 않는다.
**Truth set을 수정하지 않는다**: PATTERN_A_STAGE_LABELS는 읽기 전용으로만
쓴다 — 결과가 나빠도 audited_stage를 classifier에 맞춰 바꾸지 않는다.
**46/46을 목표로 튜닝하지 않는다**: 이 스크립트는 v0.1 rule을 있는 그대로
관찰만 한다 — 결과가 나쁘면 그대로 기록하고, docs/validation/
pattern_a_stage_classifier_v01.md의 "Known failure modes"에 v0.2 evidence로
남긴다.

실행 (repo 루트에서):
    python scripts/pattern_a_stage_validate.py

CSV: data/processed/pattern_a_stage_v01_validation.csv (로컬 전용,
data/ 전체가 gitignore).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.patterns.pattern_a_feature_set import PatternAStage
from trend_scanner.patterns.pattern_a_stage import classify_pattern_a_stage
from trend_scanner.validation.historical_snapshot import build_historical_snapshot
from trend_scanner.validation.pattern_a_stage_manifest import (
    PATTERN_A_STAGE_LABELS,
    STAGE_MANIFEST_DATASET_VERSION,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "data" / "raw" / "stocks"
OUTPUT_CSV = REPO_ROOT / "data" / "processed" / "pattern_a_stage_v01_validation.csv"

# WEAK가 완전히 서열적이지 않다는 점(docs/validation/pattern_a_stage.md)을
# 감안해도, match 판정을 위해서는 하나의 순서를 정해야 한다. lifecycle
# 진행 순서(BASE/WEAK -> TRANSITION -> EARLY_TREND -> PROGRESSED)를 그대로
# 쓰되, WEAK는 BASE 바로 아래(0)에 둔다 — "둘 다 아직 확장 전"이라는 점만
# ADJACENT 판정에 반영하고, WEAK<->TRANSITION 이상 거리는 그대로 SEVERE로
# 잡히게 둔다(이 caveat은 문서에 별도로 남긴다).
_STAGE_ORDER = {
    PatternAStage.WEAK: 0,
    PatternAStage.BASE: 1,
    PatternAStage.TRANSITION: 2,
    PatternAStage.EARLY_TREND: 3,
    PatternAStage.PROGRESSED: 4,
}

# Challenge case 3건은 truth set(PATTERN_A_STAGE_LABELS) 46건에는 없는
# 별도 (ticker, snapshot_date)다. 공식 audited_stage가 없으므로
# match_type을 계산하지 않고, predicted_stage/evidence만 별도 표로
# 보고한다(global rule에는 반영하지 않는다).
#   010620 HD현대미포: manifest에 2023-12-31(BASE)/2024-12-31(PROGRESSED)
#     두 snapshot이 있다 — 그 사이 중간 지점(2024-06-30)에서 classifier가
#     BASE->PROGRESSED 전환 과정 중 어디쯤을 찍는지 관찰한다.
#   042660 한화오션: manifest에 2024-10-31(TRANSITION)/2025-07-31
#     (PROGRESSED) 두 snapshot이 있다 — 중간 지점(2025-01-31) 관찰.
#   011200 HMM: manifest에 2024-10-31(WEAK) 1건만 있다 — 그 이후
#     시점(2025-04-30)에 WEAK가 계속 유지되는지, 다른 stage로 넘어가는지
#     관찰한다(manifest 날짜와 겹치지 않는 별도 시점).
_CHALLENGE_CASES = (
    ("010620", "HD현대미포", "2024-06-30"),
    ("042660", "한화오션", "2025-01-31"),
    ("011200", "HMM", "2025-04-30"),
)


def _match_type(predicted: PatternAStage | None, audited: PatternAStage) -> str:
    if predicted is None:
        return "NODATA"
    if predicted == audited:
        return "EXACT"
    distance = abs(_STAGE_ORDER[predicted] - _STAGE_ORDER[audited])
    return "ADJACENT" if distance == 1 else "SEVERE"


def main() -> None:
    cache = ParquetCache(base_dir=CACHE_DIR)
    print(f"dataset_version: {STAGE_MANIFEST_DATASET_VERSION} ({len(PATTERN_A_STAGE_LABELS)}건)")
    print()

    def _classify_row(ticker: str, name: str, snapshot_date: str) -> dict:
        daily = cache.load(ticker)
        if daily is None or daily.empty:
            return {
                "ticker": ticker,
                "name": name,
                "snapshot_date": snapshot_date,
                "predicted_stage": None,
                "reason_codes": "",
                "no_cache": True,
            }
        snap = build_historical_snapshot(ticker, name, daily, snapshot_date, include_incomplete_periods=False)
        result = classify_pattern_a_stage(snap)
        predicted = result.stage
        return {
            "ticker": ticker,
            "name": name,
            "snapshot_date": snapshot_date,
            "predicted_stage": predicted.value if predicted is not None else None,
            "reason_codes": ",".join(result.reason_codes),
            "active_decline": result.evidence.active_decline,
            "core_turning_positive": result.evidence.core_turning_positive,
            "weekly_turning_positive": result.evidence.weekly_turning_positive,
            "breakout_like_structure": result.evidence.breakout_like_structure,
            "expansion_present": result.evidence.expansion_present,
            "previously_expanded_in_current_episode": result.context.previously_expanded_in_current_episode,
            "episode_broken": result.context.episode_broken,
            "no_cache": False,
        }

    rows: list[dict] = []
    for spec in PATTERN_A_STAGE_LABELS:
        row = _classify_row(spec.ticker, spec.name, spec.snapshot_date)
        row["audited_stage"] = spec.audited_stage.value
        row["match_type"] = (
            "NO_CACHE" if row["no_cache"] else _match_type(
                PatternAStage(row["predicted_stage"]) if row["predicted_stage"] else None,
                spec.audited_stage,
            )
        )
        rows.append(row)

    df = pd.DataFrame(rows)
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"CSV saved: {OUTPUT_CSV} ({len(df)} rows)")
    print()

    core_df = df

    print("=" * 100)
    print("[Pattern A Stage Classifier v0.1] 종목별 predicted vs audited (truth set 46건)")
    print("=" * 100)
    display_cols = ["ticker", "name", "snapshot_date", "audited_stage", "predicted_stage", "match_type", "reason_codes"]
    with pd.option_context("display.max_columns", None, "display.width", 220, "display.max_colwidth", 60):
        print(core_df[display_cols].to_string(index=False))
    print()

    print("=" * 100)
    print("전체 요약")
    print("=" * 100)
    n = len(core_df)
    counts = core_df["match_type"].value_counts()
    exact = int(counts.get("EXACT", 0))
    adjacent = int(counts.get("ADJACENT", 0))
    severe = int(counts.get("SEVERE", 0))
    nodata = int(counts.get("NODATA", 0)) + int(counts.get("NO_CACHE", 0))
    print(f"n = {n}")
    print(f"EXACT match: {exact}건 ({exact / n:.1%})")
    print(f"ADJACENT mismatch: {adjacent}건 ({adjacent / n:.1%})")
    print(f"SEVERE mismatch: {severe}건 ({severe / n:.1%})")
    print(f"NODATA/NO_CACHE: {nodata}건")
    print()

    print("=" * 100)
    print("Stage별 support / exact count")
    print("=" * 100)
    by_stage = core_df.groupby("audited_stage").apply(
        lambda g: pd.Series(
            {
                "support": len(g),
                "exact": int((g["match_type"] == "EXACT").sum()),
                "exact_rate": (g["match_type"] == "EXACT").mean(),
            }
        ),
        include_groups=False,
    )
    stage_order = ["weak", "base", "transition", "early_trend", "progressed"]
    by_stage = by_stage.reindex(stage_order)
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(by_stage.to_string(float_format=lambda v: f"{v:.2f}"))
    print()

    print("=" * 100)
    print("Confusion matrix (row=audited_stage, col=predicted_stage)")
    print("=" * 100)
    valid = core_df[core_df["predicted_stage"].notna()]
    confusion = pd.crosstab(valid["audited_stage"], valid["predicted_stage"])
    confusion = confusion.reindex(index=stage_order, columns=stage_order, fill_value=0)
    print(confusion.to_string())
    print()

    print("=" * 100)
    print("Major error type audit")
    print("=" * 100)
    mism = core_df[core_df["match_type"].isin(["ADJACENT", "SEVERE"])]

    def _report(label: str, mask: pd.Series) -> None:
        sub = mism[mask]
        print(f"[{label}] {len(sub)}건")
        if not sub.empty:
            with pd.option_context("display.max_columns", None, "display.width", 200):
                print(sub[["ticker", "snapshot_date", "audited_stage", "predicted_stage", "reason_codes"]].to_string(index=False))
        print()

    _report(
        "A. EARLY_TREND truth -> PROGRESSED 예측 (확장 신호 과다 판정)",
        (mism["audited_stage"] == "early_trend") & (mism["predicted_stage"] == "progressed"),
    )
    _report(
        "B. PROGRESSED truth -> EARLY_TREND/TRANSITION 예측 (episode continuation 미포착)",
        (mism["audited_stage"] == "progressed") & (mism["predicted_stage"].isin(["early_trend", "transition"])),
    )
    _report(
        "C. BASE truth -> TRANSITION/WEAK 예측 (약한 신호에 과다 반응)",
        (mism["audited_stage"] == "base") & (mism["predicted_stage"].isin(["transition", "weak"])),
    )
    _report(
        "D. TRANSITION truth -> PROGRESSED 예측 (급등성 avg_price_change_12m을 진짜 progression과 혼동)",
        (mism["audited_stage"] == "transition") & (mism["predicted_stage"] == "progressed"),
    )
    _report(
        "E. WEAK<->BASE 경계 오분류 (active_decline threshold 경계)",
        (mism["audited_stage"].isin(["weak", "base"])) & (mism["predicted_stage"].isin(["weak", "base"])),
    )
    _report(
        "F. 그 외",
        ~(
            ((mism["audited_stage"] == "early_trend") & (mism["predicted_stage"] == "progressed"))
            | ((mism["audited_stage"] == "progressed") & (mism["predicted_stage"].isin(["early_trend", "transition"])))
            | ((mism["audited_stage"] == "base") & (mism["predicted_stage"].isin(["transition", "weak"])))
            | ((mism["audited_stage"] == "transition") & (mism["predicted_stage"] == "progressed"))
            | ((mism["audited_stage"].isin(["weak", "base"])) & (mism["predicted_stage"].isin(["weak", "base"])))
        ),
    )

    print("=" * 100)
    print("Challenge cases (truth set 46건에는 없는 별도 snapshot) — 공식 audited_stage 없음,")
    print("관찰 결과만 기록하고 global rule에는 반영하지 않는다")
    print("=" * 100)
    challenge_rows = [_classify_row(ticker, name, snapshot_date) for ticker, name, snapshot_date in _CHALLENGE_CASES]
    challenge_df = pd.DataFrame(challenge_rows)
    challenge_display_cols = ["ticker", "name", "snapshot_date", "predicted_stage", "reason_codes"]
    with pd.option_context("display.max_columns", None, "display.width", 220, "display.max_colwidth", 60):
        print(challenge_df[challenge_display_cols].to_string(index=False))
    print()


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()
