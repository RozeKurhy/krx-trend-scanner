# 분석 입력 갱신 기준 V01

## 1. 문서 역할과 현재 상태

이 문서는 [데일리 업데이트 기준 V01](daily_update_contract_v01.md) §6.2가 개요만
정의한 3단계(분석 입력 갱신)의 상세 계약이다. 1단계·2단계 상위 계약은
그대로 유지하며, 이 문서는 그 위에서 다음 5개 분석 입력에만 적용되는
세부 기준을 정의한다.

```text
외국인 수급
펀더멘털
시장 RS
업종 RS
섹터 구성
```

이 문서는 계약 문서이며 구현 완료 기록이 아니다. 3단계는 아직 구현
전이며, 이 문서는 구현에 앞서 각 입력이 무엇을 재사용하고 무엇을 새로
만들어야 하는지 확정한다.

```text
DAILY_UPDATE_PHASE1 = COMPLETE
DAILY_UPDATE_PHASE2 = COMPLETE
```

3단계의 기본 방향은 이미 존재하는 원천 수집·계산 로직을 재사용하고,
하나의 `target_as_of`로 5개 입력을 일관되게 묶는 조율 계층만 최소로
추가하는 것이다. 새 데이터 엔진을 만드는 작업이 아니다.

## 2. 공통 원칙

- 5개 입력 모두 호출 계층이 받은 하나의 `target_as_of`를 그대로
  상속한다.
- 각 원천의 공시일·효력일·거래일 규칙은 그 원천 고유의 의미로 존중한다
  (§9).
- 시스템 실행 시각이나 현재 목록을 과거 기준일 대신 사용하지 않는다.
- 중간 공백을 무시하지 않는다.
- 한 입력만 성공한 부분 성공을 3단계 전체 `PASS`로 승격하지 않는다
  (§8).

## 3. 1단계·2단계와의 경계

3단계는 다음을 다시 만들거나 재검증하지 않는다.

```text
주가 원천
수정주가
시장 대표지수 원천 갱신
Repository V2
주봉
월봉
```

이들은 각각 1단계·2단계가 이미 인증한 결과를 그대로 상속한다(§10).
3단계가 답해야 할 질문은 "분석 입력이 `target_as_of`에 맞는가"이지,
"1단계 가격 데이터가 정말 맞는가"가 아니다.

## 4. 입력별 공식 계약

### 4.1 외국인 수급

**현재 재사용 대상**: `ForeignFlowDataProvider`
(`src/trend_scanner/data/foreign_flow_provider.py`)의
`fetch_date_batch()`, `build_historical_cache()`, `load_flow_history()`.

**현재 부족한 부분**: `build_historical_cache()`는 전달받은 거래일
목록 전체를 매번 새로 수집해서 파일을 새로 쓰는 방식이며, 기존
스냅샷과 비교해 빠진 거래일만 계산해서 병합하는 절차는 없다. 커밋된
스크립트(`scripts/fetch_foreign_flow_20260814.py`)에도 기준일 인자
자체가 없어 특정 날짜 1회용으로만 동작한다.

**계약**:

```text
입력:
- target_as_of
- 기존 최신 foreign_flow 스냅샷

처리:
- 필요한 거래일 계산
- 누락일만 수집
- 기존 데이터와 병합, (date, ticker) 중복 금지
- target_as_of 스냅샷 생성

출력:
foreign_flow_daily_{YYYYMMDD}.parquet
foreign_flow_daily_{YYYYMMDD}_meta.json
```

동일한 `target_as_of`로 재실행하면 추가 수집이나 쓰기 없이 정상
종료해야 한다.

**판단**: `NEEDS_MINIMAL_UPDATE_PATH`

### 4.2 펀더멘털

