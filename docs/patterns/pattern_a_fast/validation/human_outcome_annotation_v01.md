# Pattern A Fast Human Outcome Annotation v0.1

================================================================================
0. 문서 상태
================================================================================
Phase: 13C-2 — Human Annotation
Status: **HUMAN OUTCOME ANNOTATION COMPLETE / ADVISOR REVIEW PENDING**
(이 commit만으로 Phase 13C-2를 CLOSED로 선언하지 않는다 — 사용자가
advisor 리뷰에서 실제 GitHub diff를 검토해 PASS된 뒤에 최종 봉인한다,
§19)
Base PIT checkpoint commit: `9263fcf3c61a126530406edd77fc8f538bb719e3`
Data cutoff (as_of): 2026-08-14
Network requests: 0

--------------------------------------------------------------------------------
1. Purpose
--------------------------------------------------------------------------------
Phase 13C-2 PIT Checkpoint(`9263fcf`)에서 미래 가격을 보기 전에 봉인한
첫 40개 Human PIT 판단에 대해, 사용자가 이후 주봉 Outcome을 직접 확인해
부여한 Human Outcome Label(`human_label`)을 기록한다. 핵심 원칙:
**PIT 판단은 절대 수정하지 않고, `human_label`만 추가**해 "당시 판단"과
"이후 실제 결과"를 분리해서 보존한다.

--------------------------------------------------------------------------------
2. Total Dataset / Scope
--------------------------------------------------------------------------------
* Total Dataset: 60
* Human Calibration Scope: 40 (사용자가 첫 40개로 범위를 스스로 축소)
* PIT Annotated: 40
* Outcome Annotated: 40
* Remaining UNLABELED: 20 (41~60번째 sample, Human Annotation 모든 필드
  기존 그대로 — 개발 AI가 자동으로 채우거나 예측하지 않음)
* PIT Hindsight Mutation: **NO** — Base PIT checkpoint commit(`9263fcf`)
  대비 `weekly_stage_at_reference`/`trigger_event_observed`/
  `trigger_event_date`/`human_confidence`/`human_notes` 5개 필드가 60건
  전부 field-level identical(§13 참고).

--------------------------------------------------------------------------------
3. Outcome Review Scope
--------------------------------------------------------------------------------
* Outcome Timeframe: **WEEKLY**
* Outcome Window: `reference_date` ~ `outcome_review_end`
  (`outcome_review_end = min(reference_date + 52주, 캐시 마지막 날짜)`,
  13C-1 계약 그대로 유지)
* 공식 Outcome 범위 밖의 가격 움직임은 label 근거로 사용하지 않는다.
  사용자가 대화 중 범위 밖 추가 움직임을 언급한 경우에도(예: 삼성화재
  `000810_20180629`), 이미 확정된 label을 그대로 기록했다.

--------------------------------------------------------------------------------
4. Human Label Distribution
--------------------------------------------------------------------------------
| Label | 건수 |
|---|---|
| GOOD_TRIGGER | 9 |
| BORDERLINE_TRIGGER | 6 |
| FALSE_TRIGGER | 4 |
| TOO_EARLY | 8 |
| TOO_LATE | 1 |
| TOO_EXTENDED | 3 |
| NO_SETUP | 9 |
| **Outcome Annotated 합계** | **40** |
| UNLABELED | 20 |
| **Total** | **60** |

**이 40개는 prevalence estimation dataset이 아니다.** 13C-1 sampling
자체가 Pattern A context(Cohort A) + systematic negative/ambiguous
cases(Cohort B)를 의도적으로 섞은 calibration research set이므로,
GOOD_TRIGGER 9/40이나 FALSE_TRIGGER 4/40 같은 비율을 시장 전체 성공률로
해석하지 않는다. 목적은 Human Definition 정제, Feature 후보 발견,
GOOD/BORDERLINE/FALSE/EARLY/LATE 차이 분석이다.

--------------------------------------------------------------------------------
5. Explicit Trigger Event
--------------------------------------------------------------------------------
`001540_20260213`(안국약품)만 이번 40개 중 `reference_date` 자체를
명확한 실제 진입 시점으로 판단한 유일한 sample이다:
`weekly_stage_at_reference=TRIGGER`, `trigger_event_observed=YES`,
`trigger_event_date=2026-02-13`, `human_label=GOOD_TRIGGER`. 핵심
Positive Anchor Sample — 지지 → 고점 돌파 → 돌파 후 지지 → higher low →
재돌파의 전형적인 Healthy Progression을 보였다.

`012450_20230630`(한화에어로스페이스)은 `human_label=GOOD_TRIGGER`이나
`trigger_event_observed`는 여전히 `UNLABELED`, `trigger_event_date`는
blank다 — 사용자가 "6월 12일이나 19일쯤이면 더 좋았겠지만 이때도
좋다"고 언급했지만 정확한 completed weekly TRIGGER 날짜를 직접 확정한
것이 아니므로, Outcome이 좋다고 해서 과거 Trigger date를 소급 backfill
하지 않았다.

