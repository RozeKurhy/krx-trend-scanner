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


def _lifecycle_calendar():
    return SimpleNamespace(
        trading_dates=pd.to_datetime(
            ["2025-05-28", "2025-05-29", "2025-05-30", "2025-06-02", "2025-06-03", "2025-06-20"]
        )
    )


def _open_lifecycle_row(segment: IdentitySegment, *, entry_open: float = 100.0) -> dict:
    return {
        "ticker": segment.ticker,
        "isu_cd": segment.isu_cd,
        "market": segment.market,
        "pair_id": "lifecycle-pair",
        "trade_id": "lifecycle-trade",
        "entry_execution_date": "2025-05-28",
        "entry_open": entry_open,
        "exit_signal_date": None,
        "exit_execution_date": None,
        "exit_price": None,
        "exit_type": "NO_EXIT",
        "trade_status": "OPEN_AT_CUTOFF",
        "terminal_return": 0.0,
        "terminal_valuation_date": "2025-05-29",
        "terminal_valuation_price": 100.0,
        "execution_support_missing": False,
    }


def _confirmed_cash_event(segment: IdentitySegment, **overrides) -> dict:
    return {
        "evidence_id": "cash-fixture",
        "event_evidence_status": "CONFIRMED",
        "economic_terms_status": "CONFIRMED",
        "ticker": segment.ticker,
        "isu_cd": segment.isu_cd,
        "market": segment.market,
        "event_type": "MANDATORY_CASH",
        "event_effective_date": "2025-05-30",
        "source_published_date": "2025-05-01",
        "cash_per_share": 90.0,
        "payment_date": "2025-06-20",
        **overrides,
    }


def test_typed_cash_event_at_cutoff_values_receivable_without_future_payment_lookahead():
    segment = IdentitySegment(
        ticker="029960",
        isu_cd="KR7029960002",
        market="KOSDAQ",
        effective_from=pd.Timestamp("2010-01-04"),
        effective_to=pd.Timestamp("2025-05-29"),
    )
    sparse_source_daily = pd.DataFrame(
        {"open": [100.0, 101.0], "high": [102.0, 103.0], "low": [99.0, 100.0], "close": [101.0, 102.0]},
        index=pd.to_datetime(["2025-05-28", "2025-05-29"]),
    )

    valued, applied = runner._apply_lifecycle_event(
        _open_lifecycle_row(segment),
        segment=segment,
        event=_confirmed_cash_event(segment, cash_per_share=90.0),
        cutoff_date=pd.Timestamp("2025-05-30"),
        source_daily=sparse_source_daily,
        calendar=_lifecycle_calendar(),
    )

    assert applied
    assert valued["lifecycle_state"] == "SETTLEMENT_PENDING"
    assert valued["trade_status"] == "OPEN_AT_CUTOFF"
    assert valued["settlement_date"] == "2025-06-20"
    assert valued["terminal_valuation_date"] == "2025-05-30"
    assert valued["terminal_valuation_price"] == 90.0
    assert valued["terminal_return"] == -10.0
    assert valued["holding_days"] == 3
    assert valued["terminal_valuation_at_cutoff"] is True


def test_typed_lifecycle_event_published_after_cutoff_fails_closed_without_lookahead():
    segment = IdentitySegment(
        ticker="029960",
        isu_cd="KR7029960002",
        market="KOSDAQ",
        effective_from=pd.Timestamp("2010-01-04"),
        effective_to=pd.Timestamp("2025-05-30"),
    )
    valued, applied = runner._apply_lifecycle_event(
        _open_lifecycle_row(segment),
        segment=segment,
        event=_confirmed_cash_event(segment, source_published_date="2025-06-10"),
        cutoff_date=pd.Timestamp("2025-05-30"),
        source_daily=_daily([100.0, 101.0]),
        calendar=_lifecycle_calendar(),
    )

    assert not applied
    assert "lifecycle_state" not in valued
    assert valued["terminal_return"] == 0.0


def test_confirmed_cash_event_with_partial_terms_keeps_known_receivable_pending():
    segment = IdentitySegment(
        ticker="029960",
        isu_cd="KR7029960002",
        market="KOSDAQ",
        effective_from=pd.Timestamp("2010-01-04"),
        effective_to=pd.Timestamp("2025-05-29"),
    )
    event = _confirmed_cash_event(
        segment,
        economic_terms_status="PARTIAL",
        payment_date=None,
    )

    valued, applied = runner._apply_lifecycle_event(
        _open_lifecycle_row(segment),
        segment=segment,
        event=event,
        cutoff_date=pd.Timestamp("2025-05-30"),
        source_daily=pd.DataFrame(
            {"open": [100.0], "high": [102.0], "low": [99.0], "close": [101.0]},
            index=pd.to_datetime(["2025-05-29"]),
        ),
        calendar=_lifecycle_calendar(),
    )

    assert applied
    assert valued["lifecycle_state"] == "SETTLEMENT_PENDING"
    assert valued["settlement_date"] is None
    assert valued["terminal_valuation_price"] == 90.0
    assert valued["terminal_valuation_at_cutoff"] is True
    assert valued["terminal_return"] == -10.0


def test_confirmed_share_event_with_partial_terms_stops_with_unresolved_successor():
    segment = IdentitySegment(
        ticker="000001",
        isu_cd="KR7000000001",
        market="KOSPI",
        effective_from=pd.Timestamp("2020-01-01"),
        effective_to=pd.Timestamp("2025-12-31"),
    )
    event = {
        "evidence_id": "partial-share-fixture",
        "event_evidence_status": "CONFIRMED",
        "economic_terms_status": "PARTIAL",
        "ticker": segment.ticker,
        "isu_cd": segment.isu_cd,
        "market": segment.market,
        "event_type": "MANDATORY_SHARE_EXCHANGE",
        "event_effective_date": "2025-05-30",
        "source_published_date": "2025-05-01",
        "official_source_refs": [{"url": "https://kind.krx.co.kr/external/fixture.htm"}],
    }

    unresolved, applied = runner._apply_lifecycle_event(
        _open_lifecycle_row(segment),
        segment=segment,
        event=event,
        cutoff_date=pd.Timestamp("2025-06-02"),
        source_daily=_daily([100.0, 101.0]),
        calendar=_lifecycle_calendar(),
    )

    assert applied
    assert unresolved["lifecycle_state"] == "UNRESOLVED_SUCCESSOR"
    assert unresolved["lifecycle_certification_class"] == runner.REMEDIABLE_UNRESOLVED
    assert unresolved["terminal_return"] is None
    assert unresolved["terminal_valuation_price"] is None


