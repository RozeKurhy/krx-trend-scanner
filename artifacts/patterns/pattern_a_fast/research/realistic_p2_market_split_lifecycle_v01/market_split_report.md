# A FAST Core V2 — 현실적 P2 KOSPI/KOSDAQ 분리 Lifecycle V01

## 최종 판정: `INSUFFICIENT_EVIDENCE`

interaction 성격도 `INSUFFICIENT_EVIDENCE`다.

판정 규칙은 결과를 보기 전에 표본 수만 보고 고정했다. 이 판정은 KOSDAQ 쪽 표본이 부족해서 시장 간 강도를 비교할 수 없다는 뜻이며, 핵심 질문의 답은 분명하다.

- **KOSPI:** 4개 패널(P2-1/P2-2 × eligible/filled)이 모두 판정 가능하고, 모두 NORMAL이 coverage보다 유리하다(HOLDS).
- **KOSDAQ:** 1조 이상 universe에서 coverage 경로가 eligible 13·15건, filled 5·5건뿐이다. 요청서 기준(group n≥20)을 채우는 패널이 없어 방향만 서술한다(DESCRIPTIVE_ONLY).
  - eligible 두 패널은 모두 NORMAL 쪽이 유리하다.
- **시장 구성 효과:** NORMAL 우위는 KOSPI 비중 차이로 설명되지 않는다.
  - NORMAL과 coverage의 KOSPI 비중이 거의 같다(78~87% vs 81~86%).
  - 시장을 고정한 층화 차이가 원래 차이의 95~109%다.

새 백테스트, 전략 재평가, feature 재계산, 신규 feature, 임계값 변경, Candidate, 네트워크 호출은 모두 0건이다.

## 1. 입력과 검증

- 상위 현실적 P2 분석과 같은 eligible·filled 집합, 원장 `terminal_return`, lifecycle 분류를 썼다.
- 인증 headline 게이트를 다시 통과했다(eligible 355 / 485, filled 199 / 242).
- 패널마다 시장 합계가 전체와 같고 lifecycle 합계가 시장별 건수와 같은지 확인했다. `pair_id` 중복은 0건이다.
- 진입 feature는 ATR 서술에만 썼다. 상위 PIT 캐시를 재사용했으며 연결된 행은 불일치 0건이다.

**판정 규칙**
- **등급:** 양쪽 n≥20은 판정용(A), 10~19는 서술용(B), 10 미만은 참고만(C)이다.
- **패널 유리:** 평균, +50%, +100%, AUC-0.5 네 지표 중 3개 이상이 NORMAL 쪽이고 평균 차이가 양수다.
- **deep loss:** LOSS_30 10건 이상과 LOSS_50 5건 이상일 때만 일반화한다. 모든 패널이 이 조건을 채우지 못해 deep-loss는 건수·비율만 보고한다.

## 2. 시장 전체 성과 (lifecycle 분리 전)

| 패널 | 시장 | n | 비중 | 평균 | 중앙값 | 양수 | ≥+50% | ≥+100% | ≤-30/-40/-50/-60 건수 | 보유일 중앙 | OPEN | ATR 중앙 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|
| P2-1 eligible | KOSPI | 289 | 81.4% | +6.1 | -14.8 | 39.1 | 11.4 | 3.5 | 3/1/0/0 | 104 | 19.4 | 0.035 |
| | KOSDAQ | 66 | 18.6% | -2.6 | -15.1 | 25.8 | 7.6 | 1.5 | 5/1/0/0 | 65 | 12.1 | 0.048 |
| P2-1 filled | KOSPI | 168 | 84.4% | +5.3 | -15.0 | 38.1 | 9.5 | 4.8 | 2/1/0/0 | 96 | 20.2 | 0.034 |
| | KOSDAQ | 31 | 15.6% | -7.3 | -14.9 | 22.6 | 3.2 | 0.0 | 3/0/0/0 | 32 | 12.9 | 0.046 |
| P2-2 eligible | KOSPI | 390 | 80.4% | +18.0 | -14.6 | 38.7 | 21.5 | 9.5 | 4/3/2/0 | 110 | 8.2 | 0.036 |
| | KOSDAQ | 95 | 19.6% | +4.4 | -14.9 | 26.3 | 15.8 | 5.3 | 4/1/1/1 | 60 | 7.4 | 0.046 |
| P2-2 filled | KOSPI | 204 | 84.3% | +17.2 | -14.8 | 36.3 | 18.6 | 10.8 | 3/3/2/0 | 97 | 9.8 | 0.036 |
| | KOSDAQ | 38 | 15.7% | -0.3 | -14.7 | 23.7 | 13.2 | 0.0 | 3/0/0/0 | 45 | 10.5 | 0.045 |

