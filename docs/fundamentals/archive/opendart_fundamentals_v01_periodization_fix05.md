opendart_fundamentals_v01_periodization_fix05.md

==================================================
OpenDART Fundamentals V01 Periodization FIX05
==================================================

목적
--------------------------------------------------
FIX04가 현재 snapshot의 prior filing AMBIGUOUS를 downstream ambiguity로
보존했다면, FIX05는 반대 방향의 historical-vintage gap을 해결한다.
현재 requested_as_of에서 H1이 AMBIGUOUS여도 Q3 receipt EOD 당시 H1-A가
READY였다면 H1-A filing-specific XBRL fact를 materialize해 Q3 derivation에
사용한다. Derived Metrics와 PyKRX/KRX는 범위가 아니다.

FIX04 gap
--------------------------------------------------
Provider는 현재 report selection이 READY가 아니면 해당 report code의
filing-specific facts를 모두 skip했다. 이후 Q3 anchor의 prior PIT가
2025-11-14 기준 H1-A READY라고 판단해도 facts가 없어
`MISSING_PRIOR_CUMULATIVE`로 downgrade될 수 있었다.

현재 snapshot과 anchor vintage
--------------------------------------------------
두 selection은 독립적이다.

| 구분 | 기준 | 역할 |
|------|------|------|
| current snapshot | requested_as_of | 현재 canonical report 상태 |
| historical anchor prior | later anchor receipt EOD | 해당 시점의 prior source authority |

현재 H1이 H1-B/H1-C same-EOD로 AMBIGUOUS여도 Q3 receipt 이전에는 H1-A만
있었다면 Q3 prior는 READY(H1-A)다. H1-A를 materialize해도 current H1
canonical 상태를 READY로 승격하지 않는다.

Materialization 정책
--------------------------------------------------
Provider build 순서는 다음과 같다.

1. 모든 report code의 current PIT selection과 audit metadata를 계산한다.
2. current READY report의 eligible filing versions를 기존대로 materialize한다.
3. 각 READY anchor에 대해 anchor receipt EOD의 prior PIT를 계산한다.
4. prior가 READY이고 selected filing이 있으면 해당 filing을 확인한다.
5. 아직 materialize하지 않은 `(reprt_code, rcept_no)`만 XBRL fetch/cache-read,
   basis selection, context extraction, `facts_from_xbrl_rows()`를 수행한다.
6. facts를 engine에 전달하되 current snapshot state도 함께 전달한다.

Historical source가 current report code의 AMBIGUOUS facts인 경우 engine은
그 report code의 current observation을 만들지 않고, later anchor의 prior
selection에는 해당 fact를 사용할 수 있다.

Materialization dedupe
--------------------------------------------------
한 build 안에서 `(reprt_code, rcept_no)` set을 유지한다. current eligible
materialization과 historical prior materialization이 겹치면 XBRL 작업을
반복하지 않고 `ALREADY_MATERIALIZED` audit reason을 기록한다.

Provider audit
--------------------------------------------------
기존 current selection과 `prior_pit` 필드는 유지한다. `prior_pit`에 다음
필드를 추가했다.

- `historical_source_materialized`
- `historical_source_materialization_reason`
- `historical_source_fact_count`
- `historical_source_sha256`

READY prior에서 source materialization이 실패하면 audit과 invariant가 이를
포착한다. selected prior identity는 current ambiguity와 섞이지 않는다.

Engine semantics
--------------------------------------------------
FIX04의 `prior_pit_states`는 유지된다.

| provider prior | engine |
|----------------|--------|
| AMBIGUOUS | `PRIOR_AMBIGUOUS` |
| MISSING | `PRIOR_MISSING` |
| READY | materialized historical facts로 context/coherence 검증 |

current PIT state를 별도로 engine에 전달해 current AMBIGUOUS report code의
canonical observation이 historical source로 덮어써지지 않게 했다.

Synthetic production-provider cases
--------------------------------------------------
`tests/test_opendart_fundamentals_periodization_fix05.py`는 모두
`PeriodizationProvider.build()`를 사용한다.

| case | 기대 결과 |
|------|-----------|
| A | current H1 AMBIGUOUS, historical H1-A READY materialized, Q3 cumulative-only `DERIVED_DIFFERENCE / READY`, value 50 |
| B | Q3 direct 50 + derived 50 → `DIRECT_VALIDATED_BY_DERIVATION`, MATCH 1 |
| C | Q3 source는 Q3/H1-A만 포함하고 date/SHA 배열이 정렬됨 |
| D | H1-A materialization 이후에도 current H1 AMBIGUOUS 유지 |
| E | Q3 이전 H1 same-EOD ambiguity는 derived 차단 |
| F | historical H1-A 내부 duplicate cumulative context는 context ambiguity 유지 |
| G | Q3 이후 H1-B/H1-C correction은 Q3 provenance에 유입되지 않음 |

Historical READY 결과
--------------------------------------------------
synthetic Case A의 결과는 다음과 같다.

- current H1: `AMBIGUOUS`
- Q3 prior: `READY`, selected `H1-A`
- H1-A fact: materialized
- Q3 cumulative-only: value 50, `DERIVED_DIFFERENCE / READY`
- parity: 0
- H1-A XBRL materialization: build당 1회

