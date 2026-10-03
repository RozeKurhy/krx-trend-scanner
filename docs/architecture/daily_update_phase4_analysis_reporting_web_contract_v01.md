# 분석·리포트·웹 반영 기준 V01

## 1. 문서 역할

이 문서는 [데일리 업데이트 기준 V01](daily_update_contract_v01.md) §6.3이
정의한 4단계의 상세 계약이다. 4단계는 1~3단계가 같은 기준일로 인증한
입력을 받아 기존 스캐너, 공식 전략, COMMON Stock Report v0.7, ETF36 Julia V1
Stock Report v0.6 자동 생성, 웹 정적 투영을 일관되게 연결한다. 새 분석
엔진·산식·전략을 만드는 단계가 아니다. 개별 실행
결과와 검증 일지는 이 문서의 범위에 포함하지 않는다.

## 2. 입력 경계와 공통 기준일

4단계의 유일한 기준일은 호출자가 전달한 값 하나다.

```text
target_as_of = YYYY-MM-DD
```

4단계의 날짜 필드는 다음처럼 구분한다.

```text
requested_as_of
= 사용자가 요청한 분석 기준일
= target_as_of

reference_market_date
= 1단계가 인증한 target_as_of 이하의 실제 시장 기준 거래일
<= target_as_of
```

거래일에는 두 값이 같을 수 있다. 주말·휴장일 `target_as_of`는 정상 입력이며,
이 경우 `requested_as_of`는 요청 날짜를 유지하고
`reference_market_date < target_as_of`가 정상일 수 있다. 요청 기준일을 가까운
거래일로 다시 기록하지 않는다.

4단계는 동일한 `target_as_of`에 대해 1~3단계가 `PASS` 또는
`NOOP_ALREADY_COMPLETE` 상태인지 먼저 확인한다. 이 계약은 1~3단계의
원천, Repository V2, 주봉·월봉, 수급, 펀더멘털, 시장·업종 RS 또는 섹터
구성의 정확성을 다시 수집·계산·검증하지 않는다.

다음 값은 `target_as_of`를 대신할 수 없다.

- 시스템 날짜·실행 시각 또는 오늘 날짜
- 파일·디렉터리·웹 JSON의 가장 최신 날짜
- 스캐너·리포트의 이전 실행 산출물 날짜
- 웹 화면이 현재 표시하는 날짜

필수 입력의 `requested_as_of`가 `target_as_of`와 다르거나,
`reference_market_date`가 1단계 인증 시장 권위의 실제 기준 거래일과 다르면
4단계는 `BLOCKED`다. 비거래일에 두 날짜가 다르다는 사실만으로는 차단하지
않는다. 일부만 새 날짜인 결과를 `PASS` 또는 최신 결과로 표시하지 않는다.

## 3. 재사용 경계와 입력

### 3.1 스캐너

`scan_pattern_a_universe()`는 `requested_as_of`와
`reference_market_date`를 요약에 기록하고, 운영 Repository V2와 rolling PIT
COMMON을 사용해 해당 기준일의 전체 KOSPI/KOSDAQ 보통주를 구성한다. 결과는
다음 기존 위치에 저장한다.

```text
artifacts/patterns/pattern_a/production/scanner/
  pattern_a_universe_scan_{YYYYMMDD}.csv
  pattern_a_universe_scan_{YYYYMMDD}_summary.json
```

4단계 운영 호출은 `target_as_of`와 1단계가 인증한
`reference_market_date`, Repository V2, PIT COMMON 유니버스를 명시적으로
전달한다. 시스템 날짜, 최신 파일 날짜, 생략 인자 대체 경로를 기준일로
사용하지 않는다.

### 3.2 공식 전략과 Stock Report

