"""Historical Snapshot Validation v0.1 실행 스크립트.

기존 4종목의 cached daily(Feature Validation v0.1에서 이미 받아둔 Parquet)를 그대로
사용해서, 사람이 지정한 과거 날짜들을 기준으로 Historical Snapshot을 계산하고
CSV와 사람이 읽기 좋은 비교표로 출력한다.

Pattern A 점수는 계산하지 않는다. 상승 시작일을 자동으로 탐지하는 로직도 없다 —
SNAPSHOTS 목록의 날짜는 사람이 직접 monthly close/MA24 slope 등 실제 Feature
값을 눈으로 보고 고른 것이다(선정 근거는 완료 보고에 정리).

실행 (repo 루트에서, `pip install -e ".[dev]"` 이후):
    python scripts/historical_snapshot_validate.py

새로 KRX를 호출하지 않는다. scripts/validate_features.py를 먼저 실행해서
data/raw/stocks/*.parquet 캐시가 있어야 한다.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.validation.historical_snapshot import (
    HistoricalSnapshot,
    build_historical_snapshot,
    to_csv_row,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "data" / "raw" / "stocks"
OUTPUT_CSV = REPO_ROOT / "data" / "processed" / "historical_snapshots.csv"

# 사람이 고른 snapshot 날짜 목록. label은 해석용 문자열일 뿐 점수 계산에 쓰이지 않는다.
# 날짜 선정 근거는 완료 보고에 정리한다(월봉 close/MA24 slope/compression 등 실제
# 캐시된 Feature 값을 직접 확인하고 골랐다. 자동 탐지 로직은 없다).
SNAPSHOTS: list[dict[str, str]] = [
    # --- 068270 셀트리온 ---
    {"ticker": "068270", "name": "셀트리온", "date": "2019-12-31", "label": "pre_breakout"},
    {"ticker": "068270", "name": "셀트리온", "date": "2020-06-30", "label": "early_trend"},
    {"ticker": "068270", "name": "셀트리온", "date": "2020-12-31", "label": "trend_progressed"},
    {"ticker": "068270", "name": "셀트리온", "date": "2023-03-31", "label": "unfavorable"},
    # --- 035420 NAVER ---
    {"ticker": "035420", "name": "NAVER", "date": "2020-03-31", "label": "pre_breakout"},
    {"ticker": "035420", "name": "NAVER", "date": "2020-06-30", "label": "early_trend"},
    {"ticker": "035420", "name": "NAVER", "date": "2021-06-30", "label": "trend_progressed"},
    {"ticker": "035420", "name": "NAVER", "date": "2022-12-31", "label": "unfavorable"},
    # --- 005930 삼성전자 ---
    {"ticker": "005930", "name": "삼성전자", "date": "2019-09-30", "label": "pre_breakout"},
    {"ticker": "005930", "name": "삼성전자", "date": "2020-09-30", "label": "early_trend"},
    {"ticker": "005930", "name": "삼성전자", "date": "2021-03-31", "label": "trend_progressed"},
    {"ticker": "005930", "name": "삼성전자", "date": "2022-12-31", "label": "unfavorable"},
    # --- 000660 SK하이닉스 ---
    {"ticker": "000660", "name": "SK하이닉스", "date": "2023-03-31", "label": "pre_breakout"},
    {"ticker": "000660", "name": "SK하이닉스", "date": "2023-12-31", "label": "early_trend"},
    {"ticker": "000660", "name": "SK하이닉스", "date": "2024-06-30", "label": "trend_progressed"},
    {"ticker": "000660", "name": "SK하이닉스", "date": "2022-12-31", "label": "unfavorable"},
]

# completed/live 정책(6~14번 문서 항목)이 실제로 다른 결과를 만드는지 보여주는
# 참고용 snapshot. snapshot_date를 각 종목의 가장 최근 캐시 날짜(보통 월 중간)로
# 두면 진행 중인 달이 생겨서 live/completed가 실제로 갈라진다.
CURRENT_LABEL = "current"

DELTA_COLUMNS = ["ma24_slope", "ma_spread", "atr_ratio", "range_position"]

MAIN_TABLE_COLUMNS = [
    "close",
    "range_36m",
    "compression_ratio",
    "range_position",
    "pivot_low_slope",
    "ma24_slope",
    "ma24_slope_acceleration",
    "ma_spread",
    "ma_spread_ratio",
    "atr_ratio",
    "range_position_52w",
    "weekly_ma12_slope",
]


def _build_pair(ticker: str, name: str, daily: pd.DataFrame, date: str) -> tuple[HistoricalSnapshot, HistoricalSnapshot]:
    """같은 (ticker, date)에 대해 completed/live 두 버전을 만든다."""
    completed = build_historical_snapshot(ticker, name, daily, date, include_incomplete_periods=False)
    live = build_historical_snapshot(ticker, name, daily, date, include_incomplete_periods=True)
    return completed, live


def _fmt(value, digits: int = 4) -> str:
    if value is None:
        return "N/A"
    try:
        if pd.isna(value):
            return "NaN"
    except (TypeError, ValueError):
        pass
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def main() -> None:
    cache = ParquetCache(base_dir=CACHE_DIR)

    tickers = {s["ticker"]: s["name"] for s in SNAPSHOTS}
    daily_by_ticker: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        daily = cache.load(ticker)
        if daily is None or daily.empty:
            raise SystemExit(
                f"{ticker} 캐시가 없습니다. 먼저 scripts/validate_features.py를 실행해 "
                "data/raw/stocks/*.parquet를 채워주세요."
            )
        daily_by_ticker[ticker] = daily

    # (ticker, label) -> (completed, live)
    records: list[tuple[str, str, HistoricalSnapshot, HistoricalSnapshot]] = []
    for s in SNAPSHOTS:
        daily = daily_by_ticker[s["ticker"]]
        completed, live = _build_pair(s["ticker"], s["name"], daily, s["date"])
        records.append((s["ticker"], s["label"], completed, live))

    # ticker별 "현재" snapshot(캐시 마지막 날짜) 추가 -> live/completed 실제 분기 확인용
    for ticker, name in tickers.items():
        daily = daily_by_ticker[ticker]
        today = daily.index.max()
        completed, live = _build_pair(ticker, name, daily, str(today.date()))
        records.append((ticker, CURRENT_LABEL, completed, live))

    # --- CSV: completed/live 둘 다, include_incomplete_periods 컬럼으로 구분 ---
    csv_rows = []
    for ticker, label, completed, live in records:
        csv_rows.append(to_csv_row(label, completed))
        csv_rows.append(to_csv_row(label, live))
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(csv_rows).to_csv(OUTPUT_CSV, index=False)
    print(f"CSV saved: {OUTPUT_CSV} ({len(csv_rows)} rows)")
    print()

    # --- live/completed 실제 divergence 확인(참고용) ---
    print("=" * 70)
    print("completed vs live monthly 비교 (참고용, 'current' snapshot만)")
    print("=" * 70)
    for ticker, label, completed, live in records:
        if label != CURRENT_LABEL:
            continue
        f_c, f_l = completed.features, live.features
        print(
            f"[{ticker} {f_c.name}] requested={completed.requested_snapshot_date.date()} "
            f"effective_as_of={completed.effective_as_of.date() if completed.effective_as_of is not None else None}"
        )
        print(
            f"  completed: monthly_rows={f_c.monthly_rows} close={_fmt(f_c.close, 0)} "
            f"ma24_slope={_fmt(f_c.ma24_slope)}"
        )
        print(
            f"  live:      monthly_rows={f_l.monthly_rows} close={_fmt(f_l.close, 0)} "
            f"ma24_slope={_fmt(f_l.ma24_slope)}"
        )
        print()

    # --- 메인 비교표: completed monthly 기준(14번 항목 기본값) ---
    print("=" * 70)
    print("전체 Historical Snapshot 비교표 (completed monthly 기준)")
    print("=" * 70)
    main_rows = []
    for ticker, label, completed, live in records:
        if label == CURRENT_LABEL:
            continue
        f = completed.features
        row = {
            "ticker": ticker,
            "name": f.name,
            "label": label,
            "date": completed.requested_snapshot_date.date(),
        }
        for col in MAIN_TABLE_COLUMNS:
            row[col] = getattr(f, col)
        main_rows.append(row)
    main_df = pd.DataFrame(main_rows)
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(main_df.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print()

    # --- 종목별 시간 흐름 비교 + delta 참고 컬럼(점수화하지 않음, 참고용) ---
    print("=" * 70)
    print("종목별 시간 흐름 비교 (completed monthly 기준, 날짜순, delta는 참고용)")
    print("=" * 70)
    for ticker, name in tickers.items():
        ticker_rows = [r for r in main_rows if r["ticker"] == ticker]
        ticker_rows.sort(key=lambda r: r["date"])
        df = pd.DataFrame(ticker_rows)
        for col in DELTA_COLUMNS:
            df[f"delta_{col}"] = df[col].diff()
        print(f"[{ticker} {name}]")
        display_cols = ["date", "label"] + DELTA_COLUMNS + [f"delta_{c}" for c in DELTA_COLUMNS]
        with pd.option_context("display.max_columns", None, "display.width", 200):
            print(df[display_cols].to_string(index=False, float_format=lambda v: f"{v:.4f}"))
        print()


if __name__ == "__main__":
    main()
