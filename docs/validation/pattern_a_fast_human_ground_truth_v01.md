# Pattern A Fast Human Ground Truth Dataset v0.1

================================================================================
0. 문서 상태
================================================================================
Phase: 13C-1 — Ground Truth Dataset Preparation
Status: **READY_FOR_HUMAN_REVIEW / 13C-1 Preparation FINAL** (13C-1 준비
단계 자체를 이번 correction으로 최종 봉인, w.md "[Phase 13C-1 Final
Sampling Balance Correction]" §목표 — Human Annotation은 여전히 별도
13C-2로 대기)
Base: `5d8af8245fedd5591595d91d06e3b333938e0ff7` (지난 세 라운드 요약:
Cohort A 선정 로직 결함 2회 수정(§4) → Monthly Review Data Sufficiency
Gate 도입(§6) → Cohort B 날짜 집중(35/45가 한 주) 발견 후 quarter-end
그리드를 2024-09~2026-03으로 확장했으나 그 결과 2016~2023년 표본이
전부 사라짐(§3) → 이번 correction에서 Cohort B를 RECENT_SYSTEMATIC /
HISTORICAL_COVERAGE 두 stratum으로 분리해 과거 market regime 표본을
다시 확보)

> **13C-2 PIT annotation IN PROGRESS / checkpoint commit**: 이 문서가
> 기술하는 13C-1 dataset 구성(60건 sample_id/reference_date/source_cohort
> /Pattern A Benchmark Context/manifest/reserved set/charts)은 그대로
> FROZEN이며 이번 checkpoint에서 전혀 수정되지 않았다. 40개 sample의
> PIT(Outcome 보기 전) Human Annotation 진행 상황은
> [pattern_a_fast_human_pit_annotation_checkpoint_v01.md](pattern_a_fast_human_pit_annotation_checkpoint_v01.md)
> 참고. 그 40개에 대한 Human Outcome Label(`human_label`)까지 완료된
> 최신 상태는
> [pattern_a_fast_human_outcome_annotation_v01.md](pattern_a_fast_human_outcome_annotation_v01.md)
> 참고(advisor 리뷰 대기 중, 아직 Phase 13C-2 CLOSED 아님).
Data cutoff (as_of): 2026-08-14
Network requests: 0 (전부 로컬 `data/raw/stocks/*.parquet` 캐시)

--------------------------------------------------------------------------------
1. Purpose
--------------------------------------------------------------------------------
Phase 13A에서 Pattern A Fast의 목적을, Phase 13B에서 Weekly Lifecycle Stage
의미를 정의했다. 이번 13C-1은 실제 KRX 종목의 과거 차트를 사람이 검토할 수
있도록 Point-In-Time(PIT) 기반 Human Ground Truth Dataset을 준비하는
단계다.

핵심 질문은 "사람이 실제 차트를 봤을 때 어떤 시점을 좋은 Fast Trigger라고
보는가? 어떤 시점은 너무 이르고, 어떤 Trigger는 실패하며, 어떤 시점은 이미
너무 늦었는가?"이다. 이번 커밋은 그 질문에 답하기 위한 sample 후보만
준비한다 — Feature 공식, Threshold, Classifier, Score 연구가 아니다.

--------------------------------------------------------------------------------
2. Authoritative Contracts
--------------------------------------------------------------------------------
다음 문서를 공식 계약으로 사용하며 이번 작업으로 수정하지 않는다:
* [docs/specs/pattern_a_fast_definition.md](../specs/pattern_a_fast_definition.md) (Phase 13A, CLOSED)
* [docs/specs/pattern_a_fast_lifecycle_contract.md](../specs/pattern_a_fast_lifecycle_contract.md) (Phase 13B) —
  Weekly Lifecycle Stage 5개(`WATCH`/`SETUP`/`TRIGGER`/`TREND`/`EXTENDED`)의
  의미를 그대로 사용한다.

--------------------------------------------------------------------------------
3. Dataset Scope
--------------------------------------------------------------------------------
* 총 샘플: **60건** (목표 60 달성)
* 고유 티커: **55개**
* 시장: KOSPI 39 / KOSDAQ 21
* reference_date 범위: 2018-06-29 ~ 2026-03-27
* reference_date 연도 분포: 2018(3) / 2020(3) / 2022(3) / 2023(3) /
  2024(5) / 2025(27) / 2026(16) — **7개 연도**에 걸쳐 존재(직전 버전은
  2024-09~2026-03 단 1.5년뿐이었음)
* Cohort 구성: `PATTERN_A_HISTORICAL_CONTEXT` 15 / `RECENT_SYSTEMATIC` 33 /
  `HISTORICAL_COVERAGE` 12 (§4)
* Completed monthly bars at reference: 최소 37 / 중앙값 52.0 / 최대 142
  (전부 Monthly Review Data Sufficiency Gate ≥36 통과, §6·§14 참고)