일반 종목의 공식 전략은 A FAST Core V2
(PATTERN_A_FAST_FINAL_STRATEGY_V02)와 B Select Core V1
(PATTERN_B_SELECT_CORE_V01)이다. A FAST Core V2가 기본 전략이자
CONTROL이고, B Select Core V1은 기본 전략·CONTROL이 아닌 독립 공식 전략이다.
ETF 전용 공식 전략은 Julia V1 (JULIA_ETF_STRATEGY_V01)이며 공식 ETF 36에만
적용한다. COMMON 4B 성공 뒤 같은 `target_as_of`와 4A가 확정한
`reference_market_date`로 ETF36 전용 Stock Report v0.6
(`official_strategy=JULIA_ETF_STRATEGY_V01`)을 자동 생성한다. 이 결과는
별도 artifact와 상태로 기록하고 Phase4D 종목 리포트 Web/UI 및 Strategy Monitor에
투영한다. ETF 결과는 Market RS·Sector RS·외인 랭킹과 COMMON 전략 모집단에
포함하지 않는다. 자동 주문은 승인되지 않았다.
A FAST Core V2는 의사결정 지원 운영
(PRODUCTION_DECISION_SUPPORT)이며 자동매매 권한이 아니다. V3/V4 또는
다른 비공식 후보 전략을 4단계 운영 출력에 추가하지 않는다.

`generate_stock_report()`와 `build_a_fast_core_section()`은
`requested_as_of` 이하의 입력을 사용한다. 리포트는 외국인 수급, 펀더멘털,
시장 RS와 A FAST Core V2를 기존 섹션으로 소비한다. v0.7은 v0.5에서 정의한
펀더멘털 섹션을 이어받아 이미 생성된 F2/F3/F4 결과를 주입받을 뿐 OpenDART를
호출하거나 필터를 다시 계산하지 않는다. 업종 RS는 3단계 업종 RS 순위
산출물을 소비하지 않는다. 리포트 생성기가 3단계에서 갱신한 업종 지수
캐시와 `requested_as_of`와 날짜가 정확히 같은 섹터 구성 스냅샷으로 직접
계산하며, 그 스냅샷이 없으면 업종 RS 섹션만 산출 불가(`DATA_UNAVAILABLE`)로
두고 리포트 생성은 계속한다.

Phase 4 COMMON 리포트는 Stock Report v0.7이며 출력 위치는 다음과 같다.

```text
artifacts/reporting/stock_reports/{YYYYMMDD}/
  *.md
  json/*.json
```

Official ETF 36 Julia V1 v0.6은 Phase 4E가 COMMON 4B 성공 뒤 자동 생성하며,
Phase4D 종목 리포트 Web/UI 투영에 사용한다.

```text
artifacts/reporting/etf_stock_reports/{YYYYMMDD}/
  *.md
  json/*.json
```

COMMON 리포트 생성은 `requested_as_of == target_as_of`와
`reference_market_date ==` 스캐너가 확정한 실제 시장 기준 거래일을 명시하고,
스캐너 결과를 유일한 후보 입력으로 소비한다. 리포트가 스캐너를 독립
재실행하거나 다른 기준 거래일·날짜 후보를 대체 경로로 사용하는 것은 허용하지
않는다.

ETF 리포트는 4A가 반환한 동일한 두 날짜를 명시적으로 전달받고 frozen ETF36을
대상으로 생성한다. COMMON 후보를 소비하거나 ETF universe를 다시 선정하지 않는다.

### 3.3 웹 정적 투영

`web/data/`는 표시용 정적 결과물이며 분석·전략·원천의 새 권위가 아니다.
현재 확인된 주요 투영 경로는 다음과 같다.

