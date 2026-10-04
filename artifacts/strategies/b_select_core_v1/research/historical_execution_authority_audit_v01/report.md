# B Select Historical Execution Authority Discrepancy Audit V01

작성일: 2026-10-05 KST
감사 기준 HEAD: `ca2b60ab09f19ec4d42494dffa29b7079c026c6b`
범위: historical authority 감사만 수행. 공식 history, 5-window 산출물, Production trading history와 전략 동작은 수정하지 않음.

## 요약

| 레벨 | 개수 | 판단 |
|---|---:|---|
| CRITICAL | 0 | Production 동작 및 주문 데이터 변경 없음. 감사 대상은 과거 종료 거래 기록임. |
| MAJOR | 11 | 다음 KRX 세션에 실제 거래가 확인되지만 저장 체결일이 늦음. 5-window 성과에 영향 가능성이 있음. |
| MINOR | 0 | 해당 없음. |

**판정: `B_SELECT_HISTORICAL_EXECUTION_AUTHORITY_AUDIT_CHECK_REQUIRED`**

11건 각각에서 현재 KRX 원시 일별 스냅샷은 예상 다음 세션의 거래량이 양수이고, 현재 조정 가격 authority도 유효한 시가를 제공한다. 종목 identity는 두 날짜 사이 계속 유효하며 KRX 상장주식수도 바뀌지 않았다. 따라서 현재 증거로는 정지/비거래 또는 corporate action으로 늦어진 것으로 설명할 수 없다.

과거 생성기의 실제 규칙은 신호일 이후 종목별 daily frame에서 처음 관측되는 bar를 선택하는 방식이었다. 당시 연구 metadata도 이를 “first later legal adjusted daily open”이라고 기록한다. 그러나 생성 당시 종목별 조정 가격 행의 hash와 date-level projection audit가 보존되지 않았다. 그러므로 당시 해당 다음 세션 행이 입력 frame에서 누락됐는지, 누락 없이도 저장일이 밀린 resolver 오류였는지는 11건 모두 확정할 수 없다. 원인을 `UNRESOLVED`로 둔다.

현재 계약인 `signal 다음 첫 exact KRX session open`을 바꿀 근거는 없다. 현행 가격 authority를 사용한 targeted replay에서는 11건 모두 expected date를 첫 종목 시가로 선택한다. 과거 공식 기록은 입력 authority provenance를 복구한 뒤에만 remediation을 결정해야 한다.

## 11건 개별 증거

KRX 시가/거래량/상장주식수는 `data/market/raw/krx_stocks/v01`의 날짜별 원시 KRX 스냅샷에서 확인했다. 조정 시가는 현재 `NAVER_DIRECT_DATE_RANGE_ADJUSTED_V1` authority의 `data/market/adjusted/stocks/{ticker}.parquet`에서 읽었다. 모든 signal 날짜는 해당 월의 마지막 KRX 세션이며 expected 날짜는 다음 KRX 세션이다.

