"""Pattern A Score v0.2 OOS2 Frozen Validation.

`src/trend_scanner/validation/oos_v02_manifest.py`(commit `b32f69d`로
selection freeze됨)의 38개 (ticker, snapshot_date)에 frozen Pattern A
Score v0.2(`score_pattern_a()`, pattern_a_score.py는 이 스크립트에서도
전혀 수정하지 않는다)를 그대로 적용한다.

**Score를 튜닝하지 않는다**: 이 스크립트는 v0.2를 새 데이터에 "그대로
적용했을 때 어떻게 동작하는가"를 관찰만 한다. 결과가 나쁘더라도 이
스크립트 실행 중에는 Base/Transition/confirmation gate/alignment/
penalty/Stage 어느 것도 바꾸지 않는다 — 발견된 문제는 docs/validation/
pattern_a_oos2.md의 "새롭게 발견된 failure mechanism" 절에 v0.3
development evidence로만 기록한다.

**v0.1 baseline도 diagnostic으로 같이 계산한다**: "v0.2가 v0.1보다
실제로 어떤 실패 메커니즘을 개선했는가"를 보기 위해 frozen v0.1
baseline(`scripts/score_v02_candidate_compare.py`의
`_score_v01_baseline()` — 재현성 최종 마무리 라운드에서 alignment
판정까지 production과 완전히 독립적으로 고정된 함수)도 같이 계산한다.
이건 v0.2를 다시 고르기 위한 optimization이 아니라 순수 비교용이다.
`_score_v01_baseline()`을 재구현하지 않고 그대로 import해서 쓴다(item
30 — Candidate C 공식을 다시 만들지 않는다).

**HistoricalSnapshot 경로 재사용**: `build_historical_snapshot(ticker,
name, daily, snapshot_date, include_incomplete_periods=False)`를 그대로
쓴다 — OOS2 전용 Feature 계산 로직을 새로 만들지 않는다(item 13). 이
함수가 내부적으로 `daily.index <= snapshot_date`만 쓰므로 look-ahead가
없다.

**insufficient_history 그룹의 기대 동작**: 353200/403870은 36개월/24개월
history가 snapshot 시점까지 부족하다. `build_historical_snapshot()`이
예외를 던지면 그 예외 자체가 관찰 결과다(catch해서 기록한다) — 예외를
피하려고 manifest의 snapshot_date를 조정하지 않는다(freeze된 manifest는
이 스크립트에서 건드리지 않는다).

실행 (repo 루트에서, `pip install -e ".[dev]"` 이후):
    python scripts/oos2_validate.py

CSV: data/processed/oos_v02_validation.csv (로컬 전용, data/ 전체가
gitignore).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.data.errors import MarketDataError
from trend_scanner.patterns.pattern_a_score import (
    ALIGNMENT_CORE_STRONG_THRESHOLD,
    score_pattern_a,
)
from trend_scanner.validation.historical_snapshot import build_historical_snapshot
from trend_scanner.validation.oos_v02_manifest import (
    OOS_V02_DATASET_VERSION,
    OOS_V02_VALIDATION_SNAPSHOTS,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "data" / "raw" / "stocks"
OUTPUT_CSV = REPO_ROOT / "data" / "processed" / "oos_v02_validation.csv"

# score_v02_candidate_compare.py는 scripts/라 패키지가 아니다 — importlib로
# 파일 경로 기준 로드한다(tests/test_score_v02_candidate_compare.py와 동일
# 패턴). _score_v01_baseline()을 재구현하지 않고 그대로 가져다 쓴다.
_COMPARE_SCRIPT_PATH = REPO_ROOT / "scripts" / "score_v02_candidate_compare.py"
_spec = importlib.util.spec_from_file_location("score_v02_candidate_compare", _COMPARE_SCRIPT_PATH)
_compare = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules[_spec.name] = _compare
_spec.loader.exec_module(_compare)

RAW_FEATURE_COLUMNS = [
    "range_36m",
    "avg_price_change_12m",
    "ma_spread",
    "ma24_slope",
    "weekly_ma12_slope",
    "ma24_slope_acceleration",
    "range_position",
]


def _load_daily(cache: ParquetCache, ticker: str) -> pd.DataFrame:
    daily = cache.load(ticker)
    if daily is None or daily.empty:
        raise SystemExit(f"{ticker} 캐시가 없습니다. scripts/_oos2_fetch_and_inspect.py로 먼저 채워주세요.")
    return daily


def main() -> None:
    cache = ParquetCache(base_dir=CACHE_DIR)

    print(f"dataset_version: {OOS_V02_DATASET_VERSION} ({len(OOS_V02_VALIDATION_SNAPSHOTS)}건)")
    print()

    rows: list[dict] = []
    for spec in OOS_V02_VALIDATION_SNAPSHOTS:
        daily = _load_daily(cache, spec.ticker)

        row: dict = {
            "case_group": spec.case_group,
            "ticker": spec.ticker,
            "name": spec.name,
            "snapshot_date": spec.snapshot_date,
            "expected_behavior": spec.expected_behavior,
        }

        try:
            snap = build_historical_snapshot(
                spec.ticker, spec.name, daily, spec.snapshot_date, include_incomplete_periods=False
            )
        except (MarketDataError, ValueError) as exc:
            row["snapshot_error"] = f"{type(exc).__name__}: {exc}"
            rows.append(row)
            continue

        row["snapshot_error"] = None
        for col in RAW_FEATURE_COLUMNS:
            row[col] = getattr(snap.features, col)

        result = score_pattern_a(snap.features)
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
                "insufficient_data": result.flags.get("insufficient_data", False),
            }
        )

        fv = _compare._feature_values(snap.features)
        v01 = _compare._score_v01_baseline(fv)
        row.update(
            {
                "v01_base_score": v01.base_score,
                "v01_transition_score": v01.transition_score,
                "v01_alignment_bonus": v01.alignment_bonus,
                "v01_progressed_penalty": v01.progressed_penalty,
                "v01_pattern_a_score": v01.pattern_a_score,
                "v01_insufficient_data": v01.insufficient_data,
            }
        )
        rows.append(row)

    df = pd.DataFrame(rows)
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"CSV saved: {OUTPUT_CSV} ({len(df)} rows)")
    print()

    display_cols = [
        "case_group", "ticker", "name", "snapshot_date",
        "ma24_slope", "weekly_ma12_slope", "ma24_slope_acceleration",
        "core_score", "support_score", "confirmation_bonus",
        "base_score", "transition_score", "alignment_bonus",
        "progressed_penalty", "pattern_a_score", "stage",
        "v01_pattern_a_score", "insufficient_data", "snapshot_error",
    ]
    print("=" * 100)
    print("[OOS2 Frozen Validation] snapshot별 Feature + v0.2 component + v0.1 baseline")
    print("=" * 100)
    with pd.option_context("display.max_columns", None, "display.width", 300):
        print(df[display_cols].to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print()

    print("=" * 100)
    print("case_group별 pattern_a_score(v0.2) min / median / max, n")
    print("=" * 100)
    stats = []
    for group in dict.fromkeys(spec.case_group for spec in OOS_V02_VALIDATION_SNAPSHOTS):
        values = df.loc[df["case_group"] == group, "pattern_a_score"].dropna()
        if values.empty:
            stats.append({"case_group": group, "n": 0, "min": float("nan"), "median": float("nan"), "max": float("nan")})
            continue
        stats.append(
            {"case_group": group, "n": len(values), "min": values.min(), "median": values.median(), "max": values.max()}
        )
    stats_df = pd.DataFrame(stats)
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(stats_df.to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    print()

    print("=" * 100)
    print("v0.1 baseline vs v0.2 pattern_a_score 비교 (case_group별 median)")
    print("=" * 100)
    valid = df[df["snapshot_error"].isna()].copy() if "snapshot_error" in df else df.copy()
    comp = valid.groupby("case_group")[["v01_pattern_a_score", "pattern_a_score"]].median()
    comp["v02_minus_v01"] = comp["pattern_a_score"] - comp["v01_pattern_a_score"]
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(comp.to_string(float_format=lambda v: f"{v:.2f}"))
    print()

    print("=" * 100)
    print("Weak Core + Strong Support 개별 비교 (item 12)")
    print("=" * 100)
    g_rows = valid[valid["case_group"] == "weak_core_strong_support"]
    with pd.option_context("display.max_columns", None, "display.width", 220):
        print(
            g_rows[
                ["ticker", "name", "snapshot_date", "ma24_slope", "weekly_ma12_slope", "core_score", "support_score", "v01_pattern_a_score", "pattern_a_score"]
            ].to_string(index=False, float_format=lambda v: f"{v:.2f}")
        )
    print()

    print("=" * 100)
    print(f"Alignment core threshold {ALIGNMENT_CORE_STRONG_THRESHOLD} audit (item 18)")
    print("=" * 100)
    aligned_rows = valid[valid["alignment_bonus"] > 0]
    if not aligned_rows.empty:
        bucket = aligned_rows["core_score"].apply(
            lambda c: f"core>={ALIGNMENT_CORE_STRONG_THRESHOLD:.0f}" if c is not None and c >= ALIGNMENT_CORE_STRONG_THRESHOLD else f"core<{ALIGNMENT_CORE_STRONG_THRESHOLD:.0f}"
        )
        audit = aligned_rows.assign(core_bucket=bucket).groupby(["core_bucket", "case_group"]).size()
        print(audit.to_string())
    else:
        print("(정렬 조건을 만족한 snapshot이 없음)")
    print()

    print("=" * 100)
    print("Core / Support quadrant 분포 (item 19, core/support 50 기준 4분면)")
    print("=" * 100)
    quad = valid.dropna(subset=["core_score", "support_score"]).copy()
    if not quad.empty:
        quad["core_bucket"] = quad["core_score"].apply(lambda c: "core_strong" if c >= 50 else "core_weak")
        quad["support_bucket"] = quad["support_score"].apply(lambda s: "support_strong" if s >= 50 else "support_weak")
        pivot = quad.groupby(["core_bucket", "support_bucket"])["pattern_a_score"].agg(["count", "median", "max"])
        print(pivot.to_string(float_format=lambda v: f"{v:.2f}"))
    print()


if __name__ == "__main__":
    main()