* Max single reference_date: 13/60(21.7%, `2026-03-27`) — 22개 서로
  다른 reference_date에 분산(직전 버전 45건 중 최대 18건이 한 날짜에
  몰렸던 것에서 자연스럽게 개선, §5 참고)
* 티커당 최대 episode: 2 (§48 준수, 실제 최대 2)

**이번 correction의 배경(w.md "[Phase 13C-1 Final Sampling Balance
Correction]")**: 직전 버전은 Cohort B 날짜 집중(35/45가 2025-06-27 한
주) 문제를 quarter-end 그리드를 2024-09~2026-03으로 넓혀 완화했지만,
그 부작용으로 top-N by |score| 선정 방식이 2016~2023년 후보를 전부
순위에서 밀어내 **dataset 전체 시간 범위가 2024-09~2026-03(약
1.5년)으로 좁아졌다.** 이번 correction은 Cohort B를 두 stratum으로
분리해 이 문제를 해결했다:
- **RECENT_SYSTEMATIC**(33건): 기존 top-N by |score| 방식 그대로,
  quarter-end 그리드를 2024-09~2026-03(7개 날짜)로 한정.
- **HISTORICAL_COVERAGE**(12건): 2024-09 이전 실제 market regime을
  포함하기 위한 별도 stratum. Outcome extreme score top-N이 아니라
  sample_id의 stable hash로 결정론적으로 선택해, forward return 크기가
  선정 확률을 좌우하지 않도록 했다(§4).

**정직한 한계**: 2018/2020/2022/2023 각 3건씩 뽑았지만, 실측 eligible
pool(36개월 게이트 + `weekly_return_screen` 통과 + 유효 `source_reason`
분류를 모두 만족하는 후보 수)은 2018-06-29 48개, 2020-09-25 56개,
2022-12-30 66개, 2023-06-30 66개로 **여전히 얇다**(로컬 캐시의 근본적인
이력 커버리지 한계 — 대부분 티커의 캐시 시작일이 최근 3년 내라는 사실은
이전 correction들에서 이미 확인됨). w.md §3 "얇은 historical pool
자체가 exclusion 이유는 아니다"라는 지시에 따라 이 얇음 자체를 후보를
늘리기 위한 조작 없이 그대로 받아들이고 여기 기록한다 — 이 dataset은
prevalence 추정용이 아니므로 얇은 pool도 sample 다양성 확보라는
목적에는 문제가 없다. Historical stratum의 버킷 분포도 강제로 맞추지
않았다(대부분 `AMBIGUOUS_STRUCTURE`로 쏠리는 게 실제 얇은 pool의
자연스러운 특성 — §4 참고). 더 넓은 연도 커버리지(예: 2016~2017)나
버킷 균형을 원한다면 로컬 캐시 자체의 장기 이력 백필(별도 Phase)이
필요하며, 이는 13C-2 리뷰 이후 사용자가 판단할 사안이다.

**정직한 한계 추가(시장 쏠림)**: `HISTORICAL_COVERAGE` 12건은
**100% KOSPI**다(예: LG화학/GS/한화에어로스페이스/HMM/LS/LG이노텍 —
실제 선택된 티커 이름 자체가 이미 장기 상장 대형주 위주임을 보여준다).
36개월 게이트가 "그 historical 시점에 이미 오래 상장돼 있던 종목"만
통과시키는 구조이므로 자연스러운 결과이며, 의도적으로 KOSPI를 우대한
게 아니다. 그 결과 dataset 전체 시장 비율도 이전 버전 KOSPI 33/KOSDAQ
27에서 이번 버전 **KOSPI 39/KOSDAQ 21**로 이동했다 — 이 역시 강제로
맞추지 않고 있는 그대로 기록한다.

--------------------------------------------------------------------------------
4. Selection Strategy
--------------------------------------------------------------------------------
**Cohort A — Pattern A Historical Context** (15건: `PATTERN_A_PRE_TRANSITION`
14 + `PATTERN_A_PRE_EARLY` 1):
`artifacts/scanner/pattern_a_universe_scan_20260814.csv`의 실제
`candidate_state == 'candidate'`(현재 TRANSITION/EARLY_TREND) 티커 180개를
ticker 순서로 순회하며, frozen Pattern A evaluator(`evaluate_pattern_a` +
`build_historical_snapshot`)로 2026-08-14부터 backward 탐색해 **현재
episode의 entry_boundary**(TRANSITION/EARLY_TREND로 최초 진입한 완료
주봉)를 먼저 찾고, 그보다 **최소 12주 이전, 최대 104주 이내**에서 실제
BASE였던 완료 주봉을 `reference_date`로 사용했다
(`find_base_reference_before_entry`). entry_boundary 시점 stage가
`early_trend`면 `PATTERN_A_PRE_EARLY`, 아니면 `PATTERN_A_PRE_TRANSITION`.
12주 버퍼를 만족하는 BASE가 없는 티커는 skip하고 다음 후보로 top-up했다
(180개 중 2건 skip, 15개 목표 그대로 달성).

