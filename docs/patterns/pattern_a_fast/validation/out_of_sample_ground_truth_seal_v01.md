pattern_a_fast_oos_ground_truth_seal_v01.md
==================================================
Phase 13I-1 Reserved OOS Human Ground Truth Seal
==================================================

상태: READY_FOR_ADVISOR_GROUND_TRUTH_SEAL_REVIEW
Base SHA: 3dbdffcb3277a4bb40fa969f3827075514f13f1e

1. 범위와 경계
RESERVED_OOS_A의 기존 20개 표본에 대해 사람이 PASS A stage blind review와 PASS B outcome review를 완료했다. 표본 identity, review order, reference_date, outcome_review_end, stage/outcome blind chart, blind asset manifest 및 preregistered evaluation protocol은 변경하지 않았다. 이 단계에서는 HIERARCHICAL_V01, Pattern A 또는 다른 OOS evaluator를 실행하지 않았고, 모델 점수·단계·후보 결과를 생성하지 않았다.

2. PASS A Stage Freeze

| OOS ID | 티커 | 종목명 | Stage | Confidence | Trigger observed | Trigger date |
|---|---|---|---|---|---|---|
| OOS_A_001 | 084670 | 동양고속 | EXTENDED | HIGH | NO | |
| OOS_A_002 | 049470 | 비트플래닛 | EXTENDED | HIGH | NO | |
| OOS_A_003 | 068240 | 다원시스 | WATCH | HIGH | NO | |
| OOS_A_004 | 051910 | LG화학 | SETUP | LOW | NO | |
| OOS_A_005 | 054220 | 비츠로시스 | WATCH | LOW | NO | |
| OOS_A_006 | 049800 | 우진플라임 | WATCH | HIGH | NO | |
| OOS_A_007 | 046970 | 우리로 | EXTENDED | HIGH | NO | |
| OOS_A_008 | 065170 | 비엘팜텍 | WATCH | HIGH | NO | |
| OOS_A_009 | 065170 | 비엘팜텍 | WATCH | HIGH | NO | |
| OOS_A_010 | 043260 | 성호전자 | TREND | HIGH | YES | 2025-11-24 |
| OOS_A_011 | 078930 | GS | WATCH | HIGH | NO | |
| OOS_A_012 | 043220 | 티에스넥스젠 | WATCH | HIGH | NO | |
| OOS_A_013 | 058860 | KTis | WATCH | MEDIUM | NO | |
| OOS_A_014 | 068270 | 셀트리온 | EXTENDED | HIGH | NO | |
| OOS_A_015 | 042700 | 한미반도체 | WATCH | HIGH | NO | |
| OOS_A_016 | 048430 | 유라테크 | WATCH | HIGH | NO | |
| OOS_A_017 | 076610 | 해성옵틱스 | WATCH | HIGH | NO | |
| OOS_A_018 | 065500 | 오리엔트정공 | EXTENDED | HIGH | NO | |
| OOS_A_019 | 069540 | 빛과전자 | WATCH | MEDIUM | NO | |
| OOS_A_020 | 036170 | 에이치엠넥스 | EXTENDED | HIGH | NO | |

분포: WATCH 12, SETUP 1, TRIGGER 0, TREND 1, EXTENDED 6. 관측 trigger event는 OOS_A_010 한 건이다. 2025-11-24는 사용자의 원본 관측 날짜이며 repository의 W-FRI label로 임의 치환하지 않았다.

3. PASS B Outcome Freeze

| OOS ID | Outcome label | Confidence | 상태 |
|---|---|---|---|
| OOS_A_001 | TOO_EXTENDED | HIGH | COMPLETE |
| OOS_A_002 | TOO_EXTENDED | HIGH | COMPLETE |
| OOS_A_003 | NO_SETUP | HIGH | COMPLETE |
| OOS_A_004 | TOO_EARLY | HIGH | COMPLETE |
| OOS_A_005 | NO_SETUP | HIGH | COMPLETE |
| OOS_A_006 | FALSE_TRIGGER | HIGH | COMPLETE |
| OOS_A_007 | TOO_EXTENDED | HIGH | COMPLETE |
| OOS_A_008 | TOO_EARLY | HIGH | COMPLETE |
| OOS_A_009 | TOO_EXTENDED | HIGH | COMPLETE |
| OOS_A_010 | TOO_LATE | HIGH | COMPLETE |
| OOS_A_011 | TOO_EARLY | HIGH | COMPLETE |
| OOS_A_012 | UNLABELED | UNLABELED | DATA_UNAVAILABLE |
| OOS_A_013 | NO_SETUP | HIGH | COMPLETE |
| OOS_A_014 | TOO_EXTENDED | HIGH | COMPLETE |
| OOS_A_015 | TOO_EARLY | HIGH | COMPLETE |
| OOS_A_016 | TOO_EARLY | HIGH | COMPLETE |
| OOS_A_017 | FALSE_TRIGGER | MEDIUM | COMPLETE |
| OOS_A_018 | TOO_EXTENDED | HIGH | COMPLETE |
| OOS_A_019 | FALSE_TRIGGER | HIGH | COMPLETE |
| OOS_A_020 | TOO_EXTENDED | HIGH | COMPLETE |

OOS_A_012는 거래정지로 정상적인 가격 outcome을 평가할 수 없었다. 기존 7-label taxonomy에 여덟 번째 label을 추가하지 않았으며, `pattern_a_fast_oos_outcome_adjudication_v01.csv`에 `TRADING_SUSPENSION_OUTCOME_UNAVAILABLE` 및 label available=false로 기록했다. Labeled 19건 분포는 FALSE_TRIGGER 3, TOO_EARLY 5, TOO_LATE 1, TOO_EXTENDED 7, NO_SETUP 3이다.

4. Preregistered Primary Test 사전 확인
RESERVED_OOS_A contains no Human POSITIVE_STRUCTURE labels. The preregistered primary score-direction comparison is therefore expected to be sample-size inconclusive. This is a property of the frozen reserved sample and MUST NOT be corrected by adding or replacing OOS samples.

5. 무결성 및 다음 단계
human review CSV와 보호 파일 SHA-256은 seal JSON에 기록했다. Stage review는 outcome review 이전에 기록되었으며, 인간 양성 anchor 4건은 OOS metric에 포함하지 않는다. OOS_A_012 unavailable 처리의 preregistered evaluation 해석은 advisor review 전에는 결정하지 않는다. 따라서 Phase 13I-2 evaluation은 시작하지 않는다.
