# Pattern B 공식 규격

> 이 문서는 현재 Pattern B 공식 규격이다. 현재 기준 문서와 구현 위치를 연결하며, 산식과
> 규칙을 여기에 복제하지 않는다. 채택 근거는
> [공식 패턴 채택 판단 V01](../validation/adoption_decision_v01.md)에 있다.

## 1. 현재 상태

| 항목 | 현재 기준 |
|---|---|
| 패턴 | Pattern B |
| 상태 | 공식 패턴 (`OFFICIAL_PATTERN`) |
| 역할 | 종목 자신의 장기 가격 사이클에서 현재 가격이 침체 쪽인지 과열 쪽인지 5단계로 분류 |
| 현재 상태 판정 규칙 | 상태 판정 규칙 V02 (`PATTERN_B_STATE_RULE_V02`) |
| 지표 계약 | 지표 계약 V01 중 유지 지표 3개 |
| 운영 상태 | 스캐너·일일 갱신·웹에 연결되지 않음. 운영 연결은 별도로 결정한다 |
| 추가 튜닝 | 하지 않음. 규칙을 바꾸려면 새 버전 후보로 진행한다 |

Pattern B 자체의 버전 번호는 없다. 현재 기준은 "Pattern B, 현재 상태 판정 규칙 V02"로 부른다.

## 2. 현재 기준 문서

| 역할 | 문서 |
|---|---|
| 개념·경계·상태 의미 | [Pattern B 개념 기준](README.md) |
| 지표 산식·PIT·계산 불가 처리 | [지표 계약 V01](feature_contract_v01.md) |
| 유지 지표 선택 | [지표 선택 V01](../validation/feature_selection_v01.md) |
| 상태 판정 규칙·임계값 | [상태 판정 규칙 V02](../validation/state_rule_v02.md), [봉인 파일](../validation/state_rule_v02_seal.json) |
| 종목 구간 규칙 | [별도 검증 표본 V02 절차](../validation/holdout_v02_protocol.md) 선정 방법, [원시 지표값 V02](../validation/feature_raw_values_v02.md) 계산 조건 |
| 검증 전략 | [규칙 V02 검증 전략 V01](../validation/state_rule_v02_validation_strategy_v01.md) |

종목 구간 규칙: 기준일을 포함하는 PIT COMMON 종목 구간 안에서만 조정 가격을 읽고, 다른 종목
구간과 이어 붙이지 않는다. 규칙 V02의 근거 자료는 모두 이 규칙으로 계산했다.

## 3. 구현 위치

| 역할 | 위치 |
|---|---|
| 지표 계산 | `src/trend_scanner/patterns/pattern_b_features_v01.py`의 `compute_pattern_b_features_v01(daily, as_of)` |
| 상태 판정 | `src/trend_scanner/patterns/pattern_b_state_v02.py`의 `classify_pattern_b_state_v02(range_36m, monthly_ma24_distance, range_52w)` |
| 계약 테스트 | `tests/test_pattern_b_state_v02.py` |

일봉에서 상태까지 한 번에 계산하는 단일 함수는 없다. 지표 계산 결과 중 유지 지표 3개를 상태
판정에 넘긴다. 지표를 계산할 수 없으면 상태 판정은 오류를 내고 상태를 만들지 않는다.

## 4. 경계

- Pattern B 상태는 매수·보유·매도 신호가 아니다.
- Pattern B의 "싸다"는 자기 과거 가격 대비 침체라는 뜻이며, 기업가치 평가가 아니다.
- 전략, 매매 규칙, 백테스트는 Pattern B에 없다. 전략은
  [전략 생애주기](../../../strategies/strategy_lifecycle.md)를 따른다.
- 가치 함정이나 구조 붕괴 위험을 걸러 내지 않는다.

## 5. 알려진 한계

- 독립 사람 검증 성능이 없다. 개발 표본 V02 수치(정확 일치 22/36 등)는 개발용 참고 성능이다.
- 이 규칙 계열의 유일한 독립 사람 평가(규칙 V01, 별도 검증 표본 V02)는 정확 일치 12/36, 2단계
  이상 오류 7개였다.
- 급등 뒤 급락해 범위 위치는 낮지만 현재 가격이 장기 평균보다 크게 높은 경우, 규칙은 침체
  쪽으로 볼 수 있다(`PBHOLD_028` 유형).
- 규칙 V02의 `DEPRESSED`는 사용자 판정 개념보다 좁다.
- 과열 쪽은 사용자 개념과의 일치를 말할 근거가 적다.
- 계산 불가일 때 "상태 없음"을 나타내는 출력 값이 정의되어 있지 않다.
- 기준일에 거래정지 중인 종목은 마지막 거래 봉으로 상태가 계산된다.
- 전체 종목에 적용한 적이 없어 상태 분포와 계산 불가 비율을 모른다.

## 6. 연구 기록과의 구분

[Pattern B 안내](../README.md)에 연결된 사람 판정, 표본, 지표 진단·선택, 규칙 V01, 별도 검증
표본 V02 평가·사후진단, 규칙 V02 연구 문서는 연구 기록이다. 당시 상태 표현("다음 단계",
"별도 검증 표본 V03" 등)은 현재 상태가 아니다. 현재 기준은 이 문서와 2절의 문서다.
