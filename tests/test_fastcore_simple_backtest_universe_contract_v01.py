from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = (
    ROOT
    / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_ma60_vs_bullish_alignment_5window_simple_backtest_v01/run_5window_simple_backtest.py"
)
SPEC = importlib.util.spec_from_file_location("fastcore_simple_backtest_universe_contract_v01", RUNNER_PATH)
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RUNNER
SPEC.loader.exec_module(RUNNER)


def _pit_row(ticker: str, isu_cd: str, market: str, start: str, end: str, **extra):
    return {
        "ticker": ticker,
        "isu_cd": isu_cd,
        "market": market,
        "state": "COMMON",
        "effective_from": start,
        "effective_to": end,
        **extra,
    }


def _run_context(pit_intervals):
    calendar = SimpleNamespace()
    authority = SimpleNamespace(pit_intervals=pit_intervals)
    loader = SimpleNamespace(repository=object())
    window = SimpleNamespace()
    return RUNNER.STRATEGY.RunContext(
        window=window,
        calendar=calendar,
        authority=authority,
        segments_by_ticker={},
        score_contract={},
        stage_contract={},
        loader=loader,
        lifecycle_settlements=(),
        authority_coverage_start="2020-01-01",
        authority_coverage_end="2026-12-31",
        setup_seconds=0.0,
    )


def _p3_window(*_args, **_kwargs):
    return SimpleNamespace(
        effective_start=pd.Timestamp("2022-01-03"),
        effective_end=pd.Timestamp("2025-05-30"),
        execution_support=pd.Timestamp("2025-06-02"),
    )


def test_historical_common_rows_keep_low_cap_and_non_survivor_identity(monkeypatch):
    rows = [
        _pit_row("000001", "LOWCAP-ISU", "KOSPI", "2021-01-01", "2026-12-31", market_cap=1, current_survivor=False),
    ]
    base_run = _run_context(rows)
    monkeypatch.setattr(RUNNER, "resolve_standard_backtest_window", _p3_window)
    monkeypatch.setattr(RUNNER, "RepositoryV2DailyLoader", lambda repository, end: SimpleNamespace(repository=repository, end=end))

    run, gate, context = RUNNER.context_for_window(base_run, object(), frozenset(), "P3-1")

    assert gate is None
    assert run.entry_signal_gate is None
    assert set(run.segments_by_ticker) == {"000001"}
    assert run.segments_by_ticker["000001"][0].isu_cd == "LOWCAP-ISU"
    assert context["market_cap_filter"] == "NONE"
    assert context["market_cap_based_reject_count"] == 0
    assert context["current_survivor_membership_used"] is False


def test_exact_ticker_isu_exclusion_allows_ticker_reuse_and_ignores_market():
    excluded_ticker, excluded_isu = next(iter(RUNNER.PERMANENT_IDENTITY_EXCLUSIONS))
    rows = [
        {"ticker": excluded_ticker, "isu_cd": excluded_isu, "market": "KOSPI"},
        {"ticker": excluded_ticker, "isu_cd": excluded_isu, "market": "KOSDAQ"},
        {"ticker": excluded_ticker, "isu_cd": "REUSED-TICKER-OTHER-ISU", "market": "KOSDAQ"},
    ]

    kept = RUNNER.apply_exact_permanent_exclusions(rows, RUNNER.exact_permanent_exclusion_pairs())

    assert [(row["ticker"], row["isu_cd"], row["market"]) for row in kept] == [
        (excluded_ticker, "REUSED-TICKER-OTHER-ISU", "KOSDAQ")
    ]


def test_control_ma60_alignment_receive_one_shared_corrected_universe(monkeypatch, tmp_path):
    pair = ("000001", "LOWCAP-ISU", "KOSPI")
    run = SimpleNamespace(
        segments_by_ticker={"000001": (SimpleNamespace(key="one"),)},
        entry_signal_gate=None,
    )
    observed_run_ids = []
    control = pd.DataFrame({"pair_id": ["control"]})
    ma60 = pd.DataFrame({"pair_id": ["ma60"]})
    alignment = pd.DataFrame({"pair_id": ["alignment"]})
    audit = pd.DataFrame()

    monkeypatch.setattr(RUNNER, "context_for_window", lambda *_args: (run, None, {
        "window_id": "P3-1", "eligible_historical_identity_key_count": 1, "common_pit_segment_count": 1,
    }))
    monkeypatch.setattr(RUNNER, "reset_gate_audit", lambda _gate: None)
    monkeypatch.setattr(
        RUNNER,
        "run_control",
        lambda current_run, _gate: (
            observed_run_ids.append(id(current_run)) or control,
            {"worker_count": 10, "worker_errors": [], "ticker_count": 1},
            audit,
        ),
    )
    monkeypatch.setattr(RUNNER, "add_costed_returns", lambda frame: frame)
    monkeypatch.setattr(RUNNER, "metric_summary", lambda frame, window_id, strategy_name, strategy_id: {"strategy": strategy_name})
    monkeypatch.setattr(RUNNER, "write_frame", lambda _path, _frame: None)
    monkeypatch.setattr(RUNNER, "write_json", lambda _path, _payload: None)
    monkeypatch.setattr(RUNNER, "OUT", tmp_path)

    def candidate(current_run, _audit_gate, *_args, **_kwargs):
        observed_run_ids.append(id(current_run))
        return ma60, {"worker_errors": [], "ticker_count": 1}, audit, 0.01

    def alignment_candidate(_helper, current_run, _audit_gate, *_args, **_kwargs):
        observed_run_ids.append(id(current_run))
        return alignment, {"worker_errors": [], "ticker_count": 1, "elapsed_seconds": 0.01}, audit

    monkeypatch.setattr(RUNNER, "HELPER", SimpleNamespace(candidate_replay=candidate))
    monkeypatch.setattr(RUNNER, "ALIGNMENT", SimpleNamespace(candidate_replay=alignment_candidate))

    result = RUNNER.run_full_window("P3-1", None, None, frozenset({pair}), object(), [])

    assert observed_run_ids == [id(run), id(run), id(run)]
    assert run.entry_signal_gate is None
    assert result["window_id"] == "P3-1"
    assert result["execution"]["CONTROL"]["ticker_count"] == 1
    assert result["execution"]["MA60"]["ticker_count"] == 1
    assert result["execution"]["ALIGNMENT"]["ticker_count"] == 1
