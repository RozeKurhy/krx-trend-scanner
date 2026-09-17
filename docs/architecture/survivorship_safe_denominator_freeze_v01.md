survivorship_safe_denominator_freeze_v01.md

# 생존편향 방지 과거 분모 동결 (Survivorship-Safe Historical Denominator Freeze v01)

`SURVIVORSHIP_SAFE_DENOMINATOR_FREEZE_V01`은 생존편향을 방지하는 표준
universe 계약을 동결한다. 앞으로의 모든 E2E consumer(AdjustedPriceStore,
FastCore/Julia backtest, Market Breadth)는 자체 universe를 다시 계산하지
않고 이 계약을 사용해야 한다.

## 1. 서로 다른 두 개념 — 하나의 ticker 목록으로 합치지 않는다

**Population Universe**: 2010-01-04부터 2026-08-21 사이에 한 번이라도
`COMMON`이었던 모든 identity다. "이 identity가 한 번이라도 범위에 들어오는가"
라는 질문에 답하며, population 수준 consumer(AdjustedPriceStore population
target, coverage denominator, validation sampling universe)가 사용한다.

**Point-In-Time (PIT) Common Denominator**: 각 과거 거래일에 실제로 해당
날짜의 `COMMON`이었던 identity다. "날짜 D의 투자 가능한 보통주 universe는
무엇인가"라는 질문에 답하며, 생존편향 방지 backtest와 날짜별 시장 통계
(breadth, advance/decline, new-high/new-low)가 사용한다.

두 개념은 하나의 정적 ticker 목록으로 합치지 않는다. 예를 들어 2013~2015년에
COMMON이었다가 2016~2018년에 NOT_COMMON이 된 ticker는 한때 common이었으므로
Population Universe에는 포함하지만, 2016~2018의 PIT denominator에서는 반드시
제외한다.

## 2. 분리해야 하는 이유 — survivorship bias

현재 common-stock 목록으로 "날짜 D의 universe"를 재구성하는 backtest는 그
이후 상장폐지·합병·재분류된 identity를 조용히 누락한다. 이것이 바로
survivorship bias다. PIT denominator는 과거 날짜의 denominator가 오늘의
상태에 의존하지 않도록 하기 위해 존재한다.

이 계약은 다음 두 가지 실패를 방지한다.

- **Current-list broadcast**: 오늘 현재 common인 약 2,557개 ticker를 모든
  과거 날짜의 universe로 사용하는 방식이다. 이 방식은 과거에만 존재했던
  상장폐지 common 605개 identity를 누락한다.
- **Historical-label broadcast**: ticker의 *최종* 분류 label을 전체 이력에
  적용하는 방식이다. 전체적으로 `COMMON_REQUIRED`인 ticker도 과거에는
  `NOT_COMMON` 구간(예: SPAC 단계)이 있었을 수 있다. 그 구간에 COMMON을
  소급 적용하는 것은 이 동결이 방지하려는 look-ahead bias다.

## 3. Identity를 고려한 interval 의미

두 artifact는 identity를 항상 `(ticker, ISU_CD, market)`으로 식별하며
`ticker`만 사용하지 않는다. ticker 문자열은 전체 이력에서 유일하다고 보장할
수 없기 때문이다(현재 archive에서 ticker 재사용은 0건이었지만, 계약은 향후
archive 버전에서도 이를 가정하지 않는다. `historical_authority_reconciliation`
Section 6 참조). 모든 COMMON interval은 동결된 거래일 달력
(`historical_trading_calendar.json`, 4,095 dates, 2010-01-04..2026-08-21,
`trading_dates_sha256` 고정)을 기준으로 `effective_from`/`effective_to`를
기록한다.

## 4. 단일 계산 경로

두 artifact는 전체 authority를 **하나의 공통 순회**로 처리해 파생한다.

```
load_basic_info_snapshots()                       # raw KRX Basic Info 파일 8,190개
  -> build_pit_identity_timeline()                # identity별 시간순 관측값
  -> classify_full_universe()                     # row-pure 분류 + 보완 authority override
                                                    #   동결된 1,116개 대상만이 아니라
                                                    #   관측된 모든 identity에 적용
  -> derive_population_and_pit_records()           # 단일 순회: any-ever-COMMON -> population,
                                                    #   COMMON interval -> PIT denominator
```

