# A FAST Core V2 — A vs C1 Divergence V01

## 판정: 갈라지는 지점은 첫 PROGRESSED 이탈이다

- **첫 PROGRESSED 시점에 이미 차이가 있다.** 도달까지 걸린 기간은 비슷하다(96 vs 107거래일). 그러나 C1은 도달 시점 수익률이 낮다(중앙 +17.6% vs A +40.6%, AUC 0.69).
- **본격적인 분기는 첫 PROGRESSED 이탈에서 생긴다.**
  - A는 이탈 라벨에서 바로 Exit3로 청산된다(이탈 후 보유 0일).
  - C1은 coverage 계약상 Exit3가 없어 이탈 후에도 보유가 이어진다(중앙 1,090거래일).
- **C1 deep loss는 거의 전부 이 구간에서 생긴다.**
  - C1의 -50% 이하 32건과 -60% 이하 25건은 모두 PROGRESSED를 이탈한 뒤 cutoff까지 미청산으로 남은 거래다.
  - 이탈한 C1 140건 중 56건(40%)이 -30% 이하로 끝났다. 이탈하지 않은 C1 233건 중에서는 2건뿐이다.
- **후퇴 stage 중 WEAK가 가장 강하게 갈라진다.** C1 winner(≥+50%)의 7%, deep loser(≤-30%)의 97%가 이탈 후 WEAK를 거쳤다. -50% 도달의 80%(41 / 51)가 WEAK 상태에서 일어났다.
- **반복성:** 단순 5개 윈도우와 현실적 eligible 3개 윈도우에서 방향이 같다. 현실적 1조 이상 universe에는 deep loss 자체가 적다(C1 -30% 이하 2~6건).
- **다음 단계:** exit/hold 정책 연구로 넘어갈 **근거 있음**. 새 규칙은 제안하지 않는다.

새 백테스트, 청산 규칙 구현, threshold sweep, 네트워크 호출은 모두 0건이다. 원장 `lifecycle_class`(윈도우 lifecycle)는 그룹 정의에 쓰지 않았다.

## 1. 방법과 검증

**그룹:** 보유 lifecycle 기준이다(`holding_lifecycle_class`, 진입 ~ 청산 신호일, 미청산은 cutoff).
- **A `FIRST_PROGRESSED_NORMAL`:** 보유 중 첫 PROGRESSED 직전 유효 stage가 EARLY_TREND다.
- **C1:** 보유 중 PROGRESSED에 도달했지만 직접 `EARLY_TREND → PROGRESSED`가 없다.
- C2(PROGRESSED 미도달)는 비교하지 않는다.

**anchor와 가격 경로**
- anchor는 보유 중 첫 PROGRESSED 월 라벨이고, 라벨 이전 마지막 거래일 종가에 관측된다.
- 가격은 Repository V2 수정주가 일봉이다. 보유 창은 러너의 `_refresh_outcome_metrics`와 같다(청산 거래는 [진입, 청산 체결일) + 청산 시가, 미청산은 cutoff까지).
- 손실 임계(-15 / -20 / -30 / -40 / -50 / -60%) 도달은 Loss Guard와 같은 종가 기준이다.

**검증**

| 항목 | 결과 |
|---|---|
| stage 캐시 누수 점검 | 20 / 20 일치(상위 분석) |
| 원장 lifecycle 재현 | P2-2 7행 외 불일치 0(상위 분석), 불일치 행 제외 |
| 가격 parity: 원장 MFE·MAE·terminal 재현(±0.011pp) | 불일치 단순 P1 6, P2-1 1, P2-2 2, P3-1 1, P3-2 1, pooled 2행(모두 0.5% 미만), 현실적 0 → 패널 제외 없음, 불일치 행만 제외 |
| anchor = 원장 `first_progressed_date` | 모든 패널 100% |
| 보유 종료 이후 stage 사용 | 0(코드에서 차단) |
| A·C1 겹침, 거래 identity 중복 | 0 |
| 수동 점검 | 무작위 12건(`manual_audit_sample.csv`), 경로와 청산 사유가 계약과 일치 |

**표본 등급:** 양쪽 n≥20은 판정용, 10~19는 서술용, 10 미만은 `INSUFFICIENT_EVIDENCE`로 둔다. 윈도우는 서로 겹치므로 반복은 독립 확인이 아니다.

## 2. A vs C1 (pooled dedup, A 1,312 / C1 373)

