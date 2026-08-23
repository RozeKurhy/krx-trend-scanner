opendart_fundamentals_v01_periodization_fix01.md

==================================================
OpenDART Fundamentals V01 Periodization FIX01
==================================================

목적
--------------------------------------------------
엔진에 이미 전달된 fact 목록만 periodize하는 것과 실제 운영 파이프라인이
PIT-safe fact 목록을 구성하는 것은 다른 문제다. 이번 FIX는 registry와
filing-specific XBRL을 연결하는 production provider, 실제 context 검증,
연간 diagnostic vintage 정렬을 추가한다. YoY, QoQ, TTM, growth, margin,
score, valuation은 이 단계에 포함하지 않는다.

Production pipeline
--------------------------------------------------
    CorpCodeRepository
      -> FilingRegistry.list_regular_filings(as_of)
      -> PITResolver(anchor selection)
      -> XbrlRepository.fetch(rcept_no, reprt_code)
      -> period_context_rows(primary contexts)
      -> facts_from_xbrl_rows
      -> PeriodizationProvider
      -> PeriodizationEngine

`PeriodizationProvider`는
`src/trend_scanner/fundamentals/periodization_provider.py`에 있다. 요청한
EOD보다 미래인 filing은 제거하고, 현재 anchor만 쓰는 latest shortcut 대신
그 EOD까지 접수된 모든 filing version을 엔진에 전달한다. XBRL cache는
`rcept_no`와 SHA를 키로 재사용한다. 과거 이력에서
`CURRENT_LATEST` endpoint를 호출하지 않는다.

Anchor-specific PIT
--------------------------------------------------
| Anchor | 이전 누적 source | 선택 기준 |
|--------|------------------|----------|
| Q1     | 없음             | Q1 filing receipt |
| H1/Q2  | Q1              | H1 receipt 이하 최신 Q1 |
| Q3     | H1               | Q3 receipt 이하 최신 H1 |
| Annual/Q4 | Q3            | Annual receipt 이하 최신 Q3 |

Provider가 anchor마다 PITResolver를 호출해 선택 결과를 audit metadata로
남기고, 엔진은 같은 `rcept_dt <= anchor.rcept_dt` gate를 fact source에서
다시 적용한다. 따라서 현재 Q1 correction이 보여도 H1 anchor 이전 Q1
original은 보존된다. anchor 자체의 correction은 별도 periodized version을
만든다. `rcept_dt == requested_as_of`는 AVAILABLE_AT_EOD로 취급한다.

Source provenance
--------------------------------------------------
모든 canonical observation은 anchor `rcept_no`/receipt와 source
`rcept_no` 목록, source XBRL SHA, `fs_div_used`, currency를 보존한다. CFS와
OFS context는 filing별로 하나의 basis만 선택하며, 자동 혼합하지 않는다.
source가 모호하거나 current context가 여러 개면 값 대신
`PERIOD_AMBIGUOUS`/`DIRECT_DERIVED_MISMATCH`로 fail-closed한다.

Context semantics
--------------------------------------------------
현재 XBRL validation은 report code를 기간의 권위로 쓰지 않는다. 실제
`period_start`, `period_end`, instant/duration, primary context, comparative
flag를 사용한다.

- instant metric(자산/부채/자본)은 snapshot이다.
- fiscal start부터 current end인 duration은 cumulative YTD다.
- fiscal start가 아닌 current duration은 standalone quarter 후보이다.
- 비교 context는 같은 account라도 canonical candidate에서 제외한다.
- 같은 period end의 두 current duration은 보존하고, 단일 후보를 임의로
  고르지 않는다.

실제 live validation
--------------------------------------------------
실행 스크립트:

    scripts/validate_opendart_periodization_fix01.py --live \
      --env-file /Users/june/Documents/projects/env.md

bounded window로 삼성전자(005930)와 에스티팜(237690)의 FY2025 Q1/H1/Q3/
Annual filing-specific XBRL을 확인했다. 총 OpenDART 요청은 12건(최대 30),
context row는 168건이다. Hana(086790)는 기존 Annual cache만 있는
`OFFLINE_CACHE_ONLY` control로 기록했으며 bounded live cohort에는 넣지
않았다.

| 항목 | 결과 |
|------|------|
| live filing | Samsung 4종, ST Pharm 4종 |
| current context rows | 74 |
| comparative context rows | 94 |
| cumulative candidates | 38 |
| standalone candidates | 70 |
| direct-derived exact match | 12 |
| mismatch | 0 |
| 동일 current context ambiguity | 6 duplicate rows (Q1 income metrics) |
| CFS/OFS mixing | 없음; CFS만 선택 |
| historical CURRENT_LATEST | 0 |
| secret leak | 0 |

H1과 Q3에서는 실제 current cumulative 및 standalone duration이 함께
관찰되었고, revenue/operating income/net income은 Q2/Q3 direct와 cumulative
차감이 모두 exact match했다. OCF context도 두 회사에서 확인했다. Annual은
full-year current duration으로 보존하고 Q4 계산의 authority로 사용한다.
실제 current context가 여러 개인 Q1 income metric은 임의 선택하지 않고
ambiguity로 남겼다. 이는 heuristic을 완화하지 않고 실제 XBRL 구조를
우선한 결과다.

Annual diagnostic vintage
--------------------------------------------------
Annual-vs-quarter sum은 투자 지표가 아니라 diagnostic이다. 각 Annual
anchor version마다 다음을 독립적으로 수행한다.

1. Annual receipt 이하에서 Q1/Q2/Q3의 최신 READY version을 찾는다.
2. Q4는 같은 Annual `rcept_no`가 만든 Q4만 사용한다.
3. 같은 EOD에 여러 filing이 남아 primary candidate가 하나가 아니면
   `PERIOD_AMBIGUOUS`로 기록한다.
4. Annual direct FY 값은 절대 quarter sum으로 대체하지 않는다.

따라서 Annual correction은 새 diagnostic version을 만들고, Annual 이후
접수된 Q1/Q3 correction은 과거 diagnostic을 다시 쓰지 않는다.

검증 산출물
--------------------------------------------------
`artifacts/fundamentals/opendart/validation/periodization_fix01/`에 다음을
생성한다.

- `periodization_fix01_summary.json`
- `production_anchor_pit_validation.json`
- `live_period_context_matrix.csv`
- `live_direct_vs_derived_parity.csv`
- `live_company_summary.json`
- `annual_vintage_diagnostic_validation.json`
- `periodization_fix01_manifest.json`

제한사항
--------------------------------------------------
실제 live cohort는 요청 예산 때문에 Samsung/ST Pharm 두 회사로 제한했고,
Hana는 offline control로 분리했다. OpenDART raw ZIP/XML은
`data/cache/opendart`에만 남기며 commit하지 않는다. 추가 회사와 correction
chain의 live 검증은 별도 bounded run에서 진행할 수 있다.

다음 단계
--------------------------------------------------
Architect review에서 Critical=0, Major=0을 확인한 뒤에만
Periodization을 CLOSED로 전환한다. 그 다음 단계에서 처음으로 Derived
Metrics(YoY, TTM, growth, margin)를 다룬다.
