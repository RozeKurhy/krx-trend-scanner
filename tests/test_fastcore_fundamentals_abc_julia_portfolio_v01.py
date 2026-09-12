import hashlib

import pandas as pd

from scripts import run_fastcore_fundamentals_abc_julia_portfolio_v01 as runner


def _daily(start="2021-04-01", end="2021-06-30", prices=None):
    index = pd.bdate_range(start, end)
    if prices is None:
        prices = [100.0] * len(index)
    return pd.DataFrame(
        {"open": prices, "high": prices, "low": prices, "close": prices},
        index=index,
    )


def _signal(signal_date="2021-04-02", ticker="000001", exit_signal_date=None, score=80.0):
    return {
        "signal_id": f"{ticker}-{signal_date}",
        "ticker": ticker,
        "isu_cd": f"ISU{ticker}",
        "market": "KOSPI",
        "name": "Fixture",
        "signal_date": signal_date,
        "signal_information_date": signal_date,
        "fast_score": score,
        "pattern_score": None,
        "entry_open": 100.0,
        "exit_signal_date": exit_signal_date,
        "exit_type": "EXIT4_SCORE_DRAWDOWN_GE_15" if exit_signal_date else None,
        "strategy_record": {"exit_signal_date": exit_signal_date, "exit_type": "EXIT4_SCORE_DRAWDOWN_GE_15"},
    }


def test_portfolio_contract_constants():
    assert runner.INITIAL_CAPITAL == 200_000_000
    assert runner.POSITION_CAP == 5_000_000
    assert runner.SIGNAL_END == pd.Timestamp("2026-08-14")
    assert runner.SUPPORT_END == pd.Timestamp("2026-08-21")


def test_weekly_calendar_uses_next_available_session_after_week():
    daily = _daily()
    daily = daily.drop(pd.Timestamp("2021-04-05"))
    calendar = runner._build_calendar({"000001": daily})
    assert runner._next_week_open("2021-04-02", calendar) == pd.Timestamp("2021-04-06")


def test_duplicate_weekly_candidate_keeps_latest_signal():
    calendar = runner._build_calendar({"000001": _daily()})
    rows = pd.DataFrame([
        _signal("2021-04-01", score=90.0),
        _signal("2021-04-02", score=70.0),
    ])
    selected, duplicates = runner._dedupe_and_rank_candidates(rows, calendar)
    assert len(selected[pd.Timestamp("2021-04-05")]) == 1
    assert selected[pd.Timestamp("2021-04-05")][0]["signal_date"] == "2021-04-02"
    assert len(duplicates) == 1
    assert duplicates[0]["precheck_result"] == "SKIP_DUPLICATE_WEEKLY_CANDIDATE"


def test_entry_is_integer_and_capped_at_five_million():
    result = runner.run_portfolio(
        pd.DataFrame([_signal()]), runner._build_calendar({"000001": _daily()}), {"000001": _daily()}, runner.PORTFOLIO_A
    )
    entry = result["events"].query("event_type == 'ENTRY'").iloc[0]
    assert entry["shares_delta"] == 50_000
    assert abs(entry["cash_delta"]) == 5_000_000
    assert entry["shares_delta"] == int(entry["shares_delta"])


def test_cash_shortage_is_dropped_without_negative_cash():
    daily = _daily(prices=[300_000_000.0] * len(pd.bdate_range("2021-04-01", "2021-06-30")))
    result = runner.run_portfolio(
        pd.DataFrame([_signal()]), runner._build_calendar({"000001": daily}), {"000001": daily}, runner.PORTFOLIO_A
    )
    assert result["events"].empty
    assert (result["entry_audit"]["execution_result"] == "SKIP_INSUFFICIENT_CASH").all()
    assert result["summary"]["minimum_cash"] == runner.INITIAL_CAPITAL


