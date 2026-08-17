# Pattern A Fast Human Ground Truth Dataset v0.1

================================================================================
0. 문서 상태
================================================================================
Phase: 13C-1 — Ground Truth Dataset Preparation
Status: **READY_FOR_HUMAN_REVIEW** (13C-1 완료, Human Annotation은 13C-2로 대기)
Base: `6ab0c01f9269abbfb650ba1ced70636bcb5546f2` (Cohort A 선정 로직은
advisor 2회 검토에서 연달아 결함이 발견되어 수정됐고(§4), 그 뒤 Monthly
Review Data Sufficiency Gate가 추가되며 Cohort B 후보 상당수가 다시
제외/재선정됨 — §6, §14 참고)
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
* 고유 티커: **58개**
* 시장: KOSPI 39 / KOSDAQ 21
* reference_date 연도 분포: 2018(2) / 2019(1) / 2020(2) / 2021(1) /
  2022(2) / 2023(1) / 2024(1) / 2025(46) / 2026(4)
* Completed monthly bars at reference: 최소 42 / 중앙값 46 / 최대 133
  (전부 Monthly Review Data Sufficiency Gate ≥36 통과, §6·§14 참고)
* 티커당 최대 episode: 2 (§48 준수, 실제 최대 2)

**정직한 한계(연도 분포가 이번 correction으로 더 나빠짐)**: 2025년 비중이
46/60 ≈ 77%로, Monthly History Gate 도입 이전(42%)보다 오히려 심해졌다.
원인을 실측한 결과, quota 최적화 문제가 아니라 **로컬 캐시의 근본적인
이력 커버리지 한계**였다: 2016~2023년 quarter-end 시점에 36개월 이상
이력을 가진 티커가 전체 캐시 2,486개 중 44~66개뿐이었다(대부분 티커의
`cache_first_date`가 최근 3년 이내). Cohort B 티커 screening을 stride
8(약 316개)에서 전수(2,486개)로 넓혀도 이 병목은 거의 해소되지 않았다
(연도 종류는 6개→9개로 늘었지만 2025 비중은 그대로). §8의 지시대로 이
결과를 quota로 맞추려 하지 않고 있는 그대로 기록한다. 필요하면 13C-2
리뷰 이후 로컬 캐시 자체의 장기 이력 백필(별도 Phase) 여부를 사용자가
판단할 수 있다.

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

**Cohort B — Independent Negative / Ambiguous** (45건):
`cache_present` 티커 **전수**(2,486개 — 최초에는 stride 8 표집(약 316개)
이었으나, Monthly History Gate 도입 후 초기 quarter-end 날짜의 생존
후보가 극소수임이 확인되어 존재하는 후보를 stride로 더 줄이지 않도록
전수 screen으로 전환함, §3 참고) × quarter-end 날짜 그리드 13개(2016~2025,
강세/약세/횡보 국면 분산)에서 단순 가격 기반 sampling 지표
(`weekly_return_screen`)를 계산하고, 고정 규칙(`classify_source_reason`,
`src/trend_scanner/validation/pattern_a_fast_ground_truth.py`)으로 버킷팅한
뒤, Monthly History Gate(§6)를 통과하는 후보 중 버킷별 상위 N개를
선택했다:

| source_reason | 목표 | 선택 |
|---|---|---|
| FAILED_BREAKOUT | 10 | 10 |
| LONG_DOWNTREND_BOUNCE | 5 | 5 |
| STRONG_UPTREND_ALREADY_EXTENDED | 8 | 8 |
| NEGATIVE_CONTROL | 8 | 8 |
| RANGE_BOUND | 6 | 6 |
| AMBIGUOUS_STRUCTURE | 8 | 8 |

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
  FAILED_BREAKOUT(10) / LONG_DOWNTREND_BOUNCE(5) / STRONG_UPTREND_ALREADY_
  EXTENDED(8) / NEGATIVE_CONTROL(8) / RANGE_BOUND(6) / AMBIGUOUS_STRUCTURE(8)
  까지 6개 non-positive 버킷 45건 포함.
