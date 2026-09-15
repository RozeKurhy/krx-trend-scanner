# FastCore 현실적 백테스트 공통 실행조건 V01

> 상태: `검토 대기`
>
> 이 문서는 FastCore 현실적 백테스트와 향후 Julia 비교에서 재사용할 수 있는
> 전략 중립 공통 실행환경을 정리한다. 전략 규칙, Fundamentals Filter 또는
> 특정 후보 전략의 성과를 정의하는 문서가 아니다.
>
> 거래비용·세금·슬리피지·포트폴리오 자금 운용 등 승인된 현실적 계약이
> 아직 모두 확정되지 않았으므로, 이 문서 작성 단계에서는 백테스트·결과
> 계산·외부 데이터 수집·코드 및 artifact 변경을 수행하지 않는다.

## 1. 권위와 적용 범위

FastCore 현실적 백테스트의 전략 기준은 현재 동결된
`PATTERN_A_FAST_FINAL_STRATEGY_V02`를 사용한다. 이 문서는 그 전략의
진입·보유·청산·재진입 규칙을 바꾸지 않고, 신호를 실제 포트폴리오 실행과
평가에 연결하는 공통 조건만 다룬다.

현재 작업 순서는 다음과 같다.

1. 전략 중립 현실적 공통 실행조건 확정
2. Fundamentals Filter 조건 별도 확정
3. FastCore realistic backtest 및 baseline 비교
4. Julia realistic backtest

Fundamentals 조건은 이 문서의 범위가 아니다. 다음 항목은 FastCore 또는
Julia에 이 문서만으로 자동 적용하지 않는다.

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
- 신규 진입은 신호 주간 다음 `NEXT_LOCAL_TRADING_DAY_OPEN`에서 체결한다.
- Pre-PROGRESSED Loss Guard는 체결 후 완료된 일봉 종가 기준으로 발생하며,
  신호가 확정된 다음 local trading day 시가에서 청산한다.
- PROGRESSED Exit 3·Exit 4는 해당 월봉 청산 신호 이후 첫 local trading day
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

현실적 백테스트에서는 아래 항목의 적용 계약을 최종 고정해야 한다. 현재
레포에서 이 항목들을 FastCore realistic 공통조건으로 승인한 계약은 확인되지
않았다.

| 항목 | 현재 상태 |
|---|---|
| 매수 수수료 | `검토 필요` |
| 매도 수수료 | `검토 필요` |
| 거래일별 역사적 매도세금 스케줄 및 시장·시점별 적용 방식 | `검토 필요` |
| 매수 슬리피지 | `검토 필요` |
| 매도 슬리피지 | `검토 필요` |

기존 `GROSS / NO_COST_MODEL` 및 비용·세금·슬리피지 0 조건은 과거 연구
계약일 뿐 현실적 authority로 승격하지 않는다. 숫자가 확정되기 전에는 이
문서의 상태를 `확정`으로 바꾸지 않으며, 매도세금은 백테스트 전체 기간에
단일 고정 숫자를 적용하지 않는다. 실제 거래 체결일의 역사적 법정 세율
스케줄과 시장·적용 시점 차이를 execution contract에서 조회·적용한다.
세율 숫자와 세부 세법 항목은 이번 문서에서 조사하거나 확정하지 않는다.

비용이 확정되면 체결가와 현금흐름은 다음 구조로 사전 기록한다.

- 매수 체결가: 전략 신호가 정한 기준 시가에 매수 슬리피지를 반영
- 매수 현금 유출: 체결 notional과 매수 수수료 반영
- 매도 체결가: 전략 신호가 정한 기준 시가에 매도 슬리피지를 반영
- 매도 현금 유입: 체결 notional에서 매도 수수료와 거래일에 해당하는
  확정된 역사적 매도세금 스케줄에 따른 세금을 차감

위 구조에 적용할 숫자는 별도 승인 전까지 비워 둔다.

