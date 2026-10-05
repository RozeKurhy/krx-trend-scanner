# B Select Core V1

> 공식 표시명: **B Select Core V1**
>
> 전략 ID: `PATTERN_B_SELECT_CORE_V01`
>
> 기록 상태: 역사적 공식 버전. 후속 공식 버전은 [B Select Core V2](PATTERN_B_SELECT_CORE_V02.md)다.

V1은 당시 월말 ENTRY·EXIT 규칙, production artifact, 거래 이력을 보존한다. V1 EXIT cadence는
월말 observation only이며, 현재 운영 전략 규칙은 V2 문서를 따른다. 과거 산출물의 전략 ID와
내용은 수정하지 않는다.

## V1 승격 당시 지위와 역할

| 항목 | V1 승격 당시 기준 |
|---|---|
| 전략 유형 | Pattern B 상태와 Pattern A Stage를 결합한 별도 매매 전략 |
| 공식 상태 | 당시 공식 전략 채택 (`OFFICIAL_STRATEGY_ADOPTED`) |
| 기본 전략·CONTROL | 아님 |
| 전체 종목 기본형 | 공식 규칙에 포함 |
| 자동 주문 | 승인하지 않음 |

V1 승격 당시 기본 전략과 CONTROL은 `A FAST Core V2` (`PATTERN_A_FAST_FINAL_STRATEGY_V02`)였다.
B Select Core V1의 당시 공식 채택은 기본 전략 교체나 자동 주문 승인을 뜻하지 않았다.

Pattern B는 공식 패턴이며 종목의 장기 가격 상태를 판정한다. B Select Core V1은 그 상태와 Pattern A
Stage를 진입 규칙에 사용했던 별도 공식 전략이다. 현재 후속 전략은 [B Select Core V2](PATTERN_B_SELECT_CORE_V02.md)다.
Pattern B 패턴 자체의 규칙이나 운영 계약은
[Pattern B 공식 규격](../spec/production_authority.md)에 둔다.

## 기존 후보와의 관계

B Select Core V1은 검증 후보 `PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01`의 진입 규칙을 변경하지
않고 계승했다. 후보의 검증 당시 `HOLD`는 그때 공식 검증의 판정이다. Battle V02의 전체
종목 포트폴리오 결과를 당시 공통 공식 채택 기준에 대조한 판정은 이 문서의
`OFFICIAL_STRATEGY_ADOPTED`다. 전체 후보 이력은 [기존 후보 기록](PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01.md)에
보존되어 있다.

## 전략 규칙

### 유니버스

- Battle A 전체 종목 기본형과 같은 날짜별 PIT 유니버스를 사용한다.
- 시가총액이나 거래량으로 거르는 추가 종목 필터는 없다.
- V1 검증 당시의 영구 제외 기준을 사용했다. V2는 갱신된 181쌍 권위를 적용하며, 현재 기준은 [V2 전략 문서](PATTERN_B_SELECT_CORE_V02.md)를 따른다.
- KOSPI 한정 및 진입일 기준 PIT 시가총액 1조원 이상 변형은 공식 규칙에 포함하지 않는다.

### 진입

진입 판정은 매월 마지막 exact KRX 거래일 observation에서만 한다. 그 월말에 아래 조건을
모두 충족할 때 진입 신호를 만든다.

1. Pattern B 진입 상태가 `DEPRESSED`다.
2. 현재 Pattern A Stage가 `PROGRESSED`다.
3. 진입 시점의 권위 있는 직전 Pattern A Stage가 `EARLY_TREND` 또는 `TRANSITION`이다.

직전 Stage가 `BASE`, `WEAK`, `UNAVAILABLE` 또는 그 밖의 값이면 진입하지 않는다.
신호일 다음 첫 exact KRX 거래일 시가에 체결한다. 이는 다음 월요일을 뜻하지 않는다.

### 청산과 생애주기

