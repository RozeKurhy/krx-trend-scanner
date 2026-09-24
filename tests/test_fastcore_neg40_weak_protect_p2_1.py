import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import scripts.run_fastcore_neg40_weak_protect_p2_1 as runner
from scripts.run_fastcore_neg40_weak_protect_p2_1 import (
    IdentitySegment,
    _apply_lifecycle_settlement,
    _candidate_trade,
    _common_entry_eligibility_cutoff,
    _outcome_date,
    _outcome_reason,
    _pct,
)


def test_official_backtest_callers_pass_the_complete_window_contract_explicitly():
    project_root = Path(__file__).resolve().parents[1]
    required = {
        "cutoff_date",
        "signal_cutoff_date",
        "execution_support_date",
        "entry_signal_cutoff_date",
        "entry_execution_cutoff_date",
    }
    expected_calls = {
        "scripts/run_fastcore_neg40_weak_protect_p2_1.py": {
            "cutoff_date": "window_effective_end",
            "signal_cutoff_date": "window_effective_end",
            "execution_support_date": "window_execution_support",
            "entry_signal_cutoff_date": "entry_eligibility_cutoff",
            "entry_execution_cutoff_date": "entry_eligibility_cutoff",
        },
        "scripts/evaluate_pattern_a_fast_core_v02_reentry.py": {
            name: "DATA_CUTOFF" for name in required
        },
        "scripts/run_fastcore_parity_v01.py": {
            name: "DATA_CUTOFF" for name in required
        },
    }

    for relative_path, expected in expected_calls.items():
        source = (project_root / relative_path).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=relative_path)
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and getattr(node.func, "attr", getattr(node.func, "id", None))
            == "simulate_ticker_core_v02_reentry"
        ]
        assert calls, f"no simulator call found in {relative_path}"
        for call in calls:
            keywords = {item.arg: ast.unparse(item.value) for item in call.keywords if item.arg}
            assert required.issubset(keywords), f"missing contract keyword in {relative_path}"
            for name, value in expected.items():
                assert keywords[name] == value, f"{relative_path} has wrong {name} contract value"


def test_stable_security_identity_survives_authority_revision_and_market_transfer():
    prior = IdentitySegment(
        ticker="003670",
        isu_cd="KR7003670007",
        market="KOSDAQ",
        effective_from=pd.Timestamp("2010-01-04"),
        effective_to=pd.Timestamp("2019-05-28"),
    )
    transferred = IdentitySegment(
        ticker="003670",
        isu_cd="KR7003670007",
        market="KOSPI",
        effective_from=pd.Timestamp("2019-05-29"),
        effective_to=pd.Timestamp("2026-09-04"),
    )
    revised_coverage = IdentitySegment(
        ticker="003670",
        isu_cd="KR7003670007",
        market="KOSDAQ",
        effective_from=pd.Timestamp("2010-01-04"),
        effective_to=pd.Timestamp("2026-09-04"),
    )
    recycled_code = IdentitySegment(
        ticker="003670",
        isu_cd="KR7999990001",
        market="KOSDAQ",
        effective_from=pd.Timestamp("2026-09-05"),
        effective_to=pd.Timestamp("2026-09-24"),
    )

    assert prior.stable_security_id == transferred.stable_security_id == "KR7003670007"
    assert prior.key != transferred.key
    assert prior.stable_security_id == revised_coverage.stable_security_id
    assert prior.key != revised_coverage.key
    assert recycled_code.stable_security_id != prior.stable_security_id


def test_standard_runner_fails_closed_without_window_execution_support():
    segment = IdentitySegment(
        ticker="000001",
        isu_cd="KR7000000001",
        market="KOSPI",
        effective_from=pd.Timestamp("2025-01-01"),
        effective_to=pd.Timestamp("2025-01-10"),
    )
    run = SimpleNamespace(
        window=SimpleNamespace(effective_end=pd.Timestamp("2025-01-09"), execution_support=None),
        segments_by_ticker={"000001": (segment,)},
    )

    with pytest.raises(RuntimeError, match="requires explicit window effective_end and execution support"):
        runner._process_ticker("000001", run)


def test_p2_2_run_id_override_uses_separate_versioned_output_namespace():
    try:
        runner._configure_run("P2-2", "run_20260924_final_corrective_v01")
        assert runner.RUN_ID == "run_20260924_final_corrective_v01"
        assert runner.RUN_DIR.name == "run_20260924_final_corrective_v01"
        assert runner.SAMPLE_PATH.name == "sample_benchmark_p2_2_pit_extension_v01.json"
        assert runner.MATCHED_LEDGER_PATH.parent == runner.RUN_DIR
    finally:
        runner._configure_run("P2-1")


def test_p2_1_run_id_override_uses_isolated_recertification_namespace():
    try:
        runner._configure_run("P2-1", "run_20260924_cutoff_contract_recert_v01")
        assert runner.RUN_ID == "run_20260924_cutoff_contract_recert_v01"
        assert runner.RUN_DIR.name == runner.RUN_ID
        assert runner.RUN_DIR.parent.name == "p2_1_neg40_weak_protect_v01"
        assert runner.SAMPLE_PATH.name == "sample_benchmark.json"
        assert runner.CORRECTED_RUN_DIR == runner.RUN_DIR
        assert runner.MATCHED_LEDGER_PATH.parent == runner.RUN_DIR
    finally:
        runner._configure_run("P2-1")


@pytest.mark.parametrize("run_id", ["../outside", "run_bad/path", "invalid"])
def test_p2_2_run_id_override_rejects_unsafe_or_unversioned_names(run_id):
    with pytest.raises(ValueError, match="P2-2 run id"):
        runner._configure_run("P2-2", run_id)


@pytest.mark.parametrize("run_id", ["../outside", "run_bad/path", "invalid"])
def test_p2_1_run_id_override_rejects_unsafe_or_unversioned_names(run_id):
    with pytest.raises(ValueError, match="P2-1 run id"):
        runner._configure_run("P2-1", run_id)


def test_p3_1_uses_isolated_window_specific_artifact_namespace():
    try:
        runner._configure_run("P3-1")
        assert runner.RUN_ID == "run_20260924_single_window_v01"
        assert runner.RUN_DIR.name == runner.RUN_ID
        assert runner.RUN_DIR.parent.name == "p3_1_neg40_weak_protect_v01"
        assert runner.SAMPLE_PATH.name == "sample_benchmark_p3_1_common_pit_v01.json"
        assert runner.MATCHED_LEDGER_PATH.name == "p3_1_matched_trades.csv"
        assert runner.SOFT_EVENTS_PATH.name == "p3_1_soft_events.csv"
        assert runner.LEDGER_SUMMARY_PATH.name == "p3_1_summary.json"
    finally:
        runner._configure_run("P2-1")


