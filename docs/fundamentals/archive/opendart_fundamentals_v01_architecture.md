opendart_fundamentals_v01_architecture.md

==================================================
OpenDART Fundamentals V01 Architecture
==================================================

문서 상태
---------

작업 ID: OPENDART_FUNDAMENTALS_V01_ARCHITECTURE
범위: PIT authority / filing contract / statement family / account mapping foundation
최종 상태: READY_FOR_ARCHITECT_OPENDART_FUNDAMENTALS_ARCHITECTURE_REVIEW
실행일: 2026-08-23

이번 단계는 Fundamentals Score, valuation, 매매 signal 또는 Stock Report 통합을
구현하지 않는다. 숫자를 계산하기 전에 해당 숫자가 어떤 filing/version/statement
맥락에서 과거 시점에 공개되었는지를 재현할 수 있는지 검증하고 계약으로 고정한다.

==================================================
1. Authority와 현재 결과
==================================================

직전 access validation authority:
7b235817607f7b58d46e49a2346bc14b0b28936c

Access validation에서 확인된 고정 근거:
- OpenDART status 000
- corpCode ZIP parse 및 3개 종목 corp_code mapping
- 2025 annual CFS와 2026 half-year CFS 응답
- API key leak 0건

이번 architecture 결과:
- live HTTP request: 10회, budget 15회 이내
- 삼성전자 filing-specific XBRL: HTTP 200 / ZIP parse PASS
- 동일 filing 재호출 SHA-256 일치
- 에스티팜·하나금융지주 2025 annual original/correction pair 확인
- 새 architecture artifact에는 raw ZIP/XML/full JSON을 저장하지 않음

==================================================
2. Data authority 분리
==================================================

CURRENT_LATEST
-------------

source: fnlttSinglAcntAll.json
용도: 현재 시점 리포트, 최신 diagnostic, convenience query
제약: 특정 과거 filing의 rcept_no를 고정하지 않으므로 historical strict PIT
authority로 사용하지 않는다.

HISTORICAL_STRICT_PIT 후보
--------------------------

source: list.json filing registry + fnlttXbrl.xml filing-specific source
필수 provenance: ticker, corp_code, report_nm, reprt_code, rcept_no, rcept_dt,
pit_as_of, fs_div, ZIP hash
원칙: 먼저 as_of에 허용되는 filing을 선택하고, 선택된 rcept_no의 XBRL만 읽는다.

이번 probe는 다음 source feasibility를 입증했다.

005930 삼성전자
- report: 사업보고서 (2025.12)
- rcept_no: 20260310002820
- rcept_dt: 20260310
- reprt_code: 11011
- XBRL HTTP: 200
- content type: application/x-msdownload;charset=UTF-8
- ZIP member count: 7
- byte length: 802368
- SHA256: 946ed3c81628c5cb69e460217a1e3f656d857b64c9dde15fdac981c2d68323d1
- 동일 filing 재호출 SHA: 동일

정정 pair diagnostic:
- 에스티팜 original 20260318001605 / correction 20260602000343
  - original SHA256: c7ce79a84c5829080ceae4601e2dd70b5dc90dc3c7a4ea971ff3575438b2f92e
  - correction SHA256: faafbf7b347987c3c2c43a748e99e60f61025059a2a969fa8aa519839b90d900
- 하나금융지주 original 20260316001292 / correction 20260814004019
  - 두 filing 모두 HTTP 200 / ZIP parse PASS

정정 pair의 존재와 서로 다른 filing-specific hash를 확인했지만, 전체 DART
report-chain identity를 완전하게 복원하는 production resolver는 다음 단계다.

==================================================
3. PIT semantics
==================================================

PIT_GRANULARITY = DAILY_EOD_KST

as_of는 KST calendar day의 EOD information set을 뜻한다.

- rcept_dt < as_of: AVAILABLE
- rcept_dt == as_of: AVAILABLE_AT_EOD
- rcept_dt > as_of: FUTURE_FORBIDDEN

같은 날짜의 filing은 신호일 종가 이후 다음 local trading day open 실행 모델과
일치하는 범위에서 포함한다. 이를 instantaneous market-close 정보라고 부르지
않으며, intraday 전략에는 이 계약을 그대로 적용하지 않는다.

revision policy:
- eligible filings = rcept_dt <= as_of
- 동일 filing chain에서 eligible 중 가장 최근 제출본 선택
- 미래 correction은 과거 selection에서 제외
- chain identity가 없거나 독립 chain이 여러 개면 AMBIGUOUS로 fail closed

pure function:
select_pit_filing(filings, as_of, bsns_year, reprt_code)

unit test로 same-day, future filing, eligible correction, future correction,
ambiguous chain을 검증했다.

==================================================
4. Filing registry와 report type
==================================================

