# 분석·리포트·웹 반영 기준 V01

## 1. 문서 역할

이 문서는 [데일리 업데이트 기준 V01](daily_update_contract_v01.md) §6.3이
정의한 4단계의 상세 계약이다. 4단계는 1~3단계가 같은 기준일로 인증한
입력을 받아 기존 스캐너, 공식 전략, Stock Report v0.5와 웹 정적 투영을
일관되게 연결한다. 새 분석 엔진·산식·전략·리포트 버전을 만드는 단계가
아니다. 개별 실행 결과와 검증 일지는 이 문서의 범위에 포함하지 않는다.

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

일반 종목의 공식 전략은 오직 A FAST Core V2
(`PATTERN_A_FAST_FINAL_STRATEGY_V02`)다. 그 상태는 의사결정 지원 운영
(`PRODUCTION_DECISION_SUPPORT`)이며 자동매매 권한이 아니다. V3/V4, Julia 또는
다른 후보 전략을 4단계에 추가하지 않는다.

`generate_stock_report()`와 `build_a_fast_core_section()`은
`requested_as_of` 이하의 입력을 사용한다. 리포트는 외국인 수급, 펀더멘털,
시장 RS, 업종 RS와 A FAST Core V2를 기존 섹션으로 소비하며, v0.5의
펀더멘털 섹션은 이미 생성된 F2/F3/F4 결과를 주입받을 뿐 OpenDART를
호출하거나 필터를 다시 계산하지 않는다.

리포트 공식 버전은 Stock Report v0.5뿐이며 출력 위치는 다음과 같다.

```text
artifacts/reporting/stock_reports/{YYYYMMDD}/
  *.md
  json/*.json
```

4단계의 모든 리포트 생성은 `requested_as_of == target_as_of`와
`reference_market_date ==` 스캐너가 확정한 실제 시장 기준 거래일을 명시하고,
스캐너 결과를 유일한 후보 입력으로 소비한다. 리포트가 스캐너를 독립
재실행하거나 다른 기준 거래일·날짜 후보를 대체 경로로 사용하는 것은 허용하지
않는다.

### 3.3 웹 정적 투영

`web/data/`는 표시용 정적 결과물이며 분석·전략·원천의 새 권위가 아니다.
현재 확인된 주요 투영 경로는 다음과 같다.

| 구분 | 입력 | 웹 출력 | 계약상 역할 |
|---|---|---|---|
| 종목 리포트 | 날짜별 Stock Report v0.5, PIT 메타데이터, 정확한 일별 종가 | `stock-index.json`, `stocks/*.json` | 필수 구성 요소 |
| 마켓 RS | 공개 종목 리포트 웹 전달 데이터 | `market-ranking.json` | 필수 구성 요소 |
| 전략 모니터 | `stock-index.json`, `stocks/*.json` | `strategy-monitor.json` | 필수 구성 요소 |
| 섹터 RS | 업종 RS 권위, 메타데이터, 리포트 집합 | `sector-rs-ranking.json` | 필수 구성 요소 |
| 외인 순매수 | 외국인 수급, PIT COMMON 권위, 섹터 구성; `stock-index.json`은 리포트 보유 여부만 확인 | `foreign-net-buy-ranking.json` | 필수 구성 요소 |
| 웹 상태 | 시장·PIT·펀더멘털·리포트의 로컬 상태 | `health.json` | 필수 구성 요소 |
| 공포지수 | `artifacts/fear_index/research_v01/` 연구 산출물 | `fear-index.json` | 선택 보조 구성 요소 |
| ETF 랭킹 | 고정 ETF 메타데이터와 Repository V2 | `etf-ranking.json` | 선택 보조 구성 요소 |

`export_market_ranking_web.py`와 `export_strategy_monitor_web.py`는 Stock
Report 웹 전달 데이터를 입력으로 사용한다. 따라서 둘은 종목 리포트 웹 투영 후에만
실행한다. 외인 순매수의 `stock-index.json` 사용은 보통주 모집단을 정하는
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
     → 4B A FAST Core V2 + Stock Report v0.5
     → 4C 필수 분석 표시 결과 검증
     → 4D web/data 정적 투영
     → 전체 상태 합성
