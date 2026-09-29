from __future__ import annotations

import pandas as pd

from scripts.build_etf_official_universe_refinement_v02 import (
    classify_product,
    hard_filter_failures,
    select_group_representatives,
)


def product(name: str, objective: str, *, asset: str = "주식") -> dict[str, str]:
    return {
        "ISU_NM": name,
        "ISU_ABBRV": name,
        "ISU_ENG_NM": "",
        "ETF_OBJ_IDX_NM": objective,
        "IDX_ASST_CLSS_NM": asset,
    }


def test_classifies_broad_groups_and_excludes_narrow_or_structured_products() -> None:
    assert classify_product(product("KODEX 200", "코스피 200"))["representative_group"] == "KOREA_BROAD"
    assert classify_product(product("KODEX 코스피", "코스피"))["representative_group"] == "KOREA_BROAD"
    assert classify_product(product("KODEX IT", "코스피 200 정보기술"))["major_category"] == "SECTOR_INDEX"
    assert classify_product(product("KODEX 필수소비재", "KRX 필수소비재"))["representative_group"] == "CONSUMER_STAPLES"
    assert classify_product(product("KODEX 미국 금융", "S&P Financial Select Sector Index"))["representative_group"] == "FINANCIALS"
    assert classify_product(product("TIGER 여행레저", "WISE 여행레저 지수"))["representative_group"] == "TRAVEL_LEISURE"
    assert classify_product(product("TIGER 미국다우존스30", "Dow Jones Industrial Average"))["major_category"] == "MARKET_INDEX"
    assert classify_product(product("TIGER 반도체TOP10", "FnGuide 반도체 TOP 10 지수"))["major_category"] == "OUT_OF_SCOPE"
    assert classify_product(product("KODEX AI전력핵심설비", "iSelect AI 전력핵심설비 지수"))["major_category"] == "OUT_OF_SCOPE"
    assert classify_product(product("KODEX 200 커버드콜", "KOSPI 200 Covered Call"))["major_category"] == "OUT_OF_SCOPE"
    assert classify_product(product("KODEX 국고채", "KRX 국고채", asset="채권"))["major_category"] == "OUT_OF_SCOPE"


def test_commodity_mapping_avoids_korean_substring_false_positives() -> None:
    copper = classify_product(product("TIGER 구리실물", "S&P GSCI Cash Copper Index", asset="원자재"))
    gold = classify_product(product("KODEX 골드선물(H)", "S&P GSCI Gold Index(TR)", asset="원자재"))
    assert copper["representative_group"] == "COPPER"
    assert copper["product_structure"] == "PLAIN_LONG_SPOT"
    assert gold["representative_group"] == "GOLD"
    assert gold["product_structure"] == "PLAIN_LONG_FUTURES"


def test_exact_hard_filter_boundaries_pass_and_each_below_threshold_fails() -> None:
    base = {
        "major_category": "MARKET_INDEX",
        "representative_group": "KOREA_BROAD",
        "classification_reason": "BROAD_MARKET_INDEX",
        "listing_date": "2024-09-23",
        "reference_close": 1000,
        "raw_session_count_40d": 40,
        "avg_volume_40d": 10000,
        "avg_trading_value_40d": 300_000_000,
    }
    assert hard_filter_failures(base, "2026-09-23") == []
    assert "LISTING_AGE_LT_2Y" in hard_filter_failures({**base, "listing_date": "2024-09-24"}, "2026-09-23")
    assert "REFERENCE_CLOSE_LT_1000_KRW" in hard_filter_failures({**base, "reference_close": 999}, "2026-09-23")
    assert "AVG_VOLUME_40D_LT_10000_SHARES" in hard_filter_failures({**base, "avg_volume_40d": 9999}, "2026-09-23")
    assert "AVG_TRADING_VALUE_40D_LT_300M_KRW" in hard_filter_failures({**base, "avg_trading_value_40d": 299_999_999}, "2026-09-23")
    assert "INCOMPLETE_EXACT_40D_RAW_SESSIONS" in hard_filter_failures({**base, "raw_session_count_40d": 39}, "2026-09-23")


def test_selects_turnover_leader_and_prefers_spot_commodity() -> None:
    frame = pd.DataFrame(
        [
            {"major_category": "MARKET_INDEX", "representative_group": "KOREA_BROAD", "ticker": "000002", "avg_trading_value_40d": 995, "AUM_if_available": 100, "listing_age_days": 1000, "product_structure": "PLAIN_LONG"},
            {"major_category": "MARKET_INDEX", "representative_group": "KOREA_BROAD", "ticker": "000001", "avg_trading_value_40d": 1000, "AUM_if_available": 1, "listing_age_days": 900, "product_structure": "PLAIN_LONG"},
            {"major_category": "MARKET_INDEX", "representative_group": "KOSDAQ_BROAD", "ticker": "000005", "avg_trading_value_40d": 1000, "AUM_if_available": 1, "listing_age_days": 1000, "product_structure": "PLAIN_LONG"},
            {"major_category": "MARKET_INDEX", "representative_group": "KOSDAQ_BROAD", "ticker": "000006", "avg_trading_value_40d": 980, "AUM_if_available": 200, "listing_age_days": 900, "product_structure": "PLAIN_LONG"},
            {"major_category": "COMMODITY_RESOURCE", "representative_group": "COPPER", "ticker": "000003", "avg_trading_value_40d": 3000, "AUM_if_available": 100, "listing_age_days": 1000, "product_structure": "PLAIN_LONG_FUTURES"},
            {"major_category": "COMMODITY_RESOURCE", "representative_group": "COPPER", "ticker": "000004", "avg_trading_value_40d": 2000, "AUM_if_available": 10, "listing_age_days": 900, "product_structure": "PLAIN_LONG_SPOT"},
        ]
    )
    selected = select_group_representatives(frame)
    winners = {(row.major_category, row.representative_group): row.ticker for row in selected.itertuples(index=False)}
    assert winners[("MARKET_INDEX", "KOREA_BROAD")] == "000002"
    assert winners[("MARKET_INDEX", "KOSDAQ_BROAD")] == "000005"
    assert winners[("COMMODITY_RESOURCE", "COPPER")] == "000004"
