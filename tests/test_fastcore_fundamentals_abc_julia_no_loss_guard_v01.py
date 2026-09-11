from types import SimpleNamespace
import hashlib
import json
import socket

import pandas as pd
import pytest

from scripts import run_fastcore_fundamentals_abc_julia_no_loss_guard_v01 as runner
from scripts import run_fastcore_fundamentals_abc_v01 as base
from scripts.run_fastcore_control import validate_frozen_inputs


def _record(**overrides):
    values = {
        "ticker": "000001",
        "isu_cd": "KR7000000001",
        "market": "KOSPI",
        "name": "Fixture",
        "trade_id": "trade-1",
        "trade_sequence": 1,
        "entry_signal_date": "2022-01-07",
        "entry_execution_date": "2022-01-10",
        "entry_open": 100.0,
        "entry_fundamentals_gate_pass": True,
        "entry_signal_information_date": "2022-01-07",
        "terminal_return": 1.0,
        "mfe": 10.0,
        "mae": -5.0,
        "holding_trading_days": 10,
        "trade_status": "REALIZED",
        "loss_guard_triggered": False,
        "exit_type": "EXIT3_PROGRESSED_TO_WEAK",
        "exit_execution_date": "2022-02-01",
        "fundamental_exit_triggered": False,
        "fundamental_exit_accelerated": False,
        "fundamental_exit_all_flags": "",
        "fundamental_exit_primary_type": None,
        "first_progressed_effective_trading_date": None,
    }
    values.update(overrides)
    return pd.DataFrame([values])


def _daily(closes, opens=None):
    dates = pd.date_range("2022-01-10", periods=len(closes), freq="B")
    if opens is None:
        opens = closes
    return pd.DataFrame(
        {
            "open": opens,
            "high": [max(c, o) for c, o in zip(closes, opens)],
            "low": [min(c, o) for c, o in zip(closes, opens)],
            "close": closes,
        },
        index=dates,
    )


def test_strategy_contract_is_exactly_no_loss_guard():
    assert runner.STRATEGY_ID.endswith("ABC_JULIA_NO_LOSS_GUARD_V01")
    assert runner.SHORT_STRATEGY_ID == "ABC_JULIA_NO_LOSS_GUARD_V01"
    assert runner.PRIMARY_LOSS_GUARD == "LOSS_GUARD_CLOSE_LE_NEG_15"


def test_frozen_entry_authority_has_expected_rows_and_pass_count():
    candidates = validate_frozen_inputs()
    authority, evaluations = runner.load_entry_authority(candidates)
    assert len(authority) == 9754
    assert len(evaluations) == 1763


def test_frozen_entry_authority_classification_counts_are_fixed():
    candidates = validate_frozen_inputs()
    authority, _ = runner.load_entry_authority(candidates)
    counts = authority["classification"].value_counts().to_dict()
    assert counts["ABC_ENTRY_PASS"] == 1763
    assert counts["ABC_ENTRY_FAIL_RULE"] == 3002
    assert counts["TRUE_DATA_UNAVAILABLE"] == 3854
    assert counts["FINANCIAL_UNSUPPORTED"] == 1135


def test_entry_authority_pass_is_identical_to_classification():
    candidates = validate_frozen_inputs()
    authority, _ = runner.load_entry_authority(candidates)
    assert (authority["abc_entry_pass"].map(runner._truth) == authority["classification"].eq("ABC_ENTRY_PASS")).all()


def test_entry_evaluation_rehydrates_authority_without_recalculating_gate():
    candidates = validate_frozen_inputs()
    authority, evaluations = runner.load_entry_authority(candidates)
    row = authority[authority["classification"].eq("ABC_ENTRY_PASS")].iloc[0]
    evaluation = evaluations[str(row["candidate_id"])]
    assert evaluation.abc_entry_gate_pass is True
    assert evaluation.company_family == "NON_FINANCIAL"
    assert evaluation.as_of == row["entry_signal_information_date"]


