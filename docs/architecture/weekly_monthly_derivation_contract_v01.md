# 주봉·월봉 파생 기준 V01

## 1. 문서 역할과 현재 상태

이 문서는 [데일리 업데이트 기준 V01](daily_update_contract_v01.md) §6.1이 개요만
정의한 2단계(주봉·월봉 파생)의 상세 계약이다. 1단계 데일리 업데이트 기준은
상위 계약으로 그대로 유지하며, 이 문서는 그 위에서 주봉·월봉 파생에만
적용되는 세부 기준을 정의한다.

이 문서는 계약 문서다. 아래에서 정의하는 `DERIVED_WEEK_COMPLETE`를 포함한
개념은 모두 `src/trend_scanner/data/period_derivation.py`(`derive_periods()`)로
구현이 끝났고, 실제 운영 입력으로도 검증됐다. 각 절의 "현재 구현과의 관계"는
이 최종 구현을 기준으로 기록한다.

1단계는 이미 완료됐다.

```text
DAILY_UPDATE_PHASE1 = COMPLETE
```

2단계도 완료됐다.

```text
DAILY_UPDATE_PHASE2 = COMPLETE
```

2단계의 기본 방향은 기존 주봉·월봉 파생 로직을 재사용하고, 하나의
`target_as_of`와 기간 완료 판정 의미를 명확히 묶는 것이었다. 새로운 주봉·월봉
시스템을 만드는 작업이 아니었고, 실제로도 만들지 않았다.

구현·실운영 검증의 코드 기준 HEAD는 `cc48dab5795cb1d67615310e18b3a493b0e3e2e2`다.
이 문서를 마감하는 커밋의 HEAD는 그 이후 값이며, 코드 자체는 이 마감 커밋에서
변경되지 않는다. 실운영 검증 근거는 §14에 기록한다.

## 2. 2단계 입력 권위

주봉·월봉은 독립된 수집 대상이 아니다.

```text
1단계 인증 일봉
  → 주봉/월봉 파생
```

- 주봉·월봉을 KRX·PyKRX·Naver 등에서 별도로 수집하지 않는다.
- 1단계 인증 경계를 넘어선 일봉을 입력으로 사용하지 않는다.
- 호출 계층이 받은 하나의 `target_as_of`를 그대로 사용한다.

## 3. 기존 집계 규칙 재사용

현재 `src/trend_scanner/data/resampler.py`의 규칙을 2단계 공식 집계 규칙으로
그대로 재사용한다. 새 산식이나 별도 resample 함수를 만들지 않는다.

| 구분 | 규칙 |
|---|---|
| 주봉 경계 | `W-FRI` (금요일 라벨) |
| 월봉 경계 | `MonthEnd` |
| open | first |
| high | max |
| low | min |
| close | last |
| volume | sum |
| trading_value | sum(min_count=1), 구간 전체가 결측이면 0이 아니라 결측 유지 |

## 4. 주봉 완성 판정과 FAST 신호 기준점 분리

다음 두 개념을 하나로 합치지 않는다.

### 4.1 DERIVED_WEEK_COMPLETE

2단계의 일반적인 파생 주봉 완성 의미다.

핵심 의미:

```text
1. 기존 W-FRI 주봉 집계 규칙을 그대로 사용한다.
2. 해당 주봉의 W-FRI 라벨이 target_as_of 이하다.
→ COMPLETE

그 외
→ PROVISIONAL
```

전제는 2단계에 전달되는 일봉이 이미 1단계 인증 범위 안이라는 것이다(§2, §8).
이 전제 위에서 이 의미는 금요일이 휴장일인 주간도 처리할 수 있어야 한다.
예를 들어 그 주의 실제 마지막 거래일이 목요일이고 `target_as_of`가 금요일이면,
목요일까지의 일봉이 이미 1단계 인증 범위 안에 있으므로 일반적인 파생 주봉은
`COMPLETE`로 볼 수 있다.

