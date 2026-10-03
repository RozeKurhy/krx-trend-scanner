from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts import build_b_select_core_v1_status as status_builder
from scripts import run_pattern_b_pure_simple_backtest_v01 as pattern_b_source
from trend_scanner.universe.permanent_identity_exclusions import PERMANENT_IDENTITY_EXCLUSIONS


def test_calendar_authority_payload_maps_real_provenance_keys():
    assert status_builder._calendar_authority_payload(
        {"calendar_frontier": "2026-09-23", "calendar_sha256": "abc123"}
    ) == {"frontier": "2026-09-23", "sha256": "abc123"}


def test_calendar_authority_payload_fails_closed_when_provenance_is_missing():
    with pytest.raises(status_builder.BSelectStatusError, match="B_SELECT_CALENDAR_PROVENANCE_MISSING"):
        status_builder._calendar_authority_payload({"calendar_frontier": "2026-09-23"})


def test_catchup_session_dates_preserve_existing_one_session_path():
    calendar = ["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02"]
    assert status_builder._catchup_session_dates("2026-09-30", "2026-10-01", calendar) == ["2026-10-01"]


def test_catchup_session_dates_enumerate_every_missing_krx_session():
    calendar = ["2026-09-23", "2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02"]
    assert status_builder._catchup_session_dates("2026-09-23", "2026-10-02", calendar) == [
        "2026-09-28",
        "2026-09-29",
        "2026-09-30",
        "2026-10-01",
        "2026-10-02",
    ]


def test_catchup_session_dates_fail_closed_for_missing_or_reversed_authority():
    calendar = ["2026-09-28", "2026-09-29", "2026-09-30"]
    with pytest.raises(ValueError, match="not an exact KRX session"):
        status_builder._catchup_session_dates("2026-09-27", "2026-09-30", calendar)
    with pytest.raises(ValueError, match="must follow"):
        status_builder._catchup_session_dates("2026-09-30", "2026-09-29", calendar)


def test_exact_daily_stage_replaces_only_unavailable_same_day_monthly_observation():
    history = [
        {"as_of": "2026-08-31", "stage": "TRANSITION", "data_available": True},
        {
            "as_of": "2026-09-30",
            "stage": "UNAVAILABLE",
            "data_available": False,
            "reason": "NO_EXACT_MARKET_MONTH_END_OBSERVATION",
        },
    ]
    assert status_builder._history_before_exact_stage(
        history,
        day="2026-09-30",
        current_stage="PROGRESSED",
        ticker="017650",
    ) == history[:1]


def test_exact_daily_stage_fails_closed_on_available_same_day_monthly_mismatch():
    history = [{"as_of": "2026-09-30", "stage": "TRANSITION", "data_available": True}]
    with pytest.raises(status_builder.BSelectStatusError, match="SAME_DAY_STAGE_MISMATCH"):
        status_builder._history_before_exact_stage(
            history,
            day="2026-09-30",
            current_stage="PROGRESSED",
            ticker="017650",
        )


def test_status_builder_rejects_report_date_mismatch(tmp_path: Path):
    index_path = tmp_path / "stock-index.json"
    index_path.write_text(
        json.dumps({"requested_as_of": "2026-09-24", "reference_market_date": "2026-09-23", "items": []}),
        encoding="utf-8",
    )
    with pytest.raises(status_builder.BSelectStatusError, match="B_SELECT_STOCK_INDEX_DATE_MISMATCH"):
        status_builder.build_b_select_status(
            repo_root=tmp_path,
            index_path=index_path,
            stocks_path=tmp_path / "stocks",
            target_as_of="2026-09-25",
            reference_market_date="2026-09-23",
        )


def test_previous_stage_uses_exact_current_snapshot_after_monthly_history():
    current_stage, previous_stage, context = status_builder._report_previous_stage(
        {
            "pattern": {
                "official_stage": "PROGRESSED",
                "history_12m": [{"as_of": "2026-08-31", "stage": "WEAK"}],
            }
        },
        reference_market_date="2026-09-23",
        trading_dates=["2026-08-31", "2026-09-23"],
        root=Path("."),
        identity={"ticker": "041510", "effective_from": "2020-01-01"},
        resolve_full_history=False,
    )

    assert current_stage == "PROGRESSED"
    assert previous_stage == "WEAK"
    assert context is not None
    assert context["previous_pattern_a_stage_date"] == "2026-08-31"


def test_entry_pattern_a_context_uses_one_exact_qualified_authority_row():
    source = {
        "ticker": "001380",
        "isu_cd": "KR7001380005",
        "component_id": "001380:KR7001380005:000",
        "entry_signal_date": "2025-04-30",
        "entry_pattern_a_stage_recomputed": "PROGRESSED",
        "previous_pattern_a_stage": "EARLY_TREND",
        "previous_pattern_a_stage_date": "2024-07-31",
    }
    assert status_builder._entry_pattern_a_context(
        [source],
        ticker="001380",
        isu_cd="KR7001380005",
        component_id="001380:KR7001380005:000",
        entry_signal_date="2025-04-30",
    ) == {
        "entry_pattern_a_stage": "PROGRESSED",
        "entry_previous_pattern_a_stage": "EARLY_TREND",
        "entry_previous_pattern_a_stage_date": "2024-07-31",
    }