| 구분 | 입력 | 웹 출력 | 계약상 역할 |
|---|---|---|---|
| 종목 리포트 | 같은 날짜의 COMMON v0.7 + Official ETF36 v0.6, PIT 메타데이터, 정확한 일별 종가 | `stock-index.json`, `stocks/*.json` | 필수 구성 요소 |
| 마켓 RS | 공개 COMMON 종목 리포트 웹 전달 데이터 | `market-ranking.json` | 필수 구성 요소 |
| 전략 모니터 | A FAST·Julia 공개 리포트와 B Select current status | `strategy-monitor.json` v2 | A FAST·B Select COMMON 및 Julia ETF36을 전략별로 분리 |
| 섹터 RS | 업종 RS 권위, 메타데이터, COMMON 리포트 집합 | `sector-rs-ranking.json` | 필수 구성 요소 |
| 외인 순매수 | 외국인 수급, PIT COMMON 권위, 섹터 구성; `stock-index.json`은 리포트 보유 여부만 확인 | `foreign-net-buy-ranking.json` | 필수 구성 요소 |
| 웹 상태 | 시장·PIT·펀더멘털·리포트의 로컬 상태 | `health.json` | 필수 구성 요소 |
| 공포지수 | `artifacts/fear_index/research_v01/` 연구 산출물 | `fear-index.json` | 선택 보조 구성 요소 |
| ETF 랭킹 | 고정 ETF 메타데이터와 Repository V2 | `etf-ranking.json` | 선택 보조 구성 요소 |

`export_market_ranking_web.py`와 `export_strategy_monitor_web.py`는 Stock
Report 웹 전달 데이터를 입력으로 사용한다. 전체 stock-index와 파일 집합의 날짜·무결성을
확인한 뒤 Market RS는 COMMON만, Strategy Monitor는 A FAST·B Select의 COMMON과
Julia의 Official ETF36을 각각 독립 투영한다. B Select current status가 없거나 날짜·범위가
맞지 않으면 Phase4D는 실패 처리한다. ETF36은 COMMON Market RS 집계에 포함하지 않는다. 외인
순매수의 `stock-index.json` 사용은 보통주 모집단을 정하는
근거가 아니라 `report_available` 표시에만 한정된다.

대상 입력·출력은 모두 `requested_as_of == target_as_of`와 같은 실행의
`reference_market_date`를 명시하고, 혼합 날짜를 실패로 처리한다. 비거래일
target에서 두 날짜가 다른 것은 혼합 날짜가 아니다. `health.json`은
`market_data`, `universe`, `fundamentals`, `stock_reports` 네 영역의 상태를
합성하며 `analysis`와 `backtest`를 계약상 영역으로 포함하지 않는다.

공포지수 투영 스크립트와 ETF 투영 스크립트는 각각 승인된 연구 산출물과 Repository V2를
정적 웹 결과로 투영한다. 두 결과는 선택 보조 구성 요소이며 필수 구성 요소의
상태 합성에 포함하지 않는다.

## 4. 공식 처리 순서

```text
1~3단계의 동일 `target_as_of` 입력 인증
  → 4E 조율기
     → 4A 전체 PIT COMMON 스캐너
     → 4B A FAST Core V2 + Stock Report v0.7
     → ETF36 Julia V1 Stock Report v0.6 자동 생성 (4B 성공 후, 별도 상태)
     → 4C 필수 분석 표시 결과·B Select current status 생성 및 검증
     → 4D 같은 실행 status artifact 승격 및 COMMON v0.7 + ETF36 v0.6 Web/UI 정적 투영
     → 전체 상태 합성
```

4E 조율기는 4A~4D를 같은 `target_as_of`와 `reference_market_date`로 순서대로
호출하고 각 단계의 입력·출력을 검증한다. COMMON 4B가 성공하면 같은 날짜
권위로 ETF36 리포트를 생성하거나 유효한 기존 산출물을 `NOOP_ALREADY_COMPLETE`로
기록한 뒤 COMMON 4C/4D를 계속 실행한다. ETF 결과는 `etf_stock_reports`에
  별도로 기록하며 COMMON 4A~4D 상태 계산을 바꾸지 않는다. 4D는 같은 실행의 공개
  공개 COMMON 리포트와 ETF36 Julia 리포트로 Strategy Monitor v2를 검증하고,
  B Select lifecycle status를 한 번 생성해 메모리로 4D에 전달한다. 4D는 같은
  실행 status를 날짜별 artifact로 승격하고 정적 Web JSON을 투영한다. COMMON 4A~4D 중