def test_p3_1_population_preflight_requires_support_coverage_and_fresh_common_pit():
    segment = IdentitySegment(
        ticker="000001",
        isu_cd="KR7000000001",
        market="KOSPI",
        effective_from=pd.Timestamp("2020-01-01"),
        effective_to=pd.Timestamp("2026-12-31"),
    )
    run = SimpleNamespace(
        window=SimpleNamespace(
            window=SimpleNamespace(window_id="P3-1"),
            effective_start=pd.Timestamp("2022-01-03"),
            effective_end=pd.Timestamp("2025-05-30"),
            execution_support=pd.Timestamp("2025-06-02"),
        ),
        authority=SimpleNamespace(
            pit_path=runner.ROOT / "authority.json",
            pit_sha256="authority-hash",
        ),
        authority_coverage_start="2010-01-04",
        authority_coverage_end="2025-06-02",
        segments_by_ticker={"000001": (segment,)},
    )

    passed = runner._p3_1_population_preflight(run)
    assert passed["status"] == "PASS"
    assert passed["p2_population_reused"] is False
    assert passed["checks"]["p2_population_not_reused"] is True
    assert passed["common_identity_segment_count"] == 1

    run.authority_coverage_end = "2025-05-30"
    blocked = runner._p3_1_population_preflight(run)
    assert blocked["status"] == "CHECK_REQUIRED"
    assert blocked["checks"]["authority_coverage_execution_support"] is False


def test_result_validation_fails_closed_on_post_cutoff_entry_source():
    cutoff = pd.Timestamp("2025-05-30")
    late = pd.DataFrame(
        [{"trade_id": "000001_01", "ticker": "000001", "entry_execution_date": "2025-06-02"}]
    )
    allowed = pd.DataFrame(
        [{"trade_id": "000001_01", "ticker": "000001", "entry_execution_date": "2025-05-30"}]
    )

    with pytest.raises(RuntimeError, match="1 entry execution.*after effective_end"):
        runner._assert_entry_executions_within_effective_end(
            late,
            cutoff,
            source="test CONTROL population",
        )
    runner._assert_entry_executions_within_effective_end(
        allowed,
        cutoff,
        source="test CONTROL population",
    )


def _process_ticker_with_records(monkeypatch, records):
    segment = IdentitySegment(
        ticker="000001",
        isu_cd="KR7000000001",
        market="KOSPI",
        effective_from=pd.Timestamp("2020-01-01"),
        effective_to=pd.Timestamp("2025-05-29"),
    )
    daily = pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0],
            "high": [101.0, 102.0, 103.0],
            "low": [99.0, 100.0, 101.0],
            "close": [100.0, 101.0, 102.0],
        },
        index=pd.to_datetime(["2025-05-29", "2025-05-30", "2025-06-02"]),
    )

    class FakeLoader:
        def __init__(self, repository, *, start, end):
            self.load_count = 0

        def load(self, ticker):
            self.load_count += 1
            return daily

    class FakeRecord(dict):
        __getattr__ = dict.__getitem__

        def to_dict(self):
            return dict(self)

    monkeypatch.setattr(runner, "RepositoryV2DailyLoader", FakeLoader)
    monkeypatch.setattr(runner.v2, "build_precomputed_ticker_context", lambda *args: object())
    monkeypatch.setattr(
        runner.v2,
        "simulate_ticker_core_v02_reentry",
        lambda **kwargs: [FakeRecord(row) for row in records],
    )
    monkeypatch.setattr(
        runner,
        "_candidate_trade",
        lambda base, *, pair_id, **kwargs: (
            {**base, "pair_id": pair_id},
            {"incremental_soft_exit": False, "execution_support_missing": False},
        ),
    )
    run = SimpleNamespace(
        window=SimpleNamespace(
            window=SimpleNamespace(window_id="P2-1"),
            effective_start=pd.Timestamp("2021-01-04"),
            effective_end=pd.Timestamp("2025-05-30"),
            execution_support=pd.Timestamp("2025-06-02"),
        ),
        segments_by_ticker={"000001": (segment,)},
        loader=SimpleNamespace(repository=object()),
        score_contract={},
        stage_contract={},
        calendar=object(),
    )
    return runner._process_ticker("000001", run)


def test_process_ticker_allows_cutoff_exit_to_execute_on_support(monkeypatch):
    result = _process_ticker_with_records(
        monkeypatch,
        [
            {
                "ticker": "000001",
                "name": "000001",
                "market": "KOSPI",
                "trade_id": "000001_01",
                "trade_sequence": 1,
                "entry_signal_date": "2025-05-28",
                "entry_execution_date": "2025-05-29",
                "entry_open": 101.0,
                "entry_pattern_a_stage": "EARLY_TREND",
                "first_progressed_effective_trading_date": None,
                "exit_type": "EXIT3_PROGRESSED_TO_WEAK",
                "exit_signal_date": "2025-05-30",
                "exit_execution_date": "2025-06-02",
                "exit_price": 102.0,
                "terminal_return": 0.99,
                "mfe": 1.98,
                "mae": 0.0,
                "peak_giveback": 0.99,
                "profit_capture": 0.5,
                "holding_weeks": 0.2,
                "trade_status": "REALIZED",
            }
        ],
    )

    assert len(result["control_rows"]) == 1
    assert len(result["candidate_rows"]) == 1
    assert result["control_rows"][0]["entry_execution_date"] == "2025-05-29"
    assert result["control_rows"][0]["exit_execution_date"] == "2025-06-02"
    assert result["candidate_rows"][0]["exit_execution_date"] == "2025-06-02"


def _base_trade() -> dict:
    return {
        "ticker": "000001",
        "name": "000001",
        "market": "KOSPI",
        "trade_id": "000001_01",
        "trade_sequence": 1,
        "entry_signal_date": "2025-01-03",
        "entry_execution_date": "2025-01-06",
        "entry_open": 100.0,
        "entry_pattern_a_stage": "EARLY_TREND",
        "first_progressed_effective_trading_date": "2025-01-07",
        "exit_type": "EXIT3_PROGRESSED_TO_WEAK",
        "exit_signal_date": "2025-01-07",
        "exit_execution_date": "2025-01-08",
        "exit_price": 55.0,
        "terminal_return": -45.0,
        "mfe": 0.0,
        "mae": -45.0,
        "peak_giveback": 45.0,
        "profit_capture": None,
        "holding_weeks": 0.6,
        "trade_status": "REALIZED",
    }


def _segment() -> IdentitySegment:
    return IdentitySegment(
        ticker="000001",
        isu_cd="KR7000000001",
        market="KOSPI",
        effective_from=pd.Timestamp("2020-01-01"),
        effective_to=pd.Timestamp("2025-12-31"),
    )


