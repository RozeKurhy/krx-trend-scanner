"""OOS 후보 종목의 raw 일봉을 캐시에 채우고 월봉 종가만 출력한다(1회성
조사용 스크립트, Feature/Score는 절대 계산하지 않는다).

목적: OOS snapshot 날짜를 Feature/Score 값을 보지 않고 raw monthly close
모양만 보고 고르기 위함(negative_control 선정 때와 같은 원칙).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.pykrx_provider import PyKrxDataProvider
from trend_scanner.data.repository import MarketDataRepository
from trend_scanner.data.resampler import to_monthly

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "data" / "raw" / "stocks"

CANDIDATES: list[tuple[str, str]] = [
    ("010140", "삼성중공업"),
    ("009540", "HD한국조선해양"),
    ("010620", "HD현대미포"),
    ("005490", "POSCO홀딩스"),
    ("034020", "두산에너빌리티"),
    ("036570", "엔씨소프트"),
    ("251270", "넷마블"),
    ("090430", "아모레퍼시픽"),
    ("042660", "한화오션"),
    ("011790", "SKC"),
    ("010060", "OCI홀딩스"),
    ("004020", "현대제철"),
    ("161390", "한국타이어앤테크놀로지"),
    ("004990", "롯데지주"),
    ("011070", "LG이노텍"),
    ("000990", "DB하이텍"),
    ("097950", "CJ제일제당"),
    ("006800", "미래에셋증권"),
    ("069960", "현대백화점"),
    ("247540", "에코프로비엠"),
]

LOOKBACK_YEARS = 12


def _date_range(years: int) -> tuple[str, str]:
    end = pd.Timestamp.today().normalize()
    start = end - pd.DateOffset(years=years)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def main() -> None:
    provider = PyKrxDataProvider(adjusted=True)
    cache = ParquetCache(base_dir=CACHE_DIR)
    repository = MarketDataRepository(provider, cache)
    start, end = _date_range(LOOKBACK_YEARS)

    for ticker, name in CANDIDATES:
        print("=" * 80)
        print(f"{ticker} {name}")
        print("=" * 80)
        try:
            daily = repository.get_daily(ticker, start, end)
        except MarketDataError as exc:
            print(f"  SKIP(MarketDataError): {exc}")
            continue
        if daily.empty:
            print("  SKIP(빈 데이터)")
            continue

        monthly = to_monthly(daily)
        closes = monthly["close"]
        print(f"  일봉 {len(daily)}행 ({daily.index.min().date()} ~ {daily.index.max().date()}), "
              f"월봉 {len(closes)}개")

        # 연도별 마지막 월 종가만 출력해서 큰 흐름만 본다(raw close만, Feature 없음).
        yearly_last = closes.groupby(closes.index.year).last()
        print("  연말(또는 최근월) 종가:")
        for year, value in yearly_last.items():
            print(f"    {year}: {value:,.0f}")
        print()


if __name__ == "__main__":
    main()
