# FastCore 현실적 백테스트 공통 실행조건 V01

> 상태: `확정`
>
> 이 문서는 완료된 FastCore 현실적 백테스트와 V2 ↔ Julia 공식 비교에 사용한
> 전략 중립 공통 실행조건의 역사 기록이다. 전략 규칙, Fundamentals Filter 또는
> 특정 후보 전략의 성과를 새로 정의하는 문서가 아니다.
>
> 공통조건은 `확정`됐으며, 아래의 당시 작업 순서와 실행 경계는 현재 대기
> 상태나 새로운 실행 지시를 의미하지 않는다. 거래비용·세금·슬리피지·포트폴리오
> 자금 운용 등 승인 조건과 실행 의미론은 완료된 비교의 공통 기준으로 보존한다.

## 1. 권위와 적용 범위

FastCore 현실적 백테스트의 전략 기준은 현재 동결된
`PATTERN_A_FAST_FINAL_STRATEGY_V02`를 사용한다. 이 문서는 그 전략의
진입·보유·청산·재진입 규칙을 바꾸지 않고, 신호를 실제 포트폴리오 실행과
평가에 연결하는 공통 조건만 다룬다.

문서 작성 당시 작업 순서는 다음과 같이 기록했다.

1. 전략 중립 현실적 공통 실행조건 확정 — **완료**
2. V2 ↔ Julia 공식 검증 Stage 4 — **완료 / 동결**
3. 당시 Stage 5 실행 전 runner·execution contract 연결
4. 당시 V2 ↔ Julia 공식 백테스트: 동일 진입·순차·현실적 2억 포트폴리오
5. 당시 강건성 검증 및 최종 전략 검토

Fundamentals는 이번 V2 ↔ Julia 공식 검증의 비교 변수와 진입 필터에서
제외한다. OpenDART Fundamentals V1과 production Fundamentals Filter 자체의
상태는 변경하지 않는다. 다음 항목은 FastCore 또는 Julia에 이 문서만으로
자동 적용하지 않는다.

- Fundamentals Filter ON/OFF
- fundamentals cutoff·threshold·score
- 매출·이익·성장률 조건
- fundamentals 기반 종목 제외
- FastCore 전용 ranking·종목 선택·추가 필터
- 새로운 진입·보유·청산·재진입 조건 또는 전략 threshold

## 2. 데이터 기준

### 2.1 가격·시장 데이터 authority

공식 production 데이터 기준은 `MarketDataRepositoryV2`이다. 이 문서에서
새 데이터 경로나 fallback을 만들지 않는다.

| 데이터 | 기준 authority |
|---|---|
| adjusted OHLC | `AdjustedPriceStore` / Naver direct adjusted V02 |
| raw volume·trading value·market cap·listed shares | `KrxRawStockStore` / KRX Open API stock daily |
| Repository 조합과 계약 | `docs/architecture/market_data_repository_v02.md` |
| consumer wiring 확인 | `artifacts/data/end_to_end_data_parity/v01/consumer_migration_finalization/v01/production_wiring_manifest.json` |

가격·거래량·거래대금·시가총액 자료는 동일한 원천과 날짜 의미론을 사용한다.
조정주가와 raw 보조자료를 한 전략만 다른 경로로 바꾸지 않는다.

### 2.2 역사적 PIT와 lookahead 금지

역사적 모집단은 다음 두 계층을 분리한다.

- `Population Universe`: 연구 구간에서 한 번이라도 `COMMON`이었던 모든
  종목 식별 단위
- `Point-in-Time Common Denominator`: 정확한 각 거래일에 실제로 `COMMON`이었던
  종목 식별 단위

권위 artifact와 loader는 다음을 사용한다.

- Population: `artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/v01_spac_corrected_effective_authority/effective_historical_common_population.json`
- PIT denominator: `artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/v01_spac_corrected_effective_authority/effective_pit_common_denominator.json`
- loader: `src/trend_scanner/universe/survivorship_safe_denominator_freeze.py`
- 계약: `docs/architecture/survivorship_safe_denominator_freeze_v01.md`

현재 시점 종목 목록을 역사 전체에 broadcast하지 않는다. 정확한 날짜의 PIT
COMMON denominator를 사용하며, 동결 calendar 밖 날짜·비영업일·누락 interval은
nearest-date fallback 없이 `fail-closed`한다. 결측 OHLC·시장 데이터·metadata와
PIT 시가총액도 보간·forward-fill·0-fill 없이 unavailable 또는 `fail-closed`로
처리한다.

