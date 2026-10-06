# Naver 수정주가 과거 이력 변경 종결 기록 V01

작성일: 2026-10-06 KST

상태: `NAVER_ADJUSTED_HISTORICAL_REVISION_CLOSEOUT_V01_COMPLETE`

## 문서 역할

이 문서는 2026년 8~9월 Naver 수정주가 과거 이력 차이에 대한 감사 결과와 운영 결정을 종결 기록으로 보존한다. 이번 종결은 과거 원천 변경의 원인을 증명하거나 저장소·전략 계약을 바꾸는 의미가 아니다. 현재 운영 데이터 계약은 [KRX 운영 데이터 아키텍처](../krx_production_data_architecture_v01.md)와 [AdjustedPriceStore V02 계약](../adjusted_price_store_v02.md), 전략 계약은 [A FAST Core V2](../../patterns/pattern_a_fast/strategy/version_02/README.md)와 [B Select Core V2](../../patterns/pattern_b/strategy/PATTERN_B_SELECT_CORE_V02.md)를 따른다.

## 1. 사건과 선행 감사

2026-08-01~2026-09-30 Naver 수정주가 이력과 production `AdjustedPriceStore`를 비교한 결과는 다음과 같다.

- `NAVER_ADJUSTED_FETCH_PROVENANCE_V01_PASS`
- `NAVER_ADJUSTED_STORE_STABILITY_AUDIT_V01_CHECK_REQUIRED`
- `NAVER_ADJUSTED_STORE_COVERAGE_REVISION_SIGNATURE_V01_CHECK_REQUIRED`
- `A_FAST_B_SELECT_NAVER_REVISION_IMPACT_AUDIT_V01_CHECK_REQUIRED`

수정주가가 모두 일치하는 종목만 세는 안정성 비교에서 공통 행 98,886개 중 115개 행이 달랐고, 차이는 네 종목에 집중됐다. 115개 행 모두 현재 Naver 직접 재조회 결과와 OHLC 값이 일치했다. 이는 현재 관측의 재현성을 확인하지만 과거 값이 바뀐 원천이나 원인을 확정하지는 않는다.

## 2. Store coverage 결론

두 달의 Store missing은 8,030행이었다. 이 중 7,975행(99.32%)은 당시 운영 population 비대상으로 설명됐다. 현재 운영 authority 기준 `POPULATION_FAILURE_CANDIDATE`는 0행이다. 나머지 55행, 5개 종목은 authority가 닫히지 않아 미해결로 남긴다.

P2.2 identity extension은 당시 production 운영 경로에 소비되지 않았다. 그 extension의 promotion을 이번 closeout으로 승인하지 않는다. `900120`의 2026-08-25~2026-09-01 여섯 날짜는 P2.2 population이 향후 운영에 반영될 경우 다시 판정할 조건부 후보이며, 현재 production 누락 실패로 간주하지 않는다. P2.2와 기존 corrected census 간 `465320`, `471050`, `472220` identity authority 충돌 및 나머지 unresolved coverage는 별도 backlog로 유지한다.

## 3. Historical mismatch와 provenance 판정

| 종목 | 불일치 행 | 관측된 수치 형태 | 종결 판정 |
|---|---:|---|---|
| `207940` | 37 | 전체 OHLC 중앙 비율(Store/Naver) 1.0077577818. 연속된 mismatch 뒤 다음 KRX 세션에 exact parity 복귀 | historical adjustment revision과 구조적으로 일치. 원천 증거가 없어 revision 확정은 아님 |
| `475460` | 29 | 전체 OHLC 중앙 비율 2.9990142868. 연속된 mismatch 뒤 다음 KRX 세션에 exact parity 복귀 | historical adjustment revision과 구조적으로 일치. 원천 증거가 없어 revision 확정은 아님 |
| `042940` | 34 | 비율 범위 1.0387323944~1.0390830515. 9/17~9/18 불일치, 9/21 exact parity 복귀 | `NAVER_HISTORICAL_OHLC_REVISION_PROVENANCE_V01_UNRESOLVED` 유지 |
| `900120` | 15 | Store/Naver 비율 0.2로 일정. 마지막 mismatch 뒤 Store 행이 없어 exact return boundary 미확인 | fixed-factor 형태와 경계 미확정 모두 `UNRESOLVED` |