raw reprt_code는 보존한다.

11013 = Q1
11012 = HALF_YEAR
11014 = Q3
11011 = ANNUAL

list.json의 report_nm에서 대표 report type과 fiscal year를 만들 수 있지만,
실제 chain identity가 불충분한 경우 임의 추론하지 않는다. 이번 live probe는
3개 종목 broad window와 삼성전자 annual narrow window를 합쳐 10회 요청으로
bounded하게 수행했다.

==================================================
5. CFS / OFS contract
==================================================

report-level basis는 하나만 선택한다.

1. CFS status 000 + usable rows
   -> fs_div_used = CFS
2. CFS status 013 + OFS status 000 + usable rows
   -> fs_div_used = OFS, fallback_used = true
3. CFS API error/access failure
   -> DATA_UNAVAILABLE / fail closed
   -> OFS로 조용히 fallback하지 않음

Revenue를 CFS에서, operating income을 OFS에서 가져오는 account-level 혼합은
금지한다. 선택 결과에는 fs_div_requested, fs_div_used, fallback_used,
fallback_reason을 보존해야 한다.

==================================================
6. Statement family
==================================================

raw sj_div는 삭제하지 않고 canonical family를 추가한다.

raw sj_div       canonical statement_family
--------------------------------------------------
BS               BALANCE_SHEET
IS               INCOME_STATEMENT
CIS              INCOME_STATEMENT
CF               CASH_FLOW
SCE              EQUITY_CHANGES

에스티팜은 IS가 없고 CIS에 revenue / operating income / net income이 존재한다.
따라서 IS required 조건은 사용하지 않는다. IS와 CIS는 같은 Income Statement
family 안에서 후보로 다루며, 삼성전자처럼 둘 다 존재하면 raw context와
우선순위를 사용한다.

==================================================
7. Company family
==================================================

이번 단계의 분류는 대표 fixture용 evidence-based initial classification이다.
전체 KRX 산업분류 엔진으로 선언하지 않는다.

초기 금융 family 경계:
- induty_code prefix 64 / 65 / 66 -> FINANCIAL
- 그 외 non-empty induty_code -> NON_FINANCIAL
- induty_code 없음 + 금융 account structure evidence -> FINANCIAL fallback
- prefix 67은 이번 rule에 포함하지 않음

ticker       company_family   evidence
--------------------------------------------------
005930       NON_FINANCIAL    induty_code 264
237690       NON_FINANCIAL    induty_code 212
086790       FINANCIAL        induty_code 64992 + financial account structure

FINANCIAL에는 비금융 전용 revenue/operating income metric을 강제로 적용하지
않는다. assets, liabilities, equity, net income은 공통 candidate로 확인할 수
있지만 NIM, 대손비용, CET1, ROE 등 금융업 KPI는 이번 범위에서 구현하지 않는다.

==================================================
8. Canonical account mapping foundation
==================================================

이번 단계의 수준은 CANONICAL_ACCOUNT_MAPPING_CANDIDATE_V01이다. 완전한 KRX
production mapping이나 growth/margin 계산은 다음 단계다.

metric                  allowed family         preferred account_id
--------------------------------------------------------------------------
assets                  BALANCE_SHEET          ifrs-full_Assets
liabilities             BALANCE_SHEET          ifrs-full_Liabilities
equity                  BALANCE_SHEET          ifrs-full_Equity
revenue                 INCOME_STATEMENT       ifrs-full_Revenue
operating_income        INCOME_STATEMENT       dart_OperatingIncomeLoss
net_income              INCOME_STATEMENT       ifrs-full_ProfitLoss
operating_cash_flow     CASH_FLOW              ifrs-full_CashFlowsFromUsedInOperatingActivities

account_id가 없는 경우에도 loose substring을 production rule로 사용하지 않는다.
명시적인 alias registry와 account_nm exact candidate가 필요하다.

삼성전자:
- assets / liabilities / equity: BS에서 RESOLVED
- revenue / operating_income / net_income: IS 우선, INCOME_STATEMENT에서 RESOLVED
- operating_cash_flow: CF에서 RESOLVED
- ifrs-full_ProfitLoss는 CIS/IS/CF/SCE에 반복되지만 statement family와 raw sj_div로 분리

에스티팜:
- assets / liabilities / equity: BS에서 RESOLVED
- revenue / operating_income / net_income: CIS에서 RESOLVED
- operating_cash_flow: CF에서 RESOLVED
- IS 부재가 resolution 실패로 이어지지 않음

하나금융지주:
- company_family = FINANCIAL
- assets / liabilities / equity / net_income / operating_cash_flow만 공통 candidate
- revenue / operating_income은 NOT_APPLICABLE
- '-표준계정코드 미사용-' 금융업 계정은 일반기업 revenue로 확정하지 않음

