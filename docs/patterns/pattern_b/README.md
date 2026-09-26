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

## 관련 문서

- [패턴 안내](../README.md)
- [Pattern A 안내](../pattern_a/README.md)
- [Pattern A FAST 안내](../pattern_a_fast/README.md)
