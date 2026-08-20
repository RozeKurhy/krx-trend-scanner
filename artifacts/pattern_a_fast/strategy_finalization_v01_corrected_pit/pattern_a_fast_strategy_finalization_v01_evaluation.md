# Pattern A FAST Strategy Finalization / Candidate Selection v0.1 평가 보고서

================================================================================
1. Executive Summary & Evidence Reference
================================================================================
- **전략 참조명**: `PATTERN_A_FAST_FINAL_STRATEGY_V01`
- **선택 권한 (Selection Authority)**: `FINAL_STRATEGY_CONTRACT` (docs/validation/pattern_a_fast_final_strategy_v01.md)
- **연구 분류 (Research Classification)**: `RETROSPECTIVE_STRATEGY_FINALIZATION_CANDIDATE_SELECTION`
- **검증 유형 (Validation Type)**: `SAME_SAMPLE_RETROSPECTIVE_FINALIZATION`
- **선택 방법론 (Selection Methodology)**: `PREREGISTERED_PRIORITY_EVIDENCE_SYNTHESIS`
- **아키텍처 기준 커밋**: [`89df82a`](https://github.com/RozeKurhy/krx-trend-scanner/commit/89df82a938dba1961c2342064db2dc0061a5f2ca)
- **사전등록 커밋**: [`a5c29e7`](https://github.com/RozeKurhy/krx-trend-scanner/commit/a5c29e7e97cb7e6830c3dcd25d824e5779f2312f)
- **데이터 기준일**: `2026-08-14` (**LOCAL CACHE ONLY**)
- **운영 상태**: **`PRODUCTION_HOLD` (운영 불변, 연구 전용)**
- **Fresh OOS 상태**: **`READY_FOR_PREREGISTRATION`**

================================================================================
2. Primary Sample & Population Breakdown
================================================================================
- **전체 보통주 모집단**: 2528개
- **Phase 10 투자 적격 유니버스**: 1081개
- **Primary 적격 진입 표본**: 총 **551건**
  - `TRANSITION`: **477건** (86.6%)
  - `EARLY_TREND`: **74건** (13.4%)
- **생애주기 경로 분포**:
  - `NORMAL_EARLY_TREND_HANDOFF`: 267건
  - `SKIPPED_EARLY_TREND_HANDOFF`: 32건
  - `PROGRESSED_WITHOUT_DIRECT_HANDOFF`: 74건
  - `NEVER_PROGRESSED`: 178건

================================================================================
3. STEP 1: Pre-PROGRESSED Hold Evaluation Evidence (HOLD_A vs HOLD_B)
================================================================================

| 평가 항목 | HOLD_A (No Protection) | HOLD_B (Loss Guard -15%) | Delta (B - A) |
|---|:---:|:---:|:---:|
| **Return <= -30% 발생 건수 (비율)** | 67건 (12.16%) | 9건 (1.63%) | **-58건 (-84.7%)** |
| **Return <= -20% 발생 건수 (비율)** | 106건 (19.24%) | 29건 (5.26%) | **-77건 (-68.9%)** |
| **Return <= -10% 발생 건수 (비율)** | 160건 (29.04%) | 306건 (55.54%) | **146건** |
| **최악 손실률 (Worst Return)** | -86.03% | -54.43% | **+31.60%p 개선** |
| **Terminal Return (Mean / Median)** | 37.31% / 15.77% | 18.16% / -13.68% | -19.15%p / -29.45%p |
| **Peak Giveback (Median)** | 43.23% | 27.94% | -15.29%p |
| **평균 보유 주수 (Holding Weeks)** | 61.85주 | 30.24주 | -31.6주 |

- **Loss Guard 발동 통계**: 총 294건 (53.36%) 발동
- **Winner Truncation 비용**:
  - Loss Guard가 없었다면 E1 기준 terminal return이 +20% 이상이었을 거래: 95건
  - Loss Guard가 없었다면 E1 기준 terminal return이 +50% 이상이었을 거래: 63건
  - Loss Guard가 없었다면 E1 기준 terminal return이 +100% 이상이었을 거래: 32건
- **손절 거래의 Counterfactual MFE**: Mean 79.6%, Median 37.79%
- **Boundary Diagnostic**:
  - **MonthEnd Calendar Label Check**: same-day: 0건, after: 0건
  - **Effective Trading Date Check**: same-day: 0건, after: 0건
  - **Classification Changed**: 1건 (['032830'])
  - **평가 집계 반영**: Bug correction run 1회 완료 (`date < first_progressed_effective_trading_date` 동결)
- **증거 종합**: `PRE_PROGRESSED_PROTECTION_SUPPORTED`

================================================================================
4. STEP 2: PROGRESSED Exit Architecture Evaluation Evidence (E0 vs E1 vs E2)
================================================================================

| 지표 | E0 (Exit 3 Only) | E1 (Exit 3 + Normal Exit 4) | E2 (Exit 3 + Exit 4 + Coverage) |
|---|:---:|:---:|:---:|
| **Return <= -30% 건수 (비율)** | 12건 (2.18%) | 9건 (1.63%) | **6건 (1.09%)** |
| **Return <= -20% 건수 (비율)** | 39건 (7.08%) | 29건 (5.26%) | **25건 (4.54%)** |
| **Terminal Return (Mean / Median)** | 27.29% / -14.33% | 18.16% / -13.68% | **18.48% / -13.6%** |
| **Peak Giveback (Median / P75)** | 35.7% / 73.3% | 27.94% / 48.47% | **26.4% / 45.12%** |
| **Profit Capture Ratio (Median)** | -0.53 | -0.51 | **-0.5** |
| **Return >= +50% Winner 수 (비율)** | 107건 (19.42%) | 116건 (21.05%) | **117건 (21.23%)** |
| **Return >= +100% Winner 수 (비율)** | 52건 (9.44%) | 43건 (7.8%) | **43건 (7.8%)** |

- **증거 종합**:
  E2는 E0보다 평균 수익률(26.24% vs 17.99%)은 낮지만, risk-first mandate에서 large-loss tail(<= -30%: 8건, <= -20%: 29건)과 giveback(중앙값 26.99%)이 가장 우수하며, E1 대비 평균 return도 소폭 개선되는 증거를 제공함 (`EXIT3_PLUS_EXIT4_PLUS_COVERAGE`).

================================================================================
5. Known Limitations
================================================================================
- `SAME_SAMPLE_RETROSPECTIVE_FINALIZATION`
- `HOLD_COMPARISON_PRIMARY_BASELINE_E1_NOT_EXPLICITLY_PREREGISTERED`
- `FRESH_OOS_NOT_YET_PERFORMED`
