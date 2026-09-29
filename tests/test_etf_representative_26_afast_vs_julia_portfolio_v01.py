from __future__ import annotations

import pandas as pd

from scripts import run_etf_representative_26_afast_vs_julia_portfolio_v01 as study


def test_fixed_universe_is_exactly_26_with_declared_groups_and_explicit_140710() -> None:
    universe = study._load_universe()

    assert len(universe) == 26
    assert {row["ticker"] for row in universe} == study._fixed_ticker_set()
    assert {category: len(tickers) for category, tickers in study.UNIVERSE_GROUPS.items()} == {
        "MARKET_DOMESTIC": 2,
        "SECTOR_DOMESTIC": 16,
        "FOREIGN_MARKET": 4,
        "COMMODITY_RESOURCE": 4,
    }
    assert "140710" in {row["ticker"] for row in universe}
    assert "경기소비재" not in " ".join(row["name"] for row in universe)


def test_initial_deployment_ceiling_is_65_percent() -> None:
    ceiling = study._theoretical_initial_deployment_ceiling()

    assert ceiling["notional_krw"] == 130_000_000
    assert ceiling["pct"] == 65.0


def test_recent_listing_is_normal_not_evaluable_only_with_known_readiness_reason() -> None:
    assert study._normal_non_evaluable({
        "status": "NOT_EVALUABLE",
        "reason": "LESS_THAN_TWO_YEARS_LISTED_AT_CUTOFF;COMMON_START_AFTER_CUTOFF",
        "errors": [],
    })
    assert not study._normal_non_evaluable({
        "status": "NOT_EVALUABLE", "reason": "RAW_SESSION_GAP", "errors": [],
    })
    assert not study._normal_non_evaluable({
        "status": "NOT_EVALUABLE", "reason": "LESS_THAN_TWO_YEARS_LISTED_AT_CUTOFF",
        "errors": ["RAW_SESSION_GAP:1"],
    })


def test_group_contribution_covers_the_four_fixed_universe_groups() -> None:
    ledger = pd.DataFrame([
        {"category": "MARKET_DOMESTIC", "entry_status": "FILLED", "exit_status": "FILLED", "realized_net_return_pct": 12.0, "realized_pnl_krw": 100.0},
        {"category": "FOREIGN_MARKET", "entry_status": "CASH_SKIP", "exit_status": "NOT_CLOSED", "realized_net_return_pct": None, "realized_pnl_krw": None},
    ])

    rows = study._group_contribution(study.STRATEGIES[0], ledger)

    assert [row["category"] for row in rows] == list(study.GROUP_ORDER)
    assert rows[0]["realized_trades"] == 1
    assert rows[0]["realized_pnl_contribution_krw"] == 100.0
    assert rows[2]["candidate_trades"] == 1
