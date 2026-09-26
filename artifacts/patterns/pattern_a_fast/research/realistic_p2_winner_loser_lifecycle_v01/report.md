# A FAST Core V2 — 현실적 P2 Winner/Loser + Lifecycle Profile V01

## 최종 판정: `REALISTIC_P2_CONFIRMS_NORMAL_HANDOFF_ADVANTAGE`

- 생존 종목 + PIT 시가총액 1조 이상 universe에서도 NORMAL handoff가 coverage 경로보다 수익분포가 좋다.
- 4개 패널(P2-1/P2-2 × eligible/filled)에서 평균, +50%, +100%, 수익률 AUC가 모두 NORMAL 쪽으로 유리하다. 크기도 broad 같은 윈도우의 50% 이상이 유지된다(MAINTAINED).
- deep-loss 차이는 표본이 작다. P2-1에는 -50% 이하가 없다. P2-2에서는 broad보다 약해졌다.
- P2-1은 P2-2의 앞부분이고 filled는 eligible의 부분집합이다. 따라서 4개 패널 일치는 독립된 네 번의 확인이 아니다.

새 백테스트, 전략 재평가, Candidate 분석, 임계값·생존 정책 변경, feature 재계산, 네트워크 호출은 모두 0건이다. 원본 실행 폴더에는 아무것도 쓰지 않았다.

## 1. 입력과 검증

| | P2-1 | P2-2 |
|---|---:|---:|
| 인증 상태 | `P2_1_REALISTIC_PORTFOLIO_BACKTEST_CERTIFIED` | `P2_2_REALISTIC_PORTFOLIO_BACKTEST_CERTIFIED` |
| eligible CONTROL 거래 | 355 | 485 |
| filled (ENTRY/EXECUTED) | 199 | 242 |
| 현금 부족 스킵 (= eligible − filled) | 156 | 243 |
| 청산 체결 | 161 | 218 |

**인증 수치 재현 게이트:** 이벤트와 일별 자산 파일에서 아래 값을 다시 계산했고 `summary.csv` CONTROL 값과 모두 일치했다.
- 체결 수, 청산 수, 현금 부족 스킵 수
- 비용 반영 순수익 기준 승률(22.98% / 30.28%)
- 꼬리 건수: P2-1은 ≤-30/-40/-50/-60 = 2/0/0/0, ≥+50/+100 = 11/7이다. P2-2는 5/2/1/0, 37/21이다.
- effective_end 평가 자산, MDD

**수익률 두 가지를 섞지 않았다.**
- **기본:** 원장 `terminal_return`이다. broad 연구와 같은 계약이며 OPEN_AT_CUTOFF는 cutoff 평가값이다. 모든 lifecycle·winner/loser 비교에 쓴다.
- **보조:** 체결 후 청산된 거래의 비용 반영 순수익률이다. 게이트와 filled 프로파일의 참고 열에만 쓴다. 청산 거래마다 원장 수익률 대비 비용 차감 비율이 0.99~1.0 안에 드는지 확인했다.

**진입 feature 연결:** 상위 연구의 PIT 복원 캐시를 (ticker, isu_cd, entry_signal_date)로 재사용했다.
- P2-1 355건 중 328건, P2-2 485건 중 450건이 연결되었다.
- 연결된 행 모두 실제형 원장의 `fast_score`, Pattern A 단계와 불일치 0건이며, 캐시 키 중복도 0건이다.
- 나머지는 broad 원장에 없는 신호라서 NA로 두고 다시 계산하지 않았다. 1조 미만으로 거부된 신호가 재진입 상태를 소모하지 않아 생긴 새 재진입이다.
- 그룹별 연결률은 `feature_cache_join_coverage.csv`에 있다.
- PIT 시가총액은 실제형 원장의 `entry_market_cap`(정확한 신호일 KRX MKTCAP)을 썼다.

**경로 점검:** 실제형 eligible 거래 중 broad 같은 윈도우 원장에 같은 identity가 있는 거래는 P2-1 327건, P2-2 449건이다. 이 거래들은 100% `terminal_return`과 `lifecycle_class`가 같다. 따라서 broad와 실제형의 차이는 경로 변화가 아니라 선택(필터) 효과다.

