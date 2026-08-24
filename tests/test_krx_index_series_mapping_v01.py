"""Deterministic tests for the validation-only index mapping helpers."""

from decimal import Decimal

from scripts.validate_krx_index_series_mapping_v01 import (
    PRIMARY_DATES,
    _fetch_pykrx_series,
    _mapping_evidence,
    build_cross_taxonomy_relations,
    build_signature,
    classify_candidate,
    classify_duplicate,
    compare_signatures,
    normalize_decimal,
    readiness_gate,
)


def _series(value: str = "100.00") -> dict[str, str]:
    return {"open": value, "high": value, "low": value, "close": value}


def _raw_row(name: str, value: str, idx_class: str) -> dict[str, str]:
    return {"IDX_CLSS": idx_class, "IDX_NM": name, "OPNPRC_IDX": value, "HGPRC_IDX": value, "LWPRC_IDX": value, "CLSPRC_IDX": value}


def _taxonomy_snapshots(*, krx_values: dict[str, list[str]], native_values: dict[str, list[str]] | None = None) -> dict[tuple[str, str], list[dict[str, str]]]:
    native_values = native_values or {"Native B": ["100.00"] * len(PRIMARY_DATES)}
    snapshots: dict[tuple[str, str], list[dict[str, str]]] = {}
    for index, date in enumerate(PRIMARY_DATES):
        snapshots[("krx_dd_trd", date)] = [_raw_row(name, values[index], "KRX") for name, values in krx_values.items() if index < len(values)]
        snapshots[("kospi_dd_trd", date)] = [_raw_row(name, values[index], "KOSPI") for name, values in native_values.items() if index < len(values)]
    return snapshots


def _native(name: str = "Native B") -> dict[str, str]:
    return {"market": "KOSPI", "sector_code": "1005", "source_api": "kospi_dd_trd", "official_idx_class": "KOSPI", "official_idx_name": name}


def _taxonomy(name: str) -> dict[str, str]:
    return {"krx_idx_name": name, "krx_source_api": "krx_dd_trd", "official_idx_class": "KRX"}


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


def test_cross_taxonomy_exact_relation_uses_ohlc_identity() -> None:
    snapshots = _taxonomy_snapshots(krx_values={"KRX Sector A": ["100.00"] * 6})
    relations, parity, counters = build_cross_taxonomy_relations(snapshots, [_native()], [_taxonomy("KRX Sector A")])
    assert relations[0]["relation"] == "EXACT_CROSS_TAXONOMY_EQUIVALENT"
    assert relations[0]["native_exact_matches"][0]["official_idx_name"] == "Native B"
    assert relations[0]["common_date_count"] == 6
    assert relations[0]["exact_field_match_count"] == 24
    assert len(parity) == 6
    assert counters["krx_sector_exact_equivalence_count"] == 1


def test_cross_taxonomy_distinct_relation_requires_complete_nonmatching_evidence() -> None:
    snapshots = _taxonomy_snapshots(krx_values={"KRX Sector A": ["101.00"] * 6}, native_values={"Native B": ["100.00"] * 6})
    relations, _, counters = build_cross_taxonomy_relations(snapshots, [_native()], [_taxonomy("KRX Sector A")])
    assert relations[0]["relation"] == "DISTINCT_KRX_TAXONOMY"
    assert relations[0]["native_exact_match_count"] == 0
    assert relations[0]["reason"] == "6_DATE_OHLC_EVIDENCE_WITH_NO_EXACT_NATIVE_CANDIDATE"
    assert counters["krx_sector_distinct_count"] == 1


def test_cross_taxonomy_partial_relation_is_not_distinct() -> None:
    snapshots = _taxonomy_snapshots(krx_values={"KRX Sector A": ["100.00", "100.00"]})
    relations, _, counters = build_cross_taxonomy_relations(snapshots, [_native()], [_taxonomy("KRX Sector A")])
    assert relations[0]["relation"] == "PARTIAL_CROSS_TAXONOMY_EVIDENCE"
    assert counters["krx_sector_partial_count"] == 1


def test_cross_taxonomy_unknown_relation_has_no_common_evidence() -> None:
    snapshots = _taxonomy_snapshots(krx_values={"KRX Sector A": []})
    relations, _, counters = build_cross_taxonomy_relations(snapshots, [_native()], [_taxonomy("KRX Sector A")])
    assert relations[0]["relation"] == "UNKNOWN_CROSS_TAXONOMY_RELATION"
    assert relations[0]["reason"] == "NO_COMMON_NATIVE_EVIDENCE"
    assert counters["krx_sector_unknown_count"] == 1


def test_cross_taxonomy_multiple_exact_candidates_is_unknown() -> None:
    snapshots = _taxonomy_snapshots(krx_values={"KRX Sector A": ["100.00"] * 6}, native_values={"Native B": ["100.00"] * 6, "Native C": ["100.00"] * 6})
    relations, _, counters = build_cross_taxonomy_relations(snapshots, [_native("Native B"), _native("Native C")], [_taxonomy("KRX Sector A")])
    assert relations[0]["relation"] == "UNKNOWN_CROSS_TAXONOMY_RELATION"
    assert relations[0]["reason"] == "MULTIPLE_EXACT_NATIVE_CANDIDATES"
    assert counters["krx_sector_unknown_count"] == 1


