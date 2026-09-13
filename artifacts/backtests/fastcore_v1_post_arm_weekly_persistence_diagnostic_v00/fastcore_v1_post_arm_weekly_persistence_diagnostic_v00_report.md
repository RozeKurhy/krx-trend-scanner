# FASTCORE V1 POST-ARM WEEKLY PERSISTENCE DIAGNOSTIC V00 결과 보고서

- Work ID: `FASTCORE_V1_POST_ARM_WEEKLY_PERSISTENCE_DIAGNOSTIC_V00`
- Status: `COMPLETE`
- Analysis: `FIRST_ARM_ONLY`; primary trades `648`
- Period: `2021-04-01` to signal cutoff `2026-08-14`, support end `2026-08-21`, final valuation `2026-08-21 CLOSE`
- Weekly semantics: `COMPLETED_WEEKLY_FAST_INCLUDING_UNAVAILABLE`
- First MFE20 semantics: `RAW_RUNNING_MFE_GE_20`

## Scope and invariants

이번 결과는 FIRST ARM 이후 completed weekly FAST observation의 시간축 persistence를 보는 descriptive diagnostic이다. RECOVERY/NEVER_WINNER label은 cohort grouping과 pre-winner censoring에만 사용했고, 가격·FAST metric 계산은 label-independent하게 수행했다.

- Variant counts: `{"FASTCORE_V1_W25_PREWINNER_ARMED_V00": 351, "FASTCORE_V1_W30_PREWINNER_ARMED_V00": 297}`
- Recovery counts: `{"FASTCORE_V1_W25_PREWINNER_ARMED_V00": {"NEVER_WINNER": 199, "RECOVERY": 152}, "FASTCORE_V1_W30_PREWINNER_ARMED_V00": {"NEVER_WINNER": 179, "RECOVERY": 118}}`
- FIRST ARM source row duplication: `0`
- Unknown FAST state count: `0`
- Weekly evaluation errors: `0`
- Primary MFE20 parity: `648/648/mismatch 0`

## Censoring by checkpoint

분포의 denominator는 `eligible == true`다. 모든 648 × 6 조합은 observation artifact에 남겼고, 아래는 variant/cohort/checkpoint별 eligible/censored 수다.

