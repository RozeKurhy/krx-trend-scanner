# A FAST Core V2 — EARLY_TREND 진입 Strict Handoff V01

## 요약

- **표본:** pooled dedup에서 EARLY_TREND 진입 거래는 738건이다(전체 5,376건의 13.7%, 게이트 불일치 4건 제외).
  - STRICT PASS 199건, STRICT FAIL 316건, 다음 stage 없이 청산 또는 cutoff 223건이다.
- **PASS가 FAIL보다 뚜렷하게 좋다.** 평균 +33.2% vs +6.8%(+26.4pp), 중앙값 +19.4% vs -15.3%, 수익률 AUC 0.71이다.
  - 단순 5개 윈도우 모두 판정용 표본이고 같은 방향이다(AUC 0.67~0.72).
  - 현실적 eligible 3개 윈도우도 같은 방향이다(AUC 0.68~0.71, P2-2만 판정용이고 나머지는 서술용).
- **deep loss는 PASS 쪽이 적지 않다.** -30% 이하가 PASS 10건, FAIL 5건이고 -50% 이하는 1건씩이라 일반화하지 않는다. 차이는 winner 쪽에서 난다.
- **순수 `TRANSITION → EARLY_TREND [매수] → PROGRESSED`(165건)는 다른 origin의 PASS(34건)와 차이가 없다**(pooled AUC 0.51).
- **FAIL은 거의 전부 TRANSITION으로 먼저 이탈한 거래다**(300 / 316).

새 백테스트, 전략 변경, threshold 변경, 네트워크 호출은 모두 0건이다.

## 1. 관측 기준과 정의

**관측 기준**
- 대상은 원장 `entry_pattern_a_stage`가 EARLY_TREND인 CONTROL 거래다.
  - 이 값은 완료된 주간 신호 종가(`entry_signal_date`)에서 평가한 Pattern A stage다. 매수는 다음 거래일 시가에 체결된다.
- 진입 이후 stage는 월 라벨 스냅샷이다. 각 라벨은 그 이전 마지막 거래일 종가에 관측된다.
- 관측일이 청산 신호일(미청산은 윈도우 cutoff) 이하인 라벨만 보유 중 관측으로 쓴다.
- 진입 여부는 원장 그대로이며 미래 stage로 다시 정의하지 않았다.

**분류(결과 확인 전에 고정)**
- 보유 중 처음으로 EARLY_TREND가 아닌 유효 stage가 나오면 그 stage로 판정한다. UNAVAILABLE은 건너뛴다.
  - PROGRESSED면 `STRICT_PASS`, 그 외 stage면 `STRICT_FAIL`이다.
  - 나중에 다시 `EARLY_TREND → PROGRESSED`가 와도 FAIL은 바꾸지 않는다.
- 그런 stage 없이 청산되거나 cutoff에 닿으면 `NO_NEXT_STAGE_BEFORE_EXIT_OR_CUTOFF`다.
  - 대부분 -15% Loss Guard 청산이다(보유 중앙 19거래일, 평균 -17.1%).
  - PASS와 FAIL은 둘 다 첫 stage 변화까지 살아남은 거래다. 그래서 의미 있는 대비는 PASS vs FAIL이고 NO_NEXT는 따로 둔다.

**진입 전 origin:** 신호 주간 이전 월 라벨을 거꾸로 보며 EARLY_TREND와 UNAVAILABLE을 건너뛰고 첫 다른 stage를 origin으로 잡는다.
- 진입 직전 월 라벨의 stage가 EARLY_TREND인 비율은 55~62%다. 나머지는 주간 평가에서 먼저 EARLY_TREND로 바뀐 경우다.

## 2. 결과 (pooled dedup)

| 그룹 | n | 평균 | 중앙값 | 양수 | ≥+50% | ≥+100% | ≤-30/-50/-60 건수 | 보유 중앙(거래일) | OPEN | MFE 중앙 | MAE 중앙 |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|
| STRICT PASS | 199 | +33.2 | +19.4 | 72.4 | 30.7 | 10.1 | 10/1/1 | 105 | 2 | 54.7 | -10.6 |
| └ TRANSITION → ET [매수] → PROGRESSED | 165 | +32.6 | +20.7 | 72.7 | 30.3 | 10.3 | 8/1/1 | 105 | 2 | 54.7 | -10.3 |
| └ 그 외 origin PASS | 34 | +36.1 | +16.5 | 70.6 | 32.4 | 8.8 | 2/0/0 | 105 | 0 | 57.0 | -12.1 |
| STRICT FAIL | 316 | +6.8 | -15.3 | 28.5 | 13.9 | 5.1 | 5/1/1 | 115 | 14 | 22.8 | -16.7 |
| └ ET → TRANSITION 이탈 | 300 | +7.2 | -15.3 | 28.3 | 14.3 | 5.3 | 5/1/1 | 113 | 14 | 22.7 | -16.5 |
| NO_NEXT_STAGE | 223 | -17.1 | -16.3 | 0.0 | 0.0 | 0.0 | 3/0/0 | 19 | 0 | 5.9 | -17.8 |

- 수익률과 비율의 단위는 %다.
- PASS origin 구성: TRANSITION 165, BASE 17, PROGRESSED 8, WEAK 5, OTHER 4다.
- FAIL에서 BASE·WEAK로 이탈한 경우는 7·4건뿐이다.

## 3. 반복성 (PASS vs FAIL)