## 2. NORMAL vs coverage 핵심 성과 (원장 `terminal_return`, 전체 거래)

| 패널 | NORMAL n | COV n | 평균 N / C | 중앙값 N / C | ≥+50% N / C | ≥+100% N / C | ≤-30% N / C | ≤-50% N / C | AUC |
|---|---:|---:|---|---|---|---|---|---|---:|
| P2-1 eligible | 98 | 69 | +25.6 / +5.6 | +14.2 / -14.5 | 22.4 / 13.0 | 9.2 / 2.9 | 0 / 10.1 | 0 / 0 | 0.633 |
| P2-1 filled | 55 | 33 | +24.8 / +0.6 | +14.3 / -14.8 | 18.2 / 9.1 | 10.9 / 6.1 | 0 / 12.1 | 0 / 0 | 0.661 |
| P2-2 eligible | 273 | 89 | +29.6 / +8.8 | -0.5 / -14.8 | 29.3 / 18.0 | 13.2 / 6.7 | 1.5 / 3.4 | 0.4 / 2.2 | 0.592 |
| P2-2 filled | 138 | 37 | +29.2 / +4.4 | -7.9 / -14.8 | 26.1 / 13.5 | 13.8 / 8.1 | 2.9 / 2.7 | 0.7 / 2.7 | 0.604 |
| broad P2-1 (참고) | 613 | 323 | | | | | | | 0.637 |
| broad P2-2 (참고) | 1,069 | 474 | | | | | | | 0.625 |

- 비율은 %다. N은 NORMAL, C는 coverage다.
- SKIPPED·WITHOUT_DIRECT 각각의 지표와 NEVER_PROGRESSED 참고 행은 `p2_*_{eligible,filled}_profile.csv`에 있다.
- P2-1은 cutoff가 짧아 eligible의 53%가 NEVER_PROGRESSED다. lifecycle 표본이 작고 라벨도 cutoff에 따라 바뀐다. 예를 들어 025980은 P2-1에서 SKIPPED였지만 P2-2에서는 NORMAL이다.

**closed-only(eligible)**
- 평균 차이: P2-1 +23.1pp, P2-2 +19.5pp
- +50% 차이: +10.6pp, +10.5pp
- AUC: 0.661, 0.597
- 모두 broad 같은 윈도우 대비 MAINTAINED다. deep-loss 지표는 양쪽 건수가 0~4건이라 판단에 쓰지 않는다.

## 3. Broad 대비

**비교 기준:** broad 같은 윈도우(같은 기간·cutoff)의 NORMAL−coverage 차이다. 분류 규칙은 결과를 보기 전에 고정했다.
- MAINTAINED: 같은 방향이고 broad의 50% 이상
- WEAKENED: 20~50%
- VANISHED: 20% 미만 또는 0
- REVERSED: 방향 반대

| 지표 | P2-1 eligible | P2-2 eligible | P2-1 filled | P2-2 filled |
|---|---|---|---|---|
| 평균 | +20.0 vs +19.5 MAINTAINED | +20.8 vs +22.0 MAINTAINED | +24.3 MAINTAINED | +24.8 MAINTAINED |
| ≥+50% | +9.4 vs +12.0 MAINTAINED | +11.3 vs +13.3 MAINTAINED | +9.1 MAINTAINED | +12.6 MAINTAINED |
| ≥+100% | +6.3 vs +5.2 MAINTAINED | +6.4 vs +6.1 MAINTAINED | +4.8 MAINTAINED | +5.7 MAINTAINED |
| ≤-30% | -10.1 vs -6.3 MAINTAINED | -1.9 vs -5.0 WEAKENED | 서술용 | 서술용 (+0.2, 반대) |
| ≤-50% | 0 vs -2.6 VANISHED | -1.9 vs -3.2 MAINTAINED | 서술용 | 서술용 |
| ≤-60% | 0 vs -1.4 VANISHED | -1.1 vs -2.4 WEAKENED | 서술용 | 서술용 |
| AUC-0.5 | 0.133 vs 0.137 | 0.092 vs 0.125 | 0.161 | 0.104 |

