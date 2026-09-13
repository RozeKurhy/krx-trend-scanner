# FASTCORE V1 PRE-WINNER FAILURE ARMED MATCHED-ENTRY A/B V00 결과 보고서

## 결론

고정된 V0 CONTROL 973개 entry를 다시 스캔하지 않고 독립 replay했다. V0 disabled parity가 거래별로 통과한 뒤, pre-winner FAILURE ARMED의 가격 임계값만 -25%와 -30%로 달리한 두 diagnostic variant를 비교했다. 자동 winner 선정은 하지 않는다.

- V0 parity: PASS (973/973, entry date/open·terminal return·holding·exit reason·status 일치)
- Q1 FAST state domain/count: {"EXTENDED": 13858, "SETUP": 61410, "TREND": 11190, "TRIGGER": 12637, "UNAVAILABLE": 1348, "WATCH": 41247}
- TRIGGER는 WEAK가 아니라 STRONG/RECOVERED다. ARM/confirm에는 쓰지 않고, 새 usable FAST date의 ARMED trade를 disarm한다.
- 네트워크 요청: 0; production 변경: 없음; label signal input: 없음.

## Q3–Q4. 설계와 V0 baseline

V0 Winner Mode는 daily HIGH HWM/MFE를 먼저 갱신하고, MFE 20% 이상에서만 V0의 tier별 soft/hard trailing exit을 동일하게 적용했다. Pre-winner에는 고정 hard failure를 두지 않았고, 약한 weekly FAST와 종가 가격손상이 함께 발생하면 ARM만 한다. 확정은 ARM 이후 엄격히 새로운 usable weekly FAST date에서만 가능하며, 실제 청산은 항상 다음 identity-scoped local OPEN이다.

V0 replay baseline: 973 trades, positive 690/973 (70.914697%), mean 8.666341%, median 9.200000%, mean holding 292.540596 days.

## Q2–Q4. Variant·TRIGGER mechanism·수익률

- FASTCORE_V1_W25_PREWINNER_ARMED_V00 (-25%): positive 58.581706%, mean 5.225725% (V0 paired delta -3.440617pp), median 5.920000%, improved/worsened/same 144/184/645, confirmed/executed/unexecuted 328/328/0.
  - STRONG disarm Q2: TRIGGER 0, TREND 0, EXTENDED 0; price/fast/both 219/0/0; armed→Winner 0.
  - Q8 tail delta vs V0 (<=-30/-40/-50/-60): -55/-106/-71/-39; Q9 V0 terminal >=50/>=100 pre-winner exits: 5/4, V0 MFE >=50/>=100 pre-winner exits: 32/8.
- FASTCORE_V1_W30_PREWINNER_ARMED_V00 (-30%): positive 61.562179%, mean 5.535725% (V0 paired delta -3.130617pp), median 7.170000%, improved/worsened/same 123/154/696, confirmed/executed/unexecuted 277/277/0.
  - STRONG disarm Q2: TRIGGER 0, TREND 0, EXTENDED 0; price/fast/both 186/0/0; armed→Winner 0.
  - Q8 tail delta vs V0 (<=-30/-40/-50/-60): 116/-103/-71/-39; Q9 V0 terminal >=50/>=100 pre-winner exits: 5/4, V0 MFE >=50/>=100 pre-winner exits: 25/8.

ARM 자체는 매도가 아니며, 같은 weekly FAST date가 daily bars에서 반복되어도 확정되지 않는다. 새 weak FAST와 가격손상 유지가 확인될 때만 FAILURE_CONFIRMED EOD signal이 발생한다. 가격 회복, FAST 회복, 둘 다 회복, UNAVAILABLE 대기는 event log로 분리했다. MFE 20% 도달일에는 armed 상태를 해제하고 같은 날부터 V0 Winner Mode를 적용했다.

## Q5–Q7. RECOVERY, NEVER_WINNER, Loss Guard

RECOVERY/NEVER_WINNER와 과거 Loss Guard 표시는 FIX03 artifact에서 사후 진단용으로만 join했다. 이 label들은 entry/arm/confirm/exit 판단에 사용하지 않았다.