def test_share_exchange_without_successor_availability_is_remediable_unresolved():
    segment = IdentitySegment(
        ticker="000001",
        isu_cd="KR7000000001",
        market="KOSPI",
        effective_from=pd.Timestamp("2020-01-01"),
        effective_to=pd.Timestamp("2025-12-31"),
    )
    event = {
        "evidence_id": "missing-availability-fixture",
        "event_evidence_status": "CONFIRMED",
        "economic_terms_status": "PARTIAL",
        "ticker": segment.ticker,
        "isu_cd": segment.isu_cd,
        "market": segment.market,
        "event_type": "MANDATORY_SHARE_EXCHANGE",
        "event_effective_date": "2025-05-30",
        "source_published_date": "2025-05-01",
        "successor_ticker": "999999",
        "successor_isu_cd": "KR7999990009",
        "successor_market": "KOSPI",
        "conversion_ratio": 0.5,
    }

    unresolved, applied = runner._apply_lifecycle_event(
        _open_lifecycle_row(segment),
        segment=segment,
        event=event,
        cutoff_date=pd.Timestamp("2025-06-02"),
        source_daily=_daily([100.0, 101.0]),
        calendar=_lifecycle_calendar(),
        successor_identity_validated=True,
    )

    assert applied
    assert unresolved["lifecycle_state"] == "UNRESOLVED_SUCCESSOR"
    assert unresolved["lifecycle_certification_class"] == runner.REMEDIABLE_UNRESOLVED
    assert unresolved["terminal_return"] is None


def test_successor_availability_published_after_cutoff_fails_closed_without_lookahead():
    segment = IdentitySegment(
        ticker="000001",
        isu_cd="KR7000000001",
        market="KOSPI",
        effective_from=pd.Timestamp("2020-01-01"),
        effective_to=pd.Timestamp("2025-12-31"),
    )
    event = {
        "evidence_id": "future-availability-fixture",
        "event_evidence_status": "CONFIRMED",
        "economic_terms_status": "PARTIAL",
        "ticker": segment.ticker,
        "isu_cd": segment.isu_cd,
        "market": segment.market,
        "event_type": "MANDATORY_SHARE_EXCHANGE",
        "event_effective_date": "2025-05-30",
        "event_effective_date_known_from": "2025-05-01",
        "source_published_date": "2025-05-01",
        "successor_ticker": "999999",
        "successor_isu_cd": "KR7999990009",
        "successor_market": "KOSPI",
        "successor_identity_known_from": "2025-05-01",
        "conversion_ratio": 0.5,
        "conversion_ratio_known_from": "2025-05-01",
        "successor_available_date": "2025-06-03",
        "successor_available_date_known_from": "2025-06-03",
    }

    unresolved, applied = runner._apply_lifecycle_event(
        _open_lifecycle_row(segment),
        segment=segment,
        event=event,
        cutoff_date=pd.Timestamp("2025-06-02"),
        source_daily=_daily([100.0, 101.0]),
        calendar=_lifecycle_calendar(),
        successor_identity_validated=True,
    )

    assert applied
    assert unresolved["lifecycle_state"] == "UNRESOLVED_SUCCESSOR"
    assert unresolved["lifecycle_certification_class"] == runner.REMEDIABLE_UNRESOLVED
    assert "published after the replay cutoff" in unresolved["lifecycle_unresolved_reason"]
    assert unresolved["terminal_return"] is None


def test_check_required_event_is_not_applied_even_with_confirmed_economics():
    segment = IdentitySegment(
        ticker="029960",
        isu_cd="KR7029960002",
        market="KOSDAQ",
        effective_from=pd.Timestamp("2010-01-04"),
        effective_to=pd.Timestamp("2025-05-29"),
    )
    event = _confirmed_cash_event(segment, event_evidence_status="CHECK_REQUIRED")

    unchanged, applied = runner._apply_lifecycle_event(
        _open_lifecycle_row(segment),
        segment=segment,
        event=event,
        cutoff_date=pd.Timestamp("2025-05-30"),
        source_daily=_daily([100.0, 101.0]),
        calendar=_lifecycle_calendar(),
    )

    assert not applied
    assert "lifecycle_state" not in unchanged
    assert unchanged["terminal_return"] == 0.0


def test_typed_lifecycle_event_rejects_wrong_source_ticker_or_market():
    segment = IdentitySegment(
        ticker="029960",
        isu_cd="KR7029960002",
        market="KOSDAQ",
        effective_from=pd.Timestamp("2010-01-04"),
        effective_to=pd.Timestamp("2025-05-29"),
    )
    for override in ({"ticker": "000001"}, {"market": "KOSPI"}):
        with pytest.raises(RuntimeError, match="lifecycle source identity mismatch"):
            runner._apply_lifecycle_event(
                _open_lifecycle_row(segment),
                segment=segment,
                event=_confirmed_cash_event(segment, **override),
                cutoff_date=pd.Timestamp("2025-05-30"),
                source_daily=_daily([100.0, 101.0]),
                calendar=_lifecycle_calendar(),
            )


