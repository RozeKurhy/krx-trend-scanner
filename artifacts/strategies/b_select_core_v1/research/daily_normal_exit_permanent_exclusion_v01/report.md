# B Select 7개 permanent exclusion + 5-window 재검증 V01

| 레벨 | 개수 |
|---|---:|
| CRITICAL | 0 |
| MAJOR | 0 |
| MINOR | 0 |

- 영구 제외 판정: B_SELECT_7_IDENTITY_PERMANENT_EXCLUSION_PASS
- Daily NORMAL Exit 후보: B_SELECT_DAILY_NORMAL_EXIT_CANDIDATE_VALIDATION_PASS
- 시작 HEAD/origin/main: c69f1e09cde89d364e1a1df837065c67a6e4da50 / c69f1e09cde89d364e1a1df837065c67a6e4da50
- worker: 10
- Strategy signal/trade source entries are filtered by exact identity before the fresh exit-cadence and cash-portfolio replay; neither previous portfolio output nor production state is reused or modified.

## 1–2. 영구 제외 exact-set 검증

기준 중앙 registry 174개에 사용자 승인 exact pair 7개를 더해 181개야. duplicate exact key, normalization collision, ticker-only exclusion은 모두 0이야.

| ticker | ISU_CD | 종목 | data-quality 사유 |
|---|---|---|---|
| 007720 | KR7007720006 | 소노스퀘어 | 주식수 변경 뒤 adjusted price unit 연속성 미확정 |
| 011080 | KR7011080009 | 형지I&C | 주식수 변경 뒤 adjusted price unit 연속성 미확정 |
| 019490 | KR7019490002 | 엑시큐어하이트론 | 주식수 변경 뒤 adjusted price unit 연속성 미확정 |
| 019570 | KR7019570001 | GMI벤처 | 설명되지 않은 adjusted price unit 변화 |
| 066790 | KR7066790007 | 씨씨에스 | 복수 주식수 변경 뒤 adjusted price unit 연속성 미확정 |
| 073570 | KR7073570004 | 리튬포어스 | 주식수 변경 뒤 adjusted price unit 연속성 미확정 |
| 083660 | KR7083660001 | CSA 코스믹 | 주식수 변경 뒤 adjusted price unit 연속성 미확정 |

## 3. 5-window CONTROL/TEST 무결성

월말 source ledger와 재계산 CONTROL 청산일이 다른 일부 행은 기존 cadence V01에서도 이미 확인된 차이야. 아래 `기존/신규`는 봉인된 사전 제외 cadence 비교표와 exact identity·진입일·양쪽 청산일을 대조해 계산했고, 새 차이만 구조 검증 실패로 처리했어.

| Window | exclusion count | 제거된 source candidate/fill | 신규 7 leak | 월말 ENTRY 위반 | CONTROL 중간월 EXIT | TEST 비-NORMAL EXIT | exact-session 위반 | invalid open | overlap | silent drop | 현금 오류 | 비용 mismatch | cutoff 뒤 ENTRY | 월말 source parity 기존/신규 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P1 | 181 | 10/10 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2/2 / 0 |
| P2-1 | 181 | 2/2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0/0 / 0 |
| P2-2 | 181 | 4/4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1/1 / 0 |
| P3-1 | 181 | 1/1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0/0 / 0 |
| P3-2 | 181 | 3/3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1/1 / 0 |

## 4–5, 7. Portfolio 성과·valuation·자본 운용

