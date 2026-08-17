# Pattern A Fast Human PIT Annotation Checkpoint v0.1

================================================================================
0. 문서 상태
================================================================================
Phase: 13C-2 — Human Annotation
Status: **PIT CHECKPOINT / OUTCOME REVIEW PENDING**
Base commit: `d121cdf76f72f5b457652fb3f07c04a14e743d52` (Phase 13C-1 최종
봉인 시점)
Data cutoff (as_of): 2026-08-14
Network requests: 0

--------------------------------------------------------------------------------
1. Purpose
--------------------------------------------------------------------------------
Phase 13C-1에서 최종 봉인된 60개 Human Ground Truth Sample 중, 사용자가
직접 PIT(reference_date 시점까지의) 차트만 보고 판단한 첫 40개
Weekly Lifecycle Stage 판단을 **Outcome을 보기 전에** repository에
immutable checkpoint로 고정한다. 목적은 hindsight contamination 방지 —
나중에 Outcome 차트를 본 뒤 이 PIT 판단이 사후적으로 수정되는 일이
없도록, 이 시점의 판단을 먼저 별도로 못 박아 둔다.

**이번 commit은 Outcome Annotation이 아니다.** `human_label`
(`GOOD_TRIGGER`/`BORDERLINE_TRIGGER`/`FALSE_TRIGGER`/`TOO_EARLY`/
`TOO_LATE`/`TOO_EXTENDED`/`NO_SETUP`)은 60건 전부 `UNLABELED`로 남아
있다.

--------------------------------------------------------------------------------
2. Annotation Sample Count
--------------------------------------------------------------------------------
* Total Dataset Samples: 60
* PIT Annotated (weekly_stage_at_reference 채움): **40**
* Remaining UNLABELED: **20**

나머지 20개는 사용자가 이번 라운드에서 검토하지 않기로 결정한 샘플이며,
`weekly_stage_at_reference`/`trigger_event_observed`/`human_label` =
`UNLABELED`, `trigger_event_date`/`human_confidence`/`human_notes` =
blank 그대로 유지된다.

--------------------------------------------------------------------------------
3. Stage Distribution
--------------------------------------------------------------------------------
| Stage | 건수 |
|---|---|
| WATCH | 24 |
| SETUP | 10 |
| TRIGGER | 1 |
| TREND | 2 |
| EXTENDED | 3 |
| **Annotated 합계** | **40** |
| UNLABELED | 20 |
| **Total** | **60** |

이 분포는 사용자가 40개 각각에 입력한 값을 그대로 반영한 결과이지,
목표 분포를 맞추기 위해 조정한 값이 아니다.

--------------------------------------------------------------------------------
4. Trigger Event
--------------------------------------------------------------------------------
이번 40개 중 사용자가 `reference_date` 자체를 명확한 실제 진입 시점으로
판단한 sample은 **1건뿐**이다:

* `001540_20260213` (안국약품) — `trigger_event_observed = YES`,
  `trigger_event_date = 2026-02-13`.

나머지 39개는 `trigger_event_observed = UNLABELED`, `trigger_event_date`
= blank로 유지했다. 특히 `012450_20230630`(한화에어로스페이스)은
사용자가 "6월 12일이나 19일쯤이면 더 좋았겠지만 이때도 좋다"고
언급했지만, 정확한 completed weekly TRIGGER 날짜를 직접 확정한 것이
아니므로 `weekly_stage_at_reference = TREND`만 기록하고 trigger date를
추정/backfill하지 않았다(Trigger Date Backfill 금지 원칙).

--------------------------------------------------------------------------------
5. Human Labels
--------------------------------------------------------------------------------
`human_label` = `UNLABELED` — **60건 전부**. Outcome chart는 이번
checkpoint에서 전혀 열람하지 않았고, Pattern A 이후 움직임을 근거로
Stage를 수정하지도 않았다. 이번 40개 Stage는 오직 `reference_date`
까지의 PIT 차트만 보고 판단한 값이다.

--------------------------------------------------------------------------------
6. Outcome Reviewed / Hindsight Mutation
--------------------------------------------------------------------------------
* Outcome Reviewed: **NO**
* Hindsight Mutation: **금지, 발생하지 않음** — 이 문서와 worksheet는
  PIT 판단만 담고 있으며, Outcome Annotation(Phase 13C-2 다음 단계)
  이전까지는 이 40개 Stage 값을 Outcome을 근거로 재작성하지 않는다.

