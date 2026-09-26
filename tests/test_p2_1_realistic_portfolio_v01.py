import pandas as pd

from scripts.run_p2_1_realistic_portfolio_v01 import _frame_for_record, _portfolio_replay


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


def _run(records: list[dict[str, object]], frames: dict[str, pd.DataFrame], *, end: str = "2021-01-06") -> dict[str, object]:
    dates = pd.to_datetime(["2021-01-04", "2021-01-05", "2021-01-06", "2021-01-07"])
    return _portfolio_replay(
        records,
        frames,
        dates,
        strategy_id="TEST",
        effective_start=pd.Timestamp("2021-01-04"),
        effective_end=pd.Timestamp(end),
        execution_support=pd.Timestamp("2021-01-07"),
        gap_classifications={(str(records[0]["ticker"]), "2021-01-05"): "NON_TRADING_PLACEHOLDER"},
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
    assert stale["used_for_execution"] is False
    assert stale["used_for_strategy_or_features"] is False


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