**현재 재사용 대상**: OpenDART 원천 → `FilingRegistry` → F2 → F3 → F4
→ `FundamentalsSection` 생성 계층(`src/trend_scanner/reporting/fundamentals_report.py`).
생성된 섹션은 Stock Report v0.5에 주입하며, `stock_report.py`는 이를 소비·렌더링한다.

**현재 부족한 부분**: 벌크 유니버스 재수화 스크립트
(`scripts/hydrate_fundamentals_v1_production.py`)는 `--as-of`
인자가 없다. `_load_requested_as_of()`가 파일명에 `20260904`가
고정된 `SCAN_SUMMARY_PATH`
(`artifacts/patterns/pattern_a/production/scanner/pattern_a_universe_scan_20260904_summary.json`)를
읽어서 기준일을 역산하는 구조이며, 그 파일이 없으면 즉시 예외를 던진다.

**계약**:

```text
target_as_of를 명시적으로 받는다.
--as-of YYYY-MM-DD 또는 동등한 하나의 명시적 매개변수.
```

금지:

- 스캐너 요약 파일명에서 기준일 역추론
- 오늘 날짜 자동 사용
- `2026-09-04` 고정값 사용

PIT 원칙은 기존 그대로 유지한다.

```text
filing availability date <= target_as_of
```

재무기간 종료일, 공시일, `filing availability date`(공시 열람 가능일),
`target_as_of`를 하나의 날짜로 취급하지 않는다.

출력 위치는 기존 그대로 `artifacts/fundamentals/production/{YYYYMMDD}/`를
재사용한다. 같은 기준일 재실행 시 기존 캐시를 재사용하고 불필요한
전체 재수집을 하지 않는다.

**판단**: `NEEDS_MINIMAL_UPDATE_PATH`

### 4.3 시장 RS

**현재 재사용 대상**: 가격 원천은 `MarketDataRepositoryV2`, 시장
지수는 `IndexStore`(`MARKET_INDEX`) — 둘 다 1단계 권위를 그대로
재사용한다. 계산 로직은 기존 `relative_strength`/`cross_section` 계산
모듈을 재사용한다.

**현재 실제로 두 경로가 공존함**(이전 감사가 놓친 부분): 스캐너는
`MarketDataRepositoryV2` + `IndexStore`로 실행 시점에 시장 RS를 계산하지만,
종목 리포트는 별도로 **정확한 날짜의 스냅샷 파일**을 요구한다.
`src/trend_scanner/reporting/relative_strength_report.py`는 파일
docstring부터 "Local exact-date consumer for the Phase 12 Market RS
authority snapshot"이며,
`load_relative_strength_section(ticker, requested_as_of, ...)`가
`RS_ARTIFACT_TEMPLATE = "artifacts/patterns/pattern_a/validation/relative_strength/market_completion_v01/market_rs_universe_{date}.csv"`
경로에서 `requested_as_of`와 정확히 일치하는 파일만 읽는다. 그 파일이
없으면 다른 날짜로 대체하지 않고 `DATA_UNAVAILABLE`을 반환한다(코드
주석: "never falls back to another snapshot date").

**계약**: 3단계의 책임은 계산 엔진을 새로 만드는 것이 아니라,
`target_as_of` 기준 전체 `COMMON`(보통주) 시장 RS의 정확한 날짜 스냅샷을
생성하는 것이다.

**시장 RS cross-section 모집단 권위**:

```text
Market RS cross-section population
= Phase 1 rolling PIT authority
  (data/market/rolling_authority/merged_pit_intervals.json)에서
  target_as_of에 COMMON인 전체 KOSPI/KOSDAQ 종목 집합
```

이 전체 모집단을 `compute_market_rs_cross_section()`에 전달한 뒤, 스캐너나
종목 리포트에는 그 결과를 조회해 붙인다. 현재 종목 목록, Pattern A
candidate subset, investable subset, scanner 결과 subset, 과거 Phase 12
검증용 oracle artifact는 운영 cross-section 분모로 사용하지 않는다.

