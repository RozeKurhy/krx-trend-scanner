# Pattern B

Pattern B는 종목 자신의 장기 가격 사이클에서 현재 가격이 침체 쪽인지 과열 쪽인지를 5단계로
분류하는 **공식 패턴** (`OFFICIAL_PATTERN`)이다. 상태는 매수·매도 신호가 아니며, 패턴과 전략은
별도 영역에서 관리한다. 현재 스캐너·일일 갱신·웹에는 연결되어 있지 않다.

## 현재 기준

| 항목 | 현재 기준 |
|---|---|
| 역할 | 자기 장기 가격 사이클 내 침체·과열 상태를 5단계로 분류 |
| 공식 상태 | 공식 패턴 (`OFFICIAL_PATTERN`) |
| 현재 상태 판정 규칙 | V02 (`PATTERN_B_STATE_RULE_V02`), 추가 튜닝 없음 |
| 현재 지표 계약 | V01 중 유지 지표 3개 (월봉 2개, 주봉 1개) |
| 현재 운영 계약 | V02 |
| 최신 전체 종목 운영 감사 | V02 `PASS` (2026-09-21 기준) |
| 관련 공식 전략 | [B Select Core V1](strategy/PATTERN_B_SELECT_CORE_V01.md) (`PATTERN_B_SELECT_CORE_V01`) |
| 기본 전략 여부 | 기본 전략·CONTROL이 아님. 기본/CONTROL은 [A FAST Core V2](../pattern_a_fast/strategy/version_02/README.md) |
| 운영 연결 | 스캐너·일일 갱신·웹의 현재 운영 범위에 포함되지 않음 |

Pattern B의 “싸다”는 기업가치 대비가 아니라 자기 과거 가격 대비 침체라는 뜻이다. 독립 사람 검증
성능은 없으며, 알려진 한계는 공식 규격 문서에 있다. B Select Core V1은 Pattern B 상태를 이용하는
별도의 매매 전략이며, 전략 규칙과 공식 채택 근거는 해당 전략 문서에 있다.

## 현재 기준 문서

1. [Pattern B 공식 규격](spec/production_authority.md) — 현재 권위, 구현 위치, 알려진 한계
2. [Pattern B 개념 기준](spec/README.md) — 목적, 경계, 시간축 역할, 5개 상태의 의미
3. [지표 계약 V01](spec/feature_contract_v01.md) — 지표 산식, PIT, 계산 불가 처리
4. [상태 판정 규칙 V02](validation/state_rule_v02.md) — 현재 규칙, 임계값, 봉인
5. [운영 계약 V02](spec/production_contract_v02.md) — 운영 호출, 평가 상태, 시장 이전 이력, 가격 신선도
6. [전체 종목 운영 감사 V02](validation/full_universe_operational_audit_v02.md) — 전체 종목 1회 적용 점검
7. [B Select Core V1 공식 전략](strategy/PATTERN_B_SELECT_CORE_V01.md) — 공식 규칙과 채택 근거

Pattern B 패턴의 공식 채택 근거는 [공식 패턴 채택 판단 V01](validation/adoption_decision_v01.md)에 있다.

## 전략 검증 결과와 연구 변형

[V2 vs Pattern B 3-Way Portfolio Battle V02 최종 보고서](../../../artifacts/strategy_battles/fast_v2_vs_pattern_b_v02/final_report.md)는
30/30 검증 항목, 워커 10개로 완료되어 `PASS`했다. 전체 종목 Pattern B 결과는 A~E 공식 전략 채택
기준을 다섯 표준 기간 모두 통과했으며, 채택 근거와 수치는 [B Select Core V1 공식 전략 문서](strategy/PATTERN_B_SELECT_CORE_V01.md)에
정리되어 있다. 이 비교 결과로 B Select Core V1을 공식 전략으로 채택했으며 기본 전략은 변경하지 않았다.

| 대상 | 현재 상태 | 기록 |
|---|---|---|
| 전체 종목 기본형 | B Select Core V1 공식 규칙 | 종목 유니버스 임계값·필터 추가 탐색 없이 전체 종목 기준을 유지한다. 기존 원시 산출물과 검증 이력은 보존한다. |
| KOSPI 한정 | 저노출·저MDD 연구 변형 | 승률 약 79–80%, 거래 수익률 중앙값 약 +10–14%, MDD 약 -9~-11%, 평균 자본 활용률 약 12–21%. P3-1·P3-2 수익률은 +14.41%·+23.94%로 V2의 -14.27%·+2.96%보다 높았다. 공식 전략 규칙이나 별도 전략 ID에는 포함하지 않는다. |
| 진입일 기준 정확 PIT 시가총액 1조원 이상 | `CLOSED_NO_FURTHER_STOCK_MCAP_SWEEP` | Pattern B 실행 수는 P1 33, P2-1 12, P2-2 26, P3-1 9, P3-2 23건, 평균 자본 활용률은 약 1.84–2.76%다. 대부분 자본이 현금으로 남아 추가 시가총액 탐색을 종료했다. 기존 산출물은 보존한다. |

기존 후보 ID `PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01`과 검증 당시 `HOLD` 판정은
역사 기록으로 보존한다. 해당 규칙은 변경 없이 B Select Core V1에 계승되었으며, 당시 판정과 현재
공식 채택 상태의 구분은 [후보 기록](strategy/PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01.md)에서
확인할 수 있다.

## 관련 문서

- [패턴 안내](../README.md)
- [Pattern A 안내](../pattern_a/README.md)
- [Pattern A FAST 안내](../pattern_a_fast/README.md)
