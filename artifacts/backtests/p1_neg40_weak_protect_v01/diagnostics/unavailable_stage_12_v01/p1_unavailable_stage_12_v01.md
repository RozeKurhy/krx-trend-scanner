P1_UNAVAILABLE_12_DIAGNOSTIC_COMPLETE

# P1 unavailable-stage 12-case diagnostic

- 대상: 12개 실패 로그의 ticker/pair_id/EOD만
- 원인 분포: {"A_PIPELINE_BUG": 3, "B_LEGITIMATE_INSUFFICIENT_HISTORY": 0, "C_SOURCE_OR_AUTHORITY_GAP": 9, "D_TICKER_SPECIFIC_EXCEPTION": 0, "E_OTHER": 0}
- classifier reason: {"insufficient_data": 12}
- production code 변경: 없음 (diagnostic-only helper 추가)
- replay / 전략 변경 / 부분 raw 수정 / canonical 교체: 모두 없음
- 다음 권고: B. UNAVAILABLE semantics 설계 필요

| Ticker | ISU | 실패 EOD | Classifier reason | Missing features | Upstream cause | Cause class | 이전 usable stage/date | 다음 usable stage/date |
|---|---|---|---|---|---|---|---|---|
| 001140 | KR7001140003 | 2023-05-31 | insufficient_data | weekly_ma12_slope | weekly_ma12_slope: 3 empty weekly bucket(s) (2023-05-05..2023-05-19): 13 KRX trading sessions expected, but 0 Repository V2 daily rows; rolling OHLC close becomes NaN | C_SOURCE_OR_AUTHORITY_GAP | WEAK @ 2023-04-28 | WEAK @ 2023-09-27 |
| 009730 | KR7009730003 | 2017-12-21 | insufficient_data | weekly_ma12_slope | weekly_ma12_slope: 2017-10-06 empty weekly bin: 0 KRX sessions and 0 Repository V2 rows; resampler's volume sum leaves an all-price-NaN/volume-0 bucket in the rolling window | A_PIPELINE_BUG | WEAK @ 2017-09-29 | WEAK @ 2018-01-31 |
| 031980 | KR7031980006 | 2020-03-13 | insufficient_data | ma24_slope, ma_spread | ma24_slope: 1 empty monthly bucket(s) (2019-04-30..2019-04-30): 22 KRX trading sessions expected, but 0 Repository V2 daily rows; rolling OHLC close becomes NaN; ma_spread: 1 empty monthly bucket(s) (2019-04-30..2019-04-30): 22 KRX trading sessions expected, but 0 Repository V2 daily rows; rolling OHLC close becomes NaN | C_SOURCE_OR_AUTHORITY_GAP | PROGRESSED @ 2019-03-27 | PROGRESSED @ 2021-07-30 |
| 035290 | KR7035290006 | 2022-04-29 | insufficient_data | ma24_slope, weekly_ma12_slope, avg_price_change_12m, ma_spread | ma24_slope: 26 empty monthly bucket(s) (2020-02-29..2022-03-31): 535 KRX trading sessions expected, but 0 Repository V2 daily rows; rolling OHLC close becomes NaN; weekly_ma12_slope: 16 empty weekly bucket(s) (2022-01-07..2022-04-22): 75 KRX trading sessions expected, but 0 Repository V2 daily rows; rolling OHLC close becomes NaN; avg_price_change_12m: 23 empty monthly bucket(s) (2020-05-31..2022-03-31): 473 KRX trading sessions expected, but 0 Repository V2 daily rows; rolling OHLC close becomes NaN; ma_spread: 23 empty monthly bucket(s) (2020-05-31..2022-03-31): 473 KRX trading sessions expected, but 0 Repository V2 daily rows; rolling OHLC close becomes NaN | C_SOURCE_OR_AUTHORITY_GAP | WEAK @ 2019-09-23 | WEAK @ 2024-06-28 |
| 036260 | KR7036260008 | 2016-10-04 | insufficient_data | weekly_ma12_slope | weekly_ma12_slope: 3 empty weekly bucket(s) (2016-09-09..2016-09-23): 12 KRX trading sessions expected, but 0 Repository V2 daily rows; rolling OHLC close becomes NaN | C_SOURCE_OR_AUTHORITY_GAP | PROGRESSED @ 2016-08-31 | WEAK @ 2017-01-31 |
| 036620 | KR7036620003 | 2017-10-31 | insufficient_data | weekly_ma12_slope | weekly_ma12_slope: 2017-10-06 empty weekly bin: 0 KRX sessions and 0 Repository V2 rows; resampler's volume sum leaves an all-price-NaN/volume-0 bucket in the rolling window | A_PIPELINE_BUG | WEAK @ 2017-09-29 | TRANSITION @ 2018-01-31 |
| 043710 | KR7043710003 | 2017-01-18 | insufficient_data | ma24_slope, weekly_ma12_slope, ma_spread | ma24_slope: 5 empty monthly bucket(s) (2016-07-31..2016-11-30): 104 KRX trading sessions expected, but 0 Repository V2 daily rows; rolling OHLC close becomes NaN; weekly_ma12_slope: 16 empty weekly bucket(s) (2016-09-02..2016-12-16): 76 KRX trading sessions expected, but 0 Repository V2 daily rows; rolling OHLC close becomes NaN; ma_spread: 5 empty monthly bucket(s) (2016-07-31..2016-11-30): 104 KRX trading sessions expected, but 0 Repository V2 daily rows; rolling OHLC close becomes NaN | C_SOURCE_OR_AUTHORITY_GAP | PROGRESSED @ 2016-06-15 | WEAK @ 2019-02-28 |
| 044060 | KR7044060002 | 2025-08-20 | insufficient_data | ma24_slope, weekly_ma12_slope, avg_price_change_12m, ma_spread | ma24_slope: 26 empty monthly bucket(s) (2023-06-30..2025-07-31): 528 KRX trading sessions expected, but 0 Repository V2 daily rows; rolling OHLC close becomes NaN; weekly_ma12_slope: 16 empty weekly bucket(s) (2025-04-25..2025-08-08): 75 KRX trading sessions expected, but 0 Repository V2 daily rows; rolling OHLC close becomes NaN; avg_price_change_12m: 23 empty monthly bucket(s) (2023-09-30..2025-07-31): 464 KRX trading sessions expected, but 0 Repository V2 daily rows; rolling OHLC close becomes NaN; ma_spread: 23 empty monthly bucket(s) (2023-09-30..2025-07-31): 464 KRX trading sessions expected, but 0 Repository V2 daily rows; rolling OHLC close becomes NaN | C_SOURCE_OR_AUTHORITY_GAP | WEAK @ 2023-04-26 | 없음 |
| 052300 | KR7052300001 | 2017-12-20 | insufficient_data | weekly_ma12_slope | weekly_ma12_slope: 2017-10-06 empty weekly bin: 0 KRX sessions and 0 Repository V2 rows; resampler's volume sum leaves an all-price-NaN/volume-0 bucket in the rolling window | A_PIPELINE_BUG | WEAK @ 2017-09-29 | WEAK @ 2018-01-31 |
| 052400 | KR7052400009 | 2022-06-13 | insufficient_data | ma24_slope, ma_spread | ma24_slope: 6 empty monthly bucket(s) (2020-04-30..2020-09-30): 125 KRX trading sessions expected, but 0 Repository V2 daily rows; rolling OHLC close becomes NaN; ma_spread: 4 empty monthly bucket(s) (2020-06-30..2020-09-30): 86 KRX trading sessions expected, but 0 Repository V2 daily rows; rolling OHLC close becomes NaN | C_SOURCE_OR_AUTHORITY_GAP | TRANSITION @ 2020-03-19 | WEAK @ 2022-12-29 |
| 068150 | KR7068150002 | 2017-02-23 | insufficient_data | weekly_ma12_slope | weekly_ma12_slope: 6 empty weekly bucket(s) (2016-04-15..2016-05-20): 27 KRX trading sessions expected, but 0 Repository V2 daily rows; rolling OHLC close becomes NaN | C_SOURCE_OR_AUTHORITY_GAP | PROGRESSED @ 2016-04-04 | 없음 |
| 130660 | KR7130660004 | 2020-02-21 | insufficient_data | weekly_ma12_slope | weekly_ma12_slope: 2 empty weekly bucket(s) (2019-10-11..2019-10-18): 9 KRX trading sessions expected, but 0 Repository V2 daily rows; rolling OHLC close becomes NaN | C_SOURCE_OR_AUTHORITY_GAP | WEAK @ 2019-09-30 | WEAK @ 2020-02-28 |

## 분류 기준

- A_PIPELINE_BUG: 거래 세션이 0개인 달력 주가 volume=0/close=NaN 빈 resample bucket으로 rolling 계산에 포함됨
- B_LEGITIMATE_INSUFFICIENT_HISTORY: feature 산식의 최소 완료 monthly/weekly bar 수 미달
- C_SOURCE_OR_AUTHORITY_GAP: KRX 거래 세션은 있었지만 해당 구간 Repository V2 일봉이 0개
- D_TICKER_SPECIFIC_EXCEPTION: 충분한 입력에서 0 분모/평탄 범위 등 종목별 가격 예외
- E_OTHER: 위 기준으로 단정 불가한 기타 계산 이상

반복 원인: 달력상 거래 0일인 주의 빈 resample bucket이 3건에서 반복되고, 거래 세션 대비 Repository V2 가격행 공백이 9건에서 관찰됐다.
A 증거 코드 경로: `src/trend_scanner/data/resampler.py::_resample`의 volume `sum` 결과 0이 `dropna(how='all')` 이후에도 빈 OHLC bucket을 유지한다.
세부 수치, feature별 upstream 이유, 원인 bucket별 거래일/일봉 수, pair_id, session audit은 동반 CSV/JSON에 기록했다.
