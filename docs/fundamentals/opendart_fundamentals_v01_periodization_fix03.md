opendart_fundamentals_v01_periodization_fix03.md

==================================================
OpenDART Fundamentals V01 Periodization FIX03
==================================================

목적
--------------------------------------------------
FIX02에서 남은 Major를 해결했다. 하나의 filing(`rcept_no`)만 있어도 그
filing 내부의 valid current cumulative context가 여러 개면 canonical prior
fact를 하나로 결정할 수 없으므로 derived quarter를 생성하지 않는다.
YoY, QoQ, TTM, growth, margin, valuation과 Stock Report 연동은 이번 범위가
아니다.

FIX02에서 발견된 문제
--------------------------------------------------
FIX02는 동일 EOD에 서로 다른 filing이 여러 개일 때만 prior를 차단했다.
하지만 삼성전자 FY2025 Q1처럼 같은 `rcept_no=20250515001922` 안에도
동일 current cumulative 기간의 context가 revenue, operating_income,
net_income별로 2개씩 존재한다. 기존 선택은 filing 번호가 하나라는 이유로
`latest[0]`을 사용할 수 있었고, Q2 derived parity를 만들었다.

Filing ambiguity와 context ambiguity
--------------------------------------------------
| 구분 | 조건 | 결과 |
|------|------|------|
| filing ambiguity | 최신 receipt EOD에 서로 다른 `rcept_no`가 2개 이상 | `PRIOR_PIT_MULTIPLE_FILINGS_ON_SAME_EOD` |
| context ambiguity | 선택된 하나의 `rcept_no` 안에 valid cumulative context가 2개 이상 | `PRIOR_PIT_MULTIPLE_CURRENT_CUMULATIVE_CONTEXTS` |

두 경우 모두 `AMBIGUOUS`이며 prior source를 provenance에 임의 기록하지
않는다. 값이 같거나 period start/end가 같아도 dedupe하지 않는다.

새 prior selection algorithm
--------------------------------------------------
`PeriodizationEngine._prior_cumulative_selection()`은 다음 순서를 지킨다.

1. prior report code의 cumulative, valid source를 anchor receipt EOD 이하에서
   수집한다.
2. 가장 최신 receipt EOD만 남긴다.
3. 최신 EOD의 distinct `rcept_no`가 여러 개면 filing ambiguity로 종료한다.
4. `rcept_no` 하나 안의 latest valid cumulative context 수가 2개 이상이면
   context ambiguity로 종료한다.
5. 정확히 하나일 때만 `READY` selected fact를 반환한다.

`latest[0]`, first fact, lexical context_ref, context 순서, value equality는
selection authority로 사용하지 않는다.

DIRECT_ONLY preservation policy
--------------------------------------------------
prior가 `AMBIGUOUS`여도 anchor에 valid direct standalone context가 정확히
하나면 direct 값은 보존한다.

    prior cumulative: AMBIGUOUS
    direct standalone: unique
    result: READY / DIRECT_ONLY
    derived value: null
    parity: 미생성

direct standalone도 없거나 여러 개면 `PERIOD_AMBIGUOUS`다. 따라서 parity
count가 FIX02의 12에서 FIX03의 6으로 줄어든 것은 regression이 아니라
ambiguous prior source를 제거한 PIT-safe 결과다.

회귀 테스트
--------------------------------------------------
신규 `tests/test_opendart_fundamentals_periodization_fix03.py`에서 다음을
검증했다.

| 케이스 | 결과 |
|--------|------|
| same filing + same-value duplicate cumulative | Q1/Q2 ambiguity, parity 0 |
| same filing + different-value duplicate cumulative | Q2 `PERIOD_AMBIGUOUS`, parity 0 |
| ambiguous prior + unique direct Q2 | `DIRECT_ONLY`, READY, parity 0 |
| unique prior + direct Q2 | `DIRECT_VALIDATED_BY_DERIVATION`, MATCH |
| same-EOD multiple filings | 기존 FIX02 reason 유지 |
| late correction | earlier Q2 ambiguity 유지 |

삼성전자 live 결과
--------------------------------------------------
FY2025 Q1 filing `20250515001922`에서 세 metric 모두 current cumulative
context count가 2이고 distinct rcept_no count는 1이다.

