import pandas as pd

from scripts.run_p2_1_realistic_portfolio_v01 import (
    _frame_for_record,
    _mdd,
    _portfolio_replay,
    _valuation_close_with_carry,
    _valuation_coverage_metrics,
)


def test_frame_lookup_matches_identity_segment_pipe_key():
    record = {
        "ticker": "005930",
        "isu_cd": "KR7005930003",
        "market": "KOSPI",
        "identity_effective_from": "2010-01-04",
        "identity_effective_to": "2026-09-21",
    }
    frame = pd.DataFrame({"open": [100.0]})
    frames = {"005930|KR7005930003|KOSPI|2010-01-04|2026-09-21": frame}

    assert _frame_for_record(record, frames) is frame


def _portfolio_record(ticker: str, *, entry_date: str = "2021-01-04") -> dict[str, object]:
    identity = f"KR{int(ticker):010d}"
    key = f"{ticker}|{identity}|KOSPI|2010-01-04|2026-08-21"
    pair_id = f"{key}|{ticker}_01"
    return {
        "ticker": ticker,
        "isu_cd": identity,
        "market": "KOSPI",
        "identity_effective_from": "2010-01-04",
        "identity_effective_to": "2026-08-21",
        "pair_id": pair_id,
        "trade_id": f"{ticker}_01",
        "entry_signal_date": "2021-01-03",
        "entry_execution_date": entry_date,
        "entry_open": 100.0,
        "entry_market_cap": 2_000_000_000_000,
        "trade_status": "OPEN_AT_CUTOFF",
        "terminal_valuation_date": None,
        "terminal_valuation_price": None,
    }


def _frame(ticker: str, identity: str, closes: dict[str, float], opens: dict[str, float] | None = None) -> pd.DataFrame:
    opens = opens or closes
    dates = sorted(set(closes) | set(opens))
    return pd.DataFrame(
        {
            "open": [opens.get(day, closes.get(day)) for day in dates],
            "high": [max(opens.get(day, closes.get(day)), closes.get(day, opens.get(day))) for day in dates],
            "low": [min(opens.get(day, closes.get(day)), closes.get(day, opens.get(day))) for day in dates],
            "close": [closes.get(day, opens.get(day)) for day in dates],
        },
        index=pd.to_datetime(dates),
    )


def _run(
    records: list[dict[str, object]],
    frames: dict[str, pd.DataFrame],
    *,
    end: str = "2021-01-06",
    gap_classifications: dict[tuple[str, str], str] | None = None,
) -> dict[str, object]:
    dates = pd.to_datetime(["2021-01-04", "2021-01-05", "2021-01-06", "2021-01-07"])
    if gap_classifications is None:
        gap_classifications = {
            (str(records[0]["ticker"]).zfill(6), "2021-01-05"): "NON_TRADING_PLACEHOLDER"
        }
    return _portfolio_replay(
        records,
        frames,
        dates,
        strategy_id="TEST",
        effective_start=pd.Timestamp("2021-01-04"),
        effective_end=pd.Timestamp(end),
        execution_support=pd.Timestamp("2021-01-07"),
        gap_classifications=gap_classifications,
    )


def test_valuation_gap_carries_prior_valid_close_for_daily_mtm_only():
    record = _portfolio_record("000001")
    key = "000001|KR0000000001|KOSPI|2010-01-04|2026-08-21"
    frame = _frame(
        "000001",
        "KR0000000001",
        {"2021-01-04": 100.0, "2021-01-06": 110.0},
        {"2021-01-04": 100.0, "2021-01-06": 110.0},
    )

    result = _run([record], {key: frame})

    assert result["metrics"]["unresolved_count"] == 0
    assert result["daily_equity"][1]["date"] == "2021-01-05"
    assert result["daily_equity"][1]["equity"] is not None
    assert len(result["valuation_gap_audit"]) == 1
    stale = result["valuation_gap_audit"][0]
    assert stale["last_valid_adjusted_close_date"] == "2021-01-04"
    assert stale["carried_adjusted_close"] == 100.0
    assert stale["stale_age_trading_days"] == 1
    assert stale["stale_age_calendar_days"] == 1
    assert stale["gap_classification"] == "NON_TRADING_PLACEHOLDER"
    assert stale["carry_allowed"] is True
    assert stale["carry_applied"] is True
    assert stale["carry_evidence"] == "MARKET_DATA_REPOSITORY_V2_NON_TRADING_PLACEHOLDER_V01"
    assert stale["used_for_execution"] is False
    assert stale["used_for_strategy_or_features"] is False


def test_exact_close_is_used_without_carry_audit():
    record = _portfolio_record("000001")
    key = "000001|KR0000000001|KOSPI|2010-01-04|2026-08-21"
    frame = _frame(
        "000001",
        "KR0000000001",
        {"2021-01-04": 100.0, "2021-01-05": 105.0},
    )
    close, audit = _valuation_close_with_carry(
        record,
        {key: frame},
        pd.Timestamp("2021-01-05"),
        {pd.Timestamp(day): index for index, day in enumerate(pd.to_datetime(["2021-01-04", "2021-01-05"]))},
        {},
        strategy_id="TEST",
        pair_id=str(record["pair_id"]),
    )
    assert close == 105.0
    assert audit is None


