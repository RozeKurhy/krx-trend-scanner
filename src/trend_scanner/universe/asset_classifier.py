"""Pattern A Asset Type Classifier.

종목 코드 및 종목명을 분석하여 자산 유형(보통주, 우선주, SPAC, REIT, ETF, ETN 등)을 분류한다.
"""

from __future__ import annotations

import re

from trend_scanner.universe.models import AssetType

# 주요 ETF/ETN 브랜드 및 키워드 패턴
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


def classify_asset_type(ticker: str, name: str) -> AssetType:
    """종목 코드와 종목명을 기반으로 AssetType을 판별한다.

    1. ETF / ETN 판별
    2. SPAC 판별
    3. REIT (부동산투자회사) 판별
    4. 우선주 판별 (코드 끝자리 != '0' 또는 이름 패턴)
    5. 보통주 (위 조건에 해당하지 않는 일반 주식)
    """
    clean_ticker = str(ticker).strip().zfill(6)
    clean_name = str(name).strip()
    upper_name = clean_name.upper()

    # 1. ETN 판별
    if "ETN" in upper_name:
        return AssetType.ETN

    # 2. ETF 판별
    if "ETF" in upper_name:
        return AssetType.ETF
    for prefix in _ETF_PREFIXES:
        if upper_name.startswith(prefix.upper() + " ") or upper_name.startswith(prefix.upper()):
            # 단, 일반 기업명(예: '한화', '삼성전자')과 혼동되지 않도록 공백/특수문자 패턴 확인
            if any(upper_name.startswith(p + " ") for p in _ETF_PREFIXES):
                return AssetType.ETF

    # 3. SPAC 판별
    if "스팩" in clean_name or "SPAC" in upper_name:
        return AssetType.SPAC

    # 4. REIT 판별
    if "리츠" in clean_name or "REIT" in upper_name or "부동산투자회사" in clean_name:
        return AssetType.REIT

    # 5. 우선주 판별
    # 한국 거래소 6자리 종목코드에서 보통주는 6번째 자리가 '0'이며, 우선주는 '5', '7', '8', '9', 'K', 'L' 등이다.
    if len(clean_ticker) == 6 and clean_ticker[-1] != "0":
        return AssetType.PREFERRED

    # 이름 끝에 '우', '우B', '우C', '1우', '2우', '3우' 등이 붙은 경우
    if re.search(r"(우|우B|우C|1우|2우|3우|1우B|2우B|3우B|\(전환\))$", clean_name):
        return AssetType.PREFERRED

    # 6. 보통주
    if len(clean_ticker) == 6 and clean_ticker[-1] == "0":
        return AssetType.COMMON

    return AssetType.UNKNOWN