--------------------------------------------------------------------------------
6. Outcome Label Semantics (참고 — Phase 13B 계약 확장 아님)
--------------------------------------------------------------------------------
이번 Human Label은 단순 forward return label이 아니다. 가격이 크게
올랐다고 자동 GOOD_TRIGGER가 아니고, 가격이 이후 더 올랐다고 EXTENDED
판단이 틀린 것도 아니다 — 구조적 주봉 Outcome(지지/저항 돌파/higher
low/지지 실패 등)을 기준으로 사용자가 직접 판단한 Human Ground Truth다.
7개 라벨(GOOD_TRIGGER/BORDERLINE_TRIGGER/FALSE_TRIGGER/TOO_EARLY/
TOO_LATE/TOO_EXTENDED/NO_SETUP)의 정의는
`docs/patterns/pattern_a_fast/spec/definition_v01.md`(Phase 13A, CLOSED)의 Ground
Truth Label Vocabulary를 그대로 따른다.

--------------------------------------------------------------------------------
7. Outcome Review Evidence (40개 요약)
--------------------------------------------------------------------------------
사용자가 Outcome 검토 시 남긴 근거를 보존한다. **worksheet의
`human_notes`는 PIT Checkpoint 당시 기록이므로 여기 Outcome 근거를
덧붙이거나 overwrite하지 않았다** — 이 별도 문서에만 기록한다.

