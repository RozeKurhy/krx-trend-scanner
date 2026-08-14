import pandas as pd

from trend_scanner.features.downtrend_structure import (
    long_term_high_slope_36m,
    prior_leg_drift_36m,
)


def _monthly(closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2020-01-31", periods=len(closes), freq="ME")
    close = pd.Series(closes, index=idx)
    return pd.DataFrame({"close": close, "high": close + 2, "low": close - 2})


def test_falling_highs_gives_negative_slope():
    closes = [100 - i * 1.4 for i in range(36)]
    monthly = _monthly(closes)
    assert long_term_high_slope_36m(monthly) < -0.2
    assert prior_leg_drift_36m(monthly) < 0


def test_flat_base_gives_zero():
    monthly = _monthly([50.0] * 36)
    assert long_term_high_slope_36m(monthly) == 0.0
    assert prior_leg_drift_36m(monthly) == 0.0


def test_rising_base_gives_positive_slope():
    closes = [50 + i * 1.4 for i in range(36)]
    monthly = _monthly(closes)
    assert long_term_high_slope_36m(monthly) > 0.2
    assert prior_leg_drift_36m(monthly) > 0


def test_insufficient_history_is_nan():
    monthly = _monthly([100.0] * 35)
    assert pd.isna(long_term_high_slope_36m(monthly))
    assert pd.isna(prior_leg_drift_36m(monthly))


def test_missing_high_column_is_nan_safe():
    monthly = _monthly([100.0] * 36).drop(columns=["high"])
    assert pd.isna(long_term_high_slope_36m(monthly))


def test_only_uses_trailing_36_months():
    """36개월보다 더 오래된 데이터가 앞에 붙어도 결과가 바뀌지 않아야
    한다 — range_36m/avg_price_change_12m와 같은 관례로 tail(36) 밖
    데이터는 보지 않는다(look-ahead 방지 자체는 HistoricalSnapshot이
    보장하는 별개의 계층이다 — 이 테스트는 창 크기만 확인한다)."""
    closes = [100 - i * 1.4 for i in range(36)]
    monthly = _monthly(closes)
    extended = pd.concat([_monthly([10_000.0] * 5), monthly])
    assert long_term_high_slope_36m(extended) == long_term_high_slope_36m(monthly)
    assert prior_leg_drift_36m(extended) == prior_leg_drift_36m(monthly)