### 첫 PROGRESSED 이전과 그 시점

| 지표 | A 중앙 | C1 중앙 | AUC(A>C1) |
|---|---:|---:|---:|
| 진입 → 첫 PROGRESSED(거래일) | 96 | 107 | 0.46 |
| 첫 PROGRESSED 시점 수익률 | +40.6% | +17.6% | **0.69** |
| 첫 PROGRESSED 이전 MFE | +70.0% | +48.8% | 0.65 |
| 첫 PROGRESSED 이전 MAE | -7.6% | -9.2% | 0.57 |
| 이전 stage 전이 수 | 1 | 2 | 0.45 |
| Pattern A 점수 변화(진입 직전 월 → anchor) | -2.8 | +13.0 | 0.38 |
| FAST 점수(진입) | 77.4 | 76.9 | 0.52 |

- C1의 첫 PROGRESSED 직전 stage는 TRANSITION(96.5%)이고 A는 정의상 EARLY_TREND다.
- C1은 anchor까지 가격 상승이 작은데 Pattern A 점수는 크게 뛰어 PROGRESSED에 들어간다.

### 첫 PROGRESSED 이후

| 지표 | A | C1 |
|---|---:|---:|
| 이후 PROGRESSED 이탈 비율 | 19.5% | 37.5% |
| 이탈 후 청산까지 거래일(중앙, 이탈 거래) | 0 | 1,090 |
| 이탈 후 PROGRESSED 복귀 | 0% | 19.8% |
| 이후 WEAK / BASE / TRANSITION 관측 | 4.3 / 0.5 / 13.3% | 30.6 / 28.7 / 35.9% |
| 이후 MAE 중앙 | +17.0% | -7.3% (AUC 0.70) |
| 최종 수익률 중앙 | +38.6% | +19.2% (AUC 0.64) |
| OPEN_AT_CUTOFF | 1.8% | 41.3% |

- **A의 청산:** 80%가 이탈 전에 PROGRESSED 안에서 Exit4(점수 -15pt)로 끝난다(1,032건). 이탈한 256건은 전부 이탈 라벨에서 Exit3로 청산된다.
- **C1의 청산:** 이탈하지 않은 233건은 219건이 Exit4로 끝나고 평균 +47.7%다. 이탈한 140건은 전부 미청산이다.

## 3. C1 extreme loss

| 임계 | 전체 deep loss(보유 기준) | 그중 C1 | 그중 A | C1 중 이탈 후 보유 거래 | C1 OPEN_AT_CUTOFF |
|---|---:|---:|---:|---:|---:|
| ≤-30% | 110 | 58 | 22 | 56 | 56 |
| ≤-40% | 67 | 47 | 10 | 47 | 47 |
| ≤-50% | 41 | 32 | 2 | 32 | 32 |
| ≤-60% | 28 | 25 | 2 | 25 | 25 |

**반복되는 이벤트 시퀀스(≤-50% 32건)**

`ENTRY[TRANSITION] → PROG(작은 상승, 중앙 +2%) → DEPART:TRANSITION(22건, WEAK 7, BASE 2, EARLY_TREND 1) → 22건 RE-PROG → -30% 도달 → WEAK 체류 중 -50% 도달 → OPEN_AT_CUTOFF`

- 이탈 시점 수익률은 중앙 -9%다.
- 이탈부터 -30% 도달까지 중앙 208거래일, -50% 도달까지 중앙 472거래일이 걸렸다.
- 거래별 시퀀스는 `c1_extreme_loss_event_sequences.csv`에 있다.

**임계 도달 시점 stage(C1)**
- -30%는 93건이 닿았고, 그중 76건이 이탈 후였다. 당시 stage는 WEAK 42, PROGRESSED 22, TRANSITION 17, BASE 12다.
- -50%는 51건 중 49건이 이탈 후였고, 당시 stage는 WEAK 41이다.
- -30%에 닿은 C1의 52%(48 / 93)는 이후 손익분기로 회복했다. 우측 꼬리가 겹친다는 뜻이다.

**A의 deep loss는 성격이 다르다.**
- A의 임계 도달은 전부 PROGRESSED 안에서 일어났다(-30% 41건 모두).
- 이탈 없이 PROGRESSED 안에서 급락한 뒤 Exit4·Exit3로 청산됐다. -50% 이하는 2건이다.