`classify_full_universe`(`historical_authority_reconciliation.py`)는 동결된
1,116개 historical-only reconciliation에서 이미 검토·테스트한
`_classify_observations`/`_intervalize` 로직을 그대로 재사용하며, target-list
filter만 제거한다. Population과 PIT를 독립적으로 계산하지 않기 때문에 아래
Section 6의 union invariant는 우연히 두 경로가 일치한 결과가 아니라 실제
파생 규칙이 된다.

이 모듈은 별도로 유지되는 live `InstrumentMetadataResolver`
(`src/trend_scanner/universe/instrument_metadata.py`,
`instrument_metadata_authority.md` §1-17)와 의도적으로 조정하지 않는다. 해당
시스템은 Basic Info가 아닌 KRX MDC를 상위 원천으로 사용하고 분류 규칙도
다르다. 2026-08-21 snapshot에서 현재 COMMON을 2,666개
(numeric 2,641 / alpha 25)로 보고하는데, 이는 이 동결이 독립적으로 계산한
현재 common 2,557개(numeric 2,534 / alpha 23)와 다르다. 이 차이는 예상된
것이며 어느 시스템의 결함도 아니다. 두 pipeline은 서로 다른 질문에 답한다
(현재 live MDC 검증 asset type과 전체 이력 Basic-Info 기반 PIT 분류)며,
ticker별 결과가 일치할 필요도 없다. 이 동결의 Population/PIT 수치는 **오직**
Basic Info와 보완 authority chain에서 산출하며 live resolver 결과를 사용하거나
강제로 일치시키지 않는다.

## 5. Historical-only reconciliation 하위 집합

1,116개 ticker로 동결된 historical-only reconciliation target
(`HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION_V01` 및 residual resolution
rounds)은 full-universe 파생 결과에서 다음과 같이 나뉜다.

| 구분 | count | Population 포함 여부 |
|---|---|---|
| Frozen target, `HISTORICAL_COMMON_REQUIRED` | 605 | yes (historical-only, not currently common) |
| Frozen target, `HISTORICAL_NOT_COMMON` | 511 | no |
| Outside frozen target (row-pure resolves cleanly without needing supplemental review) | 2,557 | yes (all currently common) |

`605 + 2,557 = 3,162`로 Population Universe total과 정확히 일치한다. 이는
파생 후 검증된 결과이며, 파생 과정이 이 수치에 맞도록 조정된 것은 아니다
(Section 9의 주의사항 참조).

### 5.1. 시장별 집계와 시장 간 전환

Population Universe의 시장별 집계는 다음과 같다.

- `kospi_ever_common_identity_count`: 982
- `kosdaq_ever_common_identity_count`: 2,202
- `cross_market_common_identity_count`: 22
- Total unique identities: `982 + 2,202 - 22 = 3,162`

단순 합계(`3,184`)와 Population total(`3,162`)의 차이 22는 과거 기간에
KOSDAQ에서 KOSPI로 이동한 22개 cross-market company의 정확한 집합이다
(예: `035720` Kakao, `068270` Celltrion, `022100` POSCO DX).

**집계 의미:**
- KOSPI(982)와 KOSDAQ(2,202) count는 해당 시장에서 과거 기간 중 한 번이라도
  COMMON interval을 가진 identity의 "ever-common by market" 수다. **현재
  snapshot bucket 간 상호 배타적 count가 아니다.**
- 4,095개 거래일 전체에서 같은 날짜의 dual-market membership은 엄격히 0이다.
  어떤 identity도 같은 날짜에 KOSPI COMMON과 KOSDAQ COMMON에 동시에 속하지 않는다.
- 전환 경계는 연속적이다. 모든 이동 identity에서 이전 시장의 마지막 거래일과
  새 시장의 첫 거래일은 정확히 연속된 거래일이다(trading day difference = 1,
  overlap 0, gap 0).

## 6. Population ⋃ PIT 불변식

어떤 PIT COMMON interval에든 나타나는 identity는 Population Universe에도
반드시 나타나야 하며, 반대도 성립해야 한다.
`evaluate_population_pit_union_invariant`가 `(ticker, ISU_CD)` 단위로 이를
검사하며, 필수이고 면제할 수 없는 gate다(그렇지 않으면
`BLOCKED_UNION_MISMATCH`). 두 결과가 같은 순회(Section 4)에서 나오므로
불일치는 예상 가능한 edge case가 아니라 파생 로직의 실제 bug를 뜻한다.

