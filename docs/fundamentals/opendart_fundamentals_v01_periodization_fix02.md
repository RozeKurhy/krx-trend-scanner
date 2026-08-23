opendart_fundamentals_v01_periodization_fix02.md

==================================================
OpenDART Fundamentals V01 Periodization FIX02
==================================================

목적
--------------------------------------------------
FIX02는 과거 누적값을 하나로 결정할 수 없는 동일 EOD PIT 상황을
fail-closed로 고정하고, 하나금융지주 FINANCIAL branch를 실제 OpenDART
cohort에 포함해 검증한다. YoY, QoQ, TTM, growth, margin, score와
valuation은 이번 작업 범위에 없다.

Major #1: prior same-EOD ambiguity
--------------------------------------------------
`PeriodizationEngine._prior_cumulative_selection()`은 다음 순서로 동작한다.

1. anchor의 `rcept_dt`를 PIT cutoff으로 확정한다.
2. 직전 report code, 같은 fiscal year/metric, cumulative semantic, 유효한
   source만 `rcept_dt <= anchor.rcept_dt` 조건으로 수집한다.
3. 가장 최신 receipt EOD의 후보만 남긴다.
4. 그 EOD에 서로 다른 `rcept_no`가 2개 이상이면 `AMBIGUOUS`와
   `PRIOR_PIT_MULTIPLE_FILINGS_ON_SAME_EOD`를 반환한다. `rcept_no` lexical
   정렬이나 correction의 현재 존재를 근거로 winner를 고르지 않는다.
5. 후보가 하나면 `READY`, 후보가 없으면 `MISSING`이다.

따라서 H1이 Q1-A/Q1-B 중 하나를 과거 정보로 선택하지 못하는 경우 Q2는
`PERIOD_AMBIGUOUS`와 `value=null`이다. Q1-C가 나중에 접수되어도 Q2의
earlier same-EOD ambiguity를 해소하지 않는다. direct current context가
독립적으로 유효한 경우에는 direct-only evidence를 보존하지만, 누적 차감의
prior source는 계속 ambiguity로 차단한다.

변경 위치
--------------------------------------------------
| 파일 | 변경 |
|------|------|
| `src/trend_scanner/fundamentals/periodization.py` | 상태 기반 prior PIT 선택, ambiguity reason, 차감 차단 |
| `src/trend_scanner/fundamentals/period_models.py` | `PriorCumulativeSelection`, `source_rcept_dts` 모델 필드 |
| `src/trend_scanner/fundamentals/__init__.py` | 새 모델 export |
| `tests/test_opendart_fundamentals_periodization_fix02.py` | same-EOD, late correction, provenance 회귀 |
| `scripts/validate_opendart_periodization_fix02.py` | bounded live 검증, request accounting, artifact 생성 |

회귀 검증
--------------------------------------------------
| 케이스 | 결과 |
|--------|------|
| Q1-A/Q1-B가 2025-05-15에 동시 존재, H1은 2025-08-14 | Q2 `PERIOD_AMBIGUOUS`, reason exact match |
| Q1-C가 2025-10-01에 늦게 접수 | Q1 current는 Q1-C, Q2 ambiguity 유지 |
| Provider `prior_pit`와 Engine 결과 | `AMBIGUOUS` / `PERIOD_AMBIGUOUS` 정합 |
| source receipt provenance | `source_rcept_nos`, `source_rcept_dts`, `source_sha256s` 길이·순서 정렬 |

하나금융지주 live FINANCIAL validation
--------------------------------------------------
최종 실행은 `scripts/validate_opendart_periodization_fix02.py --live`로
수행했고, API key는 환경에서만 읽었다. 최종 artifact 기준으로 Q1/Q3/Annual
세 filing의 filing-specific XBRL을 CFS로 파싱했다. H1은 원본과 정정본이
동일 receipt EOD에 존재해 PIT resolver가 `AMBIGUOUS`로 종료했으며,
임의 XBRL winner를 만들지 않았다.

| report | status | rcept_no / source SHA |
|--------|--------|-----------------------|
| Q1 | READY | `20250515002336` / `61723a55aa82344f505779c596639f21845d6e3d1179d120370f6646eb41033e` |
| H1 | AMBIGUOUS | candidates `20250814003918`, `20250814004489`; selected SHA 없음 (PIT ambiguity로 parser 미실행) |
| Q3 | READY | `20251114002661` / `af590d9ff03fe04188bc149b314f95a0306fd9e6e559ead33d0cc0f90fc10c75` |
| Annual | READY | `20260316001292` / `e7d5f224b7b1b9619bd3f927b6b588496b10df91ac5c2603efa31ffe83779efb` |

| 검증 항목 | 결과 |
|-----------|------|
| company family | `FINANCIAL` |
| revenue | `NOT_APPLICABLE` (FINANCIAL report-level policy) |
| operating income | `NOT_APPLICABLE` (FINANCIAL report-level policy) |
| net income | READY observations 4, `PERIOD_AMBIGUOUS` 1, `DATA_UNAVAILABLE` 1; aggregate status READY |
| operating cash flow | READY 5, `DERIVATION_UNAVAILABLE` 1; aggregate status READY |
| assets / liabilities / equity | instant context 각각 READY 3 |
| basis | CFS only; CFS/OFS mixing 없음 |
| comparative | 34 comparative contexts는 보존하되 canonical periodization에서 제외 |
| current ambiguity | 1; fail-closed 유지 |

