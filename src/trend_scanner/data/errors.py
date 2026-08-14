"""데이터 계층 공통 예외."""

from __future__ import annotations


class MarketDataError(Exception):
    """외부 API 실패, 응답 형식 오류, invalid OHLCV 등 데이터 계층에서 발생하는 오류."""
