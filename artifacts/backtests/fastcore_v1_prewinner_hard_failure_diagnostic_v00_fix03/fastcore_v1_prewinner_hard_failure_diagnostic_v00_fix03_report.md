# FASTCORE V1 PRE-WINNER HARD FAILURE DIAGNOSTIC V00 FIX03

## FIX03 핵심 질문에 대한 숫자 답

### Q1. lifecycle boundary correction으로 execution이 실제로 바뀌었는가?

- CONTROL trade 0건, threshold-trade row 0건이 변경됐어. breach 관측과 next OPEN 탐색을 모두 동일한 identity-scoped daily path에서 수행했어.

### Q2. threshold별 changed execution은 어디에 발생했는가?

- execution 변화가 있는 threshold: 없음. threshold sweep 수치 변화가 있는 구간: 없음. 상세 count는 아래 FIX02 → FIX03 비교표와 JSON에 기록했어.

### Q3. RECOVERY/NEVER_WINNER와 Loss Guard 분류가 바뀌었는가?

- RECOVERY delta +0, NEVER_WINNER delta +0, Loss Guard RECOVERY delta +0, Loss Guard NEVER_WINNER delta +0야.

### Q4. -30% 핵심 지표는 어떻게 변했는가?

- recovery kill 16.010855% → 16.010855%, failure capture 75.847458% → 75.847458%, positive rate 60.226105% → 60.226105%, mean 5.261881% → 5.261881%, median 6.570000% → 6.570000%, mean holding 140.441932d → 140.441932d야.

### Q5. fixed Hard Failure 결론은 변했는가?

- **유지**. `hard_failure_threshold_identified=false`, candidate `None`, V0 mean 개선 fixed threshold 0개야.

### Q6. FAILURE ARMED 참고 영역은 유지하는가?

- **유지**. `-25~-30%`는 Hard Exit나 strategy parameter가 아닌 FAILURE ARMED price-damage 연구 참고 영역으로만 남겨.



## 보조 분포 및 threshold 진단

### Q1. RECOVERY는 +20% 전 어디까지 하락했는가?

- 전체 973건 중 RECOVERY는 **737건**이야.
- CLOSE — ALL_973 RECOVERY: p10 -39.377086%, p25 -21.054524%, median -10.739191%, p75 -3.659775%, p90 0.546448%, worst -81.120000%, mean -15.161884%.
- LOW — ALL_973 RECOVERY: p10 -40.711286%, p25 -22.996512%, median -12.427410%, p75 -5.501841%, p90 -1.785714%, worst -81.560000%, mean -16.891987%.
- Loss Guard 590건 중 RECOVERY 387건: CLOSE — LOSS_GUARD_590 RECOVERY: p10 -47.060552%, p25 -32.401549%, median -20.223325%, p75 -10.787108%, p90 -2.101076%, worst -76.279070%, mean -22.735266%.
- Loss Guard RECOVERY LOW — LOSS_GUARD_590 RECOVERY: p10 -48.196159%, p25 -33.139236%, median -21.465428%, p75 -12.251092%, p90 -3.909149%, worst -76.558140%, mean -24.195214%.

### Q2. NEVER_WINNER는 어디까지 하락했는가?

- 전체 973건 중 NEVER_WINNER는 **236건**이야.
- CLOSE — ALL_973 NEVER_WINNER: p10 -74.118515%, p25 -60.757216%, median -46.663824%, p75 -30.547127%, p90 -18.900116%, worst -99.931436%, mean -46.622350%.
- LOW — ALL_973 NEVER_WINNER: p10 -75.271228%, p25 -61.948004%, median -48.487329%, p75 -32.846332%, p90 -20.322380%, worst -99.934354%, mean -47.906485%.
- Loss Guard 590건 중 NEVER_WINNER 203건: CLOSE — LOSS_GUARD_590 NEVER_WINNER: p10 -75.221314%, p25 -61.407054%, median -48.146067%, p75 -33.902043%, p90 -25.226220%, worst -99.931436%, mean -49.066967%.
- Loss Guard NEVER_WINNER LOW — LOSS_GUARD_590 NEVER_WINNER: p10 -76.174147%, p25 -62.542991%, median -49.705882%, p75 -34.991245%, p90 -26.419404%, worst -99.934354%, mean -50.332649%.

### Q3. 두 분포가 가장 크게 갈라지는 구간

