from __future__ import annotations

import pandas as pd

from scripts import analyze_pattern_b_progressed_previous_pattern_a_stage_v01 as study


def test_resolves_contiguous_progressed_run_and_prior_stage() -> None:
    snapshots = ["2024-01-31", "2024-02-29", "2024-03-29", "2024-04-30"]
    stages = {
        "2024-01-31": "TRANSITION",
        "2024-02-29": "PROGRESSED",
        "2024-03-29": "PROGRESSED",
        "2024-04-30": "PROGRESSED",
    }
    trading_positions = {
        "2024-01-31": 20,
        "2024-02-29": 41,
        "2024-03-29": 62,
        "2024-04-30": 84,
    }

    result = study._resolve_progressed_episode(
        snapshots,
        stages,
        "2024-04-30",
        {day: index for index, day in enumerate(snapshots)},
        trading_positions,
    )

    assert result["previous_pattern_a_stage"] == "TRANSITION"
    assert result["previous_pattern_a_stage_date"] == "2024-01-31"
    assert result["progressed_segment_start_date"] == "2024-02-29"
    assert result["progressed_segment_krx_sessions"] == 43
    assert result["progressed_segment_month_observation_count"] == 3
    assert result["episode_boundary_reason"] == "PREVIOUS_DIFFERENT_OBSERVATION"


def test_unavailable_observation_breaks_progressed_segment() -> None:
    snapshots = ["2024-01-31", "2024-02-29", "2024-03-29", "2024-04-30"]
    stages = {
        "2024-01-31": "BASE",
        "2024-02-29": "PROGRESSED",
        "2024-03-29": "UNAVAILABLE",
        "2024-04-30": "PROGRESSED",
    }

    result = study._resolve_progressed_episode(
        snapshots,
        stages,
        "2024-04-30",
        {day: index for index, day in enumerate(snapshots)},
        {day: index * 21 for index, day in enumerate(snapshots)},
    )

    assert result["previous_pattern_a_stage"] == "UNAVAILABLE"
    assert result["previous_pattern_a_stage_date"] == "2024-03-29"
    assert result["progressed_segment_start_date"] == "2024-04-30"
    assert result["progressed_segment_krx_sessions"] == 0
    assert result["episode_boundary_reason"] == "PREVIOUS_DIFFERENT_OBSERVATION"


def test_pit_identity_active_gap_breaks_progressed_segment() -> None:
    snapshots = ["2024-01-31", "2024-02-29", "2024-03-29"]
    active_dates = ["2024-01-31", "2024-03-29"]
    stages = {"2024-01-31": "PROGRESSED", "2024-03-29": "PROGRESSED"}

    result = study._resolve_progressed_episode(
        active_dates,
        stages,
        "2024-03-29",
        {day: index for index, day in enumerate(snapshots)},
        {"2024-01-31": 20, "2024-03-29": 62},
    )

    assert result["previous_pattern_a_stage"] == "UNAVAILABLE"
    assert result["episode_boundary_reason"] == "PIT_IDENTITY_ACTIVE_GAP"
    assert result["progressed_segment_start_date"] == "2024-03-29"
    assert result["progressed_segment_krx_sessions"] == 0


def test_duration_summary_reports_requested_percentiles() -> None:
    result = study._duration_summary([0, 10, 20, 30, 40])

    assert result["n"] == 5
    assert result["mean"] == 20
    assert result["median"] == 20
    assert result["p25"] == 10
    assert result["p75"] == 30
    assert result["p90"] == 36
    assert result["min"] == 0
    assert result["max"] == 40


def test_return_thresholds_include_exact_boundaries() -> None:
    result = study._return_summary([
        {"gross_return_pct": 0.0},
        {"gross_return_pct": 20.0},
        {"gross_return_pct": 50.0},
        {"gross_return_pct": 100.0},
        {"gross_return_pct": -20.0},
        {"gross_return_pct": -30.0},
        {"gross_return_pct": -50.0},
    ])

    assert result["n"] == 7
    assert result["win_count"] == 3
    assert result["ge_20_count"] == 3
    assert result["ge_50_count"] == 2
    assert result["ge_100_count"] == 1
    assert result["le_20_count"] == 3
    assert result["le_30_count"] == 2
    assert result["le_50_count"] == 1


