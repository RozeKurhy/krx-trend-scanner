opendart_fundamentals_v01_core_fix02.md

==================================================
OpenDART Fundamentals V01 Core FIX02
==================================================

목적
--------------------------------------------------
FIX01의 pagination completeness를 historical `as_of` coverage completeness로
확장한다. Registry가 페이지를 모두 읽었더라도 요청 시점 이후의 correction이
조회 범위 밖에 있으면 PIT 입력 집합은 완전하지 않다.

핵심 invariant
--------------------------------------------------
    REGISTRY_COVERAGE_END >= REQUESTED_AS_OF

Registry는 `bsns_year-01-01`부터 요청된 `as_of`까지의 결정적 날짜 window를
사용한다. 이번 구현은 list.json에 대해 하나의 명시적 window를 사용하고,
그 window 내부에는 FIX01과 동일하게 HTTP 200 + status 000, pagination,
`total_page`/`total_count`, MAX_PAGES와 partial failure 검증을 적용한다.

Provider 전달 구조
--------------------------------------------------
    Provider.normalize(as_of)
      -> FilingRegistry.list_regular_filings(as_of=as_of)
      -> PITResolver(as_of)
      -> selected rcept_no
      -> filing-specific XBRL

Registry는 PITResolver에만 as_of를 맡기지 않고, 먼저 해당 시점까지의
correction history coverage를 확보한다. 미래 as_of는 `InvalidAsOfError`로
거부한다.

캐시 coverage semantics
--------------------------------------------------
| 조건 | 동작 |
|------|------|
| complete/status/cache valid + coverage_end >= requested as_of | cache hit |
| coverage_end < requested as_of + client | requested range refresh |
| coverage_end < requested as_of + no client | `RegistryCoverageInsufficientError` |
| refresh/extension 실패 | 현재 요청 fail-closed, 기존 valid cache 보존 |
| 성공 refresh | coverage_end를 요청 시점까지 advance |

캐시 metadata에는 `coverage_start`, `coverage_end`, `requested_as_of`,
`window_count`, `request_window`, 페이지/레코드 수와 기존 source provenance를
함께 저장한다. 캐시 key는 기존 corp_code/year/reprt_code를 유지한다.

Late correction과 wider cache
--------------------------------------------------
예시 fixture는 original `2021-03-20`, correction `2024-06-10`이며
requested `as_of=2024-07-01`에서 두 filing을 모두 registry에 포함한다.
PIT는 2023-12-31에 original, 2024-06-10 당일에 correction과
`AVAILABLE_AT_EOD`, 이후에는 correction을 선택한다.

더 넓은 cache에 미래 correction이 이미 들어 있어도 PITResolver가
`rcept_dt <= as_of`만 eligible로 취급하므로 earlier as_of로 누출되지 않는다.

Historical authority
--------------------------------------------------
Historical 값과 basis의 authority는 계속

    list.json registry -> PITResolver -> selected rcept_no -> fnlttXbrl.xml

뿐이다. `fnlttSinglAcntAll`/`financial_statements()`는 historical 경로에서
호출하지 않는다. FIX01의 UNKNOWN family fail-closed, status gate, XBRL SHA와
mutation protection도 유지한다.

검증
--------------------------------------------------
    PYTHONDONTWRITEBYTECODE=1 PYTHONWARNINGS=ignore .venv/bin/pytest -q -p no:cacheprovider \
      tests/test_opendart_fundamentals_contract.py \
      tests/test_opendart_fundamentals_core.py \
      tests/test_opendart_fundamentals_core_fix01.py \
      tests/test_opendart_fundamentals_core_fix02.py

FIX02 targeted suite는 50개 테스트가 통과했다. 이번 작업에서는 live OpenDART
호출을 실행하지 않았고 raw JSON/XML/ZIP 또는 API key를 artifact에 기록하지
않았다. Periodization과 derived metrics는 Core FIX02 승인 뒤에 진행한다.