def test_portfolio_b_triggers_exactly_at_fifty_and_only_once():
    index = pd.bdate_range("2021-04-01", "2021-06-30")
    close = [100.0 if date < pd.Timestamp("2021-04-09") else 150.0 for date in index]
    daily = _daily(prices=close)
    result = runner.run_portfolio(
        pd.DataFrame([_signal(exit_signal_date="2021-05-14")]),
        runner._build_calendar({"000001": daily}),
        {"000001": daily},
        runner.PORTFOLIO_B,
    )
    partials = result["events"].query("event_type == 'PARTIAL_PROFIT'")
    assert len(partials) == 1
    assert partials.iloc[0]["shares_delta"] == -25_000
    assert result["summary"]["total_partial_exits"] == 1


def test_portfolio_b_below_fifty_does_not_trigger():
    index = pd.bdate_range("2021-04-01", "2021-06-30")
    close = [100.0 if date < pd.Timestamp("2021-04-09") else 149.99 for date in index]
    daily = _daily(prices=close)
    result = runner.run_portfolio(
        pd.DataFrame([_signal(exit_signal_date="2021-05-14")]),
        runner._build_calendar({"000001": daily}),
        {"000001": daily},
        runner.PORTFOLIO_B,
    )
    assert result["summary"]["total_partial_exits"] == 0


def test_full_exit_precedes_partial_profit_same_batch():
    index = pd.bdate_range("2021-04-01", "2021-06-30")
    close = [100.0 if date < pd.Timestamp("2021-04-09") else 160.0 for date in index]
    daily = _daily(prices=close)
    # Exit signal in the same week as the +50% trigger's next batch.
    result = runner.run_portfolio(
        pd.DataFrame([_signal(exit_signal_date="2021-04-09")]),
        runner._build_calendar({"000001": daily}),
        {"000001": daily},
        runner.PORTFOLIO_B,
    )
    assert list(result["events"]["event_type"]) == ["ENTRY", "FULL_EXIT"]


def test_daily_curve_marks_every_trading_day():
    daily = _daily()
    result = runner.run_portfolio(
        pd.DataFrame([_signal()]), runner._build_calendar({"000001": daily}), {"000001": daily}, runner.PORTFOLIO_A
    )
    assert len(result["equity_curve"]) == len(daily)
    assert result["equity_curve"]["date"].is_unique


def test_frozen_trade_authority_hash_and_count():
    assert hashlib.sha256(runner.FROZEN_TRADES_PATH.read_bytes()).hexdigest() == runner.FROZEN_TRADES_SHA
    assert hashlib.sha256(runner.ABC_TRADES_PATH.read_bytes()).hexdigest() == runner.ABC_TRADES_SHA
    assert hashlib.sha256(runner.RAW_PATH.read_bytes()).hexdigest() == runner.RAW_SHA
    assert callable(runner.load_fresh_signal_authority)


def test_existing_portfolio_artifacts_have_nonnegative_cash_and_contract_metrics():
    import json
    from pathlib import Path

    out = Path("artifacts/backtests/fastcore_fundamentals_abc_julia_portfolio_v01")
    for name in ("portfolio_a_summary.json", "portfolio_b_summary.json"):
        summary = json.loads((out / name).read_text())
        assert summary["initial_capital"] == 200_000_000
        assert summary["minimum_cash"] >= 0
        assert summary["execution_contract"]["fractional_shares"] is False
    b = json.loads((out / "portfolio_b_summary.json").read_text())
    assert b["total_fresh_entry_candidates"] > 345
    assert b["duplicate_weekly_candidate_skipped_count"] >= 0


def test_realized_portfolio_events_preserve_cash_integer_and_lifecycle_integrity():
    from pathlib import Path

    out = Path("artifacts/backtests/fastcore_fundamentals_abc_julia_portfolio_v01")
    for variant in ("a", "b"):
        events = pd.read_csv(out / f"portfolio_{variant}_events.csv")
        active = set()
        for date, group in events.groupby("execution_date", sort=False):
            order = group["event_type"].tolist()
            assert order == sorted(order, key={"FULL_EXIT": 0, "PARTIAL_PROFIT": 1, "ENTRY": 2}.get)
            for row in group.to_dict("records"):
                ticker = str(row["ticker"])
                if row["event_type"] == "ENTRY":
                    assert ticker not in active
                    assert -float(row["cash_delta"]) <= runner.POSITION_CAP
                    active.add(ticker)
                elif row["event_type"] == "PARTIAL_PROFIT":
                    assert ticker in active
                elif row["event_type"] == "FULL_EXIT":
                    assert ticker in active
                    active.remove(ticker)
                assert int(row["shares_delta"]) == row["shares_delta"]
                assert float(row["cash_after"]) >= 0