| Window | Case | 최종자산(원) | 총수익률 | CAGR | MDD/유형 | coverage | unresolved marks / 누락일 | 평균/최대 자본활용 | turnover 배수 | 현금부족 skip/비율 | 평균/최대 동시보유 |
|---|---|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| P1 | CONTROL_MONTH_END | 414,812,849 | 107.41% | 5.93% | -17.40% / OBSERVED MDD | 99.07% | 36 / 29 | 25.52% / 92.59% | 23.20x | 14 / 2.96% | 20.39 / 82 |
| P1 | TEST_DAILY | 443,225,802 | 121.61% | 6.49% | -13.50% / OBSERVED MDD | 99.07% | 33 / 29 | 21.45% / 85.22% | 24.01x | 4 / 0.85% | 17.11 / 83 |
| P2-1 | CONTROL_MONTH_END | 246,931,427 | 23.47% | 4.91% | -20.62% / OBSERVED MDD | 99.91% | 1 / 1 | 46.60% / 99.26% | 9.28x | 20 / 9.39% | 28.64 / 51 |
| P2-1 | TEST_DAILY | 271,771,229 | 35.89% | 7.22% | -17.59% / OBSERVED MDD | 99.91% | 1 / 1 | 39.03% / 99.33% | 9.84x | 12 / 5.63% | 26.51 / 53 |
| P2-2 | CONTROL_MONTH_END | 262,511,876 | 31.26% | 4.93% | -23.46% / OBSERVED MDD | 97.91% | 36 / 29 | 45.77% / 99.26% | 12.33x | 61 / 19.37% | 29.39 / 60 |
| P2-2 | TEST_DAILY | 309,266,986 | 54.63% | 8.01% | -18.28% / OBSERVED MDD | 97.91% | 33 / 29 | 37.50% / 99.33% | 13.86x | 37 / 11.75% | 26.50 / 62 |
| P3-1 | CONTROL_MONTH_END | 234,683,060 | 17.34% | 4.81% | -18.52% / EXACT MDD | 100.00% | 0 / 0 | 55.53% / 98.25% | 7.44x | 20 / 11.30% | 31.78 / 48 |
| P3-1 | TEST_DAILY | 237,433,705 | 18.72% | 5.17% | -17.58% / EXACT MDD | 100.00% | 0 / 0 | 49.38% / 98.27% | 7.54x | 19 / 10.73% | 29.02 / 45 |
| P3-2 | CONTROL_MONTH_END | 248,378,673 | 24.19% | 4.76% | -24.07% / OBSERVED MDD | 97.54% | 35 / 28 | 52.63% / 98.25% | 10.39x | 63 / 22.58% | 31.43 / 57 |
| P3-2 | TEST_DAILY | 269,653,785 | 34.83% | 6.63% | -19.82% / OBSERVED MDD | 97.54% | 32 / 28 | 45.68% / 99.87% | 11.19x | 51 / 18.28% | 27.84 / 58 |

| Window | Case | 전체 거래일 | 관측 equity | 누락 equity | unresolved 구간 | 최대 누락 연속 | peak / trough / recovery |
|---|---|---:|---:|---:|---:|---:|---|
| P1 | CONTROL_MONTH_END | 3107 | 3078 | 29 | 3 | 19 | 2026-04-23 / 2026-07-29 / 2026-08-12 |
| P1 | TEST_DAILY | 3107 | 3078 | 29 | 3 | 19 | 2026-04-23 / 2026-07-29 / 2026-08-12 |
| P2-1 | CONTROL_MONTH_END | 1082 | 1081 | 1 | 1 | 1 | 2022-01-12 / 2022-10-13 / 2023-05-22 |
| P2-1 | TEST_DAILY | 1082 | 1081 | 1 | 1 | 1 | 2022-08-18 / 2022-10-13 / 2023-02-03 |
| P2-2 | CONTROL_MONTH_END | 1387 | 1358 | 29 | 3 | 19 | 2026-04-23 / 2026-07-29 / 미회복 |
| P2-2 | TEST_DAILY | 1387 | 1358 | 29 | 3 | 19 | 2026-04-23 / 2026-07-29 / 2026-08-12 |
| P3-1 | CONTROL_MONTH_END | 834 | 834 | 0 | 0 | 0 | 2023-06-28 / 2024-12-09 / 미회복 |
| P3-1 | TEST_DAILY | 834 | 834 | 0 | 0 | 0 | 2024-01-09 / 2024-12-09 / 미회복 |
| P3-2 | CONTROL_MONTH_END | 1139 | 1111 | 28 | 2 | 19 | 2026-04-23 / 2026-07-29 / 미회복 |
| P3-2 | TEST_DAILY | 1139 | 1111 | 28 | 2 | 19 | 2026-04-23 / 2026-07-29 / 2026-08-12 |

valuation-only carry는 공식 KRX raw exact-date 0 OHLC·volume·trading_value placeholder, positive close/listed_shares, exact PIT COMMON 활성, A/B 연속성 audit, 직전 정상 Repository V2 adjusted close와 raw trade anchor를 모두 통과한 경우에만 적용했어. 새 7개 C identity는 후보/체결 입력에서 제거됐고 carry audit에 들어오지 않았어. 단순 결측은 unresolved로 유지했어.

## 6. 거래 및 tail 비교

Net return은 실제 포트폴리오에서 실행된 완료 ENTRY/EXIT 체결의 비용 반영 수익률이야.

