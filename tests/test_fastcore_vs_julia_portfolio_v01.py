"""Focused local-only tests for the FastCore/Julia portfolio comparison."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from scripts import run_fastcore_vs_julia_portfolio_v01 as runner
from trend_scanner.backtest import fastcore_fundamentals_simple_v01 as engine


def _daily(start: str = "2020-12-01", end: str = "2021-04-30", price: float = 100.0) -> pd.DataFrame:
    dates = pd.bdate_range(start, end)
    frame = pd.DataFrame(
        {"open": price, "high": price, "low": price, "close": price, "volume": 1000.0, "trading_value": 1000.0},
        index=dates,
    )
    return frame


def test_mcap_boundary_and_liquidity_override():
    date = pd.Timestamp("2021-04-02")
    for market_cap, expected in ((99_999_999_999, False), (100_000_000_000, True)):
        panel = pd.DataFrame({"market_cap": [market_cap], "avg_trading_value_20d": [10_000_000.0], "close": [1.0]}, index=[date])
        result = runner.evaluate_mcap_only_entry_filter(panel, date)
        assert result["entry_filter_pass"] is expected
        assert result["liquidity_filter_applied"] is False
        assert result["price_filter_applied"] is False


def test_unavailable_liquidity_does_not_reject_mcap_pass():
    date = pd.Timestamp("2021-04-02")
    panel = pd.DataFrame({"market_cap": [100_000_000_000], "avg_trading_value_20d": [float("nan")], "close": [float("nan")]}, index=[date])
    result = runner.evaluate_mcap_only_entry_filter(panel, date)
    assert result["entry_filter_pass"] is True
    assert result["entry_trading_value_pass"] is True
    assert result["entry_close_pass"] is True


def test_fastcore_guard_on_and_julia_guard_off(monkeypatch):
    daily = _daily()
    signal_date = pd.Timestamp("2021-02-26")
    entry_date = pd.Timestamp("2021-03-01")
    daily.loc[daily.index >= entry_date, "close"] = 80.0
    daily.loc[daily.index >= entry_date, "low"] = 80.0
    panel = pd.DataFrame({"market_cap": [100_000_000_000]}, index=[signal_date])
    lifecycle = engine.IdentityLifecycle("000001", "KR7000000001", "KOSPI", daily.index.min(), daily.index.max())

    def fake_fast(*_args, **_kwargs):
        return {
            "fast_machine_stage": "TRIGGER",
            "fast_machine_stage_status": "READY",
            "fast_monthly_permission_state": "PERMITTED_REGIME",
            "fast_daily_risk_state": "NORMAL",
            "fast_score_status": "READY",
            "fast_score": 80.0,
            "pattern_a_stage": "TRANSITION",
        }

    class _Stage:
        value = "TRANSITION"

    monkeypatch.setattr(engine, "evaluate_pattern_a_fast", fake_fast)
    monkeypatch.setattr(engine, "evaluate_pattern_a", lambda _snapshot: SimpleNamespace(stage=_Stage(), score=1.0))
    with runner.comparison_filter_override():
        kwargs = dict(
            ticker="000001", isu_cd="KR7000000001", name="Example", market="KOSPI", daily=daily,
            raw_panel=panel, score_contract={}, stage_contract={}, backtest_end=pd.Timestamp("2021-04-30"),
            entry_eligible_from=pd.Timestamp("2021-01-01"), allowed_signal_dates={signal_date},
            identity_lifecycle=lifecycle,
        )
        fast = engine.simulate_ticker_strategy_fundamentals_v01(strategy_id=runner.FASTCORE_ID, loss_guard_enabled=True, **kwargs)
        julia = engine.simulate_ticker_strategy_fundamentals_v01(strategy_id=runner.JULIA_ID, loss_guard_enabled=False, **kwargs)
    assert len(fast) == len(julia) == 1
    assert fast[0].exit_type == "LOSS_GUARD_CLOSE_LE_NEG_15"
    assert julia[0].exit_type != "LOSS_GUARD_CLOSE_LE_NEG_15"


def test_cash_block_no_carry_and_same_open_proceeds_reuse(monkeypatch):
    monkeypatch.setattr(runner, "INITIAL_CAPITAL", 100.0)
    monkeypatch.setattr(runner, "POSITION_CAP", 100.0)
    dates = pd.bdate_range("2021-04-01", "2021-04-23")
    daily = {ticker: pd.DataFrame({"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0}, index=dates) for ticker in ("000001", "000002", "000003")}
    rows = []
    def add(ticker: str, date: str, score: float):
        rows.append({"signal_id": f"{ticker}|I|KOSPI|{date}", "ticker": ticker, "isu_cd": "I", "market": "KOSPI", "name": ticker, "signal_date": date, "fast_score": score})
    add("000001", "2021-04-02", 90.0)  # executed on 04-05; exits on 04-12
    add("000002", "2021-04-02", 80.0)  # cash blocked; must not carry
    add("000001", "2021-04-09", 95.0)  # same-open re-entry on 04-12; must skip
    add("000003", "2021-04-09", 70.0)  # uses 000001 sale proceeds on 04-12
    add("000002", "2021-04-16", 60.0)  # genuinely new signal; executes after 000003 exits
    signals = pd.DataFrame(rows)
    calendar = runner._build_calendar(daily)
    exits = {"000001": "2021-04-07", "000003": "2021-04-14"}
    def factory(_strategy: str, candidate):
        return {"exit_signal_date": exits.get(candidate["ticker"]), "exit_type": "TEST_EXIT"}
    result = runner.run_portfolio(signals, calendar, daily, runner.FASTCORE_ID, factory)
    audit = result["entry_audit"]
    assert audit.loc[(audit.ticker == "000002") & (audit.signal_date == "2021-04-02"), "execution_result"].iloc[0] == "SKIP_CASH_BLOCKED"
    assert audit.loc[(audit.ticker == "000002") & (audit.signal_date == "2021-04-16"), "execution_result"].iloc[0] == "EXECUTED"
    assert audit.loc[(audit.ticker == "000001") & (audit.signal_date == "2021-04-09"), "execution_result"].iloc[0] == "SKIP_SAME_OPEN_REENTRY"
    assert audit.loc[(audit.ticker == "000003") & (audit.signal_date == "2021-04-09"), "execution_result"].iloc[0] == "EXECUTED"
