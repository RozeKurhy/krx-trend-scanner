from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


RUNNER_PATH = (
    Path(__file__).resolve().parents[1]
    / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_ma60_vs_bullish_alignment_5window_simple_backtest_v01/run_5window_simple_backtest.py"
)
SPEC = importlib.util.spec_from_file_location("fastcore_simple_backtest_runner_cleanup_fix_v01", RUNNER_PATH)
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RUNNER
SPEC.loader.exec_module(RUNNER)


def test_run_full_window_completes_cleanup_after_three_strategy_replays(monkeypatch, tmp_path):
    control = pd.DataFrame({"pair_id": ["control"]})
    ma60 = pd.DataFrame({"pair_id": ["ma60"]})
    alignment = pd.DataFrame({"pair_id": ["alignment"]})
    empty_audit = pd.DataFrame()

    monkeypatch.setattr(
        RUNNER,
        "context_for_window",
        lambda base_run, gate, survivors, window_id: (
            SimpleNamespace(segments_by_ticker={}),
            object(),
            {"window_id": window_id},
        ),
    )
    monkeypatch.setattr(RUNNER, "reset_gate_audit", lambda gate: None)
    monkeypatch.setattr(
        RUNNER,
        "run_control",
        lambda run, gate: (control, {"worker_count": 10, "worker_errors": []}, empty_audit),
    )
    monkeypatch.setattr(RUNNER, "add_costed_returns", lambda frame: frame)
    monkeypatch.setattr(
        RUNNER,
        "metric_summary",
        lambda frame, window_id, strategy_name, strategy_id: {"strategy": strategy_name},
    )
    monkeypatch.setattr(RUNNER, "write_frame", lambda path, frame: None)
    monkeypatch.setattr(RUNNER, "write_json", lambda path, payload: None)
    monkeypatch.setattr(RUNNER, "OUT", tmp_path)
    monkeypatch.setattr(
        RUNNER,
        "HELPER",
        SimpleNamespace(
            candidate_replay=lambda *args, **kwargs: (
                ma60,
                {"worker_errors": [], "ticker_count": 1},
                empty_audit,
                0.01,
            )
        ),
    )
    monkeypatch.setattr(
        RUNNER,
        "ALIGNMENT",
        SimpleNamespace(
            candidate_replay=lambda *args, **kwargs: (
                alignment,
                {"worker_errors": [], "ticker_count": 1, "elapsed_seconds": 0.01},
                empty_audit,
            )
        ),
    )

    metrics = []
    result = RUNNER.run_full_window("P2-1", None, None, frozenset(), None, metrics)

    assert result["execution"]["MA60"]["worker_errors"] == []
    assert result["execution"]["ALIGNMENT"]["worker_errors"] == []
    assert [row["strategy"] for row in metrics] == ["CONTROL", "MA60", "ALIGNMENT"]