def test_unclassified_gap_is_not_carried_and_nav_recovers_when_price_returns():
    record = _portfolio_record("000001")
    key = "000001|KR0000000001|KOSPI|2010-01-04|2026-08-21"
    frame = _frame(
        "000001",
        "KR0000000001",
        {"2021-01-04": 100.0, "2021-01-06": 110.0},
    )
    result = _run([record], {key: frame}, gap_classifications={})

    assert result["daily_equity"][1]["equity"] is None
    assert result["daily_equity"][2]["equity"] is not None
    assert result["metrics"]["total_valuation_days"] == 3
    assert result["metrics"]["valid_nav_days"] == 2
    assert result["metrics"]["unobservable_nav_days"] == 1
    assert result["metrics"]["mdd_type"] == "INSUFFICIENT"
    assert result["valuation_gap_audit"][0]["carry_applied"] is False
    assert result["valuation_gap_audit"][0]["carry_status"] == "UNOBSERVABLE_NO_APPROVED_NON_TRADING_EVIDENCE"


def test_unobservable_execution_support_nav_is_not_double_counted_as_non_valuation():
    record = _portfolio_record("000001")
    key = "000001|KR0000000001|KOSPI|2010-01-04|2026-08-21"
    frame = _frame("000001", "KR0000000001", {"2021-01-04": 100.0})

    result = _run([record], {key: frame}, gap_classifications={})

    assert result["daily_equity"][-1]["equity"] is None
    assert result["metrics"]["final_equity"] is None
    assert result["metrics"]["unresolved_count"] > len(result["valuation_gap_audit"])
    assert result["metrics"]["unresolved_non_valuation_count"] == 0


def test_one_unclassified_held_position_makes_the_whole_portfolio_nav_unobservable():
    first = _portfolio_record("000001")
    second = _portfolio_record("000002")
    first_key = "000001|KR0000000001|KOSPI|2010-01-04|2026-08-21"
    second_key = "000002|KR0000000002|KOSPI|2010-01-04|2026-08-21"
    frames = {
        first_key: _frame("000001", "KR0000000001", {"2021-01-04": 100.0, "2021-01-06": 110.0}),
        second_key: _frame("000002", "KR0000000002", {"2021-01-04": 100.0, "2021-01-06": 110.0}),
    }
    result = _run(
        [first, second],
        frames,
        gap_classifications={("000001", "2021-01-05"): "NON_TRADING_PLACEHOLDER"},
    )

    gap_day = result["daily_equity"][1]
    assert gap_day["equity"] is None
    assert gap_day["invested_market_value"] is None
    assert result["daily_equity"][2]["equity"] is not None


def test_valuation_carry_is_not_used_to_fill_a_missing_entry_open():
    record = _portfolio_record("000001", entry_date="2021-01-05")
    key = "000001|KR0000000001|KOSPI|2010-01-04|2026-08-21"
    frame = _frame(
        "000001",
        "KR0000000001",
        {"2021-01-04": 100.0, "2021-01-06": 110.0},
    )

    result = _run([record], {key: frame})

    assert result["metrics"]["trade_count"] == 0
    assert result["metrics"]["unresolved_count"] == 1
    assert result["valuation_gap_audit"] == []


def test_mdd_uses_only_valid_nav_rows_and_records_valid_peak_trough_and_recovery():
    curve = pd.DataFrame(
        {
            "date": ["2021-01-04", "2021-01-05", "2021-01-06", "2021-01-07", "2021-01-08"],
            "equity": [100.0, None, 75.0, 119.0, 120.0],
        }
    )
    result = _mdd(curve)
    assert result["mdd_pct"] == -25.0
    assert result["peak_date"] == "2021-01-04"
    assert result["trough_date"] == "2021-01-06"
    assert result["recovery_date"] == "2021-01-07"


def test_coverage_classifies_exact_observed_and_raw_below_90_percent():
    start = pd.Timestamp("2021-01-01")
    exact_curve = pd.DataFrame({"date": pd.date_range(start, periods=10), "equity": [100.0] * 10})
    observed_curve = exact_curve.copy()
    observed_curve.loc[0, "equity"] = None
    below_curve = pd.DataFrame({"date": pd.date_range(start, periods=2000), "equity": [100.0] * 1799 + [None] * 201})

    exact = _valuation_coverage_metrics(exact_curve, effective_start=start, effective_end=exact_curve["date"].iloc[-1])
    observed = _valuation_coverage_metrics(observed_curve, effective_start=start, effective_end=observed_curve["date"].iloc[-1])
    below = _valuation_coverage_metrics(below_curve, effective_start=start, effective_end=below_curve["date"].iloc[-1])

    assert exact["mdd_type"] == "EXACT"
    assert observed["coverage_ratio"] == 0.9
    assert observed["mdd_type"] == "OBSERVED"
    assert below["coverage_ratio"] == 0.8995
    assert below["coverage_pct"] == 89.95
    assert below["mdd_type"] == "INSUFFICIENT"
    assert below["mdd_usable_for_official_pass"] is False


def test_no_hidden_n40_cap_and_cash_shortage_is_the_actual_limiter():
    records = [_portfolio_record(f"{number:06d}") for number in range(1, 51)]
    frames: dict[str, pd.DataFrame] = {}
    for record in records:
        ticker = str(record["ticker"])
        identity = str(record["isu_cd"])
        key = f"{ticker}|{identity}|KOSPI|2010-01-04|2026-08-21"
        frames[key] = _frame(
            ticker,
            identity,
            {"2021-01-04": 4_000_000.0, "2021-01-06": 4_000_000.0},
        )

    result = _run(records, frames)
    audit = result["entry_candidate_audit"]
    at_40 = [row for row in audit if row["concurrent_positions_before_candidate"] == 40]

    assert len(at_40) == 1
    assert at_40[0]["position_cap_configured"] is None
    assert at_40[0]["slot_cap_would_block"] is False
    assert at_40[0]["cash_sufficient"] is True
    assert at_40[0]["decision"] == "EXECUTED"
    assert result["metrics"]["maximum_concurrent_positions"] > 40
    assert any(row["decision"] == "CASH_INSUFFICIENT" for row in audit)
    assert result["metrics"]["cash_shortage_skipped_entries"] == 1
