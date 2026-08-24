corporate_action_dirty_refresh_v01.md

======================================================================
Corporate Action Dirty Refresh V01
======================================================================

상태
----------------------------------------------------------------------

이 문서는 adjusted history가 authority 변화로 stale일 가능성이 있을 때
이를 감지하고 안전하게 full refresh하는 primitive 계약을 정의한다.
이번 phase의 최종 상태는
`READY_FOR_ARCHITECT_CORPORATE_ACTION_DIRTY_REFRESH_V01_REVIEW`이며,
Architect 승인 전에는 `CORPORATE_ACTION_DIRTY_REFRESH_V01 = CLOSED`로
선언하지 않는다.

범위와 비범위
----------------------------------------------------------------------

- `LIST_SHRS`와 `PARVAL`의 point-in-time snapshot을 비교한다.
- detector는 refresh 필요성만 판단하고 corporate-action 종류를 분류하지 않는다.
- `CorporateActionStateStore`는 SQLite transaction으로 dirty/refresh 상태를 관리한다.
- `CorporateActionRefreshService`는 `AdjustedPriceDataProvider`와
  `AdjustedPriceStore`를 주입받아 dirty ticker의 retained full history를 교체한다.
- 기존 `AdjustedPriceStore`가 없는 ticker는 initial backfill하지 않는다.
- KRX raw fetch, historical backfill, production consumer 전환, custom adjustment
  formula와 event taxonomy는 다음 phase 또는 별도 범위다.

1. Detector contract
----------------------------------------------------------------------

`CorporateActionSnapshot`의 필수 입력은 canonical six-digit `ticker`, calendar
`as_of`, 0보다 큰 integer-compatible `listed_shares`다. `par_value`는 optional
numeric이며 missing은 허용하지만 음수와 파싱 실패는 거부한다.

비교 순서는 `previous.as_of < current.as_of`여야 한다. 동일 날짜의 동일 값은
idempotent observation으로 처리하고, 동일 날짜의 다른 authority 값은
`SOURCE_CONFLICT`로 fail closed한다. 역순은 `OUT_OF_ORDER`로 거부한다.

dirty primary signal은 동일 semantic namespace 안에서 normalized `LIST_SHRS`의 실제 변화다. `PARVAL`은
corroborating signal이며 양쪽 값이 모두 존재할 때만 비교한다. 따라서 missing
PARVAL만으로는 dirty를 선언하지 않지만 LIST_SHRS 변화는 항상 dirty다.

`RAW_DAILY_LISTED_SHARES`와 `MASTER_SNAPSHOT_LISTED_SHARES`처럼
`listed_shares_semantics`가 다르면 값을 비교하지 않고
`SOURCE_SEMANTIC_CONFLICT`로 fail closed한다. `source_name`은 audit provenance이며
동일 semantic이면 서로 달라도 비교를 허용한다.

dirty reason은 다음 factual evidence만 사용한다.

----------------------------------------------------------------------
| 조건                                      | reason                              |
----------------------------------------------------------------------
| LIST_SHRS만 변화                          | LISTED_SHARES_CHANGED               |
| PARVAL만 변화                             | PAR_VALUE_CHANGED                   |
| LIST_SHRS와 PARVAL 모두 변화              | LISTED_SHARES_AND_PAR_VALUE_CHANGED |
----------------------------------------------------------------------

가격 gap, 수익률 jump, volume spike, OHLC discontinuity와 ratio threshold는
V01 detector signal이 아니다. split, reverse split, rights, dividend 등
event type을 출력하거나 OHLC를 직접 조정하지 않는다.

2. State store contract
----------------------------------------------------------------------

runtime state의 기본 경로는 `data/market/state/corporate_action.sqlite3`다.
`artifacts/`에는 runtime database를 저장하지 않는다. current-state의 핵심
필드는 다음과 같다.

`ticker`, `as_of`, `status`, `dirty_reason`, `last_success_at`,
`last_attempt_at`, `dirty_since`, `last_error`, `updated_at`,
`last_content_sha256`, `refresh_requested_start`, `refresh_requested_end`,
`listed_shares`, `par_value`, `listed_shares_semantics`, `source_name`.

status enum은 정확히 `CLEAN`, `DIRTY`, `REFRESHING`, `FAILED`다. 상태 변경과
refresh claim은 SQLite `BEGIN IMMEDIATE` transaction으로 수행한다. 같은 ticker의
동시 claim은 compare-and-set으로 하나만 성공하며, transition log는
`corporate_action_transition_log`에 append한다.

허용 transition
----------------------------------------------------------------------

ABSENT -> CLEAN / DIRTY
CLEAN -> CLEAN / DIRTY
DIRTY -> DIRTY / REFRESHING
FAILED -> DIRTY / REFRESHING
REFRESHING -> CLEAN / FAILED

