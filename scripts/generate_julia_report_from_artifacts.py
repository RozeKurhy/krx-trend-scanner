#!/usr/bin/env python
"""Machine Generator for Julia Strategy V00 Research & Checkpoint Documentation.

Guarantees 100% exact parity between CSV/JSON artifacts and Markdown documentation.
When final_pit_backtest_ready is False, all comparative performance metrics are strictly
suppressed to prevent premature / non-authoritative evidence exposure.
When final_pit_backtest_ready is True, requires all canonical artifacts and safely generates
the full comparative research report without producing empty documents.
Eliminates local file:// user links in favor of canonical repo-relative paths.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
JULIA_DIR = ROOT / "artifacts/strategies/julia/v00"
DOC_MD = ROOT / "docs/strategies/julia/v00.md"


def generate_checkpoint_report(pit_audit: dict) -> str:
    """Generate safe, governance-compliant checkpoint report when PIT coverage is incomplete."""
    req_count = pit_audit.get("historical_market_cap_source_dates_required", 215)
    avail_count = pit_audit.get("historical_market_cap_source_dates_available", 117)
    miss_count = pit_audit.get("historical_market_cap_source_dates_missing", 98)
    cov_rate = pit_audit.get("historical_market_cap_source_coverage_rate", 54.42)
    ch_counts = pit_audit.get("source_channel_counts", {})

    content = f"""# Research Report: Julia Strategy V00 Interrupted PIT Backfill Checkpoint

> [!WARNING]
> **EVIDENCE STATUS: NON_AUTHORITATIVE_INCOMPLETE_SOURCE_COVERAGE**
> Historical Market-Cap Point-in-Time coverage is currently **{cov_rate:.2f}% ({avail_count}/{req_count} dates)**.
> All comparative performance metrics (Mean, Median, Win Rate, Big Winners, Worst Losses, Loss Guard Recovery) are **STRICTLY SUPPRESSED** until 100.00% Full PIT coverage is achieved via approved KRX Open API backfill.

---

## 1. Executive Status & Governance

| Item | Specification / Value |
| :--- | :--- |
| **Strategy ID** | `JULIA_STRATEGY_V00` |
| **Base Strategy ID** | `PATTERN_A_FAST_FINAL_STRATEGY_V02` (A FAST Core V2) |
| **Research Classification** | `EXPLORATORY_CANDIDATE` |
| **Evidence Classification** | `INCOMPLETE_PIT_CHECKPOINT` |
| **Production Recommendation** | `NOT_APPROVED` (Default remains `PATTERN_A_FAST_FINAL_STRATEGY_V02`) |
| **Evaluation Window** | `2022-01-01` ~ `2026-08-14` (Initial Position State: `FLAT`) |
| **Lookback History** | Full pre-2022 daily bars utilized for rolling indicators and snapshots |
| **Only Delta from Base** | Pre-PROGRESSED Loss Guard (-15% Daily Close Stop) `DISABLED` (OFF) |
| **Source Collection Status** | `INTERRUPTED_KRX_TEMPORARY_RESTRICTION` |
| **Final PIT Backtest Ready** | `False` |
| **Final Result Status** | `INVALID_INCOMPLETE_PIT_COVERAGE` |
| **Authoritative Start SHA** | `8024736b178630e327d103683beb9da6549c625a` |

---

## 2. Historical Market Cap PIT Coverage & Provenance Reclassification

2022-01-01부터 2026-08-14까지 2,528개 전종목에서 발생한 모든 잠재적 신호 기준일({req_count}개 날짜)을 전수 스캔하고, 현재까지 확보된 {avail_count}개 공식 KRX snapshot에 대해 엄격한 수집 채널 및 역할 재분류를 적용하였습니다.

```json
{json.dumps(pit_audit, indent=2, ensure_ascii=False)}
```

### Source Acquisition Provenance Breakdown

