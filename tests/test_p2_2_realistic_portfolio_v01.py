import pandas as pd

from scripts import run_p2_2_realistic_portfolio_v01 as p2_2
from scripts import run_p2_1_realistic_portfolio_v01 as portfolio


def test_p2_2_uses_frozen_window_and_separate_output_namespace():
    assert p2_2.CALENDAR_START == "2021-01-01"
    assert p2_2.CALENDAR_END == "2026-08-31"
    assert p2_2.RUN_ID.startswith("run_20260926_")
    assert "p2_2_neg40_weak_protect_v01" in str(p2_2.OUT_DIR)
    assert p2_2.WORKERS == 10


def test_p2_2_sell_tax_uses_execution_date_historical_schedule():
    cases = (
        ("2021-06-01", 0.0023),
        ("2023-06-01", 0.0020),
        ("2024-06-01", 0.0018),
        ("2025-06-01", 0.0015),
        ("2026-06-01", 0.0020),
    )
    for day, expected in cases:
        assert portfolio._tax_rate(pd.Timestamp(day), "KOSPI") == expected
        assert portfolio._tax_rate(pd.Timestamp(day), "KOSDAQ") == expected


def test_p2_1_comparison_table_compares_candidate_to_candidate():
    keys = (
        "final_equity", "cumulative_return_pct", "CAGR_pct", "mdd_pct", "trade_count",
        "win_rate_pct", "average_holding_trading_days", "median_holding_trading_days",
        "average_concurrent_positions", "maximum_concurrent_positions",
        "average_capital_utilization_pct", "maximum_capital_utilization_pct",
        "average_cash_ratio_pct", "turnover_multiple", "total_commissions_krw",
        "total_sell_tax_krw", "slippage_impact_krw", "cash_shortage_skipped_entries",
        "open_at_effective_cutoff_count", "realized_return_le_neg_30_count",
        "realized_return_le_neg_40_count", "realized_return_le_neg_50_count",
        "realized_return_le_neg_60_count", "realized_return_ge_pos_50_count",
        "realized_return_ge_pos_100_count",
    )
    control = {key: 1 for key in keys}
    candidate = {key: 1 for key in keys}
    candidate["cumulative_return_pct"] = 20.0
    p2_1_candidate = {key: 1 for key in keys}
    p2_1_candidate["cumulative_return_pct"] = 15.0
    summary = {
        "status": "P2_2_REALISTIC_PORTFOLIO_BACKTEST_CERTIFIED",
        "window": {"effective_start": "2021-01-04", "effective_end": "2026-08-31", "execution_support": "2026-09-01"},
        "universe": {"latest_daily_update_as_of": "2026-09-21"},
        "portfolio": {
            "control": control,
            "candidate": candidate,
            "candidate_minus_control": {key: 0 for key in keys},
        },
        "p2_1_comparison": {"candidate": p2_1_candidate},
    }

    report = p2_2._comparison_report(summary)

    assert "| 지표 | P2-1 인증 Candidate | P2-2 Candidate | P2-2 − P2-1 |" in report
    assert "| 누적수익률 (%) | 15.0 | 20.0 | 5.0 |" in report
