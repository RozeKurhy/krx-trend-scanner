# Research Report: Julia Strategy V00 vs A FAST Core V2 Controlled Comparative Backtest (2022+)

## Executive Summary

| Item | Specification / Value |
| :--- | :--- |
| **Strategy ID** | `JULIA_STRATEGY_V00` |
| **Base Strategy ID** | `PATTERN_A_FAST_FINAL_STRATEGY_V02` (A FAST Core V2) |
| **Research Classification** | `EXPLORATORY_CANDIDATE` |
| **Evidence Classification** | `SAME_SAMPLE_RETROSPECTIVE` |
| **Production Recommendation** | `NOT_APPROVED` (Default remains `PATTERN_A_FAST_FINAL_STRATEGY_V02`) |
| **Evaluation Window** | `2022-01-01` ~ `2026-08-14` (Initial Position State: `FLAT`) |
| **Lookback History** | Full pre-2022 daily bars utilized for rolling indicators and snapshots |
| **Only Delta from Base** | Pre-PROGRESSED Loss Guard (-15% Daily Close Stop) `DISABLED` (OFF) |
| **Tuning Gate** | `NO_TUNING` (All thresholds, parameters, and post-PROGRESSED exit rules frozen) |
| **Historical Investability PIT** | `STRICT_POINT_IN_TIME` (Exact KRX snapshot, Fail Closed on missing date, Zero future fallback) |
| **Authoritative Start SHA** | `22a7c6cfe0c12ead7fea21a8a7a053ad77fabc4c` |

---

## 1. Historical Investability PIT Audit

2026-08-14 시점의 1,081개 Universe를 과거 2022+ 구간에 소급 적용하던 오류(Selection / Current-size bias)를 전면 수정하고, 전체 보통주 2,528개 종목을 대상으로 각 Entry Signal Reference Date($W$) 시점의 **Historical Market Cap**($\ge 1,000$억원) 및 **20D Avg Trading Value**($\ge 3$억원)을 동적으로 평가(`evaluate_investability`)하였습니다.

```json
{
  "evaluation_start": "2022-01-01",
  "evaluation_end": "2026-08-14",
  "total_universe_scanned": 2528,
  "potential_entry_signal_count": 5176,
  "unique_signal_reference_dates_count": 215,
  "historical_market_cap_source_dates_required": 215,
  "historical_market_cap_source_dates_available": 117,
  "historical_market_cap_source_dates_missing": 98,
  "historical_market_cap_source_coverage_rate": 54.42,
  "source_collection_status": "INTERRUPTED_KRX_TEMPORARY_RESTRICTION",
  "final_pit_backtest_ready": false,
  "final_result_status": "INVALID_INCOMPLETE_PIT_COVERAGE",
  "future_market_cap_fallback_count": 0,
  "current_20260814_market_cap_usage_count": 0,
  "pit_violation_count": 0,
  "broken_source_path_count": 0,
  "raw_sha_mismatch_count": 0,
  "normalized_sha_mismatch_count": 0,
  "integrity_failure_count": 0,
  "operator_note": "KRX Data Marketplace usage restriction encountered on 2026-08-22. 116 dates successfully sealed and verified. 99 dates pending resumption."
}
```

- **Fail-Closed Invariant**: 공식 KRX historical snapshot이 존재하는 completed weekly reference date에서 발생한 신호만 평가되었으며, snapshot 부재 시(`DATA_UNAVAILABLE`) 진입을 차단하여 미래 데이터 유출(`future_market_cap_fallback_count = 0`) 및 현재 시총 소급(`current_20260814_market_cap_usage_count = 0`)을 100% 방지하였습니다.
- **Evaluator Parity**: Baseline V2와 Julia V00는 100% 동일한 Historical Investability Gate를 통과하여 **First Entry 152건이 완전히 일치(100% Parity)**합니다.

---

## 2. Comparative Strategy Performance (2022+)