def test_entry_audit_has_no_signal_carry_or_unclassified_result():
    from pathlib import Path

    audit = pd.read_csv(Path("artifacts/backtests/fastcore_fundamentals_abc_julia_portfolio_v01/portfolio_entry_audit.csv"))
    allowed = {
        "EXECUTED", "SKIP_ACTIVE_POSITION", "SKIP_INSUFFICIENT_CASH",
        "SKIP_SAME_OPEN_REENTRY", "SKIP_DUPLICATE_WEEKLY_CANDIDATE",
        "SKIP_MISSING_EXECUTION_PRICE",
    }
    assert set(audit["execution_result"]) <= allowed
    assert audit["signal_id"].notna().all()


def test_cash_blocked_first_signal_allows_later_fresh_signal():
    index = pd.bdate_range("2021-04-01", "2021-04-30")
    prices = [100.0] * len(index)
    prices[index.get_loc(pd.Timestamp("2021-04-05"))] = 300_000_000.0
    daily = _daily(start="2021-04-01", end="2021-04-30", prices=prices)
    signals = pd.DataFrame([_signal("2021-04-02"), _signal("2021-04-09")])
    result = runner.run_portfolio(
        signals, runner._build_calendar({"000001": daily}), {"000001": daily}, runner.PORTFOLIO_A
    )
    audit = result["entry_audit"].sort_values("signal_date")
    assert audit["execution_result"].tolist() == ["SKIP_INSUFFICIENT_CASH", "EXECUTED"]


def test_cash_blocked_signal_is_not_carried_without_a_later_signal():
    index = pd.bdate_range("2021-04-01", "2021-04-30")
    prices = [300_000_000.0] * len(index)
    daily = _daily(start="2021-04-01", end="2021-04-30", prices=prices)
    result = runner.run_portfolio(
        pd.DataFrame([_signal("2021-04-02")]),
        runner._build_calendar({"000001": daily}),
        {"000001": daily},
        runner.PORTFOLIO_A,
    )
    assert result["events"].empty
    assert result["entry_audit"]["execution_result"].tolist() == ["SKIP_INSUFFICIENT_CASH"]


def test_later_fresh_signal_survives_baseline_active_suppression_when_first_executes():
    daily = _daily()
    signals = pd.DataFrame([_signal("2021-04-02"), _signal("2021-04-09")])
    result = runner.run_portfolio(
        signals, runner._build_calendar({"000001": daily}), {"000001": daily}, runner.PORTFOLIO_A
    )
    audit = result["entry_audit"].sort_values("signal_date")
    assert audit["execution_result"].tolist() == ["EXECUTED", "SKIP_ACTIVE_POSITION"]
    assert set(audit["signal_id"]) == {"000001-2021-04-02", "000001-2021-04-09"}


def test_active_position_blocks_a_later_fresh_signal():
    daily = _daily()
    result = runner.run_portfolio(
        pd.DataFrame([_signal("2021-04-02"), _signal("2021-04-09")]),
        runner._build_calendar({"000001": daily}),
        {"000001": daily},
        runner.PORTFOLIO_A,
    )
    assert (result["entry_audit"]["execution_result"] == "SKIP_ACTIVE_POSITION").sum() == 1


def test_same_open_full_exit_and_reentry_is_skipped():
    daily = _daily(start="2021-04-01", end="2021-05-31")
    first = _signal("2021-04-02", exit_signal_date="2021-04-16")
    second = _signal("2021-04-12")
    result = runner.run_portfolio(
        pd.DataFrame([first, second]),
        runner._build_calendar({"000001": daily}),
        {"000001": daily},
        runner.PORTFOLIO_A,
    )
    audit = result["entry_audit"].sort_values("signal_date")
    assert audit["execution_result"].tolist() == ["EXECUTED", "SKIP_SAME_OPEN_REENTRY"]
    assert result["events"]["event_type"].tolist() == ["ENTRY", "FULL_EXIT"]