| 패널 | PASS / FAIL n | 평균 차이 | 중앙값 차이 | ≥+50% 차이 | ≥+100% 차이 | AUC | 등급 |
|---|---|---:|---:|---:|---:|---:|---|
| 단순 P1 | 176 / 280 | +29.6 | +35.5 | +20.2 | +6.7 | 0.723 | 판정용 |
| 단순 P2-1 | 74 / 99 | +26.0 | +30.2 | +20.3 | +7.1 | 0.683 | 판정용 |
| 단순 P2-2 | 95 / 125 | +21.2 | +31.1 | +13.8 | +6.0 | 0.667 | 판정용 |
| 단순 P3-1 | 28 / 66 | +37.0 | +62.3 | +39.4 | +13.3 | 0.712 | 판정용 |
| 단순 P3-2 | 49 / 91 | +23.6 | +34.5 | +22.3 | +3.5 | 0.677 | 판정용 |
| 단순 pooled | 199 / 316 | +26.4 | +34.7 | +16.7 | +5.0 | 0.710 | 판정용 |
| 현실 P2-1 eligible | 14 / 23 | +25.0 | +28.4 | +12.7 | +14.3 | 0.714 | 서술용 |
| 현실 P2-2 eligible | 25 / 26 | +23.3 | +30.2 | +8.9 | +16.0 | 0.688 | 판정용 |
| 현실 P3-2 eligible | 18 / 24 | +23.5 | +33.3 | +15.3 | +5.6 | 0.677 | 서술용 |
| 현실 filled (P2-1 / P2-2 / P3-2) | 8/17, 15/19, 9/19 | +40.0 / +21.0 / +16.7 | | | | 0.86 / 0.72 / 0.59 | 건수 / 서술 / 건수 |

- **방향:** 평균, 중앙값, +50%, +100% 차이가 모든 패널에서 PASS 쪽이다.
- **청산 구조:** PASS는 첫 stage 변화가 곧 직접 handoff라서 그 시점에 Loss Guard 구간이 끝나고 Exit3·Exit4로 넘어간다.
  - PASS 청산은 Exit4 75.9%, Exit3 23.1%다.
  - FAIL은 첫 변화 이후에도 PROGRESSED 전이면 -15% Loss Guard 아래에 남는다. FAIL 청산의 65.5%가 Loss Guard이고 중앙값이 -15.3%인 이유다.
  - 따라서 +26pp 차이에는 경로뿐 아니라 이 청산 규칙 차이가 함께 들어 있다.
- **deep loss:** -30% 이하 비율은 대부분 패널에서 PASS가 약간 높다(pooled +3.4pp). 비교 쌍의 LOSS_50이 5건 미만이라 deep-loss 결론은 내리지 않는다.
- **윈도우 중첩:** 5개 윈도우와 현실적 3개 윈도우는 기간이 겹친다. 반복은 독립 확인이 아니다.

**순수 entry cycle vs 다른 origin PASS**
- pooled는 평균 -3.5pp, AUC 0.51로 차이가 없다.
- P1은 판정용인데 AUC 0.49로 역시 차이가 없다.
- P2-1·P2-2·P3-2(서술용)와 현실적 패널(건수만)은 순수 cycle 쪽이 높게 나오지만 다른 origin 표본이 1~19건이다.

**민감도(청산 이후 관측 포함, 참고용):** cutoff까지 보면 PASS 243건(평균 +24.1%), FAIL 494건(평균 -1.8%)이다. 방향은 같다.

## 4. 질문 3·4에 대한 답

3. **EARLY_TREND 매수 뒤 다음 stage가 바로 PROGRESSED인 PASS가 FAIL보다 우수한가?**
   - 우수하다. 평균 +26pp, 중앙값 +35pp, +50% 비율 +17pp, AUC 0.71이다.
   - 차이는 winner 쪽에서 나며 deep-loss 차이는 확인되지 않는다.
   - 순수 `TRANSITION → EARLY_TREND → PROGRESSED`의 추가 우위는 없다.
4. **단순 5-window와 현실적 3-window에서 반복되는가?**
   - 반복된다. 단순 5개 윈도우와 pooled는 모두 판정용이고 AUC 0.67~0.72다.
   - 현실적 eligible 3개도 같은 방향이다(AUC 0.68~0.71, 1개 판정용·2개 서술용).
   - filled는 표본이 작아 방향 확인용이다.

## 5. 해석 주의

- PASS·FAIL은 진입 후 첫 stage 변화(월 라벨)에서 정해진다. 진입 시점에 알 수 있는 값이 아니므로 진입 필터로 쓸 수 없다.
- PASS는 정의상 첫 PROGRESSED가 직접 handoff인 거래(보유 기준 A)의 부분집합이다.
- 상관을 인과로 단정하지 않는다.

## 산출물

| 파일 | 내용 |
|---|---|
| `strict_entry_profile.csv` | 패널별 PASS, FAIL, NO_NEXT, origin별 PASS, FAIL 이탈 stage별 지표 |
| `strict_entry_comparison.csv` | PASS vs FAIL, 순수 cycle vs FAIL, 순수 cycle vs 다른 origin PASS |
| `strict_entry_sensitivity_through_cutoff.csv` | 청산 이후 관측을 포함한 민감도(참고용) |
| `trade_stage_paths.csv` | 거래별 strict 분류, 진입 origin, 보유 경로 |
| `summary.json` | 패널별 EARLY_TREND 진입 수, strict·origin 건수, 진입 직전 월 stage 일치율 |