## 4. C1 winner vs deep loser (pooled, ≥+50% 102 vs ≤-30% 58, 판정용)

| 지표 | winner | deep loser | AUC / 차이 |
|---|---:|---:|---:|
| 첫 PROGRESSED 시점 수익률(중앙) | +41.7% | +4.1% | AUC 0.87 |
| 첫 PROGRESSED 이전 MFE | +73.9% | +46.3% | 0.73 |
| 진입 → 첫 PROGRESSED(거래일) | 135 | 98 | 0.68 |
| PROGRESSED 이탈 | 13.7% | 96.6% | -83pp |
| 첫 이탈 stage TRANSITION / WEAK / BASE | 12.7 / 1.0 / 0% | 69.0 / 17.2 / 8.6% | |
| 이후 WEAK 관측 | 6.9% | 96.6% | **-90pp** |
| 이후 BASE 관측 | 8.8% | 86.2% | -77pp |
| 이후 TRANSITION 관측 | 13.7% | 89.7% | -76pp |
| PROGRESSED 복귀 | 8.8% | 60.3% | -52pp |
| 이탈 시점 수익률(중앙, 이탈 거래) | +22.1% (n=14) | -9.2% (n=56) | 0.78 |
| KOSDAQ | 49.0% | 63.8% | -15pp |
| OPEN_AT_CUTOFF | 18.6% | 96.6% | |

- 이 표의 이후 지표(MFE·MAE·보유·WEAK 관측 등)는 결과 그룹 정의와 겹치는 사후 값이다. 설명용이다.
- 진입·anchor 시점에 알 수 있는 값 중에서는 **첫 PROGRESSED 시점 수익률**이 가장 크게 갈렸다.

## 5. 반복성 (A vs C1 AUC, A 쪽이 클수록 >0.5)

| 패널 | 등급 | anchor 수익률 | 이후 MAE | 최종 수익률 | C1 이탈 후 ≤-30% / 비이탈 ≤-30% |
|---|---|---:|---:|---:|---|
| 단순 P1 | 판정용 | 0.69 | 0.70 | 0.63 | 53/127, 2/210 |
| 단순 P2-1 | 판정용 | 0.69 | 0.71 | 0.62 | 19/67, 2/110 |
| 단순 P2-2 | 판정용 | 0.68 | 0.68 | 0.62 | 28/79, 2/149 |
| 단순 P3-1 | 판정용 | 0.72 | 0.69 | 0.62 | 8/36, 1/50 |
| 단순 P3-2 | 판정용 | 0.69 | 0.68 | 0.63 | 15/51, 2/99 |
| 단순 pooled | 판정용 | 0.69 | 0.70 | 0.64 | 56/140, 2/233 |
| 현실 P2-1 eligible | 판정용 | 0.70 | 0.74 | 0.57 | 5/19, 1/23 |
| 현실 P2-2 eligible | 판정용 | 0.66 | 0.68 | 0.57 | 2/11, 1/32 |
| 현실 P3-2 eligible | 판정용 | 0.70 | 0.69 | 0.59 | 1/8, 1/29 |
| 현실 filled(참고) | 서술용 | 0.66~0.77 | 0.67~0.81 | 0.61~0.64 | 1~3/5~8, 0/9~13 |

- 모든 패널에서 A가 anchor 수익률, 이후 MAE, 최종 수익률 모두 높다.
- 모든 패널에서 C1의 deep loss는 이탈 후 보유 거래에 몰려 있다. 현실적 패널은 deep loss 건수가 1~5건이라 방향만 본다.

## 6. 질문별 답

1. **A와 C1은 first PROGRESSED 이전부터 다른가?** 가격 상승 폭은 다르다(anchor 수익률 AUC 0.69, 이전 MFE 0.65). 도달 기간과 이전 MAE·낙폭은 비슷하다(AUC 0.46~0.57).
2. **first PROGRESSED 시점 성과는 비슷한가?** 비슷하지 않다. A 중앙 +40.6%, C1 +17.6%이며, C1 deep loser는 +4.1%에 그친다.
3. **차이가 본격적으로 벌어지는 첫 post-PROGRESSED event는?** 첫 PROGRESSED 이탈이다(C1은 주로 TRANSITION으로 이탈).
   - 이 시점에 A는 Exit3로 청산되고 C1은 보유가 이어진다.
   - 이는 동결 계약의 청산 규칙 차이(coverage 경로에 Exit3 없음)와 정확히 겹친다.