**왜 이렇게 만들었는가(2회의 회귀 기록)**: 최초 구현은 "cutoff에서 가장
가까운 BASE"를 그대로 `reference_date`로 썼는데, 이는 구조상
entry_boundary 바로 한 주 전이 되어(다음 주 바로 TRANSITION 시작) 관측
가능한 lead time이 거의 항상 1주로 눌렸다 — Cohort A가 원래 보여주려는
"Fast가 Pattern A보다 몇 주 먼저 보이는가"(13A §26 개념 예시)를 이 cohort
자체가 보여줄 수 없는 상태였다. 같은 원인으로 `013700`/`031510` 같은 최근
티커는 outcome 리뷰 창(52주 목표)이 1~2주로 잘려 사람이 Outcome 차트로
`human_label`을 매길 수조차 없었다.

1차 수정(12주 버퍼 도입)만으로는 부족했다 — entry_boundary를 찾는
backward walk가 TRANSITION/EARLY_TREND가 아닌 주가 **단 1주**만 나와도
episode가 끝났다고 판단해 멈췄기 때문에, 실제로는 몇 달째 이어지던
episode를 "최근의 짧은 재진입"으로 오인해 entry_boundary 자체를 실제보다
훨씬 최근으로 잘못 잡는 사례가 다수였다(advisor 2차 검토에서 발견:
15건 중 7건이 `pattern_a_transition_first_after_reference`가 정확히 1주
후였음 — reference가 이미 진행 중인 TRANSITION 구간 내부의 1주짜리 BASE
dip이었다는 뜻). 2차 수정으로 backward walk는 비-TRANSITION/EARLY_TREND
주가 **4주 연속**(gap_tolerance_weeks) 나올 때까지 산발적 1~3주 dip을
무시하고 entry_boundary를 계속 확장하도록 바꿨고, 찾은 BASE 후보도
forward로 최소 4주(confirm_pre_episode_weeks) 연속 TRANSITION/EARLY_TREND
가 아님을 확인한 뒤에만 채택하도록 했다. 수정 후
`pattern_a_transition_first_after_reference` 기준 lead는 5~18주(중앙값
7주)로 안정됐고, outcome 리뷰 창 최솟값은 20주로 늘었다.
`find_base_reference_before_entry`에 이 배경과 함께 기록해 두었다.

**Cohort B는 두 개의 독립적인 sampling stratum으로 구성된다**(이번
correction, w.md §1·§2). 둘 다 같은 고정 규칙(`classify_source_reason`)
으로 버킷팅하지만 날짜 범위와 선택 방식이 다르다.

