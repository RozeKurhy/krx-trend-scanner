# Pattern B

Pattern B는 종목 자신의 장기 가격 사이클을 기준으로, 가격이 장기 침체 상태인지
장기 과열 상태인지 탐지하기 위한 **연구 후보 패턴**이다. 아직 공식 패턴이 아니다.
상태 판정 규칙 V01은 별도 검증 표본 V02로 공식 1회 평가를 마쳤다. 상태 판정 규칙 V02는
개발 표본 V02로 만들어 봉인했으며, 별도 검증은 아직 없다. 채택 여부는 아직 정하지 않았으며,
점수와 전략은 없다.

## 현재 상태

| 항목 | 현재 내용 |
|---|---|
| 패턴 | Pattern B |
| 역할 | 자기 장기 가격 사이클 내 침체·과열 상태 탐지 |
| 현재 상태 | 초기 연구 후보 (다음 단계: 규칙 V02에 추가 사람 검증이 필요한지 판단) |
| 시간축 | 월봉(핵심), 주봉(보조) |
| 사람 판정 | V01 36개 판정 완료·봉인. 별도 검증 표본 V02 사람 판정 완료·봉인. 개발 표본 V02 사람 판정 완료·봉인 |
| 지표 | V01 산식·PIT 계약 확정, 적합성 진단 V01 완료, [선택 V01](validation/feature_selection_v01.md) 결정 완료 (유지 3개) |
| 상태 판정 규칙 | [V01](validation/state_rule_v01.md) 설계·봉인 완료. [별도 검증 표본 V02 공식 1회 평가](validation/state_rule_v01_holdout_v02_evaluation.md) 완료, V02는 소진됨. [V02](validation/state_rule_v02.md) 구현·봉인 완료 (개발 표본 성능만 있음) |
| 전략·백테스트 | 없음 |

Pattern B의 “싸다”는 기업가치 대비 싸다는 뜻이 아니라, 자기 과거 가격 상태 대비
극단적으로 침체되었다는 뜻이다. 상태 판단은 매수·보유·매도 신호가 아니다.

## 기준 문서

- [Pattern B 개념 기준](spec/README.md) — 목적, 다른 영역과의 경계, 시간축 역할,
  지표 후보, 상태 후보, 구조 붕괴 위험과의 경계
- [지표 계약 V01](spec/feature_contract_v01.md) — 7개 지표의 산식과 PIT 계약
- [사람 판정 기준 V01](validation/human_ground_truth_v01.md) — 차트를 보고 상태를
  판정하는 원칙. 판정 결과는 [봉인 파일](validation/human_ground_truth_labels_v01.csv)
- [사람 판정 차트 묶음 V01](validation/chart_pack_v01.md) — 고정 표본 36개와 식별정보를
  가린 차트 생성 방식
- [표본 원시 지표값 V01](validation/feature_raw_values_v01.md) — 36개 표본의 7개 지표
  원시값
- [지표 적합성 진단 V01](validation/feature_fitness_v01.md) — 사람 판정과 원시 지표값의
  관계 진단
- [지표 선택 V01](validation/feature_selection_v01.md) — 7개 지표의 유지·수정·제외 결정과
  상태 판정 규칙 설계에 넘길 유지 지표 목록
- [별도 검증 표본 V02 절차](validation/holdout_v02_protocol.md) — 상태 판정 규칙 봉인
  뒤에만 여는 검증용 표본 36개
- [사람 판정 V02](validation/human_ground_truth_v02.md) — 별도 검증 표본 36개의 사용자
  판정과 봉인 기록 (자동 평가 전)
- [개발 표본 V02](validation/development_v02_protocol.md) — 사람 판정 기준 V02용 개발 표본 36개.
  [사람 판정](validation/development_v02_human_labels.md)·[지표 평가](validation/development_v02_feature_evaluation_v01.md)·[규칙 V02 연구](validation/state_rule_v02_research_v01.md)
  완료
- [사람 판정 기준 V02](validation/human_ground_truth_criteria_v02.md) — 현재 상태 우선 원칙.
  별도 검증 표본 V03 이후 새 판정부터 적용
- [별도 검증 표본 V02 사후진단 V01](validation/holdout_v02_posthoc_adjudication_v01.md) — 공식
  평가 뒤 대형 오류 7개를 다시 본 진단 기록. 공식 평가는 바꾸지 않았고, 다음 판정 기준·규칙
  연구용이다
- [상태 판정 규칙 V01](validation/state_rule_v01.md) — 유지 지표 3개로 만든 5단계 자동
  상태 판정 규칙과 봉인 기록
- [상태 판정 규칙 V02](validation/state_rule_v02.md) — V01에서 극단 침체 조건 하나만 바꾼
  규칙과 봉인 기록. 성능은 개발 표본 기준이다

## 관련 문서

- [패턴 안내](../README.md)
- [Pattern A 안내](../pattern_a/README.md)
- [Pattern A FAST 안내](../pattern_a_fast/README.md)