주봉·월봉은 완료된 기간만 사용하고, 신호 시점 이후의 자료를 신호·투자적합성·
전략 상태에 사용하지 않는다. duplicate row, future row, 날짜 집합 불일치 및
authority 무결성 실패는 실행 중단 또는 명시적 격리 사유로 기록한다.

ETF·ETN·SPAC·REIT·우선주·외국주권·예탁증권 및 분류 불능 유형은 개별 보통주
FastCore 모집단에 자동 포함하지 않는다. 자산 유형은 ticker 모양이나 이름
substring이 아니라 KRX 공식 instrument metadata의 `AssetType` 분류를 사용한다.

## 3. 전략 규칙 경계

기준 전략과 canonical 규칙 문서는 다음과 같다.

- 전략 ID: `PATTERN_A_FAST_FINAL_STRATEGY_V02`
- canonical: `docs/patterns/pattern_a_fast/strategy/version_02/README.md`

다음 규칙은 이 문서에서 변경하지 않는다.

- 진입 허용 Stage: `TRANSITION`, `EARLY_TREND`
- FAST 진입: `TRIGGER` 및 `READY`
- 월봉 허용 상태: `PERMITTED_REGIME`
- 일봉 위험 상태: `NORMAL`, `ELEVATED`; `EXTREME` 차단
- FAST 점수 상태: `READY`, `PARTIAL`
- Pre-PROGRESSED `Loss Guard`의 기존 `-15%` 규칙
- PROGRESSED의 Exit 3 및 Exit 4
- 독립 재진입 허용, 피라미딩 금지, 동일 종목 중복 보유 금지
- 재진입 시 `entry_open`, Loss Guard, lifecycle, Exit 4 HWM의 완전 리셋

현실적 실행조건을 이유로 전략 규칙을 수정하거나 새로운 필터·국면 제한·
threshold를 추가하지 않는다.

## 4. 신호와 체결 시점

현재 V2 canonical 의미론을 공통 실행의 기준으로 사용한다.

- 신호는 완료된 주봉·월봉·일봉 정보만으로 형성한다.
- 신규 진입은 완료된 주간 신호가 확정된 뒤 도래하는 새로운 주의 첫 로컬 거래일 시가인 `NEXT_LOCAL_TRADING_DAY_OPEN`에서 체결한다.
- Pre-PROGRESSED Loss Guard는 완료된 일봉 종가에서 조건을 확인한 뒤 다음
  로컬 거래일 시가에서 청산한다.
- PROGRESSED Exit 3·Exit 4는 기존 월봉 청산 신호 이후 다음 달 첫 로컬 거래일
  시가에서 청산한다.
- 동일 시가에서 청산과 재진입을 동시에 수행하지 않는다.
- 겹치는 포지션과 피라미딩은 수행하지 않는다.
- 평가 cutoff 이후 새 신호·새 진입을 만들지 않는다.
- cutoff 시점 미청산 포지션은 `OPEN_AT_CUTOFF`로 별도 보고하며, 전략의
  청산 신호로 임의 청산하지 않는다. 최종 평가가격과 지원 종료일은 각
  전략의 동결된 평가계약에서 정하고, 이 문서가 새 날짜를 만들지 않는다.

체결가·평가가격을 확보할 수 없는 경우 nearest-date 또는 종가 fallback을
조용히 사용하지 않는다. 해당 결측 처리와 최종 valuation 예외는 실행계약에
기록하고 `fail-closed` 또는 명시적 검토 상태로 처리한다.

## 5. 거래비용·세금·슬리피지

현실적 백테스트에서는 아래 항목의 적용 계약을 모든 비교 전략에 동일하게
적용한다. V2와 Julia 비교에서 비용·세금·슬리피지 조건을 다르게 두지 않는다.

| 항목 | 확정 상태 |
|---|---|
| 매수 수수료 | 매수 체결금액의 `0.015%` |
| 매도 수수료 | 매도 체결금액의 `0.015%` |
| 거래일별 역사적 매도세금 스케줄 및 시장·시점별 적용 방식 | `확인됨`; 실제 매도 체결일·시장별 법정 세율을 매도에만 적용 |
| 매수 슬리피지 | 기준 체결 시가에 `0.10%` 가산 |
| 매도 슬리피지 | 기준 체결 시가에 `0.10%` 차감 |