`BLOCKED` 또는 `FAILED`가 발생하면 이후 COMMON 단계는 진행하지 않는다. 4D에는
Strategy Monitor v2의 세 전략 projection과 웹 상태가 포함된다.
공포지수와 ETF 랭킹의 웹 투영은 선택 보조 구성 요소라 실패해도 COMMON
4A~4D를 차단하지 않는다. ETF36 Julia V1 Stock Report 생성은 별도 단계이며
그 결과를 최상위 상태에 합성한다. 정기적인
섹터 구성 갱신 같은 관리 작업은 4단계 일일 완료 게이트가 아니라 3단계의
별도 운영 주기를 따른다.

## 5. 4A~4E 계약

### 4A. 전체 PIT COMMON 스캐너

- 입력: 인증된 1~3단계 결과와 명시적 `target_as_of`.
- 처리: Repository V2와 rolling PIT COMMON을 사용해 전체 KOSPI/KOSDAQ 보통주를
  한 번 스캔한다. subset·limit·이전 scanner 산출물 재사용은 운영 결과가 아니다.
- 출력: 기준일 이름의 scanner CSV와 요약 JSON.
- 검증: 요약의 `requested_as_of == target_as_of`와
  `reference_market_date ==` 1단계 인증 시장 권위의 실제 기준 거래일을
  확인한다. `reference_market_date <= target_as_of`여야 하며, 비거래일에는
  엄격히 더 이를 수 있다. 또한 공식 COMMON 총수와 emitted row 수의 관계를
  확인한다.

### 4B. A FAST Core V2 및 Stock Report v0.7

- 입력: 4A scanner 결과, 3단계의 외국인 수급·펀더멘털·시장 RS, 업종 RS
  직접 계산용 업종 지수 캐시와 기준일 섹터 구성 스냅샷.
- 처리: 후보를 scanner 결과에서만 받아 A FAST Core V2 상태와 Stock Report v0.7을
  생성한다. Pattern B는 기존 evaluator·운영 계약을 쓰는 정보 분석이며 매매 전략
  실행과 분리한다. 스캐너 재실행, 전략 재정의, 펀더멘털 수집 또는 새 산식은 하지 않는다.
- 출력: `artifacts/reporting/stock_reports/{YYYYMMDD}/`의 Markdown/JSON.
- 검증: 모든 발행 리포트의 `requested_as_of`와 date directory가
  `target_as_of`에 일치하고, `reference_market_date`가 4A scanner가 확정한
  실제 시장 기준 거래일과 같으며, A FAST Core의 strategy ID가 V2이고 report
  version이 `0.7`인지 확인한다.

### ETF36. Julia V1 Stock Report v0.6 자동 생성

- 실행 시점: COMMON 4B가 `PASS` 또는 `NOOP_ALREADY_COMPLETE`로 끝난 직후,
  COMMON 4C 시작 전.
- 입력: 호출자가 전달한 `target_as_of`와 4A가 확정한 정확한
  `reference_market_date`. 날짜를 독립 계산하거나 KRX/API를 조회하지 않는다.
- 처리: frozen Official ETF 36과 기존 Julia V1 v0.6 생성기를 사용한다. Julia
  lifecycle과 과거 adoption eligibility 산식/threshold는 보존한다. 현재 production
  ENTRY와 universe에는 20일 평균 거래량 10,000주를 적용하지 않는다.
- 출력: `artifacts/reporting/etf_stock_reports/{YYYYMMDD}/`의 Markdown 36개,
  `json/`의 JSON 36개 및 생성 요약.
- 멱등성: 동일 날짜의 완전하고 유효한 corpus(정확한 frozen ticker 집합 36개,
  v0.6 ETF 스키마, Julia V1 ID, 날짜 일치, post-reference data 0, evaluator 오류
  0, network 0, 생성 실패 0)는 쓰기 없이 `NOOP_ALREADY_COMPLETE`로 기록한다.
  과거 eligibility PASS/FAIL 수는 report snapshot과 summary 간 일관성만 검증하며,
  거래량 미달만으로 corpus를 실패 처리하지 않는다. partial/stale corpus는 NOOP가
  아니며 staging 전체 검증 후에만 canonical 경로로 promote한다.