수익률과 비율의 단위는 %다.

- **시장 효과가 크다.** KOSDAQ은 KOSPI보다 평균이 9~14pp 낮고, 양수 비율이 13~16pp 낮으며, ATR이 약 30% 높다.
- **LOSS_30 비율:** KOSDAQ 7.6%·4.2%, KOSPI 1.0%·1.0%(eligible 기준)이다.
- **NORMAL 비중:** P2-1은 28% vs 26%로 비슷하고, P2-2는 KOSDAQ이 오히려 높다(63% vs 55%).

## 3. KOSPI 안에서 NORMAL vs coverage

| 패널 | n N/C | 평균 N/C | 중앙값 N/C | ≥+50% N/C | ≥+100% N/C | ≤-30% N/C | AUC | 판정 |
|---|---|---|---|---|---|---|---:|---|
| P2-1 eligible | 81/56 | +24.8 / +11.4 | +12.2 / -6.8 | 21.0 / 16.1 | 9.9 / 3.6 | 0 / 5.4 | 0.574 | 유리 |
| P2-1 filled | 48/28 | +26.0 / +4.7 | +14.2 / -14.5 | 18.8 / 10.7 | 12.5 / 7.1 | 0 / 7.1 | 0.629 | 유리 |
| P2-2 eligible | 213/74 | +34.6 / +10.1 | +7.6 / -14.6 | 31.5 / 18.9 | 15.0 / 6.8 | 0.9 / 2.7 | 0.606 | 유리 |
| P2-2 filled | 113/32 | +34.8 / +4.4 | +5.6 / -14.4 | 28.3 / 12.5 | 16.8 / 9.4 | 1.8 / 3.1 | 0.612 | 유리 |

- **평균 차이:** +13.5 ~ +30.5pp다.
- **closed-only:** 평균 차이 +18.2 ~ +31.2pp, AUC 0.62~0.65로 유지된다.
- **deep loss:** KOSPI deep loss는 2~4건이라 일반화하지 않는다.

## 4. KOSDAQ 안에서 NORMAL vs coverage (서술용)

| 패널 | n N/C | 등급 | 평균 N/C | ≥+50% N/C | ≤-30% N/C | AUC |
|---|---|---|---|---|---|---:|
| P2-1 eligible | 17/13 | B | +29.3 / -19.2 | 29.4 / 0.0 | 0 / 30.8 | 0.846 |
| P2-1 filled | 7/5 | C | +17.1 / -22.5 | 14.3 / 0.0 | 0 / 40.0 | 0.829 |
| P2-2 eligible | 60/15 | B | +11.7 / +2.3 | 21.7 / 13.3 | 3.3 / 6.7 | 0.560 |
| P2-2 filled | 25/5 | C | +4.1 / +4.8 | 16.0 / 20.0 | 8.0 / 0.0 | 0.592 |

- **eligible:** 두 패널 모두 NORMAL 쪽이 유리하다. 다만 크기가 P2-1 +48pp, P2-2 +9pp로 크게 다르다.
- **filled P2-2:** coverage 5건이라 방향이 뒤집혀도(-0.7pp) 해석하지 않는다.
- **P2-1 KOSDAQ coverage:** -30% 이하 4건은 모두 SKIPPED 경로의 기간 종료일 미청산 보유다(상위 분석에서 확인).

