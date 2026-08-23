opendart_fundamentals_v01_periodization_fix04.md

==================================================
OpenDART Fundamentals V01 Periodization FIX04
==================================================

목적
--------------------------------------------------
FIX03에서 남은 production boundary Major를 해결했다. Provider가 filing PIT
selection이 AMBIGUOUS인 prior filing을 facts에서 제외하면서 downstream이
MISSING으로 보이던 문제를 막고, filing-level prior state를 canonical
Periodization result까지 전파한다. PyKRX/KRX 네트워크와 Derived Metrics는
이번 범위가 아니다.

문제 원인과 수정
--------------------------------------------------
기존 `PeriodizationProvider.build()`는 anchor filing selection이 READY가
아니면 해당 filing을 skip했다. 따라서 하나금융지주 H1 2025의
`20250814003918`/`20250814004489` same-EOD ambiguity가 Q3 engine에 전달되지
않고, H1 facts가 비어 Q3가 MISSING 또는 derivation unavailable로 보일 수
있었다.

Provider는 이제 anchor별 `prior_pit` audit와 함께 다음을 engine에 전달한다.

| filing-level state | engine prior state | canonical 결과 |
|--------------------|--------------------|-----------------|
| READY | normal context selection | context가 1개일 때 derived 허용 |
| AMBIGUOUS | `PRIOR_AMBIGUOUS` | `PERIOD_AMBIGUOUS`, prior reason 보존 |
| DATA_UNAVAILABLE / FUTURE_FORBIDDEN | `PRIOR_MISSING` | derived fail-closed |

AMBIGUOUS일 때는 selected prior rcept_no를 만들지 않는다. same-filing
cumulative context ambiguity는 기존 FIX03의
`PRIOR_PIT_MULTIPLE_CURRENT_CUMULATIVE_CONTEXTS`로 계속 구분한다.

Provider audit contract
--------------------------------------------------
각 anchor selection에는 anchor report code/type, selected rcept_no/date,
status, reason, eligible count, future count와 `candidate_rcept_nos`가
기록된다. `prior_pit`에는 prior report code, status, canonical reason,
raw reason, selected prior identity와 candidate rcept_nos가 기록된다.
AMBIGUOUS prior의 selected identity는 항상 null이다.

DIRECT_ONLY 및 parity 정책
--------------------------------------------------
filing-level 또는 context-level prior가 AMBIGUOUS여도 현재 anchor에 unique
direct standalone이 있으면 `READY / DIRECT_ONLY`로 그 값을 보존한다. 이
경로는 prior source를 source array에 넣지 않고 parity도 만들지 않는다.
prior filing과 context가 모두 deterministic하고 coherence가 통과할 때만
`DIRECT_VALIDATED_BY_DERIVATION` 및 parity를 만든다. parity의 prior status는
READY이고 context count는 정확히 1이어야 한다.

Production Provider regression cases
--------------------------------------------------
`tests/test_opendart_fundamentals_periodization_fix04.py`는 모두
`PeriodizationProvider.build()`를 호출한다.

| case | 검증 |
|------|------|
| A | ambiguous H1 + Q3 cumulative only → Q3 `PERIOD_AMBIGUOUS`, same-EOD reason, parity 0 |
| B | ambiguous H1 + unique Q3 direct → `DIRECT_ONLY / READY`, parity 0 |
| C | READY H1 + Q3 direct/cumulative → validated derivation, MATCH parity |
| D | same-filing duplicate cumulative context 유지 |
| E | same-EOD multiple filing ambiguity 유지 |
| F | late correction이 earlier anchor ambiguity를 해소하지 않음 |

하나금융지주 production end-to-end
--------------------------------------------------
실제 OpenDART bounded live에서 `PeriodizationProvider.build()`를 사용했다.
H1 selection은 `AMBIGUOUS`, reason은 `MULTIPLE_FILINGS_ON_SAME_DATE`, 후보는
`20250814003918`와 `20250814004489`다. Q3 anchor의 prior도
`AMBIGUOUS / PRIOR_PIT_MULTIPLE_FILINGS_ON_SAME_EOD`이며 selected prior는
없다.

| Q3 metric | final method | status | parity |
|-----------|--------------|--------|--------|
| net_income | DIRECT_ONLY | READY | 없음 |
| operating_cash_flow | NONE | PERIOD_AMBIGUOUS | 없음 |