def test_simulate_no_loss_guard_forces_false(monkeypatch):
    captured = {}

    def fake_engine(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(runner, "simulate_ticker_strategy_fundamentals_v01", fake_engine)
    assert runner.simulate_no_loss_guard(loss_guard_enabled=True) == []
    assert captured["loss_guard_enabled"] is False


def test_counterfactual_guard_records_crossing_and_next_open():
    record = SimpleNamespace(
        entry_execution_date="2022-01-10",
        entry_open=100.0,
        first_progressed_effective_trading_date=None,
    )
    daily = _daily([100.0, 90.0, 80.0, 82.0], opens=[100.0, 89.0, 81.0, 83.0])
    result = runner._counterfactual_guard(record, daily)
    assert result["counterfactual_loss_guard_triggered"] is True
    assert result["counterfactual_loss_guard_signal_date"] == "2022-01-12"
    assert result["counterfactual_loss_guard_execution_date"] == "2022-01-13"
    assert result["counterfactual_loss_guard_execution_price"] == 83.0


def test_counterfactual_guard_does_not_trigger_above_threshold():
    record = SimpleNamespace(
        entry_execution_date="2022-01-10",
        entry_open=100.0,
        first_progressed_effective_trading_date=None,
    )
    result = runner._counterfactual_guard(record, _daily([100.0, 86.0]))
    assert result["counterfactual_loss_guard_triggered"] is False
    assert result["counterfactual_loss_guard_signal_date"] is None


def test_counterfactual_guard_respects_first_progressed_boundary():
    record = SimpleNamespace(
        entry_execution_date="2022-01-10",
        entry_open=100.0,
        first_progressed_effective_trading_date="2022-01-12",
    )
    result = runner._counterfactual_guard(record, _daily([100.0, 100.0, 80.0]))
    assert result["counterfactual_loss_guard_triggered"] is False


def test_decorated_frame_keeps_disabled_guard_diagnostic_separate():
    frame = _record(terminal_return=-22.0)
    decorated = runner._decorate_trade_frame(frame, {"trade-1": {
        "counterfactual_loss_guard_triggered": True,
        "counterfactual_loss_guard_signal_date": "2022-01-20",
    }})
    assert bool(decorated.iloc[0]["loss_guard_triggered"]) is False
    assert bool(decorated.iloc[0]["counterfactual_loss_guard_triggered"]) is True
    assert decorated.iloc[0]["exit_type"] != runner.PRIMARY_LOSS_GUARD


def test_extended_metrics_include_deep_loss_tails_and_large_winners():
    frame = pd.concat([
        _record(terminal_return=-61.0),
        _record(trade_id="trade-2", terminal_return=201.0),
    ], ignore_index=True)
    frame = runner._decorate_trade_frame(frame, {})
    metrics = runner._extended_metrics(frame)
    assert metrics["tail_counts"]["terminal_return_le_neg_60_pct_points"] == 1
    assert metrics["winner_counts"]["terminal_return_ge_pos_200_pct_points"] == 1


def test_extended_metrics_count_exit3_and_exit4_separately():
    frame = pd.concat([
        _record(exit_type="EXIT3_PROGRESSED_TO_WEAK"),
        _record(trade_id="trade-2", exit_type="EXIT4_SCORE_DRAWDOWN_GE_15"),
    ], ignore_index=True)
    frame = runner._decorate_trade_frame(frame, {})
    metrics = runner._extended_metrics(frame)
    assert metrics["exit3_count"] == 1
    assert metrics["exit4_count"] == 1


def test_extended_metrics_count_fundamental_a_b_c_flags():
    frame = _record(
        fundamental_exit_all_flags="FUNDAMENTAL_A_OPERATING_LOSS|FUNDAMENTAL_B_SHARP_DECLINE|FUNDAMENTAL_C_TWO_CONSECUTIVE_DECLINES",
        fundamental_exit_primary_type="FUNDAMENTAL_A_OPERATING_LOSS",
        fundamental_exit_accelerated=True,
        exit_type="FUNDAMENTAL_A_OPERATING_LOSS",
    )
    frame = runner._decorate_trade_frame(frame, {})
    metrics = runner._extended_metrics(frame)
    assert metrics["fundamental_exit_a_count"] == 1
    assert metrics["fundamental_exit_b_count"] == 1
    assert metrics["fundamental_exit_c_count"] == 1
    assert metrics["fundamental_exit_accelerated_count"] == 1


def test_extended_metrics_count_no_exit_and_no_progressed():
    frame = pd.concat([
        _record(exit_type="NO_EXIT_BEFORE_CUTOFF", trade_id="trade-1"),
        _record(exit_type="NO_PROGRESSED_BEFORE_CUTOFF", trade_id="trade-2"),
    ], ignore_index=True)
    frame = runner._decorate_trade_frame(frame, {})
    metrics = runner._extended_metrics(frame)
    assert metrics["no_exit_count"] == 1
    assert metrics["no_progressed_count"] == 1


def test_comparison_delta_is_no_guard_minus_on():
    on = runner._decorate_trade_frame(_record(terminal_return=-10.0), {})
    off = runner._decorate_trade_frame(_record(terminal_return=20.0), {})
    comparison = runner._comparison(on, off)
    assert comparison["metric_table"]["mean_return"]["ABC_ON"] == -10.0
    assert comparison["metric_table"]["mean_return"]["ABC_NO_LOSS_GUARD"] == 20.0
    assert comparison["metric_table"]["mean_return"]["delta"] == 30.0


def test_counterfactual_pairs_by_entry_identity_not_sequence():
    baseline = _record(
        trade_id="baseline-7",
        trade_sequence=7,
        exit_type=runner.PRIMARY_LOSS_GUARD,
        terminal_return=-16.0,
    )
    experiment = _record(
        trade_id="experiment-1",
        trade_sequence=1,
        terminal_return=12.0,
        exit_type="EXIT3_PROGRESSED_TO_WEAK",
    )
    paired, summary = runner.build_counterfactual(baseline, experiment)
    assert len(paired) == 1
    assert paired.iloc[0]["paired_status"] == "PAIRED"
    assert paired.iloc[0]["no_loss_guard_trade_id"] == "experiment-1"
    assert summary["paired_count"] == 1


def test_counterfactual_leaves_different_entry_unpaired():
    baseline = _record(
        trade_id="baseline-7",
        exit_type=runner.PRIMARY_LOSS_GUARD,
        terminal_return=-16.0,
    )
    experiment = _record(ticker="000002", trade_id="experiment-1", terminal_return=12.0)
    paired, summary = runner.build_counterfactual(baseline, experiment)
    assert paired.iloc[0]["paired_status"].startswith("UNPAIRED")
    assert summary["unpaired_count"] == 1


def test_counterfactual_counts_recovery_and_return_direction():
    baseline = pd.concat([
        _record(trade_id="baseline-1", exit_type=runner.PRIMARY_LOSS_GUARD, terminal_return=-16.0),
        _record(trade_id="baseline-2", exit_type=runner.PRIMARY_LOSS_GUARD, entry_signal_date="2022-02-07", entry_execution_date="2022-02-08", terminal_return=-20.0),
    ], ignore_index=True)
    experiment = pd.concat([
        _record(trade_id="experiment-1", terminal_return=12.0),
        _record(trade_id="experiment-2", entry_signal_date="2022-02-07", entry_execution_date="2022-02-08", terminal_return=-25.0),
    ], ignore_index=True)
    _, summary = runner.build_counterfactual(baseline, experiment)
    assert summary["higher_return_count"] == 1
    assert summary["lower_return_count"] == 1
    assert summary["recovered_to_positive_count"] == 1


def test_same_open_helper_rejects_same_day_reentry():
    first = _record(trade_id="first", exit_execution_date="2022-02-01")
    second = _record(trade_id="second", trade_sequence=2, entry_execution_date="2022-02-01")
    frame = pd.concat([first, second], ignore_index=True)
    assert runner._same_open_violation(frame) == 1


def test_same_open_helper_allows_next_day_reentry():
    first = _record(trade_id="first", exit_execution_date="2022-02-01")
    second = _record(trade_id="second", trade_sequence=2, entry_execution_date="2022-02-02")
    frame = pd.concat([first, second], ignore_index=True)
    assert runner._same_open_violation(frame) == 0


def test_network_guard_blocks_socket_attempts():
    audit = base.NetworkAudit()
    with base.network_guard(audit):
        with pytest.raises(base.NetworkRequestBlocked):
            socket.socket().connect(("127.0.0.1", 1))
    assert audit.request_count == 1


def test_baseline_hash_constants_match_local_files():
    assert runner.BASELINE_SUMMARY_SHA == "ec06f43fb378974ebf76f58d21cc7c4490593fd752095d9e8e35beeb7ff9a728"
    assert hashlib.sha256(runner.BASELINE_TRADES_PATH.read_bytes()).hexdigest() == runner.BASELINE_TRADES_SHA
    assert hashlib.sha256(runner.BASELINE_SUMMARY_PATH.read_bytes()).hexdigest() == runner.BASELINE_SUMMARY_SHA


def test_baseline_readiness_is_zero_gap_and_authority_is_read_only():
    readiness = json.loads(runner.BASELINE_READINESS_PATH.read_text(encoding="utf-8"))
    assert readiness["status"] == "COMPLETE"
    assert readiness["final_return_network_calls"] == 0
    assert readiness["local_cache_miss_pending_opendart"] == 0
    assert runner.ENTRY_AUTHORITY_PATH != runner.TRADES_PATH


def test_no_signal_carry_is_represented_by_frozen_candidate_gate():
    candidates = validate_frozen_inputs()
    authority, _ = runner.load_entry_authority(candidates)
    failed = authority[~authority["abc_entry_pass"].map(runner._truth)]
    assert len(failed) == 7991
    assert not failed["classification"].eq("ABC_ENTRY_PASS").any()
