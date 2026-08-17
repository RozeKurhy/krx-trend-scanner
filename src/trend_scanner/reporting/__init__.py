"""Stock Report Generation & Reporting Layer.

로컬 일봉 시세 및 정본 아티팩트를 기반으로 단일 종목의 현재 상태,
월별 국면 추이, 외국인 수급 및 거래대금 흐름을 리포트로 생성한다.
"""

from __future__ import annotations

from trend_scanner.reporting.stock_report import generate_stock_report

__all__ = [
    "generate_stock_report",
]