기존 `GROSS / NO_COST_MODEL` 및 비용·세금·슬리피지 0 조건은 과거 연구
계약일 뿐 현실적 authority가 아니다. 매도세금은 백테스트 전체 기간에 단일
고정 숫자를 적용하지 않고, 실제 거래 체결일의 역사적 법정 세율 스케줄과
시장·적용 시점 차이를 execution contract에서 조회·적용한다.

비용이 확정되면 체결가와 현금흐름은 다음 구조로 사전 기록한다.

- 매수 체결가: 전략 신호가 정한 기준 시가에 매수 슬리피지를 반영
- 매수 현금 유출: 체결 notional과 매수 수수료 반영
- 매도 체결가: 전략 신호가 정한 기준 시가에 매도 슬리피지를 반영
- 매도 현금 유입: 체결 notional에서 매도 수수료와 거래일에 해당하는
  확정된 역사적 매도세금 스케줄에 따른 세금을 차감

매수·매도 수수료와 슬리피지는 V2·Julia 등 비교 전략에 동일하게 적용한다.

## 6. 포트폴리오 자금 운용

현실적 공통조건에 필요한 항목과 확정 상태는 다음과 같다.

| 항목 | 확정 상태 |
|---|---|
| 초기 자본 | `200,000,000 KRW` |
| 종목별 position sizing | 종목당 총 매수 현금예산 `q = 5,000,000 KRW` |
| 종목별 최대 투자금·비중 | `5,000,000 KRW`, 초기자본의 `2.5%` |
| 최대 동시 보유 종목 수 | `N = 40` |
| 현금 부족 시 신규 신호 처리 | 부분 체결 없이 해당 신규 진입 건너뜀 |
| 청산 자금 재사용 시점 | 매도 체결 다음 평가 가능한 로컬 거래일 시가부터 |
| 서로 다른 종목의 같은 시가 이벤트 순서 | 신호 확정일 기준 PIT 시가총액 내림차순, 동률 종목코드 오름차순 |

V2에서 고정된 실행 경계인 동일 종목 중복 보유 금지, 피라미딩 금지, 동일
시가 청산·재진입 금지는 유지한다. 그 외의 초기자본·비중·동시보유·현금
배분은 아래 승인값을 사용한다.

`q`는 종목당 총 매수 현금예산이다. 즉 주식 매수 거래금액과 매수 수수료의
합계가 `q` 이하가 되어야 한다. 매수 슬리피지를 반영한 체결가와 매수
수수료를 함께 고려하여 `q` 이하의 최대 정수 주식 수량을 산출한다. 별도
예산 버퍼나 복잡한 추가 산식은 만들지 않는다.

초기자본과 `q`, `N`은 `q × N = C0` 구조를 유지한다. 현금 부족 시 부분
체결은 하지 않고 `SKIPPED_CASH_UNAVAILABLE` 또는
`SKIPPED_POSITION_LIMIT`으로 기록한다. 같은 시가의 매도 이벤트를 먼저
처리하되 그 매도대금은 같은 시가 신규 진입에 재사용하지 않는다.

같은 시가 신규 신호가 가용 현금 또는 빈 슬롯을 초과하면 신호 확정일 기준
PIT 시가총액 내림차순으로 우선 진입하고, 시가총액 동률은 종목코드
오름차순으로 처리한다. 해당 PIT 시가총액이 공식 기준을 충족하지 못하면
현재·미래 시가총액, nearest-date fallback, 임의 proxy를 사용하지 않고
기존 결측·실패 의미론을 따른다. 이 순서는 전략 점수·적격성 필터·펀더멘털
순위가 아닌 전략 중립 포트폴리오 배분 규칙이다.

## 7. 비용 적용 체결가와 이벤트 원장

실행 시 각 주문은 최소한 다음 원장을 남긴다.

- signal date와 execution date
- 전략 기준 시가와 비용·슬리피지 반영 체결가
- 주문 수량과 notional
- 수수료·세금·슬리피지 금액
- 체결 전후 현금과 보유 수량
- 포지션 식별자, 진입·청산 사유, open-at-cutoff 여부