## 7. Alpha 구성 종목과 수정주가 적격성 — 별개의 질문

23개의 alphanumeric identifier ticker(예: `0008Z0`, `0009K0`, `0010F0` 형태)는
정상적인 historical COMMON identity로서 Population Universe에 포함된다. 모두
KRX의 alphanumeric ticker 발행 규칙에 따라 도입된 현재 active common stock이다.

반대로 기존 supplemental authority는 preferred-class alphanumeric ticker
(예: `00781K` 코리아써키트2우선주(신형), 14개 preferred-class residual item
전체, 58개 historical NOT_COMMON alpha item 전체)가 `HISTORICAL_NOT_COMMON`임을
확인했다. 이들은 Population Universe와 PIT COMMON interval 모두에서 엄격히
**제외된다**(intersection count = 0).

이 정상적인 alphanumeric COMMON identifier에 대해 `PyKRX adjusted=True`가
실제로 수정주가 OHLC를 제공할 수 있는지는 **별도로 검증되지 않은** 질문이다.
이 동결은 이를 테스트하지 않으며, source eligibility가 불명확하다는 이유로
alpha identity를 제외하지 않는다. 여기서 alpha membership을 조용히 누락하면
실제로 common stock이었는지와 무관한 이유로 historical universe를 축소하는
survivorship 인접 bug가 된다. 수정주가 원천 적격성은
`ADJUSTED_PRICE_STORE_BOUNDED_LIVE_PILOT_V01`로 명시적으로 미룬다.

## 8. 미래 사건 누출

`classify_full_universe`와 population/PIT 파생은 분석 날짜를 기준으로 한
"미래" 개념을 사용하지 않는다. 모든 관측값은 자신의 `effective_date` 공식
필드만으로 분류하며, 필요한 경우에도 인용된 증거가 동결된 historical cutoff
이전인 supplemental-authority record만 사용한다(`instrument_metadata_authority.md`
§20 참조). COMMON interval의 `effective_from`은 실제 COMMON으로 관측된
날짜보다 과거로 소급해 확장될 수 없다.

## 9. Consumer가 자체 universe를 계산하지 않는다

과거 사용 코드(backtest engine, market-breadth calculator)는 각자 보유한
"current" 데이터 원천에서 ticker 목록을 파생하지 말고 이 동결의 artifact(산출물)를
로드해야 한다. Consumer별 재계산은 어떤 과거 날짜에 survivorship-bias 보호를
적용할지 서로 달라지는 위험을 만든다.

## 10. Artifact와 loader 계약

- `artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/v01/historical_common_population_v01.json`
  — Population Universe records + `population_manifest_sha256`.
- `.../pit_common_denominator_v01.json` — canonical COMMON interval records
  (not a per-date manifest — Section 3's interval-first design) +
  `pit_common_denominator_sha256` + the calendar's `trading_dates_sha256`.
- `.../survivorship_safe_denominator_freeze_v01.json` — closure summary:
  status, authority checkpoint SHA, supplemental authority provenance,
  trading calendar identity, population/PIT summary stats + hashes,
  historical-only reconciliation counts, gate results, `created_from_head`.

Loader API (`src/trend_scanner/universe/survivorship_safe_denominator_freeze.py`):

- `load_historical_common_population(path=...)` — Population Universe record 목록.
- `load_pit_common_intervals(path=...)` — canonical COMMON interval record 목록.
- `get_common_universe_as_of(date, market=None, *, intervals=None)` —
  정확히 동결된 거래일 기준의 identity-aware COMMON 집합을 반환한다.
  Fail-closed: 동결 달력 범위 밖 날짜나 비거래일이면 `FreezeContractError`를
  발생시키며, 가장 가까운 거래일이나 현재 전체 집합으로 fallback하지 않는다.

AdjustedPriceStore/FastCore/Julia/Market Breadth를 이 loader로 실제 전환하는
작업은 이 freeze 범위 밖이다(`ADJUSTED_PRICE_STORE_BOUNDED_LIVE_PILOT_V01` 및
후속 단계). 이 freeze는 해당 consumer가 사용할 안정적인 계약만 제공한다.
