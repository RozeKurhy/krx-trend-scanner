opendart_fundamentals_v1_scope_freeze.md

======================================================================
F1 — OpenDART CURRENT-STATE AUDIT & V1 SCOPE FREEZE
======================================================================

감사 기준
----------------------------------------------------------------------

- 기준 HEAD: cc54c4b4137ef480c9939c16e5a59e9bf9936d0b
- 감사 시점의 origin/main과 로컬 main은 동일한 HEAD였다.
- 감사 대상: src/trend_scanner/fundamentals/, 관련 테스트, 문서,
  artifacts/fundamentals/opendart/validation/의 커밋된 내용
- 이번 단계에서는 구현·테스트·아티팩트를 변경하지 않았다.
- OpenDART, KRX Open API, PyKRX, 웹 스크래핑, 외부 시세 API 호출은 하지 않았다.
- 로컬 쓰기 권한은 docs/fundamentals/.f1_write_probe.tmp에 대해
  write → read-back equality → delete 순서로 확인했으며 PASS였다.

1. 현재 구현 맵
----------------------------------------------------------------------

+----------------------------+----------------------+----------------------------+
| 구성요소                   | 현재 상태            | F1 판정                   |
+----------------------------+----------------------+----------------------------+
| Corp Code Repository       | 캐시 로드, ticker/    | REUSE: PIT identity의      |
|                            | corp_code 매핑,      | 기준 저장소로 사용         |
|                            | ZIP refresh 경로     |                            |
+----------------------------+----------------------+----------------------------+
| Filing Registry            | 캐시 완전성/HTTP     | REUSE: 페이지네이션,      |
|                            | 200/status 000,      | coverage 및 correction     |
|                            | 중복·페이지 검증,    | 검증 계약 유지             |
|                            | 원자적 저장          |                            |
+----------------------------+----------------------+----------------------------+
| PIT Resolver               | bsns_year/reprt_code | REUSE: DAILY_EOD_KST,     |
|                            | 및 rcept_dt<=as_of   | 미래 누수·동일일 모호성   |
|                            | 기준 결정론적 선택   | fail-closed 유지          |
+----------------------------+----------------------+----------------------------+
| XBRL Repository            | filing별 ZIP/sha     | REUSE: filing-specific    |
|                            | 검증, context/기간/  | XBRL context와 basis      |
|                            | 차원 보존, CFS/OFS   | 선택을 canonical raw      |
|                            | atomic fallback      | 입력으로 사용             |
+----------------------------+----------------------+----------------------------+
| Financial Statement       | 단일 filing의 core   | REUSE_IF_NEEDED: 단일     |
| Provider                   | metric 정규화,       | 보고서 정규화 경로.       |
|                            | company-family       | 다기간 출력은             |
|                            | aware NOT_APPLICABLE | PeriodizationProvider로   |
|                            | 처리                 | 확장                       |
+----------------------------+----------------------+----------------------------+
| Periodization Engine/     | Q1~Q4/FY standalone, | REUSE: 누적→standalone,   |
| Provider                   | direct-vs-derived    | prior PIT anchor, parity, |
|                            | parity, basis/통화/  | coherence와 provenance    |
|                            | PIT gate             | 보존                       |
+----------------------------+----------------------+----------------------------+
| Derived Metrics Engine/   | TTM, 분기·연간 YoY,  | REUSE: 순수 파생 계산.    |
| Provider                   | margin, trend/       | 12Q/5Y report adapter와   |
|                            | acceleration, OCF    | filter 입력 계약은       |
|                            | margin               | EXTEND                    |
+----------------------------+----------------------+----------------------------+
| Assessment Engine/        | Growth/Profitability/ | REUSE_IF_DIRECTLY_USEFUL: |
| Provider                   | Cash Flow/Momentum   | 기존 STRONG/MIXED 등은   |
|                            | 축 및 FINANCIAL      | 선택 기능. V1에 새       |
|                            | NOT_APPLICABLE       | scoring·판정은 추가하지   |
|                            | 처리                 | 않는다                    |
+----------------------------+----------------------+----------------------------+
| Stock Report              | Pattern A/시장·수급/ | NEW: Fundamentals 표·     |
| integration               | 상대강도 리포트만    | summary/filter 연결 없음  |
|                            | 제공                 |                            |
+----------------------------+----------------------+----------------------------+
| Trading Filter            | Fundamentals 전용    | NEW: PIT-confirmed        |
|                            | evaluator 없음       | configurable threshold    |
|                            |                      | 계약 필요                 |
+----------------------------+----------------------+----------------------------+

핵심 해석
----------------------------------------------------------------------

현재 코드는 OpenDART의 PIT-safe 수집·정규화·기간화·파생계산 엔진을 갖추고
있다. 다만 이를 Stock Report의 12분기/5년 표나 Fundamentals Trading Filter로
묶는 생산 경계는 아직 구현되어 있지 않다. Assessment는 범용 비금융 평가
엔진이며 FINANCIAL 프로파일은 명시적으로 NOT_APPLICABLE이다.

