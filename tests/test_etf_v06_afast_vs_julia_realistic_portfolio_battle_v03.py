from __future__ import annotations

import math

import pandas as pd
import pytest

from scripts import run_etf_v06_afast_vs_julia_realistic_portfolio_battle_v03 as battle


DATES = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"])


def _account(monkeypatch: pytest.MonkeyPatch, *, initial: float = 100.0, cap: float = 80.0) -> None:
    monkeypatch.setattr(battle, "GLOBAL_START", DATES[0])
    monkeypatch.setattr(battle, "CUTOFF", DATES[2])
    monkeypatch.setattr(battle, "EXECUTION_SUPPORT", DATES[3])
    monkeypatch.setattr(battle, "INITIAL_CAPITAL", initial)
    monkeypatch.setattr(battle, "POSITION_CAP", cap)


def _daily(*, opens: list[float] | None = None, closes: list[float] | None = None) -> pd.DataFrame:
    opens = opens or [1.0] * len(DATES)
    closes = closes or [1.0] * len(DATES)
    return pd.DataFrame(
        {
            "open": opens,
            "high": [max(o, c) for o, c in zip(opens, closes)],
            "low": [min(o, c) for o, c in zip(opens, closes)],
            "close": closes,
            "volume": [1_000] * len(DATES),
        },
        index=DATES,
    )


def _candidate(
    ticker: str,
    *,
    entry_day: pd.Timestamp = DATES[1],
    signal_day: pd.Timestamp = DATES[0],
    entry_price: float = 1.0,
    status: str = "OPEN_AT_CUTOFF",
    exit_signal: pd.Timestamp | None = None,
    exit_day: pd.Timestamp | None = None,
    exit_price: float | None = None,
) -> dict[str, object]:
    return {
        "strategy_id": battle.STRATEGY_A_FAST,
        "ticker": ticker,
        "ISU_CD": f"KR{ticker}",
        "name": f"ETF {ticker}",
        "category": "MARKET_INDEX",
        "signal_date": signal_day.strftime("%Y-%m-%d"),
        "entry_execution_date": entry_day.strftime("%Y-%m-%d"),
        "entry_price_raw_open": entry_price,
        "exit_signal_date": exit_signal.strftime("%Y-%m-%d") if exit_signal is not None else None,
        "exit_execution_date": exit_day.strftime("%Y-%m-%d") if exit_day is not None else None,
        "exit_price_raw_open": exit_price,
        "exit_or_terminal_date": exit_day.strftime("%Y-%m-%d") if exit_day is not None else DATES[2].strftime("%Y-%m-%d"),
        "terminal_price_raw": 1.0,
        "trade_status": status,
        "exit_reason": "TEST_EXIT",
        "source_signal_details": {"canonical_trade_id": f"{ticker}_01"},
    }


def test_buy_sizing_uses_integer_shares_and_position_notional_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(battle, "POSITION_CAP", 100.0)
    sizing = battle._buy_sizing(10.0, 1_000.0)

    assert sizing["shares"] == 9
    assert sizing["fill_price"] == pytest.approx(10.01)
    assert sizing["notional"] <= 100.0
    assert sizing["total_cost"] == pytest.approx(sizing["notional"] * (1 + battle.BUY_FEE_RATE))
    assert sizing["cash_sufficient"] is True


def test_cash_shortage_skips_whole_order_without_partial_fill_or_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    _account(monkeypatch)
    daily = {"000001": _daily(), "000002": _daily()}
    candidates = [_candidate("000001"), _candidate("000002")]

    result = battle._portfolio_replay(
        candidates, daily, list(DATES), battle.STRATEGY_A_FAST,
        {"000001": "MARKET_INDEX", "000002": "MARKET_INDEX"},
    )
    ledger = result["ledger"].set_index("ticker")

    assert ledger.loc["000001", "entry_status"] == "FILLED"
    assert ledger.loc["000002", "entry_status"] == "CASH_SKIP"
    assert ledger.loc["000002", "shares"] == 0
    assert not ((result["events"]["ticker"] == "000002") & (result["events"]["event_type"] == "ENTRY")).any()
    assert result["summary"]["negative_cash_count"] == 0
    assert result["summary"]["leverage_usage_krw"] == 0


