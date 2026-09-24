from types import SimpleNamespace

import pandas as pd
import pytest

import scripts.run_fastcore_neg40_weak_protect_p2_1 as runner
from scripts.run_fastcore_neg40_weak_protect_p2_1 import (
    IdentitySegment,
    _apply_lifecycle_settlement,
    _candidate_trade,
    _identity_signal_cutoff,
    _outcome_date,
    _outcome_reason,
    _pct,
)


def test_p2_2_run_id_override_uses_separate_versioned_output_namespace():
    try:
        runner._configure_run("P2-2", "run_20260924_final_corrective_v01")
        assert runner.RUN_ID == "run_20260924_final_corrective_v01"
        assert runner.RUN_DIR.name == "run_20260924_final_corrective_v01"
        assert runner.SAMPLE_PATH.name == "sample_benchmark_p2_2_pit_extension_v01.json"
        assert runner.MATCHED_LEDGER_PATH.parent == runner.RUN_DIR
    finally:
        runner._configure_run("P2-1")


@pytest.mark.parametrize("run_id", ["../outside", "run_bad/path", "invalid"])
def test_p2_2_run_id_override_rejects_unsafe_or_unversioned_names(run_id):
    with pytest.raises(ValueError, match="P2-2 run id"):
        runner._configure_run("P2-2", run_id)


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


def test_soft_signal_after_identity_segment_is_rejected_even_with_execution_price():
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
            }
        ]
    )

    with pytest.raises(RuntimeError, match="lies beyond its Candidate identity segment"):
        runner._build_soft_event_ledger(diagnostics, candidate)


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


def test_candidate_rejects_next_open_beyond_identity_segment():
    base = _base_trade()
    segment = IdentitySegment(
        ticker="000001",
        isu_cd="KR7000000001",
        market="KOSPI",
        effective_from=pd.Timestamp("2025-01-01"),
        effective_to=pd.Timestamp("2025-01-07"),
    )
    with pytest.raises(RuntimeError, match="next-session execution lies beyond its Candidate identity segment"):
        _candidate_trade(
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


def test_month_end_signal_label_cannot_cross_identity_end():
    segment = IdentitySegment(
        ticker="010420",
        isu_cd="KR7010420008",
        market="KOSPI",
        effective_from=pd.Timestamp("2010-01-04"),
        effective_to=pd.Timestamp("2025-09-24"),
    )

    signal_cutoff = _identity_signal_cutoff(segment, pd.Timestamp("2026-08-31"))

    assert signal_cutoff == pd.Timestamp("2025-09-24")
    assert pd.Timestamp("2025-09-30") > signal_cutoff


def test_process_ticker_passes_identity_bounded_cutoff_to_v2_core(monkeypatch):
    segment = IdentitySegment(
        ticker="010420",
        isu_cd="KR7010420008",
        market="KOSPI",
        effective_from=pd.Timestamp("2010-01-04"),
        effective_to=pd.Timestamp("2025-09-24"),
    )
    captured = {}

    class FakeLoader:
        def __init__(self, repository, *, start, end):
            self.load_count = 0

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
                "identity_effective_to": "2025-09-24",
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
    assert captured["signal_cutoff_date"] == pd.Timestamp("2025-09-24")
    assert pd.Timestamp("2025-09-30") > captured["signal_cutoff_date"]
    assert result["control_rows"][0]["trade_status"] == "LIFECYCLE_SETTLED"
    assert result["candidate_rows"][0]["trade_status"] == "LIFECYCLE_SETTLED"
    assert result["control_rows"][0]["terminal_return"] == 0.69
    assert result["candidate_rows"][0]["execution_support_missing"] is False


def test_confirmed_share_exchange_settlement_is_terminal_without_market_execution():
    segment = IdentitySegment(
        ticker="010420",
        isu_cd="KR7010420008",
        market="KOSPI",
        effective_from=pd.Timestamp("2010-01-04"),
        effective_to=pd.Timestamp("2025-09-24"),
    )
    row = {
        **_base_trade(),
        "ticker": segment.ticker,
        "isu_cd": segment.isu_cd,
        "market": segment.market,
        "identity_effective_from": "2010-01-04",
        "identity_effective_to": "2025-09-24",
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
                "identity_effective_to": "2025-09-24",
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