```

4E 조율기는 4A~4D를 같은 `target_as_of`와 `reference_market_date`로 순서대로
호출하고 각 단계의 입력·출력을 검증한 뒤 전체 상태를 합성한다. 4A~4D 중
`BLOCKED` 또는 `FAILED`가 발생하면 이후 단계는 진행하지 않는다. 4C에는 마켓 RS, 섹터 RS,
외인 순매수, 전략 모니터와 웹 상태가 포함된다.
공포지수와 ETF는 이 순서에 붙일 수 있는 선택 보조 투영이지만, 실패해도
필수 결과를 같은 성공으로 승격하거나 필수 완료를 차단하지 않는다. 정기적인
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

### 4B. A FAST Core V2 및 Stock Report v0.5

- 입력: 4A scanner 결과와 3단계의 외국인 수급·펀더멘털·시장 RS·업종 RS.
- 처리: 후보를 scanner 결과에서만 받아 A FAST Core V2 상태와 Stock Report v0.5를
  생성한다. 스캐너 재실행, 전략 재정의, 펀더멘털 수집·주입 또는 새 산식은 하지 않는다.
- 출력: `artifacts/reporting/stock_reports/{YYYYMMDD}/`의 Markdown/JSON.
- 검증: 모든 발행 리포트의 `requested_as_of`와 date directory가
  `target_as_of`에 일치하고, `reference_market_date`가 4A scanner가 확정한
  실제 시장 기준 거래일과 같으며, A FAST Core의 strategy ID가 V2이고 report
  version이 `0.5`인지 확인한다.

### 4C. 필수 분석 표시 결과

- 입력: 4B 리포트와 3단계 권위 산출물.
- 처리: 기존 마켓 RS, 섹터 RS, 외인 순매수, 전략 모니터, 상태 투영을 사용한다.
- 검증: 각 필수 전달 데이터의 `requested_as_of == target_as_of`,
  `reference_market_date ==` 해당 실행의 실제 시장 기준 거래일, 입력 집합과
  공개 리포트 집합을 확인한다. 마켓 RS와 전략 모니터는 `stock-index.json` 및
  `stocks/*.json`의 일치도 함께 확인한다.

### 4D. `web/data` 정적 반영

- 입력: 4B와 4C의 검증된 결과.
- 처리: 기존 `export_*_web.py`만 사용해 `web/data/`에 투영한다. 웹 계층에서
  전략·RS·펀더멘털을 재계산하지 않는다.
- 검증: `stock-index.json` 및 종목 JSON, 필수 순위·모니터·상태 JSON에
  `requested_as_of == target_as_of`와 동일 실행의 `reference_market_date`가
  일관되게 기록되고, 화면 입력 파일이 존재하며 JSON 형식이 유효한지 확인한다.
  비거래일에는 `reference_market_date < target_as_of`를 정상으로 처리한다.
- 배포: 이 단계는 `web/data` 생성까지만 정의한다. Pages 배포는 main 반영 후의
  기존 배포 흐름의 책임이며 웹 JSON 자체가 분석 권위가 되지 않는다.

### 4E. 조율과 상태 합성

4단계 조율기는 새 계산기를 만들지 않고 4A~4D의 기존 진입점을 명시적
`target_as_of`로 호출·검증·기록한다. 상태 토큰은 새로 만들지 않고 다음만 쓴다.

| 상태 | 의미 |
|---|---|
| `PASS` | 모든 필수 4A~4D 단위가 같은 기준일로 새 결과를 정상 생성 |
| `NOOP_ALREADY_COMPLETE` | 모든 필수 단위의 유효한 동일 기준일 결과가 이미 존재하고 쓰기 없음 |
| `BLOCKED` | 기준일·권위·필수 입력·출력 일치 검증이 불가능해 안전하게 중단 |
| `FAILED` | 예기치 않은 실행·형식·무결성 오류 |

필수 단위 중 하나라도 `FAILED`이면 전체 `FAILED`, `FAILED`는 없고 하나라도
`BLOCKED`이면 전체 `BLOCKED`, 모두 `NOOP_ALREADY_COMPLETE`이면 전체
`NOOP_ALREADY_COMPLETE`, 나머지 정상 조합은 `PASS`다. 선택 보조 투영과
정기 관리 작업은 전체 상태 합성에 포함하지 않고 별도로 기록한다.

### 동일 기준일 멱등성 원칙

동일한 입력과 동일한 `target_as_of`로 다시 실행했을 때 이미 유효한 결과가
존재하면 불필요한 재계산이나 쓰기를 하지 않고 멱등적으로 처리한다.

## 6. 저장·권위 경계

4단계는 기존 경로만 사용한다.

```text
scanner:
artifacts/patterns/pattern_a/production/scanner/

Stock Report:
artifacts/reporting/stock_reports/{YYYYMMDD}/

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
- [Stock Report v0.5 안내](../reporting/stock_report/README.md)
- [Stock Report v0.5 계약](../reporting/stock_report/contract_v05.md)
- [웹 영역 안내](../web/README.md)
