# Pattern B 상태 판정 규칙 V02

> 상태: 구현·봉인 완료. [규칙 V02 연구 V01](state_rule_v02_research_v01.md)에서 고른 후보
> A1/B0를 그대로 옮겼다. 아래 수치는 **개발 표본 성능**이며 별도 검증 표본 성능이 아니다.
> 전략·매매 규칙·백테스트는 없다.

## 1. 규칙 계약

코드: `src/trend_scanner/patterns/pattern_b_state_v02.py`
(`classify_pattern_b_state_v02(range_36m, monthly_ma24_distance, range_52w)`)

- 지표: [규칙 V01](state_rule_v01.md)과 같은 유지 지표 3개
  - 월봉 핵심: `36M_RANGE_POSITION`, `MONTHLY_MA24_DISTANCE`
  - 주봉 보조: `52W_RANGE_POSITION`
- 출력 상태: `DEEP_DEPRESSED`, `DEPRESSED`, `NORMAL`, `OVERHEATED`, `EXTREME_OVERHEATED`
- 임계값: 규칙 V01과 같다. 각 임계값은 위쪽 상태의 하한이다(값이 같으면 위쪽 band).

| 지표 | DEP 하한 | NORMAL 하한 | OVH 하한 | EXT 하한 |
|---|---|---|---|---|
| `36M_RANGE_POSITION` | 0.05 | 0.25 | 0.55 | 0.80 |
| `MONTHLY_MA24_DISTANCE` | −0.35 | −0.10 | 0.15 | 0.50 |
| `52W_RANGE_POSITION` | 0.15 | 0.25 | 0.70 | 0.80 |

판정 순서(36M=`m36`, MA24=`ma24`, 52W=`w52` band):

1. 세 값을 각각 band 0~4로 바꾼다. 값이 유한한 숫자가 아니면 오류를 낸다.
2. **(V02 변경)** `m36`이 `DEEP_DEPRESSED`이고 `ma24`가 `DEPRESSED` 이하이면
   `DEEP_DEPRESSED`로 끝낸다.
3. 그 밖에는 규칙 V01과 같다.
   - `m36`을 주 상태로 둔다.
   - 극단 주 상태는 `ma24`도 같은 극단이어야 하고, 아니면 NORMAL 쪽으로 한 단계 물러난다.
   - NORMAL이 아닌 상태는 `ma24` 또는 `w52`가 같은 쪽에 있어야 하고, 아니면 NORMAL이다.

코드는 규칙 V01의 band 함수·임계값·결합 함수를 그대로 가져다 쓰고, 2번 분기 하나만 더한다.

## 2. V01과의 차이

125개 band 조합 중 결과가 다른 조합은 5개뿐이다: `m36`=DEEP, `ma24`=DEP (`w52`는 무관).
V01은 `DEPRESSED`, V02는 `DEEP_DEPRESSED`를 낸다.

그대로인 부분:

- 36개월 침체·NORMAL 경계 0.25, MA24·52W 임계값
- 과열 쪽 로직 전체 (`EXTREME_OVERHEATED`는 여전히 두 월봉이 모두 극단일 때만)
- NORMAL이 아닌 상태의 같은 쪽 확인 단계
- `m36`이 DEEP이 아닌 모든 경우

V02에서 `DEEP_DEPRESSED`는 `m36`이 DEEP이고 `ma24`가 침체 쪽(DEEP 또는 DEP)일 때만 나온다.
두 월봉이 모두 극단일 필요는 없다.

[사람 판정 기준 V02](human_ground_truth_criteria_v02.md)는 `DEEP_DEPRESSED`를 "현재 가격
자체가 장기 사이클의 하단 극단에 있고, 월봉에서 장기간 눌려 있으며, 주봉도 현재 저점권의
극단성을 보조로 확인하는 상태"로 본다. V02는 앞의 두 조건(36M 하단 극단, MA24 침체 쪽)만
요구하고 주봉 확인은 요구하지 않는다. 주봉 확인을 더한 후보 A2는 개발 표본에서 결과가
A1과 같아, 조건이 적은 A1을 골랐다.

## 3. 개발 표본 V02 성능 (36개)

입력: 봉인된 [개발 표본 V02 사람 판정](development_v02_human_labels.md)과
[개발 표본 원시 지표값](development_v02_feature_raw_values_v01.csv).

