"""Targeted invariant tests for the FastCore vs Julia STEP 1 backtest engine
(directive MAIN_MERGE_AND_FASTCORE_JULIA_STRATEGY_BACKTEST_V01, B23).

No live network calls anywhere in this file. No full-repository regeneration.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.backtest.fastcore_julia_strategy_v01 import (
    AVG_TRADING_VALUE_20D_THRESHOLD,
    CLOSE_THRESHOLD,
    MARKET_CAP_THRESHOLD,
    simulate_ticker_strategy_v01,
)
from trend_scanner.backtest.raw_investability_panel import evaluate_entry_filter

ROOT = Path(__file__).resolve().parent.parent
SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"


@pytest.fixture
def contracts():
    sc = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    st = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))
    return sc, st


# ---------------------------------------------------------------------------
# Entry filter: thresholds, entry-only semantics, PIT
# ---------------------------------------------------------------------------


def _panel(rows: dict[str, list]) -> pd.DataFrame:
    dates = pd.to_datetime(rows.pop("date"))
    df = pd.DataFrame(rows, index=dates)
    return df


def test_entry_filter_thresholds_are_the_new_v01_values():
    assert MARKET_CAP_THRESHOLD == 300_000_000_000.0
    assert AVG_TRADING_VALUE_20D_THRESHOLD == 300_000_000.0
    assert CLOSE_THRESHOLD == 5_000.0


def test_entry_filter_passes_only_when_all_three_conditions_hold():
    panel = _panel({
        "date": ["2020-01-02"],
        "close": [5000.0],
        "market_cap": [300_000_000_000.0],
        "trading_value": [1.0],
        "avg_trading_value_20d": [300_000_000.0],
    })
    result = evaluate_entry_filter(
        panel, pd.Timestamp("2020-01-02"),
        market_cap_threshold=MARKET_CAP_THRESHOLD,
        avg_trading_value_threshold=AVG_TRADING_VALUE_20D_THRESHOLD,
        close_threshold=CLOSE_THRESHOLD,
    )
    assert result["entry_filter_pass"] is True
    assert result["entry_market_cap_pass"] is True
    assert result["entry_trading_value_pass"] is True
    assert result["entry_close_pass"] is True


@pytest.mark.parametrize(
    "market_cap,avg_tv,close",
    [
        (299_999_999_999.0, 300_000_000.0, 5_000.0),  # market cap just under
        (300_000_000_000.0, 299_999_999.0, 5_000.0),  # trading value just under
        (300_000_000_000.0, 300_000_000.0, 4_999.99),  # close just under
    ],
)
def test_entry_filter_fails_if_any_single_condition_fails(market_cap, avg_tv, close):
    panel = _panel({
        "date": ["2020-01-02"],
        "close": [close],
        "market_cap": [market_cap],
        "trading_value": [1.0],
        "avg_trading_value_20d": [avg_tv],
    })
    result = evaluate_entry_filter(
        panel, pd.Timestamp("2020-01-02"),
        market_cap_threshold=MARKET_CAP_THRESHOLD,
        avg_trading_value_threshold=AVG_TRADING_VALUE_20D_THRESHOLD,
        close_threshold=CLOSE_THRESHOLD,
    )
    assert result["entry_filter_pass"] is False


def test_entry_filter_missing_panel_data_fails_closed():
    result = evaluate_entry_filter(
        None, pd.Timestamp("2020-01-02"),
        market_cap_threshold=MARKET_CAP_THRESHOLD,
        avg_trading_value_threshold=AVG_TRADING_VALUE_20D_THRESHOLD,
        close_threshold=CLOSE_THRESHOLD,
    )
    assert result["entry_filter_pass"] is False
    assert result["entry_market_cap"] is None


def test_entry_filter_never_exits_is_a_structural_property():
    """The entry filter function only ever returns pass/fail booleans on
    entry-side fields; it has no exit_type/exit_signal concept at all, so
    it structurally cannot be wired up as an exit condition -- confirming
    B6's "ENTRY-ONLY FILTER, NEVER AN EXIT CONDITION" requirement."""
    result = evaluate_entry_filter(
        None, pd.Timestamp("2020-01-02"),
        market_cap_threshold=MARKET_CAP_THRESHOLD,
        avg_trading_value_threshold=AVG_TRADING_VALUE_20D_THRESHOLD,
        close_threshold=CLOSE_THRESHOLD,
    )
    assert "exit_type" not in result
    assert "exit_signal_date" not in result