- 전체 close bin에서 `-20% to > -25%`는 RECOVERY/NEVER_WINNER 56/10, `-25% to > -30%`는 35/20, `-30% to > -35%`는 23/17건이야.
- Loss Guard close bin에서는 같은 구간이 각각 55/9, 33/20, 23/17건이야.
- 따라서 분포 분리는 -20%~-30%부터 눈에 띄게 커지고, -60% 이하에서는 NEVER_WINNER가 지배적이지만 그 깊은 threshold는 recovery 보호와 failure capture를 함께 크게 잃어 고정 기준선 확정에는 부적합해.

분포 percentile 요약은 아래 CSV에 전체 stat(min/p05/p10/p25/median/p75/p90/p95/max/mean)으로 저장했어. 대표적으로 전체 CLOSE median은 RECOVERY **-10.739191%**, NEVER_WINNER **-46.663824%**이고, Loss Guard CLOSE median은 각각 **-20.223325%**, **-48.146067%**야.

#### 5% CLOSE bins — ALL_973

| bin | total n/rate | recovery n/rate | never n/rate | recovery within bin |
|---|---:|---:|---:|---:|
| > -10% | 360/36.998972% | 349/35.868448% | 11/1.130524% | 96.944444% |
| -10% to > -15% | 98/10.071942% | 93/9.558068% | 5/0.513875% | 94.897959% |
| -15% to > -20% | 91/9.352518% | 80/8.221994% | 11/1.130524% | 87.912088% |
| -20% to > -25% | 66/6.783145% | 56/5.755396% | 10/1.027749% | 84.848485% |
| -25% to > -30% | 55/5.652621% | 35/3.597122% | 20/2.055498% | 63.636364% |
| -30% to > -35% | 40/4.110997% | 23/2.363823% | 17/1.747174% | 57.500000% |
| -35% to > -40% | 41/4.213772% | 25/2.569373% | 16/1.644399% | 60.975610% |
| -40% to > -45% | 42/4.316547% | 19/1.952724% | 23/2.363823% | 45.238095% |
| -45% to > -50% | 34/3.494347% | 18/1.849949% | 16/1.644399% | 52.941176% |
| -50% to > -55% | 33/3.391572% | 13/1.336074% | 20/2.055498% | 39.393939% |
| -55% to > -60% | 31/3.186023% | 7/0.719424% | 24/2.466598% | 22.580645% |
| <= -60% | 76/7.810894% | 13/1.336074% | 63/6.474820% | 17.105263% |

#### 5% CLOSE bins — LOSS_GUARD_590

| bin | total n/rate | recovery n/rate | never n/rate | recovery within bin |
|---|---:|---:|---:|---:|
| > -10% | 93/15.762712% | 93/15.762712% | 0/0.000000% | 100.000000% |
| -10% to > -15% | 19/3.220339% | 19/3.220339% | 0/0.000000% | 100.000000% |
| -15% to > -20% | 84/14.237288% | 74/12.542373% | 10/1.694915% | 88.095238% |
| -20% to > -25% | 64/10.847458% | 55/9.322034% | 9/1.525424% | 85.937500% |
| -25% to > -30% | 53/8.983051% | 33/5.593220% | 20/3.389831% | 62.264151% |
| -30% to > -35% | 40/6.779661% | 23/3.898305% | 17/2.881356% | 57.500000% |
| -35% to > -40% | 38/6.440678% | 23/3.898305% | 15/2.542373% | 60.526316% |
| -40% to > -45% | 41/6.949153% | 18/3.050847% | 23/3.898305% | 43.902439% |
| -45% to > -50% | 28/4.745763% | 16/2.711864% | 12/2.033898% | 57.142857% |
| -50% to > -55% | 32/5.423729% | 12/2.033898% | 20/3.389831% | 37.500000% |
| -55% to > -60% | 26/4.406780% | 6/1.016949% | 20/3.389831% | 23.076923% |
| <= -60% | 68/11.525424% | 11/1.864407% | 57/9.661017% | 16.176471% |

### Q4. threshold별 recovery kill / failure capture

- -15%: ALL RECOVERY kill 289/39.213026%, ALL NEVER_WINNER capture 220/93.220339%; Loss Guard RECOVERY 271/70.025840%, Loss Guard NEVER_WINNER 203/100.000000%
- -20%: ALL RECOVERY kill 208/28.222524%, ALL NEVER_WINNER capture 209/88.559322%; Loss Guard RECOVERY 196/50.645995%, Loss Guard NEVER_WINNER 193/95.073892%
- -25%: ALL RECOVERY kill 153/20.759837%, ALL NEVER_WINNER capture 199/84.322034%; Loss Guard RECOVERY 142/36.692506%, Loss Guard NEVER_WINNER 184/90.640394%
- -30%: ALL RECOVERY kill 118/16.010855%, ALL NEVER_WINNER capture 179/75.847458%; Loss Guard RECOVERY 109/28.165375%, Loss Guard NEVER_WINNER 164/80.788177%
- -35%: ALL RECOVERY kill 95/12.890095%, ALL NEVER_WINNER capture 162/68.644068%; Loss Guard RECOVERY 86/22.222222%, Loss Guard NEVER_WINNER 147/72.413793%
- -40%: ALL RECOVERY kill 70/9.497965%, ALL NEVER_WINNER capture 146/61.864407%; Loss Guard RECOVERY 63/16.279070%, Loss Guard NEVER_WINNER 132/65.024631%