def test_lifecycle_event_uses_stable_isu_and_validates_ticker_market_at_event_context():
    entry_segment = IdentitySegment(
        ticker="000001",
        isu_cd="KR7000000001",
        market="KOSDAQ",
        effective_from=pd.Timestamp("2025-01-01"),
        effective_to=pd.Timestamp("2025-05-29"),
    )
    event_segment = IdentitySegment(
        ticker="000002",
        isu_cd="KR7000000001",
        market="KOSPI",
        effective_from=pd.Timestamp("2025-05-30"),
        effective_to=pd.Timestamp("2025-12-31"),
    )
    event = {
        **_confirmed_cash_event(entry_segment),
        "ticker": "000002",
        "market": "KOSPI",
        "source_ticker": "000002",
        "source_market": "KOSPI",
    }

    matched = runner._confirmed_lifecycle_event_for_segment(
        entry_segment,
        (event,),
        pd.Timestamp("2025-06-02"),
        {"000001": (entry_segment,), "000002": (event_segment,)},
    )
    assert matched["isu_cd"] == entry_segment.stable_security_id
    assert matched["ticker"] == "000002"

    with pytest.raises(RuntimeError, match="conflicts with PIT identity at event date"):
        runner._confirmed_lifecycle_event_for_segment(
            entry_segment,
            ({**event, "ticker": "000003", "source_ticker": "000003"},),
            pd.Timestamp("2025-06-02"),
            {"000001": (entry_segment,), "000002": (event_segment,)},
        )


def test_typed_share_exchange_carries_only_economics_and_requires_successor_cutoff_price():
    segment = IdentitySegment(
        ticker="000001",
        isu_cd="KR7000000001",
        market="KOSPI",
        effective_from=pd.Timestamp("2020-01-01"),
        effective_to=pd.Timestamp("2025-12-31"),
    )
    event = {
        "evidence_id": "exchange-fixture",
        "event_evidence_status": "CONFIRMED",
        "economic_terms_status": "PARTIAL",
        "ticker": segment.ticker,
        "isu_cd": segment.isu_cd,
        "market": segment.market,
        "event_type": "MANDATORY_SHARE_EXCHANGE",
        "event_effective_date": "2025-05-30",
        "source_published_date": "2025-05-01",
        "successor_ticker": "999999",
        "successor_isu_cd": "KR7999990009",
        "successor_market": "KOSPI",
        "conversion_ratio": 0.25,
        "successor_available_date": "2025-06-02",
    }
    successor_daily = pd.DataFrame(
        {"open": [118.0], "high": [125.0], "low": [115.0], "close": [120.0]},
        index=pd.to_datetime(["2025-06-02"]),
    )
    row = _open_lifecycle_row(segment)
    row["pattern_a_stage_at_cutoff"] = "WEAK"
    row["candidate_action"] = "CONTROL_PRESERVED"

    valued, applied = runner._apply_lifecycle_event(
        row,
        segment=segment,
        event=event,
        cutoff_date=pd.Timestamp("2025-06-02"),
        source_daily=_daily([100.0, 101.0]),
        calendar=_lifecycle_calendar(),
        successor_daily=successor_daily,
        successor_identity_validated=True,
    )

    assert applied
    assert valued["lifecycle_state"] == "SUCCESSOR_POSITION"
    assert valued["successor_quantity"] == 0.25
    assert valued["fractional_cash"] == 0.0
    assert valued["successor_valuation_basis"] == "NORMALIZED_FRACTIONAL_QUANTITY_X_SUCCESSOR_CLOSE"
    assert valued["terminal_valuation_price"] == 30.0
    assert valued["terminal_return"] == -70.0
    assert valued["pattern_a_stage_at_cutoff"] == "WEAK"
    assert valued["candidate_action"] == "CONTROL_PRESERVED"

    pending, applied = runner._apply_lifecycle_event(
        row,
        segment=segment,
        event=event,
        cutoff_date=pd.Timestamp("2025-06-03"),
        source_daily=_daily([100.0, 101.0]),
        calendar=_lifecycle_calendar(),
        successor_daily=successor_daily,
        successor_identity_validated=True,
    )
    assert applied
    assert pending["lifecycle_state"] == "SUCCESSOR_PENDING"
    assert pending["terminal_return"] is None


def test_optional_right_never_uses_offer_price_and_liquidation_is_unresolved():
    segment = IdentitySegment(
        ticker="000001",
        isu_cd="KR7000000001",
        market="KOSPI",
        effective_from=pd.Timestamp("2020-01-01"),
        effective_to=pd.Timestamp("2025-12-31"),
    )
    optional = {
        "evidence_id": "optional-fixture",
        "event_evidence_status": "CONFIRMED",
        "economic_terms_status": "UNRESOLVED",
        "ticker": segment.ticker,
        "isu_cd": segment.isu_cd,
        "market": segment.market,
        "event_type": "OPTIONAL_RIGHT",
        "event_effective_date": "2025-05-30",
        "source_published_date": "2025-05-01",
        "holder_action_required": True,
        "offer_price": 999.0,
        "delisting_date": "2025-05-30",
    }
    unresolved, applied = runner._apply_lifecycle_event(
        _open_lifecycle_row(segment),
        segment=segment,
        event=optional,
        cutoff_date=pd.Timestamp("2025-06-02"),
        source_daily=_daily([100.0, 101.0]),
        calendar=_lifecycle_calendar(),
    )
    assert applied
    assert unresolved["lifecycle_state"] == "UNRESOLVED_POST_DELIST_VALUE"
    assert unresolved["terminal_return"] is None
    assert unresolved["terminal_valuation_price"] is None

    still_listed, applied = runner._apply_lifecycle_event(
        _open_lifecycle_row(segment),
        segment=segment,
        event={key: value for key, value in optional.items() if key != "delisting_date"},
        cutoff_date=pd.Timestamp("2025-06-02"),
        source_daily=_daily([100.0, 101.0]),
        calendar=_lifecycle_calendar(),
    )
    assert not applied
    assert still_listed["terminal_return"] == 0.0
    assert still_listed.get("settlement_price") is None

    liquidation, applied = runner._apply_lifecycle_event(
        _open_lifecycle_row(segment),
        segment=segment,
        event={**optional, "event_type": "LIQUIDATION_UNRESOLVED", "evidence_id": "liquidation-fixture"},
        cutoff_date=pd.Timestamp("2025-06-02"),
        source_daily=_daily([100.0, 101.0]),
        calendar=_lifecycle_calendar(),
    )
    assert applied
    assert liquidation["lifecycle_state"] == "UNRESOLVED_SETTLEMENT"
    assert liquidation["terminal_return"] is None