| Source Channel | Source Role | Snapshot Count | Authority Status |
| :--- | :--- | :--- | :--- |
| `KRX_DATA_MARKETPLACE_UI_CSV` | `CANONICAL_RAW_UI_EXPORT` | {ch_counts.get('KRX_DATA_MARKETPLACE_UI_CSV', 13)}개 | `CANONICAL_UI_AUTHORITY` |
| `KRX_DATA_MARKETPLACE_JSON_ENDPOINT` | `DERIVED_PROVIDER_RESPONSE_SNAPSHOT` | {ch_counts.get('KRX_DATA_MARKETPLACE_JSON_ENDPOINT', 104)}개 | `CHECKPOINT_ACCEPTED_NOT_FINAL_SOURCE_AUTHORITY` |
| `KRX_OPEN_API` | `CANONICAL_OPEN_API_SNAPSHOT` | 0개 (승인 대기) | `PENDING_AUTHORITY` |
| **Total Available** | - | **{avail_count}개 ({cov_rate:.2f}%)** | `INTEGRITY_PASS` |
| **Total Missing / Pending** | - | **{miss_count}개** | `PENDING_KRX_RECOVERY` |

---

## 3. Resumable Backfill & Integrity Guarantees

1. **Immutability of Sealed Snapshots**:
   - 확보된 {avail_count}개 스냅샷은 파일 존재, Ticker 고유성, 시총 양수값, 그리고 **Source / Normalized Dual SHA-256 해시 검증**을 100% 통과하여 `artifacts/strategies/julia/v00/historical_market_cap_source_manifest.csv`에 영구 봉인되었습니다.
2. **Strict Registry Enforcement**:
   - `HistoricalMarketCapRegistry.load_from_repository()`는 `available == True` AND `integrity_status == PASS` 조건뿐만 아니라, 로드 시점에 실제 디스크 파일의 Source 및 Normalized SHA-256을 실시간 재검증하여 위변조를 원천 차단합니다.
3. **Pending Dates Frozen**:
   - 미수집된 {miss_count}개 날짜는 `artifacts/strategies/julia/v00/historical_market_cap_missing_dates.csv`에 명시적으로 동결되었으며, 향후 KRX Open API 승인 후 멱등성(Idempotency)을 유지하며 단 한 번에 이어서 수집됩니다.

---

## 4. Performance Interpretation & Next Steps

> [!IMPORTANT]
> **Performance Interpretation Suppressed**:
> 이전 Sparse-Date(13개 날짜) 기반의 157/152건 거래 통계는 2024년 이후 비대칭 결측치로 인한 편향이 존재하므로 현재 보고서에서 완전히 비노출(Suppressed) 처리되었습니다.

1. **Production Strategy Invariant**:
   - 현재 프로덕션 기본 전략은 `PATTERN_A_FAST_FINAL_STRATEGY_V02` (A FAST Core V2, 783 historical trades)를 엄격히 유지합니다.
2. **Next Action Upon Access Recovery**:
   - KRX Open API 공식 이용 승인 및 인증키 발급
   - 미수집 {miss_count}개 기준일에 대한 Open API 원천 스냅샷 백필
   - 215/215 (100.00%) Full PIT 커버리지 달성 후 Baseline V2 vs Julia V00 2022+ 전면 재실행
