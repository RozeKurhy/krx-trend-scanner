"""Pattern A v0.1 Score OOS(Out-of-sample) Validation.

Score Design v0.1(harmonic mean + alignment bonus - progressed penalty,
range_36m/ma24_slope required anchor)을 새 종목/날짜에 그대로 적용한다.
holdout/negative_control은 이미 Score 설계(weight/threshold/penalty
확정)에 쓰였으므로 이제 Score 관점에서는 in-sample이다 — 여기 쓰인
종목/날짜는 전부 처음 등장한다.

**중요 원칙(negative_control 선정 때와 동일)**: 종목/날짜를 고를 때
Pattern A Score, base_score, transition_score, range_36m, ma24_slope 등
어떤 Feature/Score 값도 보지 않았다. `scripts/_oos_fetch_and_inspect.py`로
raw monthly close(월봉 종가)만 먼저 출력해서 그 모양만 보고 날짜를
고정한 뒤, 이 스크립트에서 처음으로 Feature/Score를 계산한다.

이번 라운드는 Score를 튜닝하지 않는다 — weight/threshold/bonus/penalty
전부 이전 라운드 값 그대로다. 이 스크립트는 그 값을 새 데이터에 "그대로
적용했을 때 어떻게 실패하는가"를 관찰만 한다.

그룹:
    positive_pre_breakout / positive_early_trend / positive_trend_progressed
        - 5개 종목, 각 종목이 세 시점을 모두 제공(holdout 구성과 동일한 방식)
    hard_negative_false_turn
        - 박스/기저 이후 반등처럼 보였지만 이후 다시 꺾인 9개 종목
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

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "data" / "raw" / "stocks"
OUTPUT_CSV = REPO_ROOT / "data" / "processed" / "oos_validation.csv"

# --- positive: 5종목 x 3시점(pre_breakout/early_trend/trend_progressed) ---
# 선정 근거는 raw monthly close 모양만 보고 정했다(완료 보고에 정리).
POSITIVE_SNAPSHOTS: list[dict[str, str]] = [
    {"ticker": "010620", "name": "HD현대미포", "date": "2023-12-31", "group": "positive_pre_breakout"},
    {"ticker": "010620", "name": "HD현대미포", "date": "2024-06-30", "group": "positive_early_trend"},
    {"ticker": "010620", "name": "HD현대미포", "date": "2024-12-31", "group": "positive_trend_progressed"},
    {"ticker": "012450", "name": "한화에어로스페이스", "date": "2021-12-31", "group": "positive_pre_breakout"},
    {"ticker": "012450", "name": "한화에어로스페이스", "date": "2022-12-31", "group": "positive_early_trend"},
    {"ticker": "012450", "name": "한화에어로스페이스", "date": "2024-06-30", "group": "positive_trend_progressed"},
    {"ticker": "079550", "name": "LIG넥스원", "date": "2020-12-31", "group": "positive_pre_breakout"},
    {"ticker": "079550", "name": "LIG넥스원", "date": "2021-12-31", "group": "positive_early_trend"},
    {"ticker": "079550", "name": "LIG넥스원", "date": "2023-12-31", "group": "positive_trend_progressed"},
    {"ticker": "005490", "name": "POSCO홀딩스", "date": "2022-12-31", "group": "positive_pre_breakout"},
    {"ticker": "005490", "name": "POSCO홀딩스", "date": "2023-03-31", "group": "positive_early_trend"},
    {"ticker": "005490", "name": "POSCO홀딩스", "date": "2023-07-31", "group": "positive_trend_progressed"},
    {"ticker": "042660", "name": "한화오션", "date": "2024-10-31", "group": "positive_pre_breakout"},
    {"ticker": "042660", "name": "한화오션", "date": "2025-01-31", "group": "positive_early_trend"},
    {"ticker": "042660", "name": "한화오션", "date": "2025-07-31", "group": "positive_trend_progressed"},
]

# --- hard_negative_false_turn: 박스/기저 이후 반등 -> 이후 재하락 ---
# 010060(OCI홀딩스) 2023-06-30은 원래 후보였으나 2023-04-27~05-29 거래정지
# (인적분할, OCI홀딩스/OCI로 분할 재상장) 구간이 껴 있어 제외했다 — 36개월
# range가 분할 전후 가격을 그대로 이어붙인 값이라 경제적으로 불연속하다
# (카카오 1원 위반 제외 선례와 같은 원칙: provider 보정 정책을 확장하지
# 않고, validate_ohlcv를 통과했어도 데이터 품질 사유로 뺀다).
HARD_NEGATIVE_SNAPSHOTS: list[dict[str, str]] = [
    {"ticker": "036570", "name": "엔씨소프트", "date": "2023-11-30"},
    {"ticker": "251270", "name": "넷마블", "date": "2023-11-30"},
    {"ticker": "090430", "name": "아모레퍼시픽", "date": "2024-05-31"},
    {"ticker": "011790", "name": "SKC", "date": "2024-06-30"},
    {"ticker": "004020", "name": "현대제철", "date": "2023-09-30"},
    {"ticker": "161390", "name": "한국타이어앤테크놀로지", "date": "2024-04-30"},
    {"ticker": "069960", "name": "현대백화점", "date": "2021-05-31"},
    {"ticker": "000990", "name": "DB하이텍", "date": "2023-11-30"},
]

# --- downtrend_reversal_boundary: 아직 base가 없는 하락 도중의 반등 ---
# 일부 종목은 hard_negative와 겹치지만 36개월 트레일링 구간(직전 3년)은
# 대부분 겹치지 않는다: 아모레(2024-05 vs 2018-12)와 넷마블(2023-11 vs
# 2020-08)은 안 겹친다. 현대백화점만 예외 — hard_negative(2021-05, 구간
# 2018-06~2021-05)와 boundary(2019-04, 구간 2016-05~2019-04)가 약 11개월
# (2018-06~2019-04) 겹친다. 그래도 각 스냅샷이 보는 "그 시점까지의 최근
# 36개월"이라는 관점 자체가 다르므로(반등 시도의 시점이 다름) 남겨두되,
# 겹침 사실은 숨기지 않는다.
BOUNDARY_SNAPSHOTS: list[dict[str, str]] = [
    {"ticker": "090430", "name": "아모레퍼시픽", "date": "2018-12-31"},
    {"ticker": "251270", "name": "넷마블", "date": "2020-08-31"},
    {"ticker": "069960", "name": "현대백화점", "date": "2019-04-30"},
    {"ticker": "097950", "name": "CJ제일제당", "date": "2019-12-31"},
    {"ticker": "006800", "name": "미래에셋증권", "date": "2022-10-31"},
]

# --- insufficient_data_check: range_36m 36개월 창을 못 채우는 시점 ---
INSUFFICIENT_DATA_SNAPSHOTS: list[dict[str, str]] = [
    {"ticker": "247540", "name": "에코프로비엠", "date": "2021-06-30"},  # 상장 2019-03, 이 시점 약 27개월치만 존재
]

ALL_GROUPS: dict[str, list[dict[str, str]]] = {}
for row in POSITIVE_SNAPSHOTS:
    ALL_GROUPS.setdefault(row["group"], []).append(row)
ALL_GROUPS["hard_negative_false_turn"] = HARD_NEGATIVE_SNAPSHOTS
ALL_GROUPS["downtrend_reversal_boundary"] = BOUNDARY_SNAPSHOTS
ALL_GROUPS["insufficient_data_check"] = INSUFFICIENT_DATA_SNAPSHOTS

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

    rows: list[dict] = []
    for group, snapshots in ALL_GROUPS.items():
        for s in snapshots:
            daily = _load_daily(cache, s["ticker"])
            snap = build_historical_snapshot(
                s["ticker"], s["name"], daily, s["date"], include_incomplete_periods=False
            )
            result = score_pattern_a(snap.features)
            row = {
                "group": group,
                "ticker": s["ticker"],
                "name": s["name"],
                "snapshot_date": s["date"],
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
    print("[OOS] snapshot별 raw Feature + component Score")
    print("=" * 100)
    with pd.option_context("display.max_columns", None, "display.width", 260):
        print(df[display_cols].to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print()

    print("=" * 100)
    print("그룹별 pattern_a_score min / median / max")
    print("=" * 100)
    stats = []
    for group, _ in ALL_GROUPS.items():
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