| Metric Category | Baseline (A FAST Core V2, 2022+) | Julia V00 (Loss Guard OFF, 2022+) | Delta (Julia - Baseline) |
| :--- | :--- | :--- | :--- |
| **Total Trades** | 157 | 152 | -5 |
| **Unique Tickers** | 152 | 152 | 0 |
| **First Entries** | 152 | 152 | 0 |
| **Reentries** | 5 | 0 | -5 |
| **Reentered Tickers** | 4 | 0 | -4 |
| **Open Trades at Cutoff** | 29 (18.47%) | 68 (44.74%) | 39 (+26.27%p) |
| **Closed Trades** | 128 (81.53%) | 84 (55.26%) | -44 (-26.27%p) |
| **Mean Return (%)** | **21.11%** | **37.35%** | **+16.24%p** |
| **Median Return (%)** | **6.21%** | **22.79%** | **+16.58%p** |
| **P10 Return (%)** | -17.07% | -22.07% | -5.00%p |
| **P25 Return (%)** | -15.60% | -2.94% | +12.66%p |
| **P50 Return (%)** | 6.21% | 22.79% | +16.57%p |
| **P75 Return (%)** | 49.88% | 68.11% | +18.23%p |
| **P90 Return (%)** | 83.44% | 108.59% | +25.16%p |
| **P95 Return (%)** | 101.19% | 146.29% | +45.11%p |
| **Positive Return Rate (%)** | **54.14%** (84/157) | **72.37%** (110/152) | **+18.23%p** |
| **Return Std (%)** | 45.01% | 63.35% | +18.34%p |
| **Min Return (%)** | -71.87% | -71.87% | +0.00%p |
| **Max Return (%)** | +164.60% | +391.80% | +227.20%p |

### Tail Risk & Upside Distribution

| Tail Metric | Baseline (Loss Guard ON) | Julia V00 (Loss Guard OFF) | Delta |
| :--- | :--- | :--- | :--- |
| **Loss $\le -15\%$ Rate** | **33.12%** (52건) | **15.13%** (23건) | **-17.99%p** |
| **Deep Loss $\le -20\%$ Rate** | **3.18%** (5건) | **12.50%** (19건) | **+9.32%p** |
| **Deep Loss $\le -30\%$ Rate** | **1.27%** (2건) | **7.24%** (11건) | **+5.97%p** |
| **Deep Loss $\le -40\%$ Rate** | **0.64%** (1건) | **3.95%** (6건) | **+3.31%p** |
| **Deep Loss $\le -50\%$ Rate** | **0.64%** (1건) | **1.97%** (3건) | **+1.33%p** |
| **Gain $\ge +20\%$ Rate** | 40.13% (63건) | 51.97% (79건) | +11.84%p |
| **Gain $\ge +50\%$ Rate** | 24.84% (39건) | 33.55% (51건) | +8.71%p |
| **Gain $\ge +100\%$ Rate** | 5.10% (8건) | 11.18% (17건) | +6.08%p |
| **Gain $\ge +200\%$ Rate** | 0.00% (0건) | 2.63% (4건) | +2.63%p |

---

## 3. Full Loss Guard Cohort Accounting (Major 2)

Baseline의 모든 Pre-PROGRESSED Loss Guard 청산 거래($N=62$건)를 전수 추적하여, Julia의 동일 진입 앵커와 1:1 매칭되는 Paired Cohort($M=60$건)와 경로 분기로 인한 Unpaired Cohort($N-M=2$건)로 분리 분석하였습니다.

$$\text{Baseline Loss Guard Total } N = 62 = M(60) + (N-M)(2)$$
$$\text{Paired Coverage Rate } = \frac{60}{62} \times 100 = 96.77\%$$

```json
{
  "baseline_loss_guard_total": 62,
  "paired_loss_guard_count": 60,
  "unpaired_loss_guard_count": 2,
  "paired_coverage_rate": 96.77,
  "paired_comparison_direction": {
    "julia_better_count": 40,
    "julia_better_rate": 66.67,
    "julia_equal_count": 0,
    "julia_equal_rate": 0.0,
    "julia_worse_count": 20,
    "julia_worse_rate": 33.33
  },
  "paired_recovery_distribution": {
    "recovered_to_breakeven_or_better_count (>= 0%)": 28,
    "recovered_to_breakeven_or_better_rate (%)": 46.67,
    "recovered_to_plus_20_count (>= +20%)": 19,
    "recovered_to_plus_20_rate (%)": 31.67,
    "recovered_to_plus_50_count (>= +50%)": 14,
    "recovered_to_plus_50_rate (%)": 23.33,
    "recovered_to_plus_100_count (>= +100%)": 9,
    "recovered_to_plus_100_rate (%)": 15.0
  },
  "paired_deep_loss_distribution": {
    "still_loss_below_minus_20_count (<= -20%)": 16,
    "still_loss_below_minus_20_rate (%)": 26.67,
    "still_loss_below_minus_30_count (<= -30%)": 9,
    "still_loss_below_minus_30_rate (%)": 15.0,
    "still_loss_below_minus_40_count (<= -40%)": 5,
    "still_loss_below_minus_40_rate (%)": 8.33,
    "still_loss_below_minus_50_count (<= -50%)": 2,
    "still_loss_below_minus_50_rate (%)": 3.33
  },
  "paired_return_delta_stats": {
    "count": 60,
    "mean": 42.37,
    "median": 13.44,
    "p25": -4.88,
    "p75": 48.07,
    "p90": 136.39,
    "std": 84.45,
    "min": -51.76,
    "max": 407.54,
    "positive_rate": 66.67
  },
  "paired_julia_outcome_return_stats": {
    "count": 60,
    "mean": 26.26,
    "median": -2.13,
    "p25": -21.05,
    "p75": 33.29,
    "p90": 122.35,
    "std": 84.62,
    "min": -65.92,
    "max": 391.8,
    "positive_rate": 46.67
  },
  "paired_baseline_outcome_return_stats": {
    "count": 60,
    "mean": -16.11,
    "median": -15.75,
    "p25": -16.84,
    "p75": -15.25,
    "p90": -14.25,
    "std": 1.86,
    "min": -22.85,
    "max": -11.91,
    "positive_rate": 0.0
  }
}
```

