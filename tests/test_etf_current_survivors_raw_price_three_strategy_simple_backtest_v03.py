from __future__ import annotations

import math

import pandas as pd

from scripts import run_etf_current_survivors_raw_price_three_strategy_simple_backtest_v03 as runner


def test_etf_eligibility_uses_exact_trailing_twenty_sessions_and_never_future_data():
    sessions = list(pd.bdate_range(end=runner.CUTOFF, periods=20))
    future = pd.Timestamp("2026-09-01")
    runner._WORKER["calendar_dates"] = [
        *(date.strftime("%Y-%m-%d") for date in sessions),
        future.strftime("%Y-%m-%d"),
    ]
    index = pd.DatetimeIndex([*sessions, future])
    daily = pd.DataFrame(
        {
            "open": 1000,
            "high": 1000,
            "low": 1000,
            "close": 1000,
            "volume": [10000] * 19 + [0, 1_000_000],
            "trading_value": 1_000_000,
        },
        index=index,
    )

    eligible, _, volume_ready, _ = runner._raw_eligibility(
        daily, "2024-08-31", "2026-08-31"
    )
    assert volume_ready == "2026-08-31"
    assert "2026-08-31" not in eligible

    daily.loc[runner.CUTOFF, "volume"] = 10000
    eligible, metrics, _, _ = runner._raw_eligibility(
        daily, "2024-08-31", "2026-08-31"
    )
    assert eligible == {"2026-08-31"}
    assert metrics["2026-08-31"] == {"close": 1000.0, "avg_volume_20d": 10000.0}


def test_trade_return_uses_next_exact_session_and_etf_fee_contract():
    calendar = ["2026-08-28", "2026-08-31", "2026-09-01"]
    runner._WORKER["calendar_dates"] = calendar
    runner._WORKER["calendar_positions"] = {date: index for index, date in enumerate(calendar)}
    daily = pd.DataFrame(
        {
            "open": [90.0, 100.0, 110.0],
            "high": [91.0, 101.0, 111.0],
            "low": [89.0, 99.0, 109.0],
            "close": [90.0, 100.0, 110.0],
            "volume": [10000, 10000, 10000],
            "trading_value": [900000, 1000000, 1100000],
        },
        index=pd.to_datetime(calendar),
    )
    trade = runner._trade_row(
        strategy_id=runner.STRATEGY_SELECT,
        ticker="123456",
        name="샘플 ETF",
        isu_cd="KR7123456000",
        signal_date="2026-08-28",
        entry_execution_date="2026-08-31",
        entry_price=100.0,
        exit_signal_date="2026-08-31",
        exit_execution_date="2026-09-01",
        exit_price=110.0,
        terminal_date="2026-09-01",
        terminal_price=110.0,
        exit_reason="PATTERN_B_NORMAL",
        trade_status="REALIZED",
        daily=daily,
        common_start="2026-01-01",
    )

    expected_cost_return = (
        110.0 * (1 - runner.SLIPPAGE_RATE) * (1 - runner.COMMISSION_RATE)
        / (100.0 * (1 + runner.SLIPPAGE_RATE) * (1 + runner.COMMISSION_RATE))
        - 1
    ) * 100
    assert math.isclose(trade["gross_return_pct"], 10.0)
    assert math.isclose(
        trade["commission_slippage_pre_tax_return_pct"], expected_cost_return
    )
    assert trade["ETF_sell_tax_rate"] == 0.0
    assert trade["holding_krx_sessions_inclusive"] == 2
