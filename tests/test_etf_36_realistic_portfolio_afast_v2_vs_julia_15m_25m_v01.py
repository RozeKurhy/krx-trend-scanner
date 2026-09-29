from __future__ import annotations

import pandas as pd

from scripts import run_etf_36_realistic_portfolio_afast_v2_vs_julia_15m_25m_v01 as portfolio


DATES = ["2025-01-02", "2025-01-03", "2025-01-06"]
WINDOW = {
    "scenario_id": "15M",
    "window_id": "P1",
    "strategy_id": portfolio.engine.STRATEGY_A_FAST,
    "strategy_label": "A FAST Core V2",
    "window_start": DATES[0],
    "cutoff_date": DATES[1],
    "execution_support_date": DATES[2],
    "initial_capital_krw": 20_000_000.0,
    "position_cap_krw": 15_000_000.0,
}


def _prices() -> dict[str, pd.DataFrame]:
    return {
        ticker: pd.DataFrame(
            {
                "open": [10_000.0, 10_100.0, 11_000.0],
                "high": [10_100.0, 10_200.0, 11_100.0],
                "low": [9_900.0, 10_000.0, 10_900.0],
                "close": [10_000.0, 10_050.0, 10_950.0],
                "volume": [1_000.0, 1_000.0, 1_000.0],
            },
            index=pd.to_datetime(DATES),
        )
        for ticker in ("000001", "000002")
    }


def _trade(ticker: str, status: str = "OPEN_AT_CUTOFF") -> dict[str, object]:
    realized = status == "REALIZED"
    return {
        "strategy_id": portfolio.engine.STRATEGY_A_FAST,
        "window_id": "P1",
        "ticker": ticker,
        "name": f"ETF {ticker}",
        "major_category": "MARKET_INDEX",
        "ISU_CD": f"ISU-{ticker}",
        "trade_identity": f"trade-{ticker}",
        "signal_date": DATES[0],
        "entry_execution_date": DATES[0],
        "entry_price_raw_open": 10_000.0,
        "exit_signal_date": DATES[1] if realized else "",
        "exit_execution_date": DATES[2] if realized else "",
        "exit_price_raw_open": 11_000.0 if realized else "",
        "exit_or_terminal_date": DATES[2] if realized else DATES[1],
        "terminal_price_raw": 10_050.0,
        "gross_return_pct": 10.0 if realized else 0.5,
        "holding_krx_sessions_inclusive": 3 if realized else 2,
        "trade_status": status,
        "cutoff_date": DATES[1],
        "comparison_effective_start": DATES[0],
    }


def _set_worker_inputs(monkeypatch) -> None:
    monkeypatch.setattr(portfolio, "_WORKER_DAILY", _prices())
    monkeypatch.setattr(portfolio, "_WORKER_CALENDAR", DATES)
    monkeypatch.setattr(
        portfolio,
        "_WORKER_CATEGORIES",
        {"000001": "MARKET_INDEX", "000002": "MARKET_INDEX"},
    )


def test_job_matrix_has_twenty_exact_combinations() -> None:
    ledger = pd.DataFrame([_trade("000001")])

    jobs = portfolio._make_jobs(ledger, {portfolio.engine.STRATEGY_A_FAST: "A FAST Core V2"})

    assert len(jobs) == 20
    assert {job["scenario_id"] for job in jobs} == {"15M", "25M"}
    assert {job["position_cap_krw"] for job in jobs} == {15_000_000.0, 25_000_000.0}
    assert {job["window_id"] for job in jobs} == set(portfolio.EXPECTED_WINDOWS)


def test_full_size_cash_shortage_is_skipped_and_audited(monkeypatch) -> None:
    _set_worker_inputs(monkeypatch)
    job = {**WINDOW, "trade_rows": [_trade("000001"), _trade("000002")]}

    result = portfolio._run_portfolio_job(job)
    ledger = result["ledger"].set_index("ticker")
    skips = portfolio._cash_skip_rows([result])

    assert ledger.loc["000001", "entry_status"] == "FILLED"
    assert ledger.loc["000002", "entry_status"] == "CASH_SKIP"
    assert int(ledger.loc["000001", "shares"]) == int(15_000_000 // (10_000 * (1 + portfolio.engine.BUY_SLIPPAGE_RATE)))
    assert float(ledger.loc["000001", "buy_notional_krw"]) <= 15_000_000.0
    assert float(result["summary"]["negative_cash_count"]) == 0
    assert len(skips) == 1
    assert skips.iloc[0]["required_capital_krw"] > skips.iloc[0]["available_cash_krw"]
    assert skips.iloc[0]["skip_reason"] == "INSUFFICIENT_CASH_FOR_FULL_POSITION"
    assert int(result["summary"]["cash_reconstruction_error_count"]) == 0


def test_realized_position_exits_on_support_and_records_net_pnl(monkeypatch) -> None:
    _set_worker_inputs(monkeypatch)
    job = {**WINDOW, "initial_capital_krw": 50_000_000.0, "trade_rows": [_trade("000001", "REALIZED")]}

    result = portfolio._run_portfolio_job(job)
    filled = portfolio._filled_trade_rows([result])

    assert result["summary"]["realized_trades"] == 1
    assert result["summary"]["open_at_cutoff_positions"] == 0
    assert result["summary"]["sell_tax_krw"] == 0.0
    assert result["summary"]["cash_reconstruction_error_count"] == 0
    assert filled.iloc[0]["portfolio_exit_status"] == "FILLED"
    assert filled.iloc[0]["exit_execution_date"] == DATES[2]
    assert filled.iloc[0]["net_pre_tax_return_pct"] == result["ledger"].iloc[0]["realized_net_return_pct"]


def test_holding_summary_separates_closed_and_open_positions() -> None:
    rows = pd.DataFrame([
        {"holding_class": "CLOSED", "holding_krx_sessions": 3, "holding_calendar_days": 4},
        {"holding_class": "OPEN_AT_CUTOFF", "holding_krx_sessions": 2, "holding_calendar_days": 1},
    ])

    all_rows = portfolio._holding_stats(rows, "ALL_FILLED_POSITIONS")
    closed = portfolio._holding_stats(rows, "CLOSED")
    opened = portfolio._holding_stats(rows, "OPEN_AT_CUTOFF")

    assert all_rows["filled_position_count"] == 2
    assert all_rows["mean_holding_sessions"] == 2.5
    assert closed["mean_holding_calendar_days"] == 4.0
    assert opened["median_holding_sessions"] == 2.0


def test_equity_curve_adds_capital_utilization_and_drawdown() -> None:
    curve = pd.DataFrame({
        "date": DATES,
        "cash": [250.0, 150.0, 160.0],
        "invested_market_value": [0.0, 100.0, 90.0],
        "total_equity": [250.0, 250.0, 250.0],
        "open_positions": [0, 1, 1],
        "cash_ratio": [1.0, 0.6, 0.64],
        "valuation_basis_date": DATES,
        "execution_support_only": [False, False, True],
    })

    enriched = portfolio._enrich_curve(curve, WINDOW)

    assert enriched["capital_utilization_pct"].tolist() == [0.0, 40.0, 36.0]
    assert enriched["drawdown_pct"].tolist() == [0.0, 0.0, 0.0]
    assert enriched["concurrent_holdings"].tolist() == [0, 1, 1]
