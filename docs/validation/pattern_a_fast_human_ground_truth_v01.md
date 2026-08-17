# Pattern A Fast Human Ground Truth Dataset v0.1

================================================================================
0. 문서 상태
================================================================================
Phase: 13C-1 — Ground Truth Dataset Preparation
Status: **READY_FOR_HUMAN_REVIEW** (13C-1 완료, Human Annotation은 13C-2로 대기)
Base: `e8cf7e6ee9585e8cc512e6cbe488eaa000497518` (Cohort A 선정 로직은 advisor
review에서 lead time이 구조적으로 ~1주로 눌리는 결함이 발견되어 같은
Phase 13C-1 작업 중 수정 — §4 참고)
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
* 고유 티커: **56개**
* 시장: KOSPI 33 / KOSDAQ 27
* reference_date 연도 분포: 2018(1) / 2020(1) / 2022(9) / 2023(10) /
  2024(10) / 2025(25) / 2026(4)
* 티커당 최대 episode: 2 (§48 준수, 실제 최대 2)

**정직한 한계**: 2025년 비중(25/60 ≈ 42%)이 상대적으로 높다. Cohort A(현재
CANDIDATE 티커의 과거 BASE 시점 역추적)가 구조상 최근 2년에 몰리기 때문이다
(2026-08-14 시점 CANDIDATE는 대부분 최근에 전환했다). 2018/2020은 1건씩으로
얇다. 다만 Cohort B가 2018~2025 quarter-end grid로 별도 확보되어 있어
강세장/약세장/횡보장 국면 자체는 최소 1건 이상씩 포함된다(§50 참고). §47의
"정확히 60을 억지로 채우지 않는다"는 총량 기준이고, 연도 분포까지 완벽히
고르게 만드는 것은 이번 13C-1 범위 밖으로 판단했다 — 필요하면 13C-2 리뷰
과정에서 사용자가 특정 연도 보강을 요청할 수 있다.

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
(180개 중 16번째 시도 `003300` 1건만 skip, 15개 목표 그대로 달성).

**왜 12주 버퍼가 필요했는가(회귀 기록)**: 최초 구현은 "cutoff에서 가장
가까운 BASE"를 그대로 `reference_date`로 썼는데, 이는 구조상 entry_boundary
바로 한 주 전이 되어(다음 주 바로 TRANSITION 시작) 관측 가능한 lead time이
거의 항상 1주로 눌렸다 — Cohort A가 원래 보여주려는 "Fast가 Pattern A보다
몇 주 먼저 보이는가"(13A §26 개념 예시)를 이 cohort 자체가 보여줄 수 없는
상태였다. 같은 원인으로 `013700`/`031510` 같은 최근 티커는 outcome 리뷰
창(52주 목표)이 1~2주로 잘려 사람이 Outcome 차트로 `human_label`을 매길
수조차 없었다. 12주 버퍼 도입 후 outcome 리뷰 창 최솟값은 16주로 늘었다.
`find_base_reference_before_entry`에 이 배경과 함께 기록해 두었다.

**Cohort B — Independent Negative / Ambiguous** (45건):
`cache_present` 티커를 stride 8로 표집(약 316개) 후 quarter-end 날짜 그리드
13개(2016~2025, 강세/약세/횡보 국면 분산)에서 단순 가격 기반 sampling 지표
(`weekly_return_screen`)를 계산하고, 고정 규칙(`classify_source_reason`,
`src/trend_scanner/validation/pattern_a_fast_ground_truth.py`)으로 버킷팅한
뒤 버킷별 상위 N개를 선택했다:

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

일부 샘플(29/60)은 `pattern_a_stage_at_reference`가 비어 있다 — 해당
historical 시점에 Pattern A Score/Stage 계산에 필요한 최소 이력(예:
36개월 완료 월봉)이 부족했기 때문이며(Pattern A 자체의 데이터 요구조건,
§121 Phase 5 참고), 결측을 임의로 채우지 않고 그대로 비워 두었다. Fast
Ground Truth 샘플 자체(source_reason, PIT 차트)는 이 결측과 무관하게
유효하다.

**`pattern_a_transition_first_after_reference`/`_early_trend_first_...`
읽는 법 — "최초 접촉"이지 "안정적으로 정착한 시점"이 아니다.** 이 두
컬럼은 `first_stage_dates_after`가 reference_date 이후 처음으로 Pattern A
가 해당 Stage에 "닿은" 완료 주봉을 반환한 값이다. Pattern A Stage도
비단조(non-monotonic)이므로, 짧게 TRANSITION을 스쳤다가 다시 BASE로
돌아간 뒤 한참 후에야 진짜로 정착하는 경우가 실제로 있다 — 예:
`001210`(금호전기)은 `reference_date=2025-03-14`, entry_boundary(Cohort A
선정에 쓴, 2026-08-14까지 유지된 "현재" episode의 시작점)는
`2026-07-24`(71주 뒤)인데, `pattern_a_transition_first_after_reference`
는 `2025-05-02`(7주 뒤)로 훨씬 이르다 — 그 사이에 짧은 TRANSITION 되돌림이
있었다는 뜻이다. 따라서 이 컬럼만으로 "Pattern A 대비 Fast 리드타임"을
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
* 60건 전부 `data_status == OK`.
* Cache miss/데이터 부족으로 제외된 후보는 dataset에 포함하지 않고 로그로만
  남겼다(재현하려면 `scripts/prepare_pattern_a_fast_ground_truth.py`를
  다시 실행하면 동일 로그를 볼 수 있다).
* Network request 0 — `ParquetCache`만 사용, `MarketDataRepository`/
  `PyKrxDataProvider`는 쓰지 않았다(네트워크 fallback 경로를 원천적으로
  배제).

--------------------------------------------------------------------------------
15. Sample Manifest
--------------------------------------------------------------------------------
`artifacts/pattern_a_fast/ground_truth/selection_manifest.json` — base
commit, as_of, source datasets, cohort별 selection strategy(위 §4의 표와
동일 내용을 기계가 읽을 수 있는 형태로), included/excluded 사유, network
requests=0을 기록.

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