| variant | checkpoint | cohort | total | eligible | censored | reason counts |
|---|---|---|---:|---:|---:|---|
| FASTCORE_V1_W25_PREWINNER_ARMED_V00 | WEEK_1 | NEVER_WINNER | 199 | 198 | 1 | `{"NONE": 198, "NO_COMPLETED_WEEKLY_OBSERVATION": 1}` |
| FASTCORE_V1_W25_PREWINNER_ARMED_V00 | WEEK_1 | RECOVERY | 152 | 151 | 1 | `{"NONE": 151, "RECOVERY_ALREADY_REACHED_MFE20": 1}` |
| FASTCORE_V1_W25_PREWINNER_ARMED_V00 | WEEK_2 | NEVER_WINNER | 199 | 198 | 1 | `{"NONE": 198, "NO_COMPLETED_WEEKLY_OBSERVATION": 1}` |
| FASTCORE_V1_W25_PREWINNER_ARMED_V00 | WEEK_2 | RECOVERY | 152 | 151 | 1 | `{"NONE": 151, "RECOVERY_ALREADY_REACHED_MFE20": 1}` |
| FASTCORE_V1_W25_PREWINNER_ARMED_V00 | WEEK_3 | NEVER_WINNER | 199 | 198 | 1 | `{"NONE": 198, "NO_COMPLETED_WEEKLY_OBSERVATION": 1}` |
| FASTCORE_V1_W25_PREWINNER_ARMED_V00 | WEEK_3 | RECOVERY | 152 | 151 | 1 | `{"NONE": 151, "RECOVERY_ALREADY_REACHED_MFE20": 1}` |
| FASTCORE_V1_W25_PREWINNER_ARMED_V00 | WEEK_4 | NEVER_WINNER | 199 | 196 | 3 | `{"NONE": 196, "NO_COMPLETED_WEEKLY_OBSERVATION": 3}` |
| FASTCORE_V1_W25_PREWINNER_ARMED_V00 | WEEK_4 | RECOVERY | 152 | 151 | 1 | `{"NONE": 151, "RECOVERY_ALREADY_REACHED_MFE20": 1}` |
| FASTCORE_V1_W25_PREWINNER_ARMED_V00 | WEEK_6 | NEVER_WINNER | 199 | 195 | 4 | `{"NONE": 195, "NO_COMPLETED_WEEKLY_OBSERVATION": 4}` |
| FASTCORE_V1_W25_PREWINNER_ARMED_V00 | WEEK_6 | RECOVERY | 152 | 148 | 4 | `{"NONE": 148, "RECOVERY_ALREADY_REACHED_MFE20": 4}` |
| FASTCORE_V1_W25_PREWINNER_ARMED_V00 | WEEK_8 | NEVER_WINNER | 199 | 179 | 20 | `{"NONE": 179, "NO_COMPLETED_WEEKLY_OBSERVATION": 20}` |
| FASTCORE_V1_W25_PREWINNER_ARMED_V00 | WEEK_8 | RECOVERY | 152 | 145 | 7 | `{"NONE": 145, "RECOVERY_ALREADY_REACHED_MFE20": 7}` |
| FASTCORE_V1_W30_PREWINNER_ARMED_V00 | WEEK_1 | NEVER_WINNER | 179 | 179 | 0 | `{"NONE": 179}` |
| FASTCORE_V1_W30_PREWINNER_ARMED_V00 | WEEK_1 | RECOVERY | 118 | 117 | 1 | `{"NONE": 117, "RECOVERY_ALREADY_REACHED_MFE20": 1}` |
| FASTCORE_V1_W30_PREWINNER_ARMED_V00 | WEEK_2 | NEVER_WINNER | 179 | 179 | 0 | `{"NONE": 179}` |
| FASTCORE_V1_W30_PREWINNER_ARMED_V00 | WEEK_2 | RECOVERY | 118 | 117 | 1 | `{"NONE": 117, "RECOVERY_ALREADY_REACHED_MFE20": 1}` |
| FASTCORE_V1_W30_PREWINNER_ARMED_V00 | WEEK_3 | NEVER_WINNER | 179 | 179 | 0 | `{"NONE": 179}` |
| FASTCORE_V1_W30_PREWINNER_ARMED_V00 | WEEK_3 | RECOVERY | 118 | 117 | 1 | `{"NONE": 117, "RECOVERY_ALREADY_REACHED_MFE20": 1}` |
| FASTCORE_V1_W30_PREWINNER_ARMED_V00 | WEEK_4 | NEVER_WINNER | 179 | 175 | 4 | `{"NONE": 175, "NO_COMPLETED_WEEKLY_OBSERVATION": 4}` |
| FASTCORE_V1_W30_PREWINNER_ARMED_V00 | WEEK_4 | RECOVERY | 118 | 117 | 1 | `{"NONE": 117, "RECOVERY_ALREADY_REACHED_MFE20": 1}` |
| FASTCORE_V1_W30_PREWINNER_ARMED_V00 | WEEK_6 | NEVER_WINNER | 179 | 170 | 9 | `{"NONE": 170, "NO_COMPLETED_WEEKLY_OBSERVATION": 9}` |
| FASTCORE_V1_W30_PREWINNER_ARMED_V00 | WEEK_6 | RECOVERY | 118 | 116 | 2 | `{"NONE": 116, "RECOVERY_ALREADY_REACHED_MFE20": 2}` |
| FASTCORE_V1_W30_PREWINNER_ARMED_V00 | WEEK_8 | NEVER_WINNER | 179 | 160 | 19 | `{"NONE": 160, "NO_COMPLETED_WEEKLY_OBSERVATION": 19}` |
| FASTCORE_V1_W30_PREWINNER_ARMED_V00 | WEEK_8 | RECOVERY | 118 | 113 | 5 | `{"NONE": 113, "RECOVERY_ALREADY_REACHED_MFE20": 5}` |

