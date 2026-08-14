import math

import pandas as pd
import pytest

from trend_scanner.validation.outcome_audit import compute_outcome, outcome_csv_row


def _rise_then_decline_frame() -> pd.DataFrame:
    """day0=100에서 day60까지 150으로 오른 뒤 day400까지 80 근처로 꾸준히 내려가는
    합성 daily. 400일이라 12개월(약 365일) 구간이 끝까지 채워진다."""
    n = 400
    index = pd.date_range("2020-01-01", periods=n, freq="D")
    close = []
    for i in range(n):
        if i <= 60:
            close.append(100 + i * (50 / 60))
        else:
            close.append(150 - (i - 60) * (70 / 340))
    return pd.DataFrame(
        {
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": [1000.0] * n,
            "trading_value": [1.0e8] * n,
        },
        index=index,
    )


def test_compute_outcome_max_and_end_returns_match_independent_slice():
    daily = _rise_then_decline_frame()
    base_date = daily.index[0]

    outcome = compute_outcome(daily, base_date)

    base_close = daily["close"].iloc[0]
    assert outcome.base_date == base_date
    assert outcome.base_close == base_close

    for months, expected_attr in [(3, "return_3m_max"), (6, "return_6m_max"), (12, "return_12m_max")]:
        window_end = base_date + pd.Timedelta(days=months * 30.4375)
        window_close = daily.loc[(daily.index > base_date) & (daily.index <= window_end), "close"]
        expected = (window_close.max() - base_close) / base_close
        assert getattr(outcome, expected_attr) == pytest.approx(expected)

    for months, expected_attr in [(6, "return_6m_end"), (12, "return_12m_end")]:
        window_end = base_date + pd.Timedelta(days=months * 30.4375)
        window_close = daily.loc[(daily.index > base_date) & (daily.index <= window_end), "close"]
        expected = (window_close.iloc[-1] - base_close) / base_close
        assert getattr(outcome, expected_attr) == pytest.approx(expected)

    # 피크(day60)가 12개월 window max이기도 하므로, 그 이후로는 running max가
    # 고정되고 마지막 날(day365 근방)이 최저 drawdown 지점이어야 한다.
    window_end_12m = base_date + pd.Timedelta(days=12 * 30.4375)
    window_close_12m = daily.loc[(daily.index > base_date) & (daily.index <= window_end_12m), "close"]
    running_max = window_close_12m.cummax()
    expected_drawdown = ((window_close_12m - running_max) / running_max).min()
    assert outcome.drawdown_12m_max == pytest.approx(expected_drawdown)
    assert outcome.drawdown_12m_max < 0  # 고점 대비 낙폭이니 음수여야 한다

    expected_months_to_peak = (daily.index[60] - base_date).days / 30.4375
    assert outcome.months_to_peak_12m == pytest.approx(expected_months_to_peak)


def test_compute_outcome_uses_nearest_prior_trading_day_for_base_date():
    daily = _rise_then_decline_frame()  # freq="D"라 모든 날짜가 다 있음. 인위적으로 구멍을 낸다.
    daily_with_gap = daily.drop(daily.index[10])  # index[10] 날짜를 빼서 비거래일처럼 만든다
    requested = daily.index[10]

    outcome = compute_outcome(daily_with_gap, requested)

    assert outcome.base_date == daily.index[9]  # 구멍 이전 마지막 거래일


def test_compute_outcome_before_any_data_returns_all_nan():
    daily = _rise_then_decline_frame()
    requested = daily.index[0] - pd.Timedelta(days=10)

    outcome = compute_outcome(daily, requested)

    assert outcome.base_date is None
    assert math.isnan(outcome.base_close)
    assert math.isnan(outcome.return_12m_max)
    assert math.isnan(outcome.drawdown_12m_max)


def test_compute_outcome_returns_nan_when_no_future_data_at_all():
    daily = _rise_then_decline_frame()
    base_date = daily.index[-1]  # 데이터의 마지막 날 -> 미래 데이터가 전혀 없음

    outcome = compute_outcome(daily, base_date)

    assert outcome.base_date == base_date
    assert not math.isnan(outcome.base_close)
    assert math.isnan(outcome.return_3m_max)
    assert math.isnan(outcome.return_12m_end)
    assert math.isnan(outcome.months_to_peak_12m)


def test_compute_outcome_partial_future_window_computed_from_available_data_only():
    # 데이터가 base_date 이후 60일치만 있으면(12개월치가 안 됨), 12개월 max return은
    # "있는 60일 중 최대"로 계산된다 — 실패시키지 않고 있는 만큼만 쓴다.
    daily = _rise_then_decline_frame()
    base_date = daily.index[0]
    truncated = daily.iloc[:61]  # base_date + 60일치만 남긴다(피크 day60 포함)

    outcome = compute_outcome(truncated, base_date)

    base_close = truncated["close"].iloc[0]
    expected_max = (truncated["close"].iloc[1:].max() - base_close) / base_close
    assert outcome.return_12m_max == pytest.approx(expected_max)
    # 12개월 end는 60일 시점 값이 된다(더 먼 미래 데이터가 없으므로)
    expected_end = (truncated["close"].iloc[-1] - base_close) / base_close
    assert outcome.return_12m_end == pytest.approx(expected_end)


def test_outcome_csv_row_shape():
    daily = _rise_then_decline_frame()
    outcome = compute_outcome(daily, daily.index[0])

    row = outcome_csv_row("TEST", "테스트", "failed_breakout", outcome)

    assert row["ticker"] == "TEST"
    assert row["name"] == "테스트"
    assert row["label"] == "failed_breakout"
    assert row["base_date"] == outcome.base_date
    assert row["return_12m_max"] == outcome.return_12m_max
    assert row["drawdown_12m_max"] == outcome.drawdown_12m_max