따라서 H1 ambiguity가 Q3에서 MISSING으로 변환되지 않고, direct가 있는
당기순이익만 안전하게 보존된다.

삼성전자 prior-context regression
--------------------------------------------------
삼성전자 Q1은 revenue, operating_income, net_income 각각 current cumulative
context 2개, distinct rcept_no 1개다. 세 metric의 Q2는 모두
`DIRECT_ONLY / READY`, prior context status는
`AMBIGUOUS / PRIOR_PIT_MULTIPLE_CURRENT_CUMULATIVE_CONTEXTS`, parity는
생성하지 않는다. Q3의 deterministic H1 prior parity 3건은 MATCH로
유지된다.

에스티팜 parity regression
--------------------------------------------------
에스티팜의 Q3 revenue, operating_income, net_income parity는 모두 MATCH다.
parity source는 READY prior filing 하나로 제한되고 source
rcept_no/date/SHA 배열 길이가 일치한다.

FINANCIAL branch
--------------------------------------------------
하나금융지주의 company family는 FINANCIAL이다. revenue와 operating_income은
NOT_APPLICABLE, net_income과 operating_cash_flow는 aggregate READY를
유지하면서 Q3 prior ambiguity는 fail-closed로 기록한다. assets,
liabilities, equity는 instant READY이고 CFS/OFS mixing은 없다.

Annual vintage 및 PIT 보호
--------------------------------------------------
Annual diagnostic은 annual receipt EOD 이하의 quarter vintage만 사용하며
annual direct FY authority를 대체하지 않는다. late correction은 correction
receipt가 도달하기 전 anchor의 prior source로 역사용되지 않는다.
`CURRENT_LATEST_historical_calls=0`, `future_correction_leakage=NO`를
검증한다.

Source provenance
--------------------------------------------------
직접 관측은 current filing source만 사용한다. derived source 배열은
`source_rcept_nos`, `source_rcept_dts`, `source_sha256s`가 같은 순서와
길이를 갖는다. AMBIGUOUS prior에는 selected prior를 source에 기록하지
않는다. Raw OpenDART ZIP/XML은 ignored cache에만 두고 artifact에 넣지
않는다.

Bounded live accounting
--------------------------------------------------
2026-08-24 실행에서 OpenDART list endpoint 12건을 사용했고 XBRL network
fetch는 0건, 기존 XBRL cache hit는 11건, validated filing은 11건이었다.
요청 상한은 30건이다. API key는 env 파일에서 프로세스 환경으로만 읽고
artifact에는 기록하지 않았다.

Artifact
--------------------------------------------------
`artifacts/fundamentals/opendart/validation/periodization_fix04/`에 다음을
생성했다.

- `periodization_fix04_summary.json`
- `periodization_fix04_manifest.json`
- `production_provider_prior_state_validation.json`
- `hana_provider_end_to_end_validation.json`
- `samsung_prior_context_validation.json`
- `live_company_summary.json`
- `live_period_context_matrix.csv`
- `live_direct_vs_derived_parity.csv`
- `annual_vintage_diagnostic_validation.json`
- `financial_company_validation.json`

Targeted test 및 PyKRX 제한
--------------------------------------------------
contract/core/core_fix01/core_fix02와 periodization V01/FIX01/FIX02/FIX03/
FIX04를 실행했고 결과는 104 passed, return code 0이다. 이번 작업에서는
PyKRX provider, `data.krx.co.kr`, KRX login 또는 관련 테스트를 실행·수정하지
않았다. Full Repo Suite는 지시 범위 밖이라 `NOT_RUN_BY_SCOPE`로 기록했다.

완료 기준
--------------------------------------------------
- provider ambiguous → missing count: 0
- provider prior state propagation: PASS
- parity prior ambiguity count: 0
- parity mismatch: 0, exact match: 6
- Samsung regression: PASS
- ST Pharm regression: PASS
- FINANCIAL branch: PASS
- Hana H1/Q3 production gate: PASS
- source provenance alignment: PASS
- secret leak: 0
- PyKRX/KRX network request: 0

최종 상태
--------------------------------------------------
`READY_FOR_ARCHITECT_OPENDART_FUNDAMENTALS_PERIODIZATION_FIX04_REVIEW`