| metric | Q1 contexts | prior status | Q2 final method | Q2 parity |
|--------|-------------|--------------|-----------------|------------|
| revenue | 2 | AMBIGUOUS / `PRIOR_PIT_MULTIPLE_CURRENT_CUMULATIVE_CONTEXTS` | DIRECT_ONLY | 없음 |
| operating_income | 2 | AMBIGUOUS / `PRIOR_PIT_MULTIPLE_CURRENT_CUMULATIVE_CONTEXTS` | DIRECT_ONLY | 없음 |
| net_income | 2 | AMBIGUOUS / `PRIOR_PIT_MULTIPLE_CURRENT_CUMULATIVE_CONTEXTS` | DIRECT_ONLY | 없음 |

Q3의 H1 prior는 deterministic해서 삼성전자 Q3 parity 3건은 MATCH로
유지됐다. Q2의 direct standalone은 값이 있어 보존했지만 Q1 cumulative를
prior로 사용하지 않았다.

ST Pharm regression
--------------------------------------------------
에스티팜도 Q1 duplicate cumulative context가 있어 Q2는 direct-only로
보존되고, Q3의 unique H1 prior parity 3건은 MATCH다. ambiguous prior만
차단했으며 derived quarter 전체를 비활성화하지 않았다.

Hana FINANCIAL regression
--------------------------------------------------
하나금융지주 086790의 FINANCIAL 정책은 FIX02와 동일하게 유지했다.

| 항목 | 결과 |
|------|------|
| company_family | FINANCIAL |
| revenue / operating_income | NOT_APPLICABLE |
| net_income | READY aggregate, current ambiguity fail-closed 포함 |
| operating_cash_flow | READY aggregate, DERIVATION_UNAVAILABLE 보존 |
| assets/liabilities/equity | instant READY |
| H1 | 동일 EOD multiple filing `AMBIGUOUS` |
| CFS/OFS mixing | 없음 |

Validation artifact
--------------------------------------------------
`artifacts/fundamentals/opendart/validation/periodization_fix03/`에 다음을
생성했다.

- `periodization_fix03_summary.json`
- `periodization_fix03_manifest.json`
- `prior_context_ambiguity_validation.json`
- `live_company_summary.json`
- `live_period_context_matrix.csv`
- `live_direct_vs_derived_parity.csv`
- `samsung_prior_context_validation.json`
- `annual_vintage_diagnostic_validation.json`
- `financial_company_validation.json`

최종 bounded live accounting은 network 12건, registry 12건, XBRL network
fetch 0건, XBRL cache hit 11건, validated filing 11건이다. API key는 환경에서
읽었고 artifact에 쓰지 않았다.

Parity invariants
--------------------------------------------------
- parity_count: 6
- exact_match_count: 6
- mismatch_count: 0
- ambiguous_prior_parity_count: 0
- 모든 parity prior context count: 1
- source_rcept_nos/dts/SHA length alignment: PASS
- CURRENT_LATEST historical calls: 0
- future_correction_leakage: NO

Targeted test provenance
--------------------------------------------------
실행 파일은 contract/core/core_fix01/core_fix02와 periodization V01/FIX01/
FIX02/FIX03이다. 실제 결과는 98 passed, return code 0이다.

Full Repo Suite / PyKRX 제한
--------------------------------------------------
이번 작업에서는 PyKRX/KRX 웹 엔드포인트에 신규 네트워크 요청을 수행하지
않았다. Full Repo Suite도 실행하지 않고 targeted OpenDART suite를 authority로
사용했다. PyKRX provider 코드 변경이나 network monkey patch는 없다.

Known limitations
--------------------------------------------------
- 삼성전자와 에스티팜 Q1 duplicate context는 source XBRL의 실제 context다.
  같은 값이어도 임의 dedupe하지 않는다.
- 하나금융 H1 원본·정정본 same EOD ambiguity는 계속 해결하지 않는다.
- Annual diagnostic은 diagnostic only이며 Annual direct FY authority를
  quarter sum으로 대체하지 않는다.
- Derived Metrics는 다음 단계에서만 검토한다.

최종 상태
--------------------------------------------------
`READY_FOR_ARCHITECT_OPENDART_FUNDAMENTALS_PERIODIZATION_FIX03_REVIEW`
