"""Deterministic unit tests for V02 validation-only helpers."""

from scripts.validate_krx_open_api_v02 import (
    classify_index_name,
    field_presence,
    missing_value,
    normalize_basic_row,
    normalize_numeric,
    required_schema_missing,
    sector_match_status,
)


def test_basic_numeric_and_blank_values_remain_explicit() -> None:
    assert normalize_numeric("1,234") == 1234
    assert normalize_numeric("-") is None
    assert normalize_numeric(" 12.50 ") == 12.5
    assert missing_value("")
    assert missing_value("-")


def test_basic_normalizer_separates_standard_and_short_code() -> None:
    row = normalize_basic_row(
        {
            "ISU_CD": "KR7005930003", "ISU_SRT_CD": "005930", "ISU_NM": "삼성전자보통주",
            "ISU_ABBRV": "삼성전자", "ISU_ENG_NM": "Samsung Electronics",
            "LIST_DD": "1975/06/11", "MKT_TP_NM": "KOSPI", "SECUGRP_NM": "주권",
            "SECT_TP_NM": "", "KIND_STKCERT_TP_NM": "보통주", "PARVAL": "100", "LIST_SHRS": "5,846,278,608",
        },
        "2026-08-20",
    )
    assert row["requested_date"] == "2026-08-20"
    assert row["standard_code"] == "KR7005930003"
    assert row["ticker"] == "005930"
    assert row["listing_date"] == "19750611"
    assert row["par_value"] == 100
    assert row["listed_shares"] == 5846278608


def test_presence_ratio_distinguishes_missing_key_from_blank_value() -> None:
    result = {item["field_name"]: item for item in field_presence([{"A": "1", "B": ""}, {"A": "2"}])}
    assert result["A"]["field_presence_count"] == 2
    assert result["A"]["field_presence_ratio"] == 1.0
    assert result["B"]["field_presence_count"] == 1
    assert result["B"]["key_missing_count"] == 1
    assert result["B"]["blank_value_count"] == 1


def test_required_schema_is_endpoint_specific() -> None:
    assert "ISU_SRT_CD" in required_schema_missing("basic", [{"ISU_CD": "KR7005930003"}])
    assert "IDX_NM" in required_schema_missing("index", [{"BAS_DD": "20260820"}])


def test_index_inventory_taxonomy_is_conservative() -> None:
    assert classify_index_name("KRX 300") == "BROAD_MARKET"
    assert classify_index_name("KRX 반도체") == "SECTOR_INDUSTRY"
    assert classify_index_name("K-샤프지수(1년)") == "STRATEGY"
    assert classify_index_name("알 수 없는 지수") == "OTHER"
    assert classify_index_name("") == "UNKNOWN"


def test_sector_matching_does_not_treat_alias_as_exact() -> None:
    names = {"KRX 건설", "KRX 에너지화학"}
    assert sector_match_status("건설", names) == ("MAPPED_TO_KRX_SERIES", "KRX 건설")
    assert sector_match_status("화학", names) == ("AMBIGUOUS_NAME_MAPPING", "KRX 에너지화학")
    assert sector_match_status("섬유·의류", names)[0] == "MISSING_FROM_KRX_SERIES"
    assert sector_match_status(None, names)[0] == "INSUFFICIENT_LOCAL_EVIDENCE"
