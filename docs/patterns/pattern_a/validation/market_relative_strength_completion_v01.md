market_relative_strength_completion_v01.md
==================================================
Phase 12 Market Relative Strength Completion v0.1
==================================================

범위
--------------------------------------------------
기존 Market Relative Strength Level(3M/6M/12M)은 그대로 유지하고, 공식
COMMON 유니버스 전체를 기준으로 Improvement, Acceleration, Rank, Percentile을
추가한 로컬 검증이다. RS는 현재 confirmation/context feature이며 entry/exit,
candidate filter, investability filter, score modifier, position sizing input이
아니다.

기준과 데이터
--------------------------------------------------
- 기준일: 2026-08-14
- START HEAD: de53a3c729d0837c1270a09708206bb37616c4cc
- 3M/6M/12M: 63/126/252 benchmark sessions
- KOSPI benchmark: 1001
- KOSDAQ benchmark: 2001
- 공식 COMMON: 2,528개
- Candidate: 180개
- Investable Candidate: 103개
- 네트워크 요청: 0회
- 입력: 기존 로컬 stock parquet, 기존 market index parquet, 기존 Phase10/11 authority

추가 필드
--------------------------------------------------
- `market_rs_delta_3m_vs_6m = market_rs_3m - market_rs_6m`
- `market_rs_delta_6m_vs_12m = market_rs_6m - market_rs_12m`
- `market_rs_acceleration_3_6_12m = market_rs_3m - 2*market_rs_6m + market_rs_12m`
- `all_market_rs_rank_{3m,6m,12m}`: horizon별 유효값 전체의 descending average rank
- `all_market_rs_percentile_{3m,6m,12m}`: `(N-rank)/(N-1)*100`, N=1은 100

결과
--------------------------------------------------
- Market RS READY Candidate: 176개
- Investable Market RS READY: 103/103
- Horizon population: 3M 2,360 / 6M 2,353 / 12M 2,325
- Horizon missing: 3M 168 / 6M 175 / 12M 203
- Legacy RS level/status/anchor mismatch: 0/0/0
- Improvement arithmetic mismatch: 0
- Missing propagation mismatch: 0
- 독립 percentile recomputation mismatch: 0
- Candidate all-market lookup mismatch: 0
- Investable all-market lookup mismatch: 0
- Pattern A Candidate identity mismatch: 0
- Phase10 identity mismatch: 0
- Phase11 identity mismatch: 0
- 진단 cohort(12M<0, 6M>12M, 3M>6M): All COMMON 1,463 / Candidate 123 / Investable 78

Sector RS 정책
--------------------------------------------------
- Market RS scope: COMPLETED
- Sector RS scope: DEFERRED_FUTURE_EXTENSION
- Sector closure gating: false
- Sector mapping/arithmetic gate: DEFERRED_NON_GATING
- 기존 Gate 7/8 실패 evidence는 덮어쓰거나 PASS로 바꾸지 않았다.

검증 및 성능
--------------------------------------------------
- Full COMMON reference 계산: 2,528 ticker loads / 2,528 RS calculations
- 전체 wall clock: 약 190.1초
- reference build: 약 4.9초
- 독립 synthetic 테스트와 candidate-only percentile regression을 포함했다.
- 새 테스트와 기존 RS 테스트: 19 passed
- Full repository test suite는 별도 실행 결과를 r.md에 기록한다.

산출물
--------------------------------------------------
`artifacts/patterns/pattern_a/validation/relative_strength/market_completion_v01/`

- `market_rs_universe_20260814.csv`
- `market_rs_candidates_20260814.csv`
- `market_rs_investable_candidates_20260814.csv`
- `market_rs_distribution_20260814.json`
- `market_rs_cross_section_validation_20260814.json`
- `market_rs_completion_summary_20260814.json`
- `market_rs_completion_manifest_20260814.json`
- `market_rs_examples_20260814.csv`

최종 판정
--------------------------------------------------
모든 Market RS completion gate가 PASS했고, Architect의 closure review만 남았다.
이 문서는 Phase12를 스스로 CLOSED 선언하지 않으며 다음 상태만 제안한다.

`READY_FOR_ARCHITECT_PHASE12_CLOSURE_REVIEW`