| Window | Case | 실행 ENTRY | 완료 거래 | cutoff 미청산 | 승률 | 평균/중앙 수익률 | 평균/중앙 보유일 | <=-15 / <=-30 | >=+30 / >=+50 / >=+100 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| P1 | CONTROL_MONTH_END | 459 | 415 | 44 | 79.76% | 13.42% / 12.13% | 131.88 / 43.00 | 44 / 22 | 73 / 25 / 6 |
| P1 | TEST_DAILY | 469 | 434 | 35 | 83.87% | 13.61% / 12.14% | 109.09 / 24.00 | 39 / 22 | 78 / 22 / 4 |
| P2-1 | CONTROL_MONTH_END | 193 | 155 | 38 | 79.35% | 15.25% / 12.34% | 116.74 / 43.00 | 14 / 7 | 31 / 11 / 3 |
| P2-1 | TEST_DAILY | 201 | 166 | 35 | 86.75% | 16.26% / 13.39% | 103.54 / 24.00 | 14 / 9 | 33 / 10 / 2 |
| P2-2 | CONTROL_MONTH_END | 254 | 215 | 39 | 75.81% | 11.60% / 11.16% | 149.23 / 44.00 | 27 / 14 | 38 / 13 / 3 |
| P2-2 | TEST_DAILY | 278 | 245 | 33 | 82.86% | 13.21% / 12.77% | 125.71 / 26.00 | 27 / 18 | 45 / 13 / 3 |
| P3-1 | CONTROL_MONTH_END | 157 | 122 | 35 | 81.15% | 15.44% / 13.99% | 134.20 / 44.00 | 14 / 7 | 28 / 10 / 2 |
| P3-1 | TEST_DAILY | 158 | 126 | 32 | 84.13% | 14.33% / 13.29% | 122.01 / 42.00 | 14 / 9 | 25 / 8 / 1 |
| P3-2 | CONTROL_MONTH_END | 216 | 179 | 37 | 77.09% | 11.87% / 11.94% | 158.23 / 44.00 | 25 / 12 | 35 / 12 / 2 |
| P3-2 | TEST_DAILY | 228 | 197 | 31 | 80.71% | 11.94% / 11.54% | 136.85 / 42.00 | 25 / 16 | 35 / 11 / 2 |

## 8–9. 공식 A–E Gate 및 후보 판정

| Window | A | B | C | D | E | CONTROL−TEST MDD | TEST MDD 절대 기준 |
|---|---|---|---|---|---|---:|---|
| P1 | PASS | PASS | PASS | PASS | PASS | -3.90pp | -55.0% |
| P2-1 | PASS | PASS | PASS | PASS | PASS | -3.03pp | -40.0% |
| P2-2 | PASS | PASS | PASS | PASS | PASS | -5.18pp | -40.0% |
| P3-1 | PASS | PASS | PASS | PASS | PASS | -0.94pp | -40.0% |
| P3-2 | PASS | PASS | PASS | PASS | PASS | -4.25pp | -40.0% |

상대 기준은 CONTROL MDD − TEST MDD가 5.0%p 이상이면 FAIL이야. coverage 90% 미만 case의 관측 MDD는 공식 Gate PASS 근거로 쓰지 않았어. 현금 부족 skip은 필수 진단값이며 PASS/FAIL Gate로 쓰지 않았어.

후보 최종 판정 token: B_SELECT_DAILY_NORMAL_EXIT_CANDIDATE_VALIDATION_PASS.
영구 제외 및 구조 검증 token: B_SELECT_7_IDENTITY_PERMANENT_EXCLUSION_PASS.

## 10. 적용 경계

중앙 exact identity exclusion authority만 공통 반영했어. A FAST Core V2와 Julia V1은 이번 작업에서 백테스트하지 않았어. B Select 연구 portfolio만 새로 재생했으며, 공식 전략 승격·history/lifecycle 수정·Production 적용은 별도 지시가 필요해.

## 재현 및 산출물

- worker count: 10
- 월말 source parity baseline: artifacts/strategies/b_select_core_v1/research/daily_normal_exit_cadence_v01/trade_comparison.csv (SHA-256 01f674e217ae4a12276646eb53a2003ab1104fec6cda3646351a83a61c8887a9); window별 사전 확인된 차이 {'P1': 2, 'P2-1': 0, 'P2-2': 1, 'P3-1': 0, 'P3-2': 1}
- 분석기: scripts/replay_b_select_daily_normal_exit_permanent_exclusion_v01.py
- 테스트: tests/test_b_select_daily_normal_exit_permanent_exclusion_v01.py
- 상세 원장: exclusion_impact.csv, integrity_checks.csv, portfolio_metrics.csv, trade_metrics.csv, valuation_carry_audit.csv, 각 window/scenario 하위 event·trade·equity·cost 파일
- 경과 시간: 231.6초