**Cohort B-1 — RECENT_SYSTEMATIC** (33건, source_cohort=`RECENT_SYSTEMATIC`):
`cache_present` 티커 전수(2,486개, `COHORT_B_TICKER_STRIDE=1`) ×
quarter-end 날짜 그리드 **7개**(`2024-09-27`, `2024-12-27`,
`2025-03-28`, `2025-06-27`, `2025-09-26`, `2025-12-26`, `2026-03-27` —
Recent Regime Pool, 이전 correction에서 확정된 "36개월 게이트 통과
티커가 풍부한" 구간)에서 `weekly_return_screen` 지표를 계산하고 버킷별
**|trailing_return|+|forward_return| 점수 상위 N개**를 선택했다. 이전
버전(45건, 버킷 목표 10/5/8/8/6/8)에서 아래처럼 각 버킷을 비례
축소(45→33)해 Historical Coverage stratum에 자리를 내줬다 — 정확한
숫자를 최적화한 게 아니라 총량을 유지하면서 "일부만 historical로
교체"하기 위한 단순 비례 축소다(w.md §1·§4):

| source_reason | 이전 목표(45건 버전) | 이번 목표 | 선택 |
|---|---|---|---|
| FAILED_BREAKOUT | 10 | 7 | 7 |
| LONG_DOWNTREND_BOUNCE | 5 | 4 | 4 |
| STRONG_UPTREND_ALREADY_EXTENDED | 8 | 6 | 6 |
| NEGATIVE_CONTROL | 8 | 6 | 6 |
| RANGE_BOUND | 6 | 4 | 4 |
| AMBIGUOUS_STRUCTURE | 8 | 6 | 6 |

top-N 방식은 순위에서 밀린 후보를 개별적으로 기록하지 않으므로(밀린
후보 수가 수천 건에 달해 전부 나열하는 것이 비현실적), 재현성을 위해
`selection_manifest.json`의 `selection_strategy.cohort_b_recent_
systematic.selection_stats_per_bucket`에 버킷별 `candidate_pool_size`
(FAILED_BREAKOUT 1,665 / LONG_DOWNTREND_BOUNCE 429 / STRONG_UPTREND_
ALREADY_EXTENDED 1,123 / NEGATIVE_CONTROL 1,542 / RANGE_BOUND 1,087 /
AMBIGUOUS_STRUCTURE 10,803), `picked`, `score_cutoff_min`/
`score_cutoff_max`를 기록했다(§7 재현성 요구사항).

**Cohort B-2 — HISTORICAL_COVERAGE** (12건, source_cohort=
`HISTORICAL_COVERAGE`): 2024-09 이전 실제 market regime 사례를 포함하기
위한 stratum. Outcome extreme score top-N을 쓰지 않는다 — 그러면
"선정 확률이 forward return 크기에 좌우된다"는, 직전 correction에서
발견된 문제(§3)와 똑같은 종류의 편향이 다시 생기기 때문이다(w.md §3).
대신 quarter-end 날짜 4개(`2018-06-29`, `2020-09-25`, `2022-12-30`,
`2023-06-30` — 2016~2023 구간에서 실측으로 eligible pool이 존재함을
확인한 지점, w.md가 예시로 든 2018/2020/2022/2023과 일치) 각각에서:
1. `cache_present` 티커 전수를 screen해 **36개월 게이트를 먼저
   적용**하고(§6), `weekly_return_screen` + `classify_source_reason`
   유효 버킷까지 만족하는 `eligible pool`을 만든다.
2. `sample_id`의 stable hash(`sha256`)로 정렬해 날짜당 상위 3개를
   선택한다(`_stable_hash_key`,
   `scripts/prepare_pattern_a_fast_ground_truth.py`) — 이 정렬은
   가격/수익률과 완전히 무관하며, 같은 입력이면 항상 같은 순서를
   낸다(targeted test로 커버, §10).

eligible pool 크기는 날짜별로 48 / 56 / 66 / 66으로 얇다 — 이 얇음
자체는 제외 사유가 아니라 정직하게 기록해야 할 사실이다(w.md §3, §3
Dataset Scope 참고). `selection_manifest.json`의
`selection_strategy.cohort_b_historical_coverage.
selection_stats_per_date`에 날짜별 `eligible_pool_size`/`picked`/
`selection_method`를 기록했다.

> **구현 메모(이 stratum을 만들며 발견한 버그)**: 최초 구현은 36개월
> 게이트 없이 `weekly_return_screen`만으로 eligible pool을 계산했다 —
> `weekly_return_screen`은 lookback/lookahead 12주(~6개월)만 요구하므로
> 캐시가 최근에 시작된 티커도 대부분 통과해, `2022-12-30`의 "eligible
> pool"이 2,148개로 부풀려졌다(진짜 36개월-게이트 통과 pool은 66개
> 뿐). 최종 선택된 3개 샘플 자체는 `build_row`가 어차피 게이트를
> 다시 적용하므로 안전했지만, 보고되는 pool 크기가 부정확했다 —
> 그래서 eligibility 계산 순서에 36개월 게이트를 앞당겨 넣었다. 위
> 수치는 수정 후 값이다.

classify_source_reason 규칙(고정, 변경 시 이 함수의 docstring도 함께
갱신):
* `FAILED_BREAKOUT`: trailing 12주 수익률 ≥ +15% 이고 forward 12주
  최대낙폭 ≤ -8% 이고 forward 12주 수익률 ≤ +3%
* `LONG_DOWNTREND_BOUNCE`: trailing 52주 수익률 ≤ -30% 이고 trailing
  12주 수익률이 0~+10%
* `STRONG_UPTREND_ALREADY_EXTENDED`: trailing 52주 수익률 ≥ +60%
* `NEGATIVE_CONTROL`: trailing 52주 수익률 ≤ -20% 이고 trailing 12주
  수익률 ≤ -3% 이고 forward 12주 최대상승 < +8%
* `RANGE_BOUND`: trailing/forward 12주 수익률·낙폭·상승폭이 전부 ±10%p 이내
* 나머지는 `AMBIGUOUS_STRUCTURE`

이 규칙은 **sampling(어떤 사례를 dataset에 넣을지) 기준일 뿐 Fast Trigger
판정 규칙이 아니다** — `human_label`/`weekly_stage_at_reference`는 이 값으로
채우지 않는다(§8 참고).

--------------------------------------------------------------------------------
5. Bias Control
--------------------------------------------------------------------------------
* Positive-only sampling 금지 원칙 준수: GOOD 후보(Cohort A, 15) 외에
  RECENT_SYSTEMATIC(33) + HISTORICAL_COVERAGE(12) = 45건이 FAILED_BREAKOUT
  / LONG_DOWNTREND_BOUNCE / STRONG_UPTREND_ALREADY_EXTENDED /
  NEGATIVE_CONTROL / RANGE_BOUND / AMBIGUOUS_STRUCTURE 6개 non-positive
  버킷에 분산되어 포함됨(§4).
* 사후 outcome(가격 metrics)을 sampling에 사용한 것은 명시적으로 허용된
  범위이며, `source_cohort`/`source_reason` 컬럼으로 항상 그 사실을 드러낸다
  (§19 Outcome enriched research set임을 숨기지 않는다).
* 이 dataset의 `GOOD_TRIGGER`/`FALSE_TRIGGER` 비율은 production prevalence
  추정치가 아니다.

