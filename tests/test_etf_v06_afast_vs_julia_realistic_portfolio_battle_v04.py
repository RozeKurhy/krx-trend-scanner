from __future__ import annotations

import json

from scripts import run_etf_v06_afast_vs_julia_realistic_portfolio_battle_v03 as battle
from scripts import validate_etf_v06_afast_vs_julia_realistic_portfolio_battle_v03_v04 as validator


def _trade(
    ticker: str,
    signal: str,
    entry: str,
    exit_date: str,
    canonical_id: str,
) -> dict[str, object]:
    return {
        "strategy_id": battle.STRATEGY_A_FAST,
        "ticker": ticker,
        "ISU_CD": f"KR{ticker}",
        "signal_date": signal,
        "entry_execution_date": entry,
        "entry_price_raw_open": 100.0,
        "exit_signal_date": exit_date,
        "exit_execution_date": exit_date,
        "exit_price_raw_open": 90.0,
        "exit_or_terminal_date": exit_date,
        "terminal_price_raw": 90.0,
        "trade_status": "REALIZED",
        "exit_reason": "TEST_EXIT",
        "holding_krx_sessions_inclusive": 2,
        "source_signal_details": {"canonical_trade_id": canonical_id},
    }


def test_pre_v06_window_only_is_allowed() -> None:
    result = battle._classify_group_b_divergence(
        [], [_trade("266360", "2020-02-28", "2020-03-02", "2020-03-20", "266360_01")],
        "2020-02-28", "2020-03-31",
    )

    assert result["divergence_class"] == "PRE_V06_WINDOW_ONLY"
    assert result["evidence"]["pre_v06_window_trade_count"] == 1


def test_lifecycle_carryover_is_allowed() -> None:
    result = battle._classify_group_b_divergence(
        [], [_trade("000001", "2020-02-28", "2020-03-02", "2020-04-02", "000001_01")],
        "2020-02-28", "2020-03-31",
    )

    assert result["divergence_class"] == "LIFECYCLE_CARRYOVER"
    assert result["evidence"]["carryover_trade_count"] == 1


def test_lifecycle_carryover_entry_on_v06_start_is_allowed() -> None:
    result = battle._classify_group_b_divergence(
        [], [_trade("280930", "2020-11-27", "2020-11-30", "2021-08-02", "280930_01")],
        "2020-02-28", "2020-11-30",
    )

    assert result["divergence_class"] == "LIFECYCLE_CARRYOVER"


def test_post_v06_unexplained_divergence_is_blocking() -> None:
    result = battle._classify_group_b_divergence(
        [], [_trade("000001", "2020-04-01", "2020-04-02", "2020-04-15", "000001_01")],
        "2020-02-28", "2020-03-31",
    )

    assert result["divergence_class"] == "POST_V06_UNEXPLAINED_DIVERGENCE"


def test_group_a_exact_parity_includes_canonical_trade_id() -> None:
    original = _trade("192090", "2020-02-03", "2020-02-04", "2020-02-10", "192090_01")
    candidate_csv_row = {
        **original,
        "source_signal_details": json.dumps(json.dumps(original["source_signal_details"])),
        "canonical_trade_id": "192090_01",
    }
    normalized = validator._normalize_candidate_rows([candidate_csv_row])

    comparison = battle._path_comparison([original], normalized, exact=True)
    assert comparison["pass"] is True


def test_266360_is_pre_v06_window_only() -> None:
    result = battle._classify_group_b_divergence(
        [], [_trade("266360", "2020-02-28", "2020-03-02", "2020-03-20", "266360_01")],
        "2020-02-28", "2020-03-31",
    )
    assert result["divergence_class"] == "PRE_V06_WINDOW_ONLY"


def test_266370_is_pre_v06_window_only() -> None:
    result = battle._classify_group_b_divergence(
        [], [_trade("266370", "2020-03-06", "2020-03-09", "2020-03-18", "266370_01")],
        "2020-02-28", "2020-03-31",
    )
    assert result["divergence_class"] == "PRE_V06_WINDOW_ONLY"