- 청산 판정도 매월 마지막 exact KRX 거래일 observation에서만 한다.
- 보유 중 해당 월말 observation에서 Pattern B가 `NORMAL`이면 청산 신호를 만든다.
- 월중 `NORMAL` 관측만으로 청산 신호를 만들지 않는다. 월중 상태가 다시 바뀌면 그 달에는
  청산하지 않는다.
- 청산 신호일 다음 첫 exact KRX 거래일 시가에 전량 체결한다. 요일 기준으로 계산하지 않는다.
- 유효 기간 종료 뒤에는 신규 진입하지 않는다. 유효 기간 안에 발생한 `NORMAL` 청산 신호의
  정산에만 체결 지원일을 허용한다.
- 이월 보유는 허용하지 않는다. 동일 종목 식별자의 보유 기간이 서로 겹치지 않는다.
- 별도 손절, `DEEP_DEPRESSED` 청산, Pattern A Stage 청산, 추가 대기 기간·임계값·Stage 조건은 없다.

과거 원장·산출물의 전략 ID는 검증 당시 값으로 보존한다. B Select Core V1의 공식 전략 ID와
관련 산출물 ID는 `PATTERN_B_SELECT_CORE_V01`이다.

## 보존된 V1 current status와 Strategy Monitor 기록

V1 운영 당시 Phase4D가 아래 경로에 exact `target_as_of`와 `reference_market_date`별 status artifact를 생성했다.

```text
artifacts/strategies/b_select_core_v1/production/{YYYYMMDD}/status.json
```

이 artifact는 V1 기준 Strategy Monitor 상태 projection이다. 현재 Monitor는 V2 status를 사용한다.
과거 completed Pattern B
관측과 해시 검증된 Pattern A progressed-episode stage lineage로 종목별 lifecycle을 복원하고,
동일 실행의 공개 COMMON Stock Report 상태를 반영했다. Pattern A/B 상태와 데이터
health는 매 거래일 표시할 수 있지만, 신규 ENTRY/EXIT lifecycle 신호는 완결된 월의 마지막
exact KRX 거래일 observation에서만 만든다. 체결은 신호 다음 첫 exact KRX session open만
인정한다. `reference_market_date` 이후 체결은 pending으로 남기며 미래 시가를 조회하지 않는다.
새 backtest·portfolio simulation·성과 metric을 만들지 않는다.

당시 Monitor scope는 해당 실행에서 공개된 COMMON 리포트 집합이다. 2026-09-25 기준 공개 집합은
1,451개다. B Select 공식 전략의 전체 PIT COMMON 적용 범위와 웹 Monitor의 공개 리포트 범위는
서로 다르다. 영구 identity 제외는 전역 exact `(ticker, ISU)` authority를 적용한다.

Pattern B 또는 lifecycle authority가 누락·불일치하면 상태를 임의로 `WAIT`로 채우지 않고
당시 Phase4D를 실패 처리했다. 이 Monitor 연결은 투자 의사결정 지원 표시이며 자동 주문 승인이 아니다.

## V1 당시 공식 채택 근거

[공식 전략 공통 채택 기준](../../../../docs/validation/official_strategy_adoption_criteria.md)의 A~E를
기존 Battle A 전체 종목 결과에 대조했다. 추가 백테스트 없이 저장된 다섯 구간의 결과와 게이트를
사용했다.

