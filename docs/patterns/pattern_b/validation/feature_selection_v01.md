# Pattern B Feature 선택 V01

> 상태: 7개 Feature의 유지·수정·제외(KEEP / MODIFY / DROP) 결정 완료. 다음 단계인 상태
> 규칙 설계에 가져갈 Feature 구성만 정했다. 임계값, 가중치, 점수, 자동 상태 판정은
> 아직 없다.

## 1. 목적

[Feature 적합성 진단 V01](feature_fitness_v01.md)을 근거로
[Feature 계약 V01](../spec/feature_contract_v01.md)의 7개 Feature를 각각 다음 중 하나로
정한다.

| 결정 | 뜻 |
|---|---|
| `KEEP` | V01 산식과 역할을 그대로 두고 상태 규칙 설계의 입력 후보로 넘긴다 |
| `MODIFY` | 개념은 유효하지만 V01 형태로는 부족하다. 수정 유형과 방향만 적고 V02 연구로 분리한다 |
| `DROP` | V01 상태 규칙 설계에 쓰지 않는다. 연구 기록으로는 남긴다 |

이번 결정에서 Feature 산식, raw 값, 진단 수치는 바꾸지 않았다. 미래 수익률, 전략 성과,
비공개 대응표는 보지 않았다.

## 2. 입력 진단 요약

진단 보고서의 수치를 그대로 옮긴다. 약어: DEEP=`DEEP_DEPRESSED`, DEP=`DEPRESSED`,
NORM=`NORMAL`, OVH=`OVERHEATED`, EXT=`EXTREME_OVERHEATED`.

| Feature | 시간축 | Spearman 전체 / HIGH | median 기대 방향 | IQR 겹침 | 가장 높은 Feature 상관 |
|---|---|---|---|---|---|
| `36M_RANGE_POSITION` | 월봉 | 0.845 / 0.875 | 4/4 | NORM–OVH, OVH–EXT | `36M_HIGH_DRAWDOWN` 0.957 |
| `MONTHLY_MA24_DISTANCE` | 월봉 | 0.847 / 0.863 | 4/4 | NORM–OVH | `36M_RANGE_POSITION` 0.928 |
| `12M_RETURN_HISTORICAL_PERCENTILE` | 월봉 | 0.676 / 0.679 | 3/4 (OVH→EXT 역전) | DEEP–DEP, NORM–OVH, OVH–EXT | `MONTHLY_MA24_DISTANCE` 0.86 |
| `36M_HIGH_DRAWDOWN` | 월봉 | 0.788 / 0.855 | 4/4 | OVH–EXT | `36M_RANGE_POSITION` 0.957 |
| `52W_RANGE_POSITION` | 주봉 | 0.684 / 0.778 | 4/4 | OVH–EXT | `WEEKLY_MA40_DISTANCE` 0.879 |
| `WEEKLY_MA40_DISTANCE` | 주봉 | 0.649 / 0.758 | 4/4 | DEP–NORM, NORM–OVH, OVH–EXT | `26W_RETURN_HISTORICAL_PERCENTILE` 0.929 |
| `26W_RETURN_HISTORICAL_PERCENTILE` | 주봉 | 0.546 / 0.668 | 4/4 | DEP–NORM, NORM–OVH, OVH–EXT | `WEEKLY_MA40_DISTANCE` 0.929 |

## 3. 판단 기준

각 Feature를 다섯 관점에서 검토했다. 숫자 점수나 가중 합계는 만들지 않았다.

- **사람 판정 정렬**: Spearman 전체·HIGH-only, 인접 4구간 median 순서
- **경계 분리**: 인접 label IQR 겹침. 특히 NORM–OVH와 OVH–EXT를 본다. DEEP(2개)와
  DEP(4개)가 걸린 구간은 표본이 적어 약하게 본다.
- **confidence 견고성**: MEDIUM을 뺐을 때 상관이 나빠지거나 순서가 깨지는지 본다.
  HIGH-only의 DEP는 1개뿐이라 과대해석하지 않는다.
- **중복성**: 상관이 높은 쌍은 더 단순한지, 해석하기 쉬운지, 경계를 더 잘 나누는지,
  월봉 핵심·주봉 보조 역할에 맞는지 비교한다. 상관이 높다는 이유만으로 제외하지 않는다.
- **시간축 역할**: 월봉은 핵심, 주봉은 보조다. 주봉 Feature가 월봉에 없는 최근 상태를
  보완하는지, 주봉끼리 중복되는지 본다.

## 4. Feature별 결정

### `36M_RANGE_POSITION` — KEEP

근거:
- 정렬: Spearman 0.845 / 0.875, median 4구간 모두 기대 방향이다.
- 경계: NORM–OVH(0.546~0.589)와 OVH–EXT(0.755~0.788)의 IQR 겹침은 폭이 좁다.
- 견고성: HIGH-only에서 상관이 오르고 순서도 유지된다.
- 중복: `36M_HIGH_DRAWDOWN`과 0.957, `MONTHLY_MA24_DISTANCE`와 0.928이다. 고점 대비
  하락 폭은 고점 한쪽만 기준으로 삼지만, 범위 위치는 저점과 고점을 함께 기준으로 삼아
  침체와 과열 양쪽을 한 값으로 나타낸다.
