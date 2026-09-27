# Pattern B + PROGRESSED 이전 WEAK 제외 P2/P3 4-Window Robustness V01

P1은 commit `2104d12675b18bea269d02e40a0b3a8864a104b9`의 frozen 결과를 그대로 읽었고, 재실행하지 않았어. P2-1/P2-2/P3-1/P3-2는 P1의 동일한 CONTROL/TEST 정의와 독립 lifecycle replay를 적용했어.

## 5-Window 핵심 지표

평균, 승률, 중앙값 순서야. Δ는 TEST−CONTROL percentage point고, tail/DEEP Δ는 CONTROL−TEST라 양수면 TEST 위험률이 낮아.

| Window | TEST 평균 | 평균 Δ | TEST 승률 | 승률 Δ | TEST 중앙 | 중앙 Δ | -30 Δ | -50 Δ | DEEP Δ | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| P1 | 12.52% | 0.51pp | 78.94% | 1.74pp | 12.25% | 0.15pp | 0.72pp | 0.27pp | 2.12pp | `PATTERN_B_PROGRESSED_WEAK_FILTER_P1_IMPROVED` |
| P2-1 | 15.74% | 0.03pp | 81.14% | 0.13pp | 12.80% | -0.66pp | 0.27pp | 0.00pp | 1.33pp | `PATTERN_B_PROGRESSED_WEAK_FILTER_P2_1_MIXED` |
| P2-2 | 13.50% | 0.66pp | 79.65% | 1.02pp | 12.64% | -0.01pp | 1.16pp | 0.34pp | 2.36pp | `PATTERN_B_PROGRESSED_WEAK_FILTER_P2_2_IMPROVED` |
| P3-1 | 15.50% | -0.02pp | 83.33% | 0.54pp | 13.69% | -0.35pp | 0.28pp | 0.00pp | 1.10pp | `PATTERN_B_PROGRESSED_WEAK_FILTER_P3_1_MIXED` |
| P3-2 | 13.82% | 0.55pp | 81.63% | 1.21pp | 13.28% | -0.29pp | 1.11pp | 0.18pp | 2.41pp | `PATTERN_B_PROGRESSED_WEAK_FILTER_P3_2_MIXED` |

평균 수익률은 verdict와 별도로 우선 지표로 표시했어. 단일 종합 점수는 만들지 않았어.

## Resolved-terminal 보조 sensitivity

실현 gross terminal과 cutoff exact close mark를 합쳤어. unresolved open은 합산에서 제외하고 건수를 분리했어.

| Window | CONTROL mean / median / positive | TEST mean / median / positive | Resolved N C/T | Exact open C/T | unresolved open C/T |
|---|---|---|---:|---:|---:|
| P1 | 8.40% / 10.59% / 72.25% | 8.91% / 10.82% / 73.90% | 782 / 682 | 67 / 60 | 16 / 12 |
| P2-1 | 4.77% / 9.03% / 66.25% | 5.46% / 8.72% / 67.50% | 323 / 280 | 65 / 52 | 6 / 4 |
| P2-2 | 6.38% / 10.06% / 69.73% | 7.18% / 9.98% / 70.93% | 446 / 399 | 67 / 60 | 7 / 4 |
| P3-1 | 4.45% / 9.18% / 66.79% | 5.01% / 9.17% / 68.24% | 274 / 233 | 59 / 47 | 5 / 3 |
| P3-2 | 6.43% / 10.50% / 70.53% | 7.16% / 10.50% / 71.88% | 397 / 352 | 65 / 58 | 6 / 3 |

Resolved-terminal tail sensitivity는 exact close mark 가능한 open과 실현 거래를 합친 분모 기준이야. 셀은 CONTROL / TEST 순서로 rate와 count를 함께 표시해.

| Window | +30 | +50 | +100 | -30 | -40 | -50 | -60 |
|---|---:|---:|---:|---:|---:|---:|---:|
| P1 | 16.24% (127) / 16.28% (111) | 5.88% (46) / 6.01% (41) | 1.02% (8) / 1.03% (7) | 10.23% (80) / 9.38% (64) | 7.29% (57) / 6.60% (45) | 5.37% (42) / 4.99% (34) | 4.09% (32) / 3.96% (27) |
| P2-1 | 16.10% (52) / 16.07% (45) | 5.88% (19) / 6.07% (17) | 1.24% (4) / 1.43% (4) | 17.03% (55) / 16.07% (45) | 12.69% (41) / 11.79% (33) | 6.81% (22) / 6.79% (19) | 4.02% (13) / 4.64% (13) |
| P2-2 | 16.37% (73) / 16.29% (65) | 6.50% (29) / 6.77% (27) | 1.12% (5) / 1.25% (5) | 13.23% (59) / 11.78% (47) | 9.64% (43) / 8.77% (35) | 7.17% (32) / 6.52% (26) | 5.83% (26) / 5.51% (22) |
| P3-1 | 16.79% (46) / 16.74% (39) | 5.84% (16) / 6.01% (14) | 0.73% (2) / 0.86% (2) | 17.52% (48) / 16.74% (39) | 12.41% (34) / 11.59% (27) | 5.84% (16) / 6.01% (14) | 3.28% (9) / 3.86% (9) |
| P3-2 | 16.88% (67) / 16.76% (59) | 6.55% (26) / 6.82% (24) | 0.76% (3) / 0.85% (3) | 13.10% (52) / 11.65% (41) | 9.07% (36) / 8.24% (29) | 6.55% (26) / 5.97% (21) | 5.29% (21) / 5.11% (18) |