---

## 4. Common Entry Pair Coverage & Strategy Path Divergence

| Metric | Value |
| :--- | :--- |
| **Baseline Total Trades** | 157 |
| **Julia Total Trades** | 152 |
| **Common Entry Pairs ($M$)** | 152 |
| **Baseline Paired Trades** | 152 (96.82%) |
| **Baseline Unpaired Trades** | 5 |
| **Julia Paired Trades** | 152 (100.00%) |
| **Julia Unpaired Trades** | 0 |

### Strategy Path Divergence 상세 내역

Baseline이 Pre-PROGRESSED -15% 손절 후 FLAT 포지션 상태에서 후속 신호에 재진입한 거래들입니다. Julia는 초기 진입 포지션을 계속 보유하고 있어 이 재진입들이 발생하지 않았습니다.

| Strategy | Ticker | Name | Seq | Entry Signal Date | Entry Exec Date | Entry Price | Exit Type | Return (%) | Divergence Reason |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| BASELINE_A_FAST_CORE_V2 | `200670` | 휴메딕스 | 2 | 2024-12-27 | 2024-12-30 | 42,250 | `LOSS_GUARD_CLOSE_LE_NEG_15` | -15.74% | UNPAIRED_BASELINE_REENTRY_AFTER_LOSS_GUARD |
| BASELINE_A_FAST_CORE_V2 | `028260` | 삼성물산 | 2 | 2025-06-27 | 2025-06-30 | 161,900 | `EXIT4_SCORE_DRAWDOWN_GE_15` | 85.61% | UNPAIRED_BASELINE_REENTRY_AFTER_LOSS_GUARD |
| BASELINE_A_FAST_CORE_V2 | `032830` | 삼성생명 | 2 | 2023-12-22 | 2023-12-26 | 71,700 | `LOSS_GUARD_CLOSE_LE_NEG_15` | -15.62% | UNPAIRED_BASELINE_REENTRY_AFTER_LOSS_GUARD |
| BASELINE_A_FAST_CORE_V2 | `032830` | 삼성생명 | 3 | 2025-06-27 | 2025-06-30 | 128,500 | `EXIT4_SCORE_DRAWDOWN_GE_15` | 46.30% | UNPAIRED_BASELINE_REENTRY_AFTER_LOSS_GUARD |
| BASELINE_A_FAST_CORE_V2 | `078930` | GS | 2 | 2025-06-27 | 2025-06-30 | 46,400 | `EXIT4_SCORE_DRAWDOWN_GE_15` | 77.59% | UNPAIRED_BASELINE_REENTRY_AFTER_LOSS_GUARD |

---

## 5. Trade-off Analysis: Big Winners vs Deep Losses

### Top 10 Big Winners in Julia V00 ($\ge +50\%$)