def _daily(closes: list[float]) -> pd.DataFrame:
    dates = pd.to_datetime(["2025-01-06", "2025-01-07", "2025-01-08", "2025-01-09", "2025-01-10"][: len(closes)])
    return pd.DataFrame(
        {
            "open": [100.0, 90.0, 80.0, 70.0, 60.0][: len(closes)],
            "high": [101.0, 95.0, 85.0, 75.0, 65.0][: len(closes)],
            "low": [99.0, 55.0, 50.0, 55.0, 54.0][: len(closes)],
            "close": closes,
        },
        index=dates,
    )


def test_candidate_return_uses_exact_v2_arithmetic_for_rounding_ties():
    assert _pct(2055.0, 2400.0) == round(((2055.0 - 2400.0) / 2400.0) * 100.0, 2)
    assert _pct(2055.0, 2400.0) == -14.37


def test_weak_protect_defers_v2_exit_and_keeps_trade_open_through_cutoff():
    daily = _daily([100.0, 60.0, 55.0, 60.0])
    candidate, diagnostics = _candidate_trade(
        _base_trade(),
        pair_id="pair-1",
        segment=_segment(),
        daily=daily,
        stage_timeline={pd.Timestamp("2025-01-07"): "WEAK"},
        window=SimpleNamespace(
            effective_end=pd.Timestamp("2025-01-09"),
            execution_support=pd.Timestamp("2025-01-10"),
        ),
    )

    assert candidate["candidate_action"] == "WEAK_PROTECT_HOLD_OPEN"
    assert candidate["trade_status"] == "OPEN_AT_CUTOFF"
    assert candidate["control_exit_signal_date"] == "2025-01-07"
    assert candidate["exit_signal_date"] is None
    assert candidate["terminal_return"] == -40.0
    assert candidate["weak_protect_eod_events"] == 3
    assert diagnostics["deferred_control_exit_open_at_cutoff"] is True
    assert [event["date"] for event in diagnostics["soft_events"]] == [
        "2025-01-07",
        "2025-01-08",
        "2025-01-09",
    ]
    assert all(event["event_type"] == "WEAK_PROTECT" for event in diagnostics["soft_events"])
    assert all(event["pattern_a_stage"] == "WEAK" for event in diagnostics["soft_events"])
    assert all(event["execution_date"] is None for event in diagnostics["soft_events"])


def test_weak_is_rechecked_and_nonweak_neg40_soft_exits_next_local_open():
    daily = _daily([100.0, 60.0, 55.0, 58.0, 54.0])
    candidate, diagnostics = _candidate_trade(
        _base_trade(),
        pair_id="pair-2",
        segment=_segment(),
        daily=daily,
        stage_timeline={
            pd.Timestamp("2025-01-07"): "WEAK",
            pd.Timestamp("2025-01-09"): "BASE",
        },
        window=SimpleNamespace(
            effective_end=pd.Timestamp("2025-01-09"),
            execution_support=pd.Timestamp("2025-01-10"),
        ),
    )

    assert candidate["candidate_action"] == "SOFT_EXIT"
    assert candidate["exit_type"] == "SOFT_EXIT_NEG40_NON_WEAK"
    assert candidate["exit_signal_date"] == "2025-01-09"
    assert candidate["exit_execution_date"] == "2025-01-10"
    assert candidate["exit_price"] == 60.0
    assert candidate["terminal_return"] == -40.0
    assert diagnostics["soft_signal"] is True
    assert [event["event_type"] for event in diagnostics["soft_events"]] == [
        "WEAK_PROTECT",
        "WEAK_PROTECT",
        "SOFT_EXIT_SIGNAL",
    ]
    signal = diagnostics["soft_events"][-1]
    assert signal["date"] == "2025-01-09"
    assert signal["pattern_a_stage"] == "BASE"
    assert signal["execution_date"] == "2025-01-10"
    assert signal["execution_open"] == 60.0


def test_matched_ledger_is_one_row_per_identical_trade_and_recomputable():
    common = {
        "ticker": "000001",
        "isu_cd": "KR7000000001",
        "market": "KOSPI",
        "identity_effective_from": "2020-01-01",
        "identity_effective_to": "2025-12-31",
        "entry_signal_date": "2025-01-03",
        "entry_execution_date": "2025-01-06",
        "entry_open": 100.0,
    }
    control = pd.DataFrame(
        [
            {
                **common,
                "pair_id": "p1",
                "trade_id": "000001_01",
                "exit_signal_date": "2025-02-03",
                "exit_execution_date": "2025-02-04",
                "exit_type": "V2_EXIT",
                "terminal_return": -10.0,
                "holding_days": 20,
                "trade_status": "REALIZED",
            },
            {
                **common,
                "pair_id": "p2",
                "trade_id": "000001_01",
                "exit_signal_date": None,
                "exit_execution_date": None,
                "exit_type": "NO_EXIT",
                "terminal_return": 2.0,
                "holding_days": 30,
                "trade_status": "OPEN_AT_CUTOFF",
            },
        ]
    )
    candidate = pd.DataFrame(
        [
            {
                **common,
                "pair_id": "p1",
                "trade_id": "000001_01",
                "exit_signal_date": "2025-02-05",
                "exit_execution_date": "2025-02-06",
                "exit_type": "SOFT_EXIT_NEG40_NON_WEAK",
                "terminal_return": -12.0,
                "holding_days": 22,
                "trade_status": "REALIZED",
                "candidate_action": "SOFT_EXIT",
            },
            {
                **common,
                "pair_id": "p2",
                "trade_id": "000001_01",
                "exit_signal_date": None,
                "exit_execution_date": None,
                "exit_type": "NO_EXIT",
                "terminal_return": 2.0,
                "holding_days": 30,
                "trade_status": "OPEN_AT_CUTOFF",
                "candidate_action": "CONTROL_PRESERVED",
            },
        ]
    )

    ledger = runner._build_matched_trade_ledger(control, candidate, cutoff_date="2025-05-30")

    assert len(ledger) == 2
    assert ledger["pair_id"].is_unique
    assert ledger["trade_id"].tolist() == ["000001_01", "000001_01"]
    first = ledger.set_index("pair_id").loc["p1"]
    assert first["control_exit_or_cutoff_date"] == "2025-02-04"
    assert first["candidate_exit_or_cutoff_date"] == "2025-02-06"
    assert first["candidate_soft_exit"]
    assert first["paired_delta"] == -2.0
    second = ledger.set_index("pair_id").loc["p2"]
    assert second["control_exit_or_cutoff_date"] == "2025-05-30"
    assert second["candidate_exit_or_cutoff_date"] == "2025-05-30"
    assert second["control_open_at_cutoff"]
    assert second["candidate_open_at_cutoff"]
    assert runner._ledger_aggregates(ledger)["paired"]["count"] == 2
    p3_ledger = runner._add_p3_1_ledger_contract_fields(ledger)
    assert {"trade_status", "terminal_reason"}.issubset(p3_ledger.columns)
    assert p3_ledger.loc[0, "trade_status"] == "CONTROL=REALIZED;CANDIDATE=REALIZED"
    assert "CONTROL=V2_EXIT" in p3_ledger.loc[0, "terminal_reason"]
    assert "CANDIDATE=SOFT_EXIT_NEG40_NON_WEAK" in p3_ledger.loc[0, "terminal_reason"]


