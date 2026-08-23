opendart_fundamentals_v01_periodization.md

==================================================
OpenDART Fundamentals V01 Periodization
==================================================

목적
--------------------------------------------------
Core가 선택한 filing-specific XBRL facts를 fiscal period semantics로
정리한다. 이 단계는 기간 의미와 PIT provenance만 다루며 YoY, QoQ, TTM,
growth, margin, Score, valuation, Stock Report는 구현하지 않는다.

경계와 authority
--------------------------------------------------
    list.json registry
      -> PITResolver(as_of)
      -> selected rcept_no
      -> filing-specific fnlttXbrl.xml
      -> period_context_rows
      -> PeriodizationEngine

Report code는 filing sequence를 표시할 뿐 economic period amount semantics를
결정하지 않는다. actual XBRL `period_start`, `period_end`, instant/duration,
primary context와 report sequence를 함께 사용한다. 비교 context는 current
candidate에서 제외한다.

Period semantics
--------------------------------------------------
| 의미 | 대상 | 처리 |
|------|------|------|
| INSTANT | assets/liabilities/equity | report-date snapshot, subtraction 금지 |
| CUMULATIVE_YTD | Q1/H1/9M/FY flow | fiscal start부터 current end 누적 |
| STANDALONE_QUARTER | Q1/Q2/Q3/Q4 flow | 해당 분기 자체의 duration |

Q1 cumulative은 실제 fiscal start부터의 정상 current context가 확인될 때
`DIRECT_EQUIVALENT_YTD` standalone으로 표현한다. H1은 H1 cumulative와 Q2
direct context를 각각 보존한다. Q3는 9M cumulative와 Q3 direct를 구분한다.
Annual FY는 annual current full-year duration을 직접 authority로 유지한다.

Direct / derived 정책
--------------------------------------------------
- Q2 = H1 cumulative - Q1 cumulative
- Q3 = 9M cumulative - H1 cumulative
- Q4 = FY cumulative - 9M cumulative
- direct와 derived가 모두 있고 exact match면 `DIRECT_VALIDATED_BY_DERIVATION`
- 불일치면 `DIRECT_DERIVED_MISMATCH`로 canonical value를 만들지 않는다.
- direct만 명확하면 `DIRECT_ONLY`, derived만 coherence gate를 통과하면
  `DERIVED_DIFFERENCE`를 사용한다.
- missing/ambiguous/NOT_FOUND/NOT_APPLICABLE는 0으로 바꾸지 않는다.
- 음수 derived value는 유효한 값으로 보존한다.

Coherence gate
--------------------------------------------------
차감에는 ticker, corp_code, fiscal_year, metric, company_family,
fiscal_year_start, fs_div_used, currency, chronological period, RESOLVED
source가 모두 일치해야 한다. CFS/OFS 또는 currency가 다르면 각각
`BASIS_MISMATCH`/`CURRENCY_MISMATCH`로 fail-closed한다. FX conversion은
구현하지 않는다.

Anchor vintage와 correction
--------------------------------------------------
Q1/Q2/Q3/Q4 anchor는 각각 Q1/H1/Q3/Annual filing이다. 차감에 쓰는 이전
cumulative version은 anchor filing의 `rcept_dt` 시점에 이용 가능했던 최신
version만 선택한다. 따라서 H1 anchor 뒤에 접수된 Q1 correction은 과거 Q2를
retroactive하게 바꾸지 않는다. H1/Q3/Annual correction은 새 anchor version을
만들 수 있다. `rcept_dt <= as_of`만 eligible이므로 wider cache의 future
correction leakage도 없다.

Fiscal year와 비표준 기간
--------------------------------------------------
`fiscal_year`와 `fiscal_year_start`는 context/fixture metadata에서 보존한다.
Gregorian 3/6/9/12월을 authority로 하드코딩하지 않는다. 결산월이 12월이
아닌 synthetic fixture는 실제 period dates로 처리한다. 표준 duration 범위를
벗어난 stub/결산월 변경 기간은 `PERIODIZATION_UNSUPPORTED`로 fail-closed한다.

Partial series와 금융업
--------------------------------------------------
Q1 filing이 없어도 H1 filing 내부의 명확한 Q2 direct context는 `DIRECT_ONLY`
로 보존할 수 있다. fiscal year 전체를 무조건 invalid 처리하지 않는다.
UNKNOWN company family는 fail-closed하며, FINANCIAL family의 revenue와
operating_income은 `NOT_APPLICABLE`이다.

검증
--------------------------------------------------
    PYTHONDONTWRITEBYTECODE=1 PYTHONWARNINGS=ignore .venv/bin/pytest -q -p no:cacheprovider \
      tests/test_opendart_fundamentals_contract.py \
      tests/test_opendart_fundamentals_core.py \
      tests/test_opendart_fundamentals_core_fix01.py \
      tests/test_opendart_fundamentals_core_fix02.py \
      tests/test_opendart_fundamentals_periodization_v01.py

결과는 80개 PASS다. 이번 작업은 offline synthetic fixture와 기존 local
cache 경계를 사용했고 live OpenDART 요청은 실행하지 않았다. 삼성전자,
에스티팜, 하나금융지주 live cohort는 다음 bounded validation에서 실제
filing context를 재확인해야 한다.

다음 단계
--------------------------------------------------
Periodization review 승인 후에만 Derived Metrics 단계에서 Quarterly/Annual
YoY, TTM, growth와 margin을 추가한다.
