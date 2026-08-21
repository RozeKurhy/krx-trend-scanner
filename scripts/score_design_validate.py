"""Pattern A v0.1 Score Design 검증 스크립트.

pattern_a_score.score_pattern_a()로 계산한 Score를 기존 historical_snapshot
캐시(holdout 5종목, negative_control 8종목, exploration 4종목 참고용)에
적용해 분포를 확인한다. 새 KRX fetch 없음. 실제 종목 추천/전체 스캔/
백테스트/미래 수익률 튜닝은 하지 않는다 — 관찰용 표만 출력한다.

Design 비교(item 28, v0.1 라운드 기준): 최종 채택안(Design C: harmonic +
alignment bonus - progressed penalty)과 함께, 기각한 두 대안도 같은
component score로 계산해서 나란히 비교한다.

    Design A: 단순 가산식(base 40% + transition 60%) — item 2가 경고한
              "Base 없이 Transition만 강해도 고득점" 문제 재현용 비교 대상.
    Design B: harmonic mean만(alignment bonus/progressed penalty 없음).
    Design C: harmonic mean + alignment bonus - progressed penalty (채택안).

**버전 고정 안내(Score Design v0.2 재리뷰 후속)**: 여기서 "Design C"는
v0.1 시절의 harmonic+bonus-penalty 구조를 가리킨다 — v0.2에서 Transition
Score(Core+Confirmation)와 alignment bonus(core-conditional) 계산 방식
자체가 바뀌었으므로, `design_c_score` 컬럼은 이제 pattern_a_score.py의
현재(v0.2) 출력을 그대로 반영한다. Design A/B는 이 스크립트 안에서만
독립적으로 재계산하는 v0.1 시절 기각안이라 v0.2 전환과 무관하게 그대로
동작한다. v0.1 vs v0.2 비교는 scripts/score_v02_candidate_compare.py와
docs/patterns/pattern_a/spec/production_authority.md의 "Score Design v0.2" 절 참고.

실행 (repo 루트에서, `pip install -e ".[dev]"` 이후):
    python scripts/score_design_validate.py

CSV 경로: data/processed/score_design_validation.csv (관찰용, data/ 전체가
gitignore라 로컬에만 남는다).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.patterns.pattern_a_score import PatternAResult, score_pattern_a
from trend_scanner.validation.historical_snapshot import (
    HistoricalSnapshot,
    build_historical_snapshot,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "data" / "raw" / "stocks"
OUTPUT_CSV = REPO_ROOT / "data" / "processed" / "score_design_validation.csv"

EXPLORATION_SNAPSHOTS: list[dict[str, str]] = [
    {"ticker": "068270", "name": "셀트리온", "date": "2019-12-31", "label": "pre_breakout"},
    {"ticker": "068270", "name": "셀트리온", "date": "2020-06-30", "label": "early_trend"},
    {"ticker": "068270", "name": "셀트리온", "date": "2020-12-31", "label": "trend_progressed"},
    {"ticker": "035420", "name": "NAVER", "date": "2020-03-31", "label": "pre_breakout"},
    {"ticker": "035420", "name": "NAVER", "date": "2020-06-30", "label": "early_trend"},
    {"ticker": "035420", "name": "NAVER", "date": "2021-06-30", "label": "trend_progressed"},
    {"ticker": "005930", "name": "삼성전자", "date": "2019-09-30", "label": "pre_breakout"},
    {"ticker": "005930", "name": "삼성전자", "date": "2020-09-30", "label": "early_trend"},
    {"ticker": "005930", "name": "삼성전자", "date": "2021-03-31", "label": "trend_progressed"},
    {"ticker": "000660", "name": "SK하이닉스", "date": "2023-03-31", "label": "pre_breakout"},
    {"ticker": "000660", "name": "SK하이닉스", "date": "2023-12-31", "label": "early_trend"},
    {"ticker": "000660", "name": "SK하이닉스", "date": "2024-06-30", "label": "trend_progressed"},
]

HOLDOUT_SNAPSHOTS: list[dict[str, str]] = [
    {"ticker": "005380", "name": "현대차", "date": "2020-06-30", "label": "pre_breakout"},
    {"ticker": "005380", "name": "현대차", "date": "2020-08-31", "label": "early_trend"},
    {"ticker": "005380", "name": "현대차", "date": "2021-02-28", "label": "trend_progressed"},
    {"ticker": "051910", "name": "LG화학", "date": "2020-03-31", "label": "pre_breakout"},
    {"ticker": "051910", "name": "LG화학", "date": "2020-06-30", "label": "early_trend"},
    {"ticker": "051910", "name": "LG화학", "date": "2021-01-31", "label": "trend_progressed"},
    {"ticker": "000270", "name": "기아", "date": "2020-06-30", "label": "pre_breakout"},
    {"ticker": "000270", "name": "기아", "date": "2020-09-30", "label": "early_trend"},
    {"ticker": "000270", "name": "기아", "date": "2021-06-30", "label": "trend_progressed"},
    {"ticker": "006400", "name": "삼성SDI", "date": "2020-03-31", "label": "pre_breakout"},
    {"ticker": "006400", "name": "삼성SDI", "date": "2020-06-30", "label": "early_trend"},
    {"ticker": "006400", "name": "삼성SDI", "date": "2021-01-31", "label": "trend_progressed"},
    {"ticker": "012330", "name": "현대모비스", "date": "2024-11-30", "label": "pre_breakout"},
    {"ticker": "012330", "name": "현대모비스", "date": "2025-06-30", "label": "early_trend"},
    {"ticker": "012330", "name": "현대모비스", "date": "2026-02-28", "label": "trend_progressed"},
]

NEGATIVE_CONTROL_SNAPSHOTS: list[dict[str, str]] = [
    {"ticker": "003550", "name": "LG", "date": "2020-12-31", "label": "failed_breakout"},
    {"ticker": "010130", "name": "고려아연", "date": "2022-06-30", "label": "failed_breakout"},
    {"ticker": "011170", "name": "롯데케미칼", "date": "2023-01-31", "label": "failed_higher_low"},
    {"ticker": "009150", "name": "삼성전기", "date": "2022-12-31", "label": "failed_momentum"},
    {"ticker": "018260", "name": "삼성에스디에스", "date": "2023-07-31", "label": "failed_breakout"},
    {"ticker": "032830", "name": "삼성생명", "date": "2021-02-28", "label": "failed_ma24_turn"},
    {"ticker": "034730", "name": "SK", "date": "2020-12-31", "label": "failed_weekly_turn"},
    {"ticker": "011200", "name": "HMM", "date": "2024-10-31", "label": "failed_breakout"},
]

# negative_control_validate.py의 NEGATIVE_SUBGROUP 그대로 재사용.
NEGATIVE_SUBGROUP: dict[str, str] = {
    "003550": "confirmed_negative",
    "010130": "confirmed_negative",
    "011170": "confirmed_negative",
    "032830": "confirmed_negative",
    "034730": "confirmed_negative",
    "009150": "ambiguous_negative",
    "018260": "ambiguous_negative",
    "011200": "ambiguous_negative",
}


def _load_daily(cache: ParquetCache, tickers: dict[str, str]) -> dict[str, pd.DataFrame]:
    daily_by_ticker: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        daily = cache.load(ticker)
        if daily is None or daily.empty:
            raise SystemExit(f"{ticker} 캐시가 없습니다. 새로 fetch하지 않습니다 — 먼저 캐시를 채워주세요.")
        daily_by_ticker[ticker] = daily
    return daily_by_ticker


def _build_snapshots(
    snapshots: list[dict[str, str]], daily_by_ticker: dict[str, pd.DataFrame]
) -> list[tuple[str, str, str, HistoricalSnapshot]]:
    records = []
    for s in snapshots:
        daily = daily_by_ticker[s["ticker"]]
        snap = build_historical_snapshot(
            s["ticker"], s["name"], daily, s["date"], include_incomplete_periods=False
        )
        records.append((s["ticker"], s["name"], s["label"], snap))
    return records


def _design_a(base_score: float | None, transition_score: float | None) -> float | None:
    """기각안: 단순 가산식(base 40% + transition 60%), clip 0~100."""
    if base_score is None or transition_score is None:
        return None
    raw = 0.4 * base_score + 0.6 * transition_score
    return max(0.0, min(100.0, raw))


def _design_b(balanced_core_score: float | None) -> float | None:
    """기각안: harmonic mean만(alignment bonus/progressed penalty 없음), clip 0~100."""
    if balanced_core_score is None:
        return None
    return max(0.0, min(100.0, balanced_core_score))


def _row(group: str, ticker: str, name: str, label: str, result: PatternAResult) -> dict:
    return {
        "group": group,
        "ticker": ticker,
        "name": name,
        "label": label,
        "base_score": result.base_score,
        "transition_score": result.transition_score,
        "balanced_core_score": result.balanced_core_score,
        "alignment_bonus": result.alignment_bonus,
        "progressed_penalty": result.progressed_penalty,
        "progressed_evidence_count": result.progressed_evidence_count,
        "design_a_score": _design_a(result.base_score, result.transition_score),
        "design_b_score": _design_b(result.balanced_core_score),
        "design_c_score": result.pattern_a_score,
        "stage": result.stage.value if result.stage is not None else None,
        "insufficient_data": result.flags.get("insufficient_data", False),
    }


def main() -> None:
    cache = ParquetCache(base_dir=CACHE_DIR)

    exploration_tickers = {s["ticker"]: s["name"] for s in EXPLORATION_SNAPSHOTS}
    holdout_tickers = {s["ticker"]: s["name"] for s in HOLDOUT_SNAPSHOTS}
    negative_tickers = {s["ticker"]: s["name"] for s in NEGATIVE_CONTROL_SNAPSHOTS}

    exploration_daily = _load_daily(cache, exploration_tickers)
    holdout_daily = _load_daily(cache, holdout_tickers)
    negative_daily = _load_daily(cache, negative_tickers)

    exploration_records = _build_snapshots(EXPLORATION_SNAPSHOTS, exploration_daily)
    holdout_records = _build_snapshots(HOLDOUT_SNAPSHOTS, holdout_daily)
    negative_records = _build_snapshots(NEGATIVE_CONTROL_SNAPSHOTS, negative_daily)

    rows: list[dict] = []

    for ticker, name, label, snap in exploration_records:
        result = score_pattern_a(snap.features)
        rows.append(_row("exploration", ticker, name, label, result))

    for ticker, name, label, snap in holdout_records:
        result = score_pattern_a(snap.features)
        rows.append(_row(f"holdout_{label}", ticker, name, label, result))

    for ticker, name, label, snap in negative_records:
        subgroup = NEGATIVE_SUBGROUP[ticker]
        result = score_pattern_a(snap.features)
        rows.append(_row(subgroup, ticker, name, label, result))

    df = pd.DataFrame(rows)

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"CSV saved: {OUTPUT_CSV} ({len(df)} rows)")
    print()

    display_cols = [
        "group",
        "ticker",
        "name",
        "label",
        "base_score",
        "transition_score",
        "balanced_core_score",
        "alignment_bonus",
        "progressed_penalty",
        "design_a_score",
        "design_b_score",
        "design_c_score",
        "stage",
    ]
    print("=" * 100)
    print("[Score Design] snapshot별 component score (Design A/B/C 비교 포함)")
    print("=" * 100)
    with pd.option_context("display.max_columns", None, "display.width", 240):
        print(df[display_cols].to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    print()

    required_groups = [
        "holdout_pre_breakout",
        "holdout_early_trend",
        "holdout_trend_progressed",
        "confirmed_negative",
        "ambiguous_negative",
    ]

    for score_col, design_name in [
        ("design_a_score", "Design A (가산식 40/60)"),
        ("design_b_score", "Design B (harmonic mean만)"),
        ("design_c_score", "Design C (harmonic + bonus - penalty, 채택안)"),
    ]:
        print("=" * 100)
        print(f"그룹별 {design_name} min / median / max (5개 필수 그룹)")
        print("=" * 100)
        stats = []
        for group in required_groups:
            values = df.loc[df["group"] == group, score_col].dropna()
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


if __name__ == "__main__":
    main()