def test_v02_catalog_preserves_all_22_roster_entries_with_split_statuses():
    records = runner._load_lifecycle_event_evidence(runner.LIFECYCLE_EVENT_EVIDENCE_V02_PATH)
    type_counts = {}
    for record in records:
        type_counts[record["event_type"]] = type_counts.get(record["event_type"], 0) + 1

    assert len(records) == 22
    assert type_counts == {
        "MANDATORY_CASH": 5,
        "MANDATORY_SHARE_EXCHANGE": 13,
        "OPTIONAL_RIGHT": 3,
        "LIQUIDATION_UNRESOLVED": 1,
    }
    assert {record["event_evidence_status"] for record in records} == {"CONFIRMED"}
    audit_counts = {}
    for record in records:
        audit_counts[record["audit_classification"]] = audit_counts.get(record["audit_classification"], 0) + 1
    assert audit_counts == {
        "SETTLEMENT_CONFIRMED": 17,
        "LIFECYCLE_EVENT_CONFIRMED": 3,
        "CHECK_REQUIRED": 2,
    }
    assert {record["economic_terms_status"] for record in records} <= {
        "CONFIRMED",
        "PARTIAL",
        "UNRESOLVED",
        "NOT_APPLICABLE",
    }
    by_ticker = {record["ticker"]: record for record in records}
    assert by_ticker["029960"]["event_evidence_status"] == "CONFIRMED"
    assert by_ticker["029960"]["economic_terms_status"] == "CONFIRMED"
    assert by_ticker["029960"]["payment_date"] == "2025-06-20"
    assert by_ticker["029960"]["payment_date_known_from"] == "2025-06-10"
    for ticker, event_date, amount, payment_date in (
        ("115390", "2024-11-22", 8750, "2024-12-06"),
        ("138580", "2024-11-08", 15849, "2024-11-29"),
        ("230360", "2026-06-15", 16000, "2026-07-09"),
    ):
        record = by_ticker[ticker]
        assert record["event_evidence_status"] == "CONFIRMED"
        assert record["economic_terms_status"] == "CONFIRMED"
        assert record["event_effective_date"] == event_date
        assert record["cash_consideration_per_source_share"] == amount
        assert record["payment_date"] == payment_date
    locknlock = by_ticker["115390"]
    assert locknlock["source_published_date"] == "2024-08-30"
    assert len(locknlock["official_source_refs"]) == 3
    assert "2024-11-24" in locknlock["official_source_refs"][2]["supports"][0]
    assert by_ticker["006390"]["event_evidence_status"] == "CONFIRMED"
    assert by_ticker["006390"]["economic_terms_status"] == "PARTIAL"
    assert by_ticker["096300"]["event_evidence_status"] == "CONFIRMED"
    assert by_ticker["096300"]["economic_terms_status"] == "UNRESOLVED"
    assert by_ticker["096300"]["dissolution_date"] == "2023-02-01"
    assert by_ticker["096300"]["dissolution_date_known_from"] == "2022-12-26"
    assert by_ticker["096300"]["delisting_date"] == "2023-02-02"
    assert by_ticker["096300"]["observed_facts"]["pre_liquidation_estimate_per_share"] == 72.58
    assert by_ticker["096300"]["observed_facts"]["earlier_partial_cash_distribution_per_share"] == 150
    assert "payment_date" not in by_ticker["096300"]
    assert "liquidation_distribution_per_source_share" not in by_ticker["096300"]
    assert any(
        source["url"] == "https://kind.krx.co.kr/common/disclsviewer.do?acptno=20221226000898&method=search"
        for source in by_ticker["096300"]["official_source_refs"]
    )
    assert "successor_ticker" in by_ticker["006390"]["unresolved_fields"]
    assert "distribution_per_share" in by_ticker["096300"]["unresolved_fields"]
    for ticker in ("005390", "335890", "950110"):
        assert by_ticker[ticker]["event_type"] == "OPTIONAL_RIGHT"
        assert by_ticker[ticker]["requires_holder_action"] is True
        assert by_ticker[ticker]["offer_price"] > 0

    combined = runner._load_lifecycle_event_catalog()
    assert len(combined) == 23
    assert combined[0]["isu_cd"] == "KR7010420008"
    assert sum(record.get("event_evidence_status") == "CONFIRMED" for record in combined) == 23


def test_096300_liquidation_closure_remains_unresolved_and_runtime_fails_closed():
    record = next(
        item
        for item in runner._load_lifecycle_event_evidence(
            runner.LIFECYCLE_EVENT_EVIDENCE_V02_PATH
        )
        if item["source_ticker"] == "096300"
    )
    assert record["event_evidence_status"] == "CONFIRMED"
    assert record["economic_terms_status"] == "UNRESOLVED"
    assert record["event_effective_date"] == record["delisting_date"] == "2023-02-02"
    assert record["dissolution_date"] == "2023-02-01"
    assert {"distribution_per_share", "payment_date", "liquidation_close_date"} <= set(
        record["unresolved_fields"]
    )
    assert not record.get("liquidation_distribution_per_source_share")
    assert not record.get("payment_date")

    segment = IdentitySegment(
        ticker="096300",
        isu_cd="KR7096300009",
        market="KOSPI",
        effective_from=pd.Timestamp("2020-01-01"),
        effective_to=pd.Timestamp("2023-02-01"),
    )
    row = _open_lifecycle_row(segment)
    row["entry_execution_date"] = "2023-01-30"
    source_daily = _daily([100.0, 101.0]).set_axis(
        pd.to_datetime(["2023-01-30", "2023-01-31"])
    )

    before_event, applied = runner._apply_lifecycle_event(
        row,
        segment=segment,
        event=record,
        cutoff_date=pd.Timestamp("2023-02-01"),
        source_daily=source_daily,
        calendar=SimpleNamespace(trading_dates=pd.to_datetime(["2023-01-30", "2023-01-31"])),
    )
    assert not applied
    assert before_event["terminal_return"] == 0.0

    unresolved, applied = runner._apply_lifecycle_event(
        row,
        segment=segment,
        event=record,
        cutoff_date=pd.Timestamp("2023-02-02"),
        source_daily=source_daily,
        calendar=SimpleNamespace(trading_dates=pd.to_datetime(["2023-01-30", "2023-01-31"])),
    )
    assert applied
    assert unresolved["lifecycle_state"] == "UNRESOLVED_SETTLEMENT"
    assert unresolved["lifecycle_certification_class"] == runner.AUTHORITATIVE_FINAL_UNRESOLVED
    assert unresolved["terminal_return"] is None
    assert unresolved["terminal_valuation_date"] is None
    assert unresolved["terminal_valuation_price"] is None
    assert unresolved.get("settlement_price") is None