```text
필수 출력:
market_rs_universe_{YYYYMMDD}.csv
```

`scripts/run_phase12_market_relative_strength_completion_v01.py`의
계산 로직은 참고·재사용하되, 그 스크립트의 `AS_OF = "2026-08-14"`
고정값은 운영 경로에서 사용하지 않는다.

**판단**: `REUSE_WITH_MINIMAL_WRAPPER`

### 4.4 업종 RS

**입력**: 종목 가격 = `MarketDataRepositoryV2`(1단계), 업종 지수 = 기존 업종
지수 캐시, 섹터 구성 = §4.5의 승인 스냅샷 선택. 일일 3F 출력 모집단은
`target_as_of`의 Phase 1 PIT COMMON 전체 모집단을 사용하고, 선택된 섹터
구성을 그 모집단에 reconciliation한다.

**업종 지수 갱신 — 공식 재사용 경로**(이전 감사가 놓친 부분):
`src/trend_scanner/data/krx_sector_index.py`의
`KrxSectorIndexCacheBuilder.update(*, target_date, output_parquet,
output_meta, minimum_sessions=1)`는 지정한 날짜 하나만 KRX Open
API로 수집해서 기존 캐시와 병합하는(기존 같은 날짜 행은 교체) 진짜
증분 갱신 메서드다. 신규 행이 없으면 `idempotent_noop=True`로
정상 종료한다.
`src/trend_scanner/data/index_price_provider.py`의
`update_sector_index_cache(target_date, output_parquet, output_meta,
...)`는 이 빌더를 감싸는 얇은 함수다. 이전 감사가 "1회성
이관 스크립트만 있다"고 본 것은
`scripts/migrate_sector_rs_krx_v01.py`만 확인했기 때문이며,
재사용 가능한 증분 갱신 메서드 자체는 이미 존재한다.

**계약**: 3단계에서 새 갱신기를 만들지 않는다. 필요한 누락 거래일을
계산해서 기존 `update_sector_index_cache()`를 그 거래일마다 호출하는
조율만 추가한다.

**업종 RS 랭킹**: `scripts/build_sector_rs_ranking_v01.py`는 이미
`--as-of`를 지원한다(기본값 `AS_OF = "2026-09-04"`). 3단계 운영
조율에서는 이 기본값을 쓰지 않고 `target_as_of`를 명시적으로
전달한다.

시장 RS와 업종 RS는 계산 엔진을 일부 공유하더라도 다음을 서로 다른
권위로 구분한다.

```text
시장 벤치마크 권위
업종 벤치마크 권위
업종 구성 권위
랭킹 대상 모집단
```

**판단**: `REUSE_WITH_MINIMAL_WRAPPER`

### 4.5 섹터 구성

**공식 생성 경로 — 이미 존재함**(이전 감사가 놓친 부분):
`src/trend_scanner/data/sector_membership_rolling.py`의
`build_rolling_sector_membership(effective_date, *, repo_root, ...)`가
공식 생성기다. `fetcher=None`인 production 기본 경로는
`load_marketplace_sector_checkpoints()`를 사용하며, 다음 로컬 원천을 읽는다.

```text
.cache/krx_marketplace/sector_membership/{YYYYMMDD}/manifest.json
+ 해당 manifest가 가리키는 날짜별 KRX Data Marketplace 공식 구성종목 CSV 46개
```

CLI(`main()`)는 이미 `--as-of`를 지원한다
(`parser.add_argument("--as-of", default=AS_OF)`). 이전 감사가
"신규 스냅샷 생성용 커밋된 스크립트를 못 찾았다"고 한 것은 부정확한
결론이다. 이 함수는 로컬 manifest와 CSV를 검증하고 46개 업종 전부가
성공해야만 발행하는 게이트를 가진다. 명시적인 `fetcher`는 테스트용
주입 경로이며 production 기본 경로의 네트워크 수집을 의미하지 않는다.