## Price path distributions

ARM close return을 anchor로 한 current CLOSE 변화와 ARM 이후 running-min CLOSE deterioration이다. 값은 pp다.

### FASTCORE_V1_W25_PREWINNER_ARMED_V00

| checkpoint | cohort | eligible | close Δ pp mean/median [p25,p75] | running close deterioration pp mean/median [p25,p75] |
|---|---|---:|---:|---:|
| WEEK_1 | RECOVERY | 151 | 0.90 / 0.60 [-1.91, 3.35] | 1.76 / 0.54 [0.00, 2.75] |
| WEEK_1 | NEVER_WINNER | 198 | 0.86 / 0.64 [-1.69, 3.21] | 1.73 / 0.54 [0.00, 2.95] |
| WEEK_2 | RECOVERY | 151 | 2.16 / 1.25 [-2.23, 6.32] | 2.98 / 1.41 [0.00, 4.69] |
| WEEK_2 | NEVER_WINNER | 198 | 1.31 / 1.45 [-2.36, 4.76] | 2.70 / 1.74 [0.00, 4.66] |
| WEEK_3 | RECOVERY | 151 | 2.75 / 1.86 [-2.63, 6.78] | 3.75 / 2.24 [0.00, 6.22] |
| WEEK_3 | NEVER_WINNER | 198 | 0.89 / 0.63 [-3.12, 4.81] | 3.66 / 2.83 [0.00, 5.87] |
| WEEK_4 | RECOVERY | 151 | 3.01 / 2.27 [-2.70, 7.16] | 4.06 / 2.55 [0.00, 6.70] |
| WEEK_4 | NEVER_WINNER | 196 | 0.88 / 0.03 [-3.60, 5.73] | 4.41 / 3.47 [0.29, 7.26] |
| WEEK_6 | RECOVERY | 148 | 2.46 / 2.40 [-3.37, 6.98] | 5.00 / 3.62 [0.55, 7.82] |
| WEEK_6 | NEVER_WINNER | 195 | 0.46 / 1.00 [-3.88, 5.00] | 5.70 / 4.61 [0.40, 8.28] |
| WEEK_8 | RECOVERY | 145 | 1.80 / 0.56 [-4.55, 7.57] | 5.76 / 4.21 [0.78, 10.33] |
| WEEK_8 | NEVER_WINNER | 179 | 0.16 / -0.73 [-6.13, 5.23] | 6.76 / 5.36 [1.89, 9.71] |

### FASTCORE_V1_W30_PREWINNER_ARMED_V00

| checkpoint | cohort | eligible | close Δ pp mean/median [p25,p75] | running close deterioration pp mean/median [p25,p75] |
|---|---|---:|---:|---:|
| WEEK_1 | RECOVERY | 117 | 1.00 / 0.44 [-1.18, 2.98] | 1.44 / 0.68 [0.00, 2.30] |
| WEEK_1 | NEVER_WINNER | 179 | 1.19 / 0.73 [-0.84, 3.30] | 1.28 / 0.04 [0.00, 2.10] |
| WEEK_2 | RECOVERY | 117 | 1.38 / 1.34 [-1.89, 5.03] | 2.77 / 1.60 [0.00, 4.39] |
| WEEK_2 | NEVER_WINNER | 179 | 1.43 / 1.17 [-1.84, 4.06] | 2.24 / 1.34 [0.00, 3.79] |
| WEEK_3 | RECOVERY | 117 | 1.53 / 1.29 [-3.39, 5.60] | 3.41 / 2.32 [0.00, 5.48] |
| WEEK_3 | NEVER_WINNER | 179 | 1.16 / 1.06 [-2.81, 4.53] | 3.03 / 2.31 [0.00, 4.98] |
| WEEK_4 | RECOVERY | 117 | 1.36 / 1.12 [-3.98, 5.16] | 3.85 / 2.46 [0.00, 6.67] |
| WEEK_4 | NEVER_WINNER | 175 | 0.52 / 0.79 [-3.33, 4.39] | 3.92 / 2.88 [0.29, 6.20] |
| WEEK_6 | RECOVERY | 116 | 2.30 / 1.48 [-3.62, 5.24] | 4.66 / 3.42 [0.53, 7.65] |
| WEEK_6 | NEVER_WINNER | 170 | 0.35 / 0.54 [-4.55, 5.30] | 5.18 / 3.80 [0.53, 8.24] |
| WEEK_8 | RECOVERY | 113 | 2.61 / 2.62 [-2.32, 6.64] | 5.33 / 4.84 [1.37, 8.56] |
| WEEK_8 | NEVER_WINNER | 160 | 0.94 / 0.19 [-5.00, 5.47] | 5.81 / 4.69 [0.80, 9.27] |

