from trend_scanner.validation.oos_v01_manifest import (
    OOS_V01_DATASET_VERSION,
    OOS_V01_DIAGNOSTIC_SNAPSHOTS,
    OOS_V01_STAGE_AUDIT,
)

_EXPECTED_GROUP_COUNTS = {
    "positive_pre_breakout": 5,
    "positive_early_trend": 5,
    "positive_trend_progressed": 5,
    "hard_negative_false_turn": 8,
    "downtrend_reversal_boundary": 5,
    "insufficient_data_check": 1,
}


def test_dataset_version_is_frozen_at_v01():
    assert OOS_V01_DATASET_VERSION == "oos_v0.1"


def test_no_duplicate_ticker_and_date_pairs():
    keys = [(s.ticker, s.snapshot_date) for s in OOS_V01_DIAGNOSTIC_SNAPSHOTS]
    assert len(keys) == len(set(keys)), "같은 (ticker, snapshot_date) 조합이 중복됐다"


def test_group_counts_match_report():
    counts: dict[str, int] = {}
    for spec in OOS_V01_DIAGNOSTIC_SNAPSHOTS:
        counts[spec.original_group] = counts.get(spec.original_group, 0) + 1
    assert counts == _EXPECTED_GROUP_COUNTS


def test_total_snapshot_count_is_29():
    assert len(OOS_V01_DIAGNOSTIC_SNAPSHOTS) == 29


def test_every_snapshot_has_a_non_empty_selection_reason():
    for spec in OOS_V01_DIAGNOSTIC_SNAPSHOTS:
        assert spec.selection_reason.strip(), f"{spec.ticker} {spec.snapshot_date}에 선정 근거가 비어있다"


def test_stage_audit_covers_exactly_the_15_positive_snapshots():
    positive_keys = {
        (s.ticker, s.snapshot_date)
        for s in OOS_V01_DIAGNOSTIC_SNAPSHOTS
        if s.original_group.startswith("positive_")
    }
    assert len(positive_keys) == 15
    assert set(OOS_V01_STAGE_AUDIT.keys()) == positive_keys


def test_original_group_is_untouched_by_stage_audit():
    # 감사 결과는 병렬 기록일 뿐, original_group을 덮어쓰지 않는다.
    original_groups = {s.original_group for s in OOS_V01_DIAGNOSTIC_SNAPSHOTS}
    assert "positive_pre_breakout" in original_groups
    assert "positive_early_trend" in original_groups
    assert "positive_trend_progressed" in original_groups