- 역할: 장기 범위 안에서 현재 가격이 어디에 있는지를 나타내는 월봉 핵심 위치 지표다.

주의점:
- DEEP(0.048)과 DEP(0.090)의 median 차이는 작고 표본도 적다.
- MEDIUM 표본 중 `NORMAL`로 판정된 `PBHGT_024`(0.254), `PBHGT_032`(0.306),
  `PBHGT_033`(0.113)은 값이 낮은 편이다. 판정 화면은 월봉 84개를 보여줬고 이 Feature는
  36개만 본다. 이 차이는 창 길이 문제일 수 있으나, MEDIUM 표본 몇 개만으로 창을 바꾸지
  않는다.

다음 단계 영향: 현재 V01 산식을 그대로 상태 규칙 설계의 입력으로 쓴다.

### `MONTHLY_MA24_DISTANCE` — KEEP

근거:
- 정렬: 전체 Spearman 0.847로 7개 중 가장 높고, HIGH-only 0.863이다. median 4구간
  모두 기대 방향이다.
- 경계: 인접 IQR 겹침은 NORM–OVH(0.128~0.132)뿐이며 폭이 매우 좁다. OVH–EXT가 겹치지
  않는 월봉 Feature는 이것뿐이다.
- 견고성: HIGH-only에서 상관이 오르고 순서도 유지된다.
- 중복: `36M_RANGE_POSITION`과 0.928이다. 범위 위치는 0~1로 묶여 상단에서 포화되지만,
  이동평균 이격은 상한이 없어 확장 강도를 구분한다(EXT median 0.713, Q3 1.848).
  사람이 보는 "범위 안 위치"와 "추세 평균 대비 확장 정도"는 다른 상태 차원이다.
- 역할: 월봉 핵심 확장·침체 강도 지표다.

주의점:
- `NORMAL`의 범위가 넓다(−0.559~0.335). 극단값 쪽 `NORMAL` 판정은 MEDIUM 표본이다.

다음 단계 영향: 현재 V01 산식을 그대로 상태 규칙 설계의 입력으로 쓴다.

### `12M_RETURN_HISTORICAL_PERCENTILE` — DROP

근거:
- 정렬: Spearman 0.676 / 0.679로 월봉 Feature 중 가장 낮다. OVH→EXT median이 역전된다
  (87.651 → 87.200).
- 경계: 상단에서 값이 100 근처에 몰려 OVH와 EXT를 나누지 못한다(IQR 68.6~99.4와
  81.0~95.4가 겹침). NORM–OVH도 겹친다.
- 견고성: HIGH-only에서 상관이 거의 오르지 않고, DEEP→DEP와 OVH→EXT가 역전된다.
- 중복: `MONTHLY_MA24_DISTANCE`와 0.86이다. 최근 상승 속도 정보는 이격 지표가 이미
  상당 부분 담는다.
- 역할: 수익률 백분위는 가격 수준이 아니라 최근 상승 속도를 본다. 장기 사이클 안의
  위치를 보는 Pattern B의 핵심 질문과 거리가 있다.

주의점: 하단 역전은 DEEP 2개, HIGH-only DEP 1개라 약한 근거다. 결정은 상단 포화와
낮은 정렬을 근거로 한다.

다음 단계 영향: 상태 규칙 입력에서 제외한다.

### `36M_HIGH_DRAWDOWN` — DROP

근거:
- 정렬: Spearman 0.788 / 0.855, median 4구간 모두 기대 방향이다.
- 경계: NORM–OVH가 겹치지 않고 OVH–EXT만 겹친다.
- 견고성: HIGH-only에서 상관이 오른다.
- 중복: `36M_RANGE_POSITION`과 0.957로 7개 중 가장 높은 쌍이다. 같은 36개월 창의 최고가를
  기준으로 삼으므로, 범위 위치가 이미 이 정보를 포함하고 저점 기준 정보도 더한다.
- 역할: 고점(H36)과의 거리만 재므로 현재 가격이 저점에 얼마나 가까운지는 알지 못한다.
  범위 위치는 같은 H36에 저점(L36)을 더해 이 정보까지 담는다.

주의점: 단독 성능은 나쁘지 않다. 제외 이유는 성능 부족이 아니라 범위 위치와의 중복이다.
NORM–OVH 분리는 범위 위치보다 낫다는 점을 기록해 둔다.

다음 단계 영향: 상태 규칙 입력에서 제외한다.

### `52W_RANGE_POSITION` — KEEP

근거:
- 정렬: Spearman 0.684 / 0.778, median 4구간 모두 기대 방향이다.
- 경계: 주봉 Feature 중 유일하게 NORM–OVH가 겹치지 않는다(0.271~0.700과 0.743~0.834).
  OVH–EXT만 겹친다.