--------------------------------------------------------------------------------
6. PIT Rules
--------------------------------------------------------------------------------
* **Selection target date vs 실제 reference_date 구분(w.md §9)**:
  `RECENT_COHORT_B_DATES`/`HISTORICAL_COVERAGE_DATES`에 적힌 quarter-end
  문자열(예: `2022-12-30`)은 어디까지나 **selection target date** —
  후보를 뽑을 때 쓰는 임의의 날짜일 뿐, 완료 주봉 라벨이 아닐 수도
  있다. `resolve_completed_weekly_reference`가 이를 실제
  `reference_date`(항상 완료된 W-FRI 주봉 라벨)로 변환하며, 방향은
  **항상 과거뿐이다** — target date 이하에서 가장 가까운 완료 주봉만
  찾고, 미래 주로 이동하거나 없는 데이터를 미래 값으로 backfill하는
  일은 없다(없으면 None). 그래서 target date `2022-12-30`(금요일)이
  실제로는 `2022-12-23`으로 resolve된 샘플이 있다(`build_historical_
  snapshot(..., include_incomplete_periods=False)`의 `weekly_as_of`를
  그대로 반환 — 가장 가까운 날짜로 silent substitution하지 않는다,
  §35). dataset에는 selection target date가 아니라 이 실제
  resolve된 `reference_date`만 저장된다.
* Chart PIT slice(`build_chart_slices`)는 monthly/weekly/daily 각각
  `index.max() <= reference_date`를 **assert로 machine-check**한다(§26,
  targeted test `test_build_chart_slices_no_future_leakage` /
  `test_build_chart_slices_daily_pit_excludes_future_rows_even_if_present`
  로 커버).
* Outcome slice는 `outcome_review_end = min(reference_date + 52주,
  캐시 마지막 날짜)`까지만 포함한다.
* `pattern_a_transition_first_after_reference` /
  `pattern_a_early_trend_first_after_reference`는 Pattern A 자체의 사후
  벤치마크 조회 결과이며, reference 시점 Stage 판단에는 전혀 쓰이지 않는다.
* **Monthly Review Data Sufficiency Gate**: 모든 샘플은 `reference_date`
  시점 completed monthly bars가 `MONTHLY_HISTORY_MIN_BARS = 36` 이상이어야
  한다(`monthly_history_status`, `src/trend_scanner/validation/
  pattern_a_fast_ground_truth.py`). 이 36은 Pattern A Fast Feature나
  Threshold가 아니라 "월봉에서 장기 흐름을 사람이 실제로 판단할 수
  있는가"를 보장하는 Human Review Data Quality 기준일 뿐이며, Pattern A
  Fast Monthly Regime 공식으로 쓰지 않는다. 미달 후보는
  `MONTHLY_HISTORY_INSUFFICIENT`로 fail-closed 처리되어 dataset에서
  제외되고 다음 후보로 top-up된다(§14 참고). 이전 버전(60건)에서는 이
  게이트가 그 시점 `pattern_a_stage_at_reference` 결측 29건과 100%
  일치했으나, 이번 correction으로 표본 구성이 바뀌면서 그 일치가
  깨졌다 — §11 참고(우연의 일치였을 뿐 구조적 보장이 아니었다는 뜻).

--------------------------------------------------------------------------------
7. Source Cohorts
--------------------------------------------------------------------------------
§4 참고. 요약: `PATTERN_A_HISTORICAL_CONTEXT`=Pattern A 실제 후보의 과거
BASE 지점(15), `RECENT_SYSTEMATIC`=2024-09~2026-03 systematic
negative/ambiguous cohort(33), `HISTORICAL_COVERAGE`=2024-09 이전
market regime을 위한 deterministic-hash 선택 cohort(12). 세 cohort 모두
`source_cohort` 컬럼으로 dataset에 명시된다.

--------------------------------------------------------------------------------
8. Schema
--------------------------------------------------------------------------------
Source dataset: `artifacts/pattern_a_fast/ground_truth/pattern_a_fast_ground_truth_source_v01.csv`

| column | 설명 |
|---|---|
| sample_id | `{ticker}_{YYYYMMDD}`, 고유 |
| episode_id | `{ticker}_E01`, `E02`... 티커별 episode 순번 |
| ticker / name / market | 종목 메타데이터 |
| reference_date | 완료 주봉 PIT 기준일 |
| source_cohort / source_reason | 왜 dataset에 들어왔는지(Human Label 아님) |
| weekly_stage_at_reference | **UNLABELED** (13C-2 Human 필드) |
| trigger_event_observed / trigger_event_date | **UNLABELED** / 빈값 (13C-2 Human 필드) |
| human_label / human_confidence / human_notes | **UNLABELED** / 빈값 (13C-2 Human 필드) |
| pattern_a_stage_at_reference 등 pattern_a_* | Pattern A Benchmark Context (frozen evaluator, 이번 단계에 채움) |
| lead_weeks_to_pattern_a_* | **NOT_EVALUATED** (trigger_event_observed=YES일 때만 13C-2에서 계산, §30) |
| completed_monthly_bars_at_reference | reference_date 시점 completed monthly bars 수 (Human Review Data Quality evidence, Fast Feature 아님) |
| monthly_history_status | `OK` (전 샘플, ≥36 게이트 통과) — Human Review Data Quality metadata |
| human_review_eligible | `True` (전 샘플 — 게이트 미통과 후보는 애초에 dataset에서 제외됨) |
| pit_data_start / pit_data_end / outcome_review_end | PIT/Outcome 경계 |
| data_status / quality_flags | 품질 상태 |