def test_completed_month_period_label_may_follow_last_exchange_session() -> None:
    assert study._stage_inputs_are_pit_safe(
        "2018-09-28", "2018-09-28", "2018-09-30", "2018-09-28"
    )
    assert not study._stage_inputs_are_pit_safe(
        "2018-09-28", "2018-09-28", "2018-10-31", "2018-09-28"
    )
    assert not study._stage_inputs_are_pit_safe(
        "2018-09-28", "2018-09-30", "2018-09-30", "2018-09-28"
    )


def test_deep_arrival_uses_only_states_observed_while_trade_is_held() -> None:
    trade = {
        "ticker": "000001",
        "isu_cd": "KR7000000001",
        "component_id": "000001:KR7000000001:000",
        "entry_signal_date": "2024-01-31",
        "exit_signal_date": "2024-02-29",
    }
    samples = pd.DataFrame([
        {"ticker": "000001", "isu_cd": "KR7000000001", "component_id": trade["component_id"], "snapshot_date": "2024-02-29", "state": "DEEP_DEPRESSED"},
        {"ticker": "000001", "isu_cd": "KR7000000001", "component_id": trade["component_id"], "snapshot_date": "2024-03-29", "state": "DEEP_DEPRESSED"},
    ])

    assert study._deep_trade_keys([trade], samples) == {("000001", "KR7000000001", "2024-01-31")}

    samples.loc[0, "state"] = "DEPRESSED"
    assert study._deep_trade_keys([trade], samples) == set()


def test_previous_stage_tables_keep_path_trades_and_open_marks_separate() -> None:
    key_realized = ("000001", "KR7000000001", "2024-01-31")
    key_open = ("000002", "KR7000000002", "2024-02-29")
    candidates = pd.DataFrame([
        {
            "ticker": key_realized[0], "isu_cd": key_realized[1], "entry_signal_date": key_realized[2],
            "previous_pattern_a_stage": "TRANSITION", "progressed_segment_krx_sessions": 20,
            "pattern_b_path_outcome": "NORMAL_FIRST", "sessions_to_first_normal": 10,
            "sessions_to_first_deep_depressed": 30,
        },
        {
            "ticker": key_open[0], "isu_cd": key_open[1], "entry_signal_date": key_open[2],
            "previous_pattern_a_stage": "BASE", "progressed_segment_krx_sessions": 0,
            "pattern_b_path_outcome": "DEEP_FIRST", "sessions_to_first_normal": None,
            "sessions_to_first_deep_depressed": 5,
        },
    ])
    trades = {
        key_realized: {
            "ticker": key_realized[0], "isu_cd": key_realized[1], "entry_signal_date": key_realized[2],
            "trade_status": "REALIZED", "gross_return_pct": 50.0, "mfe_pct": 60.0,
            "mae_pct": -10.0, "holding_krx_sessions": 20,
        },
        key_open: {
            "ticker": key_open[0], "isu_cd": key_open[1], "entry_signal_date": key_open[2],
            "trade_status": "OPEN_AT_CUTOFF", "gross_return_pct": None,
            "mark_to_cutoff_gross_return_pct": -35.0, "mfe_pct": 5.0,
            "mae_pct": -45.0, "holding_krx_sessions": 20,
        },
    }

    stage, deep, opened, failures, winners, grouped = study._build_group_tables(
        candidates, trades, {key_realized, key_open}
    )

    transition = stage.loc[stage.previous_pattern_a_stage == "TRANSITION"].iloc[0]
    base = stage.loc[stage.previous_pattern_a_stage == "BASE"].iloc[0]
    assert transition.realized_ge_50_count == 1
    assert transition.path_normal_first_count == 1
    assert base.open_exact_cutoff_marked_count == 1
    assert base.open_marked_le_30_count == 1
    assert int(deep.loc[deep.previous_pattern_a_stage == "TRANSITION", "deep_arrival_trade_count"].iloc[0]) == 1
    assert int(opened.loc[opened.previous_pattern_a_stage == "BASE", "open_at_cutoff_count"].iloc[0]) == 1
    assert set(failures.cohort) >= {"REALIZED_LE_30", "OPEN_MARK_LE_30"}
    assert set(winners.cohort) >= {"REALIZED_GE_50"}
    assert grouped["duration"].loc[lambda frame: frame.cohort == "ALL_RAW_SIGNALS", "n"].iloc[0] == 2
