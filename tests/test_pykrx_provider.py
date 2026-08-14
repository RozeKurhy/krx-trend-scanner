import pandas as pd
import pytest

from trend_scanner.data import pykrx_provider as pykrx_provider_module
from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.pykrx_provider import PyKrxDataProvider
from trend_scanner.data.validator import validate_ohlcv


def _adjusted_korean_df() -> pd.DataFrame:
    # adjusted=True 경로(Naver)는 거래대금 컬럼이 없다.
    index = pd.date_range("2024-01-02", periods=2, freq="D")
    return pd.DataFrame(
        {
            "시가": [100, 101],
            "고가": [105, 106],
            "저가": [95, 96],
            "종가": [102, 103],
            "거래량": [1000, 1100],
            "등락률": [0.0, 0.98],
        },
        index=index,
    )


def _unadjusted_korean_df() -> pd.DataFrame:
    # adjusted=False 경로(KRX)는 거래대금 컬럼을 포함한다.
    index = pd.date_range("2024-01-02", periods=2, freq="D")
    return pd.DataFrame(
        {
            "시가": [99, 100],
            "고가": [104, 105],
            "저가": [94, 95],
            "종가": [101, 102],
            "거래량": [999, 1099],
            "거래대금": [123_456_789, 234_567_890],
            "등락률": [0.0, 0.99],
        },
        index=index,
    )


def test_load_daily_merges_adjusted_price_with_unadjusted_trading_value(monkeypatch):
    calls = []

    def fake_get_market_ohlcv_by_date(fromdate, todate, ticker, adjusted=True):
        calls.append(adjusted)
        return _adjusted_korean_df() if adjusted else _unadjusted_korean_df()

    monkeypatch.setattr(
        pykrx_provider_module.stock, "get_market_ohlcv_by_date", fake_get_market_ohlcv_by_date
    )

    provider = PyKrxDataProvider(adjusted=True)
    result = provider.load_daily("005930", "2024-01-02", "2024-01-03")

    assert calls == [True, False]
    assert list(result.columns) == ["open", "high", "low", "close", "volume", "trading_value"]
    assert isinstance(result.index, pd.DatetimeIndex)
    assert result.index.is_monotonic_increasing

    # OHLC/volume은 adjusted(Naver) 경로에서, trading_value는 unadjusted(KRX) 경로에서 온다.
    assert result["open"].tolist() == [100.0, 101.0]
    assert result["volume"].tolist() == [1000, 1100]
    assert result["trading_value"].tolist() == [123_456_789.0, 234_567_890.0]

    assert result["open"].dtype == "float64"
    assert result["volume"].dtype == "int64"
    assert result["trading_value"].dtype == "float64"


def test_unadjusted_mode_calls_pykrx_only_once(monkeypatch):
    calls = []

    def fake_get_market_ohlcv_by_date(fromdate, todate, ticker, adjusted=True):
        calls.append(adjusted)
        return _unadjusted_korean_df()

    monkeypatch.setattr(
        pykrx_provider_module.stock, "get_market_ohlcv_by_date", fake_get_market_ohlcv_by_date
    )

    provider = PyKrxDataProvider(adjusted=False)
    result = provider.load_daily("005930", "2024-01-02", "2024-01-03")

    assert calls == [False]
    assert result["trading_value"].tolist() == [123_456_789.0, 234_567_890.0]


def test_load_daily_wraps_underlying_exception():
    def raising_get_market_ohlcv_by_date(*args, **kwargs):
        raise RuntimeError("network down")

    provider = PyKrxDataProvider(adjusted=True)
    original = pykrx_provider_module.stock.get_market_ohlcv_by_date
    pykrx_provider_module.stock.get_market_ohlcv_by_date = raising_get_market_ohlcv_by_date
    try:
        with pytest.raises(MarketDataError):
            provider.load_daily("005930", "2024-01-02", "2024-01-03")
    finally:
        pykrx_provider_module.stock.get_market_ohlcv_by_date = original


def test_load_daily_empty_response_returns_empty_standard_frame(monkeypatch):
    def fake_get_market_ohlcv_by_date(fromdate, todate, ticker, adjusted=True):
        return pd.DataFrame()

    monkeypatch.setattr(
        pykrx_provider_module.stock, "get_market_ohlcv_by_date", fake_get_market_ohlcv_by_date
    )

    provider = PyKrxDataProvider(adjusted=True)
    result = provider.load_daily("005930", "2024-01-02", "2024-01-03")

    assert result.empty
    assert list(result.columns) == ["open", "high", "low", "close", "volume", "trading_value"]
    assert isinstance(result.index, pd.DatetimeIndex)