Human Review Worksheet(사람이 직접 채우는 원본):
`artifacts/pattern_a_fast/ground_truth/pattern_a_fast_human_review_v01.csv`
— `sample_id, ticker, name, reference_date, weekly_stage_at_reference,
trigger_event_observed, trigger_event_date, human_label,
human_confidence, human_notes`만 포함(§43/§44, machine metadata와 분리).

--------------------------------------------------------------------------------
9. Human Annotation Workflow
--------------------------------------------------------------------------------
§28 순서를 그대로 따른다:
1. PIT Monthly/Weekly/Daily 차트 확인 (`charts/{sample_id}_monthly_pit.png`,
   `_weekly_pit.png`, `_daily_pit.png`)
2. `weekly_stage_at_reference` 기록
3. `trigger_event_observed` 기록
4. 필요하면 `trigger_event_date` 기록 (§15 — 관측되지 않으면 `NOT_OBSERVED`
   유지, 임의 생성 금지)
5. PIT 판단 저장
6. Outcome 차트 공개 (`_weekly_outcome.png`)
7. `human_label` 기록
8. `human_confidence` 기록 (HIGH/MEDIUM/LOW)
9. `human_notes` 작성

`pattern_a_fast_human_review_v01.csv`에 직접 기록한다.

--------------------------------------------------------------------------------
10. Blind Review Procedure
--------------------------------------------------------------------------------
PIT 차트(`*_monthly_pit.png`, `*_weekly_pit.png`, `*_daily_pit.png`)는
`reference_date` 이후 가격/거래량을 전혀 포함하지 않는다(§26, assert로
machine-check). Outcome 차트(`*_weekly_outcome.png`)만 `reference_date`
이후 움직임을 보여주며, 빨간 점선으로 `reference_date`를 표시해 PIT/Outcome
경계를 시각적으로 구분한다. STEP 1~5(PIT 판단)를 먼저 마친 뒤에 Outcome
차트를 열어보는 순서를 권장한다(§27 — Outcome으로 weekly_stage_at_reference
를 재작성하지 않는다).

--------------------------------------------------------------------------------
11. Pattern A Benchmark Context
--------------------------------------------------------------------------------
`pattern_a_stage_at_reference` / `pattern_a_candidate_state_at_reference` /
`pattern_a_score_at_reference`는 frozen Pattern A Score v0.2 / Stage
Classifier v0.1을 reference_date 시점 PIT snapshot에 그대로 적용한
결과다(Pattern A는 DONE/FROZEN, 로직 수정 없음). Pattern A는 Fast Ground
Truth가 아니라 **Benchmark**로만 쓰인다 — Pattern A가 나중에 EARLY_TREND가
됐다고 자동으로 GOOD_TRIGGER를 부여하지 않으며, Pattern A가 Candidate가
아니라고 자동으로 FALSE_TRIGGER를 부여하지도 않는다.