| 규칙 | 정확 일치 | 1단계 이내 | 순서 MAE | 2단계 이상 | 3단계 이상 | DEEP 정확 일치 |
|---|---|---|---|---|---|---|
| V01 | 17/36 | 35/36 | 0.5556 | 1 | 0 | 3/11 |
| V02 | 22/36 | 35/36 | 0.4167 | 1 | 0 | 9/11 |

높은 신뢰도 35개만 보면 V02는 정확 일치 22/35, MAE 0.3714다.

혼동 행렬 (V02, 행 사람, 열 자동):

| 사람 \ 자동 | DEEP | DEP | NORM | OVH | EXT |
|---|---|---|---|---|---|
| `DEEP_DEPRESSED` | 9 | 1 | 1 | 0 | 0 |
| `DEPRESSED` | 1 | 5 | 6 | 0 | 0 |
| `NORMAL` | 0 | 1 | 6 | 1 | 0 |
| `OVERHEATED` | 0 | 0 | 2 | 2 | 0 |
| `EXTREME_OVERHEATED` | 0 | 0 | 0 | 1 | 0 |

V01 대비 예측이 바뀐 표본은 7개이며, 모두 `DEPRESSED` → `DEEP_DEPRESSED`다.

| sample_id | 사람 판정 | 36M | MA24 | 52W | V01 | V02 |
|---|---|---|---|---|---|---|
| `PBDEV2_005` | `DEEP_DEPRESSED` | 0.013 | −0.268 | 0.013 | `DEPRESSED` | `DEEP_DEPRESSED` |
| `PBDEV2_011` | `DEEP_DEPRESSED` | 0.047 | −0.310 | 0.138 | `DEPRESSED` | `DEEP_DEPRESSED` |
| `PBDEV2_024` | `DEEP_DEPRESSED` | 0.042 | −0.264 | 0.167 | `DEPRESSED` | `DEEP_DEPRESSED` |
| `PBDEV2_025` | `DEPRESSED` | 0.012 | −0.253 | 0.093 | `DEPRESSED` | `DEEP_DEPRESSED` |
| `PBDEV2_026` | `DEEP_DEPRESSED` | 0.040 | −0.210 | 0.350 | `DEPRESSED` | `DEEP_DEPRESSED` |
| `PBDEV2_030` | `DEEP_DEPRESSED` | 0.044 | −0.188 | 0.016 | `DEPRESSED` | `DEEP_DEPRESSED` |
| `PBDEV2_033` | `DEEP_DEPRESSED` | 0.023 | −0.315 | 0.207 | `DEPRESSED` | `DEEP_DEPRESSED` |

6개는 고쳐졌고 `PBDEV2_025` 1개는 새 오류다.

## 4. 한계

- 규칙 V02는 같은 개발 표본 36개로 후보를 고르고 성능을 쟀다. 이 수치는 낙관적이다.
- `DEPRESSED` → `NORMAL` 6개는 그대로다. 36개월 경계를 바꾼 후보(B1·B2)는 순이득이 없어
  넣지 않았다.
- 과열 쪽은 개발 표본이 적어(OVH 4, EXT 1) 검토하지 않았고 V01 그대로다.
- `PBDEV2_019`(사람 `DEEP_DEPRESSED`/`MEDIUM`, 자동 `NORMAL`)는 판정이 모호한 참고
  사례로만 남긴다.
- [별도 검증 표본 V02](holdout_v02_protocol.md)는 규칙 V01 평가에 이미 썼으므로 V02
  평가에 쓰지 않는다.

## 5. 봉인

이 문서, `src/trend_scanner/patterns/pattern_b_state_v02.py`, 연구 V01 결과를
[state_rule_v02_seal.json](state_rule_v02_seal.json)의 SHA-256으로 봉인한다. 봉인 파일에는
개발셋 성능과 입력 파일(사람 판정, 원시 지표값, 사람 판정 기준 V02, 규칙 V01)의 SHA-256도
기록했다. 이후 규칙 V02를 고치면 새 버전으로 만든다.

## 6. 다음 단계

별도 검증 표본을 바로 만들지 않는다. 먼저 규칙 V02에 추가 사람 검증이 정말 필요한지
판단한다.

1. 사람 판정 없이 종료할 수 있는지 검토한다.
2. 꼭 필요할 때만 최대 16개의 가린 별도 검증 표본을 만든다.

이전 기록([지표 평가 V01](development_v02_feature_evaluation_v01.md),
[연구 V01](state_rule_v02_research_v01.md))에 적힌 "별도 검증 표본 V03 24개" 계획은
폐기했다.