def test_same_day_exit_precedes_buy_and_terminal_mark_is_separate_from_realized_pnl(monkeypatch: pytest.MonkeyPatch) -> None:
    _account(monkeypatch)
    daily = {
        "000001": _daily(opens=[1.0, 1.0, 1.2, 1.1], closes=[1.0, 1.0, 1.2, 1.1]),
        "000002": _daily(opens=[1.0, 1.0, 1.0, 1.0], closes=[1.0, 1.0, 1.3, 1.3]),
    }
    realized = _candidate(
        "000001", status="REALIZED", exit_signal=DATES[1], exit_day=DATES[2], exit_price=1.2,
    )
    terminal = _candidate(
        "000002", entry_day=DATES[2], signal_day=DATES[1], status="OPEN_AT_CUTOFF",
    )

    result = battle._portfolio_replay(
        [terminal, realized], daily, list(DATES), battle.STRATEGY_A_FAST,
        {"000001": "MARKET_INDEX", "000002": "SECTOR_INDUSTRY"},
    )
    same_day = result["events"].loc[result["events"]["date"].eq(DATES[2].strftime("%Y-%m-%d"))]
    assert same_day["event_type"].tolist() == ["EXIT", "ENTRY"]
    assert same_day.iloc[1]["cash_before"] > 20.0

    ledger = result["ledger"].set_index("ticker")
    realized_pnl = float(ledger.loc["000001", "realized_pnl_krw"])
    terminal_pnl = float(ledger.loc["000002", "terminal_unrealized_pnl_krw"])
    terminal_market_value = float(ledger.loc["000002", "terminal_market_value_krw"])
    assert result["summary"]["realized_pnl_krw"] == pytest.approx(realized_pnl)
    assert result["summary"]["terminal_unrealized_pnl_krw"] == pytest.approx(terminal_pnl)
    assert terminal_market_value == pytest.approx(ledger.loc["000002", "shares"] * 1.3)
    assert not math.isclose(realized_pnl, terminal_pnl)


def test_same_day_entry_order_uses_ticker_then_isu_then_signal_and_execution_date() -> None:
    rows = [
        {"ticker": "000002", "ISU_CD": "KR2", "signal_date": "2020-01-02", "entry_execution_date": "2020-01-03"},
        {"ticker": "000001", "ISU_CD": "KR2", "signal_date": "2020-01-02", "entry_execution_date": "2020-01-03"},
        {"ticker": "000001", "ISU_CD": "KR1", "signal_date": "2020-01-02", "entry_execution_date": "2020-01-03"},
    ]

    assert sorted(rows, key=battle._order_key) == [rows[2], rows[1], rows[0]]


def test_portfolio_replay_rejects_non_exact_entry_price(monkeypatch: pytest.MonkeyPatch) -> None:
    _account(monkeypatch)
    candidate = _candidate("000001", entry_price=1.01)

    with pytest.raises(RuntimeError, match="EXACT_ENTRY_OPEN_MISMATCH"):
        battle._portfolio_replay(
            [candidate], {"000001": _daily()}, list(DATES), battle.STRATEGY_A_FAST,
            {"000001": "MARKET_INDEX"},
        )


def test_cutoff_after_listing_is_not_evaluable_and_0238f0_is_not_excluded() -> None:
    assert battle._can_evaluate_by_cutoff("2026-09-15") is False
    assert set(battle.PERMANENT_EXCLUSIONS) == {"269530", "265690"}
    assert "0238F0" not in battle.PERMANENT_EXCLUSIONS


def test_portfolio_price_universe_contains_candidate_and_terminal_etfs_only() -> None:
    rows = [
        {"ticker": "000002", "trade_status": "OPEN_AT_CUTOFF"},
        {"ticker": "000001", "trade_status": "REALIZED"},
        {"ticker": "000002", "trade_status": "REALIZED"},
    ]

    assert battle._portfolio_price_universe(rows) == ["000001", "000002"]
    assert battle._portfolio_price_universe([]) == []