## 5. 시장 효과와 lifecycle 효과 분리

**A. 시장 효과:** KOSPI 전체와 KOSDAQ 전체의 평균 차이는 P2-1 +8.7pp, P2-2 +13.7pp(eligible)다.

**B. lifecycle 효과:** 시장 안에서 NORMAL과 coverage의 평균 차이다.
- KOSPI: +13.5 / +24.5pp(eligible), +21.3 / +30.5pp(filled)
- KOSDAQ: +48.5 / +9.4pp(eligible, 서술용)

**C. 구성 효과 점검 (시장 층화):**

| 패널 | NORMAL 중 KOSPI | coverage 중 KOSPI | 평균 차이 원래 → 층화 | +50% 차이 원래 → 층화 | +100% 차이 원래 → 층화 |
|---|---:|---:|---|---|---|
| P2-1 eligible | 82.7% | 81.2% | +20.0 → +19.7 | +9.4 → +9.3 | +6.3 → +6.2 |
| P2-1 filled | 87.3% | 84.8% | +24.3 → +23.8 | +9.1 → +8.9 | +4.8 → +4.6 |
| P2-2 eligible | 78.0% | 83.1% | +20.8 → +21.4 | +11.3 → +11.7 | +6.4 → +6.6 |
| P2-2 filled | 81.9% | 86.5% | +24.8 → +25.1 | +12.6 → +12.4 | +5.7 → +6.2 |

- 두 그룹의 시장 구성이 거의 같다. 시장을 고정해도 차이가 그대로 남는다(비율 0.95~1.09).
- P2-2에서는 coverage 쪽 KOSPI 비중이 더 높다. 시장 구성이 오히려 coverage에 유리했는데도 NORMAL이 앞섰다.
- **interaction:** 규칙상 KOSDAQ이 판정용 등급을 채우지 못해 `INSUFFICIENT_EVIDENCE`다.
  - 서술적으로는 방향이 두 시장에서 같다. 강도는 KOSDAQ에서 P2-1과 P2-2가 엇갈려 정할 수 없다.

## 6. Broad universe와의 연결

broad 같은 윈도우(같은 기간·cutoff, n이 충분함)를 시장별로 나누면 NORMAL 우위가 두 시장 모두에서 뚜렷하다.

| broad 같은 윈도우 | n N/C | 평균 차이 | ≥+50% 차이 | ≤-30% 차이 | AUC |
|---|---|---:|---:|---:|---:|
| P2-1 KOSPI | 281/166 | +15.7 | +6.9 | -5.1 | 0.603 |
| P2-1 KOSDAQ | 332/157 | +23.1 | +16.7 | -7.7 | 0.671 |
| P2-2 KOSPI | 496/233 | +24.2 | +13.6 | -3.5 | 0.619 |
| P2-2 KOSDAQ | 573/241 | +20.0 | +13.1 | -6.6 | 0.633 |

- **broad에서는 lifecycle 효과가 시장과 무관하다.** 평균 차이가 두 시장 모두 +16~24pp다. deep-loss 격차는 KOSDAQ에서 더 크다(-7.7 / -6.6 vs -5.1 / -3.5pp).
- **현실적 KOSPI 결과는 broad KOSPI와 크기가 비슷하다.**
- **broad의 KOSDAQ loser 경향은 1조 이상에서도 같다.** 현실적 1조 이상 KOSDAQ의 LOSS_30 비율이 KOSPI의 4~8배다.

## 7. 질문별 답

