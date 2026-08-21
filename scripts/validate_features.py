"""Feature Validation v0.1 실행 스크립트.

실제 KRX 종목의 최근 약 10년 일봉을 MarketDataRepository로 수집하고,
주봉/월봉으로 변환한 뒤 기존 Feature 함수로 원본값을 계산해 CSV와
사람이 읽기 좋은 리포트로 출력한다. Pattern A 점수는 계산하지 않는다.

실행 (repo 루트에서, `pip install -e ".[dev]"` 이후):
    python scripts/validate_features.py

KRX_ID/KRX_PW가 필요하면 repo 루트의 .env에 채운다(docs/architecture/data_layer.md 참고).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.pykrx_provider import PyKrxDataProvider
from trend_scanner.data.repository import MarketDataRepository
from trend_scanner.data.resampler import to_monthly, to_weekly
from trend_scanner.validation.feature_report import (
    build_feature_row,
    format_human_report,
    to_csv_row,
)

# 검증 대상 종목. 여기만 수정하면 대상을 바꿀 수 있다.
TICKERS: list[tuple[str, str]] = [
    ("068270", "셀트리온"),
    ("035420", "NAVER"),
    ("005930", "삼성전자"),
    ("000660", "SK하이닉스"),
]

LOOKBACK_YEARS = 10

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "data" / "raw" / "stocks"
OUTPUT_CSV = REPO_ROOT / "data" / "processed" / "feature_validation.csv"


def _date_range(years: int) -> tuple[str, str]:
    end = pd.Timestamp.today().normalize()
    start = end - pd.DateOffset(years=years)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def main() -> None:
    provider = PyKrxDataProvider(adjusted=True)
    cache = ParquetCache(base_dir=CACHE_DIR)
    repository = MarketDataRepository(provider, cache)

    start, end = _date_range(LOOKBACK_YEARS)
    print(f"기간: {start} ~ {end} (최대 {LOOKBACK_YEARS}년, 상장 기간이 짧으면 존재하는 만큼만)")
    print()

    rows = []
    failures: list[tuple[str, str, str]] = []
    for ticker, name in TICKERS:
        try:
            daily = repository.get_daily(ticker, start, end)
            weekly = to_weekly(daily)
            monthly = to_monthly(daily)
            row = build_feature_row(ticker, name, daily, weekly, monthly)
        except MarketDataError as exc:
            # 한 종목의 데이터 품질 문제(예: OHLC 관계 위반)로 전체 실행이 죽지
            # 않도록 한다. Data Layer의 validator는 그대로 두고(엄격 검증이 맞음),
            # 이 스크립트 레벨에서만 종목 단위로 격리한다.
            print(f"[{ticker} {name}] 실패: {exc}")
            print("=" * 60)
            print()
            failures.append((ticker, name, str(exc)))
            continue

        rows.append(row)
        print(format_human_report(row))
        print("=" * 60)
        print()

    if failures:
        print(f"실패한 종목 {len(failures)}건: {[f'{t} {n}' for t, n, _ in failures]}")
        print()

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    csv_df = pd.DataFrame([to_csv_row(r) for r in rows])
    csv_df.to_csv(OUTPUT_CSV, index=False)
    print(f"CSV saved: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
