import math
from dataclasses import fields

import pandas as pd
import pytest

from trend_scanner.data.resampler import to_monthly, to_weekly
from trend_scanner.validation.feature_report import FeatureRow
from trend_scanner.validation.historical_snapshot import (
    HistoricalSnapshot,
    build_historical_snapshot,
    to_csv_row,
)


def _daily_frame(n: int, start: str = "2015-01-01", freq: str = "D") -> pd.DataFrame:
    index = pd.date_range(start, periods=n, freq=freq)
    close = [100.0 + i * 0.1 for i in range(n)]
    return pd.DataFrame(
        {
            "open": close,
            "high": [c + 1 for c in close],
            "low": [c - 1 for c in close],
            "close": close,
            "volume": [1000.0] * n,
            "trading_value": [1.0e8] * n,
        },
        index=index,
    )


def _assert_features_equal(a: FeatureRow, b: FeatureRow) -> None:
    for f in fields(a):
        va, vb = getattr(a, f.name), getattr(b, f.name)
        if isinstance(va, float) and isinstance(vb, float) and math.isnan(va) and math.isnan(vb):
            continue
        assert va == vb, f"{f.name}: {va!r} != {vb!r}"


def test_snapshot_excludes_data_after_snapshot_date():
    daily = _daily_frame(1500)
    snapshot_date = daily.index[900]

    snap_from_full = build_historical_snapshot("TEST", "테스트", daily, snapshot_date)

    truncated = daily[daily.index <= snapshot_date]
    snap_from_truncated = build_historical_snapshot("TEST", "테스트", truncated, snapshot_date)

    assert snap_from_full.effective_as_of == snapshot_date
    _assert_features_equal(snap_from_full.features, snap_from_truncated.features)

    # 미래 데이터가 있는 daily를 넘겨도 daily_rows는 snapshot_date까지만 세어야 한다.
    assert snap_from_full.features.daily_rows == len(truncated)
    assert snap_from_full.features.daily_rows < len(daily)


def test_non_trading_snapshot_date_uses_last_trading_day():
    daily = _daily_frame(400, freq="B")  # 영업일만 있는 데이터 -> 토/일은 index에 없음
    fridays = daily.index[daily.index.weekday == 4]
    friday = fridays[50]
    saturday = friday + pd.Timedelta(days=1)
    assert saturday not in daily.index

    snap_on_saturday = build_historical_snapshot("TEST", "테스트", daily, saturday)
    snap_on_friday = build_historical_snapshot("TEST", "테스트", daily, friday)

    assert snap_on_saturday.requested_snapshot_date == saturday
    assert snap_on_saturday.effective_as_of == friday
    _assert_features_equal(snap_on_saturday.features, snap_on_friday.features)


def test_insufficient_history_returns_nan_without_error():
    daily = _daily_frame(40)  # 약 1.3개월치 -> 36개월 range 계산 불가
    snapshot_date = daily.index[-1]

    snap = build_historical_snapshot("TEST", "테스트", daily, snapshot_date)

    assert snap.effective_as_of == snapshot_date
    assert math.isnan(snap.features.range_36m)
    assert math.isnan(snap.features.ma24)


def test_snapshot_before_any_data_returns_empty_result_without_error():
    daily = _daily_frame(40)
    snapshot_date = daily.index[0] - pd.Timedelta(days=10)

    snap = build_historical_snapshot("TEST", "테스트", daily, snapshot_date)

    assert snap.effective_as_of is None
    assert snap.features.as_of is None
    assert snap.features.daily_rows == 0
    assert math.isnan(snap.features.close)


def test_future_data_does_not_change_past_snapshot():
    daily_a = _daily_frame(1200)
    daily_b = _daily_frame(1900)  # daily_a와 같은 산식이라 앞부분이 완전히 동일하다
    snapshot_date = daily_a.index[1000]

    snap_a = build_historical_snapshot("TEST", "테스트", daily_a, snapshot_date)
    snap_b = build_historical_snapshot("TEST", "테스트", daily_b, snapshot_date)

    assert snap_a.effective_as_of == snap_b.effective_as_of == snapshot_date
    _assert_features_equal(snap_a.features, snap_b.features)


def _mid_month_daily_frame() -> pd.DataFrame:
    # 2024-05-15(수)까지의 영업일 데이터. 5월은 진행 중인 달이고, 그 주(5/13~5/17)도
    # 수요일까지만 있어 진행 중인 주(금요일 label)다.
    index = pd.date_range("2020-01-01", "2024-05-15", freq="B")
    close = [100.0 + i * 0.1 for i in range(len(index))]
    return pd.DataFrame(
        {
            "open": close,
            "high": [c + 1 for c in close],
            "low": [c - 1 for c in close],
            "close": close,
            "volume": [1000.0] * len(index),
            "trading_value": [1.0e8] * len(index),
        },
        index=index,
    )