`DIRTY -> CLEAN`, `FAILED -> CLEAN`은 성공적인 refresh 없이 허용하지 않는다.
clean observation이 들어와도 DIRTY와 FAILED는 latch를 유지한다. `evaluate_and_record()`는
`BEGIN IMMEDIATE` 안에서 persisted snapshot read, detector evaluation, state write와
transition log를 수행하며 persisted `as_of`는 절대 감소하지 않는다. REFRESHING 중
새 authority observation은 `OBSERVATION_DURING_REFRESH`로 fail closed하고 state row를
변경하지 않는다. refresh 종료 후 caller가 observation을 재제출한다.

관찰값을 기록하는 canonical production entrypoint는 `evaluate_and_record(snapshot)`다.
기존 호환성을 위해 `record_observation(snapshot, decision)`을 유지하더라도
`CorporateActionDecision`은 persisted state를 직접 갱신하는 authority가 아니다.
public method는 transaction 안에서 현재 persisted snapshot과 incoming snapshot으로
`CorporateActionDetector.evaluate()`를 다시 호출하고, caller decision의 모든 필드와
canonical decision을 exact compare한 뒤에만 private writer를 호출한다. 불일치 시
`DECISION_MISMATCH`로 거부하며, semantic namespace 충돌과 날짜 순서 invariant는
재계산된 detector 결과를 통해 동일하게 fail closed한다. 따라서 외부 caller가 fake
CLEAN, fake DIRTY 또는 dirty reason을 주입해 state를 우회할 수 없다.

3. Refresh contract
----------------------------------------------------------------------

`CorporateActionRefreshService`는 `CorporateActionStateStore`,
`AdjustedPriceDataProvider`, `AdjustedPriceStore`를 dependency injection으로
받는다. refresh 호출 하나는 logical `AdjustedPriceDataProvider.load_daily()`
1회만 수행하며 legacy `PyKrxDataProvider`를 사용하지 않는다.

정확한 순서:

1) DIRTY 또는 FAILED를 REFRESHING으로 atomic claim
2) 기존 AdjustedPriceStore pair와 metadata load
3) metadata `requested_start`를 full-history 시작점으로 사용하고 없으면
   `actual_date_min` fallback
4) caller의 `refresh_end`를 사용하되 기존 `actual_date_max`보다 이전이면 거부
5) adjusted=True provider fetch
6) typed empty, schema, OHLC 검증
7) 기존 모든 trading date가 새 frame에 존재하는지 subset 검증
8) new actual min <= old actual min, new actual max >= old actual max 검증
9) allowlist metadata context로 `AdjustedPriceStore.save_full()` full replacement
10) reload, metadata/hash integrity 검증
11) 전부 성공한 뒤에만 REFRESHING -> CLEAN

기존 store가 없으면 provider fetch 없이 `ADJUSTED_STORE_MISSING`으로 FAILED가
된다. empty response는 `EMPTY_REFRESH_RESPONSE`, 기존 날짜 하나라도 빠진
response는 `PARTIAL_REFRESH_RESPONSE`로 FAILED가 된다. 실패 시 기존 valid
parquet/metadata pair를 보존하고 `last_error`를 기록한다. 단순 row count 비교는
coverage 검증으로 사용하지 않는다.

hash가 refresh 전후 동일해도 실패가 아니다. dirty evidence가 false positive였을
가능성을 허용하며 refresh 전체가 성공했다면 CLEAN으로 전환한다.

4. Recovery
----------------------------------------------------------------------

process crash로 REFRESHING이 남으면 다음 실행의 explicit recovery가 stale
REFRESHING을 `INTERRUPTED_REFRESH` 사유의 FAILED로 전환한다. FAILED는 caller가
다시 claim하여 retry할 수 있지만 service 내부 무한 retry는 수행하지 않는다.

5. Authority와 production boundary
----------------------------------------------------------------------

Adjusted OHLC authority는 계속 `PyKRX adjusted=True`다. 이번 phase는
`LIST_SHRS`/`PARVAL` 값을 입력으로 받는 순수 dirty primitive만 구현하며 KRX
Open API, OpenDART, legacy cache, production consumer를 변경하지 않는다.
`source_contracts.py`, `adjusted_price_provider.py`, `adjusted_price_store.py`도
frozen architecture 파일로 재수정하지 않는다.

6. Validation evidence
----------------------------------------------------------------------

FIX02 validator의 provenance 시작 HEAD는
`f6afc9d5888b2316606bc8ccc986b2c12ea1f477`로 고정한다. validator는 detector cases,
public observation decision mismatch, state transition matrix, dirty latch, concurrent
claim, interrupted recovery, successful/failed/partial/empty/missing-store
refresh를 offline에서 검증한다. live mode는 optional이며 temporary Store만
사용한다. 필수 artifact는 다음과 같다.

- `corporate_action_dirty_refresh_v01_summary.json`
- `corporate_action_dirty_refresh_v01_manifest.json`
- `detector_contract.json`
- `state_store_contract.json`
- `state_transition_matrix.json`
- `refresh_contract.json`
- `samsung_split_evidence.json`
- `refresh_integrity_summary.json`
- `corporate_action_dirty_refresh_recommendation.md`
- live mode에서만 `live_refresh_smoke.json`

runtime SQLite database와 validation parquet는 commit하지 않는다.