**현재 구현과의 관계**: `_weekly_status()`(`period_derivation.py`)는 W-FRI
라벨과 `target_as_of`의 단순 비교만 수행하며, `MarketCalendarAuthority`(마지막
실제 거래일 등)를 별도로 참조하지 않는다. 2단계는 "그 주의 필요 일봉이 실제로
확보됐는지"를 캘린더로 다시 검증하지 않는다 — 1단계가 이미 인증한 `daily`
범위를 그대로 신뢰한다(§8의 `daily_gap_authority = INHERITED_FROM_PHASE1`와
같은 원칙). 초기 구현은 `calendar.max_observed_trading_date`로 이 신뢰를
대신 재검증하려 했으나, 이는 마지막 실제 거래일과 "권위가 실제로 확인한
경계"를 혼동하는 오류였고 이후 제거됐다.
`src/trend_scanner/validation/historical_snapshot.py`의
`_drop_incomplete_weekly()`는 목적이 다른 기존 로직(가장 마지막 트레일링
주봉만 대상)이며, 이 절의 `DERIVED_WEEK_COMPLETE` 판정 자체를 대신하지
않는다.

### 4.2 FAST_W_FRI_SIGNAL_ANCHOR

기존 FAST(Pattern A FAST) 및 일부 백테스트가 사용하는 과거 신호 기준점
의미다.

현재 기존 의미:

```text
W-FRI 리샘플 라벨(금요일) 자체가 실제 종목 일봉 날짜와 일치하는
완료된 금요일만 신호 기준점으로 인정
```

금요일이 휴장인 주간은 이 신호 기준점에서 제외될 수 있다.

**현재 구현과의 관계**: 이 의미는 `src/trend_scanner/reporting/pattern_a_fast_report.py`
`build_pattern_a_fast_section()`에 정확히 그대로 존재한다(코드 주석의 표현으로
"Phase 13 completed-week contract"). 모든 주봉 라벨에 대해
`week_daily.index.max().normalize() != week_label.normalize()`이면 그 주를
FAST 관측에서 완전히 제외한다(`continue`). 즉 가장 마지막 주간뿐 아니라,
과거의 이미 완료된 휴장 단축 주간도 FAST 신호 이력에서 영구적으로 빠진다.
이는 `DERIVED_WEEK_COMPLETE`보다 엄격한 별도 기준이며, 이미 운영 중인
`HIERARCHICAL_V01` 계약과 결합되어 있다.

중요:

```text
DERIVED_WEEK_COMPLETE != FAST_W_FRI_SIGNAL_ANCHOR
```

2단계 구현 때문에 기존 공식 전략·백테스트의 과거 FAST 의미를 조용히 바꾸지
않는다. FAST 신호 기준점 변경은 2단계 범위가 아니다.

## 5. 월봉 완료 판정

월봉 완료 판정 대상은 `target_as_of`가 속한 (연, 월)이 아니라, **실제로
파생된 마지막 월봉**(`monthly.index[-1]`)의 (연, 월)이다. 그 (연, 월)이
현재 운영 `MarketCalendarAuthority`의 완료 월 권위에서 완료로 확정됐는지로
판정한다.

```text
실제로 반환된 마지막 월봉의 (연, 월)이
운영 완료 월 권위에서 완료로 확정된 경우 → COMPLETE
그 외(아직 완료 월로 확정되지 않은 경우) → PROVISIONAL
```

거래정지·장기 미거래로 마지막 월봉이 과거 달에 머물러 있으면(예: 종목 마지막
거래일이 2025-12-05이고 `target_as_of`가 2026-01-15로 다음 달인 경우), 마지막
월봉은 2025-12이므로 `target_as_of`의 (연, 월)인 2026-01이 아니라 2025-12의
완료 여부로 판정한다. 2단계에서 월봉 완료 판정 구조를 새로 만들지 않는다.