def test_missing_source_column_raises_market_data_error(monkeypatch):
    def fake_get_market_ohlcv_by_date(fromdate, todate, ticker, adjusted=True):
        broken = _adjusted_korean_df().drop(columns=["거래량"])
        return broken if adjusted else _unadjusted_korean_df()

    monkeypatch.setattr(
        pykrx_provider_module.stock, "get_market_ohlcv_by_date", fake_get_market_ohlcv_by_date
    )

    provider = PyKrxDataProvider(adjusted=True)
    with pytest.raises(MarketDataError):
        provider.load_daily("005930", "2024-01-02", "2024-01-03")


def test_phantom_holiday_rows_are_filtered_out(monkeypatch):
    # 가운데 날짜(2024-01-03)는 open=high=low=volume=0, close만 직전 거래일 값을
    # 들고 있는 휴장일 phantom row. 실측(NAVER 2018-10-08/10/11, 삼성전자
    # 2018-04-30~05-03)과 동일한 형태를 재현한다.
    index = pd.date_range("2024-01-02", periods=3, freq="D")
    adjusted_df = pd.DataFrame(
        {
            "시가": [100, 0, 102],
            "고가": [105, 0, 107],
            "저가": [95, 0, 97],
            "종가": [102, 102, 104],
            "거래량": [1000, 0, 1200],
            "등락률": [0.0, 0.0, 1.96],
        },
        index=index,
    )
    unadjusted_df = pd.DataFrame(
        {
            "시가": [99, 0, 101],
            "고가": [104, 0, 106],
            "저가": [94, 0, 96],
            "종가": [101, 101, 103],
            "거래량": [999, 0, 1199],
            "거래대금": [100_000_000, 0, 120_000_000],
            "등락률": [0.0, 0.0, 1.98],
        },
        index=index,
    )

    def fake_get_market_ohlcv_by_date(fromdate, todate, ticker, adjusted=True):
        return adjusted_df if adjusted else unadjusted_df

    monkeypatch.setattr(
        pykrx_provider_module.stock, "get_market_ohlcv_by_date", fake_get_market_ohlcv_by_date
    )

    provider = PyKrxDataProvider(adjusted=True)
    result = provider.load_daily("005930", "2024-01-02", "2024-01-04")

    assert len(result) == 2
    assert list(result.index) == [index[0], index[2]]


def test_row_with_only_partial_zero_columns_is_not_filtered(monkeypatch):
    # open만 0이고 high/low/volume은 0이 아니므로 phantom row 조건을 만족하지
    # 않는다 — 필터링되면 안 된다.
    index = pd.date_range("2024-01-02", periods=1, freq="D")
    adjusted_df = pd.DataFrame(
        {"시가": [0], "고가": [105], "저가": [95], "종가": [102], "거래량": [1000], "등락률": [0.0]},
        index=index,
    )
    unadjusted_df = pd.DataFrame(
        {
            "시가": [0],
            "고가": [104],
            "저가": [94],
            "종가": [101],
            "거래량": [999],
            "거래대금": [123_456_789],
            "등락률": [0.0],
        },
        index=index,
    )

    def fake_get_market_ohlcv_by_date(fromdate, todate, ticker, adjusted=True):
        return adjusted_df if adjusted else unadjusted_df

    monkeypatch.setattr(
        pykrx_provider_module.stock, "get_market_ohlcv_by_date", fake_get_market_ohlcv_by_date
    )

    provider = PyKrxDataProvider(adjusted=True)
    result = provider.load_daily("005930", "2024-01-02", "2024-01-02")

    assert len(result) == 1


def _single_row_frames(*, high_correction=0, low_correction=0, with_trading_value=True):
    """open=100, close=105 기준, high/low를 정상값에서 얼마나 벗어나게 할지로 조립한다."""
    index = pd.date_range("2024-01-02", periods=1, freq="D")
    normal_high, normal_low = 105, 100
    high = normal_high - high_correction if high_correction else 106
    low = normal_low + low_correction if low_correction else 99

    adjusted_df = pd.DataFrame(
        {"시가": [100], "고가": [high], "저가": [low], "종가": [105], "거래량": [1000], "등락률": [0.0]},
        index=index,
    )
    unadjusted_row = {
        "시가": [99],
        "고가": [high - 1] if high_correction else [105],
        "저가": [low - 1] if low_correction else [94],
        "종가": [104],
        "거래량": [999],
        "등락률": [0.0],
    }
    if with_trading_value:
        unadjusted_row["거래대금"] = [123_456_789]
    unadjusted_df = pd.DataFrame(unadjusted_row, index=index)
    return adjusted_df, unadjusted_df


