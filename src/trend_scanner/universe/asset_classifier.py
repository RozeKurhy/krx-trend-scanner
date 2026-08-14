"""Pattern A Asset Type Classifier.

종목 코드 및 종목명을 분석하여 자산 유형(보통주, 우선주, SPAC, REIT, ETF, ETN 등)을 분류한다.
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
    """종목 코드와 종목명을 기반으로 AssetType을 판별한다.

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
    if "리츠" in clean_name or "REIT" in upper_name or "부동산투자회사" in clean_name:
        return AssetType.REIT

    # 5. 우선주 판별
    # 종목명 끝에 명시적인 우선주 접미사가 붙어 있거나, 종목코드 끝자리가 특수 접미(5, 7, 8, 9, K, L 등)이면서 이름에 '우'가 포함된 경우
    if _PREFERRED_NAME_PATTERN.search(clean_name):
        return AssetType.PREFERRED
    if len(clean_ticker) == 6 and clean_ticker[-1] in ("5", "7", "8", "9", "K", "L") and "우" in clean_name:
        return AssetType.PREFERRED

    # 6. 보통주 판별
    # 한국 거래소의 일반 보통주는 6자리 숫자로 구성되며 특수 상품 키워드가 없음
    if len(clean_ticker) == 6 and clean_ticker.isdigit():
        return AssetType.COMMON

    return AssetType.UNKNOWN