### Q5. threshold 적용 시 원래 V0 대비 aggregate

V0 baseline: positive rate **70.914697%**, mean **8.666341%**, median **9.200000%**, mean holding **292.540596d**.

| threshold | recovery killed | failed captured | positive n/rate | mean | median | +20/+30/+50/+100 n | -20/-30/-40/-50/-60 n | mean hold | Δ mean vs V0 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| -15% | 289/39.213026% | 220/93.220339% | 423/43.473792% | 2.373546% | -13.160000% | 157/84/32/15 | 23/1/1/0/0 | 71.910586d | -6.292795% |
| -20% | 208/28.222524% | 209/88.559322% | 497/51.079137% | 3.275087% | 1.350000% | 184/98/36/17 | 314/2/1/0/0 | 97.659815d | -5.391254% |
| -25% | 153/20.759837% | 199/84.322034% | 551/56.628983% | 4.123607% | 5.420000% | 207/110/42/18 | 353/18/2/0/0 | 120.416238d | -4.542734% |
| -30% | 118/16.010855% | 179/75.847458% | 586/60.226105% | 5.261881% | 6.570000% | 217/116/45/20 | 307/251/4/1/1 | 140.441932d | -3.404460% |
| -35% | 95/12.890095% | 162/68.644068% | 609/62.589928% | 5.243381% | 7.380000% | 225/117/45/20 | 276/260/9/2/1 | 163.959918d | -3.422960% |
| -40% | 70/9.497965% | 146/61.864407% | 631/64.850976% | 6.073720% | 7.790000% | 232/124/47/22 | 248/226/180/3/1 | 186.182939d | -2.592621% |
| -45% | 51/6.919946% | 123/52.118644% | 649/66.700925% | 6.817975% | 8.270000% | 240/129/49/24 | 226/198/180/8/1 | 208.811922d | -1.848366% |
| -50% | 33/4.477612% | 107/45.338983% | 663/68.139774% | 7.230719% | 8.560000% | 241/129/49/24 | 208/179/155/122/1 | 228.007194d | -1.435622% |
| -55% | 20/2.713704% | 87/36.864407% | 674/69.270298% | 7.680606% | 8.840000% | 242/129/49/24 | 194/162/135/109/5 | 245.533402d | -0.985735% |
| -60% | 13/1.763908% | 63/26.694915% | 680/69.886948% | 8.050946% | 9.070000% | 243/130/49/24 | 186/152/125/91/71 | 264.453237d | -0.615395% |

### Q6. 단일 Pre-Winner Hard Failure 기준선을 정할 수 있는가?

**현재 데이터만으로는 NO.** 단일 고정 Pre-Winner Hard Failure 기준선은 아직 확인되지 않았다. -30%는 전체 RECOVERY 118건/16.010855%를 제거하고, Loss Guard RECOVERY에서는 109건/28.165375%를 제거한다. -30% hypothetical positive rate는 60.226105%, mean return은 5.261881%이고, V0는 positive rate 70.914697%, mean 8.666341%다. 테스트한 fixed threshold 10개 중 V0 mean을 개선한 것은 0개다. 따라서 -30%를 Hard Failure candidate로 채택하지 않는다. -25~-30%는 즉시 Hard Exit 기준이 아니라 향후 FAILURE ARMED 설계에서 가격 훼손 영역으로 참고할 가치가 있을 뿐이며, 이번 FIX에서는 어떤 신규 threshold도 전략 parameter로 확정하지 않는다.

### 실제 next local OPEN impact

아래는 breach 후 next local trading day OPEN이 실제로 존재한 행만 집계한 값이야. `Δ mean`은 해당 next OPEN exit return에서 원래 V0 terminal return을 뺀 평균이고, V0 MFE도 함께 표시했어.

