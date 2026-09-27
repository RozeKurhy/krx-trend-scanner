import pandas as pd
import pytest

from scripts import run_exit4_t10_realistic_portfolio_v02 as runner


def _ledger_row(**updates):
    row = {
        "ticker": "000001",
        "trade_id": "000001_01",
        "trade_sequence": 1,
        "entry_signal_date": "2024-01-02",
        "entry_execution_date": "2024-01-03",
        "entry_pattern_a_stage": "A_FAST",
        "entry_open": 1000.0,
        "entry_market_cap": 2_000_000_000_000.0,
        "market": "KOSPI",
        "isu_cd": "KR7000000001",
        "identity_effective_from": "1990-01-01",
        "identity_effective_to": "2099-12-31",
        "pair_id": "pair-1",
        "strategy_id": runner.T15_STRATEGY_ID,
        "exit_type": "EXIT4_SCORE_DRAWDOWN_GE_15",
        "exit_signal_date": "2024-03-01",
        "exit_execution_date": "2024-03-04",
        "exit_price": 1100.0,
        "terminal_return": 10.0,
        "mfe": 20.0,
        "mae": -5.0,
        "peak_giveback": 10.0,
        "holding_days": 40,
        "holding_weeks": 8.0,
        "profit_capture": 0.5,
        "trade_status": "REALIZED",
        "terminal_valuation_date": None,
        "terminal_valuation_price": None,
        "terminal_valuation_source": None,
        "terminal_valuation_at_cutoff": None,
        "loss_guard_triggered": False,
        "loss_guard_signal_date": None,
    }
    row.update(updates)
    return row


def test_validate_t15_alignment_handles_tuple_trade_keys():
    source = pd.DataFrame([_ledger_row()])
    path = pd.DataFrame(
        [
            {
                "ticker": "000001",
                "trade_id": "000001_01",
                "entry_signal_date": "2024-01-02",
                "t15_exit_type": "EXIT4_SCORE_DRAWDOWN_GE_15",
                "t15_signal_label": "2024-03-01",
                "t15_exit_date": "2024-03-04",
                "t15_exit_price": 1100.0,
                "t15_terminal_return": 10.0,
                "t15_mfe": 20.0,
                "t15_mae": -5.0,
                "t15_holding_days": 40,
            }
        ]
    )

    result = runner.validate_t15_alignment(source, path)

    assert result["status"] == "PASS"
    assert result["matched_t15_trade_count"] == 1


def test_exit_only_parity_allows_exit_outcomes_but_rejects_other_rule_changes():
    control = pd.DataFrame([_ledger_row()])
    candidate = control.copy()
    candidate.loc[0, "strategy_id"] = runner.T10_STRATEGY_ID
    candidate.loc[0, "exit_type"] = runner.T10_EXIT4_TYPE
    candidate.loc[0, "exit_execution_date"] = "2024-02-20"

    result = runner.validate_exit_only_parity(control, candidate)

    assert result["status"] == "PASS"
    candidate.loc[0, "loss_guard_triggered"] = True
    with pytest.raises(RuntimeError, match="NON_EXIT_FIELDS_CHANGED:loss_guard_triggered"):
        runner.validate_exit_only_parity(control, candidate)


def test_build_t10_ledger_changes_exit_path_and_preserves_entry():
    control = pd.DataFrame([_ledger_row()])
    path = pd.DataFrame(
        [
            {
                "ticker": "000001",
                "trade_id": "000001_01",
                "entry_signal_date": "2024-01-02",
                "t10_exit_type": "EXIT4_SCORE_DRAWDOWN_GE_10",
                "t10_signal_label": "2024-02-15",
                "t10_exit_date": "2024-02-16",
                "t10_exit_price": 1150.0,
                "t10_terminal_return": 15.0,
                "t10_mfe": 20.0,
                "t10_mae": -5.0,
                "t10_giveback": 5.0,
                "t10_holding_days": 30,
                "t10_score_drop_at_signal": 10.5,
            }
        ]
    )

    result = runner.build_t10_ledger(control, path, frames={}, effective_end=pd.Timestamp("2024-12-31"))

    assert result.loc[0, "strategy_id"] == runner.T10_STRATEGY_ID
    assert result.loc[0, "exit_type"] == runner.T10_EXIT4_TYPE
    assert result.loc[0, "exit_execution_date"] == "2024-02-16"
    assert result.loc[0, "entry_execution_date"] == control.loc[0, "entry_execution_date"]
    assert runner.validate_entry_parity(control, result)["status"] == "PASS"
    assert runner.validate_exit_only_parity(control, result)["status"] == "PASS"


@pytest.mark.parametrize(
    ("exit_type", "expected"),
    [
        ("EXIT4_SCORE_DRAWDOWN_GE_10", "Exit4"),
        ("EXIT3_PROGRESSED_TO_WEAK", "Exit3"),
        ("LOSS_GUARD_CLOSE_LE_NEG_15", "Loss Guard"),
        ("NO_EXIT_BEFORE_CUTOFF", "No exit"),
    ],
)
def test_exit_classification(exit_type, expected):
    assert runner._classify_exit(exit_type) == expected


def test_verdict_uses_paired_tail_summary():
    details = pd.DataFrame(
        [{"closed": True, "net_realized_return_pct": 5.0, "net_realized_pnl_krw": 100_000.0}]
    )
    result = {
        "window_id": "P2-1",
        "t15_replay": {"metrics": {"final_equity": 200_000_000, "CAGR_pct": 0.0, "mdd_pct": -10.0}},
        "t10_replay": {"metrics": {"final_equity": 199_000_000, "CAGR_pct": -0.1, "mdd_pct": -10.1}},
        "t15_details": details,
        "t10_details": details,
        "tail_summary": {
            "t15_le_neg_30_count": 1,
            "t10_le_neg_30_count": 1,
            "t15_le_neg_50_count": 0,
            "t10_le_neg_50_count": 0,
        },
        "rotation": {"t10_only_fills_net_realized_pnl_krw": 0},
    }

    verdict, summary = runner._verdict([result])

    assert verdict == "T15_REMAINS_PREFERRED"
    assert summary["account_improved_windows"] == 0


def test_sparse_entry_open_fallback_requires_cash_skip():
    replay = {
        "events": [
            {"event_type": "ENTRY", "event_status": "SKIPPED_CASH_UNAVAILABLE", "ticker": "336570"},
            {"event_type": "EXIT", "event_status": "SKIPPED_NO_EXECUTED_POSITION", "ticker": "336570"},
        ]
    }
    result = runner._validate_sparse_fallback_nonfill(replay, ["336570"], "T10", "P2-2")
    assert result["status"] == "PASS"
    assert result["cash_skip_entries"] == 1
    replay["events"][0]["event_status"] = "UNRESOLVED"
    with pytest.raises(RuntimeError, match="SPARSE_FALLBACK_NOT_CASH_SKIPPED"):
        runner._validate_sparse_fallback_nonfill(replay, ["336570"], "T10", "P2-2")
