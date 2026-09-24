# Pattern B 운영 계약 V02

> 상태: 현재 기준. [운영 계약 V01](production_contract_v01.md)의 입력, 평가 상태
> (`READY`·`UNAVAILABLE`), 5개 Pattern B 상태, 오류, 결과 필드를 그대로 유지하고, 운영 정책 두
> 가지만 더한다. V01은 역사 기록으로 남긴다. 새 산식·임계값·상태는 없으며, 상태 판정은 여전히
> `evaluate_pattern_b`(지표 계약 V01 + 상태 판정 규칙 V02)만 한다. 일일 갱신·웹 연결은 이 계약의
> 범위가 아니다.

구현: `src/trend_scanner/patterns/pattern_b_operational.py` (Pattern B 전용).
Repository V2, rolling authority, 모집단 공용 코드는 바꾸지 않았다.

## 1. V01에서 그대로인 것

- 평가 상태 `READY`·`UNAVAILABLE`과 판정 조건 (유지 지표 3개로만 판단)
- `pattern_b_state`: `READY`면 5개 상태 중 하나, `UNAVAILABLE`이면 `null`
- 잘못된 입력은 예외 (`PatternBFeatureInputError`, 규칙 V02의 `ValueError`)
- V01 결과 필드와 버전 필드 (`feature_contract_version="V01"`,
  `state_rule_version="PATTERN_B_STATE_RULE_V02"`)
- 가격 출처 `MarketDataRepositoryV2`. 기준일 이후 행 없음

## 2. 정책 A — 시장 이전 가격 이력 연속성

기준일의 활성 COMMON 종목 구간에서 시작해 이전 구간을 거꾸로 확인한다. 이전 구간은 아래를 모두
만족할 때만 연결한다.

- 종목코드가 같다.
- `isu_cd`가 같다.
- 두 구간 모두 COMMON이다.
- 두 구간 모두 KOSPI 또는 KOSDAQ이고, 시장이 KOSPI ↔ KOSDAQ로 바뀌었다.
- 이전 구간 `effective_to`의 다음 KRX 거래일이 현재 구간 `effective_from`이다.
  그래서 두 구간 사이에 다른 구간이 끼어들 수 없다.

연결된 구간에서 같은 확인을 반복하며, 연속된 시장 이전 사슬만 연결한다. 다음은 연결하지 않고
사슬을 멈춘다.

| 멈춤 사유 | 뜻 |
|---|---|
| `GAP` | 거래일 공백 (수년 뒤 재상장 포함) |
| `ISU_CHANGE` | `isu_cd`가 다름 |
| `NON_COMMON` | COMMON이 아닌 구간 |
| `SAME_MARKET` | 연속이지만 시장 이전이 아님 |

- 활성 구간과 겹치는 구간이 있거나, 같은 날 끝나는 이전 구간이 둘 이상이면 판단하지 않고
  실패한다(`PatternBHistoryError`).
- 가격 로딩: 연결된 구간마다 자기 날짜 범위로 따로 조회한다. 활성 구간은 기준일까지다.
  `RepositoryV2DailyLoader`로 읽으므로 Repository V2의 기존 종목 구간 제한을 매번 그대로 거친다.
  결과는 날짜순으로 이어 붙인다.
- 이어 붙인 뒤 다음을 확인하고, 하나라도 어기면 실패한다.
  - 모든 행이 자기 구간 범위 안에 있다.
  - 날짜 중복이 없다.
  - 날짜가 오름차순이다.
  - 출처가 모두 `MarketDataRepositoryV2`다.
- 구간 중 하나라도 저장소에서 데이터를 얻지 못하면 전체를 데이터 없음으로 본다. 일부 구간만
  쓰지 않는다.

Repository V2의 종목 구간 제한은 같은 `isu_cd`의 구간을 공백과 무관하게 하나로 묶는다. 정책 A는
이보다 좁아서, 연속된 시장 이전만 연결한다.

추가 결과 필드:

| 필드 | 내용 |
|---|---|
| `history_effective_from` | 연결한 가격 이력의 시작일 |
| `history_segment_count` | 사용한 구간 수 (연결 없으면 1) |
| `market_transfer_stitched` | 이전 구간을 연결했는지 |

활성 구간의 `market`, `isu_cd`, `identity_effective_from`, `identity_effective_to`는 따로 그대로
보존한다.

## 3. 정책 B — 가격 신선도

신선도(`freshness_status`)는 Pattern B 상태와 따로 둔다.

- `expected_weekly_bar`: 지표 계약 V01의 완료 주봉(`W-FRI`) 규칙에서 기준일 이하 최신 완료 주봉의
  날짜 표시. 즉 기준일 이하 가장 최근 금요일이다.
- `weekly_last_bar == expected_weekly_bar`이면 `CURRENT`다.
- `weekly_last_bar`가 없거나 그보다 이르면 `STALE`이다.

규칙:

- `STALE`은 여섯 번째 Pattern B 상태가 아니고 `UNAVAILABLE`도 아니다.
- `READY` + `STALE`이 가능하며, 이때 Pattern B 상태는 그대로 둔다.
- 이번 단계에서 `STALE` 종목을 지우거나 상태를 바꾸지 않는다.
- 한 주 내내 휴장이면 그 주는 모든 종목이 `STALE`이 된다. 그대로 두고 따로 처리하지 않는다.

앞으로 일일 갱신·웹을 연결할 때의 원칙 (구현은 이번 범위 밖):

- 현재 상태 목록·순위에서는 `STALE`을 `CURRENT`처럼 다루지 않는다.
- 상세 화면에서는 Pattern B 상태와 마지막 봉 날짜를 함께 보여 줄 수 있다.

## 4. 범위 밖

- 일일 갱신·웹 연결
- Repository V2 종목 구간 제한 변경
- 전략, 매매 신호, 백테스트
