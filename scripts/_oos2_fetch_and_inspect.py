"""OOS2 후보 종목의 raw 일봉을 캐시에 채우고 raw 가격 구조만 출력/저장한다
(1회성 조사용 스크립트, Feature/Score는 절대 계산하지 않는다).

목적: Pattern A Score v0.2 OOS2 snapshot을 Score/Feature 값을 보지 않고
raw monthly/weekly close 모양만 보고 고르기 위함(OOS v0.1 선정 때와 같은
원칙 — scripts/_oos_fetch_and_inspect.py 참고).

여기서 계산하는 것들(range_36m_raw/position_raw/ma24_raw_slope/
ma12w_raw_slope)은 trend_scanner.features의 어떤 함수도 호출하지 않는다
— 전부 이 스크립트 안에서 pandas rolling으로 직접 계산한 "raw 가격 구조"
보조 지표다. v0.1/v0.2 Score의 curve breakpoint(예: ma24_slope 0.05,
weekly_ma12_slope 0.15)를 선정 cutoff로 쓰지 않는다 — 그건 Score 자체의
판단 기준을 선정 단계로 끌어오는 것이라 순환 논리가 된다. 여기 출력은
"어느 시점에 24개월선이 평탄~하락에서 우상향으로 바뀌는지", "36개월
박스권 대비 지금 어디 있는지" 같은 구조를 사람이 눈으로 보고 판단하기
위한 참고 자료일 뿐이다.

기존 development 종목(exploration/holdout/negative_control/OOS v0.1 29건/
score_v02_candidate_compare 64 snapshot에 쓰인 종목 33개)과 OOS v0.1
선정 당시 검토했지만 최종 미사용한 종목(000720/010060/010950/011070 —
이미 한 번 "선정 후보"로 본 종목이라 OOS2의 ticker ∩ development = 0
주장을 흐릴 수 있어 제외)은 후보에서 뺐다.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.pykrx_provider import PyKrxDataProvider
from trend_scanner.data.repository import MarketDataRepository
from trend_scanner.data.resampler import to_monthly, to_weekly

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "data" / "raw" / "stocks"
OUTPUT_MONTHLY_CSV = REPO_ROOT / "data" / "processed" / "oos2_selection_monthly_close.csv"
OUTPUT_SUMMARY_CSV = REPO_ROOT / "data" / "processed" / "oos2_selection_raw_summary.csv"

# 조회 구간을 절대 날짜로 고정한다(OOS v0.1과 동일 원칙) — 재실행 시점마다
# 구간이 달라지면 "당시 본 selection evidence"를 재현할 수 없다. 종료일은
# selection_reason이 snapshot 이후 trajectory를 참조할 수 있어야 하므로
# (item 9) 최신 스냅샷 뒤로도 충분히 데이터가 남도록 여유를 둔다.
OOS2_SELECTION_START = "2011-01-01"
OOS2_SELECTION_END = "2025-12-31"

# 43종목 over-fetch(회원사 인적분할/거래정지/validate_ohlcv 거부 등으로
# 몇 개는 빠질 것을 감안 — OOS v0.1 때도 26개 중 7개가 빠졌다).
CANDIDATES: list[tuple[str, str]] = [
    ("005940", "NH투자증권"),
    ("105560", "KB금융"),
    ("055550", "신한지주"),
    ("086790", "하나금융지주"),
    ("316140", "우리금융지주"),
    ("024110", "기업은행"),
    ("000810", "삼성화재"),
    ("001450", "현대해상"),
    ("030200", "KT"),
    ("017670", "SK텔레콤"),
    ("032640", "LG유플러스"),
    ("015760", "한국전력"),
    ("011210", "현대위아"),
    ("097230", "HJ중공업"),
    ("004000", "롯데정밀화학"),
    ("011780", "금호석유"),
    ("006650", "대한유화"),
    ("034220", "LG디스플레이"),
    ("042700", "한미반도체"),
    ("240810", "원익IPS"),
    ("353200", "대덕전자"),
    ("267260", "HD현대일렉트릭"),
    ("267250", "HD현대"),
    ("004170", "신세계"),
    ("023530", "롯데쇼핑"),
    ("007070", "GS리테일"),
    ("271560", "오리온"),
    ("004370", "농심"),
    ("002270", "롯데칠성"),
    ("128940", "한미약품"),
    ("069620", "대웅제약"),
    ("145020", "휴젤"),
    ("214150", "클래시스"),
    ("403870", "HPSP"),
    ("000880", "한화"),
    ("001040", "CJ"),
    ("032350", "롯데관광개발"),
    ("000100", "유한양행"),
    ("005180", "빙그레"),
    ("006260", "LS"),
    ("001120", "LX인터내셔널"),
    ("009830", "한화솔루션"),
    ("005850", "에스엘"),
]


def _date_range() -> tuple[str, str]:
    return OOS2_SELECTION_START, OOS2_SELECTION_END


def _raw_summary_rows(ticker: str, name: str, monthly: pd.DataFrame, weekly: pd.DataFrame) -> list[dict]:
    """월봉/주봉 close만으로 계산한 raw 구조 보조 지표. Feature/Score 미사용."""
    m_close = monthly["close"]
    w_close = weekly["close"]

    ma24_raw = m_close.rolling(24).mean()
    ma24_raw_slope_6m = ma24_raw.pct_change(6)

    ma12w_raw = w_close.rolling(12).mean()
    ma12w_raw_slope_8w = ma12w_raw.pct_change(8)

    roll36_high = m_close.rolling(36).max()
    roll36_low = m_close.rolling(36).min()
    range_36m_raw = (roll36_high - roll36_low) / roll36_low
    position_36m_raw = (m_close - roll36_low) / (roll36_high - roll36_low)

    rows = []
    for month_end, close in m_close.items():
        w_asof = ma12w_raw_slope_8w.asof(month_end)
        rows.append(
            {
                "ticker": ticker,
                "name": name,
                "month": month_end.strftime("%Y-%m"),
                "close": close,
                "range_36m_raw": range_36m_raw.get(month_end),
                "position_36m_raw": position_36m_raw.get(month_end),
                "ma24_raw_slope_6m": ma24_raw_slope_6m.get(month_end),
                "ma12w_raw_slope_8w": w_asof,
            }
        )
    return rows


def main() -> None:
    provider = PyKrxDataProvider(adjusted=True)
    cache = ParquetCache(base_dir=CACHE_DIR)
    repository = MarketDataRepository(provider, cache)
    start, end = _date_range()

    monthly_rows: list[dict] = []
    summary_rows: list[dict] = []

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
        weekly = to_weekly(daily)
        closes = monthly["close"]
        print(
            f"  일봉 {len(daily)}행 ({daily.index.min().date()} ~ {daily.index.max().date()}), "
            f"월봉 {len(closes)}개"
        )

        yearly_last = closes.groupby(closes.index.year).last()
        print("  연말(또는 최근월) 종가:")
        for year, value in yearly_last.items():
            print(f"    {year}: {value:,.0f}")

        rows = _raw_summary_rows(ticker, name, monthly, weekly)
        summary_rows.extend(rows)

        # 최근 3년 raw 구조 보조 지표만 화면에 출력(전수는 CSV에 저장).
        recent = [r for r in rows if r["month"] >= f"{pd.Timestamp(end).year - 3}-01"]
        print("  최근 raw 구조(month / close / range_36m_raw / position_36m_raw / ma24_slope_6m / ma12w_slope_8w):")
        for r in recent:
            def _fmt(x: float | None) -> str:
                return "NaN" if x is None or pd.isna(x) else f"{x:+.3f}"

            print(
                f"    {r['month']}  {r['close']:>10,.0f}  "
                f"range={_fmt(r['range_36m_raw'])}  pos={_fmt(r['position_36m_raw'])}  "
                f"ma24_6m={_fmt(r['ma24_raw_slope_6m'])}  ma12w_8w={_fmt(r['ma12w_raw_slope_8w'])}"
            )
        print()

        for month_end, close in closes.items():
            monthly_rows.append(
                {"ticker": ticker, "name": name, "month": month_end.strftime("%Y-%m"), "close": close}
            )

    OUTPUT_MONTHLY_CSV.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(monthly_rows).to_csv(OUTPUT_MONTHLY_CSV, index=False)
    pd.DataFrame(summary_rows).to_csv(OUTPUT_SUMMARY_CSV, index=False)
    print(f"CSV saved: {OUTPUT_MONTHLY_CSV} ({len(monthly_rows)} rows, close만 — Feature/Score 없음)")
    print(f"CSV saved: {OUTPUT_SUMMARY_CSV} ({len(summary_rows)} rows, raw 구조 보조 지표 — Feature/Score 없음)")


if __name__ == "__main__":
    main()
