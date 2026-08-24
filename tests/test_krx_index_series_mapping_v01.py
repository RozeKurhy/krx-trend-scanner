"""Deterministic tests for the validation-only index mapping helpers."""

from decimal import Decimal

from scripts.validate_krx_index_series_mapping_v01 import (
    PRIMARY_DATES,
    _mapping_evidence,
    build_signature,
    classify_candidate,
    classify_duplicate,
    compare_signatures,
    normalize_decimal,
    readiness_gate,
)


def _series(value: str = "100.00") -> dict[str, str]:
    return {"open": value, "high": value, "low": value, "close": value}


def test_decimal_normalization_is_exact_and_blank_safe() -> None:
    assert normalize_decimal("1,234.00") == Decimal("1234.00")
    assert normalize_decimal("-") is None
    assert normalize_decimal(0) == Decimal("0")


def test_signature_uses_only_ohlc_fields() -> None:
    signature = build_signature({"OPNPRC_IDX": "1.00", "HGPRC_IDX": "2.00", "LWPRC_IDX": "0.50", "CLSPRC_IDX": "1.50", "ACC_TRDVOL": "999"})
    assert signature["open"] == Decimal("1.00")
    assert signature["close"] == Decimal("1.50")
    assert "volume" not in signature


def test_compare_signature_marks_exact_and_rounding_separately() -> None:
    exact = compare_signatures(_series("100.00"), _series("100.00"))
    assert exact["exact_field_match_count"] == 4
    rounded = compare_signatures(_series("100.00"), _series("100.01"))
    assert rounded["rounding_only"]
    assert rounded["rounding_difference_count"] == 4


def test_candidate_classifications_cover_exact_ambiguous_partial_and_no_match() -> None:
    assert classify_candidate(6, 24, 24, 0, 1) == "EXACT_MARKET_SERIES_MATCH"
    assert classify_candidate(6, 24, 24, 0, 2) == "AMBIGUOUS_PRICE_SIGNATURE"
    assert classify_candidate(2, 8, 8, 0, 1) == "INSUFFICIENT_COMMON_DATES"
    assert classify_candidate(6, 24, 0, 0, 1) == "NO_MARKET_SERIES_MATCH"


def test_rounding_only_candidate_is_explicit() -> None:
    assert classify_candidate(6, 24, 20, 4, 1) == "ROUNDING_ONLY_MARKET_SERIES_MATCH"


def test_duplicate_classifications_do_not_deduplicate_different_series() -> None:
    assert classify_duplicate(6, 24, 24) == "EXACT_CROSS_API_DUPLICATE"
    assert classify_duplicate(6, 24, 12) == "SAME_NAME_DIFFERENT_SERIES"
    assert classify_duplicate(2, 8, 8) == "PARTIAL_CROSS_API_EVIDENCE"
    assert classify_duplicate(0, 0, 0) == "UNKNOWN_CROSS_API_RELATION"


def test_readiness_gate_requires_all_active_zero_counters() -> None:
    counters = {
        "sector_code_total_count": 46,
        "active_ambiguous_count": 0,
        "active_no_match_count": 0,
        "active_reference_unavailable_count": 0,
        "active_insufficient_common_dates_count": 0,
        "krx_access_fail_count": 0,
        "quota_counter_mismatch_count": 0,
        "request_audit_mismatch_count": 0,
        "secret_occurrence_count": 0,
        "validation_source_head_mismatch_count": 0,
    }
    assert readiness_gate(counters)
    counters["active_no_match_count"] = 1
    assert not readiness_gate(counters)


def test_mapping_evidence_selects_one_exact_candidate() -> None:
    py_rows = {date.replace("-", ""): _series("100.00") for date in PRIMARY_DATES}
    candidates = {date: {"동일지수": {"OPNPRC_IDX": "100.00", "HGPRC_IDX": "100.00", "LWPRC_IDX": "100.00", "CLSPRC_IDX": "100.00"}} for date in PRIMARY_DATES}
    detail, parity = _mapping_evidence("1005", "KOSPI", py_rows, candidates, "음식료·담배")
    assert detail["summary"]["mapping_status"] == "EXACT_MARKET_SERIES_MATCH"
    assert detail["summary"]["official_idx_name"] == "동일지수"
    assert len(parity) == 6


def test_mapping_evidence_keeps_multiple_exact_candidates_ambiguous() -> None:
    py_rows = {date.replace("-", ""): _series("100.00") for date in PRIMARY_DATES}
    candidates = {date: {"A": {"OPNPRC_IDX": "100.00", "HGPRC_IDX": "100.00", "LWPRC_IDX": "100.00", "CLSPRC_IDX": "100.00"}, "B": {"OPNPRC_IDX": "100.00", "HGPRC_IDX": "100.00", "LWPRC_IDX": "100.00", "CLSPRC_IDX": "100.00"}} for date in PRIMARY_DATES}
    detail, _ = _mapping_evidence("1005", "KOSPI", py_rows, candidates, "음식료·담배")
    assert detail["summary"]["mapping_status"] == "AMBIGUOUS_PRICE_SIGNATURE"
    assert detail["summary"]["official_idx_name"] is None


def test_mapping_evidence_requires_three_common_dates() -> None:
    py_rows = {date.replace("-", ""): _series("100.00") for date in PRIMARY_DATES}
    candidates = {date: {"부분지수": {"OPNPRC_IDX": "100.00", "HGPRC_IDX": "100.00", "LWPRC_IDX": "100.00", "CLSPRC_IDX": "100.00"}} for date in PRIMARY_DATES[:2]}
    detail, parity = _mapping_evidence("1005", "KOSPI", py_rows, candidates, "음식료·담배")
    assert detail["summary"]["mapping_status"] == "INSUFFICIENT_COMMON_DATES"
    assert parity == []