| 기준 | 판정 | 근거 |
|---|---|---|
| A 무결성 | `PASS` | PIT·종목 식별자·Pattern A Stage 연결·생애주기·현금 보존 검사를 다섯 구간에서 통과했다. Battle V02 최종 검증은 30/30 `PASS`, 워커 10개다. 당시 영구 제외 174쌍 중 추가된 식별자의 결과 영향은 아래에서 별도 대조했다. |
| B 실행 비용 | `PASS` | 매수·매도 수수료 0.015%, 슬리피지 0.1% 적용. 다섯 구간 비용 적용 범위 100%, 불일치 0건, 공식 수익률 산식의 매도세금 0원이다. |
| C 수익성 | `PASS` | 다섯 표준 기간 모두 총수익률과 CAGR이 양수다. |
| D 포트폴리오 MDD | `PASS` | P1 절대 기준 -55%, P2/P3 각 -40% 이내다. A FAST Core V2 CONTROL 대비 MDD 악화도 없으며 공통 상대 기준을 통과했다. |
| E 결과 유효성 | `PASS` | 다섯 기간 평가 포함률이 모두 100%이고, 중대한 미해결 유효성 문제가 없다. |

### Battle A 전체 종목 결과

아래 수치는 수수료와 슬리피지를 반영하고 매도세금을 제외한 결과다. 평가 포함률은 모두 100%이며,
MDD는 다섯 구간 모두 `EXACT`다.

| 기간 | 총수익률 | CAGR | MDD | 평가 포함률 |
|---|---:|---:|---:|---:|
| P1 | +95.64% | +5.44% | -20.30% | 100.00% |
| P2-1 | +27.46% | +5.67% | -20.50% | 100.00% |
| P2-2 | +29.13% | +4.63% | -26.08% | 100.00% |
| P3-1 | +17.46% | +4.84% | -17.08% | 100.00% |
| P3-2 | +16.77% | +3.39% | -27.11% | 100.00% |

근거 산출물은 [Battle V02 최종 보고서](../../../../artifacts/strategy_battles/fast_v2_vs_pattern_b_v02/final_report.md),
[Battle A Pattern B 보고서](../../../../artifacts/strategy_battles/fast_v2_vs_pattern_b_v02/battle_a_all_universe/pattern_b/report.md),
[기간별 지표](../../../../artifacts/strategy_battles/fast_v2_vs_pattern_b_v02/battle_a_all_universe/pattern_b/battle_window_metrics.csv)
및 [기간별 채택 게이트](../../../../artifacts/strategy_battles/fast_v2_vs_pattern_b_v02/battle_a_all_universe/pattern_b/)다.

Battle A 원 결과는 173쌍의 제외 권위로 생성됐다. 당시 영구 제외된 `096300/KR7096300009`는
Pattern B 다섯 구간의 진입 시도 감사 원장에 없고, Battle V02 최종 보고서도 이 종목의 여섯
미체결 시도를 V2 결과로 기록한다. 따라서 174번째 제외가 기존 Pattern B 결과를 바꾸지 않아
재백테스트하지 않았다. 이 문단은 V1 검증 당시의 제외 감사 기록이며, 현재 V2는 V2 전략 문서가
가리키는 181쌍의 영구 제외 권위를 따른다.

## 성과 특성과 범위

Battle A에서 Pattern B는 다섯 기간의 거래 승률 약 76–81%, 거래 수익률 중앙값 약 +11–14%, 평균
자본 활용률 약 28–57%를 보였다. V2보다 승률과 거래 수익률 중앙값이 높고 MDD와 자본 활용률은
낮았다. V2는 자본을 더 많이 사용하고 큰 승자에 더 의존해 절대수익 잠재력이 큰 대신 더 큰
MDD를 보였다. 기간별 실현 수익률은 서로 달랐으며, 채택은 모든 지표에서 V2를 앞선다는 판정이
아니다.

KOSPI 한정 결과는 저노출·저MDD 연구 변형으로 보존하고 공식 규칙에 포함하지 않는다. 진입일
기준 PIT 시가총액 1조원 이상 변형은 `CLOSED_NO_FURTHER_STOCK_MCAP_SWEEP`으로 종료되었다.
두 연구 변형의 기존 결과와 원시 산출물은 [Battle V02 기록](../../../../artifacts/strategy_battles/fast_v2_vs_pattern_b_v02/)에
보존되어 있다.
