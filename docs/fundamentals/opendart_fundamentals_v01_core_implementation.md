opendart_fundamentals_v01_core_implementation.md

==================================================
OpenDART Fundamentals V01 Core Implementation
==================================================

목적
--------------------------------------------------
이 문서는 Architecture authority와 FIX01 계약을 실제 재사용 가능한
PIT-safe Fundamentals data foundation으로 연결한다. 성장률, 마진,
Fundamentals Score, Stock Report와 전략 semantics는 이 경계에 포함하지 않는다.

Authority
--------------------------------------------------
- Architecture: 7993135a90a21877a13da163dd2f33d6eb1a2bd1
- Architecture FIX01: ef9a490fc2c949f14c1d3943d269dffd9c8f16fa
- PIT granularity: DAILY_EOD_KST
- regular reports: 11013/Q1, 11012/HALF_YEAR, 11014/Q3, 11011/ANNUAL

모듈 책임
--------------------------------------------------
| 모듈 | 책임 |
|------|------|
| opendart_client.py | 환경변수 key, JSON/binary status, URL redaction |
| corp_code_repository.py | corpCode ZIP/XML persistent mapping, duplicate fail-closed |
| filing_registry.py | 정기보고서 필터, report type, correction chain, cache provenance |
| pit_resolver.py | as_of까지 eligible filing 선택 및 same-day/future 상태 |
| xbrl_repository.py | rcept_no/reprt_code raw ZIP cache, SHA, mutation detection, 최소 fact parser |
| financial_statement_provider.py | family, CFS/OFS basis, canonical observation 생성 |
| models.py | filing, raw artifact, FinancialObservation, normalized report model |

데이터 흐름
--------------------------------------------------
ticker
  -> CorpCodeRepository
  -> FilingRegistry (list.json regular filings)
  -> PITResolver(as_of)
  -> selected rcept_no
  -> XbrlRepository (filing-specific fnlttXbrl.xml)
  -> report basis selector (CFS preferred, OFS fallback boundary)
  -> primary XBRL statement rows
  -> company family
  -> canonical account resolver
  -> normalized FinancialObservation

캐시 계층
--------------------------------------------------
- data/cache/opendart/corp_code_cache.json
- data/cache/opendart/filings/<corp_code>_<year>_<reprt_code>.json
- data/cache/opendart/xbrl/<rcept_no>_<reprt_code>.zip + .json

raw ZIP은 Git에 추가하지 않으며 ``data/*`` ignore 규칙 아래에 둔다. 각
metadata에는 retrieved_at, source hash, HTTP/content metadata, member 목록,
redacted source URL을 남긴다. 동일 SHA cache hit는 API를 다시 호출하지 않는다.
force_refresh에서 SHA가 변하면 SOURCE_MUTATION_DETECTED로 중단한다.

PIT와 정정 처리
--------------------------------------------------
정정 marker를 제거한
corp_code + bsns_year + reprt_code + normalized report name을 chain key로
사용한다. eligible은 rcept_dt <= as_of, future는 rcept_dt > as_of다.
동일 chain의 latest eligible만 선택하고, same-day는 AVAILABLE_AT_EOD다.
독립 chain 또는 동률 identity는 AMBIGUOUS로 fail-closed한다.

정규화 규칙
--------------------------------------------------
- XBRL primary context에서 ConsolidatedMember를 CFS로 우선 사용한다.
- ConsolidatedMember가 없을 때 SeparateMember를 OFS로 사용한다.
- account-level CFS/OFS 혼합은 하지 않는다.
- BS/IS/CIS/CF 계열을 canonical statement family로 보존하고 SCE는 후보에서 제외한다.
- missing/"-"는 0으로 채우지 않고 NOT_FOUND/DATA_UNAVAILABLE로 둔다.
- 통화와 raw row, selected rcept_no, SHA를 canonical observation에 보존한다.
- FINANCIAL(64/65/66)은 revenue/operating_income을 NOT_APPLICABLE로 둔다.

검증 실행
--------------------------------------------------
오프라인 단위 검증:

    PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -q -p no:cacheprovider \
      tests/test_opendart_fundamentals_contract.py \
      tests/test_opendart_fundamentals_core.py

실제 API 검증은 명시적 ``--live``가 있어야만 실행한다.

    .venv/bin/python scripts/validate_opendart_fundamentals_core_v01.py \
      --live --env-file /Users/june/Documents/projects/env.md

검증 결과는 artifacts/fundamentals/opendart/validation/core_v01/에 저장하며,
API key는 artifact/stdout/cache metadata에 저장하지 않는다.

검증 범위와 제한
--------------------------------------------------
- 대표 fixture: 005930, 237690, 086790
- annual/Q1/H1/Q3 report identity와 raw period context를 보존한다.
- standalone quarterization, Q2/Q3/Q4 파생, YoY/QoQ/TTM, CAGR, margin,
  valuation, Score, ranking, Stock Report, Pattern/Strategy는 구현하지 않는다.
- 최소 XBRL fact parser만 제공하며 범용 taxonomy/linkbase engine은 만들지 않는다.
- XBRL statement family의 raw sj_div는 filing-specific primary fact의 metric
  context로 보존한다. 추가 계정/기업군은 별도 fixture와 periodization 단계가 필요하다.

다음 경계
--------------------------------------------------
Architect review 후 Periodization 단계에서 결산월/period semantics와
standalone quarter를 별도 검증한다. 그 다음에야 derived metrics와
Stock Report v0.4 통합을 논의한다.
