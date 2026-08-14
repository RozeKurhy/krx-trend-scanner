"""Negative Control Validation v0.1 실행 스크립트.

지금까지(Historical Snapshot Validation v0.1)는 "나중에 크게 오른 종목"의
pre_breakout/early_trend/trend_progressed 구조만 봤다. 이번에는 반대로,
당시에는 비슷하게 좋아 보였지만 상승이 이어지지 않았거나 돌파에 실패했거나
다시 하락한 사례(negative_control)를 모아서, 지금까지 유력해 보였던 Feature
신호가 실패 사례에서도 흔하게 나타나는지 확인한다.

Pattern A 점수는 계산하지 않는다. threshold/가중치/Hard Filter도 만들지
않는다 — 그룹별 min/median/max와 조건 발생 비율만 관찰용으로 출력한다.

**중요 원칙(look-ahead와 무관하지만 반드시 지켜야 함)**: negative_control
날짜를 고를 때 "그 이후 정말 실패했는지" 확인하려면 snapshot_date 이후의
가격을 볼 수밖에 없다. 하지만 그건 **라벨을 정하는 데만** 쓴다.
Feature 계산은 지금까지와 동일하게 build_historical_snapshot()이
snapshot_date 이하 데이터만 사용해서 계산한다 — 미래 가격이 Feature
계산에 섞여 들어가는 경로는 없다(look-ahead 방지 로직은 그대로).

**Outcome Audit도 같은 원칙**: snapshot 이후 실제 수익률/drawdown을
계산하는 outcome_audit 모듈은 Feature 계산과 완전히 분리된 별도 경로다.
그 결과값은 label을 사람이 검토하기 위한 참고 자료일 뿐, Feature에도
Pattern A Score에도 threshold 최적화에도 절대 쓰지 않는다.

핵심 비교는 holdout(positive: pre_breakout/early_trend) vs negative_control.
exploration은 선택 편향이 있어 참고용으로만 화면 출력에 남긴다(CSV에는
안 남긴다 — 아래 CSV 경로 설명 참고).

실행 (repo 루트에서, `pip install -e ".[dev]"` 이후):
    python scripts/negative_control_validate.py

새로 KRX를 호출하지 않는다. 아래 종목들이 먼저 캐시돼 있어야 한다
(exploration 4종목, holdout 5종목은 이전 라운드에서 이미 캐시됨;
negative_control 8종목은 이번 라운드에서 새로 fetch해서 캐시했다).

**CSV 경로**: `data/processed/historical_snapshots.csv`는
`scripts/historical_snapshot_validate.py`만 쓴다(exploration/holdout,
completed+live). 이 스크립트는 별도로
`data/processed/negative_control_validation.csv`(negative_control만,
completed 기준)와 `data/processed/outcome_audit.csv`(세 세트 전체의
outcome metadata)를 쓴다. 두 스크립트가 같은 파일을 놓고 경쟁하지 않는다.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.validation.historical_snapshot import (
    HistoricalSnapshot,
    build_historical_snapshot,
)
from trend_scanner.validation.negative_control_analysis import (
    CONDITIONS,
    condition_table,
    snapshot_csv_rows,
    stats_table,
)
from trend_scanner.validation.outcome_audit import compute_outcome, outcome_csv_row

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "data" / "raw" / "stocks"
NEGATIVE_CONTROL_CSV = REPO_ROOT / "data" / "processed" / "negative_control_validation.csv"
OUTCOME_AUDIT_CSV = REPO_ROOT / "data" / "processed" / "outcome_audit.csv"

# --- exploration set (참고용, 선택 편향 있음) ---
SNAPSHOTS: list[dict[str, str]] = [
    {"ticker": "068270", "name": "셀트리온", "date": "2019-12-31", "label": "pre_breakout"},
    {"ticker": "068270", "name": "셀트리온", "date": "2020-06-30", "label": "early_trend"},
    {"ticker": "068270", "name": "셀트리온", "date": "2020-12-31", "label": "trend_progressed"},
    {"ticker": "068270", "name": "셀트리온", "date": "2023-03-31", "label": "unfavorable"},
    {"ticker": "035420", "name": "NAVER", "date": "2020-03-31", "label": "pre_breakout"},
    {"ticker": "035420", "name": "NAVER", "date": "2020-06-30", "label": "early_trend"},
    {"ticker": "035420", "name": "NAVER", "date": "2021-06-30", "label": "trend_progressed"},
    {"ticker": "035420", "name": "NAVER", "date": "2022-12-31", "label": "unfavorable"},
    {"ticker": "005930", "name": "삼성전자", "date": "2019-09-30", "label": "pre_breakout"},
    {"ticker": "005930", "name": "삼성전자", "date": "2020-09-30", "label": "early_trend"},
    {"ticker": "005930", "name": "삼성전자", "date": "2021-03-31", "label": "trend_progressed"},
    {"ticker": "005930", "name": "삼성전자", "date": "2022-12-31", "label": "unfavorable"},
    {"ticker": "000660", "name": "SK하이닉스", "date": "2023-03-31", "label": "pre_breakout"},
    {"ticker": "000660", "name": "SK하이닉스", "date": "2023-12-31", "label": "early_trend"},
    {"ticker": "000660", "name": "SK하이닉스", "date": "2024-06-30", "label": "trend_progressed"},
    {"ticker": "000660", "name": "SK하이닉스", "date": "2022-12-31", "label": "unfavorable"},
]

# --- holdout set (핵심 positive 비교 기준) ---
HOLDOUT_SNAPSHOTS: list[dict[str, str]] = [
    {"ticker": "005380", "name": "현대차", "date": "2020-06-30", "label": "pre_breakout"},
    {"ticker": "005380", "name": "현대차", "date": "2020-08-31", "label": "early_trend"},
    {"ticker": "005380", "name": "현대차", "date": "2021-02-28", "label": "trend_progressed"},
    {"ticker": "005380", "name": "현대차", "date": "2022-12-31", "label": "unfavorable"},
    {"ticker": "051910", "name": "LG화학", "date": "2020-03-31", "label": "pre_breakout"},
    {"ticker": "051910", "name": "LG화학", "date": "2020-06-30", "label": "early_trend"},
    {"ticker": "051910", "name": "LG화학", "date": "2021-01-31", "label": "trend_progressed"},
    {"ticker": "051910", "name": "LG화학", "date": "2024-07-31", "label": "unfavorable"},
    {"ticker": "000270", "name": "기아", "date": "2020-06-30", "label": "pre_breakout"},
    {"ticker": "000270", "name": "기아", "date": "2020-09-30", "label": "early_trend"},
    {"ticker": "000270", "name": "기아", "date": "2021-06-30", "label": "trend_progressed"},
    {"ticker": "000270", "name": "기아", "date": "2022-10-31", "label": "unfavorable"},
    {"ticker": "006400", "name": "삼성SDI", "date": "2020-03-31", "label": "pre_breakout"},
    {"ticker": "006400", "name": "삼성SDI", "date": "2020-06-30", "label": "early_trend"},
    {"ticker": "006400", "name": "삼성SDI", "date": "2021-01-31", "label": "trend_progressed"},
    {"ticker": "006400", "name": "삼성SDI", "date": "2024-11-30", "label": "unfavorable"},
    {"ticker": "012330", "name": "현대모비스", "date": "2024-11-30", "label": "pre_breakout"},
    {"ticker": "012330", "name": "현대모비스", "date": "2025-06-30", "label": "early_trend"},
    {"ticker": "012330", "name": "현대모비스", "date": "2026-02-28", "label": "trend_progressed"},
    {"ticker": "012330", "name": "현대모비스", "date": "2022-06-30", "label": "unfavorable"},
]

# --- negative_control set ---
# 날짜는 monthly raw close(시가/고가/저가/거래량/파생 Feature는 보지 않음)만 보고
# "당시엔 상승할 것처럼 보였지만 실패한 시점"을 먼저 고정했다. 선정 근거는
# 완료 보고에 정리한다. 카카오는 미보정 OHLC 위반(2018-05-16)이 있어 후보에서
# 제외했다(이번 스코프에서 provider 보정 정책을 확장하지 않음).
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
    "distance_to_resistance",
]

STATS_ATTRS = [
    "ma24_slope",
    "ma24_slope_acceleration",
    "weekly_ma12_slope",
    "range_position",
    "range_position_52w",
    "compression_ratio",
    "ma_spread",
    "ma_spread_ratio",
    "atr_ratio",
]


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


def _build_completed_snapshots(
    snapshots: list[dict[str, str]], daily_by_ticker: dict[str, pd.DataFrame]
) -> list[tuple[str, str, HistoricalSnapshot]]:
    """(ticker, label, HistoricalSnapshot) 목록. completed monthly+weekly 고정."""
    records = []
    for s in snapshots:
        daily = daily_by_ticker[s["ticker"]]
        snap = build_historical_snapshot(
            s["ticker"], s["name"], daily, s["date"], include_incomplete_periods=False
        )
        records.append((s["ticker"], s["label"], snap))
    return records


def _main_rows(records: list[tuple[str, str, HistoricalSnapshot]]) -> list[dict]:
    rows = []
    for ticker, label, snap in records:
        f = snap.features
        row = {
            "ticker": ticker,
            "name": f.name,
            "label": label,
            "requested_snapshot_date": snap.requested_snapshot_date.date(),
            "effective_as_of": snap.effective_as_of.date() if snap.effective_as_of is not None else None,
            "monthly_as_of": snap.monthly_as_of.date() if snap.monthly_as_of is not None else None,
            "weekly_as_of": snap.weekly_as_of.date() if snap.weekly_as_of is not None else None,
        }
        for col in MAIN_TABLE_COLUMNS:
            row[col] = getattr(f, col)
        rows.append(row)
    return rows


def _print_table(rows: list[dict]) -> None:
    df = pd.DataFrame(rows)
    with pd.option_context("display.max_columns", None, "display.width", 220):
        print(df.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print()


def main() -> None:
    cache = ParquetCache(base_dir=CACHE_DIR)

    exploration_tickers = {s["ticker"]: s["name"] for s in SNAPSHOTS}
    holdout_tickers = {s["ticker"]: s["name"] for s in HOLDOUT_SNAPSHOTS}
    negative_tickers = {s["ticker"]: s["name"] for s in NEGATIVE_CONTROL_SNAPSHOTS}

    exploration_daily = _load_daily(cache, exploration_tickers)
    holdout_daily = _load_daily(cache, holdout_tickers)
    negative_daily = _load_daily(cache, negative_tickers)

    exploration_records = _build_completed_snapshots(SNAPSHOTS, exploration_daily)
    holdout_records = _build_completed_snapshots(HOLDOUT_SNAPSHOTS, holdout_daily)
    negative_records = _build_completed_snapshots(NEGATIVE_CONTROL_SNAPSHOTS, negative_daily)

    # --- CSV: negative_control만. exploration/holdout은 historical_snapshots.csv가 소유한다. ---
    negative_labeled = [(label, snap) for _, label, snap in negative_records]
    negative_csv_rows = snapshot_csv_rows(negative_labeled, "negative_control")
    NEGATIVE_CONTROL_CSV.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(negative_csv_rows).to_csv(NEGATIVE_CONTROL_CSV, index=False)
    print(f"CSV saved: {NEGATIVE_CONTROL_CSV} ({len(negative_csv_rows)} rows)")
    print()

    holdout_pre = [snap.features for t, label, snap in holdout_records if label == "pre_breakout"]
    holdout_early = [snap.features for t, label, snap in holdout_records if label == "early_trend"]
    negative = [snap.features for t, label, snap in negative_records]

    print("=" * 70)
    print("[NEGATIVE CONTROL] 전체 raw Feature 비교표 (completed monthly+weekly 기준)")
    print("=" * 70)
    _print_table(_main_rows(negative_records))

    print("=" * 70)
    print("[HOLDOUT pre_breakout] 비교용 raw Feature 표")
    print("=" * 70)
    _print_table(_main_rows([r for r in holdout_records if r[1] == "pre_breakout"]))

    print("=" * 70)
    print("[HOLDOUT early_trend] 비교용 raw Feature 표")
    print("=" * 70)
    _print_table(_main_rows([r for r in holdout_records if r[1] == "early_trend"]))

    groups = {
        "holdout_pre_breakout": holdout_pre,
        "holdout_early_trend": holdout_early,
        "negative_control": negative,
    }

    print("=" * 70)
    print("그룹별 min / median / max")
    print("=" * 70)
    stats_df = stats_table(groups, STATS_ATTRS)
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(stats_df.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print()

    print("=" * 70)
    print("조건별 발생 비율 (단일 Feature + 조합 A~E, 관찰용, threshold 확정 아님)")
    print("=" * 70)
    cond_df = condition_table(groups, CONDITIONS)
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(cond_df.to_string(index=False))
    print()

    # --- Outcome Audit: label 검토용. Feature/Score/threshold에는 절대 사용하지 않는다. ---
    daily_by_ticker = {**exploration_daily, **holdout_daily, **negative_daily}
    all_records = (
        [("exploration", *r) for r in exploration_records]
        + [("holdout", *r) for r in holdout_records]
        + [("negative_control", *r) for r in negative_records]
    )
    outcome_rows = []
    for set_name, ticker, label, snap in all_records:
        daily = daily_by_ticker[ticker]
        outcome = compute_outcome(daily, snap.effective_as_of)
        row = outcome_csv_row(ticker, snap.features.name, label, outcome)
        row["set"] = set_name
        outcome_rows.append(row)

    OUTCOME_AUDIT_CSV.parent.mkdir(parents=True, exist_ok=True)
    outcome_df = pd.DataFrame(outcome_rows)
    outcome_df.to_csv(OUTCOME_AUDIT_CSV, index=False)
    print(f"CSV saved: {OUTCOME_AUDIT_CSV} ({len(outcome_rows)} rows)")
    print()

    print("=" * 70)
    print("Outcome Audit 전체 (snapshot 이후 실제 가격, label 검토용 — Feature/Score에 미사용)")
    print("=" * 70)
    display_cols = [
        "set",
        "ticker",
        "name",
        "label",
        "base_date",
        "return_3m_max",
        "return_6m_max",
        "return_12m_max",
        "return_6m_end",
        "return_12m_end",
        "drawdown_12m_max",
        "months_to_peak_12m",
    ]
    with pd.option_context("display.max_columns", None, "display.width", 220):
        print(outcome_df[display_cols].to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print()

    print("=" * 70)
    print("애매한 negative 사례 (003550 LG / 010130 고려아연 / 034730 SK / 011200 HMM)")
    print("=" * 70)
    focus_tickers = {"003550", "010130", "034730", "011200"}
    focus_df = outcome_df[outcome_df["ticker"].isin(focus_tickers)]
    with pd.option_context("display.max_columns", None, "display.width", 220):
        print(focus_df[display_cols].to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print()


if __name__ == "__main__":
    main()