2. 생산 준비도 경계
----------------------------------------------------------------------

- Engine implementation: READY_FOR_REVIEW. 저장소·PIT·XBRL·기간화·파생
  계산의 fail-closed 계약과 provenance가 코드에 존재한다.
- Representative validation: PASS evidence가 커밋되어 있다. final closure
  artifact는 production_context_fact_count 1,140, scope fingerprint 224,
  production_ttm_ready_count 140, TTM margin 105, production build error 0,
  Q1 ambiguity 42→0을 기록한다. 대표 비금융 7종목과 금융 1종목 fixture가
  사용되었다.
- Full KRX coverage: NO. 대표 cohort만 검증되었고 raw_source_committed는
  false이므로 전 종목 OpenDART 원천 확보·재현성은 아직 닫히지 않았다.
- Biggest boundary: 다기간 canonical dataset materialization과 Stock Report/
  filter adapter가 없고, 전체 종목 coverage 및 live hydration을 이번 F1에서
  수행하지 않았다.

3. Fundamentals V1 scope freeze
----------------------------------------------------------------------

3.1 Trading Filter (초기 하드 필터)

다음 조건을 모두 만족하는 종목만 V1 Fundamentals 적격으로 본다. 임계값은
설정 가능한 계약으로 두며, 이 문서가 특정 코드 상수의 구현을 요구하지는
않는다.

- 최신 PIT-confirmed FY 매출 >= 500억원
- 최신 PIT-confirmed standalone 4개 분기의 평균 매출 >= 100억원
- 최신 4개 standalone 분기의 TTM 영업이익 > 0
- 동일 TTM의 순이익 > 0

확인되지 않은 기간, basis/currency 불일치, 모호한 context, 미래 filing은
필터에서 탈락시키며 0으로 대체하지 않는다. OCF는 V1 보고서와 summary에는
포함하지만 초기 하드 필터 조건으로 사용하지 않는다.

3.2 Stock Report — quarterly

- 최근 12개 confirmed standalone quarter를 표시한다.
- 각 행: quarter, revenue, revenue YoY, operating income, operating margin,
  net income, net margin, operating cash flow(OCF)
- revenue YoY를 계산하려면 최소 16개 분기의 coherent raw/canonical coverage가
  필요하다(표시 12Q + 전년 동기 4Q).
- 각 값은 as-of, filing receipt, statement basis, source hash와 연결되어야
  하며 누락·모호성을 조용히 보간하지 않는다.

3.3 Stock Report — annual

- 최근 5개 confirmed fiscal year를 표시한다.
- 각 행: year, revenue, revenue YoY, operating income, operating margin,
  net income, net margin, ROE, debt ratio
- Annual OCF는 데이터가 있으면 availability를 나타내되 V1 필수 표 열은
  아니다.
- 5년 YoY와 consecutive-growth 계산에는 표시 기간보다 앞선 비교 기간을
  포함한 canonical coverage가 필요하다.

3.4 Summary candidates

- latest confirmed FY revenue
- latest 4Q average revenue
- TTM revenue / operating income / net income / OCF
- TTM operating margin / net margin / OCF margin
- TTM ROE / debt ratio

Summary는 적격성 판정과 표시를 분리한다. 표시 가능한 값이 없다는 이유로
필터 조건을 우회하거나 다른 원천으로 대체하지 않는다.

4. metric definitions
----------------------------------------------------------------------

모든 flow metric은 동일 PIT·basis·통화·기업 범위의 standalone observation만
조합한다.

- TTM: 최신 4개 연속 standalone quarter의 합
- Quarterly YoY: 해당 분기 flow와 4분기 전 동분기 flow의 증감률
- Annual YoY: 해당 FY flow와 직전 FY flow의 증감률
- Operating margin: operating income / revenue × 100
- Net margin: net income / revenue × 100
- OCF margin: operating cash flow / revenue × 100
- ROE: net income / ((기초 equity + 기말 equity) / 2) × 100
- Debt ratio: liabilities / equity × 100
- consecutive YoY count: 정의된 동일 기간 YoY가 연속 양수인 구간의 길이
- positive count/direction: 관측 가능한 기간만 대상으로 하며 undefined를
  양수·0으로 취급하지 않는다.

현재 DerivedMetricsEngine은 TTM, 분기·연간 YoY, margin, OCF margin과 trend를
지원한다. ROE와 debt ratio는 입력 snapshot의 일관성·평균 equity/부채 계약을
검증하는 새 파생 계산이 필요하다.

5. 지원성 및 작업 분류
----------------------------------------------------------------------