def test_zero_candidate_etfs_do_not_call_price_loader(tmp_path) -> None:
    absent_db = tmp_path / "must_not_be_opened.sqlite3"

    assert battle._portfolio_price_universe([]) == []
    assert battle._load_daily_frames(absent_db, []) == {}
    assert not absent_db.exists()


def test_candidate_price_loader_loads_only_requested_candidate_ticker(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sqlite3

    monkeypatch.setattr(battle, "GLOBAL_START", DATES[0])
    monkeypatch.setattr(battle, "EXECUTION_SUPPORT", DATES[3])
    db_path = tmp_path / "prices.sqlite3"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE bars (ticker TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL)")
        connection.executemany(
            "INSERT INTO bars VALUES (?, ?, ?, ?, ?, ?, ?)",
            [("000001", day.strftime("%Y-%m-%d"), 1.0, 1.1, 0.9, 1.0, 100.0) for day in DATES],
        )

    loaded = battle._load_daily_frames(db_path, ["000001"])

    assert set(loaded) == {"000001"}
    assert len(loaded["000001"]) == len(DATES)


def test_candidate_price_coverage_requires_cutoff_and_support_for_open_and_realized(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sqlite3

    monkeypatch.setattr(battle, "CUTOFF", DATES[2])
    monkeypatch.setattr(battle, "EXECUTION_SUPPORT", DATES[3])
    monkeypatch.setattr(battle, "GLOBAL_START", DATES[0])
    db_path = tmp_path / "prices.sqlite3"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE bars (ticker TEXT, date TEXT, open REAL, close REAL)")
        connection.executemany(
            "INSERT INTO bars VALUES (?, ?, ?, ?)",
            [("000001", DATES[2].strftime("%Y-%m-%d"), 1.2, 1.2),
             ("000001", DATES[3].strftime("%Y-%m-%d"), 1.3, 1.3)],
        )

    candidates = [
        {"ticker": "000001", "trade_status": "REALIZED"},
        {"ticker": "000001", "trade_status": "OPEN_AT_CUTOFF"},
    ]
    coverage = battle._audit_candidate_price_coverage(
        db_path, candidates, [{"ticker": "000001", "missing_session_count": 0}], authority_universe_count=3,
    )

    assert coverage["portfolio_price_requested_ticker_count"] == 1
    assert coverage["zero_candidate_etf_count"] == 2
    assert coverage["price_requested_for_zero_candidate_etf_count"] == 0
    assert coverage["candidate_required_price_coverage_missing_count"] == 0


def test_group_a_exact_parity_and_group_b_lifecycle_divergence_contract() -> None:
    base_trade = {
        "strategy_id": battle.STRATEGY_A_FAST,
        "ticker": "000001",
        "ISU_CD": "KR000001",
        "signal_date": "2020-02-03",
        "entry_execution_date": "2020-02-04",
        "entry_price_raw_open": 1.0,
        "trade_status": "REALIZED",
        "source_signal_details": {"canonical_trade_id": "base"},
    }
    group_a = battle._path_comparison([base_trade], [base_trade], exact=True)
    earlier_holding = {**base_trade, "signal_date": "2020-01-02", "exit_or_terminal_date": "2020-03-02"}
    group_b = battle._path_comparison([base_trade], [earlier_holding], exact=False)

    assert group_a["pass"] is True
    assert group_b["pass"] is False
    assert battle._earlier_position_spans_old_start([earlier_holding], "2020-02-03") is True


def test_entry_uses_exact_next_session_and_post_cutoff_entry_is_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(battle, "CUTOFF", DATES[2])
    calendar = [day.strftime("%Y-%m-%d") for day in (DATES[0], DATES[2], DATES[3])]

    assert battle._first_session_after(DATES[0], calendar) == DATES[2].strftime("%Y-%m-%d")
    assert battle._post_cutoff_candidate_entry_count([
        {"entry_execution_date": DATES[2].strftime("%Y-%m-%d")},
        {"entry_execution_date": DATES[3].strftime("%Y-%m-%d")},
    ]) == 1
