from __future__ import annotations

from scripts.build_etf_plain_long_universe_v05 import classify_product


def _product(**overrides: str) -> dict[str, str]:
    row = {
        "ISU_CD": "KR7000000001",
        "ISU_SRT_CD": "000001",
        "ISU_NM": "Test ETF",
        "ISU_ABBRV": "Test ETF",
        "ISU_ENG_NM": "Test ETF",
        "LIST_DD": "2020/01/01",
        "ETF_OBJ_IDX_NM": "코스피 200",
        "ETF_REPLICA_METHD_TP_CD": "일반",
        "IDX_MKT_CLSS_NM": "국내",
        "IDX_ASST_CLSS_NM": "주식",
    }
    row.update(overrides)
    return row


def test_official_sector_objective_is_included() -> None:
    result = classify_product(_product(ETF_OBJ_IDX_NM="FnGuide 반도체 지수"))
    assert result["category"] == "SECTOR_INDUSTRY"
    assert result["plain_long"] is True
    assert result["include"] is True


def test_dividend_growth_market_benchmark_is_excluded_as_style() -> None:
    result = classify_product(_product(
        ISU_ABBRV="TIGER 배당성장",
        ETF_OBJ_IDX_NM="코스피 배당성장 50 지수",
    ))
    assert result["category"] == "MARKET_INDEX"
    assert result["include"] is False
    assert result["exclude_reason"] == "HIGH_DIVIDEND_OR_INCOME_STYLE"


def test_replication_metadata_blocks_leveraged_product() -> None:
    result = classify_product(_product(ETF_REPLICA_METHD_TP_CD="2X 레버리지"))
    assert result["plain_long"] is False
    assert result["include"] is False
    assert result["exclude_reason"] == "LEVERAGE_INVERSE_OR_SHORT"


def test_bond_asset_class_is_excluded() -> None:
    result = classify_product(_product(
        ETF_OBJ_IDX_NM="국고채 총수익지수",
        IDX_ASST_CLSS_NM="채권",
    ))
    assert result["category"] == "FIXED_INCOME_RATE_CASH_EXCLUDED"
    assert result["include"] is False


def test_clear_commodity_resource_is_included() -> None:
    result = classify_product(_product(
        ETF_OBJ_IDX_NM="KRX 금현물지수",
        IDX_ASST_CLSS_NM="원자재",
    ))
    assert result["category"] == "COMMODITY_RESOURCE"
    assert result["plain_long"] is True
    assert result["include"] is True


def test_narrow_ai_active_mandate_is_not_broad_market() -> None:
    result = classify_product(_product(
        ISU_ABBRV="FOCUS AI코리아액티브",
        ETF_OBJ_IDX_NM="코스피",
    ))
    assert result["category"] == "UNCLASSIFIED_EXCLUDED"
    assert result["include"] is False
    assert result["exclude_reason"] == "NARROW_ACTIVE_MANDATE_WITH_BROAD_REFERENCE_INDEX"


def test_unclear_objective_fails_closed() -> None:
    result = classify_product(_product(ETF_OBJ_IDX_NM=""))
    assert result["category"] == "UNCLASSIFIED_EXCLUDED"
    assert result["include"] is False
    assert result["exclude_reason"] == "AMBIGUOUS_OR_OUTSIDE_TARGET_CATEGORIES"
