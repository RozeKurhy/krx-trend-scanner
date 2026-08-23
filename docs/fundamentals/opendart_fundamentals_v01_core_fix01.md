opendart_fundamentals_v01_core_fix01.md

==================================================
OpenDART Fundamentals V01 Core FIX01
==================================================

목적
--------------------------------------------------
Core review에서 확인된 세 가지 안전성 결함을 보완한다. 정기보고서
registry는 완전한 페이지 집합만 성공 캐시로 취급하고, historical PIT는
선택된 rcept_no의 filing-specific XBRL만 사용한다. 기업군을 판정할 수 없으면
정상 수치로 진행하지 않고 fail-closed한다.

변경 기준
--------------------------------------------------
- START HEAD: 6831b114d3cca4a61ec0a362552838075f0d6464
- Architecture: 7993135a90a21877a13da163dd2f33d6eb1a2bd1
- Architecture FIX01: ef9a490fc2c949f14c1d3943d269dffd9c8f16fa
- Core implementation: 6831b114d3cca4a61ec0a362552838075f0d6464

레지스트리 안전성
--------------------------------------------------
| 항목 | FIX01 정책 |
|------|------------|
| API 성공 | HTTP 200 AND JSON status 000만 성공 |
| 실패 상태 | 010/013/020 등은 명시적 예외, 빈 성공 캐시 금지 |
| 페이지 | total_page/total_count를 우선 사용하고 MAX_PAGES로 상한 |
| 불완전 응답 | page 누락 또는 page 오류 시 캐시 미작성 |
| 새로고침 실패 | 기존 cache_complete=true 캐시를 보존 |
| 캐시 | corp/ticker/year/report/window/page/hash/status/completeness metadata 보존 |
| 보고서 | 11013, 11012, 11014, 11011에 동일 페이지 규칙 적용 |

캐시 원자성
--------------------------------------------------
응답 수집, 상태 검증, 대상 보고서 필터와 correction dedupe가 끝난 뒤에만
캐시를 기록한다. 이전 캐시는 force refresh가 실패해도 덮어쓰지 않는다.
기존 Core 캐시처럼 `cache_complete`가 없는 파일은 FIX01에서 성공 캐시로
소비하지 않고 재수집 대상으로 취급한다.

Historical PIT 경계
--------------------------------------------------
historical `normalize()` 경로는 다음 순서만 허용한다.

    registry -> PITResolver(as_of) -> selected rcept_no -> filing-specific XBRL

`fnlttSinglAcntAll`/`financial_statements()`는 현재 최신 편의 API이므로
historical basis 판정에 호출하지 않는다. XBRL에서 ConsolidatedMember를
확인하면 CFS를 사용한다. consolidated context가 없으면 자동 OFS fallback을
하지 않고 `BASIS_UNRESOLVED`로 종료한다. 별도 OFS 증거 규칙은 후속 작업에서
명시적으로 추가하기 전까지 열지 않는다.

기업군 fail-closed
--------------------------------------------------
| 증거 | 결과 |
|------|------|
| industry code 64/65/66 | FINANCIAL |
| 기타 명시적 industry code | NON_FINANCIAL |
| company=None 또는 증거 없음 | UNKNOWN, COMPANY_FAMILY_UNRESOLVED |

UNKNOWN은 NON_FINANCIAL metrics로 암묵 변환하지 않는다. 따라서 revenue와
operating_income을 포함한 canonical observations를 `RESOLVED`로 만들지
않으며, FINANCIAL일 때에는 해당 두 지표를 `NOT_APPLICABLE`로 유지한다.

검증
--------------------------------------------------
오프라인 targeted suite:

    PYTHONDONTWRITEBYTECODE=1 PYTHONWARNINGS=ignore .venv/bin/pytest -q -p no:cacheprovider \
      tests/test_opendart_fundamentals_contract.py \
      tests/test_opendart_fundamentals_core.py \
      tests/test_opendart_fundamentals_core_fix01.py

FIX01 검증은 41개 테스트가 통과했다. 이 작업에서는 OpenDART live 요청을
실행하지 않았다. raw ZIP/XML과 API key는 artifact에 저장하지 않는다.

범위 밖
--------------------------------------------------
Periodization, standalone quarterization, growth/margin/TTM, score, report,
Pattern/Strategy/Stock Reports, KRX API와 Phase 12/13은 변경하지 않는다.
