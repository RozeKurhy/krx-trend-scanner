from scripts.analyze_b_select_daily_exit_mdd_coverage_remediation_v01 import (
    classify_gap_basis,
    coverage_mdd_type,
    raw_nontrading_placeholder,
)


def test_raw_nontrading_placeholder_requires_exact_zero_activity_and_positive_close_shares():
    row = {
        "open": 0,
        "high": 0,
        "low": 0,
        "close": 1250,
        "volume": 0,
        "trading_value": 0,
        "listed_shares": 100000,
    }
    assert raw_nontrading_placeholder(row)
    assert not raw_nontrading_placeholder({**row, "volume": 1})
    assert not raw_nontrading_placeholder({**row, "close": 0})
    assert not raw_nontrading_placeholder({**row, "listed_shares": 0})


def test_share_unit_change_is_eligible_only_when_adjusted_raw_factor_tracks_it():
    result = classify_gap_basis(10_000_000, 5_000_000, 2.0, 1.0)
    assert result == ("B", "ADJUSTED_TO_RAW_FACTOR_MATCHES_LISTED_SHARE_RATIO", 0.5, 0.5)

    unresolved = classify_gap_basis(10_000_000, 5_000_000, 2.0, 1.2)
    assert unresolved[0] == "C"


def test_unchanged_shares_require_a_stable_adjusted_price_unit():
    assert classify_gap_basis(10_000_000, 10_000_000, 1.5, 1.5)[0] == "A"
    assert classify_gap_basis(10_000_000, 10_000_000, 1.5, 1.2)[0] == "C"


def test_mdd_type_obeys_exact_90_percent_coverage_boundary():
    assert coverage_mdd_type(100.0) == "EXACT MDD"
    assert coverage_mdd_type(90.0) == "OBSERVED MDD"
    assert coverage_mdd_type(89.999) == "NO OFFICIAL MDD: coverage below 90%"
