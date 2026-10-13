from __future__ import annotations

from trend_scanner.reporting.models import AFastCoreSection, AFastCoreTradeHistoryItem, StockReport


def _stock_report(core: AFastCoreSection) -> StockReport:
    return StockReport(
        report_version="0.7",
        ticker="000001",
        name="fixture",
        market="KOSPI",
        requested_as_of="2025-01-20",
        reference_market_date="2025-01-20",
        header=None,  # type: ignore[arg-type]
        summary=None,  # type: ignore[arg-type]
        current_snapshot=None,  # type: ignore[arg-type]
        monthly_history=None,  # type: ignore[arg-type]
        foreign_flow=None,  # type: ignore[arg-type]
        relative_strength=None,  # type: ignore[arg-type]
        sector_relative_strength=None,  # type: ignore[arg-type]
        trading_value_flow=None,  # type: ignore[arg-type]
        data_quality=None,  # type: ignore[arg-type]
        provenance=None,  # type: ignore[arg-type]
        pattern_a_fast=None,  # type: ignore[arg-type]
        a_fast_core=core,
    )


def _trade() -> AFastCoreTradeHistoryItem:
    return AFastCoreTradeHistoryItem(
        trade_id="000001_01",
        trade_sequence=1,
        entry_signal_date="2025-01-05",
        entry_execution_date="2025-01-06",
        entry_open=100.0,
        entry_pattern_a_stage="EARLY_TREND",
        exit_type="TEST_EXIT",
        exit_signal_date="2025-01-08",
        exit_execution_date="2025-01-09",
        exit_price=105.0,
        trade_status="REALIZED",
        return_pct=5.0,
        strategy_id="PATTERN_A_FAST_FINAL_STRATEGY_V02_ALIGNMENT_MCAP_500B",
        entry_strategy_id="PATTERN_A_FAST_FINAL_STRATEGY_V02_ALIGNMENT_MCAP_500B",
        exit_strategy_id="PATTERN_A_FAST_FINAL_STRATEGY_V02_ALIGNMENT_MCAP_500B",
    )


def test_rolled_back_report_retains_immutable_mixed_lineage():
    core = AFastCoreSection(
        strategy_id="PATTERN_A_FAST_FINAL_STRATEGY_V02",
        activation_intervals=[{
            "activation_id": "fixture-activation-001",
            "effective_signal_date": "2025-01-01",
            "rollback_effective_signal_date": "2025-01-10",
        }],
        trade_history=[_trade()],
    )

    payload = _stock_report(core).to_dict()["a_fast_core"]

    assert payload["strategy_id"] == "PATTERN_A_FAST_FINAL_STRATEGY_V02"
    assert payload["activation_intervals"][0]["rollback_effective_signal_date"] == "2025-01-10"
    trade = payload["trade_history"][0]
    assert trade["trade_id"] == "000001_01"
    assert trade["strategy_id"] == "PATTERN_A_FAST_FINAL_STRATEGY_V02_ALIGNMENT_MCAP_500B"
    assert trade["entry_strategy_id"] == trade["exit_strategy_id"] == trade["strategy_id"]


def test_v2_without_activation_history_keeps_legacy_serialization():
    core = AFastCoreSection(
        strategy_id="PATTERN_A_FAST_FINAL_STRATEGY_V02",
        trade_history=[_trade()],
    )

    payload = _stock_report(core).to_dict()["a_fast_core"]

    assert "activation_intervals" not in payload
    assert "strategy_id" not in payload["trade_history"][0]
