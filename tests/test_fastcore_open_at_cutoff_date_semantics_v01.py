"""Targeted regression tests for OPEN_AT_CUTOFF valuation-date semantics."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from trend_scanner.backtest import fastcore_fundamentals_simple_v01 as engine


def _daily(dates: list[str], closes: list[float]) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "open": [100.0] * len(dates),
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1_000.0] * len(dates),
            "trading_value": [1_000_000.0] * len(dates),
        },
        index=pd.DatetimeIndex(dates),
    )
    return frame


def test_case_a_open_cutoff_uses_exact_effective_cutoff_row() -> None:
    outcome = engine._calc_trade_outcome(
        pd.Timestamp("2024-01-02"),
        100.0,
        None,
        _daily(["2024-01-02", "2024-01-03"], [100.0, 120.0]),
        pd.Timestamp("2024-01-03"),
    )

    assert outcome["cutoff_valuation_date"] == pd.Timestamp("2024-01-03")
    assert outcome["cutoff_close"] == 120.0


def test_case_b_open_cutoff_uses_last_actual_row_before_nontrading_cutoff() -> None:
    lifecycle = engine.IdentityLifecycle(
        "TEST", "KRTEST", "KOSPI", pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-04")
    )
    outcome = engine._calc_trade_outcome(
        pd.Timestamp("2024-01-02"),
        100.0,
        None,
        _daily(["2024-01-02", "2024-01-03"], [100.0, 120.0]),
        lifecycle.effective_to,
    )

    assert lifecycle.effective_to == pd.Timestamp("2024-01-04")
    assert outcome["cutoff_valuation_date"] == pd.Timestamp("2024-01-03")
    assert outcome["cutoff_close"] == 120.0


@pytest.mark.parametrize(
    ("ticker", "effective_to", "last_daily"),
    [
        ("003410", "2024-01-04", "2024-01-03"),
        ("049770", "2024-02-16", "2024-02-15"),
        ("029960", "2025-06-13", "2025-05-27"),
    ],
)
def test_case_d_known_class_shape_has_no_cutoff_date_price_mismatch(
    ticker: str, effective_to: str, last_daily: str
) -> None:
    lifecycle = engine.IdentityLifecycle(
        ticker, f"KR{ticker}", "KOSDAQ", pd.Timestamp(last_daily) - pd.Timedelta("10D"), pd.Timestamp(effective_to)
    )
    outcome = engine._calc_trade_outcome(
        pd.Timestamp(last_daily) - pd.Timedelta("1D"),
        100.0,
        None,
        _daily([str(lifecycle.effective_from.date()), last_daily], [100.0, 90.0]),
        lifecycle.effective_to,
    )

    assert outcome["cutoff_valuation_date"] == pd.Timestamp(last_daily)
    assert outcome["cutoff_close"] == 90.0


def test_record_uses_valuation_row_date_and_preserves_identity_effective_to(monkeypatch) -> None:
    dates = pd.bdate_range("2021-01-04", "2021-04-29")
    daily = _daily([value.strftime("%Y-%m-%d") for value in dates], [120.0] * len(dates))
    raw_panel = pd.DataFrame(
        {
            "market_cap": [400_000_000_000.0] * len(dates),
            "avg_trading_value_20d": [500_000_000.0] * len(dates),
            "close": [120.0] * len(dates),
        },
        index=dates,
    )
    lifecycle = engine.IdentityLifecycle(
        "000001", "KR7000000001", "KOSPI", dates.min(), pd.Timestamp("2021-04-30")
    )

    monkeypatch.setattr(
        engine,
        "evaluate_pattern_a_fast",
        lambda *_args, **_kwargs: {
            "fast_machine_stage": "TRIGGER",
            "fast_machine_stage_status": "READY",
            "fast_monthly_permission_state": "PERMITTED_REGIME",
            "fast_daily_risk_state": "NORMAL",
            "fast_score_status": "READY",
            "fast_score": 80.0,
            "pattern_a_stage": "TRANSITION",
        },
    )
    monkeypatch.setattr(
        engine,
        "evaluate_entry_filter",
        lambda *_args, **_kwargs: {
            "entry_filter_pass": True,
            "entry_market_cap": 400_000_000_000.0,
            "entry_avg_trading_value_20d": 500_000_000.0,
            "entry_signal_close": 120.0,
            "entry_market_cap_pass": True,
            "entry_trading_value_pass": True,
            "entry_close_pass": True,
            "entry_filter_raw_date": "2021-01-29",
        },
    )

    records = engine.simulate_ticker_strategy_fundamentals_v01(
        strategy_id="TEST_RECORD_WIRING",
        ticker="000001",
        isu_cd="KR7000000001",
        name="Example",
        market="KOSPI",
        daily=daily,
        raw_panel=raw_panel,
        score_contract={},
        stage_contract={},
        loss_guard_enabled=False,
        backtest_end=pd.Timestamp("2021-04-30"),
        entry_eligible_from=pd.Timestamp("2021-01-01"),
        allowed_signal_dates={pd.Timestamp("2021-01-29")},
        identity_lifecycle=lifecycle,
    )

    assert len(records) == 1
    assert records[0].trade_status == "OPEN_AT_CUTOFF"
    assert records[0].cutoff_date == "2021-04-29"
    assert records[0].cutoff_valuation_price == 120.0
    assert records[0].identity_effective_to == "2021-04-30"


def test_case_c_portfolio_accepts_same_row_terminal_valuation_without_synthetic_sale() -> None:
    from scripts import run_v2_julia_official_validation_v01 as runner

    record = SimpleNamespace(
        strategy_id=runner.BASE_STRATEGY_ID,
        ticker="000001",
        isu_cd="KR7000000001",
        name="000001",
        market="KOSPI",
        trade_id="trade-000001",
        trade_sequence=1,
        entry_signal_date="2021-01-01",
        entry_execution_date="2021-01-03",
        entry_open=100.0,
        entry_market_cap=200_000_000_000.0,
        entry_avg_trading_value_20d=400_000_000.0,
        exit_signal_date=None,
        exit_execution_date=None,
        exit_type="NO_EXIT_BEFORE_CUTOFF",
        exit_price=None,
        terminal_return=20.0,
        mae=-1.0,
        mfe=25.0,
        holding_trading_days=2,
        holding_weeks=0.4,
        trade_status="OPEN_AT_CUTOFF",
        cutoff_date="2021-01-04",
        cutoff_valuation_price=120.0,
        mark_to_cutoff_return=20.0,
        identity_effective_from="2021-01-01",
        identity_effective_to="2021-01-05",
        loss_guard_triggered=False,
    )
    frame = pd.DataFrame(
        {"open": [100.0, 100.0, 999.0], "close": [100.0, 120.0, 999.0]},
        index=pd.DatetimeIndex(["2021-01-03", "2021-01-04", "2026-08-14"]),
    )
    instance = object.__new__(runner.OfficialValidationRunner)
    identity = runner._identity_key_from_record(record)
    result = instance.run_realistic_portfolio(
        {runner.BASE_STRATEGY_ID: [record]},
        market_data_by_identity={identity: frame},
    )["strategies"][runner.BASE_STRATEGY_ID]

    terminal = next(event for event in result["event_ledger"] if event["event_type"] == "VALUATION")
    assert result["status"] == "PASS"
    assert result["metrics"]["unresolved_count"] == 0
    assert terminal["event_status"] == "EXECUTED"
    assert terminal["execution_date"] == "2021-01-04"
    assert terminal["cash_before"] == terminal["cash_after"]
    assert not any(event["event_type"] == "EXIT" for event in result["event_ledger"])