+----------------------------+---------------------------------------------+
| 요구사항/메트릭            | F1 분류 및 근거                            |
+----------------------------+---------------------------------------------+
| PIT-safe raw/canonical     | ALREADY_IMPLEMENTED — Registry/Resolver/   |
| source                     | XBRL/Periodization 계약                    |
+----------------------------+---------------------------------------------+
| TTM flow                   | ALREADY_IMPLEMENTED — 4 standalone quarter |
|                            | 기반 DerivedMetricsEngine                  |
+----------------------------+---------------------------------------------+
| Quarterly/Annual YoY       | ALREADY_IMPLEMENTED — 파생 엔진 지원.      |
|                            | 12Q/5Y 출력 경계는 EXTEND                  |
+----------------------------+---------------------------------------------+
| Operating/Net/OCF margin   | ALREADY_IMPLEMENTED — flow guard 포함      |
+----------------------------+---------------------------------------------+
| ROE                        | NEW_DERIVED_METRIC_REQUIRED                |
+----------------------------+---------------------------------------------+
| Debt ratio                 | NEW_DERIVED_METRIC_REQUIRED                |
+----------------------------+---------------------------------------------+
| 12-quarter Stock Report    | EXTEND — canonical multi-period 입력과     |
|                            | reporting adapter/schema 필요              |
+----------------------------+---------------------------------------------+
| 5-year annual report       | EXTEND — provider는 arbitrary fiscal years |
|                            | 를 받을 수 있으나 report adapter 부재      |
+----------------------------+---------------------------------------------+
| Fundamentals Trading      | NEW — configurable threshold evaluator,    |
| Filter                     | eligibility reason/provenance 필요         |
+----------------------------+---------------------------------------------+
| Assessment STRONG/MIXED    | REUSE_IF_DIRECTLY_USEFUL — 선택적 표시만   |
|                            | 허용, V1 판정 계약은 별도                  |
+----------------------------+---------------------------------------------+
| Financial-company metrics  | NOT_SUPPORTED_FOR_V1 — 일반회사 filter만   |
| (NIM/CET1 등)              | 적용하고 금융 특화 계산은 보류             |
+----------------------------+---------------------------------------------+

6. 금융회사 정책
----------------------------------------------------------------------

V1의 Fundamentals Trading Filter와 Stock Report는 일반회사(non-financial)
프로파일만 대상으로 한다. CompanyFamily=FINANCIAL이면 현재 계약처럼
Fundamentals Assessment를 NOT_APPLICABLE로 반환하고, 금융업 전용 매출·영업
이익 해석이나 NIM, CET1, 충당금 지표를 일반회사 지표로 변환하지 않는다.
금융회사에 대한 별도 제품 범위는 F1/F2에 포함하지 않는다.

7. 명시적 범위 제외
----------------------------------------------------------------------

- PER, PBR, PSR, EV, EBITDA, PEG 및 모든 valuation
- composite score, Pattern A + Fundamentals 합산 점수
- automated signal/recommendation
- 금융회사 특화 fundamentals (NIM, CET1 등)
- dividend analytics
- DCF, fair value, target price
- PyKRX, KRX HTML/web scraping, Naver raw fallback
- legacy ETF/parquet를 OpenDART canonical raw로 승격
- manual data injection 및 API 결과 대체

8. F2~F8 dependency map
----------------------------------------------------------------------

F2 — canonical multi-period production boundary
  - F1의 PIT/canonical/basis/provenance 계약을 입력으로 사용한다.
  - 최소 16Q raw/canonical 확보 후 최근 12Q YoY와 5 FY를 안정적으로 구성한다.
  - full-KRX coverage 및 live hydration 여부를 별도 readiness gate로 둔다.

F3 — derived metrics extension
  - 기존 TTM/YoY/margin/OCF 계산을 재사용한다.
  - ROE/debt ratio와 equity/liability snapshot coherence를 추가한다.

F4 — Fundamentals filter
  - F1의 네 조건과 configurable thresholds, missing/ambiguous reason,
    financial NOT_APPLICABLE 정책을 구현한다.

F5 — Stock Report adapter
  - quarterly 12Q/annual 5Y schema, summary candidates, provenance와
    unavailable 표현을 reporting layer에 연결한다.

F6 — representative and negative validation
  - non-financial/financial, missing period, basis mismatch, ambiguous/future
    filing, negative earnings 경로를 mocked/committed fixture로 검증한다.

F7 — production coverage/readiness
  - 전체 대상 coverage와 재현 가능한 raw artifact 정책을 확인한다.
  - F1에서 수행하지 않은 live/OpenDART 호출을 이 단계의 명시적 gate로 둔다.

F8 — final integration/review
  - F2~F7 결과를 Stock Report 및 기존 Pattern A 흐름과 연결하되, valuation·
    composite·자동 추천으로 범위를 확장하지 않는다.

======================================================================
F1 FREEZE STATUS
======================================================================

F1은 현재 구현과 커밋된 대표 검증 증거를 기준으로 Fundamentals V1의 범위를
동결했다. 이번 단계에서 새 기능이나 생산 데이터는 만들지 않았으며, 다음
단계는 위 dependency map의 F2 경계부터 시작한다.