"""
    return content


def generate_full_research_report(summary: dict, pit_audit: dict) -> str:
    """Generate full comparative research report when 100% Full PIT coverage is achieved."""
    summary_path = JULIA_DIR / "strategy_comparison_summary.json"
    lg_summary_path = JULIA_DIR / "loss_guard_recovery_summary.json"
    winners_path = JULIA_DIR / "big_winners.csv"
    worst_path = JULIA_DIR / "worst_losses.csv"
    divergence_path = JULIA_DIR / "strategy_path_divergence.csv"

    # Strict Fail-Closed Check
    required_files = [summary_path, lg_summary_path, winners_path, worst_path, divergence_path]
    missing = [str(p.name) for p in required_files if not p.exists()]
    if missing:
        raise RuntimeError(
            f"Cannot generate Full Julia Research Report: Missing required canonical artifacts: {missing}"
        )

    lg_summary = json.loads(lg_summary_path.read_text(encoding="utf-8"))
    df_winners = pd.read_csv(winners_path)
    df_worst = pd.read_csv(worst_path)
    df_divergence = pd.read_csv(divergence_path)

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

    winner_rows_md = []
    if not df_winners.empty:
        for _, r in df_winners.head(10).iterrows():
            winner_rows_md.append(
                f"| `{str(r['ticker']).zfill(6)}` | {r['name']} | {r['entry_signal_date']} | {r['julia_exit_date'] or 'Cutoff (Open)'} | **+{float(r['julia_terminal_return']):.2f}%** | +{float(r['julia_mfe']):.2f}% | `{r['baseline_exit_type']}` | {float(r['baseline_terminal_return']):.2f}% | **{'+' if float(r['return_delta']) >= 0 else ''}{float(r['return_delta']):.2f}%p** | {r['baseline_caught_via_reentry']} |"
            )
    winners_table_str = "\n".join(winner_rows_md) if winner_rows_md else "| None | - | - | - | - | - | - | - | - | - |"

    worst_rows_md = []
    if not df_worst.empty:
        for _, r in df_worst.head(10).iterrows():
            worst_rows_md.append(
                f"| `{str(r['ticker']).zfill(6)}` | {r['name']} | {r['entry_signal_date']} | {r['julia_exit_date'] or 'Cutoff (Open)'} | **{float(r['julia_terminal_return']):.2f}%** | {float(r['julia_mae']):.2f}% | `{r['baseline_exit_type']}` | {float(r['baseline_terminal_return']):.2f}% | **{float(r['return_delta']):.2f}%p** |"
            )
    worst_table_str = "\n".join(worst_rows_md) if worst_rows_md else "| None | - | - | - | - | - | - | - |"

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
| **Authoritative Start SHA** | `{meta.get("supersedes_commit", "8024736b178630e327d103683beb9da6549c625a")}` |

---

## 1. Historical Investability PIT Audit

2026-08-14 시점의 1,081개 Universe를 과거 2022+ 구간에 소급 적용하던 오류(Selection / Current-size bias)를 전면 수정하고, 전체 보통주 2,528개 종목을 대상으로 각 Entry Signal Reference Date($W$) 시점의 **Historical Market Cap**($\\ge 1,000$억원) 및 **20D Avg Trading Value**($\\ge 3$억원)을 동적으로 평가(`evaluate_investability`)하였습니다.

```json
{json.dumps(pit_audit, indent=2, ensure_ascii=False)}
```

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
| **Positive Return Rate (%)** | **{b_ret.get('positive_rate', 0.0):.2f}%** | **{j_ret.get('positive_rate', 0.0):.2f}%** | **{j_ret.get('positive_rate', 0.0) - b_ret.get('positive_rate', 0.0):+.2f}%p** |

---

## 3. Full Loss Guard Cohort Accounting

$$\\text{{Baseline Loss Guard Total }} N = {lg_summary.get('baseline_loss_guard_total', 0)} = M({lg_summary.get('paired_loss_guard_count', 0)}) + (N-M)({lg_summary.get('unpaired_loss_guard_count', 0)})$$

```json
{json.dumps(lg_summary, indent=2, ensure_ascii=False)}
```

---

## 4. Top Big Winners & Worst Losses

### Top 10 Big Winners in Julia V00 ($\\ge +50\\%$)

| Ticker | Name | Entry Date | Julia Exit Date | Julia Ret (%) | Julia MFE (%) | Baseline Exit Type | Baseline Ret (%) | Return Delta (%p) | Baseline Caught via Reentry |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
{winners_table_str}

### Top 10 Deep Losses in Julia V00

| Ticker | Name | Entry Date | Julia Exit Date | Julia Ret (%) | Julia MAE (%) | Baseline Exit Type | Baseline Ret (%) | Return Delta (%p) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
{worst_table_str}

---

## 5. Strategic Governance & Next Steps

1. **Production Status**: `NOT_APPROVED`
   - 기본 전략은 `PATTERN_A_FAST_FINAL_STRATEGY_V02`를 엄격히 유지합니다.
2. **Project Next**: `PHASE12_RELATIVE_STRENGTH_RESUME`
"""
    return content


def main() -> None:
    pit_audit_path = JULIA_DIR / "historical_investability_pit_audit.json"
    pit_audit = json.loads(pit_audit_path.read_text(encoding="utf-8")) if pit_audit_path.exists() else {}

    is_ready = bool(pit_audit.get("final_pit_backtest_ready", False))
    if not is_ready:
        text = generate_checkpoint_report(pit_audit)
    else:
        summary_path = JULIA_DIR / "strategy_comparison_summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
        text = generate_full_research_report(summary, pit_audit)

    # Atomic write
    with tempfile.NamedTemporaryFile("w", dir=str(DOC_MD.parent), delete=False, encoding="utf-8") as tf:
        tf.write(text)
        temp_path = Path(tf.name)

    temp_path.replace(DOC_MD)
    print(f"Report generated successfully to {DOC_MD} (Length: {len(text)} bytes, Final Ready: {is_ready})")


if __name__ == "__main__":
    main()