**공식 조회 경로**: `src/trend_scanner/data/sector_membership.py`의
`resolve_sector_membership_snapshot_for_target(target_as_of, ...)`.
일일 소비자는 `effective_date <= target_as_of`인 승인 스냅샷 중 가장 최신
날짜를 선택한다. 선택된 스냅샷의 parquet와 `_meta.json` 쌍이 모두 있어야
하며, 기존 공식 loader의 schema·effective date·population 검증을 통과해야
한다. 승인된 미래 스냅샷은 절대 과거 target에 적용하지 않는다.

Sector Membership refresh는 daily execution 항목이 아니다. 기본 운영 주기는
월 1회 수동 refresh이며, 필요할 때 특별 refresh를 수행한다. Daily Sector RS는
refresh를 생성하지 않고 latest approved membership을 선택해 target PIT COMMON에
적용한다.

요청 target보다 이른 승인 스냅샷이 없거나, 가장 최신 후보가 부분 발행·무효
상태이면 `SectorMembershipSnapshotUnavailable`로 fail closed한다. 이 경우
더 오래된 스냅샷으로 재대체하지 않는다. 정확일 loader는 refresh 및
historical 검증용으로 계속 유지한다.

**계약**:

```text
승인된 snapshot 중 effective_date <= target_as_of인 최신 pair 존재
→ 해당 snapshot 재사용

최신 후보 pair가 부분 발행·무효이거나 eligible snapshot 없음
→ BLOCKED

target_as_of보다 미래인 snapshot만 존재
→ BLOCKED; 미래 snapshot을 backward apply하지 않음
```

원천 manifest/CSV가 준비되지 않으면 신규 snapshot 생성은 `BLOCKED`로
처리한다. 일일 소비자는 위의 승인 후보 선택 규칙만 사용하며, 무효한 최신
후보를 임의의 이전 snapshot으로 대체하지 않는다.

**판단**: `REUSE_WITH_MINIMAL_WRAPPER`

## 5. 펀더멘털 소비 경로 정정

이전 감사는 `stock_report.py`가 종목별로 OpenDART를 직접 호출한다고
기록했는데, 이는 부정확하다. 실제 구조를 코드로 확인했다.

```text
OpenDART 원천 수화(hydration)
  → Fundamentals 결과(F2/F3/F4)
  → FundamentalsSection
  → Stock Report v0.5에 주입
```

`stock_report.py`는 `FundamentalsSection`을 파라미터로 받아 렌더링만
한다(`_render_fundamentals_section()`). `fundamentals_section`이
주입되지 않고 v0.5 출력이 요청된 경우에만
`build_fundamentals_section(None, None, None, requested_as_of=...)`을
호출하는데, 이때도 실제 F2/F3/F4 원천 데이터 없이 빈 섹션을 만드는
경로일 뿐 OpenDART를 직접 호출하지 않는다. `stock_report.py` 자체는
OpenDART 호출 주체가 아니다.

## 6. 권장 실행 순서

```text
[Daily]
1. 외국인 수급
2. 펀더멘털
3. 시장 RS
4. 업종 지수
5. 승인된 Sector Membership 선택/확인
6. 업종 RS 랭킹

[Periodic Maintenance]
- Sector Membership refresh: 기본 월 1회 수동
- 필요 시 특별 refresh
```

Daily 6개 항목은 실행 단계의 목록이며 Phase 3 최상위 입력의 목록과 다르다.
Periodic Maintenance의 Sector Membership refresh는 Daily 실행에 포함되지 않는다.
Phase 3 전체 상태 합성 대상은 §1의 5개 최상위 입력(외국인 수급,
펀더멘털, 시장 RS, 섹터 구성, 업종 RS)뿐이다. 업종 지수 갱신은 Phase 3의
별도 최상위 입력이 아니라 업종 RS를 준비하기 위한 내부 선행 단계다.

