# A FAST Core V2 — 보유 중 Lifecycle 세분화 V01

## 요약

- **기존 `lifecycle_class`는 보유 lifecycle이 아니다.** 진입 신호 주간부터 윈도우 cutoff까지의 모든 월간 stage로 판정되므로 청산 이후 관찰이 섞인다.
  - pooled 원장 NORMAL 3,276건 중 **51.1%(1,674건)**는 보유 중 PROGRESSED에 한 번도 닿지 않았다. 대부분 -15% Loss Guard로 먼저 청산되었다.
  - 이 라벨로 한 이전 lifecycle 분석(winner/loser, lifecycle follow-up, 현실적 P2)의 NORMAL vs coverage 비교에는 청산 이후 경로가 섞여 있다. 이전 산출물은 수정하지 않았다.
- **보유 구간 기준에서도 NORMAL 우위가 남는다.**
  - 비교는 보유 중 PROGRESSED에 도달한 거래끼리 한다. 첫 PROGRESSED가 정상 handoff인 거래(A)와 직접 handoff가 한 번도 없는 거래(C1)다.
  - 단순 5개 윈도우 모두에서 A가 앞선다. 평균 +17~32pp, AUC 0.62~0.64이고, -30%·-50% 이하 비율도 낮다(deep-loss 일반화 가능 표본).
  - 현실적 eligible 3개 윈도우에서도 같은 방향이다(평균 +14~24pp, AUC 0.57~0.59).
- **LATE_NORMALIZED(B)는 수익이 가장 크지만 선택 효과가 강하다.** 첫 PROGRESSED 이후 직접 handoff까지 중앙 45개월, 보유 중앙 1,108일을 버틴 거래만 B가 된다.
- **handoff origin의 91%는 TRANSITION이다.** 순수 `TRANSITION → EARLY_TREND → PROGRESSED`가 다른 origin보다 특별히 우수하지는 않다. 같은 진입 stage 안에서 BASE origin이 오히려 높았다.

새 백테스트, 전략 변경, threshold 변경, 네트워크 호출은 모두 0건이다.

## 1. 방법과 검증

**월간 stage 복원**
- 대상: 8개 원장(단순 5개, 현실적 3개)에 나오는 identity 1,879개
- 경로: 러너와 같은 `build_historical_snapshot_from_context` → `evaluate_pattern_a`
- 범위: identity 시작부터 모든 월 라벨의 Pattern A stage를 복원했다(326,113행).
  - 일봉은 identity 시작 ~ 2026-09-01, 라벨은 2026-08-31까지다.
- 병렬 처리: 부모 프로세스가 일봉을 읽고 워커는 계산만 했다. 30개 identity로 단일 프로세스 결과와 바이트 단위로 같은지 확인했다.

**누수 점검:** 무작위 20개 (identity, 라벨)을 라벨의 관측일까지 자른 일봉으로 다시 계산했고 불일치는 0건이다.

**재현 게이트:** 복원한 경로로 시뮬레이터의 lifecycle 판정을 다시 돌려 원장의 `lifecycle_class`와 `first_progressed_date`를 재현했다.

| 패널 | 행 | 불일치 |
|---|---:|---:|
| 단순 P1 / P2-1 / P3-1 / P3-2 | 4,982 / 1,800 / 1,173 / 1,792 | 0 |
| 단순 P2-2 | 2,424 | 7 (0.29%, 이전 데이터 authority로 실행된 run) |
| 단순 pooled dedup | 5,380 | 4 |
| 현실적 P2-1 / P2-2 / P3-2 (eligible·filled) | 355·199 / 485·242 / 405·228 | 0 |

불일치 행은 해당 패널에서 뺐다.

**관측 기준**
- 진입 stage는 완료된 주간 신호 종가 시점의 Pattern A stage(`entry_pattern_a_stage`)이고, 체결은 다음 거래일 시가다.
- 월 라벨의 스냅샷은 라벨 이전 마지막 거래일 종가에 관측된다.
- **보유 구간:** 진입 이후 관측일이 청산 신호일 이하인 라벨이다. 정산 거래는 정산일, 미청산 거래는 윈도우 cutoff까지 본다.

**그룹 정의(결과 확인 전에 고정)**
- **A `FIRST_PROGRESSED_NORMAL`:** 보유 중 첫 PROGRESSED 직전 유효 stage가 EARLY_TREND다.
- **B `LATE_NORMALIZED`:** 첫 PROGRESSED는 직접 handoff가 아니지만 이후 보유 중 직접 handoff가 한 번 이상 있다.
- **C `NEVER_NORMALIZED_COVERAGE`:** 보유 중 직접 handoff가 없다.
  - C1: 보유 중 PROGRESSED에 도달했다.
  - C2: 보유 중 PROGRESSED에 도달하지 못했다(대부분 Loss Guard).
- A·B·C는 모든 패널에서 빠짐없이, 겹치지 않게 나뉘는 것을 확인했다.
- A∪B가 원장 NORMAL의 부분집합인지도 확인했다(위반 0건).