1. **KOSPI 전체와 KOSDAQ 전체 성과는 얼마나 다른가?** KOSDAQ의 평균이 9~14pp 낮고, 양수 비율이 13~16pp 낮으며, LOSS_30 비율이 4~8배 높다. ATR도 약 30% 높다.
2. **KOSPI 안에서도 NORMAL 우위가 유지되는가?** 유지된다. 4개 패널 모두 판정 가능하고 모두 유리하며, 평균 차이는 +13~31pp, AUC는 0.57~0.63이다.
3. **KOSDAQ 안에서도 유지되는가?** eligible 두 패널 모두 방향은 유지되지만 coverage가 13·15건이라 판정용 표본이 아니다. broad KOSDAQ(n 150~570)에서는 뚜렷하게 유지된다.
4. **P2-1 / P2-2에서 방향이 반복되는가?** KOSPI는 반복된다. KOSDAQ eligible도 방향은 같지만 크기가 다르다(+48 vs +9pp).
5. **eligible / filled에서도 방향이 유지되는가?** KOSPI는 4개 모두 같은 방향이다. KOSDAQ filled는 coverage 5건이라 해석하지 않는다.
6. **NORMAL 우위를 KOSPI 비중 차이로 설명할 수 있는가?** 없다. 두 그룹의 KOSPI 비중이 거의 같고, 층화 차이가 원래 차이와 같다.
7. **어느 시장에서 lifecycle 효과가 더 강한가?** 1조 이상 universe에서는 판단할 수 없다. broad에서는 평균 차이가 비슷하고 deep-loss 격차는 KOSDAQ이 크다.
8. **KOSDAQ의 높은 변동성과 deep-loss 성향이 lifecycle 차이를 확대하는가?** broad에서는 deep-loss 쪽 격차를 확대한다. 1조 이상에서는 P2-1 KOSDAQ coverage의 30.8%가 -30% 이하였지만 4건이라 일반화하지 않는다.
9. **broad의 KOSDAQ loser 경향과 현실적 1조+ 결과가 일치하는가?** 일치한다. 1조 이상에서도 KOSDAQ의 LOSS_30 비율이 높고 평균이 낮다.
10. **coverage exit 연구를 시장 공통으로 할지, 시장별로 나눌지?** 공통 정책으로 연구하되 결과는 시장별로 나눠 보고하는 것이 맞다.
    - lifecycle 효과의 방향은 두 시장에서 같고, 시장 구성으로 설명되지 않는다.
    - 1조 이상 KOSDAQ의 coverage 표본(13~15건)으로는 별도 정책을 설계할 수 없다.
    - 다만 KOSDAQ은 deep-loss 성향이 강하다. coverage exit 효과는 KOSDAQ에서 더 크게 나타날 수 있으니 시장별 결과를 따로 확인할 가치가 있다.
    - 새 전략안은 만들지 않았다.

## 8. 해석 주의

- P2-1은 P2-2의 앞부분이고 filled는 eligible의 부분집합이다. 패널 간 일치는 독립 확인이 아니다.
- P2-1은 cutoff가 짧아 NEVER_PROGRESSED 비중이 크다.
- KOSDAQ 1조 이상 표본은 작다. 등급 B·C 수치는 방향 참고용이다.
- 상관을 인과로 단정하지 않는다. lifecycle은 진입 후 상태다.

## 산출물

| 파일 | 내용 |
|---|---|
| `market_overall_profile.csv` | 패널 × 시장(ALL 포함) 전체 성과, lifecycle 비중, ATR 중앙값 |
| `market_lifecycle_profile.csv` | 패널 × 시장 × lifecycle 그룹 지표(전체/closed-only) |
| `market_lifecycle_auc.csv` | 패널 × 시장 × 4개 lifecycle 비교(차이, AUC, 등급, 유리 여부) |
| `p2_1_market_split.csv`, `p2_2_market_split.csv` | 윈도우별 NORMAL vs coverage 요약 |
| `eligible_vs_filled_market_effect.csv` | 시장별 eligible·filled 비중·평균·lifecycle 차이 |
| `market_stratified_lifecycle_effect.csv` | 시장 층화 차이와 원래 차이 비교 |
| `broad_same_window_market_reference.csv` | broad 같은 윈도우의 시장별 참고값 |
| `market_split_summary.json` | 검증, 규칙, 판정 세부 |

재현 방법은 `python scripts/analyze_realistic_p2_winner_loser_lifecycle_v01.py market-split`이다. 같은 입력에서 SHA가 같은 산출물을 만든다.