```text
업종 RS
├─ 업종 지수 갱신
├─ 섹터 구성 준비 확인
└─ 업종 RS 랭킹 생성
```

섹터 구성은 자체 최상위 입력이면서 업종 RS의 의존성이다. Daily 경로에서는
승인 스냅샷 선택과 target PIT COMMON reconciliation이 준비 확인에 해당한다.

업종 RS 랭킹은 업종 지수와 섹터 구성이 모두 `target_as_of` 기준으로
준비된 뒤에만 실행한다. 시장 RS는 1단계 가격·지수에만 의존하므로 이
순서 안에서 상대적으로 독립적이다.

## 7. 상태 계약

3단계 전체 상태와 5개 최상위 입력의 상태는 동일한 값 집합을 사용한다.

| 상태 | 의미 |
|---|---|
| `PASS` | `target_as_of`까지 필요한 입력 생성·갱신 완료 |
| `NOOP_ALREADY_COMPLETE` | `target_as_of`의 정확한 날짜 산출물이 이미 정상 존재 |
| `BLOCKED` | 필요한 원천 미확정(예: 섹터 구성 원천 CSV 없음, OpenDART 권위 사용 불가, 업종 지수 원천 미확정) |
| `FAILED` | 계약상 예상하지 못한 코드·실행 오류 |

## 8. 전체 상태 합성 및 부분 성공 금지

Phase 3 전체 상태는 다음 5개 최상위 입력의 상태만 합성한다.

- 외국인 수급
- 펀더멘털
- 시장 RS
- 섹터 구성
- 업종 RS

업종 지수는 별도 최상위 상태로 합성하지 않고 업종 RS 내부 선행 단계로
처리한다. 업종 지수 상태가 `BLOCKED`이면 업종 RS는 `BLOCKED`,
`FAILED`이면 업종 RS는 `FAILED`로 전달한다. 업종 지수가
`NOOP_ALREADY_COMPLETE`이어도 업종 RS 랭킹이 새로 생성되면 업종 RS는
`PASS`가 될 수 있다.

5개 최상위 입력 결과를 3단계 전체 상태로 합칠 때는 다음 우선순위를
고정한다.

```text
1. 하나라도 FAILED
   → 전체 FAILED

2. FAILED는 없고 하나라도 BLOCKED
   → 전체 BLOCKED

3. FAILED와 BLOCKED가 없고 모든 필수 입력이 NOOP_ALREADY_COMPLETE
   → 전체 NOOP_ALREADY_COMPLETE

4. 그 밖의 정상 조합
   (PASS + NOOP_ALREADY_COMPLETE)
   → 전체 PASS
```

따라서 다음과 같이 합성한다.

```text
PASS + NOOP_ALREADY_COMPLETE + PASS + PASS + NOOP_ALREADY_COMPLETE
→ 전체 PASS

NOOP_ALREADY_COMPLETE + NOOP_ALREADY_COMPLETE + NOOP_ALREADY_COMPLETE
+ NOOP_ALREADY_COMPLETE + NOOP_ALREADY_COMPLETE
→ 전체 NOOP_ALREADY_COMPLETE

PASS + PASS + PASS + BLOCKED + PASS
→ 전체 BLOCKED

PASS + FAILED + BLOCKED + PASS + PASS
→ 전체 FAILED
```

하나의 입력이 `BLOCKED`나 `FAILED`인 상태에서 다른 입력만 성공한 부분
성공을 전체 `PASS`로 승격하지 않으며, 섹터 구성이 막힌 상태에서 업종 RS
랭킹을 억지로 진행하지 않는다.

## 9. target_as_of 공통 규칙

5개 입력 모두 동일한 `target_as_of`를 상속한다.

금지:

- `datetime.now()`나 오늘 날짜 사용
- 현재 구성(membership)을 과거 날짜에 그대로 적용

단, 섹터 구성 소비자에는 다음의 명시적 승인 규칙을 적용한다.

