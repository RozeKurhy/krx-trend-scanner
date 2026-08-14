"""Pattern A v0.1 Score OOS Case Validation.

**명칭/성격(재리뷰 후속)**: 이건 시장 전체에서의 unbiased OOS 성능 검증이
아니다 — "이후 상승/하락했는지"를 알고 나서 사례를 골랐으므로(outcome
conditioned case selection) 정확히는 **Frozen Score External Case
Validation**(OOS Case Validation / stress test)이다. 종목/날짜를 고를
때 Feature/Score 값은 보지 않았지만(아래 원칙 참고), 그룹 라벨 자체가
"나중에 어떻게 됐는지"를 반영한다. 따라서 이 결과의 그룹별 비율(예:
hard_negative 8개 중 2개가 70점 이상)을 실제 시장에서의 false positive
rate나 precision으로 해석하면 안 된다 — 의도적으로 고른 실패/성공
사례에 frozen score를 적용했을 때의 관찰 결과일 뿐이다.

Score Design v0.1(harmonic mean + alignment bonus - progressed penalty,
range_36m/ma24_slope required anchor, commit 6e7cc95)을 새 종목/날짜에
그대로 적용한다. holdout/negative_control은 이미 Score 설계(weight/
threshold/penalty 확정)에 쓰였으므로 더 이상 out-of-sample이 아니다.

**버전 고정 안내(Score Design v0.2 재리뷰 후속)**: 이 문서/CSV의 원래
실행 결과는 v0.1 Score(commit 6e7cc95~11cf690)를 기준으로 만들어졌다.
pattern_a_score.py는 이후 v0.2로 freeze됐다 — 이 스크립트를 지금 다시
실행하면 `score_pattern_a()`가 v0.2(Core + Confirmation transition,
core-conditional alignment)를 반환하므로 아래 그룹 통계와 다른 숫자가
나온다. 이건 버그가 아니라 기대된 동작이다 — 이 스크립트는 "그 시점에
frozen된 Score를 새 데이터에 적용하면 어떻게 되는가"를 보는 용도라서
Score가 바뀌면 결과도 같이 바뀐다. v0.1과 v0.2의 직접 비교는 docs/
patterns/pattern_a.md의 "Score Design v0.2" 절 참고.

**중요 원칙(negative_control 선정 때와 동일)**: 종목/날짜를 고를 때
Pattern A Score, base_score, transition_score, range_36m, ma24_slope 등
어떤 Feature/Score 값도 보지 않았다. `scripts/_oos_fetch_and_inspect.py`로
raw monthly close(월봉 종가)만 먼저 출력해서 그 모양만 보고 날짜를
고정한 뒤, 이 스크립트에서 처음으로 Feature/Score를 계산한다.

이번 라운드는 Score를 튜닝하지 않는다 — weight/threshold/bonus/penalty
전부 이전 라운드 값 그대로다. 이 스크립트는 그 값을 새 데이터에 "그대로
적용했을 때 어떻게 실패하는가"를 관찰만 한다.

**v0.2 diagnostic set으로 고정됨(재리뷰 후속)**: 여기 쓰인 29개
(ticker, snapshot_date)는 이미 결과를 본 상태라, 앞으로 v0.2 설계에
재사용할 수는 있지만(development/diagnostic) v0.2 성능 검증에는 다시
쓰지 않는다. 실제 목록은 `trend_scanner.validation.oos_v01_manifest`가
유일한 출처다(이 스크립트가 목록을 따로 들고 있으면 조용히 어긋날 수
있어서 manifest를 그대로 가져다 쓴다).

그룹:
    positive_pre_breakout / positive_early_trend / positive_trend_progressed
        - 5개 종목, 각 종목이 세 시점을 모두 제공(holdout 구성과 동일한 방식)
    hard_negative_false_turn
        - 박스/기저 이후 반등처럼 보였지만 이후 다시 꺾인 8개 종목
    downtrend_reversal_boundary
        - 장기 하락이 아직 base로 정착하기 전, 하락 도중의 반등 시점
          (Pattern B와의 경계 검증용). 일부 종목은 hard_negative와 같은
          종목이지만 완전히 다른 연대(36개월 트레일링 구간)를 쓴다.
    insufficient_data_check
        - 상장 이력이 짧아 range_36m 36개월 창을 채우지 못하는 시점
          (required anchor 정책이 실제로 insufficient_data를 만드는지 확인)

실행 (repo 루트에서, `pip install -e ".[dev]"` 이후):
    python scripts/oos_validate.py

CSV: data/processed/oos_validation.csv (관찰용, data/ 전체가 gitignore라
로컬 전용).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.patterns.pattern_a_score import score_pattern_a
from trend_scanner.validation.historical_snapshot import build_historical_snapshot
from trend_scanner.validation.oos_v01_manifest import (
    OOS_V01_DATASET_VERSION,
    OOS_V01_DIAGNOSTIC_SNAPSHOTS,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "data" / "raw" / "stocks"
OUTPUT_CSV = REPO_ROOT / "data" / "processed" / "oos_validation.csv"

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
        raise SystemExit(f"{ticker} 캐시가 없습니다. scripts/_oos_fetch_and_inspect.py로 먼저 채워주세요.")
    return daily


def main() -> None:
    cache = ParquetCache(base_dir=CACHE_DIR)

    print(f"dataset_version: {OOS_V01_DATASET_VERSION} ({len(OOS_V01_DIAGNOSTIC_SNAPSHOTS)}건)")
    print()

    rows: list[dict] = []
    for spec in OOS_V01_DIAGNOSTIC_SNAPSHOTS:
        daily = _load_daily(cache, spec.ticker)
        snap = build_historical_snapshot(
            spec.ticker, spec.name, daily, spec.snapshot_date, include_incomplete_periods=False
        )
        result = score_pattern_a(snap.features)
        row = {
            "group": spec.original_group,
            "ticker": spec.ticker,
            "name": spec.name,
            "snapshot_date": spec.snapshot_date,
            "base_score": result.base_score,
            "transition_score": result.transition_score,
            "balanced_core_score": result.balanced_core_score,
            "alignment_bonus": result.alignment_bonus,
            "progressed_evidence_count": result.progressed_evidence_count,
            "progressed_penalty": result.progressed_penalty,
            "pattern_a_score": result.pattern_a_score,
            "stage": result.stage.value if result.stage is not None else None,
            "insufficient_data": result.flags.get("insufficient_data", False),
        }
        for col in RAW_FEATURE_COLUMNS:
            row[col] = getattr(snap.features, col)
        rows.append(row)

    df = pd.DataFrame(rows)
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"CSV saved: {OUTPUT_CSV} ({len(df)} rows)")
    print()

    display_cols = [
        "group",
        "ticker",
        "name",
        "snapshot_date",
        "range_36m",
        "avg_price_change_12m",
        "ma_spread",
        "ma24_slope",
        "weekly_ma12_slope",
        "ma24_slope_acceleration",
        "range_position",
        "base_score",
        "transition_score",
        "balanced_core_score",
        "alignment_bonus",
        "progressed_evidence_count",
        "progressed_penalty",
        "pattern_a_score",
        "stage",
        "insufficient_data",
    ]
    print("=" * 100)
    print("[OOS Case Validation] snapshot별 raw Feature + component Score")
    print("=" * 100)
    with pd.option_context("display.max_columns", None, "display.width", 260):
        print(df[display_cols].to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print()

    print("=" * 100)
    print("그룹별 pattern_a_score min / median / max")
    print("=" * 100)
    stats = []
    for group in dict.fromkeys(spec.original_group for spec in OOS_V01_DIAGNOSTIC_SNAPSHOTS):
        values = df.loc[df["group"] == group, "pattern_a_score"].dropna()
        if values.empty:
            stats.append({"group": group, "n": 0, "min": float("nan"), "median": float("nan"), "max": float("nan")})
            continue
        stats.append(
            {
                "group": group,
                "n": len(values),
                "min": values.min(),
                "median": values.median(),
                "max": values.max(),
            }
        )
    stats_df = pd.DataFrame(stats)
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(stats_df.to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    print()

    print("=" * 100)
    print("그룹별 base_score / transition_score median")
    print("=" * 100)
    comp_stats = (
        df.groupby("group")[["base_score", "transition_score"]].median().reset_index()
    )
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(comp_stats.to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    print()


if __name__ == "__main__":
    main()