## 6. 포트폴리오 자금 운용

현실적 공통조건에 필요한 항목과 현재 상태는 다음과 같다.

| 항목 | 현재 상태 |
|---|---|
| 초기 자본 | `검토 필요` |
| 종목별 position sizing | `검토 필요` |
| 종목별 최대 투자금·비중 | `검토 필요` |
| 최대 동시 보유 종목 수 | `검토 필요` |
| 현금 부족 시 신규 신호 처리 | `검토 필요` |
| 청산 자금 재사용 시점 | `검토 필요` |
| 서로 다른 종목의 같은 시가 이벤트 순서 | `검토 필요` |

V2에서 고정된 실행 경계인 동일 종목 중복 보유 금지, 피라미딩 금지, 동일
시가 청산·재진입 금지는 유지한다. 그 외의 초기자본·비중·동시보유·현금
배분 숫자는 임의로 정하지 않는다.

과거 `200,000,000 KRW` 초기자본과 종목당 `5,000,000 KRW` position cap은
`scripts/run_fastcore_vs_julia_portfolio_v01.py` 등 과거 연구의 구현 참고
자료일 뿐이다. 이벤트 처리·현금 관리·equity curve·turnover 구조를 참고할
수는 있지만, 공식 realistic 조건으로 자동 승계하지 않는다.

## 7. 비용 적용 체결가와 이벤트 원장

실행 시 각 주문은 최소한 다음 원장을 남긴다.

- signal date와 execution date
- 전략 기준 시가와 비용·슬리피지 반영 체결가
- 주문 수량과 notional
- 수수료·세금·슬리피지 금액
- 체결 전후 현금과 보유 수량
- 포지션 식별자, 진입·청산 사유, open-at-cutoff 여부

이 원장은 비용이 확정된 뒤 execution contract와 함께 생성한다. 현재 작업에서
새 runner나 portfolio engine을 만들거나 수정하지 않는다.

## 8. 포트폴리오 평가와 집계

다음 지표의 의미론을 사용하되, 초기자본·비용·sizing 및 최종 지원 종료일이
확정되기 전에는 값을 산출하지 않는다.

- **일별 equity**: 현금과 각 미청산 포지션의 기준일 종가 평가액 합계
- **총수익률**: 최종 equity / 초기 자본 - 1
- **CAGR**: 시작일과 최종 valuation일 사이의 calendar-day 기준 연율화
- **MDD**: 일별 equity의 직전 고점 대비 drawdown 최저값
- **MDD 기간**: 고점 일자부터 해당 trough까지의 기간과 회복 여부
- **exposure**: 일별 invested market value / 일별 equity; 평균·최대값을
  구분하여 보고
- **turnover**: numerator, 매수·매도 notional 포함 범위, normalization
  기준, 비용 포함 여부 및 보고 단위를 FastCore realistic 실행계약에서
  사전 확정한 뒤 산출한다. 현재 공통조건 문서에서는 특정 공식을 공식
  기준으로 고정하지 않는다.
- **거래 수**: 실행된 독립 진입과 청산 원장을 기준으로 집계
- **보유기간**: 진입 체결일부터 청산 체결일까지; open-at-cutoff는 censored로
  별도 집계
- **승률**: 비용 반영 후 실현 terminal return이 양수인 종료 거래 비율
- **payoff ratio**: 비용 반영 후 평균 이익 거래 / 평균 손실 거래 절대값
- **open-at-cutoff**: 최종 valuation일에 미청산인 포지션 수·금액·손익을
  종료 거래와 분리

미청산 보유분은 동결된 평가일의 authority 종가로 평가한다. 해당 가격이
없으면 nearest-date로 대체하지 않고 실행계약의 fail-closed 또는 검토 상태를
따른다.

## 9. Benchmark

