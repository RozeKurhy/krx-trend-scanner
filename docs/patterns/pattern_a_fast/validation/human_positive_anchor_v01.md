pattern_a_fast_human_positive_anchor_v01.md
==================================================
Pattern A Fast Human Positive Anchor v0.1
==================================================

상태: QUALITATIVE_REFERENCE_ONLY

이 파일은 사용자가 식별한 GOOD_TRIGGER 구조의 인간 관찰 예시 4건을 보존한다. 이 anchor는 calibration sample도 RESERVED_OOS_A sample도 아니며 OOS metric 계산, HIERARCHICAL_V01 tuning, threshold/weight/feature/stage rule 변경 근거로 사용하지 않는다.

| Anchor | 티커 | 종목명 | Human identified week | Normalized W-FRI completed label | Stage | Human label |
|---|---|---|---|---|---|---|
| HPA_001 | 420770 | 기가비스 | 2026-01-12 | 2026-01-16 | TRIGGER | GOOD_TRIGGER |
| HPA_002 | 006110 | 삼아알미늄 | 2023-03-13 | 2023-03-17 | TRIGGER | GOOD_TRIGGER |
| HPA_003 | 034020 | 두산에너빌리티 | 2025-05-12 | 2025-05-16 | TRIGGER | GOOD_TRIGGER |
| HPA_004 | 000660 | SK하이닉스 | 2024-02-19 | 2024-02-23 | TRIGGER | GOOD_TRIGGER |

normalized_completed_week_label은 local raw cached OHLCV를 W-FRI로 resample해 기계적으로 확인했다. human_identified_week와 human_trigger_event_date는 사용자의 원본 관찰 날짜이며 덮어쓰지 않았다.

Human observation 공통점:
1. 단순 바닥 반등만으로는 충분하지 않다.
2. 역배열 상태에서 가격만 급등하는 형태는 positive가 아니다.
3. 이미 수배 상승한 이후 위치는 Fast 신규 진입 관점에서 부적절하다.
4. 이전의 의미 있는 주봉 고점 또는 저항이 존재한다.
5. 그 저항을 강하게 돌파하고 주봉 종가가 상승 마감으로 이를 확인한다.
6. 그 돌파는 크게 진행된 상승 후반이 아닌 초기 추세 형성 구간이다.

위 문장은 사람의 질적 관찰일 뿐이며 이번 commit에서 새 rule, feature, threshold 또는 score formula로 구현하지 않는다.