def test_029960_catalog_retains_later_payment_fact_without_cutoff_lookahead():
    segment = IdentitySegment(
        ticker="029960",
        isu_cd="KR7029960002",
        market="KOSDAQ",
        effective_from=pd.Timestamp("2010-01-04"),
        effective_to=pd.Timestamp("2025-05-29"),
    )
    event = next(
        record
        for record in runner._load_lifecycle_event_evidence(runner.LIFECYCLE_EVENT_EVIDENCE_V02_PATH)
        if record["ticker"] == "029960"
    )
    source_daily = pd.DataFrame(
        {
            "open": [10000.0, 10000.0],
            "high": [10100.0, 10200.0],
            "low": [9900.0, 9800.0],
            "close": [10000.0, 9900.0],
        },
        index=pd.to_datetime(["2025-05-28", "2025-05-29"]),
    )

    early, applied = runner._apply_lifecycle_event(
        _open_lifecycle_row(segment, entry_open=10000.0),
        segment=segment,
        event=event,
        cutoff_date=pd.Timestamp("2025-05-30"),
        source_daily=source_daily,
        calendar=_lifecycle_calendar(),
    )
    assert applied
    assert early["lifecycle_state"] == "SETTLEMENT_PENDING"
    assert early["settlement_date"] is None
    assert early["terminal_valuation_price"] == 9000.0
    assert early["terminal_return"] == -10.0

    later, applied = runner._apply_lifecycle_event(
        _open_lifecycle_row(segment, entry_open=10000.0),
        segment=segment,
        event=event,
        cutoff_date=pd.Timestamp("2025-06-25"),
        source_daily=source_daily,
        calendar=_lifecycle_calendar(),
    )
    assert applied
    assert later["lifecycle_state"] == "SETTLED"
    assert later["settlement_date"] == "2025-06-20"
    assert later["terminal_valuation_date"] == "2025-06-20"
    assert later["terminal_valuation_price"] == 9000.0

@pytest.mark.parametrize("window_id", ["P2-1", "P2-2", "P3-1"])
@pytest.mark.parametrize("event_type", ["MANDATORY_CASH", "MANDATORY_SHARE_EXCHANGE"])
def test_lifecycle_strategy_horizon_stops_source_signal_simulation_before_action(
    monkeypatch,
    window_id,
    event_type,
):
    segment = IdentitySegment(
        ticker="029960",
        isu_cd="KR7029960002",
        market="KOSDAQ",
        effective_from=pd.Timestamp("2025-01-01"),
        effective_to=pd.Timestamp("2025-05-29"),
    )
    full_daily = pd.DataFrame(
        {"open": [100.0, 101.0, 80.0, 81.0, 82.0], "high": [101.0, 102.0, 81.0, 82.0, 83.0],
         "low": [99.0, 100.0, 79.0, 80.0, 81.0], "close": [100.0, 101.0, 80.0, 81.0, 82.0]},
        index=pd.to_datetime(["2025-05-28", "2025-05-29", "2025-05-30", "2025-06-02", "2025-06-03"]),
    )
    captured = {}

    class FakeLoader:
        def __init__(self, repository, *, start, end):
            self.load_count = 0

        def load(self, ticker):
            self.load_count += 1
            return full_daily.copy()

    class FakeRecord:
        entry_signal_date = "2025-05-28"
        entry_execution_date = "2025-05-29"
        entry_open = 101.0
        trade_id = "029960_01"
        exit_signal_date = None
        exit_execution_date = None
        first_progressed_effective_trading_date = None

        def to_dict(self):
            return {
                "ticker": "029960", "name": "029960", "market": "KOSDAQ", "trade_id": self.trade_id,
                "trade_sequence": 1, "entry_signal_date": self.entry_signal_date,
                "entry_execution_date": self.entry_execution_date, "entry_open": self.entry_open,
                "entry_pattern_a_stage": "EARLY_TREND", "first_progressed_effective_trading_date": None,
                "exit_type": "NO_EXIT", "exit_signal_date": None, "exit_execution_date": None,
                "exit_price": None, "terminal_return": 0.0, "mfe": 0.0, "mae": 0.0,
                "peak_giveback": 0.0, "profit_capture": None, "holding_weeks": 0.4,
                "trade_status": "OPEN_AT_CUTOFF",
            }

    def fake_simulator(**kwargs):
        captured["last_source_date"] = kwargs["daily"].index.max().strftime("%Y-%m-%d")
        captured["signal_cutoff_date"] = kwargs["signal_cutoff_date"]
        captured["execution_support_date"] = kwargs["execution_support_date"]
        captured["entry_execution_cutoff_date"] = kwargs["entry_execution_cutoff_date"]
        return [FakeRecord()]

    monkeypatch.setattr(runner, "RepositoryV2DailyLoader", FakeLoader)
    monkeypatch.setattr(runner.v2, "build_precomputed_ticker_context", lambda *args: object())
    monkeypatch.setattr(runner.v2, "simulate_ticker_core_v02_reentry", fake_simulator)
    event = _confirmed_cash_event(segment)
    event["source_identity_context_verified"] = True
    segments_by_ticker = {"029960": (segment,)}
    expected_lifecycle_state = "SETTLEMENT_PENDING"
    if event_type == "MANDATORY_SHARE_EXCHANGE":
        successor_segment = IdentitySegment(
            ticker="001234",
            isu_cd="KR7001230004",
            market="KOSPI",
            effective_from=pd.Timestamp("2025-05-30"),
            effective_to=pd.Timestamp("2025-12-31"),
        )
        event.update(
            {
                "event_type": "MANDATORY_SHARE_EXCHANGE",
                "successor_ticker": successor_segment.ticker,
                "successor_isu_cd": successor_segment.isu_cd,
                "successor_market": successor_segment.market,
                "conversion_ratio": 1.0,
                "successor_available_date": "2025-05-30",
                "fractional_cash_rule": "NO_FRACTIONAL_CASH_REQUIRED",
            }
        )
        segments_by_ticker[successor_segment.ticker] = (successor_segment,)
        expected_lifecycle_state = "SUCCESSOR_POSITION"
    run = SimpleNamespace(
        window=SimpleNamespace(
            window=SimpleNamespace(window_id=window_id),
            effective_start=pd.Timestamp("2025-01-01"),
            effective_end=pd.Timestamp("2025-06-02"),
            execution_support=pd.Timestamp("2025-06-03"),
        ),
        segments_by_ticker=segments_by_ticker,
        loader=SimpleNamespace(repository=object()),
        score_contract={},
        stage_contract={},
        calendar=_lifecycle_calendar(),
        lifecycle_settlements=(event,),
    )

    result = runner._process_ticker("029960", run)

    assert captured["last_source_date"] == "2025-05-29"
    assert captured["entry_execution_cutoff_date"] == pd.Timestamp("2025-05-29")
    assert captured["signal_cutoff_date"] == pd.Timestamp("2025-06-02")
    assert captured["execution_support_date"] == pd.Timestamp("2025-06-03")
    assert result["control_rows"][0]["lifecycle_state"] == expected_lifecycle_state
    assert result["candidate_rows"][0]["lifecycle_state"] == expected_lifecycle_state
    assert runner._outcome_reason(result["control_rows"][0]) in {
        "MANDATORY_CASH_CORPORATE_ACTION",
        "MANDATORY_SHARE_EXCHANGE_SUCCESSOR_VALUE",
    }
    ledger = runner._build_matched_trade_ledger(
        pd.DataFrame(result["control_rows"]),
        pd.DataFrame(result["candidate_rows"]),
        cutoff_date="2025-06-02",
    )
    assert ledger.loc[0, "control_exit_reason"] == ledger.loc[0, "candidate_exit_reason"]
    assert ledger.loc[0, "control_lifecycle_state"] == expected_lifecycle_state
    aggregates = runner._ledger_aggregates(ledger)
    assert aggregates["control"]["lifecycle_state_counts"] == {expected_lifecycle_state: 1}