| 유형 | 종목 | 신호일 | 다음 KRX 세션 | 조정 시가 | KRX 원시 시가 / 거래량 | 저장 체결일 / 조정 시가 | 원인 분류 | 조치 |
|---|---:|---|---|---:|---:|---|---|---|
| ENTRY | 018680 | 2016-02-29 | 2016-03-02 | 14,431 | 12,450 / 33,989 | 2016-03-03 / 15,764 | `UNRESOLVED` | 당시 종목 가격 frame 복구 또는 date-level provenance 확인 |
| ENTRY | 035200 | 2013-10-31 | 2013-11-01 | 1,854 | 2,925 / 25,004 | 2013-11-04 / 1,864 | `UNRESOLVED` | 동일 |
| ENTRY | 049950 | 2013-07-31 | 2013-08-01 | 7,878 | 9,020 / 20,908 | 2013-08-02 / 7,904 | `UNRESOLVED` | 동일 |
| ENTRY | 072020 | 2017-03-31 | 2017-04-03 | 15,063 | 18,600 / 89,651 | 2017-04-04 / 15,873 | `UNRESOLVED` | 동일 |
| ENTRY | 109820 | 2017-03-31 | 2017-04-03 | 2,510 | 3,765 / 31,695 | 2017-04-04 / 2,586 | `UNRESOLVED` | 동일 |
| ENTRY | 123330 | 2016-08-31 | 2016-09-01 | 20,070 | 21,200 / 65,649 | 2016-09-02 / 20,828 | `UNRESOLVED` | 동일 |
| EXIT | 001040 | 2017-05-31 | 2017-06-01 | 198,965 | 211,000 / 50,989 | 2017-06-05 / 202,266 | `UNRESOLVED` | 동일 |
| EXIT | 005030 | 2016-05-31 | 2016-06-01 | 1,639 | 1,815 / 102,239 | 2016-06-02 / 1,643 | `UNRESOLVED` | 동일 |
| EXIT | 014200 | 2022-03-31 | 2022-04-01 | 21,072 | 3,510 / 2,845,048 | 2022-04-04 / 27,378 | `UNRESOLVED` | 동일 |
| EXIT | 065440 | 2013-04-30 | 2013-05-02 | 1,561 | 2,055 / 436,860 | 2013-05-03 / 1,705 | `UNRESOLVED` | 동일 |
| EXIT | 078160 | 2018-11-30 | 2018-12-03 | 36,909 | 83,200 / 71,631 | 2018-12-04 / 37,839 | `UNRESOLVED` | 동일 |

expected일과 저장일 양쪽에서 모두 거래량이 0보다 컸다. 각 쌍의 KRX `listed_shares` 값도 같았다. 조사한 두 날짜 사이에 거래정지/비거래 또는 주식 수가 바뀐 흔적은 없다. 현재 exact-next open resolver semantics를 이 데이터에 적용한 targeted replay는 11/11건에서 expected 날짜를 반환한다.

### 실행 resolver 및 미확정 원인

- historical code: `39af0240c` 당시 `scripts/run_pattern_b_pure_simple_backtest_v01.py`의 `_next_bar_after()`가 `next_observed_open_date(daily.index, signal_date)`를 호출한다. 이는 전역 KRX calendar의 바로 다음 날을 강제하지 않고, 해당 ticker daily frame에 남아 있는 다음 관측 row를 선택한다.
- historical metadata: `artifacts/patterns/pattern_b/pattern_a_entry_filter_simple_v01/metadata.json`의 trade rule은 entry/exit를 “first later legal adjusted daily open”으로 기록한다. 저장 체결가도 각 저장일의 adjusted open과 일치한다.
- provenance gap: 같은 metadata는 신호·PIT·calendar·원천 ledger hash와 price-load 집계 건수를 기록하지만, 각 ticker의 adjusted-price frame hash나 11개 날짜의 row projection을 저장하지 않았다.
- 따라서 확인된 것은 **legacy next-observed-ticker-bar 경로와 현재 exact-next 계약의 의미 차이**다. 개별 케이스에서 그 경로가 expected 날짜를 건너뛴 직접 원인이 과거 조정 데이터의 누락인지 resolver 구현 오류인지는 입증되지 않았다. 억지로 `HISTORICAL_EXECUTION_RESOLVER_BUG`, `RAW_DATA_GAP_OR_STALE_AUTHORITY` 또는 `TICKER_NOT_EXECUTABLE_ON_NEXT_KRX_SESSION`으로 분류하지 않았다.
- 조사 구간에는 `CORPORATE_ACTION_HANDLING`으로 볼 상장주식수 변화가 없었다.

## 5-window 영향 범위

공식 V01 5-window test trade ledger의 교차 대조 결과:

| Window | 거래 행 수 | 지연 체결 노출 |
|---|---:|---:|
| P1 | 582 | ENTRY 3, EXIT 4 |
| P2-1 | 246 | EXIT 1 (014200) |
| P2-2 | 353 | EXIT 1 (014200, P1/P2-1과 같은 trade) |
| P3-1 | 203 | 0 |
| P3-2 | 310 | 0 |