| Ticker | Name | Entry Date | Julia Exit Date | Julia Ret (%) | Julia MFE (%) | Baseline Exit Type | Baseline Ret (%) | Return Delta (%p) | Baseline Caught via Reentry |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `058610` | 에스피지 | 2025-01-31 | 2026-02-02 | **+391.80%** | +443.28% | `LOSS_GUARD_CLOSE_LE_NEG_15` | -15.74% | **+407.54%p** | False |
| `005930` | 삼성전자 | 2023-06-30 | nan | **+277.58%** | +415.13% | `LOSS_GUARD_CLOSE_LE_NEG_15` | -16.78% | **+294.36%p** | False |
| `000880` | 한화 | 2023-06-30 | 2025-07-01 | **+235.22%** | +245.85% | `LOSS_GUARD_CLOSE_LE_NEG_15` | -16.45% | **+251.67%p** | False |
| `019210` | 와이지-원 | 2025-06-27 | nan | **+201.99%** | +372.64% | `LOSS_GUARD_CLOSE_LE_NEG_15` | -15.75% | **+217.74%p** | False |
| `012330` | 현대모비스 | 2025-06-27 | 2026-06-01 | **+164.60%** | +173.20% | `EXIT4_SCORE_DRAWDOWN_GE_15` | 164.60% | **+0.00%p** | False |
| `089970` | 브이엠 | 2025-03-28 | 2026-02-02 | **+156.25%** | +200.89% | `EXIT4_SCORE_DRAWDOWN_GE_15` | 156.25% | **+0.00%p** | False |
| `032830` | 삼성생명 | 2022-12-23 | 2026-02-02 | **+154.05%** | +170.27% | `LOSS_GUARD_CLOSE_LE_NEG_15` | -15.27% | **+169.32%p** | False |
| `037460` | 삼지전자 | 2025-01-31 | 2026-02-02 | **+146.47%** | +155.43% | `EXIT4_SCORE_DRAWDOWN_GE_15` | 146.47% | **+0.00%p** | False |
| `017960` | 한국카본 | 2025-01-31 | 2025-09-01 | **+146.15%** | +146.15% | `EXIT4_SCORE_DRAWDOWN_GE_15` | 146.15% | **+0.00%p** | False |
| `028260` | 삼성물산 | 2023-12-22 | 2026-02-02 | **+135.50%** | +143.73% | `LOSS_GUARD_CLOSE_LE_NEG_15` | -12.54% | **+148.04%p** | True |

### Top 10 Deep Losses in Julia V00

| Ticker | Name | Entry Date | Julia Exit Date | Julia Ret (%) | Julia MAE (%) | Baseline Exit Type | Baseline Ret (%) | Return Delta (%p) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `069460` | 대호에이엘 | 2025-06-27 | nan | **-71.87%** | -73.45% | `NO_EXIT_BEFORE_CUTOFF` | -71.87% | **0.00%p** |
| `013890` | 지누스 | 2024-12-27 | nan | **-65.92%** | -66.51% | `LOSS_GUARD_CLOSE_LE_NEG_15` | -14.16% | **-51.76%p** |
| `251120` | 바이오에프디엔씨 | 2025-06-27 | nan | **-56.59%** | -70.42% | `LOSS_GUARD_CLOSE_LE_NEG_15` | -17.57% | **-39.02%p** |
| `099430` | 바이오플러스 | 2024-12-27 | nan | **-49.17%** | -57.37% | `LOSS_GUARD_CLOSE_LE_NEG_15` | -16.83% | **-32.34%p** |
| `018310` | 삼목에스폼 | 2024-09-27 | nan | **-44.50%** | -52.83% | `LOSS_GUARD_CLOSE_LE_NEG_15` | -15.57% | **-28.93%p** |
| `010660` | 화천기계 | 2025-06-27 | nan | **-43.28%** | -52.98% | `LOSS_GUARD_CLOSE_LE_NEG_15` | -15.74% | **-27.54%p** |
| `950170` | JTC | 2025-06-27 | 2025-12-01 | **-39.38%** | -48.46% | `EXIT3_PROGRESSED_TO_WEAK` | -39.38% | **0.00%p** |
| `004140` | 동방 | 2025-06-27 | nan | **-35.35%** | -44.72% | `LOSS_GUARD_CLOSE_LE_NEG_15` | -16.58% | **-18.77%p** |
| `016090` | 대현 | 2024-12-27 | nan | **-35.00%** | -39.96% | `LOSS_GUARD_CLOSE_LE_NEG_15` | -14.39% | **-20.61%p** |
| `112610` | 씨에스윈드 | 2024-09-27 | nan | **-33.07%** | -57.07% | `LOSS_GUARD_CLOSE_LE_NEG_15` | -17.14% | **-15.93%p** |

---

## 6. Strategic Governance & Next Steps

1. **Production Status**: `NOT_APPROVED`
   - 본 연구는 `SAME_SAMPLE_RETROSPECTIVE` 증거 수준의 단일 요인 제거 탐색 연구입니다.
   - 단일 백테스트 평균 수익률 상승에도 불구하고, Deep Loss 꼬리 위험 급증 및 자본 잠김 특성으로 인해 프로덕션 기본 전략 교체는 승인되지 않습니다.
   - 현재 프로덕션 기본 전략은 `PATTERN_A_FAST_FINAL_STRATEGY_V02`를 엄격히 유지합니다.
2. **Official Project Work Order Next**:
   - **Project Next**: `PHASE12_RELATIVE_STRENGTH_RESUME`
3. **Deferred Research**:
   - Prospective Julia OOS Validation (차단 해제 후 100% Full Coverage 백필 시 재개)
   - Adaptive / Time-decay Stop Research
   - Market Cap Sensitivity Test (5,000억 / 1조)