def _unresolved_contract_run():
    return SimpleNamespace(
        window=SimpleNamespace(
            window=SimpleNamespace(window_id="P2-1"),
            effective_start=pd.Timestamp("2021-01-04"),
            effective_end=pd.Timestamp("2025-05-30"),
            execution_support=pd.Timestamp("2025-06-02"),
        )
    )


def _contract_trade(pair_id, *, ticker, terminal_return, lifecycle_state=None, side="CONTROL"):
    unresolved = lifecycle_state is not None
    row = {
        "pair_id": pair_id,
        "trade_id": f"{ticker}_01",
        "trade_sequence": 1,
        "ticker": ticker,
        "isu_cd": f"KR7{int(ticker):09d}",
        "market": "KOSPI",
        "identity_effective_from": "2020-01-01",
        "identity_effective_to": "2025-12-31",
        "entry_signal_date": "2025-01-03",
        "entry_execution_date": "2025-01-06",
        "entry_open": 100.0,
        "exit_signal_date": None if unresolved else "2025-02-03",
        "exit_execution_date": None if unresolved else "2025-02-04",
        "exit_type": "NO_EXIT" if unresolved else "V2_EXIT",
        "terminal_return": None if unresolved else terminal_return,
        "holding_days": None if unresolved else 20,
        "trade_status": "OPEN_AT_CUTOFF" if unresolved else "REALIZED",
        "execution_support_missing": False,
        "terminal_valuation_date": None,
        "terminal_valuation_at_cutoff": False,
        "stage_asof_date_at_signal": None,
    }
    if side == "Candidate":
        row["candidate_action"] = "CONTROL_PRESERVED"
    if unresolved:
        row.update(
            {
                "lifecycle_state": lifecycle_state,
                "lifecycle_certification_class": runner.REMEDIABLE_UNRESOLVED,
                "lifecycle_unresolved_reason": f"test reason for {lifecycle_state}",
                "lifecycle_source_isu_cd": f"KR7{int(ticker):09d}",
                "lifecycle_event_type": "MANDATORY_SHARE_EXCHANGE"
                if lifecycle_state == "UNRESOLVED_SUCCESSOR"
                else "MANDATORY_CASH",
                "lifecycle_evidence_id": f"evidence-{pair_id}-{side.lower()}",
            }
        )
    return row


def _contract_frames(pair_specs):
    control_rows = []
    candidate_rows = []
    for index, spec in enumerate(pair_specs, start=1):
        ticker = f"{index:06d}"
        pair_id = spec["pair_id"]
        control_state = spec.get("control_state")
        candidate_state = spec.get("candidate_state")
        control_rows.append(
            _contract_trade(
                pair_id,
                ticker=ticker,
                terminal_return=spec.get("control_return"),
                lifecycle_state=control_state,
                side="CONTROL",
            )
        )
        candidate_rows.append(
            _contract_trade(
                pair_id,
                ticker=ticker,
                terminal_return=spec.get("candidate_return"),
                lifecycle_state=candidate_state,
                side="Candidate",
            )
        )
    return pd.DataFrame(control_rows), pd.DataFrame(candidate_rows)