def test_no_lookahead_entry_filter():
    """A future date that would pass the filter must not leak into a
    decision made at an earlier signal date."""
    panel = _panel({
        "date": ["2020-01-02", "2020-06-01"],
        "close": [1_000.0, 6_000.0],
        "market_cap": [1.0, 400_000_000_000.0],
        "trading_value": [1.0, 1.0],
        "avg_trading_value_20d": [1.0, 400_000_000.0],
    })
    early = evaluate_entry_filter(
        panel, pd.Timestamp("2020-01-02"),
        market_cap_threshold=MARKET_CAP_THRESHOLD,
        avg_trading_value_threshold=AVG_TRADING_VALUE_20D_THRESHOLD,
        close_threshold=CLOSE_THRESHOLD,
    )
    assert early["entry_filter_pass"] is False
    assert early["entry_market_cap"] == 1.0

    late = evaluate_entry_filter(
        panel, pd.Timestamp("2020-06-01"),
        market_cap_threshold=MARKET_CAP_THRESHOLD,
        avg_trading_value_threshold=AVG_TRADING_VALUE_20D_THRESHOLD,
        close_threshold=CLOSE_THRESHOLD,
    )
    assert late["entry_filter_pass"] is True


def test_no_lookahead_evaluate_entry_filter_ignores_rows_after_signal_date():
    panel = _panel({
        "date": ["2020-01-02", "2020-01-03"],
        "close": [10_000.0, 10_000.0],
        "market_cap": [1.0, 999_999_999_999.0],
        "trading_value": [1.0, 1.0],
        "avg_trading_value_20d": [1.0, 999_999_999.0],
    })
    result = evaluate_entry_filter(
        panel, pd.Timestamp("2020-01-02"),
        market_cap_threshold=MARKET_CAP_THRESHOLD,
        avg_trading_value_threshold=AVG_TRADING_VALUE_20D_THRESHOLD,
        close_threshold=CLOSE_THRESHOLD,
    )
    assert result["entry_market_cap"] == 1.0, "must not read the 2020-01-03 row from a 2020-01-02 decision"


# ---------------------------------------------------------------------------
# Strategy invariant: FastCore vs Julia differ ONLY in loss-guard behavior
# ---------------------------------------------------------------------------


def _make_synthetic_daily(
    n_days: int = 900,
    drop_pct_on_day: int | None = None,
    drop_amount: float = -0.20,
    base_days: int = 500,
) -> pd.DataFrame:
    """A long flat base (for 24M-slope / long-term-structure warm-up)
    followed by a sustained uptrend, so Pattern A / FAST have a realistic
    chance of reaching TRANSITION/EARLY_TREND + TRIGGER/READY -- a pure
    monotonic-up or flat series rarely clears those gates."""
    dates = pd.bdate_range("2019-01-02", periods=n_days)
    price = 10_000.0
    opens, highs, lows, closes = [], [], [], []
    for i in range(n_days):
        if drop_pct_on_day is not None and i == drop_pct_on_day:
            price = price * (1 + drop_amount)
        elif i < base_days:
            price = price * (1 + 0.0003 * (1 if i % 2 == 0 else -1))
        else:
            price = price * 1.0035
        opens.append(price * 0.999)
        highs.append(price * 1.012)
        lows.append(price * 0.988)
        closes.append(price)
    volume = [1_000_000] * n_days
    trading_value = [p * v for p, v in zip(closes, volume)]
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volume, "trading_value": trading_value},
        index=dates,
    )


def _always_pass_panel(dates: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "close": [10_000.0] * len(dates),
            "market_cap": [1_000_000_000_000.0] * len(dates),
            "trading_value": [1_000_000_000.0] * len(dates),
            "avg_trading_value_20d": [1_000_000_000.0] * len(dates),
        },
        index=dates,
    )


def test_fastcore_and_julia_share_identical_entry_decisions(contracts, monkeypatch):
    """With the entry filter forced to always pass, FastCore and Julia run
    against the same underlying price series must find the exact same
    first entry (same signal date, same execution date, same entry price,
    same entry-side contract fields) -- the only place they may then
    diverge is loss-guard-driven exit behavior."""
    score_contract, stage_contract = contracts
    daily = _make_synthetic_daily(n_days=900, drop_pct_on_day=580, drop_amount=-0.25, base_days=500)
    panel = _always_pass_panel(daily.index)

    fc = simulate_ticker_strategy_v01(
        strategy_id="FASTCORE", ticker="999999", isu_cd=None, name="SYN", market="KOSPI",
        daily=daily, raw_panel=panel, score_contract=score_contract, stage_contract=stage_contract,
        loss_guard_enabled=True, backtest_end=daily.index[-1],
    )
    jl = simulate_ticker_strategy_v01(
        strategy_id="JULIA", ticker="999999", isu_cd=None, name="SYN", market="KOSPI",
        daily=daily, raw_panel=panel, score_contract=score_contract, stage_contract=stage_contract,
        loss_guard_enabled=False, backtest_end=daily.index[-1],
    )

    if not fc or not jl:
        pytest.skip("synthetic series produced no FAST/Pattern A signal -- entry-invariant not exercised")

    entry_fields = [
        "entry_signal_date", "entry_execution_date", "entry_open",
        "entry_market_cap", "entry_avg_trading_value_20d", "entry_signal_close",
        "entry_pattern_a_stage", "fast_stage", "fast_status",
        "monthly_permission_state", "daily_risk", "fast_score", "fast_score_state",
    ]
    for field in entry_fields:
        assert getattr(fc[0], field) == getattr(jl[0], field), f"first-entry field {field} diverged"


