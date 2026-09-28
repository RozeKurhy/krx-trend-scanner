# Pattern B

Pattern B는 종목 자신의 장기 가격 사이클에서 현재 가격이 침체 쪽인지 과열 쪽인지를 5단계로
분류하는 **공식 패턴** (`OFFICIAL_PATTERN`)이다. 상태는 매수·매도 신호가 아니며, 전략·백테스트와
분리되어 있다. 일일 갱신·웹에는 아직 연결되지 않았다.

## 현재 공식 상태

| 항목 | 현재 기준 |
|---|---|
| 역할 | 자기 장기 가격 사이클 내 침체·과열 상태를 5단계로 분류 |
| 공식 상태 | 공식 패턴 (`OFFICIAL_PATTERN`) |
| 현재 상태 판정 규칙 | V02 (`PATTERN_B_STATE_RULE_V02`), 추가 튜닝 없음 |
| 현재 지표 계약 | V01 중 유지 지표 3개 (월봉 2개, 주봉 1개) |
| 현재 운영 계약 | V02 |
| 최신 전체 종목 운영 감사 | V02 `PASS` (2026-09-21 기준) |
| 운영 연결 | 일일 갱신·웹 미연결 |

Pattern B의 "싸다"는 기업가치 대비가 아니라 자기 과거 가격 대비 침체라는 뜻이다. 독립 사람 검증
성능은 없으며, 알려진 한계는 공식 규격 문서에 있다.

## 현재 기준 문서

1. [Pattern B 공식 규격](spec/production_authority.md) — 현재 권위, 구현 위치, 알려진 한계
2. [Pattern B 개념 기준](spec/README.md) — 목적, 경계, 시간축 역할, 5개 상태의 의미
3. [지표 계약 V01](spec/feature_contract_v01.md) — 지표 산식, PIT, 계산 불가 처리
4. [상태 판정 규칙 V02](validation/state_rule_v02.md) — 현재 규칙, 임계값, 봉인
5. [운영 계약 V02](spec/production_contract_v02.md) — 운영 호출, 평가 상태, 시장 이전 이력, 가격 신선도
6. [전체 종목 운영 감사 V02](validation/full_universe_operational_audit_v02.md) — 전체 종목 1회 적용 점검

공식 채택 근거는 [공식 패턴 채택 판단 V01](validation/adoption_decision_v01.md)에 있다.

## 연구 기록

과거 사람 판정, 표본, 별도 검증 표본(Holdout), 지표 진단·선택, 상태 판정 규칙 V01·V02 연구
과정과 봉인 자료, 이전 운영 계약·감사는 `validation/`과 `spec/`에 연구 기록으로 보존한다. 당시
문서의 상태 표현은 현재 상태가 아니며, 현재 공식 기준은 위 문서 목록을 따른다.

### 관련 전략 연구 상태

- 현재 연구 후보 ID는 `PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01`이다. 규칙과 기존 공식 검증 이력은 [후보 규칙 문서](strategy/PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01.md) 및 [공식 검토 결과](../../../artifacts/patterns/pattern_b/progressed_previous_stage_early_transition_only_official_validation_v01/report.md)에 보존한다.
- `V2 vs Pattern B 3-Way Portfolio Battle V02`는 30개 비교 항목, worker 10개로 완료되어 최종 `PASS`다. 이는 비교 검증 결과이며 공식 전략 채택 판정은 아니다. 기존 공식 검증의 채택 보류(`HOLD`)는 유지하고, Pattern B 후보도 새 전략명이나 공식 production strategy로 승격하지 않는다. 원 결과와 검증 이력은 [Battle V02 최종 보고서](../../../artifacts/strategy_battles/fast_v2_vs_pattern_b_v02/final_report.md)에 보존한다.
- 전체 종목 기본형은 독립 연구·운용 후보로 보존한다. 이번 단계에서 stock-universe threshold/filter 연구는 종료했으며, 기존 raw artifact와 검증 이력은 그대로 유지한다.

#### Battle V02의 연구 상태

| 비교 | 최종 상태 | 해석 |
|---|---|---|
| Pattern B 전체 종목 기본형 | 유지 — 연구·운용 후보 | Pattern B의 전체 전략을 대표한다. 추가 stock-universe threshold/filter sweep은 하지 않는다. |
| KOSPI-only (`battle_c_kospi_only`) | 유지 — 저노출·저MDD 연구 variant | 전체 전략을 대체하거나 공식 채택한 것이 아니며, 별도 전략 ID도 만들지 않는다. 5개 창의 승률은 약 79–80%, trade median은 약 +10–14%, MDD는 약 -9~-11%, 평균 자본 활용률은 약 12–21%다. 최근 P3-1·P3-2에서 포트폴리오 수익률은 각각 +14.41%·+23.94%로 V2의 -14.27%·+2.96%보다 높았다. 연구 결과만 보존하며 필요할 때 재검토한다. |
| entry-date exact PIT 시총 ≥ 1조원 (`battle_b_pit_mcap_1t`) | `CLOSED_NO_FURTHER_STOCK_MCAP_SWEEP` | Pattern B 실행 수는 P1 33, P2-1 12, P2-2 26, P3-1 9, P3-2 23건이고 평균 자본 활용률은 약 1.84–2.76%다. 대부분 현금이 남아 추가 시총 sweep의 실익이 낮다. 기존 산출물은 보존한다. |
| `PATTERN_A_FAST_FINAL_STRATEGY_V02` / A FAST Core V2 | 공식 CONTROL 유지 | Pattern B 결과로 규칙, 이름, 공식 지위를 변경하지 않는다. V2는 더 높은 자본 활용과 큰 승자 의존, 더 큰 절대수익 잠재력 및 더 큰 MDD를 보였고, Pattern B는 더 높은 승률·양(+)의 trade median·낮은 자본 활용·낮은 MDD 특성을 보였다. |

다음 비교 연구는 ETF universe에 한정한 `V2 vs Pattern B vs Julia`다. 해당 연구는 아직 실행하지 않았다.

## 관련 문서

- [패턴 안내](../README.md)
- [Pattern A 안내](../pattern_a/README.md)
- [Pattern A FAST 안내](../pattern_a_fast/README.md)