* 사후 outcome(가격 metrics)을 sampling에 사용한 것은 명시적으로 허용된
  범위이며, `source_cohort`/`source_reason` 컬럼으로 항상 그 사실을 드러낸다
  (§19 Outcome enriched research set임을 숨기지 않는다).
* 이 dataset의 `GOOD_TRIGGER`/`FALSE_TRIGGER` 비율은 production prevalence
  추정치가 아니다.

--------------------------------------------------------------------------------
6. PIT Rules
--------------------------------------------------------------------------------
* `reference_date`는 항상 완료된 W-FRI 주봉 라벨이다(`resolve_completed_
  weekly_reference`가 `build_historical_snapshot(..., include_incomplete_
  periods=False)`의 `weekly_as_of`를 그대로 반환 — 가장 가까운 날짜로
  silent substitution하지 않는다, §35).
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
  제외되고 다음 후보로 top-up된다(§14 참고). 흥미롭게도 이 게이트가
  정확히, 이전 버전에서 `pattern_a_stage_at_reference`가 비어 있던 29/60
  행과 100% 일치했다 — Pattern A Score/Stage 자체도 내부적으로 36개월
  완료 월봉을 요구하기 때문(Phase 5 데이터 계약)이며, 이번 게이트는 그
  결측을 사전에 명시적으로 걸러내는 역할도 겸한다.

--------------------------------------------------------------------------------
7. Source Cohorts
--------------------------------------------------------------------------------
§4 참고. 요약: A=Pattern A 실제 후보의 과거 BASE 지점(15), B=독립
Negative/Ambiguous cohort(45). 두 cohort 모두 `source_cohort` 컬럼으로
dataset에 명시된다.

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

`pattern_a_stage_at_reference`는 60건 전부 채워져 있다(결측 0). 이전
버전에서는 29/60이 비어 있었는데 — 해당 historical 시점에 Pattern A
Score/Stage 계산에 필요한 최소 이력(36개월 완료 월봉, Pattern A 자체의
데이터 요구조건, Phase 5 데이터 계약 참고)이 부족했기 때문이다. 이번
correction에서 도입한 Monthly Review Data Sufficiency Gate(§6)가 동일한
36개월 기준으로 그 결측 케이스를 사전에 걸러내면서, 결과적으로 결측이
전부 사라졌다(의도적으로 결측을 메운 것이 아니라, 애초에 결측이 나올
샘플 자체를 dataset에서 제외했다는 뜻).

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
* 이번 correction에서 제외된 후보 총 206건 — `MONTHLY_HISTORY_INSUFFICIENT`
  203건, `NO_PRE_EPISODE_BASE` 2건, `MAX_EPISODES_PER_TICKER` 1건. 로그
  뿐 아니라 `selection_manifest.json`의 `excluded_candidates`에
  ticker/candidate_reference_date/reason/cohort로 machine-readable하게
  전부 기록했다(§7 재현성 요구사항, §15 참고).
* Network request 0 — `ParquetCache`만 사용, `MarketDataRepository`/
  `PyKrxDataProvider`는 쓰지 않았다(네트워크 fallback 경로를 원천적으로
  배제).

--------------------------------------------------------------------------------
15. Sample Manifest
--------------------------------------------------------------------------------
`artifacts/pattern_a_fast/ground_truth/selection_manifest.json` — base
commit, as_of, source datasets, cohort별 selection strategy(위 §4의 표와
동일 내용을 기계가 읽을 수 있는 형태로), Monthly History Gate 기준(§6),
**포함된 sample_id 전체 목록(`included_sample_ids`)**, **제외된 후보
전체 목록(`excluded_candidates` — ticker, candidate_reference_date,
reason, cohort)**, network requests=0을 기록. 이전 버전은 제외 사유를
generic 문자열 하나로만 남겼는데, 이번 correction에서 위와 같이
machine-readable 목록으로 보강했다(§7).

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
| 13 | Monthly Review Data Sufficiency Gate (≥36 completed monthly bars) | PASS (최소 42, 전 샘플 통과) |

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