- 셀의 앞 값은 실제형, 뒤 값은 broad 같은 윈도우다.
- **winner 쪽:** 평균, +50%, +100%, AUC의 우위는 네 패널 모두 broad 같은 윈도우와 비슷한 크기로 유지된다.
- **deep-loss 쪽:** 1조 이상 universe에는 deep loss 자체가 거의 없어서 차이가 사라지거나 약해졌다. P2-1 eligible의 -50% 이하는 0건이고, P2-2 eligible은 3건이다.

## 4. Winner profile (+50% / +100%)

**lifecycle 분포**

| | P2-1 elig | P2-1 filled | P2-2 elig | P2-2 filled | broad pooled |
|---|---:|---:|---:|---:|---:|
| WIN_50 n | 38 | 17 | 99 | 43 | 830 |
| WIN_50 중 NORMAL | 57.9% | 58.8% | 80.8% | 83.7% | 87.0% |
| WIN_50 중 NEVER_PROGRESSED | 18.4% | 23.5% | 3.0% | 4.7% | 0.7% |
| WIN_100 n | 11 | 8 | 42 | 22 | 346 |
| WIN_100 중 NORMAL | 81.8% | 75.0% | 85.7% | 86.4% | 88.7% |

- P2-2의 winner lifecycle 분포는 broad와 비슷하다.
- P2-1은 cutoff가 짧아 아직 PROGRESSED에 닿지 않은 평가상 winner(NEVER_PROGRESSED)가 섞여 있어 NORMAL 비중이 낮다.

**진입 feature**
- WIN_50은 비교군보다 ATR이 4개 패널 모두 낮다(AUC 0.33~0.42). broad(0.45, MIXED)보다 뚜렷하다.
- WIN_50은 KOSDAQ 비중이 5~11pp 낮고, `close_vs_wma200_pct`가 낮다.
- WIN_100은 broad와 반대로 시가총액이 더 크다(AUC 0.57~0.67). broad pooled에서는 소형주 쪽이었다.
- Pattern A 점수와 FAST 점수는 여기서도 약하다(|AUC-0.5| ≤ 0.06). P2-1 WIN_100의 Pattern A 점수(0.13~0.14, n=8~11)만 예외다.

## 5. Loser profile (-30% 이하)

- -30% 이하는 eligible 8건 / 8건, filled 5건 / 6건이다. n<10이라 profile 일반화를 하지 않는다. -50% 이하는 0 / 3건, -60% 이하는 0 / 1건이다.
- 참고로 방향만 보면 broad와 같다. KOSDAQ 비중이 +31~46pp 높고, ATR이 높고, `wma12_vs_wma26_pct` 이격이 크다.
- **개별 건:**
  - P2-2의 최악 두 건(-61%, -57%)은 SKIPPED 경로에서 청산 신호 없이 cutoff까지 보유된 거래다.
  - NORMAL 경로의 deep loss 3건(-55%, -46%, -34%)은 Exit4·Exit3로 청산된 갭 손실이다.

## 6. Eligible vs filled 선택 효과 (현금 제약)

| | P2-1 elig | filled | skipped | P2-2 elig | filled | skipped |
|---|---:|---:|---:|---:|---:|---:|
| NORMAL 비중 | 27.6 | 27.6 | 27.6 | 56.3 | 57.0 | 55.6 |
| coverage 비중 | 19.4 | 16.6 | 23.1 | 18.4 | 15.3 | 21.4 |
| WIN_50 비중 | 10.7 | 8.5 | 13.5 | 20.4 | 17.8 | 23.0 |
| WIN_100 비중 | 3.1 | 4.0 | 1.9 | 8.7 | 9.1 | 8.2 |
| LOSS_30 비중 | 2.3 | 2.5 | 1.9 | 1.6 | 2.5 | 0.8 |
| 평균 수익률 | 4.49 | 3.38 | 5.92 | 15.36 | 14.47 | 16.25 |
| 2021~2022 진입 비중 | 46.8 | 60.3 | 29.5 | 34.0 | 46.3 | 21.8 |
| 시총 중앙값(억) | 24,514 | 28,994 | 18,339 | 24,088 | 27,289 | 19,383 |