**표본 등급:** n≥20은 판정용, 10~19는 서술용, 10 미만은 건수만 본다. deep-loss 결론은 비교 쌍의 LOSS_30≥10과 LOSS_50≥5를 모두 채울 때만 낸다.

## 2. 원장 라벨 vs 보유 기준 (pooled dedup)

| 원장 `lifecycle_class` | A | B | C1 | C2 |
|---|---:|---:|---:|---:|
| NORMAL_EARLY_TREND_HANDOFF | 1,313 | 289 | 0 | **1,674** |
| SKIPPED_EARLY_TREND_HANDOFF | 0 | 0 | 139 | 145 |
| PROGRESSED_WITHOUT_DIRECT_HANDOFF | 0 | 0 | 235 | 504 |
| NEVER_PROGRESSED | 0 | 0 | 0 | 1,077 |

원장의 coverage 라벨(SKIPPED + WITHOUT_DIRECT) 1,023건 중 649건도 보유 중에는 PROGRESSED에 도달하지 못했다.

## 3. 보유 기준 그룹 성과 (pooled dedup)

| 그룹 | n | 평균 | 중앙값 | 양수 | ≥+50% | ≥+100% | ≤-30/-50/-60 건수 | 보유 중앙(거래일) | OPEN | MFE 중앙 | MAE 중앙 |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|
| A FIRST_PROGRESSED_NORMAL | 1,313 | +52.2 | +38.7 | 84.5 | 40.8 | 14.9 | 22/2/2 | 147 | 25 | 79.8 | -8.9 |
| B LATE_NORMALIZED | 289 | +94.6 | +72.2 | 88.9 | 64.4 | 38.4 | 11/5/1 | 1,108 | 7 | 146.9 | -29.5 |
| C NEVER_NORMALIZED_COVERAGE | 3,774 | -11.2 | -16.0 | 8.1 | 2.9 | 1.0 | 77/34/25 | 52 | 249 | 10.8 | -17.3 |
| └ C1 PROGRESSED 도달 | 374 | +31.6 | +18.8 | 63.9 | 27.3 | 10.4 | 58/32/25 | 231 | 155 | 66.2 | -13.7 |
| └ C2 PROGRESSED 미도달 | 3,400 | -15.9 | -16.1 | 2.0 | 0.2 | 0.0 | 19/2/0 | 45 | 94 | 9.1 | -17.3 |

- 수익률과 비율의 단위는 %다. 윈도우·현실적 패널별 값은 `holding_lifecycle_profile.csv`에 있다.
- **청산 사유:**
  - A는 Exit4가 대부분이다.
  - B는 Exit4 220건, Exit3 62건, 미청산 7건이다.
  - C1은 미청산(NO_EXIT_BEFORE_CUTOFF) 비중이 크다.
- **deep loss 집중:** -50% 이하 41건 중 32건, -60% 이하 28건 중 25건이 C1에 있다.

## 4. 비교와 반복성

| 비교 | 단순 P1 | P2-1 | P2-2 | P3-1 | P3-2 | pooled | 현실 P2-1 elig | P2-2 elig | P3-2 elig |
|---|---|---|---|---|---|---|---|---|---|
| A vs C1 평균 차이 / AUC | +20.5 / 0.63 | +17.1 / 0.62 | +21.5 / 0.62 | +22.8 / 0.62 | +32.2 / 0.63 | +20.7 / 0.64 | +14.2 / 0.57 | +19.7 / 0.57 | +23.6 / 0.59 |
| A vs C1 ≤-30% 차이(pp) | -14.8 | -10.6 | -11.5 | -8.4 | -9.0 | -13.8 | -14.3 | -6.2 | -4.5 |
| B vs C1 평균 차이 / AUC | +63.2 / 0.75 | +67.1 / 0.79 | +57.0 / 0.73 | (B n=4) | +57.9 / 0.72 | +63.0 / 0.75 | (B n=7) | +63.2 / 0.75 | +64.6 / 0.80 (서술용) |
| A vs B 평균 차이 | -42.7 | -49.9 | -35.5 | (B n=4) | -25.7 | -42.4 | (B n=7) | -43.5 | -41.0 (서술용) |

- **A vs C1:** 단순 5개 윈도우, pooled, 현실적 eligible 3개 모두 판정용 표본이고 7개 핵심 지표가 모두 A 쪽이다(현실적 P2-1·P3-2는 5승 0패, 나머지는 무승부).
  - deep-loss 차이는 단순 윈도우에서만 일반화 가능한 표본이다. 현실적 1조 이상 universe에는 deep loss가 거의 없다.
- **현실적 filled:** 같은 방향이다(A vs C1 AUC 0.61~0.64, 서술용).
- **윈도우 중첩:** 5개 윈도우와 현실적 3개 윈도우는 기간이 겹치므로 독립 반복이 아니다.

## 5. B(LATE_NORMALIZED) 진단 (서술만)

- **규모:** pooled 289건이다. 첫 PROGRESSED에서 직접 handoff까지 월 라벨 기준 중앙 45개월이고, 보유 중앙은 1,108거래일이다.
- **B가 되는 구조:** 동결 시뮬레이터에서 원장 NORMAL 거래는 첫 직접 handoff 시점부터 Exit3·Exit4가 켜진다. Loss Guard는 첫 PROGRESSED 이후 꺼진다.
  - 따라서 B 거래는 첫 PROGRESSED와 handoff 사이에 작동하는 청산 규칙이 없다.
  - 그 구간을 버틴 뒤 나중에 handoff가 관찰된 거래만 B가 된다.
