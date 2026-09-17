krx_index_series_mapping_v01.md
================================================================================
KRX native sector index mapping V01
================================================================================

목적
--------------------------------------------------------------------------------
기존 KOSPI 24개 및 KOSDAQ 22개 PyKRX sector code를 KRX Open API의 native
market index row에 6개 거래일 OHLC price identity로 검증한다. 이 문서는
validation-only 경계를 정의하며 production Sector RS provider를 교체하지 않는다.

검증 계약
--------------------------------------------------------------------------------
| 대상                         | 기준                                      |
|------------------------------|-------------------------------------------|
| KOSPI sector code             | kospi_dd_trd row만 후보                  |
| KOSDAQ sector code            | kosdaq_dd_trd row만 후보                 |
| identity fields               | open/high/low/close                       |
| identity comparison           | canonical Decimal exact                   |
| volume/trading value          | mapping identity에서 제외                |
| fingerprint dates             | 2026-07-24, 07-31, 08-07, 08-14, 08-20, 08-21 |
| PyKRX probe                   | code당 range call 1회, sequential, 0.75초 |

이름과 taxonomy
--------------------------------------------------------------------------------
이름 기반 추정은 primary mapping 근거가 아니다. exact price identity 후
official IDX_NM을 sanity check하며, 이름이 다르면 NAME_SEMANTIC_WARNING을
남긴다. KRX-branded sector/industry series는 native 46-code taxonomy와 별도
source-qualified 축으로 유지하고 drop-in replacement로 취급하지 않는다.

네트워크 안전
--------------------------------------------------------------------------------
KRX Open API는 동일 날짜/API snapshot을 한 번만 호출하고 총 30 attempt budget을
사용한다. PyKRX는 병렬 호출·ticker/name sweep 없이 순차 호출하며 code당 최대 1
retry, 총 60 operations ceiling을 둔다. 연속 empty/parser/network failure가
3회면 PYKRX_SUSPECTED_THROTTLE_OR_BLOCK으로 즉시 중단한다.

생산 동결
--------------------------------------------------------------------------------
PyKrxDataProvider, MarketDataRepository, IndexPriceDataProvider production
default, Pattern A, FastCore, Julia, Foreign Flow, Fundamentals, RS formula,
scanner scoring, backtest와 ticker→sector membership PIT는 변경하지 않는다.
index price-history PIT와 ticker membership PIT는 별도 문제다.