- 공식 5-window 안의 unique discrepancy trade: **7건** (P1 7건)
- window별 노출 합계: **9건** (014200이 P1, P2-1, P2-2에 중복)
- 11개 history discrepancy 중 5-window에 없는 거래: 4건 (035200, 049950, 123330, 065440)
- 성과 수치는 바뀔 수 있다. 예를 들어 014200의 현행 조정 기준 expected exit 시가는 21,072원이고 저장 exit 시가는 27,378원이다. 다만 이는 현행 가격 authority 기준의 sensitivity일 뿐, 과거 입력을 복구하지 않은 상태에서 공식 수익률 delta로 확정하지 않았다. 전체 5-window 재실행은 하지 않았다.

## 007110 가격 scale 별도 감사

| 비교 | entry (2018-11-01) | exit (2019-01-02) | 수익률 |
|---|---:|---:|---:|
| 기존 V04 control ledger | 1,595원 | 2,380원 | 49.2163009404% |
| 재생성 Production history / 현행 Naver 조정 가격 | 7,975원 | 11,900원 | 49.2163009404% |
| 배율 | 5.0x | 5.0x | 동일 |

현행 sidecar `data/market/adjusted/stocks/007110.meta.json`은 `NAVER_DIRECT_DATE_RANGE_ADJUSTED_V1`, `source_native_adjusted=true`이며 2026-10-03에 생성됐다. 로컬 pre-cutover 백업 sidecar는 `PYKRX_ADJUSTED_PRICE`이고, 그 파일의 2018년/2019년 open도 기존 V04 ledger 및 KRX 원시 시가와 각각 1,595원/2,380원으로 일치한다. 다만 V04 metadata가 price input hash를 기록하지 않아 ledger 자체가 그 백업 파일을 직접 사용했는지는 provenance로 확정되지 않는다.

가격 scale 변경의 원인은 거래기간 후인 **2026-10-01의 5:1 주식병합**이다. KRX 원시 스냅샷의 listed shares가 2026-09-30의 77,456,610주에서 2026-10-01의 15,491,322주로 정확히 1/5이 됐다. KRX에도 일신석재의 주식병합 결정 공시가 있다: [KRX KIND 공시](https://kind.krx.co.kr/common/disclsviewer.do?acptno=20260713000776&docno=&method=search&viewerhost=). Naver의 현행 조정 시계열은 병합 후 주식 단위로 과거 가격을 소급 조정해 2018/2019 가격이 정확히 5배가 됐다.

영향:

- trade return 통계: entry와 exit에 같은 5배가 적용되어 변하지 않음.
- B Select Production status: 007110 trade는 이미 `REALIZED`이고 status history에는 주식 수나 현금 필드가 없다. 현행 history만으로 현금/보유 수량 변화를 만들지 않는다.
- 수량 기반 외부 계산: 같은 원화 배정액을 가격으로 나누면 표시 share unit 수는 대략 1/5이 되지만 목표 notional은 동일하며, 실제 계좌 수량은 이 monitor record가 관리하지 않는다.
- 웹 리포트 UI: 거래 이력 표는 `entry_open`/`exit_price`를 그대로 표시하므로 과거 nominal 가격 1,595/2,380원이 아니라 현행 adjusted basis 7,975/11,900원을 표시한다. 49.2163% 수익률은 동일하다.

## 최종 판정과 다음 조치

- confirmed resolver bug: 0
- 문서로 확인된 legacy next-observed-ticker-bar 의미와 현재 exact-next 계약의 차이: 11
- next-session 비거래/정지: 0
- confirmed raw-data gap/stale authority: 0 (과거 price frame provenance가 없어 확정 불가)
- corporate-action 원인(11건 구간): 0
- unresolved: 11
- 현행 `next exact KRX session open` 계약: **유지 가능**. 11건 모두 expected 세션의 실제 KRX 거래가 확인되고, 계약 변경 근거는 없다.
- 역사 authority remediation: **보류**. 원시 가격 입력을 소급 복구하거나 비슷한 시기의 authority snapshot을 식별한 뒤 7개 공식 5-window trade만 targeted replay로 확정해야 한다. 그 전까지 공식 산출물과 Production 동작은 수정하지 않는다.

검증: 현행 KRX raw/adjusted rows와 calendar를 읽는 11건 targeted check 11/11 통과. 전체 backtest와 production code 변경은 수행하지 않았다.