현재 레포에는 시장·섹터 report에서 사용하는 benchmark metadata와 KRX 공식
지수 원천이 있으나, FastCore realistic portfolio의 전략 중립 benchmark
비교 계약은 확인되지 않았다. 따라서 KOSPI·KOSDAQ·임의 ETF 등을 이 문서에서
공식 benchmark로 확정하지 않는다.

- benchmark 비교: `검토 필요`
- benchmark 데이터 신규 수집: 이번 작업에서 수행하지 않음
- benchmark가 확정되면 동일 평가기간·PIT·valuation 의미론을 적용하고,
  전략 규칙과 독립된 비교로만 사용

## 10. Market Regime

V2의 `PERMITTED_REGIME`는 전략 내부의 월봉 허용 상태이며, 포트폴리오
성과를 나누는 일반 market regime 분류 authority와 동일하지 않다. 레포의
Fear Index 및 regime 연구는 연구 자료로 확인되었으나, FastCore realistic
공통 실행조건의 승인된 market regime 계약으로 사용하지 않는다.

- 공통 market regime 분류: `기존 공식 기준 없음 / 별도 검토 필요`
- 새로운 regime 모델·threshold·진입 제한: 이번 작업에서 만들지 않음
- 향후 기준이 확정되면 전략 규칙과 섞지 않고 결과 분할·benchmark 분석에만
  사용

## 11. Parameter Robustness

현재 V2 전략은 동결되어 있으며 `-15% Loss Guard`, Exit 4 등 전략 threshold를
결과에 맞춰 sweep하지 않는다. 기존 V2 동결 문서의 zero-sweep 원칙을 따른다.

전략 파라미터를 바꾸지 않는다는 점은 확정되어 있지만, FastCore realistic
결과에 적용할 공통 robustness 보고 방식은 별도 승인된 계약이 확인되지 않았다.
따라서 이번 작업에서 대규모 sweep·새 regime model·결과 기반 threshold 조정을
설계하지 않는다. 전략별 검증 계획에서 필요한 robustness 범위와 보고 형식을
별도로 정한다.

## 12. Julia와 공유할 전략 중립 공통조건

FastCore realistic 조건이 확정되면 Julia에는 아래 전략 중립 실행환경만
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

## 13. 미확정 항목

다음 항목이 남아 있으므로 문서 상태는 `검토 대기`이며, FastCore realistic
백테스트를 실행하지 않는다.

1. 매수·매도 수수료, 거래일별 역사적 매도세금 스케줄 및 시장·시점별 적용
   방식, 매수·매도 슬리피지의 승인 계약
2. 초기 자본, position sizing, 종목별 cap·비중, 최대 동시보유 및 현금 부족
   처리
3. 청산 자금 재사용과 서로 다른 종목의 같은 시가 이벤트 순서
4. 최종 valuation 가격 결측·상장폐지·거래정지 포지션 처리
5. turnover numerator, 매수·매도 notional 포함 범위,
   turnover normalization 기준(초기자본·평균 equity 등), 비용 포함 여부 및
   보고 단위
6. 전략 중립 benchmark와 동일기간 비교 방식
7. 공통 market regime 분류 기준 및 결과 분할 방식
8. strategy-specific parameter robustness의 범위와 보고 형식

이미 고정된 항목은 Repository V2/PIT authority, Population/PIT 분리,
lookahead 금지·fail-closed 원칙, V2 신호·체결 및 동일 종목 비중복 경계다.
이 문서는 위 미확정 항목이 결정되기 전까지 `확정` 또는 실행 허가 문서로
사용하지 않는다.

## 14. 실행 금지와 제출 경계

이번 문서 작성에서는 FastCore·Julia 백테스트, 샘플 실행, 성과 계산, pytest,
외부 API·네트워크 데이터 수집, runner·portfolio engine·PIT loader 수정 및
artifact 생성을 수행하지 않는다. 조건이 모두 확정되고 별도 리뷰를 통과한
뒤에만 실행 계약과 결과 artifact를 만든다.