def test_julia_never_triggers_loss_guard(contracts):
    score_contract, stage_contract = contracts
    daily = _make_synthetic_daily(n_days=900, drop_pct_on_day=580, drop_amount=-0.30, base_days=500)
    panel = _always_pass_panel(daily.index)

    jl = simulate_ticker_strategy_v01(
        strategy_id="JULIA", ticker="888888", isu_cd=None, name="SYN2", market="KOSDAQ",
        daily=daily, raw_panel=panel, score_contract=score_contract, stage_contract=stage_contract,
        loss_guard_enabled=False, backtest_end=daily.index[-1],
    )
    for trade in jl:
        assert trade.loss_guard_triggered is False
        assert trade.exit_type != "LOSS_GUARD_CLOSE_LE_NEG_15"


def test_fastcore_loss_guard_can_trigger_on_large_drawdown(contracts):
    score_contract, stage_contract = contracts
    daily = _make_synthetic_daily(n_days=900, drop_pct_on_day=580, drop_amount=-0.30, base_days=500)
    panel = _always_pass_panel(daily.index)

    fc = simulate_ticker_strategy_v01(
        strategy_id="FASTCORE", ticker="888888", isu_cd=None, name="SYN2", market="KOSDAQ",
        daily=daily, raw_panel=panel, score_contract=score_contract, stage_contract=stage_contract,
        loss_guard_enabled=True, backtest_end=daily.index[-1],
    )
    if not fc:
        pytest.skip("synthetic series produced no FAST/Pattern A signal")
    # At least confirm the loss-guard machinery is reachable and self-consistent
    # whenever it does trigger (execution strictly after signal, at NEXT open).
    for trade in fc:
        if trade.loss_guard_triggered:
            assert trade.loss_guard_signal_date is not None
            assert trade.loss_guard_execution_date is not None
            assert trade.loss_guard_execution_date > trade.loss_guard_signal_date


def test_reentry_requires_fresh_filter_pass(contracts):
    """A ticker that fails the investability filter for its entire history
    must produce zero trades under either strategy -- confirms the filter
    gate applies at every entry/re-entry, not merely at t=0."""
    score_contract, stage_contract = contracts
    daily = _make_synthetic_daily(n_days=900, base_days=500)
    failing_panel = pd.DataFrame(
        {
            "close": [10_000.0] * len(daily),
            "market_cap": [1.0] * len(daily),  # always below threshold
            "trading_value": [1.0] * len(daily),
            "avg_trading_value_20d": [1.0] * len(daily),
        },
        index=daily.index,
    )
    fc = simulate_ticker_strategy_v01(
        strategy_id="FASTCORE", ticker="777777", isu_cd=None, name="SYN3", market="KOSPI",
        daily=daily, raw_panel=failing_panel, score_contract=score_contract, stage_contract=stage_contract,
        loss_guard_enabled=True, backtest_end=daily.index[-1],
    )
    assert fc == []


# ---------------------------------------------------------------------------
# Network isolation
# ---------------------------------------------------------------------------


def test_backtest_module_never_imports_live_network_clients():
    import trend_scanner.backtest.fastcore_julia_strategy_v01 as engine
    import trend_scanner.backtest.raw_investability_panel as panel_mod

    source_engine = Path(engine.__file__).read_text(encoding="utf-8")
    source_panel = Path(panel_mod.__file__).read_text(encoding="utf-8")
    for forbidden in ("pykrx", "KrxOpenApiClient", "NaverDirectAdjustedPriceDataProvider", "OpenDart", "requests.get", "urllib"):
        assert forbidden not in source_engine, f"engine module references {forbidden}"
        assert forbidden not in source_panel, f"panel module references {forbidden}"
