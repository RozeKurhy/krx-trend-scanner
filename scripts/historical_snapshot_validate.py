"""Historical Snapshot Validation v0.1 실행 스크립트.

기존 종목들의 cached daily(Parquet)를 그대로 사용해서, 사람이 지정한 과거
날짜들을 기준으로 Historical Snapshot을 계산하고 CSV와 사람이 읽기 좋은
비교표로 출력한다.

Pattern A 점수는 계산하지 않는다. 상승 시작일을 자동으로 탐지하는 로직도
없다.

두 세트를 구분해서 다룬다.

- SNAPSHOTS (exploration set): 068270/035420/005930/000660. 날짜는 사람이
  직접 monthly close/MA24 slope/spread/compression 등 실제 Feature 값을
  눈으로 보고 골랐다(선정 근거는 완료 보고에 정리) — 즉 선택 편향이 있다.
- HOLDOUT_SNAPSHOTS (holdout set): 005380/051910/000270/006400/012330.
  Feature 값을 전혀 보지 않고 monthly 종가(raw close)만으로 구간을 먼저
  고정한 뒤 계산했다(선정 근거는 완료 보고에 정리).

실행 (repo 루트에서, `pip install -e ".[dev]"` 이후):
    python scripts/historical_snapshot_validate.py

새로 KRX를 호출하지 않는다. scripts/validate_features.py로 exploration
4종목을, 별도 fetch로 holdout 5종목을 먼저 캐시해둬야 한다
(data/raw/stocks/*.parquet).
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

# --- exploration set: 기존 4종목. Feature 값을 보고 고른 날짜(선택 편향 있음) ---
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

# --- holdout set: Feature 값은 전혀 안 보고 monthly raw close 흐름만 보고 고른 날짜 ---
HOLDOUT_SNAPSHOTS: list[dict[str, str]] = [
    # --- 005380 현대차 ---
    {"ticker": "005380", "name": "현대차", "date": "2020-06-30", "label": "pre_breakout"},
    {"ticker": "005380", "name": "현대차", "date": "2020-08-31", "label": "early_trend"},
    {"ticker": "005380", "name": "현대차", "date": "2021-02-28", "label": "trend_progressed"},
    {"ticker": "005380", "name": "현대차", "date": "2022-12-31", "label": "unfavorable"},
    # --- 051910 LG화학 ---
    {"ticker": "051910", "name": "LG화학", "date": "2020-03-31", "label": "pre_breakout"},
    {"ticker": "051910", "name": "LG화학", "date": "2020-06-30", "label": "early_trend"},
    {"ticker": "051910", "name": "LG화학", "date": "2021-01-31", "label": "trend_progressed"},
    {"ticker": "051910", "name": "LG화학", "date": "2024-07-31", "label": "unfavorable"},
    # --- 000270 기아 ---
    {"ticker": "000270", "name": "기아", "date": "2020-06-30", "label": "pre_breakout"},
    {"ticker": "000270", "name": "기아", "date": "2020-09-30", "label": "early_trend"},
    {"ticker": "000270", "name": "기아", "date": "2021-06-30", "label": "trend_progressed"},
    {"ticker": "000270", "name": "기아", "date": "2022-10-31", "label": "unfavorable"},
    # --- 006400 삼성SDI ---
    {"ticker": "006400", "name": "삼성SDI", "date": "2020-03-31", "label": "pre_breakout"},
    {"ticker": "006400", "name": "삼성SDI", "date": "2020-06-30", "label": "early_trend"},
    {"ticker": "006400", "name": "삼성SDI", "date": "2021-01-31", "label": "trend_progressed"},
    {"ticker": "006400", "name": "삼성SDI", "date": "2024-11-30", "label": "unfavorable"},
    # --- 012330 현대모비스 ---
    {"ticker": "012330", "name": "현대모비스", "date": "2024-11-30", "label": "pre_breakout"},
    {"ticker": "012330", "name": "현대모비스", "date": "2025-06-30", "label": "early_trend"},
    {"ticker": "012330", "name": "현대모비스", "date": "2026-02-28", "label": "trend_progressed"},
    {"ticker": "012330", "name": "현대모비스", "date": "2022-06-30", "label": "unfavorable"},
]

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


def _load_daily(cache: ParquetCache, tickers: dict[str, str]) -> dict[str, pd.DataFrame]:
    daily_by_ticker: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        daily = cache.load(ticker)
        if daily is None or daily.empty:
            raise SystemExit(
                f"{ticker} 캐시가 없습니다. 먼저 해당 종목을 fetch해서 "
                "data/raw/stocks/*.parquet를 채워주세요."
            )
        daily_by_ticker[ticker] = daily
    return daily_by_ticker


def _build_records(
    snapshots: list[dict[str, str]],
    daily_by_ticker: dict[str, pd.DataFrame],
    tickers: dict[str, str],
    add_current: bool,
) -> list[tuple[str, str, HistoricalSnapshot, HistoricalSnapshot]]:
    records: list[tuple[str, str, HistoricalSnapshot, HistoricalSnapshot]] = []
    for s in snapshots:
        daily = daily_by_ticker[s["ticker"]]
        completed, live = _build_pair(s["ticker"], s["name"], daily, s["date"])
        records.append((s["ticker"], s["label"], completed, live))

    if add_current:
        # completed/live 정책이 실제로 다른 결과를 만드는지 보여주는 참고용
        # snapshot. snapshot_date를 캐시의 가장 최근 날짜(보통 월/주 중간)로
        # 두면 진행 중인 달/주가 생겨서 실제로 갈라진다.
        for ticker, name in tickers.items():
            daily = daily_by_ticker[ticker]
            today = daily.index.max()
            completed, live = _build_pair(ticker, name, daily, str(today.date()))
            records.append((ticker, CURRENT_LABEL, completed, live))

    return records


def _main_rows(records: list[tuple[str, str, HistoricalSnapshot, HistoricalSnapshot]]) -> list[dict]:
    rows = []
    for ticker, label, completed, live in records:
        if label == CURRENT_LABEL:
            continue
        f = completed.features
        row = {
            "ticker": ticker,
            "name": f.name,
            "label": label,
            "date": completed.requested_snapshot_date.date(),
            "monthly_as_of": completed.monthly_as_of.date() if completed.monthly_as_of is not None else None,
            "weekly_as_of": completed.weekly_as_of.date() if completed.weekly_as_of is not None else None,
        }
        for col in MAIN_TABLE_COLUMNS:
            row[col] = getattr(f, col)
        rows.append(row)
    return rows


def _print_current_divergence(records: list[tuple[str, str, HistoricalSnapshot, HistoricalSnapshot]]) -> None:
    for ticker, label, completed, live in records:
        if label != CURRENT_LABEL:
            continue
        f_c, f_l = completed.features, live.features
        print(
            f"[{ticker} {f_c.name}] requested={completed.requested_snapshot_date.date()} "
            f"effective_as_of={completed.effective_as_of.date() if completed.effective_as_of is not None else None}"
        )
        print(
            f"  completed: monthly_rows={f_c.monthly_rows} monthly_as_of={completed.monthly_as_of} "
            f"weekly_rows={f_c.weekly_rows} weekly_as_of={completed.weekly_as_of} "
            f"close={_fmt(f_c.close, 0)} ma24_slope={_fmt(f_c.ma24_slope)} "
            f"weekly_ma12_slope={_fmt(f_c.weekly_ma12_slope)} range_position_52w={_fmt(f_c.range_position_52w)}"
        )
        print(
            f"  live:      monthly_rows={f_l.monthly_rows} monthly_as_of={live.monthly_as_of} "
            f"weekly_rows={f_l.weekly_rows} weekly_as_of={live.weekly_as_of} "
            f"close={_fmt(f_l.close, 0)} ma24_slope={_fmt(f_l.ma24_slope)} "
            f"weekly_ma12_slope={_fmt(f_l.weekly_ma12_slope)} range_position_52w={_fmt(f_l.range_position_52w)}"
        )
        print()


def _print_main_table(main_rows: list[dict]) -> None:
    main_df = pd.DataFrame(main_rows)
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(main_df.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print()


def _print_time_series(main_rows: list[dict], tickers: dict[str, str]) -> None:
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


def main() -> None:
    cache = ParquetCache(base_dir=CACHE_DIR)

    exploration_tickers = {s["ticker"]: s["name"] for s in SNAPSHOTS}
    holdout_tickers = {s["ticker"]: s["name"] for s in HOLDOUT_SNAPSHOTS}

    exploration_daily = _load_daily(cache, exploration_tickers)
    holdout_daily = _load_daily(cache, holdout_tickers)

    exploration_records = _build_records(SNAPSHOTS, exploration_daily, exploration_tickers, add_current=True)
    holdout_records = _build_records(HOLDOUT_SNAPSHOTS, holdout_daily, holdout_tickers, add_current=False)

    # --- CSV: exploration + holdout, completed/live 둘 다, set/include_incomplete_periods 컬럼으로 구분 ---
    csv_rows = []
    for set_name, records in (("exploration", exploration_records), ("holdout", holdout_records)):
        for ticker, label, completed, live in records:
            for snap in (completed, live):
                row = to_csv_row(label, snap)
                row["set"] = set_name
                csv_rows.append(row)
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(csv_rows).to_csv(OUTPUT_CSV, index=False)
    print(f"CSV saved: {OUTPUT_CSV} ({len(csv_rows)} rows)")
    print()

    print("=" * 70)
    print("completed vs live monthly/weekly 비교 (참고용, exploration 'current' snapshot만)")
    print("=" * 70)
    _print_current_divergence(exploration_records)

    print("=" * 70)
    print("[EXPLORATION] 전체 Historical Snapshot 비교표 (completed monthly 기준)")
    print("=" * 70)
    exploration_main_rows = _main_rows(exploration_records)
    _print_main_table(exploration_main_rows)

    print("=" * 70)
    print("[EXPLORATION] 종목별 시간 흐름 비교 (completed monthly 기준, 날짜순, delta는 참고용)")
    print("=" * 70)
    _print_time_series(exploration_main_rows, exploration_tickers)

    print("=" * 70)
    print("[HOLDOUT] 전체 Historical Snapshot 비교표 (completed monthly 기준)")
    print("=" * 70)
    holdout_main_rows = _main_rows(holdout_records)
    _print_main_table(holdout_main_rows)

    print("=" * 70)
    print("[HOLDOUT] 종목별 시간 흐름 비교 (completed monthly 기준, 날짜순, delta는 참고용)")
    print("=" * 70)
    _print_time_series(holdout_main_rows, holdout_tickers)


if __name__ == "__main__":
    main()