`SOURCE_REVISION_CONFIRMED` 또는 `STORE_BUG_CONFIRMED` 표현은 과거 source provenance 없이 사용하지 않는다. 특히 `042940`의 fixed-factor 유사 패턴과 `900120`의 0.2 비율은 원인 증거가 아니다. `207940`, `475460`도 수치 signature가 adjustment revision과 일치한다고만 기록한다. `900120`에서 확인된 KRX section 및 상장주식수 변경도 이번 자료만으로 특정 corporate action의 증거로 단정하지 않는다.

## 4. Causal strategy impact

실제 historical trade가 확인된 두 종목만 기존 전략 코드와 당시 authority로 replay했다. 기준일은 2026-10-02이며, 정확한 KRX calendar session과 당시 signal cutoff를 사용하고 대상 종목의 adjusted OHLC만 교체했다. 다른 종목·PIT identity·전략 parameter·부가 입력은 그대로 유지했다.

전략 impact replay에 사용한 최종 전체 구간 재조회 provenance는 다음과 같다. 저장 Store hash는 현재 production sidecar의 `content_sha256`이며, 조회 hash는 2026-10-06 Naver fetch의 raw payload와 parsed canonical OHLC hash다. 이 현재 조회 기록은 과거 원천 revision의 원인 증거로 해석하지 않는다.

| 종목 | Naver 구간 / 행 수 | fetch 시각 (UTC) | raw payload SHA-256 | parsed OHLC SHA-256 | Store `content_sha256` |
|---|---|---|---|---|---|
| `207940` | 2016-11-10~2026-10-02 / 2,426 | 2026-10-06T09:23:08.489099+00:00 | `f83174389b891f08ea0a35a9b4183c5543fb838f7592a0c92defe0b93ad86a40` | `94c3af30eeafdd109d812c66d38bab48edc7b37f061f882d710e41562cea477b` | `a1f5958ce17051d15040d1685e4d6bc288639b8ebe0c45a753adc154879a688f` |
| `042940` | 2010-01-04~2026-10-02 / 4,123 | 2026-10-06T09:26:59.179390+00:00 | `b732a636f58adfb8de15cecc245a1849d02b4201e1ae53cf63515c5ef6d258f0` | `010e493f743348c15b8cf4446af24c07e12209267594e496cbc20d51e3b40a46` | `238d0f1fca03108ffcbf81f7f4f5a74e5c5d6685376d293a0d225ab86d679f9e` |

Naver source authority ID was `NAVER_DIRECT_DATE_RANGE_ADJUSTED_V1`; provider version was `NaverDirectAdjustedPriceDataProvider_v02`.

| 종목 / 전략 / 거래 | 신호일 → 진입일 | 진입가 A → B | 청산 신호일 → 체결일 | 청산가 A → B | 수익률 A → B |
|---|---|---:|---|---:|---:|
| `207940` A FAST #1 | 2019-11-29 → 2019-12-02 | 573,079 → 568,667 | 2020-08-31 → 2020-09-01 | 1,127,251 → 1,118,573 | 96.700804% → 96.700881% |
| `207940` A FAST #2 | 2022-07-29 → 2022-08-01 | 1,261,285 → 1,251,576 | 2023-07-07 → 2023-07-10 | 1,058,184 → 1,050,038 | -16.102705% → -16.102738% |
| `207940` A FAST #3 | 2024-02-02 → 2024-02-05 | 1,252,454 → 1,242,812 | 미청산 | — | 2026-10-02 mark: 9.065882% → 9.912038% |
| `042940` B Select #1 | 2025-06-30 → 2025-07-01 | 11,660 → 11,225 | 미청산 | — | 2026-10-02 mark: -53.516295% → -51.714922% |

실현 수익률은 각 시나리오 진입·청산 체결가 비율이고, 미청산 수익률은 2026-10-02 종가 mark다. 네 거래 모두 replay에 성공했고 canonical 거래 identity가 일치했다. 진입 신호, 진입 적격성, 정확한 진입·청산 session, 거래 생성·소멸 및 청산 lifecycle 변경은 모두 0건이다.

연속값은 일부 달랐다. A FAST 세 건의 Pattern A 진입 점수는 달랐지만 stage와 eligibility는 같았다. 54개 월간 Pattern A 비교에서 stage 변경은 0건, score 변경은 1건이었다. B Select에서는 `range_36m`, `monthly_ma24_distance`, `range_52w`가 진입 이후 309개 관측일 모두 달랐지만 Pattern B discrete state 변경은 0건이었다. 309일 모두 청산 관측이 없었고 두 시나리오 모두 OPEN을 유지했다.

