# Pattern A 투자 적합성 정책

## 1. 역할

이 문서는 Pattern A가 구조 후보를 찾은 뒤 적용하는 현재 투자 적합성·거래
가능성 후단 필터의 기준이다. Pattern A Score, Stage, Raw Candidate 정의를
변경하지 않으며, 보통주 후보를 `INVESTABLE` 또는 명시적인 탈락·평가 불가
상태로 분류한다.

현재 정책은 자동 주문 승인이나 투자 권고가 아니라 의사결정 지원용 판정이다.

## 2. 현재 확정 정책

| 항목 | 현재 기준 |
|---|---|
| 대상 | Pattern A 구조 후보 중 KRX 공식 보통주 (`COMMON`) |
| 최소 시가총액 | `100,000,000,000 KRW` 이상 (1,000억 원) |
| 최소 20일 평균 거래대금 | `300,000,000 KRW` 이상 (3억 원) |
| 가격 하드필터 | 없음 (`NOT_NEEDED`) |
| 60일 평균 거래대금 | 참고·검증 지표. 단독 필수 조건 아님 |
| 필수 데이터 부족 | `DATA_UNAVAILABLE` |
| 현재 구현 | `src/trend_scanner/filters/investability.py` |

이 문서의 임계값은 현재 운영 계약이다. 과거 Phase 10의 분포·시나리오
비교는 선택 근거를 보존하는 역사 자료이며, 이 문서에서 새 임계값을 탐색하지
않는다.

## 3. 판정 순서

한 종목을 기준일 `as_of`에서 다음 순서로 판정한다.

1. 필수 입력을 확인한다.
   - 양수이고 결측이 아닌 PIT 시가총액
   - `as_of` 당일의 exact close 관측값
   - `as_of` 이하에 존재하는 완전한 20개 거래대금 관측값
2. 하나라도 없으면 `DATA_UNAVAILABLE`로 종료한다.
3. 시가총액이 `100,000,000,000 KRW` 미만이면
   `FILTERED_MARKET_CAP`으로 판정한다.
4. 20일 평균 거래대금이 `300,000,000 KRW` 미만이면
   `FILTERED_LIQUIDITY`로 판정한다.
5. 위 조건을 모두 통과하면 `INVESTABLE`로 판정한다.

판정 상태는 다음 네 가지를 사용한다.

| 상태 | 의미 |
|---|---|
| `INVESTABLE` | 시가총액·20일 평균 거래대금 조건을 모두 통과 |
| `FILTERED_MARKET_CAP` | 시가총액이 1,000억 원 미만 |
| `FILTERED_LIQUIDITY` | 20일 평균 거래대금이 3억 원 미만 |
| `DATA_UNAVAILABLE` | 필수 입력을 기준일에서 확인할 수 없음 |

필수 데이터 결측은 저유동성이나 소형주 탈락과 섞지 않는다. 판정 사유는
`REQUIRED_METRIC_UNAVAILABLE` 등 코드가 정한 설명값으로 함께 보존한다.

## 4. 결측 처리와 60일 참고 지표

- `market_cap`이 없거나 양수가 아니면 `DATA_UNAVAILABLE`이다.
- `daily`가 없거나 비어 있으면 `DATA_UNAVAILABLE`이다.
- `as_of` 이전 자료만 남긴 뒤 `as_of` exact index가 없거나 close가 결측이면
  `DATA_UNAVAILABLE`이다. 휴일·거래정지·stale 자료를 다른 날짜 값으로
  조용히 대체하지 않는다.
- 20개 미만의 유효한 `trading_value` 관측값이면 20일 평균을 만들 수 없으므로
  `DATA_UNAVAILABLE`이다.
- 60일 평균 거래대금은 충분한 관측값이 있을 때 참고값으로 계산한다. 60일
  값이 없다는 이유만으로 `DATA_UNAVAILABLE`로 바꾸지 않는다.
- 보간, 전방 채움, 0 대체, 현재 시점 값의 과거 시점 방송은 사용하지 않는다.

## 5. Point-in-Time 원칙

`as_of`에서 사용할 수 있었던 정보만 사용한다. 시가총액은 호출부가 기준일에
맞는 PIT 값을 제공해야 하며, 현재 또는 미래 시가총액을 과거 판정에 사용하지
않는다. 일별 가격·거래대금도 다음 조건을 지킨다.

- `daily.index <= as_of`로 자른 자료만 사용한다.
- close는 기준일 exact 관측값을 요구한다.
- 20일 평균은 기준일 이하의 마지막 20개 유효 관측값으로 계산한다.
- 데이터 원천·시장 구분·보통주 여부는 KRX 공식 메타데이터와 현재 저장소
  계약을 따른다.

투자 적합성 필터는 Pattern A 후보를 후단에서 분류하며 Pattern A의 Score,
Stage, 후보 수를 재계산하거나 변경하지 않는다.

## 6. 현재 구현 위치

주요 구현은 다음과 같다.

- 상수: `MIN_MARKET_CAP_KRW`, `MIN_AVG_TRADING_VALUE_20D_KRW`
- 상태: `InvestabilityStatus`
- 사유: `InvestabilityReason`
- 결과: `InvestabilityEvaluationResult`
- 판정 함수: `evaluate_investability(...)`

현재 구현은 60일 평균 거래대금을 결과에 포함할 수 있지만, 판정의 필수
통과 조건은 시가총액·exact close·20일 평균 거래대금이다.

## 7. 역사적 선정 근거

다음 문서는 과거 Phase 10의 임계값 비교·통합 검증 기록이다. 현재 정책의
상세 실험 보고서이지, 별도 현재 계약이나 진행 중인 작업 지시가 아니다.

- [Phase 10B 임계값 설계·검증](../archive/validation/investability_threshold_design_v01.md)
- [Phase 10C 후단 통합 검증](../archive/validation/investability_integration_v01.md)
- [문서 재정리 분류표](../../PATTERNS_DOC_REORGANIZATION_REVIEW_V01.md)

현재 구현과 역사 문서가 다르면 현재 구현과 이 현재 기준 문서를 우선 확인하고,
규칙 변경은 별도 승인된 변경 작업으로만 수행한다.
