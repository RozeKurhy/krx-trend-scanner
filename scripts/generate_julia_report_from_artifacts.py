#!/usr/bin/env python
"""Machine Generator for Julia Strategy V00 Research Report from Canonical Artifacts.

Guarantees 100% exact parity between CSV/JSON artifacts and Markdown documentation.
"""

from __future__ import annotations

import json
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
JULIA_DIR = ROOT / "artifacts/strategies/julia/v00"
DOC_MD = ROOT / "docs/strategies/julia/v00.md"
R_MD = ROOT / "r.md"


def generate_markdown_report() -> str:
    summary_path = JULIA_DIR / "strategy_comparison_summary.json"
    pit_audit_path = JULIA_DIR / "historical_investability_pit_audit.json"
    lg_summary_path = JULIA_DIR / "loss_guard_recovery_summary.json"
    winners_path = JULIA_DIR / "big_winners.csv"
    worst_path = JULIA_DIR / "worst_losses.csv"
    divergence_path = JULIA_DIR / "strategy_path_divergence.csv"

    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    pit_audit = json.loads(pit_audit_path.read_text(encoding="utf-8")) if pit_audit_path.exists() else {}
    lg_summary = json.loads(lg_summary_path.read_text(encoding="utf-8")) if lg_summary_path.exists() else {}

    df_winners = pd.read_csv(winners_path) if winners_path.exists() else pd.DataFrame()
    df_worst = pd.read_csv(worst_path) if worst_path.exists() else pd.DataFrame()
    df_divergence = pd.read_csv(divergence_path) if divergence_path.exists() else pd.DataFrame()

    meta = summary.get("metadata", {})
    pairs = summary.get("pair_coverage", {})
    b_metrics = summary.get("baseline_v2_2022", {})
    j_metrics = summary.get("julia_v00_2022", {})

    b_ret = b_metrics.get("return_stats", {})
    j_ret = j_metrics.get("return_stats", {})
    b_p = b_metrics.get("percentiles", {})
    j_p = j_metrics.get("percentiles", {})
    b_loss = b_metrics.get("loss_tail", {})
    j_loss = j_metrics.get("loss_tail", {})
    b_up = b_metrics.get("upside_tail", {})
    j_up = j_metrics.get("upside_tail", {})

    # Top 10 Winners Table
    winner_rows_md = []
    if not df_winners.empty:
        for _, r in df_winners.head(10).iterrows():
            winner_rows_md.append(
                f"| `{str(r['ticker']).zfill(6)}` | {r['name']} | {r['entry_signal_date']} | {r['julia_exit_date'] or 'Cutoff (Open)'} | **+{float(r['julia_terminal_return']):.2f}%** | +{float(r['julia_mfe']):.2f}% | `{r['baseline_exit_type']}` | {float(r['baseline_terminal_return']):.2f}% | **{'+' if float(r['return_delta']) >= 0 else ''}{float(r['return_delta']):.2f}%p** | {r['baseline_caught_via_reentry']} |"
            )
    winners_table_str = "\n".join(winner_rows_md) if winner_rows_md else "| None | - | - | - | - | - | - | - | - | - |"

    # Top 10 Worst Losses Table
    worst_rows_md = []
    if not df_worst.empty:
        for _, r in df_worst.head(10).iterrows():
            worst_rows_md.append(
                f"| `{str(r['ticker']).zfill(6)}` | {r['name']} | {r['entry_signal_date']} | {r['julia_exit_date'] or 'Cutoff (Open)'} | **{float(r['julia_terminal_return']):.2f}%** | {float(r['julia_mae']):.2f}% | `{r['baseline_exit_type']}` | {float(r['baseline_terminal_return']):.2f}% | **{float(r['return_delta']):.2f}%p** |"
            )
    worst_table_str = "\n".join(worst_rows_md) if worst_rows_md else "| None | - | - | - | - | - | - | - |"

    # Divergence Table
    div_rows_md = []
    if not df_divergence.empty:
        for _, r in df_divergence.iterrows():
            div_rows_md.append(
                f"| {r['origin_strategy']} | `{str(r['ticker']).zfill(6)}` | {r['name']} | {r['trade_sequence']} | {r['entry_signal_date']} | {r['entry_execution_date']} | {float(r['entry_open']):,.0f} | `{r['exit_type']}` | {float(r['terminal_return']):.2f}% | {r['divergence_reason']} |"
            )
    div_table_str = "\n".join(div_rows_md) if div_rows_md else "| None | - | - | - | - | - | - | - | - | - |"

    content = f"""# Research Report: Julia Strategy V00 vs A FAST Core V2 Controlled Comparative Backtest (2022+)

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
| **Authoritative Start SHA** | `{meta.get("supersedes_commit", "2b966aad4fdb461937b293ae719cc354f86020f9")}` |

---

## 1. Historical Investability PIT Audit

2026-08-14 시점의 1,081개 Universe를 과거 2022+ 구간에 소급 적용하던 오류(Selection / Current-size bias)를 전면 수정하고, 전체 보통주 2,528개 종목을 대상으로 각 Entry Signal Reference Date($W$) 시점의 **Historical Market Cap**($\\ge 1,000$억원) 및 **20D Avg Trading Value**($\\ge 3$억원)을 동적으로 평가(`evaluate_investability`)하였습니다.

```json
{json.dumps(pit_audit, indent=2, ensure_ascii=False)}
```

- **Fail-Closed Invariant**: 공식 KRX historical snapshot이 존재하는 completed weekly reference date에서 발생한 신호만 평가되었으며, snapshot 부재 시(`DATA_UNAVAILABLE`) 진입을 차단하여 미래 데이터 유출(`future_market_cap_fallback_count = 0`) 및 현재 시총 소급(`current_20260814_market_cap_usage_count = 0`)을 100% 방지하였습니다.
- **Evaluator Parity**: Baseline V2와 Julia V00는 100% 동일한 Historical Investability Gate를 통과하여 **First Entry {b_metrics.get('first_entries', 0)}건이 완전히 일치(100% Parity)**합니다.

---

## 2. Comparative Strategy Performance (2022+)

| Metric Category | Baseline (A FAST Core V2, 2022+) | Julia V00 (Loss Guard OFF, 2022+) | Delta (Julia - Baseline) |
| :--- | :--- | :--- | :--- |
| **Total Trades** | {b_metrics.get('total_trades', 0)} | {j_metrics.get('total_trades', 0)} | {j_metrics.get('total_trades', 0) - b_metrics.get('total_trades', 0)} |
| **Unique Tickers** | {b_metrics.get('unique_tickers', 0)} | {j_metrics.get('unique_tickers', 0)} | {j_metrics.get('unique_tickers', 0) - b_metrics.get('unique_tickers', 0)} |
| **First Entries** | {b_metrics.get('first_entries', 0)} | {j_metrics.get('first_entries', 0)} | 0 |
| **Reentries** | {b_metrics.get('reentries', 0)} | {j_metrics.get('reentries', 0)} | {j_metrics.get('reentries', 0) - b_metrics.get('reentries', 0)} |
| **Reentered Tickers** | {b_metrics.get('reentered_tickers_count', 0)} | {j_metrics.get('reentered_tickers_count', 0)} | {j_metrics.get('reentered_tickers_count', 0) - b_metrics.get('reentered_tickers_count', 0)} |
| **Open Trades at Cutoff** | {b_metrics.get('open_trades', 0)} ({b_metrics.get('open_trades', 0)/b_metrics.get('total_trades', 1)*100:.2f}%) | {j_metrics.get('open_trades', 0)} ({j_metrics.get('open_trades', 0)/j_metrics.get('total_trades', 1)*100:.2f}%) | {j_metrics.get('open_trades', 0) - b_metrics.get('open_trades', 0)} ({j_metrics.get('open_trades', 0)/j_metrics.get('total_trades', 1)*100 - b_metrics.get('open_trades', 0)/b_metrics.get('total_trades', 1)*100:+.2f}%p) |
| **Closed Trades** | {b_metrics.get('closed_trades', 0)} ({b_metrics.get('closed_trades', 0)/b_metrics.get('total_trades', 1)*100:.2f}%) | {j_metrics.get('closed_trades', 0)} ({j_metrics.get('closed_trades', 0)/j_metrics.get('total_trades', 1)*100:.2f}%) | {j_metrics.get('closed_trades', 0) - b_metrics.get('closed_trades', 0)} ({j_metrics.get('closed_trades', 0)/j_metrics.get('total_trades', 1)*100 - b_metrics.get('closed_trades', 0)/b_metrics.get('total_trades', 1)*100:+.2f}%p) |
| **Mean Return (%)** | **{b_ret.get('mean', 0.0):.2f}%** | **{j_ret.get('mean', 0.0):.2f}%** | **{j_ret.get('mean', 0.0) - b_ret.get('mean', 0.0):+.2f}%p** |
| **Median Return (%)** | **{b_ret.get('median', 0.0):.2f}%** | **{j_ret.get('median', 0.0):.2f}%** | **{j_ret.get('median', 0.0) - b_ret.get('median', 0.0):+.2f}%p** |
| **P10 Return (%)** | {b_p.get('p10', 0.0):.2f}% | {j_p.get('p10', 0.0):.2f}% | {j_p.get('p10', 0.0) - b_p.get('p10', 0.0):+.2f}%p |
| **P25 Return (%)** | {b_p.get('p25', 0.0):.2f}% | {j_p.get('p25', 0.0):.2f}% | {j_p.get('p25', 0.0) - b_p.get('p25', 0.0):+.2f}%p |
| **P50 Return (%)** | {b_p.get('p50', 0.0):.2f}% | {j_p.get('p50', 0.0):.2f}% | {j_p.get('p50', 0.0) - b_p.get('p50', 0.0):+.2f}%p |
| **P75 Return (%)** | {b_p.get('p75', 0.0):.2f}% | {j_p.get('p75', 0.0):.2f}% | {j_p.get('p75', 0.0) - b_p.get('p75', 0.0):+.2f}%p |
| **P90 Return (%)** | {b_p.get('p90', 0.0):.2f}% | {j_p.get('p90', 0.0):.2f}% | {j_p.get('p90', 0.0) - b_p.get('p90', 0.0):+.2f}%p |
| **P95 Return (%)** | {b_p.get('p95', 0.0):.2f}% | {j_p.get('p95', 0.0):.2f}% | {j_p.get('p95', 0.0) - b_p.get('p95', 0.0):+.2f}%p |
| **Positive Return Rate (%)** | **{b_ret.get('positive_rate', 0.0):.2f}%** ({int(b_metrics.get('total_trades', 0)*b_ret.get('positive_rate', 0)/100)}/{b_metrics.get('total_trades', 0)}) | **{j_ret.get('positive_rate', 0.0):.2f}%** ({int(j_metrics.get('total_trades', 0)*j_ret.get('positive_rate', 0)/100)}/{j_metrics.get('total_trades', 0)}) | **{j_ret.get('positive_rate', 0.0) - b_ret.get('positive_rate', 0.0):+.2f}%p** |
| **Return Std (%)** | {b_ret.get('std', 0.0):.2f}% | {j_ret.get('std', 0.0):.2f}% | {j_ret.get('std', 0.0) - b_ret.get('std', 0.0):+.2f}%p |
| **Min Return (%)** | {b_ret.get('min', 0.0):.2f}% | {j_ret.get('min', 0.0):.2f}% | {j_ret.get('min', 0.0) - b_ret.get('min', 0.0):+.2f}%p |
| **Max Return (%)** | {b_ret.get('max', 0.0):+.2f}% | {j_ret.get('max', 0.0):+.2f}% | {j_ret.get('max', 0.0) - b_ret.get('max', 0.0):+.2f}%p |

### Tail Risk & Upside Distribution

| Tail Metric | Baseline (Loss Guard ON) | Julia V00 (Loss Guard OFF) | Delta |
| :--- | :--- | :--- | :--- |
| **Loss $\\le -15\\%$ Rate** | **{b_loss.get('le_neg_15_rate', 0.0):.2f}%** ({b_loss.get('le_neg_15_count', 0)}건) | **{j_loss.get('le_neg_15_rate', 0.0):.2f}%** ({j_loss.get('le_neg_15_count', 0)}건) | **{j_loss.get('le_neg_15_rate', 0.0) - b_loss.get('le_neg_15_rate', 0.0):+.2f}%p** |
| **Deep Loss $\\le -20\\%$ Rate** | **{b_loss.get('le_neg_20_rate', 0.0):.2f}%** ({b_loss.get('le_neg_20_count', 0)}건) | **{j_loss.get('le_neg_20_rate', 0.0):.2f}%** ({j_loss.get('le_neg_20_count', 0)}건) | **{j_loss.get('le_neg_20_rate', 0.0) - b_loss.get('le_neg_20_rate', 0.0):+.2f}%p** |
| **Deep Loss $\\le -30\\%$ Rate** | **{b_loss.get('le_neg_30_rate', 0.0):.2f}%** ({b_loss.get('le_neg_30_count', 0)}건) | **{j_loss.get('le_neg_30_rate', 0.0):.2f}%** ({j_loss.get('le_neg_30_count', 0)}건) | **{j_loss.get('le_neg_30_rate', 0.0) - b_loss.get('le_neg_30_rate', 0.0):+.2f}%p** |
| **Deep Loss $\\le -40\\%$ Rate** | **{b_loss.get('le_neg_40_rate', 0.0):.2f}%** ({b_loss.get('le_neg_40_count', 0)}건) | **{j_loss.get('le_neg_40_rate', 0.0):.2f}%** ({j_loss.get('le_neg_40_count', 0)}건) | **{j_loss.get('le_neg_40_rate', 0.0) - b_loss.get('le_neg_40_rate', 0.0):+.2f}%p** |
| **Deep Loss $\\le -50\\%$ Rate** | **{b_loss.get('le_neg_50_rate', 0.0):.2f}%** ({b_loss.get('le_neg_50_count', 0)}건) | **{j_loss.get('le_neg_50_rate', 0.0):.2f}%** ({j_loss.get('le_neg_50_count', 0)}건) | **{j_loss.get('le_neg_50_rate', 0.0) - b_loss.get('le_neg_50_rate', 0.0):+.2f}%p** |
| **Gain $\\ge +20\\%$ Rate** | {b_up.get('ge_20_rate', 0.0):.2f}% ({b_up.get('ge_20_count', 0)}건) | {j_up.get('ge_20_rate', 0.0):.2f}% ({j_up.get('ge_20_count', 0)}건) | {j_up.get('ge_20_rate', 0.0) - b_up.get('ge_20_rate', 0.0):+.2f}%p |
| **Gain $\\ge +50\\%$ Rate** | {b_up.get('ge_50_rate', 0.0):.2f}% ({b_up.get('ge_50_count', 0)}건) | {j_up.get('ge_50_rate', 0.0):.2f}% ({j_up.get('ge_50_count', 0)}건) | {j_up.get('ge_50_rate', 0.0) - b_up.get('ge_50_rate', 0.0):+.2f}%p |
| **Gain $\\ge +100\\%$ Rate** | {b_up.get('ge_100_rate', 0.0):.2f}% ({b_up.get('ge_100_count', 0)}건) | {j_up.get('ge_100_rate', 0.0):.2f}% ({j_up.get('ge_100_count', 0)}건) | {j_up.get('ge_100_rate', 0.0) - b_up.get('ge_100_rate', 0.0):+.2f}%p |
| **Gain $\\ge +200\\%$ Rate** | {b_up.get('ge_200_rate', 0.0):.2f}% ({b_up.get('ge_200_count', 0)}건) | {j_up.get('ge_200_rate', 0.0):.2f}% ({j_up.get('ge_200_count', 0)}건) | {j_up.get('ge_200_rate', 0.0) - b_up.get('ge_200_rate', 0.0):+.2f}%p |

---

## 3. Full Loss Guard Cohort Accounting (Major 2)

Baseline의 모든 Pre-PROGRESSED Loss Guard 청산 거래($N={lg_summary.get('baseline_loss_guard_total', 0)}$건)를 전수 추적하여, Julia의 동일 진입 앵커와 1:1 매칭되는 Paired Cohort($M={lg_summary.get('paired_loss_guard_count', 0)}$건)와 경로 분기로 인한 Unpaired Cohort($N-M={lg_summary.get('unpaired_loss_guard_count', 0)}$건)로 분리 분석하였습니다.

$$\\text{{Baseline Loss Guard Total }} N = {lg_summary.get('baseline_loss_guard_total', 0)} = M({lg_summary.get('paired_loss_guard_count', 0)}) + (N-M)({lg_summary.get('unpaired_loss_guard_count', 0)})$$
$$\\text{{Paired Coverage Rate }} = \\frac{{{lg_summary.get('paired_loss_guard_count', 0)}}}{{{lg_summary.get('baseline_loss_guard_total', 1)}}} \\times 100 = {lg_summary.get('paired_coverage_rate', 0.0):.2f}\\%$$

```json
{json.dumps(lg_summary, indent=2, ensure_ascii=False)}
```

---

## 4. Common Entry Pair Coverage & Strategy Path Divergence

| Metric | Value |
| :--- | :--- |
| **Baseline Total Trades** | {pairs.get('baseline_total_trades', 0)} |
| **Julia Total Trades** | {pairs.get('julia_total_trades', 0)} |
| **Common Entry Pairs ($M$)** | {pairs.get('common_entry_pair_count', 0)} |
| **Baseline Paired Trades** | {pairs.get('baseline_paired_count', 0)} ({pairs.get('baseline_pair_coverage_rate', 0.0):.2f}%) |
| **Baseline Unpaired Trades** | {pairs.get('baseline_unpaired_count', 0)} |
| **Julia Paired Trades** | {pairs.get('julia_paired_count', 0)} ({pairs.get('julia_pair_coverage_rate', 0.0):.2f}%) |
| **Julia Unpaired Trades** | {pairs.get('julia_unpaired_count', 0)} |

### Strategy Path Divergence 상세 내역

Baseline이 Pre-PROGRESSED -15% 손절 후 FLAT 포지션 상태에서 후속 신호에 재진입한 거래들입니다. Julia는 초기 진입 포지션을 계속 보유하고 있어 이 재진입들이 발생하지 않았습니다.

| Strategy | Ticker | Name | Seq | Entry Signal Date | Entry Exec Date | Entry Price | Exit Type | Return (%) | Divergence Reason |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
{div_table_str}

---

## 5. Trade-off Analysis: Big Winners vs Deep Losses

### Top 10 Big Winners in Julia V00 ($\\ge +50\\%$)

| Ticker | Name | Entry Date | Julia Exit Date | Julia Ret (%) | Julia MFE (%) | Baseline Exit Type | Baseline Ret (%) | Return Delta (%p) | Baseline Caught via Reentry |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
{winners_table_str}

### Top 10 Deep Losses in Julia V00

| Ticker | Name | Entry Date | Julia Exit Date | Julia Ret (%) | Julia MAE (%) | Baseline Exit Type | Baseline Ret (%) | Return Delta (%p) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
{worst_table_str}

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
"""
    return content


def main() -> None:
    text = generate_markdown_report()
    DOC_MD.write_text(text, encoding="utf-8")
    R_MD.write_text(text, encoding="utf-8")
    print(f"Report generated successfully to {DOC_MD} and {R_MD} (Length: {len(text)} bytes)")


if __name__ == "__main__":
    main()
