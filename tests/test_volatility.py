import pandas as pd
import pytest

from trend_scanner.features.volatility import atr, atr_pct, true_range


def _flat_range_frame() -> pd.DataFrame:
    # 매일 high-low가 정확히 2, close는 100으로 고정된 데이터
    return pd.DataFrame(
        {
            "high": [101.0] * 20,
            "low": [99.0] * 20,
            "close": [100.0] * 20,
        }
    )


def test_true_range_uses_high_low_when_no_gap():
    tr = true_range(_flat_range_frame())
    assert (tr.dropna() == 2.0).all()


def test_atr_converges_to_constant_true_range():
    df = _flat_range_frame()
    result = atr(df, period=5)
    assert result.iloc[-1] == pytest.approx(2.0)


def test_atr_pct_normalizes_by_close():
    df = _flat_range_frame()
    result = atr_pct(df, period=5)
    assert result.iloc[-1] == pytest.approx(0.02)