- 상태: `etf_stock_reports.status`에 `PASS`, `NOOP_ALREADY_COMPLETE`,
  `BLOCKED`, `FAILED`를 별도 기록한다. ETF 실패는 COMMON 4C/4D를 중단하지 않고,
  최상위 `overall_status`에는 반영한다.
- 범위: 이 생성 단계는 Web/UI, Strategy Monitor, 자동 주문에 연결되지 않는다.

### 4C. 필수 분석 표시 결과

- 입력: 4B 리포트와 3단계 권위 산출물.
- 처리: 기존 마켓 RS, 섹터 RS, 외인 순매수, 전략 모니터, 상태 투영을 사용한다.
- 검증: 각 필수 전달 데이터의 `requested_as_of == target_as_of`,
  `reference_market_date ==` 해당 실행의 실제 시장 기준 거래일, 입력 집합과
  공개 리포트 집합을 확인한다. 마켓 RS와 전략 모니터는 `stock-index.json` 및
  `stocks/*.json`의 일치도 함께 확인한다.

### 4D. `web/data` 정적 반영

- 입력: 4B와 4C의 검증된 COMMON 결과 및 같은 실행에서 생성되거나 유효한
  NOOP로 확인된 exact-date Official ETF36 v0.6 corpus.
- 처리: 기존 `export_*_web.py`만 사용해 `web/data/`에 투영한다. 웹 계층에서
  Julia·Pattern A·eligibility·COMMON 전략·RS·펀더멘털을 재계산하지 않는다.
  ETF corpus는 frozen ETF36 전체 집합, v0.6 schema, Julia ID와 두 날짜가 모두
  검증되어야 한다. ETF 전략 상세는 Julia V1 authority를 보존한다. Historical
  eligibility 결과와 거래량 값은 투영할 수 있지만 ETF36 집합이나 corpus 유효성의
  filter로 사용하지 않는다.
- 범위 분리: 종목 index/JSON은 COMMON과 ETF36을 함께 포함한다. Market RS,
  Sector RS 및 외인 랭킹은 기존 COMMON 집합만 포함한다. Strategy Monitor v2는
  A FAST Core V2와 B Select Core V1을 공개 COMMON 집합에, Julia V1을 Official ETF 36에
  각각 분리해 저장하며 기본 선택은 A FAST Core V2다. ETF Pattern B는 적용하지 않는다.
- B Select current status: Phase4C가 `build_b_select_core_v1_status.py`를 한 번 실행한다. 이 생성기는 해시 검증된 기존
  candidate-stage authority와 월별 Pattern B state를 exact PIT identity에 연결하고,
  현재 공개 COMMON 리포트의 같은 실행 기준일 상태를 더해 per-identity lifecycle을
  복원한다. exact KRX 다음 세션 시가만 체결로 사용한다. reference 뒤 체결은 pending으로
  남기며 해당 시가를 조회하지 않는다. 이 경로는 성과 지표·portfolio simulation을 만들지 않는다.
- 실패 정책: B Select status가 없거나 날짜·범위·lifecycle 검증에 실패하면 Strategy Monitor를
  가짜 WAIT로 채우지 않고 Phase4C/4D를 실패 처리한다. Phase4D는 Phase4C가 만든
  같은 실행의 status를 재사용해 날짜별 artifact로 보존한다.
- 검증: `stock-index.json` 및 종목 JSON, 필수 순위·모니터·상태 JSON에
  `requested_as_of == target_as_of`와 동일 실행의 `reference_market_date`가
  일관되게 기록되고, strategy-monitor v2의 3개 전략 범위·counts·items 및 B Select
  status artifact가 일치하며 화면 입력 JSON 형식이 유효한지 확인한다.
  비거래일에는 `reference_market_date < target_as_of`를 정상으로 처리한다.
  ETF corpus가 없거나 불완전·무효이면 NOOP로 통과시키지 않고 4D를 실패 처리한다.