`pattern_a_stage_at_reference`는 60건 중 **59건**이 채워져 있다(결측
1건, `012170_20250328`, completed monthly bars 43개로 게이트는
통과). 원인은 이전 correction에서 확인된 것과 동일한 종류다 — Pattern A
Stage Classifier가 **주봉 파생 feature(`weekly_ma12_slope`) 계산에
필요한 warm-up이 부족**하면 `stage=None`, `candidate_state=
INSUFFICIENT_DATA`를 반환한다(재현 확인: `evaluate_pattern_a(...).
stage_result.reason_codes == ('insufficient_data',)`,
`weekly_ma12_slope == nan`). Monthly Review Data Sufficiency Gate(월봉
36개, §6)와 Pattern A 자체의 내부 데이터 요구조건(월봉 + 주봉 feature
warm-up)은 겹치지만 동일하지 않으므로, 표본 구성이 바뀔 때마다 이런
결측이 0~1건 정도 나타날 수 있다 — 구조적으로 보장된 결측 0이
아니라는 뜻이다. 이 결측 자체는 dataset의 결함이 아니다 — Pattern A는
Benchmark로만 쓰이므로(§11 서두), `INSUFFICIENT_DATA`도 그 시점
frozen Pattern A가 실제로 내리는 정직한 판단이며, 이를 억지로 채우거나
게이트를 더 추가해 강제로 없애지 않는다(§8 "quota 최적화는 하지 말
것"과 같은 취지 — 특정 컬럼의 결측 0을 목표로 후처리하지 않는다).

**`pattern_a_transition_first_after_reference`/`_early_trend_first_...`
읽는 법 — "최초 접촉"이지 "안정적으로 정착한 시점"이 아니다.** 이 두
컬럼은 `first_stage_dates_after`가 reference_date 이후 처음으로 Pattern A
가 해당 Stage에 "닿은" 완료 주봉을 반환한 값이다. Pattern A Stage도
비단조(non-monotonic)이므로, 짧게 TRANSITION을 스쳤다가 다시 BASE로
돌아간 뒤 한참 후에야 진짜로 정착하는 경우가 실제로 있다 — 예:
`001210`(금호전기)은 `reference_date=2025-03-14`, entry_boundary(Cohort A
선정에 쓴, 2026-08-14까지 gap-tolerant하게 이어진 "현재" episode의
시작점)는 `2026-07-03`(약 68주 뒤)인데, `pattern_a_transition_first_
after_reference`는 `2025-05-02`(7주 뒤)로 훨씬 이르다 — 그 사이에 짧은
TRANSITION 되돌림이 있었다는 뜻이다(entry_boundary는 4주 연속 이탈에서만
episode 종료로 판단하므로, 그보다 짧은 되돌림은 episode에 포함되지만
`first_stage_dates_after`의 "최초 접촉" 정의로는 그 되돌림 자체가
먼저 잡힌다). 따라서 이 컬럼만으로 "Pattern A 대비 Fast 리드타임"을
계산하면 실제보다 과소평가될 수 있다 — 13C-2/13H에서 실제 PIT/Outcome
차트를 보고 판단해야 하며, 이 컬럼은 참고용 benchmark 조회 결과일 뿐이다.

--------------------------------------------------------------------------------
12. Trigger Event Handling
--------------------------------------------------------------------------------
`trigger_event_observed`/`trigger_event_date`는 사람이 차트를 보고
명시적으로 TRIGGER Stage 진입을 확인했을 때만 채우는 필드다(13C-2). 이번
13C-1 준비 단계는 이 필드를 절대 채우지 않는다 — `UNLABELED`/빈 값으로
둔다. `docs/specs/pattern_a_fast_lifecycle_contract.md` §21의 Skipped
Trigger(`NOT_OBSERVED`) 개념을 그대로 승계한다.

--------------------------------------------------------------------------------
13. Lead Time Rules
--------------------------------------------------------------------------------
`lead_weeks_to_pattern_a_transition`/`lead_weeks_to_pattern_a_early_trend`는
`trigger_event_observed == YES`일 때만 계산 가능한 Human 파생 필드다(§30).
13C-1은 `trigger_event_observed`를 채우지 않으므로 두 컬럼 모두
`NOT_EVALUATED`로 고정했다 — `pattern_a_transition_first_after_reference`
날짜를 가져와 미리 대입하는 실수를 하지 않았다(그렇게 하면 Trigger Date
Backfill과 동일한 위반이 된다, §31).

--------------------------------------------------------------------------------
14. Data Quality
--------------------------------------------------------------------------------
* 60건 전부 `data_status == OK`이고 `monthly_history_status == OK`(≥36
  completed monthly bars).
* `build_row` 단계에서 개별적으로 skip/기록된 후보 총 **3건** —
  `NO_PRE_EPISODE_BASE`(Cohort A, 12주 버퍼를 만족하는 BASE 없음) 2건,
  `MAX_EPISODES_PER_TICKER` 1건. `MONTHLY_HISTORY_INSUFFICIENT`로 인한
  build_row 단계 skip은 이번엔 0건이다 — HISTORICAL_COVERAGE stratum이
  eligibility 계산 시점에 이미 36개월 게이트를 먼저 적용하도록 고쳤기
  때문(§4 구현 메모). `selection_manifest.json`의 `excluded_candidates`에
  ticker/candidate_reference_date/reason/cohort로 machine-readable하게
  전부 기록했다(§7 재현성 요구사항, §15 참고).
* 이 3건과 별개로, `RECENT_SYSTEMATIC`은 버킷당 상위 N개만 뽑는 top-N
  방식이라 순위에서 밀린 후보는 `excluded_candidates`에 개별 기록되지
  않는다(수가 수천 건이라 비현실적) — 예: `AMBIGUOUS_STRUCTURE` 버킷은
  10,803개 후보 중 6개만 선택됐다. 이 top-N 재현성은
  `selection_stats_per_bucket`(§4, §15)의 `candidate_pool_size`/
  `score_cutoff_min`/`score_cutoff_max`로 보강했다. `HISTORICAL_COVERAGE`
  는 top-N이 아니라 stable hash 선택이므로 대신 `eligible_pool_size`를
  `selection_stats_per_date`(§4, §15)에 기록했다.
* Network request 0 — `ParquetCache`만 사용, `MarketDataRepository`/
  `PyKrxDataProvider`는 쓰지 않았다(네트워크 fallback 경로를 원천적으로
  배제).

--------------------------------------------------------------------------------
15. Sample Manifest
--------------------------------------------------------------------------------
`artifacts/pattern_a_fast/ground_truth/selection_manifest.json` — base
commit, as_of, source datasets, cohort별 selection strategy(위 §4의 표와
동일 내용을 기계가 읽을 수 있는 형태로 `selection_strategy.cohort_a` /
`cohort_b_recent_systematic` / `cohort_b_historical_coverage` 세 블록),
Monthly History Gate 기준(§6), **포함된 sample_id 전체 목록
(`included_sample_ids`)**, **build_row 단계에서 개별 skip된 후보 목록
(`excluded_candidates` — ticker, candidate_reference_date, reason,
cohort)**, **RECENT_SYSTEMATIC 버킷별 top-N 선정 통계
(`selection_strategy.cohort_b_recent_systematic.
selection_stats_per_bucket` — candidate_pool_size, picked,
score_cutoff_min/max, §4·§14 참고)**, **HISTORICAL_COVERAGE 날짜별
선정 통계(`selection_strategy.cohort_b_historical_coverage.
selection_stats_per_date` — eligible_pool_size, picked,
selection_method, §4·§14 참고)**, network requests=0을 기록. 이전
버전은 제외 사유를 generic 문자열 하나로만 남겼는데, correction을
거치며 위와 같이 machine-readable 목록 + 두 stratum별 선정 통계로
보강했다(§7).

`artifacts/pattern_a_fast/ground_truth/reserved_calibration_samples.json`
— 이번 60건의 `ticker`+`reference_date` 전체 목록. Phase 13I OOS Validation
에서 동일 sample을 재사용하지 않기 위한 예약 목록(§51).

--------------------------------------------------------------------------------
16. Preparation Gates
--------------------------------------------------------------------------------
| Gate | 내용 | 결과 |
|---|---|---|
| 1 | 13A/13B authoritative contracts unchanged | PASS |
| 2 | Pattern A Frozen identity unchanged | PASS |
| 3 | Dataset rows are ticker+reference_date unique | PASS (0 dup) |
| 4 | Completed weekly reference dates only | PASS (전부 금요일 라벨) |
| 5 | PIT chart has no future data | PASS (assert 통과, 테스트로 커버) |
| 6 | Outcome chart clearly separated | PASS (reference_date 점선 표시) |
| 7 | Human labels are not auto generated | PASS (전부 UNLABELED) |
| 8 | Pattern A is benchmark only | PASS |
| 9 | Network requests = 0 | PASS |
| 10 | Sample selection manifest reproducible | PASS (`selection_manifest.json`) |
| 11 | Positive only sampling avoided | PASS (6개 non-positive 버킷 포함) |
| 12 | Source dataset and Human Worksheet separated | PASS (두 개 CSV로 분리) |
| 13 | Monthly Review Data Sufficiency Gate (≥36 completed monthly bars) | PASS (최소 37, 전 샘플 통과) |
| 14 | Orphan/Missing charts = 0 (idempotent 재생성, §8) | PASS (240 files, orphan 0, missing 0, machine-check) |
| 15 | Historical selection은 forward return 크기와 무관 (§3·§10) | PASS (stable hash, targeted test로 커버) |
| 16 | 60건이 최소 2~3개 연도 이상에 분산 (§2) | PASS (7개 연도: 2018/2020/2022/2023/2024/2025/2026) |

ALL PASS — HOLD 아님.

--------------------------------------------------------------------------------
17. Human Review Pending Status
--------------------------------------------------------------------------------
이번 commit은 **13C-1 Dataset Preparation = READY_FOR_HUMAN_REVIEW** 까지만
완료한다. `pattern_a_fast_human_review_v01.csv`의 Human 필드는 전부
blank/UNLABELED다. 사용자가 실제 chart packet(`charts/`)을 검토해 Human
Annotation을 완료하고 dataset을 Freeze한 뒤에야 **Phase 13C = CLOSED**로
처리한다.

--------------------------------------------------------------------------------
18. Non Goals
--------------------------------------------------------------------------------
이번 단계에서 만들지 않은 것: Feature 공식, 숫자 Threshold, Fast Score,
Stage Classifier 구현, `weekly_stage_at_reference`/`human_label` 값,
Production Scanner 연결.

--------------------------------------------------------------------------------
19. Next Step
--------------------------------------------------------------------------------
1. **Phase 13C-2 Human Chart Annotation**: 사용자가
   `pattern_a_fast_human_review_v01.csv`와 `charts/`를 이용해
   `weekly_stage_at_reference`, `trigger_event_observed`,
   `trigger_event_date`, `human_label`, `human_confidence`,
   `human_notes`를 확정.
2. Annotation 완료 후 Ground Truth Dataset Freeze → Phase 13C CLOSED.
3. 그 다음 Phase 13D(Monthly Regime Research), 13E(Weekly Trigger Feature
   Research)로 진행 — 아직 Pattern A Fast가 어떤 MA를 쓸지조차 정하지
   않은 단계이며, 지금은 "우리가 잡고 싶은 차트가 정확히 어떤 모습인가"를
   실제 사례로 고정하는 단계임을 유지한다.