def test_high_one_won_below_close_is_corrected(monkeypatch):
    # open=100, close=105, high=104 (close보다 1원 낮음) -> high가 105로 보정돼야 한다.
    adjusted_df, unadjusted_df = _single_row_frames(high_correction=1)

    def fake_get_market_ohlcv_by_date(fromdate, todate, ticker, adjusted=True):
        return adjusted_df if adjusted else unadjusted_df

    monkeypatch.setattr(
        pykrx_provider_module.stock, "get_market_ohlcv_by_date", fake_get_market_ohlcv_by_date
    )

    provider = PyKrxDataProvider(adjusted=True)
    result = provider.load_daily("005930", "2024-01-02", "2024-01-02")

    assert result["high"].iloc[0] == 105.0
    validate_ohlcv(result)  # 보정 후에는 관계 위반이 없어야 한다.


def test_low_one_won_above_open_is_corrected(monkeypatch):
    # open=100, close=105, low=101 (open보다 1원 높음) -> low가 100으로 보정돼야 한다.
    adjusted_df, unadjusted_df = _single_row_frames(low_correction=1)

    def fake_get_market_ohlcv_by_date(fromdate, todate, ticker, adjusted=True):
        return adjusted_df if adjusted else unadjusted_df

    monkeypatch.setattr(
        pykrx_provider_module.stock, "get_market_ohlcv_by_date", fake_get_market_ohlcv_by_date
    )

    provider = PyKrxDataProvider(adjusted=True)
    result = provider.load_daily("005930", "2024-01-02", "2024-01-02")

    assert result["low"].iloc[0] == 100.0
    validate_ohlcv(result)  # 보정 후에는 관계 위반이 없어야 한다.


def test_two_won_violation_is_not_corrected_and_validator_rejects(monkeypatch):
    # open=100, close=105, high=103 (close보다 2원 낮음) -> 보정하지 않고 그대로 둔다.
    adjusted_df, unadjusted_df = _single_row_frames(high_correction=2)

    def fake_get_market_ohlcv_by_date(fromdate, todate, ticker, adjusted=True):
        return adjusted_df if adjusted else unadjusted_df

    monkeypatch.setattr(
        pykrx_provider_module.stock, "get_market_ohlcv_by_date", fake_get_market_ohlcv_by_date
    )

    provider = PyKrxDataProvider(adjusted=True)
    result = provider.load_daily("005930", "2024-01-02", "2024-01-02")

    assert result["high"].iloc[0] == 103.0  # 보정되지 않음
    with pytest.raises(MarketDataError):
        validate_ohlcv(result)


def test_adjusted_false_one_won_violation_is_not_corrected(monkeypatch):
    # adjusted=False(원본) 경로는 1원 위반이라도 절대 보정하지 않는다.
    index = pd.date_range("2024-01-02", periods=1, freq="D")
    unadjusted_df = pd.DataFrame(
        {
            "시가": [100],
            "고가": [104],  # close(105)보다 1원 낮음
            "저가": [99],
            "종가": [105],
            "거래량": [999],
            "거래대금": [123_456_789],
            "등락률": [0.0],
        },
        index=index,
    )

    def fake_get_market_ohlcv_by_date(fromdate, todate, ticker, adjusted=True):
        return unadjusted_df

    monkeypatch.setattr(
        pykrx_provider_module.stock, "get_market_ohlcv_by_date", fake_get_market_ohlcv_by_date
    )

    provider = PyKrxDataProvider(adjusted=False)
    result = provider.load_daily("005930", "2024-01-02", "2024-01-02")

    assert result["high"].iloc[0] == 104.0  # 보정되지 않음
    with pytest.raises(MarketDataError):
        validate_ohlcv(result)


@pytest.mark.parametrize(
    "column,bad_value",
    [
        ("시가", "abc"),  # 문자열 -> float64 변환 실패
        ("거래량", float("nan")),  # NaN -> int64 변환 실패
    ],
)
def test_dtype_conversion_failure_raises_market_data_error(monkeypatch, column, bad_value):
    def fake_get_market_ohlcv_by_date(fromdate, todate, ticker, adjusted=True):
        if not adjusted:
            return _unadjusted_korean_df()
        broken = _adjusted_korean_df()
        broken.loc[broken.index[0], column] = bad_value
        return broken

    monkeypatch.setattr(
        pykrx_provider_module.stock, "get_market_ohlcv_by_date", fake_get_market_ohlcv_by_date
    )

    provider = PyKrxDataProvider(adjusted=True)
    with pytest.raises(MarketDataError):
        provider.load_daily("005930", "2024-01-02", "2024-01-03")