def test_matched_ledger_rejects_duplicate_pair_id_as_the_uniqueness_key():
    control = pd.DataFrame(
        [{"pair_id": "same-pair", "trade_id": "000001_01"}] * 2
    )
    candidate = control.copy()

    with pytest.raises(RuntimeError, match="duplicate CONTROL pair_id"):
        runner._build_matched_trade_ledger(control, candidate, cutoff_date="2025-05-30")


def test_calendar_month_end_v2_signal_uses_last_trading_eod_and_preserves_next_open():
    base = _base_trade()
    base.update(
        {
            "exit_signal_date": "2025-01-12",  # Sunday calendar label
            "exit_execution_date": "2025-01-13",
            "exit_price": 80.0,
            "terminal_return": -20.0,
        }
    )
    dates = pd.to_datetime(
        ["2025-01-06", "2025-01-07", "2025-01-08", "2025-01-09", "2025-01-10", "2025-01-13"]
    )
    daily = pd.DataFrame(
        {
            "open": [100.0, 99.0, 98.0, 97.0, 96.0, 80.0],
            "high": [101.0, 100.0, 99.0, 98.0, 97.0, 81.0],
            "low": [99.0, 98.0, 97.0, 96.0, 95.0, 79.0],
            "close": [100.0, 100.0, 100.0, 100.0, 100.0, 80.0],
        },
        index=dates,
    )
    candidate, _ = _candidate_trade(
        base,
        pair_id="pair-calendar-month-end",
        segment=_segment(),
        daily=daily,
        stage_timeline={pd.Timestamp("2025-01-10"): "BASE"},
        window=SimpleNamespace(
            effective_end=pd.Timestamp("2025-01-10"),
            execution_support=pd.Timestamp("2025-01-13"),
        ),
    )

    assert candidate["candidate_action"] == "CONTROL_EXIT"
    assert candidate["exit_signal_date"] == "2025-01-12"
    assert candidate["exit_execution_date"] == "2025-01-13"
    assert candidate["terminal_return"] == -20.0


def test_monthly_pattern_stage_is_available_at_last_local_eod_for_calendar_label(monkeypatch):
    daily = _daily([100.0, 100.0, 100.0, 100.0, 100.0])
    month_end = pd.Timestamp("2025-01-12")  # Sunday; last local session is Jan 10.
    context = SimpleNamespace(monthly_up_to=lambda _cutoff: pd.DataFrame(index=[month_end]))
    monkeypatch.setattr(runner.v2, "build_historical_snapshot_from_context", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        runner,
        "evaluate_pattern_a",
        lambda _snapshot: SimpleNamespace(stage=SimpleNamespace(value="WEAK")),
    )

    timeline = runner._stage_timeline(
        daily,
        context,
        pd.Timestamp("2025-01-01"),
        pd.Timestamp("2025-01-10"),
        calendar=None,
    )

    assert timeline == {pd.Timestamp("2025-01-10"): "WEAK"}


def test_soft_event_ledger_keeps_weak_events_and_matches_next_open_soft_exit():
    diagnostics = [
        {
            "soft_events": [
                {
                    "trade_id": "000001_01",
                    "pair_id": "pair-soft",
                    "ticker": "000001",
                    "date": "2025-01-07",
                    "close_return": -40.0,
                    "pattern_a_stage": "WEAK",
                    "event_type": "WEAK_PROTECT",
                    "execution_date": None,
                    "execution_open": None,
                },
                {
                    "trade_id": "000001_01",
                    "pair_id": "pair-soft",
                    "ticker": "000001",
                    "date": "2025-01-09",
                    "close_return": -42.0,
                    "pattern_a_stage": "BASE",
                    "event_type": "SOFT_EXIT_SIGNAL",
                    "execution_date": "2025-01-10",
                    "execution_open": 60.0,
                },
            ]
        }
    ]
    candidate = pd.DataFrame(
        [
            {
                "trade_id": "000001_01",
                "pair_id": "pair-soft",
                "candidate_action": "SOFT_EXIT",
                "exit_signal_date": "2025-01-09",
                "exit_execution_date": "2025-01-10",
                "exit_price": 60.0,
            },
            {
                "trade_id": "000001_01",
                "pair_id": "pair-other-segment",
                "candidate_action": "CONTROL_PRESERVED",
                "exit_signal_date": None,
                "exit_execution_date": None,
                "exit_price": None,
            },
        ]
    )

    events = runner._build_soft_event_ledger(diagnostics, candidate)

    assert list(events["event_type"]) == ["WEAK_PROTECT", "SOFT_EXIT_SIGNAL"]
    assert set(events["trade_id"]) == {"000001_01"}
    assert set(events["pair_id"]) == {"pair-soft"}
    assert events.iloc[-1]["execution_date"] == "2025-01-10"


def test_missing_soft_execution_error_identifies_pair_trade_ticker_and_boundary():
    diagnostics = [
        {
            "soft_events": [
                {
                    "trade_id": "000001_03",
                    "pair_id": "pair-boundary",
                    "ticker": "000001",
                    "date": "2026-08-21",
                    "close_return": -41.25,
                    "pattern_a_stage": "BASE",
                    "event_type": "SOFT_EXIT_SIGNAL",
                    "execution_date": None,
                    "execution_open": None,
                }
            ]
        }
    ]
    candidate = pd.DataFrame(
        [
            {
                "trade_id": "000001_03",
                "pair_id": "pair-boundary",
                "ticker": "000001",
                "isu_cd": "KR7000000001",
                "market": "KOSPI",
                "identity_effective_from": "2020-01-01",
                "identity_effective_to": "2026-08-21",
                "repository_v2_last_actual_date": "2026-08-21",
                "trade_status": "UNEXECUTED_SIGNAL",
                "execution_support_missing": True,
                "terminal_valuation_date": "2026-08-21",
                "terminal_valuation_at_cutoff": False,
                "candidate_action": "SOFT_EXIT",
            }
        ]
    )

    with pytest.raises(RuntimeError) as exc_info:
        runner._build_soft_event_ledger(diagnostics, candidate)

    message = str(exc_info.value)
    assert "pair_id=pair-boundary" in message
    assert "trade_id=000001_03" in message
    assert "ticker=000001" in message
    assert "signal_date=2026-08-21" in message
    assert "segment_end=2026-08-21" in message
    assert "terminal_valuation_at_cutoff=False" in message