**현재 구현과의 관계**: `_monthly_status()`(`period_derivation.py`)는
`monthly.index[-1]`의 (연, 월)로 `calendar.get_actual_month_end()`를 조회하고,
반환값이 있고 `target_as_of`가 그 값 이상이면 `COMPLETE`로 판정한다.
`get_actual_month_end()`는 완료 월 목록에 없는 (연, 월)에 대해 예외 없이
`None`을 반환하므로, 비거래일 `target_as_of`에서도 별도 클램프 없이 안전하게
조회할 수 있다. 운영에서 이 완료 월 권위는
`load_rolling_production_market_calendar()`가 만드는데, 이 함수는 달력
데이터에 관측된 가장 최근 (연, 월)을 완료 월 목록에서 제외하는 방식으로
동작한다. 즉 그 달의 실제 마지막 거래일이 지난 당일 곧바로 완료로 확정하는
것이 아니라, 다음 달의 첫 실제 거래일이 캘린더 데이터에 관측되어야 비로소
그 이전 달이 완료 월로 확정된다. 이 의미를 그대로 따르며, 월봉 완료 판정
전용 신규 구조는 만들지 않는다. 이 함수가 `None`을 반환하면(병합 캘린더
산출물 자체가 없음) `BLOCKED`로 처리한다(§12).

## 6. PROVISIONAL 의미

2단계 계약에서는 진행 중인 기간을 다음 두 상태로 명확히 정의한다.

```text
COMPLETE
PROVISIONAL
```

단, 이 상태를 반드시 파일에 영구 저장해야 한다고 계약하지 않는다. 상태는
실행 시점 계산 결과나 조율 계층 결과의 메타데이터로 표현할 수 있다.
저장 방식은 구현 필요성이 증명될 때만 추가한다.

## 7. target_as_of

2단계의 공식 진입점은 하나의 `target_as_of`를 받아야 한다.

기본 의미:

```text
daily = 1단계 인증 일봉 중 date <= target_as_of
weekly/monthly = 그 일봉 구간에서만 파생
```

금지:

- 시스템 오늘 날짜를 기준으로 삼기
- 저장 파일의 최신 날짜를 기준으로 삼기
- 소비 계층별로 임의의 기준일을 새로 만들기

소비 계층이 별도 날짜를 만들어 2단계 기준일을 바꾸지 않는다.

## 8. 중간 공백 처리 — 1단계 상속

기본 원칙:

```text
1단계 인증 일봉의 완전성 보장을 상속
```

2단계는 1단계와 동일한 일봉 전체 중간 공백 검증을 다시 구현하지 않는다.

```text
daily_gap_authority = INHERITED_FROM_PHASE1
```

단, 2단계 입력이 1단계 인증 범위를 벗어나거나 필요한 일봉 커버리지를 증명할
수 없으면 `BLOCKED`로 처리한다. 새 전체 이력 검증 체계를 만들지 않는다.

## 9. 저장 / 공식 산출물

현재 계약에서는 별도 주봉·월봉 parquet 저장소를 필수로 만들지 않는다. 기본
방향은 실행 시점 결정적 계산이다.

허용:

- 얇은 조율 계층 결과
- 상태·기준일 요약 메타데이터

별도 영구 주봉·월봉 저장소는 다음 조건이 실제로 확인될 때만 후속 승인
대상이다.

- 실제 성능 병목
- 소비 계층 간 일관성 문제
- 운영상 재사용 필요성

단순히 "2단계니까 저장해야 한다"는 이유로 새 저장소를 만들지 않는다.

## 10. 동일 기준일 멱등성

동일한 1단계 인증 일봉과 동일한 `target_as_of` 입력에 대해 주봉·월봉 결과는
결정적으로 동일해야 한다.

```text
동일 입력 → 동일 파생 결과
```