Case B는 direct 50을 같은 historical derived 값으로 검증해
`DIRECT_VALIDATED_BY_DERIVATION / READY`, `MATCH` parity 1을 만든다.

READY → MISSING invariant
--------------------------------------------------
`provider_ready_to_missing_count`는 provider anchor-specific prior가 READY인데
historical fact가 없어 `MISSING_PRIOR_CUMULATIVE`,
`DERIVATION_UNAVAILABLE`, `DATA_UNAVAILABLE`로 downgrade된 건수다.
정상 기준은 0이다. FIX04의 `provider_ambiguous_to_missing_count`도 0을
유지한다.

Samsung regression
--------------------------------------------------
삼성전자 Q1 revenue, operating_income, net_income은 각각 current cumulative
context 2개와 distinct rcept_no 1개다. Q2는 세 metric 모두
`DIRECT_ONLY / READY`, prior context ambiguity reason
`PRIOR_PIT_MULTIPLE_CURRENT_CUMULATIVE_CONTEXTS`, parity 없음이다.
deterministic H1 prior를 사용하는 Q3 parity는 유지한다.

ST Pharm regression
--------------------------------------------------
에스티팜 Q3 revenue, operating_income, net_income parity는 모두 MATCH다.
모든 emitted parity의 prior filing은 READY이고 context count는 1이다.

Hana regression
--------------------------------------------------
하나금융지주 H1은 `AMBIGUOUS`, Q3 prior도
`AMBIGUOUS / PRIOR_PIT_MULTIPLE_FILINGS_ON_SAME_EOD`다. H1 후보 중 하나를
historical READY로 강제 선택하지 않는다. Q3 net_income은
`DIRECT_ONLY / READY`, parity false이고 OCF는 `PERIOD_AMBIGUOUS`, parity
false다.

FINANCIAL regression
--------------------------------------------------
company_family은 FINANCIAL이다. revenue와 operating_income은
NOT_APPLICABLE, net_income과 operating_cash_flow는 기존 fail-closed
aggregate 정책을 유지한다. assets/liabilities/equity는 instant READY이며
CFS/OFS mixing은 false다.

Parity 및 provenance
--------------------------------------------------
모든 emitted parity는 prior filing PIT READY와 context count 1을 만족해야
한다. mismatch는 `DIRECT_DERIVED_MISMATCH`로만 fail-closed한다.
Derived observation의 `source_rcept_nos`, `source_rcept_dts`,
`source_sha256s`는 같은 순서와 길이를 갖는다. Historical READY source인
H1-A는 Q3 provenance에 들어가고 현재 correction H1-B/H1-C는 들어가지
않는다.

Annual 및 historical 보호
--------------------------------------------------
Annual diagnostic은 annual receipt EOD 이하의 quarter vintage만 사용한다.
`CURRENT_LATEST_historical_calls=0`, `future_correction_leakage=NO`를
검증한다. Annual direct authority를 quarter sum으로 대체하지 않는다.

Live validation
--------------------------------------------------
Samsung, ST Pharm, Hana FY2025를 실제 production `PeriodizationProvider.build()`
경계로 bounded OpenDART 재검증한다. live cohort에서 current AMBIGUOUS +
historical READY 조합이 없어도 synthetic provider acceptance가 이를
검증한다.

Network 및 보안
--------------------------------------------------
OpenDART list/XBRL bounded live만 허용한다. PyKRX/KRX provider, KRX web
endpoint, login, 기존 PyKRX tests는 실행·수정하지 않는다. API key는 환경에서
읽고 artifact에 쓰지 않는다. Raw ZIP/XML은 ignored cache에만 둔다.

Artifact
--------------------------------------------------
`artifacts/fundamentals/opendart/validation/periodization_fix05/`에 다음을
생성한다.

- `periodization_fix05_summary.json`
- `periodization_fix05_manifest.json`
- `historical_ready_materialization_validation.json`
- `production_provider_vintage_validation.json`
- `hana_provider_end_to_end_validation.json`
- `samsung_prior_context_validation.json`
- `live_company_summary.json`
- `live_period_context_matrix.csv`
- `live_direct_vs_derived_parity.csv`
- `annual_vintage_diagnostic_validation.json`
- `financial_company_validation.json`

Known limitations
--------------------------------------------------
- Historical source materialization은 같은 build의 known filing rows 안에서만 수행한다.
- Current snapshot AMBIGUOUS는 historical source가 있어도 canonical READY로
  바꾸지 않는다.
- Derived Metrics, YoY/QoQ/TTM/growth/margin/valuation과 Stock Report 연동은
  후속 작업이다.
- Full Repo Suite는 PyKRX/KRX 금지 범위 때문에 `NOT_RUN_BY_SCOPE`로 남긴다.

최종 상태 기준
--------------------------------------------------
historical materialization PASS, READY→MISSING 0, AMBIGUOUS→MISSING 0,
current ambiguity 보존, provenance alignment PASS, Samsung/ST/Hana/FINANCIAL
regression PASS, parity ambiguity 0, mismatch 0, future leakage NO, targeted
tests PASS, PyKRX/KRX network 0, secret leak 0, raw source 미커밋일 때만
다음 상태를 사용한다.

`READY_FOR_ARCHITECT_OPENDART_FUNDAMENTALS_PERIODIZATION_FIX05_REVIEW`