- 배포: 이 단계는 `web/data` 생성까지만 정의한다. Pages 배포는 main 반영 후의
  기존 배포 흐름의 책임이며 웹 JSON 자체가 분석 권위가 되지 않는다.

### 4E. 조율과 상태 합성

4단계 조율기는 새 계산기를 만들지 않고 4A~4D의 기존 진입점을 명시적
`target_as_of`로 호출·검증·기록한다. 상태 토큰은 새로 만들지 않고 다음만 쓴다.

| 상태 | 의미 |
|---|---|
| `PASS` | 모든 COMMON 4A~4D 단위가 같은 기준일로 새 결과를 정상 생성 |
| `NOOP_ALREADY_COMPLETE` | 모든 COMMON 단위의 유효한 동일 기준일 결과가 이미 존재하고 쓰기 없음 |
| `BLOCKED` | 기준일·권위·필수 입력·출력 일치 검증이 불가능해 안전하게 중단 |
| `FAILED` | 예기치 않은 실행·형식·무결성 오류 |

`common_overall_status`는 기존 규칙대로 COMMON 4A~4D 상태만 합성한다. 최상위
`overall_status`는 이 값과 ETF 상태를 함께 합성해 ETF 실패가 성공으로 가려지지
않게 한다. ETF 상태는 `etf_stock_reports.status`에 기록하며 `PASS`,
`NOOP_ALREADY_COMPLETE`, `BLOCKED`, `FAILED`를 쓴다. ETF 단계의 실패는 COMMON
4C/4D 실행을 중단시키지 않는다. 두 상태 값은 각각 COMMON 결과와 ETF 리포트
생성 결과를 구분해 해석한다. 공포지수 투영과 정기 관리 작업은 전체 상태 합성에
포함하지 않고 별도로 기록한다.

### 동일 기준일 멱등성 원칙

동일한 입력과 동일한 `target_as_of`로 다시 실행했을 때 이미 유효한 결과가
존재하면 불필요한 재계산이나 쓰기를 하지 않고 멱등적으로 처리한다.

## 6. 저장·권위 경계

4단계는 기존 경로만 사용한다.

```text
scanner:
artifacts/patterns/pattern_a/production/scanner/

COMMON Stock Report:
artifacts/reporting/stock_reports/{YYYYMMDD}/

ETF36 Julia V1 Stock Report:
artifacts/reporting/etf_stock_reports/{YYYYMMDD}/

B Select Core V1 current status:
artifacts/strategies/b_select_core_v1/production/{YYYYMMDD}/status.json

웹 정적 투영:
web/data/
```

3단계의 시장 RS, 업종 RS, 외국인 수급, 펀더멘털 저장 위치와 Repository V2는
그 단계의 권위·저장 계약을 계속 따른다. 4단계는 새 데이터베이스, manifest,
전략 ID, 리포트 버전 또는 권위 계층을 만들지 않는다.

## 7. 제외 범위와 연결 원칙

이 문서는 코드·테스트·데이터 갱신·외부 API 호출·실행·웹 배포의 계약과
경계만 정의한다. 4A~4E의 구현과 운영 호출은 이 문서의 입력·권위·상태
계약을 따르며, 필수 구성 요소와 선택 보조 구성 요소를 상태 합성에서
구분한다.

## 8. 관련 현재 기준 문서

- [데일리 업데이트 기준 V01](daily_update_contract_v01.md)
- [분석 입력 갱신 기준 V01](daily_update_phase3_analysis_inputs_contract_v01.md)
- [A FAST Core V2 현재 기본 전략](../patterns/pattern_a_fast/strategy/version_02/README.md)
- [Stock Report 안내 및 버전 색인](../reporting/README.md)
- [Stock Report v0.7 계약](../reporting/contract_v07.md)
- [Official ETF 36 Stock Report v0.6 계약](../reporting/contract_v06.md)
- [웹 영역 안내](../web/README.md)
