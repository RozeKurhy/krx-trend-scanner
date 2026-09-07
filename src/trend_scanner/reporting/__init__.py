"""Stock Report Generation & Reporting Layer.

로컬 일봉 시세 및 정본 아티팩트를 기반으로 단일 종목의 현재 상태,
월별 국면 추이, 외국인 수급 및 거래대금 흐름을 리포트로 생성한다.
"""

from __future__ import annotations

from trend_scanner.reporting.stock_report import generate_stock_report
from trend_scanner.reporting.fundamentals_report import build_fundamentals_section
from trend_scanner.reporting.sector_relative_strength_report import build_sector_relative_strength_section

__all__ = [
    "generate_stock_report",
    "build_fundamentals_section",
    "build_sector_relative_strength_section",
]