이 원장은 비용이 확정된 뒤 execution contract와 함께 생성한다. 별도 전략
규칙을 추가하지 않고, 아래의 공통 terminal valuation 의미론을 적용한다.

## 8. 포트폴리오 평가와 집계

다음 지표의 의미론은 완료된 현실적 백테스트에 사용한 기준이다. 이 문서는
수치를 산출하는 문서가 아니며, 당시 초기자본·비용·sizing 및 최종 지원 종료일이
확정되기 전에는 값을 산출하지 않는다는 실행 경계를 보존한다.

- **일별 equity**: 현금과 각 미청산 포지션의 기준일 종가 평가액 합계
- **총수익률**: 최종 equity / 초기 자본 - 1
- **CAGR**: 시작일과 최종 valuation일 사이의 calendar-day 기준 연율화
- **MDD**: 일별 equity의 직전 고점 대비 drawdown 최저값
- **MDD 기간**: 고점 일자부터 해당 trough까지의 기간과 회복 여부
- **exposure**: 일별 invested market value / 일별 equity; 평균·최대값을
  구분하여 보고
- **turnover**: `T = (Σ 매수 거래금액 + Σ 매도 거래금액) / C0`. 거래금액은
  비용과 세금 차감 전 명목금액이며, 수수료·거래세·슬리피지는 별도 비용으로
  보고한다. 전체기간 배수 `T`와 백분율 `100T%`를 보고하고 연환산하지 않는다.
- **거래 수**: 실행된 독립 진입과 청산 원장을 기준으로 집계
- **보유기간**: 진입 체결일부터 청산 체결일까지; open-at-cutoff는 censored로
  별도 집계
- **승률**: 비용 반영 후 실현 terminal return이 양수인 종료 거래 비율
- **payoff ratio**: 비용 반영 후 평균 이익 거래 / 평균 손실 거래 절대값
- **open-at-cutoff**: 최종 valuation일에 미청산인 포지션 수·금액·손익을
  종료 거래와 분리
- **비용 총액**: 수수료·거래세·슬리피지 영향을 각각 분리하고 합계를 보고

미청산 보유분은 동결된 평가일의 authority 종가로 평가한다. 해당 가격이
없으면 nearest-date로 대체하지 않고 실행계약의 fail-closed 또는 검토 상태를
따른다.

identity lifecycle이 global final valuation 이전에 종료된
`OPEN_AT_CUTOFF` 포지션은 identity의 정확한 `cutoff_date` 종가에서 terminal
valuation한다. 이는 전략 청산이나 매도 체결이 아니므로 매도 수수료·세금·
슬리피지, realized return 및 turnover에 포함하지 않는다. 평가금액은 현금으로
전환하거나 재투자하지 않고 `locked terminal value`로 global final까지
carry하며, equity·invested market value·exposure·cash conservation에
포함한다. 실제 처분이 없으므로 position slot을 유지하되, 이후 같은 short
ticker의 새 identity 진입은 허용할 수 있다. 정확한 cutoff 종가가 없거나
Sequential의 `cutoff_valuation_price`와 일치하지 않으면 nearest-date나
post-lifecycle 가격을 사용하지 않고 `UNRESOLVED`·fail-closed로 처리한다.

## 9. Benchmark

현재 레포의 KRX 공식 지수 원천을 사용하여 다음 시장별 benchmark를 확정한다.

- KOSPI COMMON: KOSPI 지수 `1001`
- KOSDAQ COMMON: KOSDAQ 지수 `2001`
- 전략과 동일한 평가기간·PIT·valuation 의미론을 적용한다.
- 혼합 포트폴리오에 임의의 단일 합성 비교지수를 만들지 않고 KOSPI·KOSDAQ
  결과를 시장별로 분리 비교한다.
- benchmark는 전략 규칙과 독립된 비교로만 사용하며, 이번 문서 확정을 위해
  신규 benchmark 데이터를 수집하지 않는다.

## 10. Market Regime

V2의 `PERMITTED_REGIME`는 전략 내부의 월봉 허용 상태이며, 포트폴리오
성과를 나누는 일반 market regime 분류 authority와 동일하지 않다. 레포의
Fear Index 및 regime 연구는 연구 자료로 확인되었으나, FastCore realistic
공통 실행조건의 승인된 market regime 계약으로 사용하지 않는다.