4. **C1 extreme loser에서 반복되는 stage transition이 있는가?** 있다. PROGRESSED → TRANSITION(또는 WEAK·BASE) 이탈 → 흔히 PROGRESSED 재진입 → WEAK 체류 중 -50% 도달 → cutoff 미청산이다. 32건 모두 이탈 후 보유 거래다.
5. **C1 winner는 deep loser와 무엇이 다른가?** winner는 대부분 이탈 전에 PROGRESSED 안에서 Exit4로 청산된다(이탈 13.7%). 또 anchor 시점에 이미 크게 올라 있었다(+41.7% vs +4.1%).
6. **WEAK·BASE·TRANSITION 중 설명력이 가장 큰 후퇴 상태는?**
   - WEAK다. C1 winner 7% vs loser 97%(-90pp)이고, -50% 도달의 80%가 WEAK 상태였다.
   - 첫 이탈 stage로는 TRANSITION이 가장 흔하지만, TRANSITION 이탈 104건 중 13건은 +50% 이상 winner였다.
7. **loss threshold 전에 공통 warning signal이 있는가?**
   - PROGRESSED 이탈이 -30% 도달의 82%, -50% 도달의 96%보다 먼저 일어났다. 이탈부터 -30%까지 중앙 208거래일, -50%까지 472거래일이 걸렸다.
   - 다만 오경보도 있다. 이탈한 C1의 10%(14 / 140)는 +50% 이상 winner였고, -30%에 닿은 C1의 52%는 손익분기로 회복했다.
8. **simple / realistic에서 같은 방향으로 반복되는가?** 반복된다. 단순 5개와 현실적 eligible 3개 모두 방향이 같다. 현실적 패널은 deep loss 건수가 적어 방향 확인 수준이다.
9. **exit/hold 정책 연구를 진행할 근거가 있는가?** 근거 있음.

## 7. 해석

- **강한 차이:**
  - C1 deep loss가 이탈 후 보유 구간에 몰려 있다(-50% 이하 32 / 32).
  - 이탈 여부와 WEAK 관측으로 C1 winner와 loser가 갈린다.
  - 이 구조가 모든 패널에서 반복된다.
- **selection·confounding 가능:**
  - A와 C1은 anchor 시점에 이미 가격 상승이 다르다.
  - 이탈 후 결과 차이에는 청산 규칙 차이(A는 Exit3 청산)가 기계적으로 들어 있다. 경로 자체의 차이와 분리되지 않는다.
  - 이후 지표는 결과와 동시에 관찰되는 사후 값이다.
  - 우측 꼬리가 겹친다(이탈 C1 winner 14건, -30% 도달 후 회복 48건). 이는 기존 V2 문서의 PROGRESSED 하락 방어 보류 사유와 같은 성격이다.
- **아직 불충분:**
  - 현실적 1조 이상 universe의 C1 deep loss는 건수가 너무 적다.
  - FAST 점수는 진입 시점 값만 있어 anchor 시점 비교를 하지 못했다.
  - 이탈 후 청산을 했다면 어땠을지는 반사실 계산이라 하지 않았다.

## 산출물

| 파일 | 내용 |
|---|---|
| `a_vs_c1_trade_level.csv` | 거래별 anchor·이탈·임계 도달·경로·이벤트 시퀀스 |
| `first_progressed_anchor_metrics.csv` | anchor 시점 지표 |
| `a_vs_c1_comparison.csv` | 패널별 A vs C1 비교(AUC·중앙·비율) |
| `c1_winner_vs_loser_comparison.csv` | C1 winner vs deep loser(≥+50 vs ≤-30, ≥+100 vs ≤-50) |
| `c1_extreme_loss_event_sequences.csv` | C1 ≤-30% 거래의 요약 이벤트 시퀀스와 임계별 상태 |
| `loss_threshold_touch_summary.csv` | 그룹·임계별 도달 건수, 시점, stage, 회복 여부 |
| `first_departure_outcomes.csv` | 첫 이탈 stage별 결과 |
| `window_level_summary.csv`, `summary.json` | 패널별 요약, 게이트, deep loss 집중도 |
| `manual_audit_sample.csv` | 수동 점검 표본 |

재현 방법은 `python scripts/analyze_fastcore_v2_a_vs_c1_divergence_v01.py`다. 같은 입력에서 CSV SHA가 같다.