## 5-Window 질문 답변

1. P1의 평균/승률/중앙 개선 방향이 P2/P3에서 반복됐는지: P1 Δ는 평균 `0.51pp`, 승률 `1.74pp`, 중앙 `0.15pp`야. P2/P3에서는 각각 `3/4`, `4/4`, `0/4`개 window에서 TEST가 CONTROL보다 높았어.
2. 전체 5개 window 중 TEST 평균이 개선된 window는 `4/5`야.
3. 전체 5개 window 중 승률 개선은 `5/5`야.
4. 전체 5개 window 중 중앙값 개선은 `1/5`야.
5. P2/P3 tail 재현성(각 위험률 0.1pp 이상 감소)은 -30 `4/4`, -50 `2/4`, DEEP `4/4` window야. P1에서의 대응 delta는 -30 `0.72pp`, -50 `0.27pp`, DEEP `2.12pp`야.
6. P2-1/P3-1은 2025-05 고정 종료, P2-2/P3-2는 2026-08 full 종료라 각 pair에서 판정과 mean/win/median/tail delta를 나눠서 아래에 적었어.

| 고정/전체 pair | 고정 verdict | 전체 verdict | mean Δ 고정→전체 | win Δ 고정→전체 | median Δ 고정→전체 | -30 Δ | -50 Δ | DEEP Δ |
|---|---|---|---:|---:|---:|---:|---:|---:|
| P2-1 → P2-2 | `PATTERN_B_PROGRESSED_WEAK_FILTER_P2_1_MIXED` | `PATTERN_B_PROGRESSED_WEAK_FILTER_P2_2_IMPROVED` | 0.03pp → 0.66pp | 0.13pp → 1.02pp | -0.66pp → -0.01pp | 0.27pp → 1.16pp | 0.00pp → 0.34pp | 1.33pp → 2.36pp |
| P3-1 → P3-2 | `PATTERN_B_PROGRESSED_WEAK_FILTER_P3_1_MIXED` | `PATTERN_B_PROGRESSED_WEAK_FILTER_P3_2_MIXED` | -0.02pp → 0.55pp | 0.54pp → 1.21pp | -0.35pp → -0.29pp | 0.28pp → 1.11pp | 0.00pp → 0.18pp | 1.10pp → 2.41pp |

7. 다음 연구 단계 유지 근거: 5개 중 improved `2`개 (`P1, P2-2`); P2/P3만 보면 improved/mixed/no-benefit `1/3/0`야. P1 외 개선 판정이 한 창뿐이라 재현 근거는 제한적이야. 다음 연구에서는 탐색적 가설로만 유지하고, 추가 독립 구간 증거 전에는 우선순위를 낮게 두는 게 맞아.

## Window별 상세 산출물

각 하위 폴더에 CONTROL/TEST 원장, open positions, filter audit, WEAK 직접효과, DEEP/연도 비교, 30건 lifecycle 검수, metadata/provenance가 있어. P1 frozen summary는 `summary.json`과 `frozen_p1_reference`에 기록했어.

- `P2-1`: verdict `PATTERN_B_PROGRESSED_WEAK_FILTER_P2_1_MIXED`; `p2_1/report.md`.
- `P2-2`: verdict `PATTERN_B_PROGRESSED_WEAK_FILTER_P2_2_IMPROVED`; `p2_2/report.md`.
- `P3-1`: verdict `PATTERN_B_PROGRESSED_WEAK_FILTER_P3_1_MIXED`; `p3_1/report.md`.
- `P3-2`: verdict `PATTERN_B_PROGRESSED_WEAK_FILTER_P3_2_MIXED`; `p3_2/report.md`.

P1 frozen verdict: `PATTERN_B_PROGRESSED_WEAK_FILTER_P1_IMPROVED`.
