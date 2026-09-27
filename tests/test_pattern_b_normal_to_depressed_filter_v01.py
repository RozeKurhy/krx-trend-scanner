from __future__ import annotations

import pandas as pd
import pytest

from scripts import run_pattern_b_normal_to_depressed_filter_v01 as runner


IDENTITY = ("000001", "KR7000000001")
COMPONENT = "000001:KR7000000001:000"


def _event(date: str, previous_date: str, previous_state: str) -> dict:
    return {
        "signal_id": f"{IDENTITY[0]}_{IDENTITY[1]}_{date}",
        "ticker": IDENTITY[0],
        "isu_cd": IDENTITY[1],
        "entry_signal_date": date,
        "previous_state_date": previous_date,
        "previous_state": previous_state,
        "entry_signal_state": "DEPRESSED",
        "market_at_signal": "KOSPI",
        "component_id": COMPONENT,
        "entry_signal_status": "PENDING",
        "trade_id": None,
        "entry_execution_date": None,
        "entry_reference_open": None,
        "status_reason": None,
    }


def _observation(date: str, state: str) -> dict:
    return {
        "ticker": IDENTITY[0],
        "isu_cd": IDENTITY[1],
        "snapshot_date": date,
        "state": state,
        "component_id": COMPONENT,
        "market": "KOSPI",
    }


def test_partition_preserves_raw_candidates_and_admits_only_normal_transition() -> None:
    signals = {
        IDENTITY: [
            _event("2020-01-31", "2019-12-31", "NORMAL"),
            _event("2020-02-28", "2020-01-31", "DEEP_DEPRESSED"),
            _event("2020-04-30", "2020-02-28", "NORMAL"),
        ]
    }

    audit, admitted = runner._partition_candidates(signals)

    assert len(audit) == 3
    assert [row["entry_signal_date"] for row in admitted[IDENTITY]] == ["2020-01-31"]
    assert audit[0]["entry_filter_status"] == "PASS_NORMAL_TO_DEPRESSED"
    assert audit[1]["entry_signal_status"] == runner.FILTERED_STATUS
    assert audit[2]["entry_filter_status"] == runner.FILTERED_STATUS


def test_independent_state_machine_receives_only_admitted_events() -> None:
    deep_event = _event("2019-11-29", "2019-10-31", "DEEP_DEPRESSED")
    normal_event = _event("2020-01-31", "2019-12-31", "NORMAL")
    observations = [
        _observation("2019-10-31", "DEEP_DEPRESSED"),
        _observation("2019-11-29", "DEPRESSED"),
        _observation("2019-12-31", "NORMAL"),
        _observation("2020-01-31", "DEPRESSED"),
        _observation("2020-02-28", "NORMAL"),
    ]
    audit, admitted = runner._partition_candidates({IDENTITY: [deep_event, normal_event]})
    daily = pd.DataFrame(
        [
            {"open": 100.0, "high": 105.0, "low": 95.0, "close": 101.0, "market": "KOSPI"},
            {"open": 110.0, "high": 112.0, "low": 108.0, "close": 111.0, "market": "KOSPI"},
        ],
        index=pd.Index(["2020-02-03", "2020-03-02"]),
    )

    trades, _state = runner._replay_identity_state_machine(
        observations, admitted[IDENTITY], {COMPONENT: daily}, "2020-03-02"
    )

    assert len(audit) == 2
    assert len(admitted[IDENTITY]) == 1
    assert len(trades) == 1
    assert trades[0]["entry_signal_date"] == "2020-01-31"
    assert trades[0]["trade_status"] == "REALIZED"


def test_same_isu_overlap_is_rejected_across_ticker_codes() -> None:
    trades = [
        {
            "trade_id": "first",
            "ticker": "000001",
            "isu_cd": "KR7000000001",
            "entry_execution_date": "2024-01-02",
            "exit_execution_date": "2024-02-01",
        },
        {
            "trade_id": "second",
            "ticker": "000002",
            "isu_cd": "KR7000000001",
            "entry_execution_date": "2024-02-01",
            "exit_execution_date": "2024-03-01",
        },
    ]

    with pytest.raises(RuntimeError, match="identical ISU"):
        runner._check_no_overlapping_isu_positions(trades, "2024-12-31")


def test_annual_comparison_counts_metric_specific_improvement() -> None:
    control_events = [{"entry_signal_date": "2024-01-31", "entry_signal_status": "FILLED"}]
    control_trades = [{
        "entry_signal_date": "2024-01-31",
        "trade_status": "REALIZED",
        "gross_return_pct": 5.0,
    }]
    test_events = [{
        "entry_signal_date": "2024-01-31",
        "entry_signal_status": "FILLED",
        "entry_filter_status": "PASS_NORMAL_TO_DEPRESSED",
    }]
    test_trades = [{
        "entry_signal_date": "2024-01-31",
        "trade_status": "REALIZED",
        "gross_return_pct": 10.0,
    }]

    annual, improvements = runner._annual_summary(
        control_events, control_trades, test_events, test_trades
    )

    assert annual.iloc[0]["median_return_direction"] == "TEST_BETTER"
    assert improvements["median_return"]["years_test_improved"] == 1
    assert improvements["median_return"]["years_comparable"] == 1


def test_normal_slice_replay_parity_is_a_post_replay_audit() -> None:
    trade = {
        "ticker": IDENTITY[0],
        "isu_cd": IDENTITY[1],
        "entry_signal_date": "2020-01-31",
        "entry_previous_state": "NORMAL",
        "entry_execution_date": "2020-02-03",
        "exit_signal_date": "2020-03-31",
        "exit_execution_date": "2020-04-01",
        "trade_status": "REALIZED",
        "entry_reference_open": 100.0,
        "exit_reference_open": 110.0,
        "gross_return_pct": 10.0,
        "commission_slippage_pre_tax_return_pct": 9.7,
        "full_standard_net_return_pct": 9.0,
        "mfe_pct": 15.0,
        "mae_pct": -3.0,
        "holding_krx_sessions": 42,
        "cutoff_close": None,
        "mark_to_cutoff_gross_return_pct": None,
        "valuation_status": None,
    }

    parity = runner._normal_slice_control_replay_parity([trade], [dict(trade)])
    assert parity["parity_pass"] is True
    assert parity["signal_key_match_count"] == 1
    assert parity["trade_field_mismatch_count"] == 0
    assert "not used as TEST inputs" in parity["construction_method"]

    changed_test_trade = {**trade, "gross_return_pct": 10.1}
    mismatched = runner._normal_slice_control_replay_parity([trade], [changed_test_trade])
    assert mismatched["parity_pass"] is False
    assert mismatched["trade_field_mismatch_count"] == 1