- FASTCORE_V1_W25_PREWINNER_ARMED_V00 / RECOVERY: n=737, armed 152, confirmed/executed 136/136, recovery preempted 136.0, NEVER captured nan, mean delta -8.610706pp, holding reduction 76.507463 days.
- FASTCORE_V1_W25_PREWINNER_ARMED_V00 / NEVER_WINNER: n=236, armed 199, confirmed/executed 192/192, recovery preempted nan, NEVER captured 192.0, mean delta 12.704958pp, holding reduction 432.351695 days.
- FASTCORE_V1_W25_PREWINNER_ARMED_V00 / LOSS_GUARD_RECOVERY: n=387, armed 141, confirmed/executed 125/125, recovery preempted 125.0, NEVER captured nan, mean delta -15.430698pp, holding reduction 131.160207 days.
- FASTCORE_V1_W25_PREWINNER_ARMED_V00 / LOSS_GUARD_NEVER_WINNER: n=203, armed 184, confirmed/executed 177/177, recovery preempted nan, NEVER captured 177.0, mean delta 13.425025pp, holding reduction 446.783251 days.
- FASTCORE_V1_W30_PREWINNER_ARMED_V00 / RECOVERY: n=737, armed 118, confirmed/executed 105/105, recovery preempted 105.0, NEVER captured nan, mean delta -7.437761pp, holding reduction 63.439620 days.
- FASTCORE_V1_W30_PREWINNER_ARMED_V00 / NEVER_WINNER: n=236, armed 179, confirmed/executed 172/172, recovery preempted nan, NEVER captured 172.0, mean delta 10.320085pp, holding reduction 393.864407 days.
- FASTCORE_V1_W30_PREWINNER_ARMED_V00 / LOSS_GUARD_RECOVERY: n=387, armed 109, confirmed/executed 96/96, recovery preempted 96.0, NEVER captured nan, mean delta -13.319302pp, holding reduction 107.390181 days.
- FASTCORE_V1_W30_PREWINNER_ARMED_V00 / LOSS_GUARD_NEVER_WINNER: n=203, armed 164, confirmed/executed 157/157, recovery preempted nan, NEVER captured 157.0, mean delta 10.885468pp, holding reduction 404.798030 days.

## Q10–Q11. 전이 시간, 종료 경계, 결론

마지막 identity daily date 또는 support end에서 확정되어 다음 local OPEN이 없으면, 신호는 EXIT_UNEXECUTED로 기록하고 가짜 체결을 만들지 않았다. 기존 V0/V3/FIX01/FIX03 artifact는 읽기만 했으며 이 작업의 새 artifact 7개만 생성했다.
Variant summary에는 arm→confirm, arm→disarm, arm→Winner의 calendar-day mean/median을 기록한다. W25/W30 평가는 positive-rate 보존, mean return, RECOVERY preemption, NEVER capture, deep-loss tail, large-winner preservation, holding을 함께 보고 trade-off 여부로 결론 낸다.
Q11 결론: 둘 다 부적합. W25/W30 모두 V0 positive rate 70.914697%와 mean return 8.666341%를 크게 훼손했고, RECOVERY preemption이 높다. W25는 일부 deep-loss tail을 줄였지만 대가가 크며, W30은 <=-30 tail도 악화했다. 다음 V1-W candidate로 자동 채택하지 않는다.

### Exit reason 요약

- FASTCORE_V1_W25_PREWINNER_ARMED_V00 / HARD_EXIT: 169 trades, mean return 40.996982%.
- FASTCORE_V1_W25_PREWINNER_ARMED_V00 / OPEN_AT_CUTOFF: 47 trades, mean return -4.817660%.
- FASTCORE_V1_W25_PREWINNER_ARMED_V00 / PREWINNER_FAILURE_CONFIRMED: 328 trades, mean return -28.482195%.
- FASTCORE_V1_W25_PREWINNER_ARMED_V00 / SOFT_EXIT: 429 trades, mean return 18.006364%.
- FASTCORE_V1_W30_PREWINNER_ARMED_V00 / HARD_EXIT: 181 trades, mean return 39.021326%.
- FASTCORE_V1_W30_PREWINNER_ARMED_V00 / OPEN_AT_CUTOFF: 67 trades, mean return -9.242985%.
- FASTCORE_V1_W30_PREWINNER_ARMED_V00 / PREWINNER_FAILURE_CONFIRMED: 277 trades, mean return -32.751119%.
- FASTCORE_V1_W30_PREWINNER_ARMED_V00 / SOFT_EXIT: 448 trades, mean return 17.890045%.
