from scripts.replay_b_select_daily_normal_exit_cadence_v01 import (
    _feature_boundary_sessions,
    _interior_sessions,
    _mark_open_at_cutoff,
    _month_end_sessions,
    _next_executable_open,
    _next_exact_session,
    _rebase_entry_price,
    portfolio_v02,
)


def test_next_exact_session_is_strictly_after_signal_date():
    trading_dates = ["2024-03-28", "2024-03-29", "2024-04-01"]

    assert _next_exact_session(trading_dates, "2024-03-28") == "2024-03-29"
    assert _next_exact_session(trading_dates, "2024-03-29") == "2024-04-01"
    assert _next_exact_session(trading_dates, "2024-03-31") == "2024-04-01"
    assert _next_exact_session(trading_dates, "2024-04-01") is None


def test_month_end_sessions_use_last_exact_krx_session_per_month():
    trading_dates = ["2024-03-28", "2024-03-29", "2024-04-01", "2024-04-02"]

    assert _month_end_sessions(trading_dates, "2024-03-01", "2024-04-30") == [
        "2024-03-29",
        "2024-04-02",
    ]


def test_feature_boundaries_project_weekly_and_monthly_labels_to_next_session():
    # March 29 is an exchange holiday. Both the Friday weekly label and the
    # Sunday month-end monthly label first become observable on April 1.
    trading_dates = ["2024-03-28", "2024-04-01", "2024-04-05"]

    assert _feature_boundary_sessions(trading_dates, "2024-03-28", "2024-04-05") == [
        "2024-04-01",
        "2024-04-05",
    ]


def test_piecewise_spot_checks_exclude_feature_boundary_sessions():
    trading_dates = [
        "2024-04-01",
        "2024-04-02",
        "2024-04-03",
        "2024-04-04",
        "2024-04-05",
    ]

    assert _interior_sessions(
        trading_dates,
        "2024-04-01",
        "2024-04-06",
        ["2024-04-02", "2024-04-04"],
    ) == ["2024-04-03", "2024-04-05"]


def test_entry_price_rebase_preserves_source_and_uses_current_authority():
    source = {"trade_id": "T1", "entry_reference_open": 1322.0, "entry_price": 1322.0}

    row, rebased = _rebase_entry_price(source, 13220.0)

    assert rebased is True
    assert source["entry_reference_open"] == 1322.0
    assert row["source_entry_reference_open"] == 1322.0
    assert row["entry_reference_open"] == 13220.0
    assert row["entry_price"] == 13220.0


def test_open_at_cutoff_clears_stale_source_exit_fields(monkeypatch):
    monkeypatch.setattr(
        portfolio_v02.portfolio,
        "_price",
        lambda row, frames, day, field: 125.0 if field == "close" else None,
    )
    source = {
        "trade_id": "T2",
        "trade_status": "OPEN_AT_CUTOFF",
        "exit_execution_date": float("nan"),
        "exit_reference_open": float("nan"),
        "gross_return_pct": -12.0,
        "commission_slippage_pre_tax_return_pct": -13.0,
        "full_standard_net_return_pct": -14.0,
        "sell_tax_rate": 0.2,
    }

    row, audit = _mark_open_at_cutoff(source, {}, "2024-03-29")

    assert row["trade_status"] == "OPEN_AT_CUTOFF"
    assert row["exit_execution_date"] is None
    assert row["exit_reference_open"] is None
    assert row["gross_return_pct"] is None
    assert row["commission_slippage_pre_tax_return_pct"] is None
    assert row["full_standard_net_return_pct"] is None
    assert row["sell_tax_rate"] is None
    assert row["cutoff_close"] == 125.0
    assert audit["execution_status"] == "OPEN_AT_CUTOFF"


def test_exit_fill_uses_first_session_with_valid_authoritative_open(monkeypatch):
    prices = {"2026-05-04": None, "2026-05-06": 5240.0}
    monkeypatch.setattr(
        portfolio_v02.portfolio,
        "_price",
        lambda row, frames, day, field: prices.get(day.strftime("%Y-%m-%d")) if field == "open" else None,
    )

    day, price, unavailable = _next_executable_open(
        {"ticker": "096630"},
        {},
        ["2026-04-30", "2026-05-04", "2026-05-06"],
        "2026-04-30",
        "2026-05-06",
    )

    assert day == "2026-05-06"
    assert price == 5240.0
    assert unavailable == ["2026-05-04"]