def test_entry_pattern_a_context_fails_closed_on_missing_duplicate_or_unqualified_source():
    source = {
        "ticker": "001380",
        "isu_cd": "KR7001380005",
        "component_id": "001380:KR7001380005:000",
        "entry_signal_date": "2025-04-30",
        "entry_pattern_a_stage_recomputed": "PROGRESSED",
        "previous_pattern_a_stage": "EARLY_TREND",
        "previous_pattern_a_stage_date": "2024-07-31",
    }
    kwargs = {
        "ticker": "001380",
        "isu_cd": "KR7001380005",
        "component_id": "001380:KR7001380005:000",
        "entry_signal_date": "2025-04-30",
    }
    with pytest.raises(status_builder.BSelectStatusError, match="SOURCE_MATCH_COUNT"):
        status_builder._entry_pattern_a_context([], **kwargs)
    with pytest.raises(status_builder.BSelectStatusError, match="SOURCE_MATCH_COUNT"):
        status_builder._entry_pattern_a_context([source, source], **kwargs)
    unqualified = {**source, "previous_pattern_a_stage": "WEAK"}
    with pytest.raises(status_builder.BSelectStatusError, match="SOURCE_NOT_QUALIFIED"):
        status_builder._entry_pattern_a_context([unqualified], **kwargs)


def test_tracked_open_status_keeps_entry_lineage_separate_from_current_snapshot():
    status_path = status_builder.ROOT / status_builder.STATUS_RELATIVE / "20260925/status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    candidate_rows = status_builder._load_candidate_signals(status_builder.ROOT)
    open_items = [item for item in status["items"] if item.get("canonical_position") == "OPEN"]

    assert len(open_items) == 24
    assert len([item for item in open_items if item.get("action") == "HOLD"]) == 23
    assert len([item for item in open_items if item.get("action") == "EXIT"]) == 1
    for item in open_items:
        trade = item["current_trade"]
        expected = status_builder._entry_pattern_a_context(
            candidate_rows,
            ticker=item["ticker"],
            isu_cd=item["isu_cd"],
            component_id=item["component_id"],
            entry_signal_date=trade["entry_signal_date"],
        )
        assert item["entry_pattern_a_stage"] == expected["entry_pattern_a_stage"] == "PROGRESSED"
        assert item["entry_previous_pattern_a_stage"] == expected["entry_previous_pattern_a_stage"]
        assert item["entry_previous_pattern_a_stage"] in {"EARLY_TREND", "TRANSITION"}
        assert item["entry_previous_pattern_a_stage_date"] == expected["entry_previous_pattern_a_stage_date"]

    current_weak = next(item for item in open_items if item["pattern_a_stage"] == "WEAK")
    current_progressed_weak_predecessor = next(
        item for item in open_items
        if item["pattern_a_stage"] == "PROGRESSED" and item["previous_pattern_a_stage"] == "WEAK"
    )
    exit_pending = next(item for item in open_items if item["action"] == "EXIT")
    early_lineage = next(item for item in open_items if item["entry_previous_pattern_a_stage"] == "EARLY_TREND")
    transition_lineage = next(item for item in open_items if item["entry_previous_pattern_a_stage"] == "TRANSITION")
    assert current_weak["entry_pattern_a_stage"] == "PROGRESSED"
    assert current_progressed_weak_predecessor["entry_previous_pattern_a_stage"] != "WEAK"
    assert exit_pending["entry_pattern_a_stage"] == "PROGRESSED"
    assert early_lineage["entry_pattern_a_stage"] == transition_lineage["entry_pattern_a_stage"] == "PROGRESSED"

    non_entry_items = [item for item in status["items"] if item.get("canonical_position") != "OPEN" and item.get("action") not in {"ENTRY", "ENTER_NEXT_OPEN"}]
    assert all(item.get("entry_pattern_a_stage") is None for item in non_entry_items)
    assert all(item.get("entry_previous_pattern_a_stage") is None for item in non_entry_items)


def test_monthly_state_authority_applies_exact_permanent_identity_exclusion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    excluded_ticker, excluded_isu = sorted(PERMANENT_IDENTITY_EXCLUSIONS)[0]
    retained_isu = "KR7999999999"
    snapshot_date = "2026-09-23"
    interval_end = "2026-09-23"
    intervals = [
        {
            "ticker": excluded_ticker,
            "isu_cd": isu,
            "market": "KOSPI",
            "state": "COMMON",
            "effective_from": "2020-01-01",
            "effective_to": interval_end,
        }
        for isu in (excluded_isu, retained_isu)
    ]
    components = {
        pattern_b_source.interval_key(row): f"component-{index}"
        for index, row in enumerate(intervals)
    }
    sample_path = tmp_path / "monthly.csv.gz"
    pd.DataFrame(
        [
            {
                "ticker": excluded_ticker,
                "isu_cd": isu,
                "market": "KOSPI",
                "effective_from": "2020-01-01",
                "effective_to": interval_end,
                "snapshot_date": snapshot_date,
                "monthly_last_bar": "2026-08-31",
                "weekly_last_bar": "2026-09-18",
                "state": "DEPRESSED",
            }
            for isu in (excluded_isu, retained_isu)
        ]
    ).to_csv(sample_path, index=False, compression="gzip")
    monkeypatch.setattr(status_builder, "MONTHLY_SAMPLE_REL", sample_path.relative_to(tmp_path))

    states, policy_exclusion_count = status_builder._load_monthly_states(
        tmp_path,
        intervals,
        components,
        [snapshot_date],
    )

    assert policy_exclusion_count == len(PERMANENT_IDENTITY_EXCLUSIONS)
    assert states[["ticker", "isu_cd"]].to_records(index=False).tolist() == [(excluded_ticker, retained_isu)]