- `resolve_sector_membership_snapshot_for_target()`가 승인된
  `effective_date <= target_as_of` 중 최신 pair를 선택한다.
- 미래 스냅샷은 선택하지 않는다.
- 선택된 최신 후보가 부분 발행·무효이면 더 오래된 후보로 대체하지 않고
  fail closed한다.
- 다른 입력 원천에는 최신 파일 자동 선택이나 가장 가까운 이전 스냅샷의
  자동 대체를 적용하지 않는다.

각 원천이 내부적으로 다음 의미를 쓰는 것은 정상이며, `target_as_of`와
같은 값으로 섞어 쓰지 않는다.

```text
filing availability date
실제 거래일
effective_date
```

## 10. 1단계·2단계 상속

다음은 3단계에서 재검증하지 않고 1단계·2단계의 인증 결과를 그대로
신뢰한다.

```text
Repository V2 시세
시장 대표지수
주봉
월봉
```

## 11. 저장 구조

새 저장소를 만들지 않는다. 기존 위치를 그대로 재사용한다.

```text
외국인 수급:
artifacts/patterns/pattern_a/production/flow/source/

펀더멘털:
artifacts/fundamentals/production/{YYYYMMDD}/

시장 RS:
artifacts/patterns/pattern_a/validation/relative_strength/market_completion_v01/

업종 지수:
.cache/krx_openapi/sector_rs_migration/v01/

섹터 구성:
data/market/sector_membership/v01/

업종 RS:
data/analytics/sector_rs_ranking/v01/
```

새 데이터베이스나 매니페스트 체계를 만들지 않는다.

## 12. 재사용 대상과 3단계 신규 범위

아래 표의 업종 지수 행은 별도 최상위 입력을 뜻하지 않는다. 업종 지수는
업종 RS 내부 선행 단계이며, 그 상태는 업종 RS에 전달한다.

| 입력 | 기존 엔진 재사용 | 3단계 신규 범위 |
|---|---|---|
| 외국인 수급 | `ForeignFlowDataProvider` | 누락 거래일 계산·병합 조율 계층 |
| 펀더멘털 | 기존 OpenDART/F2/F3/F4 계층 | 벌크 재수화 스크립트에 `target_as_of` 매개변수화 |
| 시장 RS | 기존 `relative_strength`/`cross_section` 계산 | `target_as_of` 정확한 날짜 스냅샷 생성 계층 |
| 업종 지수(업종 RS 내부 선행 단계) | `KrxSectorIndexCacheBuilder.update()` / `update_sector_index_cache()` | 누락 거래일 계산 조율 계층 |
| 섹터 구성 | `build_rolling_sector_membership()` / 승인 snapshot resolver | Periodic refresh(기본 월 1회 수동·필요 시 특별)와 Daily 승인 snapshot 선택·target PIT COMMON reconciliation |
| 업종 RS | 기존 랭킹 빌더(`build_sector_rs_ranking_v01.py`) | 실행 순서·`target_as_of` 전달 조율 |

## 13. 구현 단계 분리(참고, 이 문서가 강제하지 않음)

이 계약 확정 이후 구현은 한 번에 전체를 고치지 않는 것을 권장한다.
아래는 논리적 단위일 뿐이며 실제 커밋 수를 강제하지 않는다.

```text
3A 외국인 수급
3B 펀더멘털
3C 시장 RS
3D 업종 지수 + 섹터 구성
3E 업종 RS 랭킹
3F 통합 조율
3G 실운영 검증
Phase 3 COMPLETE
```

## 14. 관련 현재 기준 문서

- [데일리 업데이트 기준 V01](daily_update_contract_v01.md) — 1단계 상위 계약
- [주봉·월봉 파생 기준 V01](weekly_monthly_derivation_contract_v01.md) — 2단계 상세 계약
- [Sector RS KRX 이관 기준](sector_rs_krx_migration_v01.md)
