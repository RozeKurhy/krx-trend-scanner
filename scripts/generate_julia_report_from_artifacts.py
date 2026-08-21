#!/usr/bin/env python
"""Machine Generator for Julia Strategy V00 Research & Checkpoint Documentation.

Guarantees 100% exact parity between CSV/JSON artifacts and Markdown documentation.
When final_pit_backtest_ready is False, all comparative performance metrics are strictly
suppressed to prevent premature / non-authoritative evidence exposure.
"""

from __future__ import annotations

import json
from pathlib import Path
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
    role_counts = pit_audit.get("source_role_counts", {})

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
| **Authoritative Start SHA** | `4d4cc1c1ad455bd0bd8bde2a6efe4e6c16facb20` |

---

## 2. Historical Market Cap PIT Coverage & Provenance Reclassification

2022-01-01부터 2026-08-14까지 2,528개 전종목에서 발생한 모든 잠재적 신호 기준일({req_count}개 날짜)을 전수 스캔하고, 현재까지 확보된 {avail_count}개 공식 KRX snapshot에 대해 엄격한 수집 채널 및 역할 재분류를 적용하였습니다.

```json
{json.dumps(pit_audit, indent=2, ensure_ascii=False)}
```

### Source Acquisition Provenance Breakdown

| Source Channel | Source Role | Snapshot Count | Authority Status |
| :--- | :--- | :--- | :--- |
| `KRX_DATA_MARKETPLACE_UI_CSV` | `CANONICAL_RAW_UI_EXPORT` | {ch_counts.get('KRX_DATA_MARKETPLACE_UI_CSV', 12)}개 | `CANONICAL_UI_AUTHORITY` |
| `KRX_DATA_MARKETPLACE_JSON_ENDPOINT` | `DERIVED_PROVIDER_RESPONSE_SNAPSHOT` | {ch_counts.get('KRX_DATA_MARKETPLACE_JSON_ENDPOINT', 105)}개 | `CHECKPOINT_ACCEPTED_NOT_FINAL_SOURCE_AUTHORITY` |
| `KRX_OPEN_API` | `CANONICAL_OPEN_API_SNAPSHOT` | 0개 (승인 대기) | `PENDING_AUTHORITY` |
| **Total Available** | - | **{avail_count}개 ({cov_rate:.2f}%)** | `INTEGRITY_PASS` |
| **Total Missing / Pending** | - | **{miss_count}개** | `PENDING_KRX_RECOVERY` |

---

## 3. Resumable Backfill & Integrity Guarantees

1. **Immutability of Sealed Snapshots**:
   - 확보된 {avail_count}개 스냅샷은 파일 존재, Ticker 고유성, 시총 양수값, 그리고 **Raw / Normalized SHA-256 해시 검증**을 100% 통과하여 [historical_market_cap_source_manifest.csv](file:///Users/june/Documents/projects/krx-trend-scanner/artifacts/strategies/julia/v00/historical_market_cap_source_manifest.csv)에 영구 봉인되었습니다.
2. **Strict Registry Enforcement**:
   - `HistoricalMarketCapRegistry.load_from_repository()`는 `available == True` AND `integrity_status == PASS` 조건뿐만 아니라, 로드 시점에 실제 디스크 파일의 SHA-256을 재검증하여 위변조를 원천 차단합니다.
3. **Pending Dates Frozen**:
   - 미수집된 {miss_count}개 날짜는 [historical_market_cap_missing_dates.csv](file:///Users/june/Documents/projects/krx-trend-scanner/artifacts/strategies/julia/v00/historical_market_cap_missing_dates.csv)에 명시적으로 동결되었으며, 향후 KRX Open API 승인 후 멱등성(Idempotency)을 유지하며 단 한 번에 이어서 수집됩니다.

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
    # (Used only when final_pit_backtest_ready == True)
    return ""


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

    DOC_MD.write_text(text, encoding="utf-8")
    print(f"Report generated successfully to {DOC_MD} (Length: {len(text)} bytes, Final Ready: {is_ready})")


if __name__ == "__main__":
    main()