| threshold | cohort | executable n | next OPEN return mean | median | Δ mean vs V0 | original V0 MFE mean |
|---:|---|---:|---:|---:|---:|---:|
| -15% | RECOVERY | 289 | -16.051142% | -15.730000% | -39.145606% | 56.179931% |
| -15% | NEVER_WINNER | 220 | -16.294864% | -15.925000% | 23.591773% | 8.685182% |
| -20% | RECOVERY | 208 | -21.061250% | -20.860000% | -45.523413% | 60.119231% |
| -20% | NEVER_WINNER | 209 | -21.249378% | -20.880000% | 20.206603% | 8.693062% |
| -25% | RECOVERY | 153 | -26.191503% | -25.850000% | -50.272353% | 61.073464% |
| -25% | NEVER_WINNER | 199 | -26.466332% | -26.080000% | 16.440151% | 8.527286% |
| -30% | RECOVERY | 118 | -31.497373% | -31.025000% | -50.304576% | 52.366017% |
| -30% | NEVER_WINNER | 179 | -31.351006% | -30.910000% | 14.655866% | 8.593966% |
| -35% | RECOVERY | 95 | -36.229263% | -36.050000% | -55.878316% | 55.642211% |
| -35% | NEVER_WINNER | 162 | -36.392531% | -36.080000% | 12.209259% | 8.714259% |
| -40% | RECOVERY | 70 | -40.843571% | -40.665000% | -56.319429% | 48.284000% |
| -40% | NEVER_WINNER | 146 | -41.301644% | -40.750000% | 9.724247% | 8.789110% |
| -45% | RECOVERY | 51 | -46.308235% | -45.650000% | -55.968235% | 38.965098% |
| -45% | NEVER_WINNER | 123 | -46.286260% | -45.900000% | 8.584715% | 8.695691% |
| -50% | RECOVERY | 33 | -51.214545% | -50.660000% | -61.852727% | 41.308485% |
| -50% | NEVER_WINNER | 107 | -51.190561% | -50.690000% | 6.021308% | 8.626729% |
| -55% | RECOVERY | 20 | -56.046000% | -56.050000% | -68.580000% | 47.011500% |
| -55% | NEVER_WINNER | 87 | -56.195172% | -55.930000% | 4.741149% | 8.547011% |
| -60% | RECOVERY | 13 | -60.883077% | -60.670000% | -73.551538% | 51.450000% |
| -60% | NEVER_WINNER | 63 | -61.161587% | -60.920000% | 5.672857% | 9.287619% |

## FIX02 → FIX03 lifecycle execution boundary correction impact

threshold breach는 기존처럼 identity lifecycle 안에서 관측하고, 이제 next local OPEN도 같은 identity-scoped daily path에서만 탐색해. 따라서 `identity_effective_to`와 `SUPPORT_END` 중 먼저 종료되는 경계를 넘는 execution은 허용하지 않아.

- lifecycle boundary correction으로 execution이 변경된 CONTROL trade: 0건 (0 threshold-trade row)
- RECOVERY classification delta: +0, NEVER_WINNER delta: +0; classification 자체 변경: 0건
- Loss Guard RECOVERY: 387 → 387 (delta +0), Loss Guard NEVER_WINNER: 203 → 203 (delta +0)
- -30% RECOVERY kill: 118 → 118 (16.010855% → 16.010855%); failure capture: 179 → 179 (75.847458% → 75.847458%)
- -30% positive rate: 60.226105% → 60.226105%; mean: 5.261881% → 5.261881%; median: 6.570000% → 6.570000%; mean holding: 140.441932d → 140.441932d
- fixed threshold mean improvement count: 0 → 0

#### threshold별 changed execution count

| threshold | changed execution | RECOVERY | NEVER_WINNER |
|---:|---:|---:|---:|
| -15% | 0 | 0 | 0 |
| -20% | 0 | 0 | 0 |
| -25% | 0 | 0 | 0 |
| -30% | 0 | 0 | 0 |
| -35% | 0 | 0 | 0 |
| -40% | 0 | 0 | 0 |
| -45% | 0 | 0 | 0 |
| -50% | 0 | 0 | 0 |
| -55% | 0 | 0 | 0 |
| -60% | 0 | 0 | 0 |

#### 실제 changed execution record

- 변경된 execution record 없음.