- **해석:** B의 높은 수익률(평균 +94.6%)은 오래 살아남은 거래만 남는 선택 효과를 크게 포함한다. 진입이나 경로의 우수성으로 해석하지 않는다.

## 6. NORMAL handoff 직전 origin

**origin 분포:** A∪B의 handoff 직전 origin은 TRANSITION 1,465건(91%), BASE 88건, PROGRESSED 30건, WEAK 15건, OTHER 4건이다(pooled).

| origin (pooled, A∪B) | n | 평균 | 중앙값 | ≥+50% | ≥+100% |
|---|---:|---:|---:|---:|---:|
| TRANSITION (Pure Normal Cycle) | 1,465 | +58.3 | +42.6 | 44.5 | 18.6 |
| BASE | 88 | +76.2 | +58.7 | 55.7 | 25.0 |
| WEAK | 15 | +120.2 | +76.6 | 60.0 | 40.0 |
| PROGRESSED | 30 | +65.7 | +36.9 | 36.7 | 20.0 |
| WEAK·BASE·TRANSITION 합산 | 1,568 | +59.9 | +43.3 | 45.3 | 19.2 |
| 그 외(PROGRESSED·OTHER) | 34 | +59.7 | +35.0 | 35.3 | 17.6 |

- **진입 stage와의 관계:** TRANSITION 진입 거래는 origin이 거의 기계적으로 TRANSITION이 된다(1,228 / 1,322). 그래서 같은 진입 stage 안에서 비교했다.
- **TRANSITION 진입 안:** 순수 TRANSITION origin이 BASE origin보다 낮다. 평균 -24.4pp, AUC 0.41이며 P1·P2-2·pooled가 판정용이다.
  - BASE origin은 B(장기 생존 선택 그룹) 비중이 34%로 TRANSITION origin(16%)보다 높다.
  - 그래서 A 안에서만 다시 비교했다. TRANSITION 진입은 1,018건 vs 37건, 평균 +55.3% vs +73.0%, AUC 0.40이다. EARLY_TREND 진입은 216건 vs 21건, AUC 0.46이다.
  - BASE 쪽이 높은 방향은 A 안에서도 남는다. 다만 BASE 표본이 작고 인과로 해석하지 않는다.
- **EARLY_TREND 진입 안:** 차이가 섞인다(pooled AUC 0.49, P3-1·P3-2는 반대 방향이지만 건수만).
- **결론:** 순수 `TRANSITION → EARLY_TREND → PROGRESSED`가 특별히 우수하다는 근거는 없다. 현실적 패널은 TRANSITION 외 origin이 1~5건이라 건수만 본다.

## 7. 질문 1·2에 대한 답

1. **NORMAL 우위는 A에서 주로 나오는가, B에서도 유지되는가?**
   - 보유 기준에서는 두 그룹 모두 C1보다 앞선다. 단순 5개 윈도우와 현실적 eligible 3개 윈도우에서 반복된다.
   - 원장 NORMAL 3,276건 중 A는 1,313건, B는 289건이고, 절반 이상(1,674건)은 보유 중 PROGRESSED에 닿지 않은 거래였다.
   - 따라서 A가 우위의 본체다. B의 더 큰 수익은 장기 생존 선택 효과가 크다.
2. **`TRANSITION → EARLY_TREND → PROGRESSED`가 다른 origin보다 특별히 우수한가?** 아니다. 같은 진입 stage 안에서 비교하면 BASE origin이 오히려 높거나 차이가 섞인다.

상관을 인과로 단정하지 않는다. lifecycle은 진입 후에야 알 수 있는 상태다.

## 산출물

| 파일 | 내용 |
|---|---|
| `monthly_stage_cache.csv.gz`, `monthly_stage_cache_audit.json` | 월간 stage 복원 캐시, SHA, 누수 점검 |
| `replication_gate.csv` | 패널별 원장 lifecycle 재현 결과 |
| `trade_stage_paths.csv` | 거래별 보유 경로, 전체 경로(압축 표기), 그룹, origin, strict 분류 |
| `ledger_label_vs_holding_crosstab.csv` | 원장 라벨 × 보유 기준 그룹 |
| `holding_lifecycle_profile.csv`, `holding_lifecycle_comparison.csv` | 그룹별 지표와 A/B/C1 비교 |
| `handoff_origin_profile.csv`, `handoff_origin_comparison.csv`, `handoff_origin_by_entry_stage.csv` | origin별 지표, 같은 진입 stage 안 비교, 교차표 |
| `summary.json` | 게이트, 관측 기준, 규칙, B 진단, 반복성 |

재현 방법은 `python scripts/analyze_fastcore_v2_lifecycle_refinement_strict_handoff_v01.py stages` 다음 `analyze`다. `analyze`는 같은 캐시에서 SHA가 같은 산출물을 만든다.