==================================================
9. Duplicate account contract
==================================================

실제 diagnostic duplicate:
- 삼성전자 ifrs-full_Equity: BS/SCE 반복
- 삼성전자 ifrs-full_ProfitLoss: IS/CIS/CF/SCE 반복
- 에스티팜 ifrs-full_ProfitLoss: CIS/SCE 반복
- 하나금융지주 ifrs-full_Equity, ifrs-full_ProfitLoss 및 금융업 custom account 반복

resolver context:
statement_family -> raw sj_div -> account_id -> account_nm -> account_detail
-> period context -> ord

first-match algorithm은 사용하지 않는다. 동일 우선순위 후보가 남으면
AMBIGUOUS로 반환하고 fail closed한다. SCE duplicate는 BS/IS metric candidate에
유입되지 않는다.

==================================================
10. Half-year field semantics
==================================================

2026 half-year CFS를 삼성전자와 에스티팜에 대해 실제 조회했다.

005930: status 000, 223 rows
237690: status 000, 175 rows

두 응답에서 확인된 field:
rcept_no, reprt_code, bsns_year, corp_code, sj_div, sj_nm, account_id,
account_nm, account_detail, thstrm_nm, thstrm_amount, thstrm_add_amount,
frmtrm_nm, frmtrm_amount, frmtrm_q_nm, frmtrm_q_amount, frmtrm_add_amount,
ord, currency

thstrm_amount / thstrm_add_amount / prior-period fields의 의미는 report type과
statement에 따라 달라질 수 있다. 따라서 thstrm_amount를 무조건 standalone
quarter로 해석하지 않는다.

다음 계산을 아직 contract로 freeze하지 않는다.
- Q2 = H1 - Q1
- Q3 = 9M - H1
- Q4 = FY - 9M

이번 단계는 field presence/value diagnostic까지만 수행했다.

==================================================
11. Period identity contract
==================================================

향후 normalized row는 최소 다음 provenance를 표현할 수 있어야 한다.

ticker, corp_code, company_family, bsns_year, reprt_code, report_type,
period_end, rcept_no, rcept_dt, pit_as_of, fs_div, raw_sj_div,
statement_family, account_id, account_nm, account_detail, currency, value

현재 모듈은 이 pure selection/context 규칙만 제공하며 DB/cache/provider는
아직 구현하지 않는다.

==================================================
12. Secret-safe와 artifact policy
==================================================

모든 request audit URL은 crtfc_key=<REDACTED>로 기록한다.
실제 local key exact-string scan 결과:
- source / tests / 신규 architecture artifacts: 0건

신규 artifact:
- artifacts/fundamentals/opendart/validation/architecture_v01/opendart_pit_source_validation.json
- artifacts/fundamentals/opendart/validation/architecture_v01/opendart_statement_contract.json
- artifacts/fundamentals/opendart/validation/architecture_v01/opendart_account_mapping_diagnostic.json
- artifacts/fundamentals/opendart/validation/architecture_v01/opendart_architecture_manifest.json

raw XBRL ZIP/XML, 전체 financial JSON, API key, key fingerprint는 commit하지 않는다.
기록하는 것은 rcept/provenance, status, ZIP metadata/member names 일부,
byte length, hash, field/row/account diagnostic뿐이다.

==================================================
13. 구현 경계와 제한
==================================================

이번 단계에서 구현하지 않은 것:
- OpenDART Fundamentals provider / cache / filing registry persistence
- full XBRL taxonomy parser
- PIT normalized financial database
- annual/quarterly periodization
- growth, profitability, earnings trend
- Fundamentals Score, Pattern A/RS/Flow 합산
- PER/PBR/EV/EBITDA/PEG 및 valuation
- Stock Report v0.4
- Hegemony logic

bounded list probe에서 report chain key는 normalized report_nm을 사용했다. 전체
정정공시 chain의 공식 identity를 보장하는 resolver는 다음 implementation
boundary에서 별도 설계한다. chain identity가 불분명하면 AMBIGUOUS로 닫는다.

기존 access_v01 artifacts, Stock Reports, Pattern/Strategy source는 변경하지
않았다.

==================================================
14. 다음 구현 boundary
==================================================

Architect 승인 후 후보:
OPENDART_FUNDAMENTALS_V01_CORE_IMPLEMENTATION

우선순위:
1. corp_code cache
2. filing registry cache와 correction-chain rule
3. PIT resolver
4. filing-specific XBRL raw cache
5. CFS/OFS report-level selector
6. canonical non-financial account resolver
7. annual/quarterly period model

==================================================
15. Final status
==================================================

READY_FOR_ARCHITECT_OPENDART_FUNDAMENTALS_ARCHITECTURE_REVIEW