| # | sample_id | 종목명 | PIT Stage | Outcome Label | 근거 요약 |
|---|---|---|---|---|---|
| 01 | 000050_20251024 | 경방 | WATCH | TOO_EARLY | 소폭 상승 후 급등/급락 반복. reference_date 자체는 좋은 Trigger로 보기 이름. |
| 02 | 000250_20251226 | 삼천당제약 | EXTENDED | TOO_EXTENDED | 추가 5배 이상 급등 후 급락. reference_date는 이미 과도하게 진행된 위치. |
| 03 | 000370_20250509 | 한화손해보험 | SETUP | BORDERLINE_TRIGGER | 상승/눌림 반복, 중간 저점 이탈도 발생 — 완벽한 성공 사례는 아님. |
| 04 | 000650_20250926 | 천일고속 | WATCH | TOO_EARLY | 이후 초대형 상승, 그러나 reference 시점은 하락/지지 미확인. |
| 05 | 000650_20251226 | 천일고속 | EXTENDED | TOO_EXTENDED | 이미 급등한 상태, 이후 급락. |
| 06 | 000700_20260109 | 유수홀딩스 | SETUP | BORDERLINE_TRIGGER | 저점 이탈 후 반등. 강하고 지속적인 구조는 부족. |
| 07 | 000810_20180629 | 삼성화재 | SETUP | TOO_EARLY | 공식 Outcome 범위 내 횡보/소폭 상승 후 하락. 범위 밖 가격은 근거로 미사용. |
| 08 | 000850_20250919 | 화천기공 | WATCH | TOO_EARLY | 방향성 없이 움직이다 뒤늦게 급등 — reference가 앞선 시점. |
| 09 | 001210_20250314 | 금호전기 | WATCH | NO_SETUP | 오르락내리락 반복, 저점 상승 구조 불명확. |
| 10 | 001260_20250926 | 남광토건 | WATCH | NO_SETUP | 혼란스러운 구조, 유효한 higher-low/breakout progression 없음. |
| 11 | 001450_20260116 | 현대해상 | SETUP | GOOD_TRIGGER | 급등 후 눌림에서도 higher-low 반복하며 안정적 상승 구조로 발전. |
| 12 | 001540_20260213 | 안국약품 | TRIGGER | GOOD_TRIGGER | 핵심 Positive Anchor — 고점 돌파 후 상승/눌림 반복, 재돌파(§5). |
| 13 | 001570_20240927 | 금양 | WATCH | NO_SETUP | 하락 지속, 상승 전환 구조 형성 실패. |
| 14 | 001800_20250321 | 오리온홀딩스 | SETUP | GOOD_TRIGGER | 꾸준한 상승, higher-low 반복하며 추세 지속. |
| 15 | 002070_20260327 | 비비안 | WATCH | NO_SETUP | 지속 하락, 저점도 낮아짐. 말미 반등만으로 Setup 불인정. |
| 16 | 002170_20250321 | SYTS | WATCH | TOO_EARLY | higher-low 만들며 장기간 양호한 상승 — 그러나 reference는 이른 위치. |
| 17 | 002460_20250509 | HS화성 | WATCH | BORDERLINE_TRIGGER | 저점 상승 구조 양호하나 주요 이전 고점 돌파 부족. |
| 18 | 003060_20260327 | 에이프로젠바이오로직스 | WATCH | NO_SETUP | reference 당시 역배열+장기하락+바닥미확인. 이후 대급등은 소급 근거 아님(중요 negative structural sample). |
| 19 | 003100_20250822 | 선광 | WATCH | FALSE_TRIGGER | 고점 돌파까지 발생했으나 돌파 후 지지 실패, 기준일 수준으로 회귀. |
| 20 | 003120_20260327 | 일성아이에스 | WATCH | NO_SETUP | 지지 실패 후 하락, 말미 단기 반등만 존재. |
| 21 | 003480_20250207 | 한진중공업홀딩스 | WATCH | BORDERLINE_TRIGGER | 고점 돌파 후 higher-low, 다만 지속적 저점 상승 구조는 약함. |
| 22 | 003490_20250905 | 대한항공 | SETUP | GOOD_TRIGGER | 저점을 꾸준히 높이는 건강한 structure progression. |
| 23 | 006260_20200925 | LS | WATCH | BORDERLINE_TRIGGER | 점진적 상승/저점 유지 상당 기간, Outcome 후반 저점 이탈. |
| 24 | 006260_20221223 | LS | SETUP | GOOD_TRIGGER | 지지→고점 돌파→돌파 후 지지→재돌파, 조정에서도 이전 저항이 지지선 역할. |
| 25 | 008490_20250328 | 서흥 | WATCH | FALSE_TRIGGER | 쌍바닥+돌파+지지까지 좋았으나 추가 돌파 후 지지 실패, 저점 이탈. |
| 26 | 009150_20260327 | 삼성전기 | EXTENDED | TOO_EXTENDED | 추가 상승 지속됐으나 reference 시점부터 진입 구간 상당 지남, 이후 큰 drawdown. |
| 27 | 009470_20250627 | 삼화전기 | WATCH | FALSE_TRIGGER | 여러 번 돌파 시도, 저점도 소폭 상승했으나 마지막 돌파 후 지지 실패, 기준일 아래로 하락. |
| 28 | 009730_20260327 | 이렘 | WATCH | NO_SETUP | 계속 하락, 하한가 발생. 반등해도 유효한 전환 구조 없음. |
| 29 | 009830_20250328 | 한화솔루션 | WATCH | BORDERLINE_TRIGGER | 지지→돌파 후 저점 낮아지며 구조 훼손, 나중에 재지지/재돌파로 완전 실패는 아님. |
| 30 | 011070_20200925 | LG이노텍 | SETUP | GOOD_TRIGGER | 지지→돌파→higher-low→재돌파→재지지의 전형적 Healthy Progression. |
| 31 | 011200_20221223 | HMM | WATCH | TOO_EARLY | 장기간 저점 낮추며 추가 하락, 훨씬 뒤에서야 지지/상승 — 명확히 너무 이름. |
| 32 | 011210_20180629 | 현대위아 | WATCH | TOO_EARLY | 초기 반등 후 저점 완전 이탈/추가 하락, 좋은 구조는 훨씬 뒤에 발생. |
| 33 | 011330_20260327 | 유니켐 | WATCH | NO_SETUP | 저점 깨며 추가 하락, Outcome 후반에야 바닥 지지/반등 시도. |
| 34 | 012170_20250328 | 아센디오 | WATCH | NO_SETUP | 지지 형성 실패, 저점 계속 낮아지며 하락. |
| 35 | 012450_20230630 | 한화에어로스페이스 | TREND | GOOD_TRIGGER | 하락 후 지지→고점 돌파→돌파 영역 유지→재돌파→higher-low. 강한 Positive Trend Sample(§5). |
| 36 | 032580_20260327 | 피델릭스 | WATCH | TOO_EARLY | 점진적 구조 형성 후 큰 급등, 그러나 reference 당시 역배열/바닥 미확인. |
| 37 | 032820_20251226 | 우리기술 | SETUP | GOOD_TRIGGER | 지지하며 상승, 이후 매우 강한 추세로 발전(§9-C paired example). |
| 38 | 032820_20260327 | 우리기술 | TREND | TOO_LATE | reference가 사실상 최고점 부근, 이후 대규모 하락(§9-C paired example). |
| 39 | 034220_20200925 | LG디스플레이 | WATCH | FALSE_TRIGGER | 강한 저항대 돌파 시도했으나 지지 전환 실패, 이후 지속 하락. |
| 40 | 036170_20251226 | 에이치엠넥스 | SETUP | GOOD_TRIGGER | 급등→지지→재급등의 강한 상승 추세. Penny stock observation은 label에 영향 없음(§8). |