- **NORMAL 비중:** 현금 제약이 바꾸지 않는다(차이 ≤1.5pp).
- **coverage 비중:** filled에서 3~6pp 낮다. 스킵된 거래 쪽에 coverage가 더 많았다.
- **WIN_50 비중과 평균 수익률:** filled가 스킵보다 약간 낮다.
  - filled는 초기(2021~2022) 진입이 많다. 자금이 일찍 소진되어 이후 신호가 스킵되기 때문이다.
  - 같은 날에는 시총이 큰 순서로 체결된다.
  - 따라서 이 차이는 달력·시총 순서 효과가 섞인 것이지 lifecycle 선별이 아니다.
- 새 현금 정책은 만들지 않았다.

## 7. Deep loser가 줄어든 이유 (필터 귀속)

broad 같은 윈도우 거래를 실제형 필터로 나눠 봤다. 생존 여부는 실행 폴더의 universe audit를, 시가총액은 PIT MKTCAP을 기준으로 삼았다. 기존 1조 임계값만 사용했다.

| broad 슬라이스 | P2-1 n | 두 필터 통과 | 1조 미만만 | 비생존 포함 | P2-2 n | 두 필터 통과 | 1조 미만만 | 비생존 포함 | 기존 정책 제외 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 전체 | 1,800 | 18.3% | 1,413 | 57 | 2,424 | 18.6% | 1,872 | 70 | 30 |
| WIN_50 | 187 | 19.3% | 145 | 6 | 336 | 26.8% | 234 | 7 | 5 |
| WIN_100 | 64 | 15.6% | 53 | 1 | 134 | 29.1% | 91 | 2 | 2 |
| LOSS_30 | 37 | 16.2% | 28 | 3 | 57 | 12.3% | 43 | 4 | 3 |
| LOSS_50 | 11 | 0% | 10 | 1 | 22 | 13.6% | 15 | 1 | 3 |
| LOSS_60 | 6 | 0% | 5 | 1 | 13 | 7.7% | 9 | 1 | 2 |
| coverage ≤-30% | 23 | 21.7% | 17 | 1 | 31 | 9.7% | 23 | 2 | 3 |

- deep loser는 대부분 **1조 미만 필터**에서 빠진다.
- 생존 필터만으로 빠지는 deep loser는 0건이고, 비생존이면서 1조 미만인 경우가 1~4건이다.
- P2-2에서는 1조 필터가 -50% 이하를 전체 평균(18.6%)보다 낮은 비율(13.6%)만 통과시키고, +100%는 더 높은 비율(29.1%)로 통과시킨다.
- 따라서 이번 근거는 "대형 survivor filter" 중 **시가총액 쪽**을 지지한다. 생존 필터 자체의 효과는 작다.
- 3조, 5천억 등 다른 임계값 민감도는 금지 범위라 보지 않았다.

## 8. 진입 feature vs lifecycle 설명력

같은 rank AUC 단위로 비교했다. lifecycle은 NORMAL 0/1 지시변수를 썼다.
- 양쪽 n≥10인 11개 비교 중 9개에서 NORMAL 지시변수의 |AUC-0.5|(0.15~0.28)가 가장 강한 진입 feature보다 크다.
- 예외 2개는 P2-2 filled이며 비슷한 수준이다. WIN_50에서 ATR 0.165 vs 0.162, WIN_100에서 시총 0.175 vs 0.161이다.
- lifecycle은 진입 후에야 알 수 있는 상태이므로 진입 필터 근거로 쓰지 않는다.

## 9. 질문별 답