def test_executed_soft_signal_without_next_session_open_fails_closed():
    diagnostics = [
        {
            "soft_events": [
                {
                    "trade_id": "000001_03",
                    "pair_id": "pair-executed-missing-open",
                    "ticker": "000001",
                    "date": "2026-08-21",
                    "close_return": -41.25,
                    "pattern_a_stage": "BASE",
                    "event_type": "SOFT_EXIT_SIGNAL",
                    "execution_date": None,
                    "execution_open": None,
                }
            ]
        }
    ]
    candidate = pd.DataFrame(
        [
            {
                "trade_id": "000001_03",
                "pair_id": "pair-executed-missing-open",
                "ticker": "000001",
                "trade_status": "REALIZED",
                "execution_support_missing": False,
                "candidate_action": "SOFT_EXIT",
            }
        ]
    )

    with pytest.raises(RuntimeError, match="SOFT_EXIT_SIGNAL lacks complete next-session execution support"):
        runner._build_soft_event_ledger(diagnostics, candidate)


def test_unexecuted_soft_signal_is_not_accepted_without_verified_terminal_contract():
    diagnostics = [
        {
            "soft_events": [
                {
                    "trade_id": "000001_03",
                    "pair_id": "pair-unexecuted",
                    "ticker": "000001",
                    "date": "2026-08-21",
                    "close_return": -41.25,
                    "pattern_a_stage": "BASE",
                    "event_type": "SOFT_EXIT_SIGNAL",
                    "execution_date": None,
                    "execution_open": None,
                }
            ]
        }
    ]
    candidate = pd.DataFrame(
        [
            {
                "trade_id": "000001_03",
                "pair_id": "pair-unexecuted",
                "ticker": "000001",
                "trade_status": "UNEXECUTED_SIGNAL",
                "execution_support_missing": True,
                "candidate_action": "SOFT_EXIT",
            }
        ]
    )

    with pytest.raises(RuntimeError, match="no-session cause and terminal valuation are verified"):
        runner._build_soft_event_ledger(diagnostics, candidate)


def test_soft_signal_after_common_interval_end_is_allowed_within_window():
    diagnostics = [
        {
            "soft_events": [
                {
                    "trade_id": "000001_03",
                    "pair_id": "pair-outside-identity",
                    "ticker": "000001",
                    "date": "2026-08-24",
                    "close_return": -41.25,
                    "pattern_a_stage": "BASE",
                    "event_type": "SOFT_EXIT_SIGNAL",
                    "execution_date": "2026-08-25",
                    "execution_open": 58.0,
                }
            ]
        }
    ]
    candidate = pd.DataFrame(
        [
            {
                "trade_id": "000001_03",
                "pair_id": "pair-outside-identity",
                "ticker": "000001",
                "isu_cd": "KR7000000001",
                "market": "KOSPI",
                "identity_effective_from": "2020-01-01",
                "identity_effective_to": "2026-08-21",
                "candidate_action": "SOFT_EXIT",
                "exit_signal_date": "2026-08-24",
                "exit_execution_date": "2026-08-25",
                "exit_price": 58.0,
            }
        ]
    )

    events = runner._build_soft_event_ledger(diagnostics, candidate)
    assert len(events) == 1
    assert events.iloc[0]["date"] == "2026-08-24"
    assert events.iloc[0]["execution_date"] == "2026-08-25"


def test_p2_2_identity_preflight_blocks_frozen_authority_short_of_cutoff():
    run = SimpleNamespace(
        window=SimpleNamespace(
            window=SimpleNamespace(window_id="P2-2"),
            effective_start=pd.Timestamp("2021-01-04"),
            effective_end=pd.Timestamp("2026-08-31"),
            execution_support=pd.Timestamp("2026-09-01"),
        ),
        authority_coverage_start="2010-01-04",
        authority_coverage_end="2026-08-21",
        segments_by_ticker={
            "000001": (
                IdentitySegment(
                    ticker="000001",
                    isu_cd="KR7000000001",
                    market="KOSPI",
                    effective_from=pd.Timestamp("2020-01-01"),
                    effective_to=pd.Timestamp("2026-08-31"),
                ),
            )
        },
    )

    preflight = runner._p2_2_identity_authority_preflight(run)

    assert preflight["status"] == "CHECK_REQUIRED"
    assert preflight["reason"] == "PIT_COMMON_AUTHORITY_GLOBAL_COVERAGE_SHORT_OF_P2_2_CUTOFF"
    assert preflight["pit_common_authority_global_coverage_end"] == "2026-08-21"


def test_p2_2_identity_preflight_uses_global_coverage_and_allows_expired_segments():
    run = SimpleNamespace(
        window=SimpleNamespace(
            window=SimpleNamespace(window_id="P2-2"),
            effective_start=pd.Timestamp("2021-01-04"),
            effective_end=pd.Timestamp("2026-08-31"),
            execution_support=pd.Timestamp("2026-09-01"),
        ),
        authority_coverage_start="2010-01-04",
        authority_coverage_end="2026-08-31",
        segments_by_ticker={
            "000001": (
                IdentitySegment(
                    ticker="000001",
                    isu_cd="KR7000000001",
                    market="KOSPI",
                    effective_from=pd.Timestamp("2020-01-01"),
                    effective_to=pd.Timestamp("2024-12-31"),
                ),
            )
        },
    )

    preflight = runner._p2_2_identity_authority_preflight(run)

    assert preflight["status"] == "PASS"
    assert preflight["pit_common_authority_global_coverage_end"] == "2026-08-31"
    assert preflight["common_identity_segment_count"] == 1


