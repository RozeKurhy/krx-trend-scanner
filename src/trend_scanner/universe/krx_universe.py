"""Official KRX Universe Acquisition.

PyKRX를 통해 공인 KRX 종목 마스터(KOSPI, KOSDAQ) 및 최신 영업일을 안전하게 로딩한다.
"""

from __future__ import annotations

import logging

from dotenv import load_dotenv

load_dotenv()

from pykrx import stock

from trend_scanner.data.errors import MarketDataError
from trend_scanner.universe.models import MarketType, UniverseSecurity

logger = logging.getLogger(__name__)


def get_latest_market_trading_date() -> str:
    """공식 KRX의 최신 영업일(YYYYMMDD 형식)을 확인하여 'YYYY-MM-DD'로 반환한다."""
    try:
        raw_date = stock.get_nearest_business_day_in_a_week()
        if not raw_date or len(raw_date) != 8:
            raise MarketDataError(f"유효하지 않은 영업일 응답: {raw_date}")
        return f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
    except Exception as exc:
        raise MarketDataError(f"KRX 최신 영업일 조회 실패: {exc}") from exc


def load_krx_equity_universe(as_of: str | None = None) -> list[UniverseSecurity]:
    """공인 KRX KOSPI 및 KOSDAQ 주식 유니버스 종목 목록을 조회한다.

    [Fail-Closed 원칙]:
    - 공식 종목명 조회가 실패(None 또는 빈 문자열)하는 경우 ticker 코드로 대체하지 않고
      명시적으로 MarketDataError를 발생시킨다 (불완전 metadata의 fail-open 방지).

    Args:
        as_of: 조회 기준일 (YYYY-MM-DD 또는 YYYYMMDD, 생략 시 최신 영업일)

    Returns:
        list[UniverseSecurity]: KOSPI 및 KOSDAQ에 상장된 종목 마스터 목록 (KONEX 제외)

    Raises:
        MarketDataError: KRX API 조회 실패 시 발생 (캐시 파일로 조용히 fallback하지 않음)
    """
    if as_of is None:
        target_date_formatted = get_latest_market_trading_date()
        target_date_api = target_date_formatted.replace("-", "")
    else:
        target_date_api = str(as_of).replace("-", "").strip()

    securities: list[UniverseSecurity] = []

    # 1. KOSPI 종목 로딩
    try:
        kospi_tickers = stock.get_market_ticker_list(date=target_date_api, market="KOSPI")
        if not kospi_tickers:
            raise MarketDataError(f"KOSPI 종목 목록이 비어 있습니다 (date={target_date_api}).")
        for ticker in kospi_tickers:
            raw_name = stock.get_market_ticker_name(ticker)
            if not raw_name or not str(raw_name).strip():
                raise MarketDataError(
                    f"KOSPI 종목명 조회 실패 (ticker={ticker}, date={target_date_api})."
                )
            securities.append(
                UniverseSecurity(
                    ticker=str(ticker).strip().zfill(6),
                    name=str(raw_name).strip(),
                    market=MarketType.KOSPI,
                    metadata_source="OFFICIAL_KRX",
                )
            )
    except Exception as exc:
        raise MarketDataError(f"KOSPI 종목 마스터 조회 실패 (date={target_date_api}): {exc}") from exc

    # 2. KOSDAQ 종목 로딩
    try:
        kosdaq_tickers = stock.get_market_ticker_list(date=target_date_api, market="KOSDAQ")
        if not kosdaq_tickers:
            raise MarketDataError(f"KOSDAQ 종목 목록이 비어 있습니다 (date={target_date_api}).")
        for ticker in kosdaq_tickers:
            raw_name = stock.get_market_ticker_name(ticker)
            if not raw_name or not str(raw_name).strip():
                raise MarketDataError(
                    f"KOSDAQ 종목명 조회 실패 (ticker={ticker}, date={target_date_api})."
                )
            securities.append(
                UniverseSecurity(
                    ticker=str(ticker).strip().zfill(6),
                    name=str(raw_name).strip(),
                    market=MarketType.KOSDAQ,
                    metadata_source="OFFICIAL_KRX",
                )
            )
    except Exception as exc:
        raise MarketDataError(f"KOSDAQ 종목 마스터 조회 실패 (date={target_date_api}): {exc}") from exc

    # Deterministic 정렬 (market -> ticker)
    securities.sort(key=lambda s: (s.market.value, s.ticker))
    return securities