## FAST state and persistence distributions

State rate는 eligible denominator 기준이며, UNAVAILABLE은 usable weak/strong share의 denominator에서 제외했다.

### FASTCORE_V1_W25_PREWINNER_ARMED_V00

| checkpoint | cohort | eligible | weak/strong/unavailable % | weak count median [p25,p75] | weak share median [p25,p75] | ending weak streak median [p25,p75] |
|---|---|---:|---:|---:|---:|---:|
| WEEK_1 | RECOVERY | 151 | 100.0 / 0.0 / 0.0 | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] |
| WEEK_1 | NEVER_WINNER | 198 | 100.0 / 0.0 / 0.0 | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] |
| WEEK_2 | RECOVERY | 151 | 100.0 / 0.0 / 0.0 | 2.00 [2.00, 2.00] | 1.00 [1.00, 1.00] | 2.00 [2.00, 2.00] |
| WEEK_2 | NEVER_WINNER | 198 | 99.5 / 0.5 / 0.0 | 2.00 [2.00, 2.00] | 1.00 [1.00, 1.00] | 2.00 [2.00, 2.00] |
| WEEK_3 | RECOVERY | 151 | 96.0 / 4.0 / 0.0 | 3.00 [3.00, 3.00] | 1.00 [1.00, 1.00] | 3.00 [3.00, 3.00] |
| WEEK_3 | NEVER_WINNER | 198 | 98.5 / 1.5 / 0.0 | 3.00 [3.00, 3.00] | 1.00 [1.00, 1.00] | 3.00 [3.00, 3.00] |
| WEEK_4 | RECOVERY | 151 | 97.4 / 2.6 / 0.0 | 4.00 [4.00, 4.00] | 1.00 [1.00, 1.00] | 4.00 [4.00, 4.00] |
| WEEK_4 | NEVER_WINNER | 196 | 98.5 / 1.5 / 0.0 | 4.00 [4.00, 4.00] | 1.00 [1.00, 1.00] | 4.00 [4.00, 4.00] |
| WEEK_6 | RECOVERY | 148 | 96.6 / 3.4 / 0.0 | 6.00 [6.00, 6.00] | 1.00 [1.00, 1.00] | 6.00 [6.00, 6.00] |
| WEEK_6 | NEVER_WINNER | 195 | 96.9 / 3.1 / 0.0 | 6.00 [6.00, 6.00] | 1.00 [1.00, 1.00] | 6.00 [6.00, 6.00] |
| WEEK_8 | RECOVERY | 145 | 95.9 / 4.1 / 0.0 | 8.00 [8.00, 8.00] | 1.00 [1.00, 1.00] | 8.00 [8.00, 8.00] |
| WEEK_8 | NEVER_WINNER | 179 | 95.5 / 4.5 / 0.0 | 8.00 [8.00, 8.00] | 1.00 [1.00, 1.00] | 8.00 [8.00, 8.00] |

### FASTCORE_V1_W30_PREWINNER_ARMED_V00