def test_unresolved_lifecycle_on_both_sides_is_preserved_and_excluded_pairwise():
    control, candidate = _contract_frames(
        [
            {
                "pair_id": "pair-unresolved-both",
                "control_state": "UNRESOLVED_SUCCESSOR",
                "candidate_state": "UNRESOLVED_SUCCESSOR",
            }
        ]
    )

    validation = runner._validate_results(control, candidate, _unresolved_contract_run())
    ledger = runner._build_matched_trade_ledger(control, candidate, cutoff_date="2025-05-30")
    aggregates = runner._ledger_aggregates(ledger)

    assert validation["matched_pairs_total"] == 1
    assert validation["matched_pairs_numeric_comparable"] == 0
    assert validation["matched_pairs_unresolved"] == 1
    assert validation["unresolved_lifecycle_trade_counts_by_side"] == {"CONTROL": 1, "Candidate": 1}
    assert validation["unresolved_lifecycle_state_counts"]["UNRESOLVED_SUCCESSOR"] == {
        "CONTROL": 1,
        "Candidate": 1,
    }
    assert validation["unresolved_lifecycle_state_totals"]["UNRESOLVED_SUCCESSOR"] == 2
    assert ledger.loc[0, "control_terminal_return"] is None
    assert ledger.loc[0, "candidate_terminal_return"] is None
    assert ledger.loc[0, "paired_delta"] is None
    assert ledger.loc[0, "control_unresolved_reason"] == "test reason for UNRESOLVED_SUCCESSOR"
    assert ledger.loc[0, "candidate_source_isu_cd"] == "KR7000000001"
    assert ledger.loc[0, "candidate_lifecycle_event_type"] == "MANDATORY_SHARE_EXCHANGE"
    assert aggregates["control"]["mean_terminal_return_pct"] is None
    assert aggregates["candidate"]["holding_days_mean"] is None
    assert aggregates["paired"]["count"] == 0
    assert aggregates["pair_counts"]["matched_pairs_unresolved"] == 1


@pytest.mark.parametrize("unresolved_side", ["CONTROL", "Candidate"])
def test_one_sided_unresolved_lifecycle_excludes_both_sides_from_metrics(unresolved_side):
    spec = {"pair_id": f"pair-one-sided-{unresolved_side}"}
    if unresolved_side == "CONTROL":
        spec.update(control_state="UNRESOLVED_SETTLEMENT", candidate_return=12.0)
    else:
        spec.update(control_return=-8.0, candidate_state="UNRESOLVED_SETTLEMENT")
    control, candidate = _contract_frames([spec])

    validation = runner._validate_results(control, candidate, _unresolved_contract_run())
    ledger = runner._build_matched_trade_ledger(control, candidate, cutoff_date="2025-05-30")
    aggregates = runner._ledger_aggregates(ledger)

    assert validation["matched_pairs_numeric_comparable"] == 0
    assert validation["matched_pairs_unresolved"] == 1
    assert ledger.loc[0, "paired_delta"] is None
    assert aggregates["control"]["mean_terminal_return_pct"] is None
    assert aggregates["candidate"]["mean_terminal_return_pct"] is None
    assert aggregates["paired"]["count"] == 0


def test_unresolved_settlement_provenance_survives_ledger_without_terminal_imputation():
    control, candidate = _contract_frames(
        [
            {
                "pair_id": "pair-unresolved-settlement",
                "control_state": "UNRESOLVED_SETTLEMENT",
                "candidate_state": "UNRESOLVED_SETTLEMENT",
            }
        ]
    )

    ledger = runner._build_matched_trade_ledger(control, candidate, cutoff_date="2025-05-30")

    assert ledger.loc[0, "control_lifecycle_state"] == "UNRESOLVED_SETTLEMENT"
    assert ledger.loc[0, "candidate_lifecycle_state"] == "UNRESOLVED_SETTLEMENT"
    assert ledger.loc[0, "control_terminal_return"] is None
    assert ledger.loc[0, "candidate_terminal_return"] is None
    assert ledger.loc[0, "control_unresolved_reason"] == "test reason for UNRESOLVED_SETTLEMENT"
    assert ledger.loc[0, "control_lifecycle_event_type"] == "MANDATORY_CASH"
    assert ledger.loc[0, "control_source_isu_cd"] == "KR7000000001"


def test_missing_terminal_return_without_allowed_unresolved_state_is_a_hard_failure():
    control, candidate = _contract_frames(
        [{"pair_id": "pair-unmarked-missing", "candidate_return": 1.0}]
    )
    control.loc[0, "terminal_return"] = None

    with pytest.raises(RuntimeError, match="missing without an allowed unresolved lifecycle state"):
        runner._validate_results(control, candidate, _unresolved_contract_run())


def test_numeric_terminal_return_for_unresolved_lifecycle_is_a_hard_failure():
    control, candidate = _contract_frames(
        [
            {
                "pair_id": "pair-unresolved-with-value",
                "control_state": "UNRESOLVED_POST_DELIST_VALUE",
                "candidate_state": "UNRESOLVED_POST_DELIST_VALUE",
            }
        ]
    )
    control.loc[0, "terminal_return"] = 0.0

    with pytest.raises(RuntimeError, match="unresolved lifecycle trade has a numeric terminal return"):
        runner._validate_results(control, candidate, _unresolved_contract_run())


def test_remediable_unresolved_matched_pair_prevents_recertified_pass():
    summary = {
        "window_id": "P2-1",
        "control": {"trade_count": 1, "tail_counts": {"le_neg_40_pct": 0, "le_neg_50_pct": 0}},
        "candidate": {"trade_count": 1},
        "candidate_diagnostics": {"control_ge_50_winner_damaged_count": 0},
        "paired": {"mean_delta_pct_points": 0.0, "improved": 1, "worsened": 0},
        "matched_pair_counts": {"matched_pairs_numeric_comparable": 0},
    }

    assert runner._verdict(
        summary,
        {"matched_pairs_unresolved": 1, "matched_pairs_remediable_unresolved": 1},
    ) == "CHECK_REQUIRED"