def test_cross_taxonomy_counters_close_across_all_relations() -> None:
    snapshots = _taxonomy_snapshots(
        krx_values={"Exact": ["100.00"] * 6, "Distinct": ["101.00"] * 6, "Partial": ["100.00", "100.00"]},
    )
    taxonomy = [_taxonomy("Exact"), _taxonomy("Distinct"), _taxonomy("Partial"), _taxonomy("Unknown")]
    relations, _, counters = build_cross_taxonomy_relations(snapshots, [_native()], taxonomy)
    assert len(relations) == 4
    assert sum(counters[key] for key in ("krx_sector_exact_equivalence_count", "krx_sector_distinct_count", "krx_sector_partial_count", "krx_sector_unknown_count")) == counters["krx_sector_taxonomy_count"] == 4


def test_pykrx_hard_cap_blocks_61st_attempt_before_probe() -> None:
    calls: list[str] = []

    def probe(*_: str) -> object:
        calls.append("called")
        return None

    state = {"network_operations": 60, "halted": False}
    result = _fetch_pykrx_series("1005", start="2026-06-01", end="2026-08-21", delay_seconds=0, state=state, probe=probe)
    assert result["status"] == "PYKRX_OPERATION_BUDGET_EXHAUSTED"
    assert result["attempts"] == 0
    assert state["network_operations"] == 60
    assert calls == []


def test_pykrx_retry_at_59_consumes_60_then_blocks_retry() -> None:
    calls: list[str] = []

    def probe(*_: str) -> object:
        calls.append("called")
        raise RuntimeError("synthetic failure")

    state = {"network_operations": 59, "halted": False}
    result = _fetch_pykrx_series("1005", start="2026-06-01", end="2026-08-21", delay_seconds=0, state=state, probe=probe)
    assert result["status"] == "PYKRX_OPERATION_BUDGET_EXHAUSTED"
    assert result["attempts"] == 1
    assert state["network_operations"] == 60
    assert calls == ["called"]


def test_offline_replay_never_constructs_live_clients(monkeypatch, tmp_path) -> None:
    import scripts.validate_krx_index_series_mapping_v01 as module

    monkeypatch.setattr(module, "ARTIFACT_DIR", tmp_path)
    monkeypatch.setattr(module, "RAW_DIR", tmp_path / "raw_samples")
    tmp_path.mkdir(exist_ok=True)
    previous_counters = {
        "cross_api_duplicate_pair_count": 20,
        "cross_api_exact_duplicate_count": 0,
        "cross_api_same_name_different_count": 20,
        "cross_api_partial_count": 0,
        "cross_api_unknown_count": 0,
    }
    (tmp_path / "index_mapping_v01_summary.json").write_text(__import__("json").dumps({"counters": previous_counters}), encoding="utf-8")
    (tmp_path / "index_mapping_v01_manifest.json").write_text(__import__("json").dumps({}), encoding="utf-8")
    monkeypatch.setattr(module, "load_auth_key", lambda: "")
    monkeypatch.setattr(module, "load_committed_raw_snapshots", lambda: {})
    monkeypatch.setattr(module, "_native_authority_rows", lambda: [])
    monkeypatch.setattr(module, "extract_krx_taxonomy_rows", lambda _: [{"krx_idx_name": f"KRX {i}", "krx_source_api": "krx_dd_trd", "official_idx_class": "KRX"} for i in range(24)])
    taxonomy_counters = {"krx_sector_taxonomy_count": 24, "krx_sector_exact_equivalence_count": 0, "krx_sector_distinct_count": 24, "krx_sector_partial_count": 0, "krx_sector_unknown_count": 0}
    monkeypatch.setattr(module, "build_cross_taxonomy_relations", lambda *_: ([{"krx_idx_name": f"KRX {i}", "relation": "DISTINCT_KRX_TAXONOMY"} for i in range(24)], [], taxonomy_counters))
    monkeypatch.setattr(module, "_offline_mapping_regression", lambda: {"sector_code_total_count": 46, "active_sector_code_count": 46, "exact_mapping_count": 46, "rounding_only_mapping_count": 0, "active_ambiguous_count": 0, "active_no_match_count": 0, "active_reference_unavailable_count": 0, "active_insufficient_common_dates_count": 0, "exact_ohlc_fields": 1104, "parity_row_count": 276, "detail_item_count": 46})
    monkeypatch.setattr(module, "scan_secret", lambda _: {"secret_occurrence_count": 0, "scanned_file_count": 0})
    monkeypatch.setattr(module, "KrxOpenApiClient", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("live KRX client must not be constructed")))
    monkeypatch.setattr(module, "_fetch_pykrx_series", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("live PyKRX probe must not be called")))

    result = module.run_offline_replay()
    assert result["status"] == "READY_FOR_ARCHITECT_KRX_INDEX_SERIES_MAPPING_V01_FIX01_REVIEW"
    assert result["krx_open_api_attempts"] == 0
    assert result["pykrx_network_operations"] == 0