- 견고성: HIGH-only에서 상관이 0.094 오르고 순서도 유지된다. 다만 HIGH-only 상승 폭은
  제외한 두 주봉 Feature(+0.109, +0.122)가 더 크므로, 이 항목은 52W를 고르는 근거가
  아니다. 선택 근거는 위의 NORM–OVH 분리다.
- 중복: `36M_RANGE_POSITION`과 0.81로 월봉 핵심과 겹치는 정도가 상대적으로 낮다.
  `WEEKLY_MA40_DISTANCE`와 0.879다.
- 역할: 월봉 36개월 범위보다 짧은 최근 1년 범위 안의 위치를 보여 주는 주봉 보조 지표다.

주의점: OVH와 EXT를 나누지 못한다(EXT median 0.840, IQR 0.676~0.899). 상단 극단의
구분은 `MONTHLY_MA24_DISTANCE`에 맡긴다.

다음 단계 영향: 현재 V01 산식을 그대로 상태 규칙 설계의 입력으로 쓴다.

### `WEEKLY_MA40_DISTANCE` — DROP

근거:
- 정렬: Spearman 0.649 / 0.758, median 4구간 모두 기대 방향이다.
- 경계: DEP–NORM, NORM–OVH, OVH–EXT 세 구간에서 IQR이 겹친다.
- 견고성: HIGH-only에서 상관이 오르지만 경계 겹침은 남는다.
- 중복: `52W_RANGE_POSITION`과 0.879, `26W_RETURN_HISTORICAL_PERCENTILE`과 0.929다.
- 역할: 확장 강도는 월봉 `MONTHLY_MA24_DISTANCE`가 이미 맡는다. 주봉 보조 역할은
  경계 분리가 더 나은 `52W_RANGE_POSITION` 하나로 충분하다.

주의점: 개념 자체가 틀렸다는 뜻은 아니다. 주봉 보조 Feature를 늘리지 않기 위한 단순화다.

다음 단계 영향: 상태 규칙 입력에서 제외한다.

### `26W_RETURN_HISTORICAL_PERCENTILE` — DROP

근거:
- 정렬: Spearman 0.546 / 0.668로 7개 중 가장 낮다.
- 경계: DEP–NORM, NORM–OVH, OVH–EXT 세 구간에서 IQR이 겹친다. OVH와 EXT의 median
  차이는 0.672뿐이다.
- 견고성: HIGH-only에서 DEP→NORM이 역전된다(HIGH-only DEP 1개라 약한 근거).
- 중복: `WEEKLY_MA40_DISTANCE`와 0.929다.
- 역할: 수익률 백분위는 최근 상승 속도를 보며, 가격 수준 위치를 보는 Pattern B 질문과
  거리가 있다.

주의점: 최근 상승 속도 개념이 이후 다른 목적으로 필요해지면 별도 연구로 다룬다.

다음 단계 영향: 상태 규칙 입력에서 제외한다.

## 5. Feature 구성

| 결정 | Feature |
|---|---|
| `KEEP` | `36M_RANGE_POSITION`, `MONTHLY_MA24_DISTANCE`, `52W_RANGE_POSITION` |
| `MODIFY` | 없음 |
| `DROP` | `12M_RETURN_HISTORICAL_PERCENTILE`, `36M_HIGH_DRAWDOWN`, `WEEKLY_MA40_DISTANCE`, `26W_RETURN_HISTORICAL_PERCENTILE` |

KEEP Feature의 역할:

- **월봉 핵심**
  - `36M_RANGE_POSITION`: 장기 범위 안에서 현재 위치(침체·과열 양쪽)
  - `MONTHLY_MA24_DISTANCE`: 장기 추세 평균 대비 확장·침체 강도
- **주봉 보조**
  - `52W_RANGE_POSITION`: 최근 1년 범위 안에서 현재 위치

`MODIFY`는 두지 않았다. 제외한 4개 중 두 수익률 백분위는 Pattern B 질문과 개념 거리가
있고, 나머지 두 개는 유지한 Feature와 중복돼 V02 수정 연구를 열 근거가 약하다.

KEEP 3개 중 OVH–EXT 구간의 IQR이 겹치지 않는 Feature는 `MONTHLY_MA24_DISTANCE`뿐이다.
`36M_RANGE_POSITION`과 `52W_RANGE_POSITION`은 이 구간에서 겹친다.

KEEP Feature를 서로 결합한 점수는 만들지 않았다.

## 6. 표본 한계

- 36개는 12종목 × 기준일 3개라 같은 종목 표본끼리 독립이 아니다.
- DEEP 2개, DEP 4개(HIGH-only 1개)라 하단 구간의 순서와 겹침은 불안정하다.
- Feature 선택과 다음 단계의 상태 규칙 설계가 같은 36개 표본을 쓰게 된다. 상태 규칙을
  확정하기 전에, 이번 표본과 겹치지 않는 별도 검증 표본(holdout)으로 확인해야 한다.

## 7. 다음 단계

KEEP Feature 3개로 Pattern B 5단계 상태(`DEEP_DEPRESSED`~`EXTREME_OVERHEATED`) 규칙
구조를 연구한다. 임계값과 판정 규칙은 그 단계에서 처음 다룬다.