--------------------------------------------------------------------------------
7. Human Pattern Notes (연구용 관찰, Freeze 아님)
--------------------------------------------------------------------------------
아래는 40개 PIT 판단 과정에서 사용자가 반복적으로 언급한 경향을 요약한
것이다. **이 관찰은 향후 Feature 후보를 위한 Human Observation일 뿐,
아직 Pattern A Fast Rule/Feature/Threshold로 Freeze하지 않는다.**
"주봉 200 이평 위/아래", "직전 고점 돌파" 같은 표현도 지금은 사람의
정성적 관찰이지 수치 Threshold가 아니다. Phase 13D 이후 연구 대상이다.

**A. 강한 배제 조건(대부분 WATCH)**
- 역배열 + 장기 하락
- 바닥 미확인 / 지지 미확인
- 현재가 위에 장기 이평선이 다수 존재(특히 주봉 200 이평선)
- 이전 큰 시세 이후 하락만 하고 단순 횡보 중
- 차트 구조가 지나치게 혼란스러움

**B. SETUP에 가까운 조건**
- 장기 하락이 어느 정도 멈춤, 바닥/지지 구조가 보이기 시작
- 주봉 구조가 정리되기 시작하지만 직전 고점을 아직 돌파하지 않음
- 또는 장기 이평 저항이 아직 남아 있음

**C. TRIGGER에 가까운 조건**
- 바닥/지지 확인 + 구조 정리 + 장기 하락 압력 상당 부분 해소
- 직전 주봉 고점 돌파 또는 그에 준하는 구조적 전환
- 사용자가 "이 시점이면 실제 들어가도 괜찮다"고 판단할 수 있는 위치
- 현재 명확한 대표 사례: `001540_20260213`(안국약품)

**D. TREND**
- 좋은 Trigger가 이미 조금 앞에서 발생했을 가능성이 있고, 현재도 상승
  초기/진행 구간이지만 Trigger 자체보다는 한 단계 진행된 상태
- 대표: `012450_20230630`(한화에어로스페이스), `032820_20260327`(우리기술)

**E. EXTENDED**
- 상승 여부와 무관하게 이미 너무 많이 상승해 신규 Fast 진입 위치로 부적절
- 대표: `000250_20251226`(삼천당제약), `000650_20251226`(천일고속),
  `009150_20260327`(삼성전기)

--------------------------------------------------------------------------------
8. Known Limitation
--------------------------------------------------------------------------------
이번 Human Calibration은 사용자가 **40개에서 중단**하기로 결정했으며,
나머지 20개는 의도적으로 `UNLABELED`로 남아 있다. **이 20개를 개발 AI가
자동으로 보완하거나 예측하지 않는다** — 사용자가 추후 직접 검토하거나,
40개만으로 충분하다고 판단하면 그대로 둘 사안이다.

--------------------------------------------------------------------------------
9. Source Dataset 처리
--------------------------------------------------------------------------------
이번 checkpoint는 `pattern_a_fast_human_review_v01.csv`를 Human
Annotation의 authoritative working artifact로 사용한다.
`pattern_a_fast_ground_truth_source_v01.csv`의 Human 필드는 자동
merge하지 않았다 — Source Dataset은 13C-1 준비 당시 machine/context
artifact 상태를 그대로 유지한다(전부 `UNLABELED`인 상태가 정상).
Outcome Annotation 완료 후 최종 merge/freeze 여부는 별도로 결정한다.

--------------------------------------------------------------------------------
10. Frozen 13C-1 Dataset — 변경 없음 확인
--------------------------------------------------------------------------------
다음은 이번 commit에서 전혀 수정되지 않았다(git diff로 확인 완료):
Sample 60개 구성 / `sample_id` / `reference_date` / `source_cohort` /
`source_reason` / Pattern A Benchmark Context / Monthly History Gate /
`selection_manifest.json` / `reserved_calibration_samples.json` /
`charts/` / sampling script(`scripts/prepare_pattern_a_fast_ground_truth.py`,
`scripts/generate_pattern_a_fast_ground_truth_charts.py`) / ground truth
helper(`src/trend_scanner/validation/pattern_a_fast_ground_truth.py`) /
tests / Pattern A production logic(`src/trend_scanner/patterns/`) /
Phase 12(`docs/roadmap.md`).

--------------------------------------------------------------------------------
11. Next Step
--------------------------------------------------------------------------------
1. 이 checkpoint 커밋이 advisor 리뷰에서 PASS되기 전에는 Outcome
   Annotation을 시작하지 않는다(w.md §14 명시 사항).
2. Outcome Annotation(나머지 40개에 대한 `human_label` 부여, 필요시
   20개 추가 annotation 여부는 사용자 결정)은 별도 Phase 13C-2 후속
   단계로 진행한다.