def test_authoritative_final_only_allows_certification_with_explicit_exclusion():
    control, candidate = _contract_frames(
        [
            {
                "pair_id": "pair-authoritative-final",
                "control_state": "UNRESOLVED_SETTLEMENT",
                "candidate_state": "UNRESOLVED_SETTLEMENT",
            }
        ]
    )
    for frame in (control, candidate):
        frame.loc[0, "lifecycle_certification_class"] = runner.AUTHORITATIVE_FINAL_UNRESOLVED
        frame.loc[0, "lifecycle_source_isu_cd"] = "KR7096300009"
        frame.loc[0, "lifecycle_event_type"] = "LIQUIDATION_UNRESOLVED"

    validation = runner._validate_results(control, candidate, _unresolved_contract_run())
    ledger = runner._build_matched_trade_ledger(control, candidate, cutoff_date="2025-05-30")
    aggregates = runner._ledger_aggregates(ledger)

    assert validation["matched_pairs_total"] == 1
    assert validation["matched_pairs_numeric_comparable"] == 0
    assert validation["matched_pairs_authoritative_excluded"] == 1
    assert validation["matched_pairs_remediable_unresolved"] == 0
    assert runner._certification_verdict(validation) == "RECERTIFIED_PASS_WITH_AUTHORITATIVE_EXCLUSION"
    assert ledger.loc[0, "control_terminal_return"] is None
    assert ledger.loc[0, "candidate_terminal_return"] is None
    assert ledger.loc[0, "pair_certification_class"] == runner.AUTHORITATIVE_FINAL_UNRESOLVED
    assert aggregates["paired"]["count"] == 0


def test_any_remediable_pair_blocks_certification_even_with_authoritative_exclusion():
    validation = {
        "matched_pairs_authoritative_excluded": 1,
        "matched_pairs_remediable_unresolved": 1,
    }

    assert runner._certification_verdict(validation) == "CHECK_REQUIRED"


def test_metric_difference_records_name_nested_field_values_and_signed_delta():
    differences = runner._metric_difference_records(
        {
            "holding_days_mean": 12.25,
            "tail_counts": {"le_neg_40_pct": 2},
        },
        {
            "holding_days_mean": 12.0,
            "tail_counts": {"le_neg_40_pct": 1},
        },
    )

    assert differences == [
        {
            "metric": "holding_days_mean",
            "ledger_expected": 12.25,
            "summary_actual": 12.0,
            "delta": -0.25,
        },
        {
            "metric": "tail_counts.le_neg_40_pct",
            "ledger_expected": 2,
            "summary_actual": 1,
            "delta": -1.0,
        },
    ]


@pytest.mark.parametrize("delta", [0.0001, 0.05, 0.1])
def test_aggregate_float_tolerance_accepts_differences_through_0_1pp(delta):
    assert runner._nested_values_equal({"mean_return_pct": 10.0}, {"mean_return_pct": 10.0 + delta})


def test_aggregate_float_tolerance_rejects_differences_over_0_1pp():
    assert not runner._nested_values_equal({"mean_return_pct": 10.0}, {"mean_return_pct": 10.1001})


def test_aggregate_float_tolerance_keeps_counts_identity_and_status_exact():
    assert not runner._nested_values_equal({"trade_count": 40}, {"trade_count": 41})
    assert not runner._nested_values_equal({"identity": "KR7000010006"}, {"identity": "KR7000010007"})
    assert not runner._nested_values_equal({"status": "REALIZED"}, {"status": "OPEN_AT_CUTOFF"})


def test_aggregate_float_tolerance_does_not_hide_nan_missing_or_type_mismatch():
    assert not runner._nested_values_equal({"mean_return_pct": float("nan")}, {"mean_return_pct": float("nan")})
    assert not runner._nested_values_equal({"mean_return_pct": 1.0}, {})
    assert not runner._nested_values_equal({"trade_count": 1}, {"trade_count": 1.0})


def test_no_unresolved_pairs_keeps_the_existing_recertification_verdict_path():
    summary = {
        "window_id": "P2-1",
        "control": {
            "trade_count": 1,
            "tail_counts": {"le_neg_40_pct": 0, "le_neg_50_pct": 0},
            "mean_terminal_return_pct": 5.0,
        },
        "candidate": {
            "trade_count": 1,
            "tail_counts": {"le_neg_40_pct": 0, "le_neg_50_pct": 0},
            "mean_terminal_return_pct": 5.0,
        },
        "candidate_diagnostics": {"control_ge_50_winner_damaged_count": 0},
        "paired": {"mean_delta_pct_points": 0.0, "improved": 0, "worsened": 0},
        "matched_pair_counts": {"matched_pairs_numeric_comparable": 1},
    }

    assert runner._verdict(summary, {"matched_pairs_unresolved": 0}) == "MIXED"


def test_aggregate_denominators_use_only_numeric_comparable_pairs():
    control, candidate = _contract_frames(
        [
            {"pair_id": "pair-numeric", "control_return": 5.0, "candidate_return": 10.0},
            {
                "pair_id": "pair-mixed",
                "control_return": 20.0,
                "candidate_state": "UNRESOLVED_SUCCESSOR",
            },
            {
                "pair_id": "pair-both-unresolved",
                "control_state": "UNRESOLVED_SETTLEMENT",
                "candidate_state": "UNRESOLVED_POST_DELIST_VALUE",
            },
        ]
    )

    validation = runner._validate_results(control, candidate, _unresolved_contract_run())
    ledger = runner._build_matched_trade_ledger(control, candidate, cutoff_date="2025-05-30")
    aggregates = runner._ledger_aggregates(ledger)

    assert validation["matched_pairs_total"] == 3
    assert validation["matched_pairs_numeric_comparable"] == 1
    assert validation["matched_pairs_unresolved"] == 2
    assert aggregates["pair_counts"] == {
        "matched_pairs_total": 3,
        "matched_pairs_numeric_comparable": 1,
        "matched_pairs_unresolved": 2,
    }
    assert aggregates["control"]["trade_count"] == 3
    assert aggregates["candidate"]["trade_count"] == 3
    assert aggregates["control"]["performance_pair_count"] == 1
    assert aggregates["candidate"]["performance_pair_count"] == 1
    assert aggregates["control"]["mean_terminal_return_pct"] == 5.0
    assert aggregates["candidate"]["mean_terminal_return_pct"] == 10.0
    assert aggregates["paired"]["count"] == 1
    assert aggregates["paired"]["mean_delta_pct_points"] == 5.0