1. **P2-1 1조+ universe에서 NORMAL이 coverage보다 좋은가?** 좋다. 평균 +20.0pp, +50% +9.4pp, AUC 0.633이다. 다만 coverage n이 69건이고 cutoff가 짧다.
2. **P2-2에서도 같은가?** 같다. 평균 +20.8pp, +50% +11.3pp, +100% +6.4pp, AUC 0.592이며 7개 지표가 모두 유리하다.
3. **eligible과 filled에서 방향이 유지되는가?** 평균, +50%, +100%, AUC는 4개 패널 모두 유지된다. filled deep-loss는 표본이 작아 서술용이다.
4. **broad의 NORMAL 우위가 대형 survivor universe에서도 유지되는가?** winner 쪽 우위는 broad 같은 윈도우 대비 MAINTAINED다(비율 0.76~1.25).
5. **약해진 부분은 얼마나 약해졌나?** deep-loss 쪽만 약해졌다. P2-2 eligible에서 ≤-30%는 broad의 38%, ≤-60%는 46%이고, P2-1은 0이다. AUC는 P2-2에서 broad의 73%다.
6. **winner의 lifecycle 분포는 broad와 비슷한가?** P2-2는 비슷하다(WIN_50의 81~84%, WIN_100의 86%가 NORMAL). P2-1은 짧은 cutoff 때문에 NORMAL 비중이 58%로 낮다.
7. **deep loser 감소가 대형 survivor filter 때문이라는 근거가 강화되는가?** 강화된다. broad의 deep loser는 대부분 1조 미만이라 빠졌고 생존 필터 단독 효과는 없었다. 실제형 거래는 broad와 같은 identity면 경로와 수익률이 100% 같아서 선택 효과로 설명된다.
8. **filled 선택과 현금 제약이 lifecycle 비중을 바꾸는가?** NORMAL 비중은 바꾸지 않는다. coverage 비중은 filled에서 3~6pp 낮지만 진입 연도와 시총 순서가 함께 바뀐 결과다.
9. **P2에서도 lifecycle이 진입 feature보다 설명력이 큰가?** 대체로 크다(11개 중 9개). P2-2 filled에서는 ATR과 시총이 비슷한 수준이다.
10. **coverage exit 연구의 우선순위를 강화하는가?** 부분적으로 강화한다.
    - NORMAL과 coverage의 수익률 격차가 대형주 universe에서도 그대로 유지된다. coverage 경로 거래는 평균 수익률이 20pp 가량 낮은 집단이다.
    - 실제형 최악 두 건도 coverage 미청산 보유다.
    - 다만 1조 이상 universe에서는 deep loss 자체가 드물다. "deep loss 방지" 효과보다 "coverage 경로의 낮은 기대수익" 쪽이 연구 동기로 더 크다.
    - 새 전략안은 만들지 않았다.

## 10. 해석 주의

- P2-1은 P2-2의 앞부분이고 filled는 eligible의 부분집합이다. 4개 패널 일치는 독립 확인이 아니다.
- P2-1은 cutoff가 짧아 NEVER_PROGRESSED가 53%다. lifecycle 라벨과 coverage 꼬리가 잘려 있다.
- filled deep-loss는 0~6건이라 해석하지 않았다. LOSS_30 이하 profile은 n<10이라 방향만 적었다.
- 상관을 인과로 단정하지 않는다. lifecycle은 진입 후 상태다.

## 산출물

| 파일 | 내용 |
|---|---|
| `p2_1_eligible_profile.csv`, `p2_1_filled_profile.csv`, `p2_2_eligible_profile.csv`, `p2_2_filled_profile.csv` | 패널별 lifecycle 그룹 지표(전체/closed-only, filled는 순수익 참고 열 포함) |
| `lifecycle_comparison.csv` | 패널 × 전체/closed-only × 4개 비교 |
| `winner_loser_comparison.csv` | 패널 × 7개 비교 × 진입 feature(+ lifecycle 지시변수), broad pooled 효과 대조 |
| `eligible_vs_filled_selection_effect.csv` | eligible, filled, skipped 비중·수익률·진입 연도 |
| `broad_vs_realistic_comparison.csv` | 지표별 실제형·broad 같은 윈도우·broad pooled 차이와 분류 |
| `broad_same_window_filter_attribution.csv` | broad 같은 윈도우 거래의 필터 귀속 |
| `group_counts.csv`, `feature_cache_join_coverage.csv`, `entry_vs_lifecycle_explanatory_power.csv` | 그룹 건수, 캐시 연결률, 설명력 비교 |
| `summary.json` | 게이트, 원본 SHA, 판정 규칙, 판정 세부, 경로 점검 |

재현 방법은 `python scripts/analyze_realistic_p2_winner_loser_lifecycle_v01.py`다. 같은 입력에서 SHA가 같은 산출물을 만든다.