- 공통 market regime 진입 게이트: 사용하지 않음
- V2의 `PERMITTED_REGIME`: V2 전략 내부 규칙으로만 유지
- 새로운 regime 모델·threshold·진입 제한: 만들지 않음

## 11. Parameter Robustness

현재 V2 전략은 동결되어 있으며 `-15% Loss Guard`, Exit 4 등 전략 threshold를
결과에 맞춰 sweep하지 않는다. 대규모 sweep, 격자 탐색, 결과 기반 threshold
조정은 수행하지 않는다.

승인된 최소 robustness 보고 범위는 다음과 같다.

- 연도별
- KOSPI / KOSDAQ
- 종목 집중도: 동일 종목의 모든 독립 거래를 합산한 누적 손익 기여 상위 10개
  종목의 전체 손익 기여도
- 대형 수익 거래 집중도: 개별 종료 거래 기준 수익 기여 상위 10개 거래의
  총이익 기여도
- 대형 손실 거래 집중도: 개별 종료 거래 기준 손실 기여가 가장 큰 10개
  거래의 총손실 기여도

각 구간에는 거래 횟수, 총수익률, CAGR, MDD, 평균·중앙 보유기간, 투자
노출도, 회전율, `OPEN_AT_CUTOFF`를 보고한다. `UNRESOLVED` 예외 수와 영향
금액도 함께 기록한다. 새 점수·임계값·필터·복잡한 집중도 지수는 만들지
않는다.

## 12. Julia와 공유할 전략 중립 공통조건

확정된 FastCore realistic 조건은 Julia에도 아래 전략 중립 실행환경으로
동일하게 연결한다.

공유 대상:

- 데이터·historical PIT·survivorship-safe Population/PIT authority
- 신호 이후 체결 시점과 평가 cutoff 의미론
- 거래비용·세금·슬리피지
- portfolio capital·sizing·동시보유·현금 처리
- 포트폴리오 valuation과 equity curve
- 총수익률·CAGR·MDD·exposure·turnover·거래 집계 의미론
- benchmark의 전략 중립적 비교 부분

공유하지 않는 대상:

- Fundamentals Filter 및 cutoff·threshold·score
- FastCore 전용 필터·ranking·종목 선택
- FastCore 전략의 진입·보유·청산·재진입 조건
- 전략 threshold와 새로운 market regime 진입 제한

Julia V00의 단일 전략 변경점은 계속 Pre-PROGRESSED Loss Guard ON/OFF
하나로 유지한다. 이 문서의 공통조건을 연결하는 과정에서 Julia의 전략
규칙을 추가하거나 FastCore 전용 조건을 가져오지 않는다.

## 13. 문서 상태와 실행 경계

이 문서의 전략 중립 현실적 공통 실행조건은 사용자 승인에 따라 모두
확정됐다. 문서 상태는 `확정`이며, V2 ↔ Julia 공식 검증 Stage 4도 별도 검증
계획 문서에서 **완료 / 동결**로 기록한다.

Fundamentals는 이번 공식 검증 범위에서 제외한다. Fundamentals production
기능을 폐기하거나 관련 문서를 변경하는 의미가 아니며, 이번 비교의
Fundamentals Filter·cutoff·threshold·score·종목 제외·ranking·entry gate에
사용하지 않는다는 뜻이다.

문서 작성 당시에는 Stage 5 실행 전 runner·execution contract 연결과 무결성
검토를 거친 뒤 실제 백테스트 결과 artifact를 별도 실행에서 생성하도록
기록했다. 현실적 백테스트와 V2 ↔ Julia 공식 비교는 완료됐으며, 이 문장은
현재 실행 대기나 추가 실행 지시를 의미하지 않는다.

## 14. 실행 금지와 제출 경계

문서 확정 당시에는 FastCore·Julia 백테스트, 샘플 실행, 성과 계산, pytest,
외부 API·네트워크 데이터 수집, runner·portfolio engine·PIT loader 수정 및
artifact 생성을 수행하지 않았다. 당시에는 Stage 5 실행 전 연결과 별도 리뷰를
통과한 뒤 실행 계약과 결과 artifact를 만들도록 기록했다. 현재 이 문서는
추가 실행을 지시하지 않는 역사 기록이다.