def test_completed_vs_live_monthly_around_mid_month_snapshot():
    daily = _mid_month_daily_frame()
    assert daily.index[-1] == pd.Timestamp("2024-05-15")
    snapshot_date = daily.index[-1]

    monthly_full = to_monthly(daily)

    snap_live = build_historical_snapshot(
        "TEST", "테스트", daily, snapshot_date, include_incomplete_periods=True
    )
    snap_completed = build_historical_snapshot(
        "TEST", "테스트", daily, snapshot_date, include_incomplete_periods=False
    )

    assert snap_live.features.monthly_rows == snap_completed.features.monthly_rows + 1
    assert snap_live.features.close == pytest.approx(monthly_full["close"].iloc[-1])
    assert snap_completed.features.close == pytest.approx(monthly_full["close"].iloc[-2])
    assert snap_completed.features.monthly_bar_may_be_incomplete is False


def test_completed_mode_drops_incomplete_weekly_bar():
    daily = _mid_month_daily_frame()
    snapshot_date = daily.index[-1]  # 2024-05-15(수), 그 주 금요일(5/17)은 아직 안 옴

    weekly_full = to_weekly(daily)

    snap_completed = build_historical_snapshot(
        "TEST", "테스트", daily, snapshot_date, include_incomplete_periods=False
    )

    assert snap_completed.weekly_as_of == weekly_full.index[-2]
    assert snap_completed.features.weekly_rows == len(weekly_full) - 1
    assert snap_completed.features.weekly_bar_may_be_incomplete is False


def test_live_mode_keeps_incomplete_weekly_bar():
    daily = _mid_month_daily_frame()
    snapshot_date = daily.index[-1]

    weekly_full = to_weekly(daily)

    snap_live = build_historical_snapshot(
        "TEST", "테스트", daily, snapshot_date, include_incomplete_periods=True
    )

    assert snap_live.weekly_as_of == weekly_full.index[-1]
    assert snap_live.features.weekly_rows == len(weekly_full)


def test_monthly_as_of_and_weekly_as_of_reflect_completed_trim():
    daily = _mid_month_daily_frame()
    snapshot_date = daily.index[-1]
    monthly_full = to_monthly(daily)
    weekly_full = to_weekly(daily)

    snap_completed = build_historical_snapshot(
        "TEST", "테스트", daily, snapshot_date, include_incomplete_periods=False
    )
    snap_live = build_historical_snapshot(
        "TEST", "테스트", daily, snapshot_date, include_incomplete_periods=True
    )

    assert snap_completed.monthly_as_of == monthly_full.index[-2]
    assert snap_completed.weekly_as_of == weekly_full.index[-2]
    assert snap_live.monthly_as_of == monthly_full.index[-1]
    assert snap_live.weekly_as_of == weekly_full.index[-1]


def test_monthly_as_of_and_weekly_as_of_none_when_no_data():
    daily = _daily_frame(40)
    snapshot_date = daily.index[0] - pd.Timedelta(days=10)

    snap = build_historical_snapshot("TEST", "테스트", daily, snapshot_date)

    assert snap.monthly_as_of is None
    assert snap.weekly_as_of is None


def test_monthly_field_matches_features_and_excludes_post_snapshot_data():
    """v0.2 설계 재리뷰 후속: HistoricalSnapshot.monthly는 FeatureRow 계산에
    쓰인 것과 같은(look-ahead 방지 적용된) 프레임이어야 한다."""
    daily = _daily_frame(1500)
    snapshot_date = daily.index[900]

    snap = build_historical_snapshot(
        "TEST", "테스트", daily, snapshot_date, include_incomplete_periods=False
    )

    assert snap.monthly.index.max() <= snapshot_date
    assert float(snap.monthly["close"].iloc[-1]) == pytest.approx(snap.features.close)


def test_to_csv_row_includes_snapshot_metadata_and_feature_fields():
    daily = _daily_frame(1200)
    snapshot_date = daily.index[900]
    snapshot = build_historical_snapshot(
        "068270", "셀트리온", daily, snapshot_date, include_incomplete_periods=False
    )

    row = to_csv_row("pre_breakout", snapshot)

    assert row["label"] == "pre_breakout"
    assert row["requested_snapshot_date"] == snapshot_date
    assert row["effective_as_of"] == snapshot.effective_as_of
    assert row["include_incomplete_periods"] is False
    assert row["monthly_as_of"] == snapshot.monthly_as_of
    assert row["weekly_as_of"] == snapshot.weekly_as_of
    assert row["ticker"] == "068270"
    assert row["close"] == pytest.approx(snapshot.features.close)
