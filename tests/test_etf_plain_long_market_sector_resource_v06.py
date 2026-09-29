from __future__ import annotations

import pandas as pd
import pytest

from scripts import run_etf_plain_long_market_sector_resource_v06 as v06
from scripts import run_etf_current_survivors_raw_price_three_strategy_simple_backtest_v03 as v03


def _daily_frame(rows: list[dict[str, float]], dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame(rows, index=pd.to_datetime(dates))


def _valid_row(price: float = 1000.0) -> dict[str, float]:
    return {
        "open": price,
        "high": price + 10,
        "low": price - 10,
        "close": price,
        "volume": 10000,
        "trading_value": price * 10000,
    }


def _no_trade_row() -> dict[str, float]:
    return {
        "open": 0,
        "high": 0,
        "low": 0,
        "close": 1000,
        "volume": 0,
        "trading_value": 0,
    }


def test_strict_no_trade_detection_uses_all_five_exact_conditions() -> None:
    rows = [
        _no_trade_row(),
        {**_no_trade_row(), "volume": 1},
        {**_no_trade_row(), "low": 1},
        {**_no_trade_row(), "close": 0},
    ]
    frame = _daily_frame(rows, ["2026-08-25", "2026-08-26", "2026-08-27", "2026-08-28"])

    assert v06.strict_no_trade_mask(frame).tolist() == [True, False, False, False]


def test_strict_no_trade_row_is_removed_from_technical_ohlc_only() -> None:
    frame = _daily_frame(
        [_valid_row(), _no_trade_row(), _valid_row(1010)],
        ["2026-08-25", "2026-08-26", "2026-08-27"],
    )
    technical, removed = v06.split_technical_daily(frame)

    assert technical.index.strftime("%Y-%m-%d").tolist() == ["2026-08-25", "2026-08-27"]
    assert removed.index.strftime("%Y-%m-%d").tolist() == ["2026-08-26"]
    assert frame.loc[pd.Timestamp("2026-08-26"), "volume"] == 0
    assert frame.loc[pd.Timestamp("2026-08-26"), "close"] == 1000


def test_zero_volume_remains_in_raw_twenty_session_eligibility_window(monkeypatch: pytest.MonkeyPatch) -> None:
    dates = pd.bdate_range("2026-08-04", "2026-08-31")
    rows = [_valid_row() for _ in dates]
    rows[0] = _no_trade_row()
    raw = pd.DataFrame(rows, index=dates)
    technical, removed = v06.split_technical_daily(raw)
    monkeypatch.setattr(v03, "_WORKER", {
        "calendar_dates": [d.strftime("%Y-%m-%d") for d in dates],
    })

    eligible, metrics, volume_ready, _audit = v03._raw_eligibility(
        raw, "2020-01-01", "2026-08-04"
    )

    last_day = dates[-1].strftime("%Y-%m-%d")
    assert len(removed) == 1
    assert dates[0] not in technical.index
    assert volume_ready == last_day
    assert metrics[last_day]["avg_volume_20d"] == 9500
    assert last_day not in eligible


def test_technical_filter_adds_no_synthetic_price_rows() -> None:
    frame = _daily_frame(
        [_valid_row(1000), _no_trade_row(), _valid_row(1020)],
        ["2026-08-25", "2026-08-26", "2026-08-27"],
    )
    technical, removed = v06.split_technical_daily(frame)

    assert len(technical) + len(removed) == len(frame)
    assert set(technical.index).issubset(set(frame.index))
    pd.testing.assert_frame_equal(frame.loc[technical.index], technical)
    assert len(technical.loc[~technical.index.isin(frame.index)]) == 0


def test_269530_is_the_first_permanent_universe_exclusion() -> None:
    frame, universe, audit = v06._load_universe()
    tickers = {item["ticker"] for item in universe}

    assert "269530" not in tickers
    assert audit["permanent_exclusion_tickers"] == ["265690", "269530"]
    assert len(frame) == 427


def test_265690_is_the_second_permanent_universe_exclusion() -> None:
    _frame, universe, audit = v06._load_universe()
    tickers = {item["ticker"] for item in universe}

    assert "265690" not in tickers
    assert audit["permanent_exclusion_tickers"] == ["265690", "269530"]
    assert audit["unauthorized_exclusion_count"] == 0


def test_non_signature_invalid_ohlc_fails_closed() -> None:
    invalid = {**_valid_row(), "open": 1200, "high": 1100}
    frame = _daily_frame([invalid], ["2026-08-28"])

    with pytest.raises(RuntimeError, match="OTHER_INVALID_OHLC_FAIL_CLOSED"):
        v06.split_technical_daily(frame)


def test_common_period_is_exact_maximum_of_all_five_readiness_dates() -> None:
    assert v06.common_period_start(
        "2022-01-01", "2023-07-01", "2024-02-15", "2023-06-20", "2024-02-16"
    ) == "2024-02-16"
    assert v06.common_period_start("2022-01-01", None, "2024-02-15", "2023-06-20", "2024-02-16") is None


def test_post_cutoff_entry_detection_rejects_new_entries_after_cutoff() -> None:
    trades = [
        {"signal_date": "2026-08-30", "entry_execution_date": "2026-08-31"},
        {"signal_date": "2026-08-31", "entry_execution_date": "2026-09-01"},
    ]

    assert v06.post_cutoff_entry_count(trades, cutoff="2026-08-31") == 1