실행 시점 계산만 수행하고 영구 상태 변경이 없다면, 1단계와 동일한 `NOOP`
파일 상태를 억지로 만들 필요는 없다.

## 11. 소비 계층 보호 원칙

2단계 계약 때문에 기존 소비 계층 의미를 즉시 통합하거나 변경하지 않는다.

특히 보호 대상:

- Pattern A
- Pattern A FAST
- FAST Core
- 종목 리포트
- 백테스트

기존 소비 계층별 기준일 처리·완료 판정 중 2단계 공통 계약으로 흡수할 수 있는
부분과, 각 전략 고유 의미로 남겨야 하는 부분을 구분한다.

금지:

- FAST의 `W-FRI` 과거 신호 기준점 변경
- 백테스트 결과를 바꾸는 조용한 이관
- 기존 동결(frozen) 전략 의미 변경
- 소비 계층 전수 리팩터링

## 12. 2단계 완료 상태

2단계 결과 상태는 다음과 같이 정의한다.

| 상태 | 의미 |
|---|---|
| `PASS` | `target_as_of` 일관성 확보, 1단계 인증 일봉 사용, 주봉·월봉 파생 정상, `COMPLETE`/`PROVISIONAL` 판정 정상, 소비 계층 의미 훼손 없음 |
| `BLOCKED` | 1단계 인증 경계 부족, rolling 거래일 권위 부족, 입력 일봉 권위 확인 불가 등 |
| `FAILED` | 계약상 예상하지 못한 구현 오류 |

`NOOP`은 필요한 경우에만 사용한다. 영구 산출물이 없는 실행 시점 파생에 억지로
`NOOP` 개념을 도입하지 않는다.

## 13. 현재 구조 재사용 결론

```text
2단계 기본 전략 = 기존 구조 재사용 + 최소 조율 계층 추가 (`REUSE_WITH_MINIMAL_WRAPPER`)
```

재사용:

- `to_weekly`, `to_monthly`
- `MarketCalendarAuthority`
- 1단계 인증 일봉
- 기존 PIT/`as_of` 슬라이싱 의미

최소 신규 범위 후보:

- `target_as_of` 조율 계층
- 파생 기간 상태(`COMPLETE`/`PROVISIONAL`) 판정 조율 — §4.1·§5에서 이미
  확립된 권위를 조합하는 수준이며, 별도 신규 운영 거래일 권위를 만들지 않는다
- 공통 결과 요약

별도 주봉·월봉 저장소는 기본 범위가 아니다.

## 14. 실운영 검증 근거

이 계약과 구현은 합성 시험 데이터뿐 아니라 실제 운영 입력으로도 읽기 전용
검증을 거쳤다.

```text
운영 certified_through = 2026-09-17

실제 검증 종목:
005930
068270
035420

검증 시나리오:
- 완료 금요일 2026-09-11 → weekly COMPLETE
- 비거래일 2026-09-12 → weekly COMPLETE
- 주중 2026-09-17 → weekly PROVISIONAL
- 완료 월 2026-08-31 → monthly COMPLETE
- 최신 미완료 월 2026-09-17 → monthly PROVISIONAL
- 동일 입력 재실행 → 결정적 동일 결과

최종 결과: PASS
```

실제 `RepositoryV2DailyLoader`/`MarketDataRepositoryV2`로 일봉을 읽고,
`load_rolling_production_market_calendar()`로 실제 운영 캘린더 권위를 읽어서
`derive_periods()`에 그대로 전달했다(합성 `MarketCalendarAuthority.from_dates()`
사용 안 함). 세부 행 단위 결과는 이 문서에 포함하지 않는다.

## 15. 관련 현재 기준 문서

- [데일리 업데이트 기준 V01](daily_update_contract_v01.md) — 1단계 상위 계약
- [수정주가·원천 시장데이터 결합 계층](market_data_repository_v02.md)
- [현재 수정주가 저장소 계약](adjusted_price_store_v02.md)
