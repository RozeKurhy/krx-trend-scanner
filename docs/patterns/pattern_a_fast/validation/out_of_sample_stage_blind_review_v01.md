pattern_a_fast_oos_stage_blind_review_v01.md
==================================================
Phase 13I-1 Reserved OOS Stage Blind Review Guide
==================================================

PASS A에서는 reference_date 이후 chart를 열지 않는다. 먼저 weekly_stage_at_reference, weekly_stage_confidence, human_trigger_event_observed, human_trigger_event_date를 작성하고 저장. 그 뒤 PASS B.

작성 대상: artifacts/patterns/pattern_a_fast/validation/oos/pattern_a_fast_oos_human_review_v01.csv
허용 단계: WATCH, SETUP, TRIGGER, TREND, EXTENDED
신뢰도: HIGH, MEDIUM, LOW. trigger_event_observed는 YES, NO, UNLABELED 중 하나로 기록한다.
이 문서와 차트에는 자동 판단, 점수, 후보 여부 또는 다른 모델 산출물을 표시하지 않는다.

| 순서 | OOS ID | 티커 | 종목명 | 기준일 | Stage chart |
|---:|---|---|---|---|---|
| 001 | OOS_A_001 | 084670 | 동양고속 | 2025-12-26 | `artifacts/patterns/pattern_a_fast/validation/oos/charts/stage_blind/001_OOS_A_001_monthly.png` / weekly / daily |
| 002 | OOS_A_002 | 049470 | 비트플래닛 | 2025-09-26 | `artifacts/patterns/pattern_a_fast/validation/oos/charts/stage_blind/002_OOS_A_002_monthly.png` / weekly / daily |
| 003 | OOS_A_003 | 068240 | 다원시스 | 2025-09-26 | `artifacts/patterns/pattern_a_fast/validation/oos/charts/stage_blind/003_OOS_A_003_monthly.png` / weekly / daily |
| 004 | OOS_A_004 | 051910 | LG화학 | 2023-06-30 | `artifacts/patterns/pattern_a_fast/validation/oos/charts/stage_blind/004_OOS_A_004_monthly.png` / weekly / daily |
| 005 | OOS_A_005 | 054220 | 비츠로시스 | 2024-09-27 | `artifacts/patterns/pattern_a_fast/validation/oos/charts/stage_blind/005_OOS_A_005_monthly.png` / weekly / daily |
| 006 | OOS_A_006 | 049800 | 우진플라임 | 2025-06-27 | `artifacts/patterns/pattern_a_fast/validation/oos/charts/stage_blind/006_OOS_A_006_monthly.png` / weekly / daily |
| 007 | OOS_A_007 | 046970 | 우리로 | 2026-03-27 | `artifacts/patterns/pattern_a_fast/validation/oos/charts/stage_blind/007_OOS_A_007_monthly.png` / weekly / daily |
| 008 | OOS_A_008 | 065170 | 비엘팜텍 | 2025-12-26 | `artifacts/patterns/pattern_a_fast/validation/oos/charts/stage_blind/008_OOS_A_008_monthly.png` / weekly / daily |
| 009 | OOS_A_009 | 065170 | 비엘팜텍 | 2026-03-27 | `artifacts/patterns/pattern_a_fast/validation/oos/charts/stage_blind/009_OOS_A_009_monthly.png` / weekly / daily |
| 010 | OOS_A_010 | 043260 | 성호전자 | 2025-12-26 | `artifacts/patterns/pattern_a_fast/validation/oos/charts/stage_blind/010_OOS_A_010_monthly.png` / weekly / daily |
| 011 | OOS_A_011 | 078930 | GS | 2023-06-30 | `artifacts/patterns/pattern_a_fast/validation/oos/charts/stage_blind/011_OOS_A_011_monthly.png` / weekly / daily |
| 012 | OOS_A_012 | 043220 | 티에스넥스젠 | 2024-12-27 | `artifacts/patterns/pattern_a_fast/validation/oos/charts/stage_blind/012_OOS_A_012_monthly.png` / weekly / daily |
| 013 | OOS_A_013 | 058860 | KTis | 2026-03-27 | `artifacts/patterns/pattern_a_fast/validation/oos/charts/stage_blind/013_OOS_A_013_monthly.png` / weekly / daily |
| 014 | OOS_A_014 | 068270 | 셀트리온 | 2018-06-29 | `artifacts/patterns/pattern_a_fast/validation/oos/charts/stage_blind/014_OOS_A_014_monthly.png` / weekly / daily |
| 015 | OOS_A_015 | 042700 | 한미반도체 | 2022-12-23 | `artifacts/patterns/pattern_a_fast/validation/oos/charts/stage_blind/015_OOS_A_015_monthly.png` / weekly / daily |
| 016 | OOS_A_016 | 048430 | 유라테크 | 2024-09-27 | `artifacts/patterns/pattern_a_fast/validation/oos/charts/stage_blind/016_OOS_A_016_monthly.png` / weekly / daily |
| 017 | OOS_A_017 | 076610 | 해성옵틱스 | 2025-12-26 | `artifacts/patterns/pattern_a_fast/validation/oos/charts/stage_blind/017_OOS_A_017_monthly.png` / weekly / daily |
| 018 | OOS_A_018 | 065500 | 오리엔트정공 | 2024-12-27 | `artifacts/patterns/pattern_a_fast/validation/oos/charts/stage_blind/018_OOS_A_018_monthly.png` / weekly / daily |
| 019 | OOS_A_019 | 069540 | 빛과전자 | 2026-03-27 | `artifacts/patterns/pattern_a_fast/validation/oos/charts/stage_blind/019_OOS_A_019_monthly.png` / weekly / daily |
| 020 | OOS_A_020 | 036170 | 에이치엠넥스 | 2026-03-27 | `artifacts/patterns/pattern_a_fast/validation/oos/charts/stage_blind/020_OOS_A_020_monthly.png` / weekly / daily |