def _copy_p2_2_identity_extension(destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    for source in runner.P2_2_AUTHORITY_EXTENSION_DIR.glob("*.json"):
        (destination / source.name).write_bytes(source.read_bytes())
    return destination


def test_p2_2_extended_identity_authority_resolves_sealed_snapshot_and_preflight():
    authority = runner.load_effective_authority(runner.AUTHORITY_DIR)

    extended, coverage_start, coverage_end = runner._load_p2_2_extended_identity_authority(authority)

    assert coverage_start == "2010-01-04"
    assert coverage_end == "2026-09-01"
    assert len(extended.pit_intervals) == 3181
    assert extended.pit_sha256 == "9997c55526575bc2341b7ce2e056def1d0a8c3fb77d89c8fadb3716ae2f46dd4"

    effective_start = pd.Timestamp("2021-01-04")
    effective_end = pd.Timestamp("2026-08-31")
    first_relevant = next(
        interval
        for interval in extended.pit_intervals
        if interval.get("state") == "COMMON"
        and pd.Timestamp(interval["effective_from"]) <= effective_end
        and pd.Timestamp(interval["effective_to"]) >= effective_start
    )
    run = SimpleNamespace(
        window=SimpleNamespace(
            window=SimpleNamespace(window_id="P2-2"),
            effective_start=effective_start,
            effective_end=effective_end,
            execution_support=pd.Timestamp("2026-09-01"),
        ),
        authority_coverage_start=coverage_start,
        authority_coverage_end=coverage_end,
        segments_by_ticker={
            str(first_relevant["ticker"]): (
                IdentitySegment(
                    ticker=str(first_relevant["ticker"]),
                    isu_cd=str(first_relevant["isu_cd"]),
                    market=str(first_relevant["market"]),
                    effective_from=pd.Timestamp(first_relevant["effective_from"]),
                    effective_to=pd.Timestamp(first_relevant["effective_to"]),
                ),
            )
        },
    )
    preflight = runner._p2_2_identity_authority_preflight(run)

    assert preflight["status"] == "PASS"
    assert preflight["pit_common_authority_global_coverage_end"] == "2026-09-01"
    assert preflight["common_identity_segment_count"] == 1


def test_p2_2_extended_identity_authority_missing_artifact_fails_closed(monkeypatch, tmp_path):
    authority = runner.load_effective_authority(runner.AUTHORITY_DIR)
    monkeypatch.setattr(runner, "P2_2_AUTHORITY_EXTENSION_DIR", tmp_path / "missing")

    with pytest.raises(RuntimeError, match="P2_2_IDENTITY_AUTHORITY_EXTENSION_ARTIFACT_MISSING"):
        runner._load_p2_2_extended_identity_authority(authority)


def test_p2_2_extended_identity_authority_hash_mismatch_fails_closed(monkeypatch, tmp_path):
    authority = runner.load_effective_authority(runner.AUTHORITY_DIR)
    extension_dir = _copy_p2_2_identity_extension(tmp_path / "tampered")
    calendar_path = extension_dir / "merged_trading_calendar.json"
    calendar_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(runner, "P2_2_AUTHORITY_EXTENSION_DIR", extension_dir)

    with pytest.raises(RuntimeError, match="P2_2_IDENTITY_AUTHORITY_CALENDAR_FILE_HASH_MISMATCH"):
        runner._load_p2_2_extended_identity_authority(authority)


def test_p2_2_extended_identity_authority_wrong_coverage_fails_closed(monkeypatch, tmp_path):
    authority = runner.load_effective_authority(runner.AUTHORITY_DIR)
    extension_dir = _copy_p2_2_identity_extension(tmp_path / "short-coverage")
    calendar_path = extension_dir / "merged_trading_calendar.json"
    calendar = json.loads(calendar_path.read_text(encoding="utf-8"))
    calendar["calendar_frontier"] = "2026-08-21"
    calendar_path.write_text(
        json.dumps(calendar, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    manifest_path = extension_dir / "p2_2_identity_authority_extension_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["coverage_end"] = "2026-08-21"
    manifest["merged_calendar_file_sha256"] = runner._sha256(calendar_path)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    monkeypatch.setattr(runner, "P2_2_AUTHORITY_EXTENSION_DIR", extension_dir)

    with pytest.raises(RuntimeError, match="P2_2_IDENTITY_AUTHORITY_EXECUTION_SUPPORT_MISMATCH"):
        runner._load_p2_2_extended_identity_authority(authority)


def test_candidate_allows_exit_next_open_after_common_interval_end():
    base = _base_trade()
    segment = IdentitySegment(
        ticker="000001",
        isu_cd="KR7000000001",
        market="KOSPI",
        effective_from=pd.Timestamp("2025-01-01"),
        effective_to=pd.Timestamp("2025-01-07"),
    )
    candidate, _ = _candidate_trade(
        base,
        pair_id="pair-boundary-execution",
        segment=segment,
        daily=_daily([100.0, 60.0, 55.0, 60.0]),
        stage_timeline={pd.Timestamp("2025-01-07"): "BASE"},
        window=SimpleNamespace(
            effective_end=pd.Timestamp("2025-01-09"),
            execution_support=pd.Timestamp("2025-01-10"),
        ),
    )
    assert candidate["exit_signal_date"] == "2025-01-07"
    assert candidate["exit_execution_date"] == "2025-01-08"
    assert candidate["trade_status"] == "REALIZED"


def test_common_interval_end_limits_new_entry_eligibility_only():
    segment = IdentitySegment(
        ticker="010420",
        isu_cd="KR7010420008",
        market="KOSPI",
        effective_from=pd.Timestamp("2010-01-04"),
        effective_to=pd.Timestamp("2025-09-24"),
    )

    entry_cutoff = _common_entry_eligibility_cutoff(segment, pd.Timestamp("2026-08-31"))

    assert entry_cutoff == pd.Timestamp("2025-09-24")
    assert pd.Timestamp("2025-09-30") > entry_cutoff


def test_process_ticker_separates_position_horizon_from_entry_eligibility(monkeypatch):
    segment = IdentitySegment(
        ticker="010420",
        isu_cd="KR7010420008",
        market="KOSPI",
        effective_from=pd.Timestamp("2010-01-04"),
        effective_to=pd.Timestamp("2025-05-29"),
    )
    captured = {}
    loader_bounds = {}

    class FakeLoader:
        def __init__(self, repository, *, start, end):
            self.load_count = 0
            loader_bounds.update(start=start, end=end)

        def load(self, ticker):
            self.load_count += 1
            return pd.DataFrame(
                {
                    "open": [1887.0, 1888.0],
                    "high": [1900.0, 1890.0],
                    "low": [1870.0, 1880.0],
                    "close": [1888.0, 1888.0],
                },
                index=pd.to_datetime(["2025-04-14", "2025-09-03"]),
            )

    class FakeRecord(dict):
        __getattr__ = dict.__getitem__

        def to_dict(self):
            return dict(self)

    def fake_simulator(**kwargs):
        captured.update(kwargs)
        return [
            FakeRecord(
                {
                    "ticker": "010420",
                    "name": "010420",
                    "market": "KOSPI",
                    "trade_id": "010420_02",
                    "trade_sequence": 2,
                    "entry_signal_date": "2025-04-11",
                    "entry_execution_date": "2025-04-14",
                    "entry_open": 1887.0,
                    "entry_pattern_a_stage": "TRANSITION",
                    "first_progressed_effective_trading_date": None,
                    "exit_type": "NO_EXIT",
                    "exit_signal_date": None,
                    "exit_execution_date": None,
                    "exit_price": None,
                    "terminal_return": 0.05,
                    "mfe": 1.0,
                    "mae": -1.0,
                    "peak_giveback": 0.95,
                    "profit_capture": 0.05,
                    "holding_weeks": 0.4,
                    "trade_status": "OPEN_AT_CUTOFF",
                }
            )
        ]

    monkeypatch.setattr(runner, "RepositoryV2DailyLoader", FakeLoader)
    monkeypatch.setattr(runner.v2, "build_precomputed_ticker_context", lambda *args: object())
    monkeypatch.setattr(runner.v2, "simulate_ticker_core_v02_reentry", fake_simulator)
    run = SimpleNamespace(
        window=SimpleNamespace(
            window=SimpleNamespace(window_id="P2-2"),
            effective_start=pd.Timestamp("2021-01-04"),
            effective_end=pd.Timestamp("2026-08-31"),
            execution_support=pd.Timestamp("2026-09-01"),
        ),
        segments_by_ticker={"010420": (segment,)},
        loader=SimpleNamespace(repository=object()),
        score_contract={},
        stage_contract={},
        calendar=object(),
        lifecycle_settlements=(
            {
                "ticker": "010420",
                "isu_cd": "KR7010420008",
                "market": "KOSPI",
                "identity_effective_from": "2010-01-04",
                "identity_effective_to": "2025-05-29",
                "settlement_date": "2025-09-08",
                "settlement_price": 1900.0,
                "settlement_type": "CASH_PER_SHARE",
                "terminal_reason": "SHARE_EXCHANGE_CASH_SETTLEMENT",
                "settlement_source": "https://kind.krx.co.kr/external/fixture.htm",
            },
        ),
    )

    result = runner._process_ticker("010420", run)

    assert captured["cutoff_date"] == pd.Timestamp("2026-08-31")
    assert captured["execution_support_date"] == pd.Timestamp("2026-09-01")
    assert loader_bounds["end"] == pd.Timestamp("2026-09-01")
    assert captured["signal_cutoff_date"] == pd.Timestamp("2026-08-31")
    assert captured["entry_signal_cutoff_date"] == pd.Timestamp("2025-05-29")
    assert captured["entry_execution_cutoff_date"] == pd.Timestamp("2025-05-29")
    assert result["control_rows"][0]["trade_status"] == "LIFECYCLE_SETTLED"
    assert result["candidate_rows"][0]["trade_status"] == "LIFECYCLE_SETTLED"
    assert result["control_rows"][0]["terminal_return"] == 0.69
    assert result["candidate_rows"][0]["execution_support_missing"] is False


def test_confirmed_settlement_matches_stable_isu_after_common_endpoint_changes():
    segment = IdentitySegment(
        ticker="010420",
        isu_cd="KR7010420008",
        market="KOSPI",
        effective_from=pd.Timestamp("2010-01-04"),
        effective_to=pd.Timestamp("2025-05-29"),
    )
    row = {
        **_base_trade(),
        "ticker": segment.ticker,
        "isu_cd": segment.isu_cd,
        "market": segment.market,
        "identity_effective_from": "2010-01-04",
        "identity_effective_to": "2025-05-29",
        "entry_execution_date": "2025-04-14",
        "entry_open": 1887.0,
        "pair_id": "settlement-pair",
        "trade_status": "OPEN_AT_CUTOFF",
        "exit_type": "NO_EXIT",
        "exit_signal_date": None,
        "exit_execution_date": None,
        "exit_price": None,
        "execution_support_missing": True,
    }
    settlement = {
        "evidence_id": "KRX_KIND_SETTLEMENT_FIXTURE",
        "ticker": "010420",
        "isu_cd": "KR7010420008",
        "market": "KOSPI",
        "identity_effective_from": "2010-01-04",
        "identity_effective_to": "2025-09-24",
        "settlement_date": "2025-09-08",
        "settlement_price": 1900.0,
        "settlement_type": "CASH_PER_SHARE",
        "terminal_reason": "SHARE_EXCHANGE_CASH_SETTLEMENT",
        "settlement_source": "https://kind.krx.co.kr/external/fixture.htm",
    }
    daily = pd.DataFrame(
        {
            "open": [1887.0, 1888.0],
            "high": [1900.0, 1890.0],
            "low": [1870.0, 1880.0],
            "close": [1888.0, 1888.0],
        },
        index=pd.to_datetime(["2025-04-14", "2025-09-03"]),
    )

    settled, applied = _apply_lifecycle_settlement(
        row,
        segment=segment,
        evidence=(settlement,),
        cutoff_date=pd.Timestamp("2026-08-31"),
        daily=daily,
    )

    assert applied
    assert settled["trade_status"] == "LIFECYCLE_SETTLED"
    assert settled["terminal_reason"] == "SHARE_EXCHANGE_CASH_SETTLEMENT"
    assert settled["settlement_date"] == "2025-09-08"
    assert settled["settlement_price"] == 1900.0
    assert settled["settlement_type"] == "CASH_PER_SHARE"
    assert settled["terminal_return"] == 0.69
    assert settled["execution_support_missing"] is False
    assert settled["terminal_valuation_at_cutoff"] is False
    assert settled["exit_execution_date"] is None
    assert settled["exit_price"] is None
    assert _outcome_date(settled, "2026-08-31") == "2025-09-08"
    assert _outcome_reason(settled) == "SHARE_EXCHANGE_CASH_SETTLEMENT"


def test_market_exit_before_confirmed_lifecycle_settlement_is_preserved():
    segment = IdentitySegment(
        ticker="010420",
        isu_cd="KR7010420008",
        market="KOSPI",
        effective_from=pd.Timestamp("2010-01-04"),
        effective_to=pd.Timestamp("2025-09-24"),
    )
    settlement = {
        "ticker": "010420",
        "isu_cd": "KR7010420008",
        "market": "KOSPI",
        "identity_effective_from": "2010-01-04",
        "identity_effective_to": "2025-09-24",
        "settlement_date": "2025-09-08",
        "settlement_price": 1900.0,
        "settlement_type": "CASH_PER_SHARE",
        "terminal_reason": "SHARE_EXCHANGE_CASH_SETTLEMENT",
        "settlement_source": "https://kind.krx.co.kr/external/fixture.htm",
    }
    row = {
        "pair_id": "market-exit-first",
        "entry_execution_date": "2025-04-14",
        "entry_open": 1887.0,
        "trade_status": "REALIZED",
        "exit_execution_date": "2025-09-05",
        "terminal_return": 0.11,
    }
    settled, applied = _apply_lifecycle_settlement(
        row,
        segment=segment,
        evidence=(settlement,),
        cutoff_date=pd.Timestamp("2026-08-31"),
        daily=pd.DataFrame(index=pd.to_datetime(["2025-04-14"])),
    )

    assert not applied
    assert settled["trade_status"] == "REALIZED"
    assert settled["exit_execution_date"] == "2025-09-05"
    assert settled["terminal_return"] == 0.11


def test_lifecycle_settlement_evidence_loads_with_official_provenance():
    records = runner._load_lifecycle_settlement_evidence(
        runner.LIFECYCLE_SETTLEMENT_EVIDENCE_PATH
    )

    assert len(records) == 1
    assert records[0]["evidence_status"] == "CONFIRMED"
    assert records[0]["source_authority"] == "KRX_KIND"
    assert records[0]["settlement_source"].startswith("https://kind.krx.co.kr/")


def test_confirmed_settlement_after_common_interval_end_is_accepted(tmp_path: Path):
    record = {
        "evidence_id": "fixture-settlement-after-common-end",
        "evidence_status": "CONFIRMED",
        "ticker": "010420",
        "isu_cd": "KR7010420008",
        "market": "KOSPI",
        "identity_effective_from": "2010-01-04",
        "identity_effective_to": "2025-05-29",
        "settlement_date": "2025-09-08",
        "settlement_price": 1900.0,
        "settlement_type": "CASH_PER_SHARE",
        "terminal_reason": "SHARE_EXCHANGE_CASH_SETTLEMENT",
        "settlement_source": "https://kind.krx.co.kr/external/fixture.htm",
        "source_authority": "KRX_KIND",
        "source_document_id": "fixture-document",
        "source_published_date": "2025-09-01",
    }
    evidence_path = tmp_path / "settlement.json"
    evidence_path.write_text(
        json.dumps({"schema": "lifecycle_settlement_evidence_v01", "records": [record]}),
        encoding="utf-8",
    )

    loaded = runner._load_lifecycle_settlement_evidence(evidence_path)

    assert len(loaded) == 1
    assert loaded[0]["settlement_date"] == "2025-09-08"
    assert loaded[0]["identity_effective_to"] == "2025-05-29"


def test_settlement_event_deduplication_ignores_common_interval_endpoint(tmp_path: Path):
    record = {
        "evidence_id": "fixture-event-original",
        "evidence_status": "CONFIRMED",
        "ticker": "010420",
        "isu_cd": "KR7010420008",
        "market": "KOSPI",
        "identity_effective_from": "2010-01-04",
        "identity_effective_to": "2025-05-29",
        "settlement_date": "2025-09-08",
        "settlement_price": 1900.0,
        "settlement_type": "CASH_PER_SHARE",
        "terminal_reason": "SHARE_EXCHANGE_CASH_SETTLEMENT",
        "settlement_source": "https://kind.krx.co.kr/external/fixture.htm",
        "source_authority": "KRX_KIND",
        "source_document_id": "fixture-document",
        "source_published_date": "2025-09-01",
    }
    revised_interval = {
        **record,
        "evidence_id": "fixture-event-revised-interval",
        "identity_effective_to": "2026-08-31",
    }
    evidence_path = tmp_path / "duplicate-settlement-event.json"
    evidence_path.write_text(
        json.dumps(
            {
                "schema": "lifecycle_settlement_evidence_v01",
                "records": [record, revised_interval],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="duplicate lifecycle settlement event"):
        runner._load_lifecycle_settlement_evidence(evidence_path)


def test_common_interval_end_without_lifecycle_evidence_does_not_settle_open_trade():
    segment = IdentitySegment(
        ticker="000001",
        isu_cd="KR7000000001",
        market="KOSPI",
        effective_from=pd.Timestamp("2025-01-01"),
        effective_to=pd.Timestamp("2025-01-07"),
    )
    row = {
        **_base_trade(),
        "ticker": segment.ticker,
        "isu_cd": segment.isu_cd,
        "market": segment.market,
        "identity_effective_from": "2025-01-01",
        "identity_effective_to": "2025-01-07",
        "trade_status": "OPEN_AT_CUTOFF",
    }

    unchanged, applied = _apply_lifecycle_settlement(
        row,
        segment=segment,
        evidence=(),
        cutoff_date=pd.Timestamp("2025-01-10"),
        daily=_daily([100.0, 101.0, 102.0]),
    )

    assert not applied
    assert unchanged["trade_status"] == "OPEN_AT_CUTOFF"
    assert unchanged.get("settlement_date") is None


def test_settlement_after_window_cutoff_is_not_applied_even_after_common_end():
    segment = IdentitySegment(
        ticker="010420",
        isu_cd="KR7010420008",
        market="KOSPI",
        effective_from=pd.Timestamp("2010-01-04"),
        effective_to=pd.Timestamp("2025-05-29"),
    )
    settlement = {
        "ticker": "010420",
        "isu_cd": "KR7010420008",
        "market": "KOSPI",
        "identity_effective_from": "2010-01-04",
        "identity_effective_to": "2025-05-29",
        "settlement_date": "2025-09-08",
        "settlement_price": 1900.0,
        "settlement_type": "CASH_PER_SHARE",
        "terminal_reason": "SHARE_EXCHANGE_CASH_SETTLEMENT",
        "settlement_source": "https://kind.krx.co.kr/external/fixture.htm",
    }
    row = {
        **_base_trade(),
        "ticker": segment.ticker,
        "isu_cd": segment.isu_cd,
        "market": segment.market,
        "identity_effective_from": "2010-01-04",
        "identity_effective_to": "2025-05-29",
        "entry_execution_date": "2025-04-14",
        "entry_open": 1887.0,
        "trade_status": "OPEN_AT_CUTOFF",
    }

    unchanged, applied = _apply_lifecycle_settlement(
        row,
        segment=segment,
        evidence=(settlement,),
        cutoff_date=pd.Timestamp("2025-08-31"),
        daily=_daily([100.0, 101.0, 102.0]),
    )

    assert not applied
    assert unchanged["trade_status"] == "OPEN_AT_CUTOFF"


def test_soft_signal_without_open_is_accepted_only_with_lifecycle_settlement_terminal():
    diagnostics = [
        {
            "soft_events": [
                {
                    "trade_id": "010420_02",
                    "pair_id": "settled-soft-pair",
                    "ticker": "010420",
                    "date": "2025-09-03",
                    "close_return": -40.2,
                    "pattern_a_stage": "BASE",
                    "event_type": "SOFT_EXIT_SIGNAL",
                    "execution_date": None,
                    "execution_open": None,
                }
            ]
        }
    ]
    candidate = pd.DataFrame(
        [
            {
                "trade_id": "010420_02",
                "pair_id": "settled-soft-pair",
                "ticker": "010420",
                "isu_cd": "KR7010420008",
                "market": "KOSPI",
                "identity_effective_from": "2010-01-04",
                "identity_effective_to": "2025-05-29",
                "candidate_action": "SOFT_EXIT",
                "trade_status": "LIFECYCLE_SETTLED",
                "exit_signal_date": "2025-09-03",
                "exit_execution_date": None,
                "exit_price": None,
                "execution_support_missing": False,
                "terminal_reason": "SHARE_EXCHANGE_CASH_SETTLEMENT",
                "settlement_date": "2025-09-08",
                "settlement_price": 1900.0,
                "settlement_type": "CASH_PER_SHARE",
                "settlement_source": "https://kind.krx.co.kr/external/fixture.htm",
                "terminal_valuation_at_cutoff": False,
            }
        ]
    )

    events = runner._build_soft_event_ledger(diagnostics, candidate)

    assert len(events) == 1
    assert events.iloc[0]["event_type"] == "SOFT_EXIT_SIGNAL"
    assert pd.isna(events.iloc[0]["execution_date"])
