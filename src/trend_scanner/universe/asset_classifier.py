"""Pattern A Asset Type Classifier (Diagnostic & Test Support).

자산 유형(보통주, 우선주, SPAC, REIT, ETF, ETN 등)을 진단/테스트/레거시 폴백 목적으로 판별한다.

주의 (IMPORTANT):
이 모듈의 `classify_asset_type`은 휴리스틱 기반 진단 유틸리티(`LEGACY_DIAGNOSTIC`, `QUALITY_WARNING`, `TEST_SUPPORT`)이며,
Production Runtime의 Asset Type Authority가 아닙니다.
Production Stock Report 및 전략 적격성 판정은 반드시 `trend_scanner.universe.instrument_metadata`의
정본 PIT 메타데이터(`InstrumentMetadataResolver`)를 사용해야 합니다.
"""

from __future__ import annotations

import re

from trend_scanner.universe.models import AssetType

# 주요 ETF/ETN 브랜드 및 키워드 접두사
_ETF_PREFIXES = (
    "KODEX",
    "TIGER",
    "KBSTAR",
    "ACE",
    "SOL",
    "PLUS",
    "RISE",
    "KOSEF",
    "HANARO",
    "ARIRANG",
    "TIMEFOLIO",
    "WOORI",
    "UNICORN",
    "히어로즈",
    "마이티",
    "파워",
    "FOCUS",
    "TREX",
    "HK",
)

# 우선주 종목명 접미사 패턴
_PREFERRED_NAME_PATTERN = re.compile(
    r"(우|우B|우C|우D|1우|2우|3우|1우B|2우B|3우B|4우B|\(전환\)|\(전환우\))$"
)


def classify_asset_type(ticker: str, name: str) -> AssetType:
    """종목 코드와 종목명을 기반으로 AssetType을 휴리스틱으로 판별한다 (진단/테스트 전용).

    1. ETN / ETF 판별
    2. SPAC 판별
    3. REIT (부동산투자회사) 판별
    4. 우선주 판별 (종목명 suffix 패턴 또는 검증된 우선주 코드 구조)
    5. 보통주 (위 조건에 해당하지 않고 정상 주식명/코드 구조를 갖춘 경우)
    6. 판별 불가 시 UNKNOWN
    """
    clean_ticker = str(ticker).strip().zfill(6)
    clean_name = str(name).strip()
    upper_name = clean_name.upper()

    if not clean_name or not clean_ticker:
        return AssetType.UNKNOWN

    # 1. ETN 판별
    if "ETN" in upper_name:
        return AssetType.ETN

    # 2. ETF 판별
    if "ETF" in upper_name:
        return AssetType.ETF
    for prefix in _ETF_PREFIXES:
        if upper_name.startswith(prefix.upper() + " ") or upper_name == prefix.upper():
            return AssetType.ETF

    # 3. SPAC 판별
    if "스팩" in clean_name or "SPAC" in upper_name:
        return AssetType.SPAC

    # 4. REIT 판별
    if clean_name.endswith("리츠") or clean_name.endswith("리츠1호") or "부동산투자회사" in clean_name or "REIT" in upper_name:
        return AssetType.REIT

    # 5. 우선주 판별
    if _PREFERRED_NAME_PATTERN.search(clean_name):
        return AssetType.PREFERRED
    if len(clean_ticker) == 6 and clean_ticker[-1] in ("5", "7", "8", "9", "K", "L") and "우" in clean_name:
        return AssetType.PREFERRED

    # 6. 보통주 판별
    if len(clean_ticker) == 6 and clean_ticker.isdigit():
        return AssetType.COMMON

    return AssetType.UNKNOWN