| threshold | recovery killed FIX02 → FIX03 | failure captured FIX02 → FIX03 | positive rate FIX02 → FIX03 | mean FIX02 → FIX03 | median FIX02 → FIX03 | mean holding delta |
|---:|---:|---:|---:|---:|---:|---:|
| -15% | 289 → 289 | 220 → 220 | 43.473792% → 43.473792% | 2.373546% → 2.373546% | -13.160000% → -13.160000% | 0.000000d |
| -20% | 208 → 208 | 209 → 209 | 51.079137% → 51.079137% | 3.275087% → 3.275087% | 1.350000% → 1.350000% | 0.000000d |
| -25% | 153 → 153 | 199 → 199 | 56.628983% → 56.628983% | 4.123607% → 4.123607% | 5.420000% → 5.420000% | 0.000000d |
| -30% | 118 → 118 | 179 → 179 | 60.226105% → 60.226105% | 5.261881% → 5.261881% | 6.570000% → 6.570000% | 0.000000d |
| -35% | 95 → 95 | 162 → 162 | 62.589928% → 62.589928% | 5.243381% → 5.243381% | 7.380000% → 7.380000% | 0.000000d |
| -40% | 70 → 70 | 146 → 146 | 64.850976% → 64.850976% | 6.073720% → 6.073720% | 7.790000% → 7.790000% | 0.000000d |
| -45% | 51 → 51 | 123 → 123 | 66.700925% → 66.700925% | 6.817975% → 6.817975% | 8.270000% → 8.270000% | 0.000000d |
| -50% | 33 → 33 | 107 → 107 | 68.139774% → 68.139774% | 7.230719% → 7.230719% | 8.560000% → 8.560000% | 0.000000d |
| -55% | 20 → 20 | 87 → 87 | 69.270298% → 69.270298% | 7.680606% → 7.680606% | 8.840000% → 8.840000% | 0.000000d |
| -60% | 13 → 13 | 63 → 63 | 69.886948% → 69.886948% | 8.050946% → 8.050946% | 9.070000% → 9.070000% | 0.000000d |

Threshold별 changed execution count와 실제 changed record는 summary JSON에 기록했어. 이번 lifecycle correction은 계산 결과를 바꿀 수 있으므로 V00/FIX01/FIX02 artifact를 덮어쓰지 않고 별도 경로에 저장했어.

## 정의 및 look-ahead 제한

- 권위 source는 FIX01 matched-entry artifact의 973건이야. 기존 V0/FIX01/FIX02 결과를 전략적으로 변경하지 않았어.
- RECOVERY/NEVER_WINNER는 V0 path의 미래 MFE를 사용한 retrospective label이야. signal logic이나 진입 logic에 사용하지 않았어.
- running MFE는 daily HIGH로 갱신하고, 첫 HIGH가 entry OPEN 대비 +20% 이상이 된 당일은 Pre-Winner 관측에서 제외했어. same-day ordering을 지켰어.
- Hard Failure 후보 기준은 HWM drawdown이 아니라 `entry execution OPEN 대비 daily CLOSE return`이야.
- threshold breach는 EOD signal 후보, 체결은 동일 identity lifecycle 안의 next local trading day OPEN이야. daily LOW는 보조 분포일 뿐 trigger 기준이 아니야. 관측과 execution support는 `SUPPORT_END=2026-08-21` 및 `identity_effective_to` 중 먼저 닫히는 경계를 넘지 않아.
- daily FAST 생성, 주간 FAST→일간 전환, V1 rule 구현은 하지 않았어.

## Loss Guard 590 subset

- 전체 Loss Guard: `590건`
- RECOVERY: `387건`, NEVER_WINNER: `203건`
- RECOVERY V0 mean return: `19.509845%`
- NEVER_WINNER V0 mean return: `-39.556650%`
- Loss Guard subset의 상세 percentile, 5% bins, threshold별 impact는 각 CSV와 JSON에 기록했어.

## 산출물

- `prewinner_trade_diagnostics.csv`
- `prewinner_drawdown_distribution.csv`
- `prewinner_threshold_sweep.csv`
- `prewinner_threshold_trade_impacts.csv`
- `prewinner_hard_failure_summary.json`
- `fastcore_v1_prewinner_hard_failure_diagnostic_v00_fix03_report.md`

상세 산출물 절대 경로: `/Users/june/Documents/projects/krx-trend-scanner/artifacts/backtests/fastcore_v1_prewinner_hard_failure_diagnostic_v00_fix03`

## 실행 및 보호 범위

- 실행 명령: `./.venv/bin/python scripts/analyze_fastcore_v1_prewinner_hard_failure_diagnostic_v00.py --run-fix03`
- 기존 V0/FIX01/FIX02 artifact overwrite: 없음
- 기존 V3 1,578 trade 재생성: 없음
- Production strategy 수정: 없음
- Julia/portfolio: 실행하지 않음
- 외부 API/network: `0`
- 전체 repository pytest: 실행하지 않음
