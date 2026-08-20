# Pattern A FAST Strategy Finalization / Candidate Selection v0.1 평가 보고서

================================================================================
1. Executive Summary & Selection Decision
================================================================================
- **전략 후보명**: `PATTERN_A_FAST_FINAL_STRATEGY_V01`
- **최종 선택 상태 (Final Status)**: **`FINAL_STRATEGY_SELECTED`**
- **연구 분류 (Research Classification)**: `RETROSPECTIVE_STRATEGY_FINALIZATION_CANDIDATE_SELECTION`
- **검증 유형 (Validation Type)**: `SAME_SAMPLE_RETROSPECTIVE_FINALIZATION`
- **선택 방식 (Selection Methodology)**: `PREREGISTERED_PRIORITY_EVIDENCE_SYNTHESIS`
- **아키텍처 기준 커밋**: [`89df82a`](https://github.com/RozeKurhy/krx-trend-scanner/commit/89df82a938dba1961c2342064db2dc0061a5f2ca)
- **사전등록 커밋**: [`a5c29e7`](https://github.com/RozeKurhy/krx-trend-scanner/commit/a5c29e7e97cb7e6830c3dcd25d824e5779f2312f)
- **데이터 기준일**: `2026-08-14` (**LOCAL CACHE ONLY**)
- **운영 상태**: **`PRODUCTION_HOLD` (운영 불변, 연구 전용)**

### 🏆 최종 확정 전략 컴포넌트 (`PATTERN_A_FAST_FINAL_STRATEGY_V01`)
1. **Entry Policy (`INVESTMENT_MANDATE_FROZEN`)**:
   - 허용 국면: **`TRANSITION`**, **`EARLY_TREND`** (WEAK, BASE, UNAVAILABLE, PROGRESSED 진입 제외)
   - FAST Core: Weekly Machine `TRIGGER` + `READY` / Monthly `PERMITTED` / Daily Risk `NORMAL`/`ELEVATED` / FAST Score `READY`/`PARTIAL`
   - 체결: 익영업일 시가 (**`NEXT_LOCAL_TRADING_DAY_OPEN`**)
2. **Pre-PROGRESSED Hold Policy (`EMPIRICAL_SELECTION`)**:
   - **`HOLD_B_PRE_PROGRESSED_LOSS_GUARD_SELECTED`**
3. **PROGRESSED Exit Architecture (`EMPIRICAL_SELECTION`)**:
   - **`E2_EXIT3_PLUS_EXIT4_PLUS_COVERAGE_SELECTED`**

================================================================================
2. Primary Sample & Population Breakdown
================================================================================
- **전체 보통주 모집단**: 2,528개
- **Phase 10 투자 적격 유니버스**: 1,081개
- **Primary 적격 진입 표본**: 총 **553건**
  - `TRANSITION`: **484건** (87.5%)
  - `EARLY_TREND`: **69건** (12.5%)
- **생애주기 경로 분포**:
  - `NORMAL_EARLY_TREND_HANDOFF`: 270건
  - `SKIPPED_EARLY_TREND_HANDOFF`: 32건
  - `PROGRESSED_WITHOUT_DIRECT_HANDOFF`: 75건
  - `NEVER_PROGRESSED`: 176건

================================================================================
3. STEP 1: Pre-PROGRESSED Hold Evaluation (HOLD_A vs HOLD_B)
================================================================================

| 평가 항목 | HOLD_A (No Protection) | HOLD_B (Loss Guard -15%) | Delta (B - A) |
|---|:---:|:---:|:---:|
| **Return <= -30% 발생 건수 (비율)** | 72건 (13.02%) | 11건 (1.99%) | **-61건 (-84.7%)** |
| **Return <= -20% 발생 건수 (비율)** | 106건 (19.17%) | 33건 (5.97%) | **-73건 (-68.9%)** |
| **Return <= -10% 발생 건수 (비율)** | 163건 (29.48%) | 313건 (56.6%) | **150건** |
| **최악 손실률 (Worst Return)** | -86.26% | -54.43% | **+31.83%p 개선** |
| **Terminal Return (Mean / Median)** | 36.82% / 15.05% | 17.3% / -14.33% | -19.52%p / -29.38%p |
| **Peak Giveback (Median)** | 43.23% | 28.49% | -14.74%p |
| **평균 보유 주수 (Holding Weeks)** | 61.4주 | 29.6주 | -31.8주 |

- **Loss Guard 발동 통계**: 총 295건 (53.35%) 발동
- **Winner Truncation 비용**:
  - Loss Guard가 없었다면 E1 기준 terminal return이 +20% 이상이었을 거래: 98건
  - Loss Guard가 없었다면 E1 기준 terminal return이 +50% 이상이었을 거래: 65건
  - Loss Guard가 없었다면 E1 기준 terminal return이 +100% 이상이었을 거래: 32건
- **손절 거래의 Counterfactual MFE**: Mean 79.30%, Median 38.03%
- **판정 근거**: `PRE_PROGRESSED_PROTECTION_SUPPORTED` -> **`HOLD_B_PRE_PROGRESSED_LOSS_GUARD_SELECTED` 확정** (투자자의 Large Loss Minimization 원칙 준수)

================================================================================
4. STEP 2: PROGRESSED Exit Architecture Evaluation (E0 vs E1 vs E2)
================================================================================

| 지표 | E0 (Exit 3 Only) | E1 (Exit 3 + Normal Exit 4) | E2 (Exit 3 + Exit 4 + Coverage) |
|---|:---:|:---:|:---:|
| **Return <= -30% 건수 (비율)** | 14건 (2.53%) | 11건 (1.99%) | **8건 (1.45%)** |
| **Return <= -20% 건수 (비율)** | 43건 (7.78%) | 33건 (5.97%) | **29건 (5.24%)** |
| **Terminal Return (Mean / Median)** | 25.98% / -14.58% | 17.3% / -14.33% | **17.72% / -14.15%** |
| **Peak Giveback (Median / P75)** | 36.07% / 75.53% | 28.49% / 48.61% | **26.99% / 45.16%** |
| **Profit Capture Ratio (Median)** | -0.53 | -0.5 | **-0.5** |
| **Return >= +50% Winner 수 (비율)** | 106건 (19.17%) | 114건 (20.61%) | **116건 (20.98%)** |
| **Return >= +100% Winner 수 (비율)** | 51건 (9.22%) | 41건 (7.41%) | **41건 (7.41%)** |

- **선택 해석**:
  E2는 E0보다 평균 수익률(25.98% vs 17.72%)은 낮지만, risk-first mandate에서 large-loss tail(<= -30%: 8건, <= -20%: 29건)과 giveback(중앙값 26.99%)이 가장 우수하며, E1 대비 평균 return도 소폭 개선되었으므로 **`E2_EXIT3_PLUS_EXIT4_PLUS_COVERAGE_SELECTED`**를 확정함.

================================================================================
5. Final Strategy Specification: PATTERN_A_FAST_FINAL_STRATEGY_V01
================================================================================
- **전략 명칭**: `PATTERN_A_FAST_FINAL_STRATEGY_V01`
- **진입 규칙**:
  - `TRANSITION` 및 `EARLY_TREND` 국면의 FAST v0.1 신호 익영업일 시가 매수.
  - `WEAK`, `BASE`, `UNAVAILABLE`, `PROGRESSED` 진입 금지.
- **Pre-PROGRESSED 보유/손실 방어**:
  - `PROGRESSED` 도달 전(즉, `date < first_progressed_date`) 일봉 종가 `-15%` 이하 도달 시 익영업일 시가 손실 방어 청산 (`LOSS_GUARD_CLOSE_LE_NEG_15`).
- **PROGRESSED 청산**:
  - 정상 직접 handoff 및 Coverage Hole 모두에서 15.0pt HWM Score Drawdown 발생 시 익월 첫 거래일 시가 청산.
  - 정상 handoff 국면에서 유효 구조 이탈 시 Exit 3 청산.
- **알려진 한계 및 트레이드오프 (Known Limitations & Trade-offs)**:
  - SAME_SAMPLE_RETROSPECTIVE_FINALIZATION
  - HOLD_COMPARISON_PRIMARY_BASELINE_E1_NOT_EXPLICITLY_PREREGISTERED
  - FRESH_OOS_NOT_YET_PERFORMED
