"""Base / Expansion Validation v0.1 실행 스크립트.

Pattern A v0.1 Feature Set Freeze 재리뷰 후속: compression_ratio를 Base
핵심 Feature에서 내린 뒤 대체 후보로 올린 range_36m/range_24m/range_12m/
avg_price_change_12m/ma_spread가 "아직 Base/Transition 상태인 종목"과
"이미 상승이 상당히 진행된 종목"을 실제로 구분하는지 확인한다.

Pattern A 점수는 계산하지 않는다. threshold/가중치/Hard Filter도 만들지
않는다 — 그룹별 min/median/max와 종목별 raw value만 관찰용으로 출력한다.
새 데이터 인프라나 새 KRX fetch는 없다 — 기존 historical_snapshot 캐시
(holdout 5종목, negative_control 8종목)를 그대로 재사용한다.

비교 그룹:
    holdout_pre_breakout     (positive, Base 상태)
    holdout_early_trend      (positive, Transition 막 시작)
    holdout_trend_progressed (positive, 이미 진행됨)
    confirmed_negative       (실패 사례, negative_control_validate.py의
                              NEGATIVE_SUBGROUP 그대로 재사용)

실행 (repo 루트에서, `pip install -e ".[dev]"` 이후):
    python scripts/base_expansion_validate.py

CSV 경로: data/processed/base_expansion_validation.csv (4그룹 raw value,
observational only).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.validation.historical_snapshot import (
    HistoricalSnapshot,
    build_historical_snapshot,
)
from trend_scanner.validation.negative_control_analysis import stats_table

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "data" / "raw" / "stocks"
OUTPUT_CSV = REPO_ROOT / "data" / "processed" / "base_expansion_validation.csv"

# scripts/negative_control_validate.py와 동일한 종목/날짜/label (재정의가
# 아니라 그대로 옮긴 것). 이 스크립트 하나로 재현 가능하도록 중복을 감수한다.
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
    {"ticker": "032830", "name": "삼성생명", "date": "2021-02-28", "label": "failed_ma24_turn"},
    {"ticker": "034730", "name": "SK", "date": "2020-12-31", "label": "failed_weekly_turn"},
]
# confirmed_negative만 쓴다(negative_control_validate.py의 NEGATIVE_SUBGROUP
# 참고). ambiguous_negative(009150/018260/011200)는 12개월 outcome이 꽤
# 견실하게 양수라 "이미 진행됨" 비교 기준으로 부적절해 이번 스크립트에서는
# 뺀다.

CANDIDATE_FEATURES = [
    "range_36m",
    "range_24m",
    "range_12m",
    "avg_price_change_12m",
    "ma_spread",
]

RAW_TABLE_COLUMNS = ["ticker", "name", "group", "label"] + CANDIDATE_FEATURES


def _load_daily(cache: ParquetCache, tickers: dict[str, str]) -> dict[str, pd.DataFrame]:
    daily_by_ticker: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        daily = cache.load(ticker)
        if daily is None or daily.empty:
            raise SystemExit(
                f"{ticker} 캐시가 없습니다. base_expansion_validate.py는 새로 fetch하지 "
                "않는다 — 먼저 historical_snapshot_validate.py/negative_control_validate.py로 캐시를 채워주세요."
            )
        daily_by_ticker[ticker] = daily
    return daily_by_ticker


def _build_group(
    snapshots: list[dict[str, str]],
    daily_by_ticker: dict[str, pd.DataFrame],
) -> list[tuple[str, str, str, HistoricalSnapshot]]:
    """(ticker, name, label, HistoricalSnapshot) 목록. completed monthly+weekly 고정."""
    records = []
    for s in snapshots:
        daily = daily_by_ticker[s["ticker"]]
        snap = build_historical_snapshot(
            s["ticker"], s["name"], daily, s["date"], include_incomplete_periods=False
        )
        records.append((s["ticker"], s["name"], s["label"], snap))
    return records


def _raw_rows(
    records: list[tuple[str, str, str, HistoricalSnapshot]], group_name: str
) -> list[dict]:
    rows = []
    for ticker, name, label, snap in records:
        f = snap.features
        row = {"ticker": ticker, "name": name, "group": group_name, "label": label}
        for col in CANDIDATE_FEATURES:
            row[col] = getattr(f, col)
        rows.append(row)
    return rows


def main() -> None:
    cache = ParquetCache(base_dir=CACHE_DIR)

    holdout_tickers = {s["ticker"]: s["name"] for s in HOLDOUT_SNAPSHOTS}
    negative_tickers = {s["ticker"]: s["name"] for s in NEGATIVE_CONTROL_SNAPSHOTS}

    holdout_daily = _load_daily(cache, holdout_tickers)
    negative_daily = _load_daily(cache, negative_tickers)

    holdout_records = _build_group(HOLDOUT_SNAPSHOTS, holdout_daily)
    negative_records = _build_group(NEGATIVE_CONTROL_SNAPSHOTS, negative_daily)

    holdout_pre = [(t, n, l, s) for t, n, l, s in holdout_records if l == "pre_breakout"]
    holdout_early = [(t, n, l, s) for t, n, l, s in holdout_records if l == "early_trend"]
    holdout_progressed = [(t, n, l, s) for t, n, l, s in holdout_records if l == "trend_progressed"]

    all_raw_rows = (
        _raw_rows(holdout_pre, "holdout_pre_breakout")
        + _raw_rows(holdout_early, "holdout_early_trend")
        + _raw_rows(holdout_progressed, "holdout_trend_progressed")
        + _raw_rows(negative_records, "confirmed_negative")
    )

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(all_raw_rows)[RAW_TABLE_COLUMNS].to_csv(OUTPUT_CSV, index=False)
    print(f"CSV saved: {OUTPUT_CSV} ({len(all_raw_rows)} rows)")
    print()

    print("=" * 90)
    print("[Base / Expansion Validation] 종목별 raw value")
    print("=" * 90)
    raw_df = pd.DataFrame(all_raw_rows)[RAW_TABLE_COLUMNS]
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(raw_df.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print()

    groups = {
        "holdout_pre_breakout": [s.features for _, _, _, s in holdout_pre],
        "holdout_early_trend": [s.features for _, _, _, s in holdout_early],
        "holdout_trend_progressed": [s.features for _, _, _, s in holdout_progressed],
        "confirmed_negative": [s.features for _, _, _, s in negative_records],
    }

    print("=" * 90)
    print("그룹별 min / median / max (4그룹: holdout pre/early/progressed, confirmed_negative)")
    print("=" * 90)
    stats_df = stats_table(groups, CANDIDATE_FEATURES)
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(stats_df.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print()


if __name__ == "__main__":
    main()
