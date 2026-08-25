krx_historical_backfill_v01.md

======================================================================
KRX Historical Backfill V01
======================================================================

목적
----------------------------------------------------------------------

KRX Open API의 일별매매정보를 조정하지 않은 raw authority로 보존한다.
이번 phase의 natural unit은 `market + basDd` whole-market snapshot이며,
저장 단위는 ticker 파일이 아닌 `market/year/date.parquet` immutable partition이다.

범위와 비범위
----------------------------------------------------------------------

- KOSPI `/sto/stk_bydd_trd`, KOSDAQ `/sto/ksq_bydd_trd`를 기존
  `KrxOpenApiClient`와 `LocalKrxOpenApiQuota`로 호출한다.
- `OutBlock_1`의 `BAS_DD`, `ISU_CD`, OHLC, 거래량/거래대금/시가총액/LIST_SHRS를
  frozen `KRX_RAW_STOCK_V01` schema로 매핑한다.
- raw OHLC 보정, adjusted 계산, phantom filtering, instrument filtering,
  Basic Info 일별 호출, PARVAL backfill, consumer migration은 수행하지 않는다.
- historical LIST_SHRS를 `CorporateActionStateStore`에 replay하거나 DIRTY refresh를
  발생시키지 않는다.

raw provider contract
----------------------------------------------------------------------

physical columns는 정확히 다음 순서다.

----------------------------------------------------------------------
| date | ticker | open | high | low | close | volume | trading_value | market_cap | listed_shares |
----------------------------------------------------------------------

`ISU_CD`는 이번 daily endpoint에서 이미 6자리 ticker 의미이므로 그대로 엄격히
검증한다. `BAS_DD`는 요청 `basDd`와 모든 row가 일치해야 한다. HTTP status,
records root, required source field, numeric parse, ticker 형식, duplicate ticker,
음수 값은 fail closed한다. raw zero row는 보존하고 1원 보정이나 source 값 수정은
하지 않는다. OHLC relation은 모든 OHLC가 positive인 경우에만 검증한다.

raw store contract
----------------------------------------------------------------------

기본 root:

`data/market/raw/krx_stocks/v01/`

partition:

`market=KOSPI/year=YYYY/YYYY-MM-DD.parquet`

`market/date`가 한 번 COMPLETE되면 일반 backfill에서 overwrite하지 않는다.
동일 canonical content는 `IDEMPOTENT_NOOP`, 다른 content는
`RAW_PARTITION_CONFLICT`다. manifest는 같은 root의 `manifest.sqlite3`이며
`COMPLETE`, `NO_DATA`, `FAILED` 상태와 source endpoint, row count,
`content_sha256`, `file_sha256`를 보존한다. parquet write → read-back validation →
hash → atomic replace → manifest transaction 순서를 지킨다. manifest commit 실패
시 새로 만든 파일만 rollback하며 기존 valid partition은 삭제하지 않는다.

`load_ticker()`는 KOSPI/KOSDAQ 두 market을 모두 검색하고 date 순으로 반환한다.
동일 `(date, ticker)`가 두 market에 있으면 `CROSS_MARKET_TICKER_CONFLICT`로
fail closed한다.

backfill runner contract
----------------------------------------------------------------------

candidate date는 `pd.bdate_range()`의 평일 scheduler일 뿐 KRX trading calendar가
아니다. 매 date에 KOSPI와 KOSDAQ을 순차 호출한다. 두 응답이 모두 empty이고
현재 KST 기준 2일 finalization lag를 지난 경우에만 양쪽을 `NO_DATA`로 확정한다.
한쪽만 empty면 `ASYMMETRIC_EMPTY_SNAPSHOT`으로 실패하며, 최근 양쪽 empty는
`RECENT_EMPTY_NOT_FINAL`로 남기고 NO_DATA checkpoint를 만들지 않는다.

`resume`은 integrity-valid COMPLETE/NO_DATA를 API 호출 없이 skip한다. FAILED는
`--retry-failures`에서 재시도한다. 모든 HTTP attempt는 기존 quota의
`reserve_attempt()`를 거치며 market request는 병렬화하지 않는다. task budget,
quota exhaustion은 기존 valid partition을 보존한 채 `BACKFILL_PAUSED_TASK_BUDGET`
또는 `BACKFILL_PAUSED_QUOTA`로 종료하고 다음 invocation에서 resume한다.

production target
----------------------------------------------------------------------

V01 target은 2010-01-04부터 2026-08-21까지다. 완료 gate는 각 weekday candidate가
양쪽 COMPLETE 또는 양쪽 finalized NO_DATA이고, FAILED/partial/unexplained
missing candidate가 0인 것이다. raw parquet와 manifest는 Git에 commit하지 않는다.

validation modes
----------------------------------------------------------------------

- `--offline`: synthetic provider/store contract와 신규 테스트, network=0.
- `--live-pilot`: 2018-04-27, 2018-05-04, 2026-08-21의 양 market만 bounded 호출.
- `--production-coverage`: network 없이 현재 local raw store의 manifest, hash, schema,
  date/path, duplicate와 cross-market key를 검사한다.

provenance
----------------------------------------------------------------------

FIX START HEAD는 accepted previous phase가 main에 fast-forward된
`3a87e780981491fcd2bfaf63b4f933513924b3b6`이다. Commit A에서 implementation과
offline/live/coverage validation을 실행하고, Commit B에는
`artifacts/data/krx_historical_backfill/v01/`만 기록한다.

현재 phase가 Architect 승인 전에는
`READY_FOR_ARCHITECT_KRX_HISTORICAL_BACKFILL_V01_REVIEW`를 사용하며,
`KRX_HISTORICAL_BACKFILL_V01 = CLOSED`를 선언하지 않는다.