따라서 선행 impact audit 판정은 `A_FAST_B_SELECT_NAVER_REVISION_IMPACT_AUDIT_V01_CHECK_REQUIRED`, 거래별 분류는 4건 모두 `STATE_IMPACT_NO_TRADE_CHANGE`다. 상태 입력과 가격·평가 숫자의 차이는 확인됐지만 거래 lifecycle은 바뀌지 않았다.

## 5. 운영 결정

- 기존 production `AdjustedPriceStore` snapshot과 parquet/sidecar를 소급 수정하거나 현재 Naver 값으로 덮어쓰지 않는다.
- 과거 sidecar provenance를 소급 생성하지 않는다. mismatch 원인이 입증되지 않은 데이터는 기존 Store에서 그대로 보존한다.
- canonical trade history, strategy monitor, 기존 signal/entry/exit 기록과 공식 A FAST Core V2 / B Select Core V2 결과를 유지한다.
- 전체 backtest, portfolio backtest, 전략 재채택 심사는 다시 실행하지 않는다. 이번 targeted replay에서 실제 lifecycle 차이가 없었다.
- 남은 population authority와 P2.2 extension 문제는 이 사건의 closeout과 분리하며, 이 문서를 근거로 P2.2를 production 승격하지 않는다.

## 6. 향후 provenance 진단과 escalation

향후 Naver historical OHLC 차이가 발견되면 바로 Store를 고치거나 전체 재검증하지 않는다. `NAVER_ADJUSTED_FETCH_PROVENANCE_V01`의 진단 정보를 이용해 다음 순서로 확인한다.

1. 수신한 raw payload hash와 parsed canonical OHLC hash가 달라졌는지 확인한다.
2. fetch timestamp와 source/provider version을 확인하고, 저장된 Store `content_sha256` 및 snapshot과 비교해 persisted 값이 바뀌었는지 확인한다.
3. 필요한 경우 영향을 받는 ticker/date만 고정해 당시 cutoff와 정확한 KRX session으로 전략 영향을 replay한다.

| 단계 | 조건 | 조치 |
|---|---|---|
| Level 1 — Data Difference Only | historical OHLC 차이, 전략 영향 미확인 | provenance와 mismatch 범위를 확인하고 Store 자동 수정 금지 |
| Level 2 — Strategy State Difference | continuous indicator/feature/score 차이, 신호·lifecycle 동일 | targeted impact audit으로 종료 가능. 전체 backtest 불필요 |
| Level 3 — Trade Lifecycle Difference | signal, eligibility, execution session 또는 trade 존재 여부 변화 | 영향을 받는 ticker/date/trade cohort를 고정하고 wider replay. 필요성이 증명될 때만 wider/full backtest 검토 |

Level 3도 즉시 전체 backtest로 확대하지 않는다. 먼저 대상 cohort replay로 영향 범위를 확정한다.

## 7. 별도 backlog — OPEN valuation 의미

현재 OPEN position의 진입가와 평가수익률을 frozen historical adjusted basis로 유지할지, 최신 Naver adjusted history로 재평가할지는 별도 valuation/UI semantic policy다. 이번 closeout에서는 정책을 정하거나 구현하지 않는다. 전략 signal/lifecycle 영향이나 과거 source 원인과 혼합하지 않고, 필요하면 별도 지시서로 다룬다.

## 8. 무결성 검증

선행 감사의 production Store manifest는 작업 전·후 모두 6,414개 저장 쌍, 187,719,956 bytes, SHA-256 `e9f2c4312d15f23e8181b1f0334411a1105c38f64597c4d99072db41e95024e4`로 동일했고, 변경 항목은 0개였다. 선택한 policy/authority 파일 13개도 전부 동일했으며 `web/data/strategy-monitor.json`은 5,197,544 bytes, SHA-256 `5112916fbe5eede85c539e5334c749aea8819279b395be039e6cd77e9eb2b9dc`로 동일했다. 이 closeout 작업은 문서만 추가하며 Store, canonical trade history, strategy code, strategy monitor/report 및 source policy를 수정하지 않는다.

Daily Update, Store backfill/replay, strategy backtest는 실행하지 않았다. 최종 문서 검증은 `git diff --check`로 수행한다.

## 9. 재개 조건

이 사건은 본 closeout으로 종료한다. 다음 중 하나가 새로 확인될 때만 다시 연다.

1. provenance로 뒷받침되는 새 source revision 또는 Store divergence
2. 실제 전략 signal 또는 trade lifecycle 변화
3. production Store population failure 확정
4. OPEN valuation 의미를 별도 정책으로 변경하기로 결정

그 외에는 추가 audit, replay 또는 backtest를 실행하지 않는다.