`revenue`가 해당 live filing에서 canonical observation을 만들지 못해도
FINANCIAL 계약상 non-financial metric은 `NOT_APPLICABLE`이다. 반대로
net income/OCF 및 instant metric은 실제 context와 resolution status를
그대로 남겨 `DATA_UNAVAILABLE`, `DERIVATION_UNAVAILABLE` 또는
`PERIOD_AMBIGUOUS`를 숨기지 않는다.

Live request accounting
--------------------------------------------------
최종 bounded 실행의 authority는 FIX02 summary/manifest다. registry와
filing-specific XBRL artifact를 별도 집계했으며, 같은 filing의 cache hit를
network request로 중복 계산하지 않았다.

| 항목 | 실제 값 |
|------|---------|
| network_request_count | 12 |
| registry_request_count | 12 |
| xbrl_network_fetch_count | 0 |
| xbrl_cache_hit_count | 11 |
| validated_filing_count | 11 |
| request limit | 30 |

기존 FIX01 문서의 `총 OpenDART 요청 12건` 표현은 historical artifact와
불일치했으므로 `docs/fundamentals/opendart_fundamentals_v01_periodization_fix01.md`
에서 `network 8 / registry 8`로 정정했다. FIX01 artifact 자체는 historical
evidence이므로 overwrite하지 않았다.

Samsung / ST Pharm regression
--------------------------------------------------
삼성전자와 에스티팜의 기존 direct-derived parity는 12건 exact match,
mismatch 0이다. OCF context regression은 없고, 최종 FIX02 live summary는
전체 226 context rows(현재 98, comparative 128), cumulative 51,
standalone 90, duplicate current ambiguity 10을 기록한다.

Source receipt-date provenance
--------------------------------------------------
`PeriodizedFinancialObservation`에 `source_rcept_dts`를 추가했고 기존
positional constructor 호환을 위해 dataclass 마지막에 append했다. 각
source 배열은 동일한 source 순서를 유지한다.

예: 삼성전자 2025 Q2 revenue direct/derived parity

    anchor_rcept_no: 20250814003156
    anchor_rcept_dt: 20250814
    source_rcept_nos: [20250814003156, 20250515001922]
    source_rcept_dts: [20250814, 20250515]
    source_sha256s: [<H1 SHA>, <Q1 SHA>]

실제 수치와 SHA는 `live_direct_vs_derived_parity.csv` 및
`live_company_summary.json`에서 확인한다. source SHA가 없는 fixture도
배열 위치를 유지하기 위해 빈 문자열로 보존한다.

검증 산출물
--------------------------------------------------
`artifacts/fundamentals/opendart/validation/periodization_fix02/`:

- `periodization_fix02_summary.json`
- `periodization_fix02_manifest.json`
- `production_prior_ambiguity_validation.json`
- `live_company_summary.json`
- `live_period_context_matrix.csv`
- `live_direct_vs_derived_parity.csv`
- `annual_vintage_diagnostic_validation.json`
- `financial_company_validation.json`

Targeted test provenance
--------------------------------------------------
실행 명령:

    /Users/june/Documents/projects/krx-trend-scanner/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_opendart_fundamentals_contract.py tests/test_opendart_fundamentals_core.py tests/test_opendart_fundamentals_core_fix01.py tests/test_opendart_fundamentals_core_fix02.py tests/test_opendart_fundamentals_periodization_v01.py tests/test_opendart_fundamentals_periodization_fix01.py tests/test_opendart_fundamentals_periodization_fix02.py

결과: 92 passed, return code 0.

Full Repo Suite 및 제한사항
--------------------------------------------------
이번 작업에서는 PyKRX/KRX 웹 엔드포인트에 신규 요청을 하지 않았다.
Full Repo Suite는 non-PyKRX 구간에서 88 passed, 5 deselected까지 확인한
뒤 장시간 pandas 연산에서 KeyboardInterrupt로 중단했다. 기존 실행에서
확인된 외부 blocker는 `tests/test_pykrx_provider.py`의
`data.krx.co.kr` DNS/login `requests.exceptions.ConnectionError`이며,
이번 FIX02의 OpenDART 변경과 무관하다. 사용자 지시에 따라 PyKRX 테스트를
추가 재시도하거나 우회하지 않았다.

OpenDART의 `CURRENT_LATEST` historical call은 0이고,
`future_correction_leakage`는 `NO`다. API key secret leak은 0이며 raw
OpenDART ZIP/XML은 ignored cache에만 있고 commit하지 않는다. Annual
vintage diagnostic에서 Q1/Q2/Q3가 부족한 경우도 숫자를 보간하지 않고
`DIAGNOSTIC_UNAVAILABLE`로 남긴다.

최종 상태
--------------------------------------------------
`READY_FOR_ARCHITECT_OPENDART_FUNDAMENTALS_PERIODIZATION_FIX02_REVIEW`

이 상태는 prior ambiguity fail-closed, Hana FINANCIAL live 정책, 기존
parity/mismatch, targeted test, secret/raw-source 조건을 모두 만족한다는
뜻이다. Full Repo Suite의 PyKRX 외부 blocker는 별도 인프라 조건으로
Architect review에서 확인한다.