--------------------------------------------------------------------------------
8. Penny Stock / Investability Observation
--------------------------------------------------------------------------------
`036170`(에이치엠넥스) 사례에서 새로운 사용자 선호가 관찰됐다: 저가
동전주는 Pattern A Fast의 실질적 매매/관심 Universe에서 제외하고
싶다는 의견. **이번 Phase에서는 이를 구현하지 않는다** — Phase 10
Investability Contract 수정, 최저 주가 hard filter 추가, 임의의
가격 threshold 생성, Pattern A Fast feature로 가격 필터 추가, 에이치엠넥스
label 변경 전부 하지 않았다. 차트 구조 성공 여부와 실제 투자 가능
Universe 여부는 독립된 축이라는 원칙에 따라 `human_label=GOOD_TRIGGER`
를 그대로 유지했다.

> User investability observation: very-low-price / penny-stock names may
> be outside the intended real trading universe. This is independent
> from structural Fast outcome quality. No price threshold is frozen in
> Phase 13C-2.

가격 threshold와 실제 Universe policy는 추후 별도 Research/Investability
결정에서 다룬다.

--------------------------------------------------------------------------------
9. Important Paired Examples (Feature Research 참고용)
--------------------------------------------------------------------------------
**A. 천일고속** — `000650_20250926`(WATCH → TOO_EARLY) vs
`000650_20251226`(EXTENDED → TOO_EXTENDED): 같은 종목에서도 시간에 따라
"너무 이름 → 너무 늦음"으로 빠르게 이동할 수 있음을 보여준다.

**B. LS** — `006260_20200925`(WATCH → BORDERLINE_TRIGGER) vs
`006260_20221223`(SETUP → GOOD_TRIGGER): 같은 종목이라도 구조 완성도의
차이가 Outcome 품질 차이로 연결된다.

**C. 우리기술** — `032820_20251226`(SETUP → GOOD_TRIGGER) vs
`032820_20260327`(TREND → TOO_LATE): Pattern A Fast가 원하는 핵심 Entry
Window를 연구하기에 매우 중요한 pair — "좋은 종목을 찾는 것"과 "좋은
시점을 찾는 것"이 다르다는 것을 보여주는 대표 사례.

--------------------------------------------------------------------------------
10. No Premature Feature Engineering
--------------------------------------------------------------------------------
이번 Outcome 결과에서 눈에 띈 특징(higher low, previous high breakout,
breakout support, 200-week MA resistance, inverse MA alignment, bottom
confirmation, support confirmation 등)을 이번 commit에서 코드로 구현하지
않았다. 이번 commit은 Human Ground Truth Finalization이며, Feature
연구는 다음 Phase에서 이 40개를 근거로 별도 진행한다.

--------------------------------------------------------------------------------
11. Immutable PIT Validation
--------------------------------------------------------------------------------
Base PIT checkpoint commit `9263fcf`의 worksheet와 현재 worksheet를
직접 비교해, 60건 전부에서 `weekly_stage_at_reference` /
`trigger_event_observed` / `trigger_event_date` / `human_confidence` /
`human_notes` 5개 필드가 field-level identical함을 확인했다(Python
`Series.equals` 비교, 예외 0건). 변경이 허용된 필드는 `human_label`
하나뿐이며, 실제로 다른 컬럼은 전혀 수정하지 않았다.

--------------------------------------------------------------------------------
12. Frozen 13C-1 Dataset / Phase 10 / Phase 12 — 변경 없음 확인
--------------------------------------------------------------------------------
다음은 이번 commit에서 전혀 수정되지 않았다(git diff로 확인 완료):
`pattern_a_fast_ground_truth_source_v01.csv` sample 구성 /
`selection_manifest.json` / `reserved_calibration_samples.json` /
`charts/` / `scripts/prepare_pattern_a_fast_ground_truth.py` /
`scripts/generate_pattern_a_fast_ground_truth_charts.py` /
`src/trend_scanner/validation/pattern_a_fast_ground_truth.py` / Pattern A
production code(`src/trend_scanner/patterns/`) / Phase 10 Investability
logic(`src/trend_scanner/filters/investability.py`) / Phase
12(`ROADMAP.md`). Pattern A Fast Feature/Threshold/Score/Classifier
코드도 추가하지 않았다.

--------------------------------------------------------------------------------
13. Next Step
--------------------------------------------------------------------------------
이 commit까지는 Phase 13C-2를 자동으로 CLOSED로 선언하지 않는다.
Status는 **HUMAN OUTCOME ANNOTATION COMPLETE / ADVISOR REVIEW PENDING**
으로 둔다. 사용자가 commit 결과를 advisor에게 전달하고 실제 GitHub diff
리뷰에서 PASS된 뒤에 **Phase 13C-2 40-SAMPLE HUMAN CALIBRATION SET
CLOSED/FROZEN**으로 최종 봉인한다.