| checkpoint | cohort | eligible | weak/strong/unavailable % | weak count median [p25,p75] | weak share median [p25,p75] | ending weak streak median [p25,p75] |
|---|---|---:|---:|---:|---:|---:|
| WEEK_1 | RECOVERY | 117 | 100.0 / 0.0 / 0.0 | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] |
| WEEK_1 | NEVER_WINNER | 179 | 100.0 / 0.0 / 0.0 | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] |
| WEEK_2 | RECOVERY | 117 | 100.0 / 0.0 / 0.0 | 2.00 [2.00, 2.00] | 1.00 [1.00, 1.00] | 2.00 [2.00, 2.00] |
| WEEK_2 | NEVER_WINNER | 179 | 99.4 / 0.6 / 0.0 | 2.00 [2.00, 2.00] | 1.00 [1.00, 1.00] | 2.00 [2.00, 2.00] |
| WEEK_3 | RECOVERY | 117 | 100.0 / 0.0 / 0.0 | 3.00 [3.00, 3.00] | 1.00 [1.00, 1.00] | 3.00 [3.00, 3.00] |
| WEEK_3 | NEVER_WINNER | 179 | 99.4 / 0.6 / 0.0 | 3.00 [3.00, 3.00] | 1.00 [1.00, 1.00] | 3.00 [3.00, 3.00] |
| WEEK_4 | RECOVERY | 117 | 99.1 / 0.9 / 0.0 | 4.00 [4.00, 4.00] | 1.00 [1.00, 1.00] | 4.00 [4.00, 4.00] |
| WEEK_4 | NEVER_WINNER | 175 | 100.0 / 0.0 / 0.0 | 4.00 [4.00, 4.00] | 1.00 [1.00, 1.00] | 4.00 [4.00, 4.00] |
| WEEK_6 | RECOVERY | 116 | 96.6 / 3.4 / 0.0 | 6.00 [6.00, 6.00] | 1.00 [1.00, 1.00] | 6.00 [6.00, 6.00] |
| WEEK_6 | NEVER_WINNER | 170 | 99.4 / 0.6 / 0.0 | 6.00 [6.00, 6.00] | 1.00 [1.00, 1.00] | 6.00 [6.00, 6.00] |
| WEEK_8 | RECOVERY | 113 | 96.5 / 3.5 / 0.0 | 8.00 [8.00, 8.00] | 1.00 [1.00, 1.00] | 8.00 [8.00, 8.00] |
| WEEK_8 | NEVER_WINNER | 160 | 97.5 / 2.5 / 0.0 | 8.00 [8.00, 8.00] | 1.00 [1.00, 1.00] | 8.00 [8.00, 8.00] |

## Descriptive interpretation

- Earliest descriptive separation: WEEK_4 — both W25 and W30 show a directional price split, with NEVER_WINNER weaker on current CLOSE and worse on running-min CLOSE deterioration; WEEK_1 overlaps and WEEK_2–3 are not directionally consistent.
- Persistence after earliest separation: The price direction remains visible through WEEK_6 in both variants, while WEEK_8 still shows a price direction but the FAST split is not fully stable.
- W25/W30 direction agreement: Price direction agrees from WEEK_4 through WEEK_6; FAST Weak rates are near-saturated and do not provide a stable cohort split. No variant winner is selected.

WEEK_4 is the earliest descriptive price separation and it persists through WEEK_6 across W25/W30, but distributions overlap materially and FAST persistence is near-saturated; WEEK_8 is less consistent. Persistence remains a candidate horizon for separate research, not an execution rule.

이 해석은 raw distribution의 overlap과 censoring을 함께 본 qualitative diagnostic이다. 새 cutoff, exit rule, strategy parameter를 선택하지 않는다.

## Explicit non-actions

- threshold selected: `false`
- strategy rule selected: `false`
- new backtest: `false`
- new exit simulation: `false`
- production strategy modified: `false`
- network requests: `0`
- full pytest: not run per work instruction

## Artifacts

이 작업의 신규 artifact는 지시된 6개 파일만 생성했다. 기존 authority artifact는 read-only로 사용했다.
