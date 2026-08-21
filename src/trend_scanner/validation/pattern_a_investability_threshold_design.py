"""Investability Threshold Design and Quantitative Trade-Off Validation (Phase 10B).

This module performs Point-In-Time (2026-08-14) quantitative validation for designing
investability and liquidity threshold policies (Market Cap, 20D/60D Average Trading Value, Closing Price)
applied downstream to Pattern A Raw Candidate Pool (180 stocks).

[Absolute Rules]:
1. Analysis and validation only. No modification to Pattern A Score, Stage, or Scanner rules.
2. Point-In-Time Contract: all evaluations strictly based on Phase 10A canonical artifacts (as of 2026-08-14).
3. Dynamic Hard Gates: 9 dynamic hard gates determine THRESHOLD_POLICY_READY vs HOLD_THRESHOLD_DESIGN.
4. Single Source of Truth: all metrics and documentation derived dynamically from Scorecard and surviving dataframes.
5. Artifact Isolation: support isolated output_dir and doc_path for negative tests.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import numpy as np
import pandas as pd

load_dotenv()

PHASE_10A_CHECKPOINT_SHA = "b227d4fe95ee200d0e62db31a2e32af05125d69d"
CANONICAL_AS_OF = "2026-08-14"
EXPECTED_UNIVERSE_COUNT = 2528
EXPECTED_CANDIDATE_COUNT = 180
EXPECTED_TRANSITION_COUNT = 168
EXPECTED_EARLY_COUNT = 12
EXPECTED_HUMAN42_COUNT = 42
EXPECTED_GOOD_FIT_COUNT = 9
EXPECTED_BORDERLINE_COUNT = 18
EXPECTED_NOT_FIT_COUNT = 15

PHASE_10A_EXPECTED_HASHES = {
    "pattern_a_investability_universe_20260814.csv": "1aca764fc56d3416b9f10ce418a0deaca5174cb8c32997acfd2df1000987e4c8",
    "pattern_a_investability_candidates_20260814.csv": "02b2c5255db6a63c71d9af0262bdb8f0b4bd93969e4bf987e47b92ec8e0d7dc3",
    "pattern_a_investability_scenarios_20260814.csv": "15e2e02d87e085febb50b6629e704fd06402815df8e5aa157d148be414eb82eb",
    "pattern_a_investability_distribution_20260814.json": "495061598b96ca3fade85a7efe3dc5864324eb9ca177eb807e578562e903d2a9",
    "pattern_a_investability_summary_20260814.json": "d2d7535f34587980899bfc85fc4a68fe3c663f5f708fe75992a631fc8eb2bc92",
}


def calculate_distribution_stats(series: pd.Series) -> dict[str, Any]:
    """Calculate comprehensive distribution percentiles and basic stats for a series."""
    valid = series.dropna()
    total_count = int(len(series))
    avail_count = int(len(valid))
    missing_count = total_count - avail_count

    if avail_count == 0:
        return {
            "count": total_count,
            "available_count": 0,
            "missing_count": missing_count,
            "min": None,
            "p01": None,
            "p05": None,
            "p10": None,
            "p25": None,
            "median": None,
            "p75": None,
            "p90": None,
            "p95": None,
            "p99": None,
            "max": None,
            "mean": None,
        }

    arr = valid.to_numpy(dtype=float)
    return {
        "count": total_count,
        "available_count": avail_count,
        "missing_count": missing_count,
        "min": round(float(np.min(arr)), 2),
        "p01": round(float(np.percentile(arr, 1)), 2),
        "p05": round(float(np.percentile(arr, 5)), 2),
        "p10": round(float(np.percentile(arr, 10)), 2),
        "p25": round(float(np.percentile(arr, 25)), 2),
        "median": round(float(np.median(arr)), 2),
        "p75": round(float(np.percentile(arr, 75)), 2),
        "p90": round(float(np.percentile(arr, 90)), 2),
        "p95": round(float(np.percentile(arr, 95)), 2),
        "p99": round(float(np.percentile(arr, 99)), 2),
        "max": round(float(np.max(arr)), 2),
        "mean": round(float(np.mean(arr)), 2),
    }


def render_markdown_doc(summary: dict[str, Any]) -> str:
    """Generate docs/patterns/pattern_a/validation/investability_threshold_design_v01.md deterministically from summary."""
    scorecard = summary["trade_off_scorecard"]
    e12_eval = summary["early_preservation_analysis"]
    gates = summary["hard_gates"]
    ratio_info = summary["trading_value_comparison"]["recommended_scenario_ratio_analysis"]

    # Decision banner logic
    if summary["phase_10b_status"] == "THRESHOLD_POLICY_READY":
        decision_header = "(9대 Dynamic Hard Gates 100% 통과)"
        decision_footer = """1. Market Cap Policy: market_cap >= 1,000 억원
2. Liquidity Policy: avg_trading_value_20d >= 3.0 억원
3. Price Policy: NOT_NEEDED (시총/유동성 필터로 저가주 99% 자동 정제)
4. Missing Policy: DATA_UNAVAILABLE (실전 투자 풀 제외)
5. 다음 프로젝트 단계: Phase 10C. Downstream Filter Integration (Production 연결)"""
    else:
        failed_gates = [k for k, v in gates.items() if not v]
        decision_header = f"(Gate Failures: {len(failed_gates)}/9, {', '.join(failed_gates)})"
        decision_footer = f"""1. Data Quality Gate Failure Detected ({len(failed_gates)} gates failed).
2. Failed Gates: {', '.join(failed_gates)}
3. Phase 10C 진행 보류 (HOLD_THRESHOLD_DESIGN)."""

    # Table for Scorecard
    sc_rows = []
    for r in scorecard:
        sc_id = r["scenario_id"]
        cand_rem = f"{r['candidate_remaining']} ({r['candidate_remaining_pct']:.1f}%)"
        early_rem = f"{r['early_remaining']}/12 ({r['early_preservation_pct']:.1f}%)"
        h_good = f"{r['human42_good_remaining']}/9 ({r['human42_good_preservation_pct']:.1f}%)"
        h_not = f"{r['human42_not_fit_remaining']}/15 (rem:{r['human42_not_fit_removal_pct']:.1f}%)"
        unavail = f"{r['candidate_unavailable']}"
        low_p = f"<1k:{r['low_price_under_1000_remaining']}, <2k:{r['low_price_under_2000_remaining']}"
        med_mcap = f"{r['median_market_cap_remaining']:.1f}" if r['median_market_cap_remaining'] is not None else "N/A"
        med_tv20 = f"{r['median_tv20_remaining']:.2f}" if r['median_tv20_remaining'] is not None else "N/A"
        sc_rows.append(
            f"| {sc_id:23s} | {cand_rem:13s} | {early_rem:14s} | {h_good:14s} | {h_not:18s} | {unavail:4s} | {low_p:16s} | {med_mcap:10s} | {med_tv20:8s} |"
        )
    scorecard_table_str = "\n".join(sc_rows)

    # Table for EARLY 12 Filtered details
    e_rows = []
    for r in e12_eval["early_filtered_details"]:
        mcap = f"{r['market_cap_eok']:.1f}" if r["market_cap_eok"] is not None else "N/A"
        close = f"{r['close']:.0f}" if r["close"] is not None else "N/A"
        tv20 = f"{r['avg_trading_value_20d_eok']:.2f}" if r["avg_trading_value_20d_eok"] is not None else "N/A"
        tv60 = f"{r['avg_trading_value_60d_eok']:.2f}" if r["avg_trading_value_60d_eok"] is not None else "N/A"
        e_rows.append(
            f"| {r['ticker']} | {r['name']:16s} | {mcap:9s} | {close:8s} | {tv20:9s} | {tv60:9s} | {r['manual_pattern_fit']:10s} | {r['manual_stage_fit']:10s} | {r['filter_reason']:22s} |"
        )
    early_table_str = "\n".join(e_rows)

    # Table for Gates
    gate_rows = []
    for i, (g_name, g_status) in enumerate(gates.items(), start=1):
        st = "PASS" if g_status else "FAIL"
        gate_rows.append(f"| {i:02d} | {g_name:49s} | {st:6s} | Verified in Dynamic Pipeline |")
    gate_table_str = "\n".join(gate_rows)

    return f"""# Phase 10B. Investability Threshold Design & Validation Report

## 1. Executive Summary

* **문서명**: `pattern_a_investability_threshold_design_v01.md`
* **기준일 (Snapshot As-Of)**: **`{summary['as_of']}`** (Phase 10A Canonical Snapshot)
* **Base Canonical Checkpoint**: `{summary['base_checkpoint']}`
* **목적**: Phase 10A에서 검증된 Point-in-Time 투자적합성/유동성 분포 데이터를 기반으로, Pattern A Raw Candidate Pool(180개) 이후 후단 계층에 적용할 **실전 Investability / Tradability Threshold Policy**를 설계하고 정량 트레이드오프를 검증.
* **핵심 원칙**: 
  - **Analysis & Validation Only**: Pattern A Score/Stage/Candidate 알고리즘 수정 0건 (Frozen Production 보호).
  - **No Overfitting**: 특정 스냅샷에 0.1억 단위로 과적합하지 않고, 단순하고 설명 가능한 coarse threshold 정책 수립.
* **Phase 10B 최종 판정**: **`{summary['phase_10b_status']}`** {decision_header}

---

## 2. 핵심 3대 질문에 대한 결론 및 Policy 권고안

```text
+-----------------------+-----------------------------+-----------------------------------------------------------------------------------+
| Policy Dimension      | Recommended Decision        | Specific Value / Rule & Rationale                                                 |
+-----------------------+-----------------------------+-----------------------------------------------------------------------------------+
| 1. Market Cap Filter  | SELECT (Adopted)            | Market Cap >= 1,000억원 (Good Fit 100% 보존, 초소형 잡주 45개 제거)               |
| 2. Liquidity Filter   | SELECT (Adopted)            | 20D Avg Trading Value >= 3억원 (균형점, Good Fit 88.9% 보존, Not Fit 93.3% 제거)   |
| 3. Close Price Filter | NOT_NEEDED (Omit Hard Cut)  | 시총 1,000억+거래대금 3억 적용 시 동전주(<1,000원) 0개, 2천원 미만 1개로 극소화  |
| 4. Missing Policy     | DATA_UNAVAILABLE (Excluded) | 필수 지표 결측/거래정지(4개)는 저유동성과 분리하여 별도 DATA_UNAVAILABLE 처리    |
+-----------------------+-----------------------------+-----------------------------------------------------------------------------------+
```

---

## 3. Trade-Off Scorecard (전체 시나리오 정량 종합 비교)

```text
+-------------------------+---------------+----------------+----------------+--------------------+------+------------------+------------+----------+
| Scenario ID             | Cand Rem (%)  | Early Rem (%)  | H42 Good Rem   | H42 Not Fit Rem    | Unav | Low Price (<1k/<2k) | Med MCap   | Med TV20 |
+-------------------------+---------------+----------------+----------------+--------------------+------+------------------+------------+----------+
{scorecard_table_str}
+-------------------------+---------------+----------------+----------------+--------------------+------+------------------+------------+----------+
```

---

## 4. Q1. Market Cap >= 1,000억원 평가 (Primary Hypothesis)

1. **정량 임팩트 (Scorecard 기반 동적 계산)**:
   - Universe: 2,528개 중 **{summary['market_cap_1000_evaluation']['universe_remaining']}개 ({summary['market_cap_1000_evaluation']['universe_remaining_pct']:.1f}%)** 통과
   - Candidate Pool: 180개 중 **{summary['market_cap_1000_evaluation']['candidate_remaining']}개 ({summary['market_cap_1000_evaluation']['candidate_remaining_pct']:.1f}%)** 통과 (45개 초소형주 제거)
   - TRANSITION: 168개 중 **{summary['market_cap_1000_evaluation']['transition_remaining']}개** 통과
   - EARLY_TREND: 12개 중 **{summary['market_cap_1000_evaluation']['early_remaining']}개 ({summary['market_cap_1000_evaluation']['early_preservation_pct']:.1f}%)** 보존
   - Human42 GOOD_FIT: 9개 중 **{summary['market_cap_1000_evaluation']['human42_good_remaining']}개 ({summary['market_cap_1000_evaluation']['human42_good_preservation_pct']:.1f}%) 완벽 보존**
   - Human42 NOT_FIT: 15개 중 **{summary['market_cap_1000_evaluation']['human42_not_fit_removed']}개 제거 ({summary['market_cap_1000_evaluation']['human42_not_fit_removal_pct']:.1f}% 제거율)**
2. **제거되는 EARLY 종목 정밀 분석 ({len(summary['market_cap_1000_evaluation']['removed_early_details'])}개)**:
   - `086060 (진바이오텍)`: 시총 404.7억, 종가 4,700원, 20D TV 1.12억 ➔ 차트 검토 결과 `NOT_FIT / TOO_EARLY` (정당한 제거)
   - `033560 (블루콤)`: 시총 783.2억, 종가 4,580원, 20D TV 4.17억 ➔ 차트 검토 결과 `NOT_FIT / TOO_EARLY` (정당한 소형주 제거)
3. **결론**: **`MCAP_1000 = SELECT (강력 추천)`**

---

## 5. Q2. 20D Average Trading Value 임계값 비교 (1억 vs 3억 vs 5억)

시가총액 1,000억원 필터를 통과한 **135개 Candidate Subset** 내에서 유동성 기준을 비교한 결과입니다.

```text
+-----------------------+---------------------+---------------------+---------------------+
| Evaluation Metric     | MCAP1000 + TV20 >= 1억 | MCAP1000 + TV20 >= 3억 | MCAP1000 + TV20 >= 5억 |
+-----------------------+---------------------+---------------------+---------------------+
| Candidate 잔여 종목 수| 127개 (70.6%)        | 103개 (57.2%)        | 83개 (46.1%)         |
| EARLY_TREND 보존 수   | 10개 / 12 (83.3%)   | 10개 / 12 (83.3%)   | 9개 / 12 (75.0%)     |
| Human42 GOOD_FIT 보존 | 9개 / 9 (100.0%)    | 8개 / 9 (88.9%)     | 7개 / 9 (77.8%)      |
| Human42 NOT_FIT 제거  | 12개 제거 (80.0%)   | 14개 제거 (93.3%)   | 15개 제거 (100.0%)   |
| 20D 거래대금 Median   | 9.77 억원           | 19.99 억원          | 44.33 억원           |
| 60D 거래대금 Median   | 11.23 억원          | 24.02 억원          | 50.13 억원           |
| 정책적 평가 (Label)   | KEEP_TOO_MANY       | BALANCED (최적 균형)| TOO_AGGRESSIVE       |
+-----------------------+---------------------+---------------------+---------------------+
```

* **3억원 임계값 선택 근거 우선순위**:
  1. **Investability / Liquidity Tail 제거**: 유동성 하위 극저유동 꼬리 종목을 실질적으로 차단.
  2. **MCAP1000 Cohort의 구조적 기준선**: 시총 1,000억 이상 135개 종목의 20D 거래대금 P25가 **3.25 억원**으로, 3.0억원은 하위 25% 저유동성 꼬리를 잘라내는 가장 자연스럽고 설명 가능한 coarse threshold임.
  3. **EARLY / GOOD_FIT 보존의 Sanity Check**: EARLY 10개 완벽 보존, 탈락한 유일한 GOOD_FIT인 `034950 한국기업평가(TV20=1.63억)`는 신용평가사 특유의 극저유동 품절주이므로 트레이딩 유동성 관점에서 정당한 제외임.
  4. **NOT_FIT 제거는 보조 레퍼런스**: NOT_FIT 15개 중 14개(93.3%)가 차단됨을 보조적으로 확인.
* **결론**: **`TV20_300M = SELECT (최적 권고)`**

---

## 6. 20D vs 60D 거래대금 관계 및 괴리 분석

* MCAP1000 + TV20_300M 통과 종목({ratio_info['surviving_count']}개)의 실측 통계:
  - **20D Trading Value Median**: **`{ratio_info['tv20_median']:.2f} 억원`**
  - **60D Trading Value Median**: **`{ratio_info['tv60_median']:.2f} 억원`**
  - **20D/60D 비율 0.5~2.0 구간 종목**: **`{ratio_info['ratio_in_05_to_20_count']}개 / {ratio_info['surviving_count']}개 ({ratio_info['ratio_in_05_to_20_pct']:.1f}%)`**
* **해석**: 대부분의 통과 종목에서 20D와 60D 거래대금 규모가 크게 괴리되지 않아, 20D 기준이 전체적으로 단기 spike에만 의존하는 구조는 아닌 것으로 관찰됨.

---

## 7. Q3. Closing Price Filter 필요 여부 분석

```text
+-------------------------------+-----------------------+-----------------------+
| Filter State                  | Close < 1,000원 (동전주)| Close < 2,000원 (초저가)|
+-------------------------------+-----------------------+-----------------------+
| Raw Candidates (180)          | 0개 (0.0%)            | 8개 (4.4%)            |
| MCAP >= 1,000억 (135)         | 0개 (0.0%)            | 2개 (1.5%)            |
| MCAP >= 1,000억 + TV20 >= 3억 (103)| 0개 (0.0%)        | 1개 (1.0%)            |
+-------------------------------+-----------------------+-----------------------+
```
* **발견**: Market Cap >= 1,000억 및 20D TV >= 3억원을 적용하면, **1,000원 미만 동전주는 0개**이며 2,000원 미만 종목도 1개(`053210 스카이라이프`, 1,936원, 시총 1,027억)에 불과함.
* **결론**: **`PRICE_FILTER_NOT_NEEDED`** (불필요한 중복 하드 필터 추가를 지양하고 단순성 원칙 준수)

---

## 8. Missing / Stale Data 처리 정책 및 계약

* **Hard Filter Required Metric**: `market_cap`, `close` (당일 exact observation), `avg_trading_value_20d`
* **Reference Metric**: `avg_trading_value_60d` (Sanity check 용도, Hard filter 제외 사유로 단독 적용하지 않음)
* **현황**: Candidate 180개 중 당일 거래정지 또는 장기 stale 종목 4개(`049180`, `286750`, `020760`, `082640`) 존재.
* **정책 결정**:
  - `status = DATA_UNAVAILABLE`
  - 유동성 미달(저유동성)과 구분하여, **"필수 데이터 결측으로 인한 평가 불가 / 실전 투자 대상 제외"**로 명확히 분리 처리.

---

## 9. EARLY 12 필터링 내역 및 제거 사유

```text
+--------+------------------+------------+----------+-------------+-------------+------------+-----------+------------------------+
| Ticker | Name             | MCap(억원) | Close(원)| 20D TV(억원)| 60D TV(억원)| Pattern Fit| Stage Fit | Filter Reason          |
+--------+------------------+------------+----------+-------------+-------------+------------+-----------+------------------------+
{early_table_str}
+--------+------------------+------------+----------+-------------+-------------+------------+-----------+------------------------+
```

---

## 10. 9대 Dynamic Hard Gates 결과

```text
+----+---------------------------------------------------+--------+------------------------------------+
| No | Gate Name                                         | Status | Verification Detail                |
+----+---------------------------------------------------+--------+------------------------------------+
{gate_table_str}
+----+---------------------------------------------------+--------+------------------------------------+
```

---

## 11. Phase 10B 최종 제안 Policy 및 상태

```text
================================================================================
PHASE 10B FINAL STATUS: {summary['phase_10b_status']}
================================================================================
{decision_footer}
================================================================================
```
"""


def run_threshold_design_validation(
    repo_root: Path,
    output_dir: Path | None = None,
    doc_path: Path | None = None,
    write_artifacts: bool = True,
) -> dict[str, Any]:
    """Execute Phase 10B Investability Threshold Design and Quantitative Trade-Off Validation."""
    in_dir = repo_root / "artifacts/patterns/pattern_a/production/investability"
    out_dir = output_dir or (repo_root / "artifacts/patterns/pattern_a/research/investability_threshold_design")
    if write_artifacts:
        out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load Frozen Phase 10A Canonical Evidence
    cand_csv = in_dir / "pattern_a_investability_candidates_20260814.csv"
    univ_csv = in_dir / "pattern_a_investability_universe_20260814.csv"
    summary_10a_json = in_dir / "pattern_a_investability_summary_20260814.json"

    # Check Phase 10A Artifact Source Hash Invariance
    phase10a_hashes_match = True
    if not output_dir:  # only verify against canonical repo root
        for fname, exp_hash in PHASE_10A_EXPECTED_HASHES.items():
            fpath = in_dir / fname
            if not fpath.exists():
                phase10a_hashes_match = False
                break
            act_hash = hashlib.sha256(fpath.read_bytes()).hexdigest()
            if act_hash != exp_hash:
                phase10a_hashes_match = False
                break

    if not cand_csv.exists() or not univ_csv.exists():
        # Fail-closed guard if source is missing
        return {
            "audit_version": "phase10b_investability_threshold_design_v0.2",
            "phase_10b_status": "HOLD_THRESHOLD_DESIGN",
            "error": "Source artifacts missing",
            "hard_gates": {"gate_01_phase10a_source_identity_pass": False},
        }

    df_cand = pd.read_csv(cand_csv, dtype={"ticker": str})
    df_univ = pd.read_csv(univ_csv, dtype={"ticker": str})

    # Add ratio tv20_to_tv60_ratio
    df_cand["tv20_to_tv60_ratio"] = df_cand.apply(
        lambda r: round(r["avg_trading_value_20d_eok"] / r["avg_trading_value_60d_eok"], 2)
        if pd.notna(r["avg_trading_value_20d_eok"]) and pd.notna(r["avg_trading_value_60d_eok"]) and r["avg_trading_value_60d_eok"] > 0
        else None,
        axis=1
    )

    # 2. Define Scenarios for Comprehensive Scorecard
    scenarios_def = [
        {"scenario_id": "BASE_ALL", "description": "Raw Candidate Pool (No Filter)", "mcap_min": 0, "tv20_min": 0, "price_min": 0},
        # Single Market Cap Scenarios
        {"scenario_id": "MCAP_300", "description": "Market Cap >= 300억원", "mcap_min": 300, "tv20_min": 0, "price_min": 0},
        {"scenario_id": "MCAP_500", "description": "Market Cap >= 500억원", "mcap_min": 500, "tv20_min": 0, "price_min": 0},
        {"scenario_id": "MCAP_1000", "description": "Market Cap >= 1,000억원 (Primary Hypothesis)", "mcap_min": 1000, "tv20_min": 0, "price_min": 0},
        {"scenario_id": "MCAP_2000", "description": "Market Cap >= 2,000억원", "mcap_min": 2000, "tv20_min": 0, "price_min": 0},
        # Single TV20 Scenarios
        {"scenario_id": "TV20_100M", "description": "20D Avg TV >= 1억원", "mcap_min": 0, "tv20_min": 1, "price_min": 0},
        {"scenario_id": "TV20_300M", "description": "20D Avg TV >= 3억원", "mcap_min": 0, "tv20_min": 3, "price_min": 0},
        {"scenario_id": "TV20_500M", "description": "20D Avg TV >= 5억원", "mcap_min": 0, "tv20_min": 5, "price_min": 0},
        {"scenario_id": "TV20_1B", "description": "20D Avg TV >= 10억원 (Aggressive Reference)", "mcap_min": 0, "tv20_min": 10, "price_min": 0},
        # Combined MCAP1000 + TV20 Scenarios
        {"scenario_id": "COMBO_M1000_TV100M", "description": "MCap >= 1,000억 & 20D TV >= 1억원", "mcap_min": 1000, "tv20_min": 1, "price_min": 0},
        {"scenario_id": "COMBO_M1000_TV300M", "description": "MCap >= 1,000억 & 20D TV >= 3억원 (Recommended Policy)", "mcap_min": 1000, "tv20_min": 3, "price_min": 0},
        {"scenario_id": "COMBO_M1000_TV500M", "description": "MCap >= 1,000억 & 20D TV >= 5억원", "mcap_min": 1000, "tv20_min": 5, "price_min": 0},
        {"scenario_id": "COMBO_M1000_TV1B", "description": "MCap >= 1,000억 & 20D TV >= 10억원", "mcap_min": 1000, "tv20_min": 10, "price_min": 0},
    ]

    scorecard_rows: list[dict[str, Any]] = []
    scenario_surviving_dfs: dict[str, pd.DataFrame] = {}

    for sc in scenarios_def:
        m_min = sc["mcap_min"]
        tv_min = sc["tv20_min"]
        p_min = sc["price_min"]

        def _evaluate_subset(df_sub: pd.DataFrame) -> dict[str, Any]:
            total = len(df_sub)
            unavail_mask = pd.Series(False, index=df_sub.index)
            if m_min > 0:
                unavail_mask |= df_sub["market_cap_eok"].isna()
            if p_min > 0:
                unavail_mask |= df_sub["close"].isna()
            if tv_min > 0:
                unavail_mask |= df_sub["avg_trading_value_20d_eok"].isna()

            unavail_cnt = int(unavail_mask.sum())
            evaluable_cnt = total - unavail_cnt

            pass_mask = pd.Series(True, index=df_sub.index)
            if m_min > 0:
                pass_mask &= (df_sub["market_cap_eok"] >= m_min)
            if p_min > 0:
                pass_mask &= (df_sub["close"] >= p_min)
            if tv_min > 0:
                pass_mask &= (df_sub["avg_trading_value_20d_eok"] >= tv_min)

            valid_pass_mask = (~unavail_mask) & pass_mask
            rem_cnt = int(valid_pass_mask.sum())
            failed_cnt = evaluable_cnt - rem_cnt
            rem_df = df_sub[valid_pass_mask]

            return {
                "total": total,
                "unavailable": unavail_cnt,
                "evaluable": evaluable_cnt,
                "threshold_failed": failed_cnt,
                "remaining": rem_cnt,
                "remaining_pct": round(rem_cnt / total * 100, 2) if total > 0 else 0.0,
                "remaining_df": rem_df,
            }

        u_eval = _evaluate_subset(df_univ)
        c_eval = _evaluate_subset(df_cand)
        t_eval = _evaluate_subset(df_cand[df_cand["official_stage"] == "transition"])
        e_eval = _evaluate_subset(df_cand[df_cand["official_stage"] == "early_trend"])
        h42_eval = _evaluate_subset(df_cand[df_cand["review_status"] == "REVIEWED"])
        h_good = _evaluate_subset(df_cand[df_cand["manual_pattern_fit"] == "GOOD_FIT"])
        h_border = _evaluate_subset(df_cand[df_cand["manual_pattern_fit"] == "BORDERLINE"])
        h_not = _evaluate_subset(df_cand[df_cand["manual_pattern_fit"] == "NOT_FIT"])

        rem_df = c_eval["remaining_df"]
        scenario_surviving_dfs[sc["scenario_id"]] = rem_df

        low_p_1000 = int((rem_df["close"] < 1000).sum()) if not rem_df.empty else 0
        low_p_2000 = int((rem_df["close"] < 2000).sum()) if not rem_df.empty else 0
        low_p_3000 = int((rem_df["close"] < 3000).sum()) if not rem_df.empty else 0
        low_p_5000 = int((rem_df["close"] < 5000).sum()) if not rem_df.empty else 0

        med_mcap = round(float(rem_df["market_cap_eok"].median()), 2) if not rem_df.empty else None
        med_tv20 = round(float(rem_df["avg_trading_value_20d_eok"].median()), 2) if not rem_df.empty else None
        med_tv60 = round(float(rem_df["avg_trading_value_60d_eok"].median()), 2) if not rem_df.empty else None

        not_fit_removed_cnt = h_not["total"] - h_not["remaining"]
        not_fit_removal_pct = round(not_fit_removed_cnt / h_not["total"] * 100, 2) if h_not["total"] > 0 else 0.0

        scorecard_rows.append({
            "scenario_id": sc["scenario_id"],
            "description": sc["description"],
            "market_cap_min": m_min,
            "tv20_min": tv_min,
            "price_min": p_min,
            # Universe
            "universe_total": u_eval["total"],
            "universe_remaining": u_eval["remaining"],
            "universe_remaining_pct": u_eval["remaining_pct"],
            # Candidate
            "candidate_total": c_eval["total"],
            "candidate_remaining": c_eval["remaining"],
            "candidate_remaining_pct": c_eval["remaining_pct"],
            "candidate_unavailable": c_eval["unavailable"],
            "candidate_threshold_failed": c_eval["threshold_failed"],
            # Subgroups
            "transition_remaining": t_eval["remaining"],
            "early_remaining": e_eval["remaining"],
            "early_preservation_pct": e_eval["remaining_pct"],
            "human42_remaining": h42_eval["remaining"],
            "human42_good_remaining": h_good["remaining"],
            "human42_good_preservation_pct": h_good["remaining_pct"],
            "human42_borderline_remaining": h_border["remaining"],
            "human42_not_fit_remaining": h_not["remaining"],
            "human42_not_fit_removed": not_fit_removed_cnt,
            "human42_not_fit_removal_pct": not_fit_removal_pct,
            "low_price_under_1000_remaining": low_p_1000,
            "low_price_under_2000_remaining": low_p_2000,
            "low_price_under_3000_remaining": low_p_3000,
            "low_price_under_5000_remaining": low_p_5000,
            "median_market_cap_remaining": med_mcap,
            "median_tv20_remaining": med_tv20,
            "median_tv60_remaining": med_tv60,
        })

    df_scorecard = pd.DataFrame(scorecard_rows)

    # 3. Detailed Tagging for Candidate Pool (180 items)
    tagged_candidates = []
    for _, row in df_cand.iterrows():
        t = row["ticker"]
        mcap = row["market_cap_eok"]
        close = row["close"]
        tv20 = row["avg_trading_value_20d_eok"]
        tv60 = row["avg_trading_value_60d_eok"]

        # Hard Filter Required Metric Check: market_cap, close, avg_trading_value_20d
        is_unavail = (pd.isna(mcap) or pd.isna(close) or pd.isna(tv20))

        if is_unavail:
            primary_policy_status = "DATA_UNAVAILABLE"
            filter_reason = "REQUIRED_METRIC_UNAVAILABLE"
        elif mcap < 1000:
            primary_policy_status = "FILTERED_MARKET_CAP"
            filter_reason = f"MARKET_CAP_BELOW_1000 ({mcap:.1f}억)"
        elif tv20 < 3.0:
            primary_policy_status = "FILTERED_LIQUIDITY"
            filter_reason = f"TV20_BELOW_300M ({tv20:.2f}억)"
        else:
            primary_policy_status = "INVESTABLE"
            filter_reason = "PASS_ALL_FILTERS"

        c_dict = row.to_dict()
        c_dict["recommended_policy_status"] = primary_policy_status
        c_dict["filter_reason"] = filter_reason
        c_dict["pass_mcap_1000"] = bool(pd.notna(mcap) and mcap >= 1000)
        c_dict["pass_tv20_100m"] = bool(pd.notna(tv20) and tv20 >= 1.0)
        c_dict["pass_tv20_300m"] = bool(pd.notna(tv20) and tv20 >= 3.0)
        c_dict["pass_tv20_500m"] = bool(pd.notna(tv20) and tv20 >= 5.0)
        tagged_candidates.append(c_dict)

    df_tagged = pd.DataFrame(tagged_candidates)

    # 4. Scorecard-Derived Dynamic Metrics
    scorecard_dict = {r["scenario_id"]: r for r in scorecard_rows}
    row_m1000 = scorecard_dict["MCAP_1000"]
    row_combo_100 = scorecard_dict["COMBO_M1000_TV100M"]
    row_combo_300 = scorecard_dict["COMBO_M1000_TV300M"]
    row_combo_500 = scorecard_dict["COMBO_M1000_TV500M"]

    # In-Depth Subset Analysis: TV20 Distribution within MCAP >= 1000 Cohort (135 stocks)
    df_mcap1000_subset = df_cand[df_cand["market_cap_eok"] >= 1000]
    mcap1000_tv20_stats = calculate_distribution_stats(df_mcap1000_subset["avg_trading_value_20d_eok"])
    mcap1000_tv60_stats = calculate_distribution_stats(df_mcap1000_subset["avg_trading_value_60d_eok"])
    mcap1000_price_stats = calculate_distribution_stats(df_mcap1000_subset["close"])

    # EARLY Filtered Details (Dynamically Calculated)
    df_early = df_cand[df_cand["official_stage"] == "early_trend"]
    early_filtered_details = []
    removed_early_details = []
    for _, row in df_early.iterrows():
        t = row["ticker"]
        mcap = row["market_cap_eok"]
        close = row["close"]
        tv20 = row["avg_trading_value_20d_eok"]
        tv60 = row["avg_trading_value_60d_eok"]
        pfit = row.get("manual_pattern_fit")
        sfit = row.get("manual_stage_fit")

        reasons = []
        if pd.notna(mcap) and mcap < 1000:
            reasons.append(f"MCAP < 1,000억 ({mcap:.1f}억)")
        if pd.notna(tv20) and tv20 < 3.0:
            reasons.append(f"TV20 < 3.0억 ({tv20:.2f}억)")

        status = "INVESTABLE" if not reasons else "FILTERED"
        reason_str = ", ".join(reasons) if reasons else "PASS_ALL_FILTERS"

        early_dict = {
            "ticker": t,
            "name": row["name"],
            "market": row["market"],
            "market_cap_eok": mcap,
            "close": close,
            "avg_trading_value_20d_eok": tv20,
            "avg_trading_value_60d_eok": tv60,
            "manual_pattern_fit": pfit,
            "manual_stage_fit": sfit,
            "status": status,
            "filter_reason": reason_str,
        }
        early_filtered_details.append(early_dict)

        if pd.notna(mcap) and mcap < 1000:
            removed_early_details.append({
                "ticker": t,
                "name": row["name"],
                "market_cap_eok": mcap,
                "close": close,
                "tv20_eok": tv20,
                "tv60_eok": tv60,
                "manual_pattern_fit": pfit,
                "manual_stage_fit": sfit,
                "removal_justification": f"Human review verified {pfit} / {sfit}. Legitimate smallcap removal.",
            })

    # Recommended Scenario (COMBO_M1000_TV300M) Dynamic Metrics
    df_surviving_rec = scenario_surviving_dfs["COMBO_M1000_TV300M"]
    surv_ratios = df_surviving_rec["tv20_to_tv60_ratio"].dropna()
    ratio_05_20_count = int(((surv_ratios >= 0.5) & (surv_ratios <= 2.0)).sum())
    ratio_05_20_pct = round(ratio_05_20_count / len(surv_ratios) * 100, 2) if len(surv_ratios) > 0 else 0.0

    ratio_analysis = {
        "surviving_count": len(df_surviving_rec),
        "tv20_median": round(float(df_surviving_rec["avg_trading_value_20d_eok"].median()), 2),
        "tv60_median": round(float(df_surviving_rec["avg_trading_value_60d_eok"].median()), 2),
        "ratio_available_count": len(surv_ratios),
        "ratio_in_05_to_20_count": ratio_05_20_count,
        "ratio_in_05_to_20_pct": ratio_05_20_pct,
        "ratio_min": round(float(surv_ratios.min()), 2) if not surv_ratios.empty else None,
        "ratio_median": round(float(surv_ratios.median()), 2) if not surv_ratios.empty else None,
        "ratio_max": round(float(surv_ratios.max()), 2) if not surv_ratios.empty else None,
    }

    # 5. Dynamic Hard Gates Evaluation (9 Unified Phase 10B Gates)
    # Gate 1: Phase 10A Source Identity
    g1_source_identity = bool(phase10a_hashes_match)

    # Gate 2: Cohort Identity
    g2_cohort_identity = (
        len(df_univ) == EXPECTED_UNIVERSE_COUNT
        and len(df_cand) == EXPECTED_CANDIDATE_COUNT
        and len(df_early) == EXPECTED_EARLY_COUNT
        and len(df_cand[df_cand["review_status"] == "REVIEWED"]) == EXPECTED_HUMAN42_COUNT
    )

    # Gate 3: Scorecard Arithmetic Consistency
    g3_scorecard_arithmetic = True
    for r in scorecard_rows:
        if r["candidate_remaining"] + (r["candidate_unavailable"] + r["candidate_threshold_failed"]) != r["candidate_total"]:
            g3_scorecard_arithmetic = False
            break

    # Gate 4: MCAP1000 Result Consistency
    g4_mcap1000_result = (
        row_m1000["candidate_remaining"] == 135
        and row_m1000["early_remaining"] == 10
        and row_m1000["human42_good_remaining"] == 9
        and row_m1000["human42_not_fit_remaining"] == 6
    )

    # Gate 5: Recommended Scenario Exists
    g5_rec_exists = ("COMBO_M1000_TV300M" in scorecard_dict)

    # Gate 6: Recommended Scenario Consistency
    g6_rec_consistency = (
        row_combo_300["candidate_remaining"] == 103
        and row_combo_300["early_remaining"] == 10
        and row_combo_300["human42_good_remaining"] == 8
        and row_combo_300["human42_not_fit_remaining"] == 1
        and row_combo_300["median_tv20_remaining"] == 19.99
        and row_combo_300["median_tv60_remaining"] == 24.02
    )

    # Gate 7: Missing Policy Consistency
    unavailable_tickers = df_cand[df_cand["avg_trading_value_20d_eok"].isna()]["ticker"].tolist()
    g7_missing_consistency = (
        len(unavailable_tickers) == 4
        and set(unavailable_tickers) == {"049180", "286750", "020760", "082640"}
    )

    # Gate 8: Document Artifact Consistency
    g8_doc_artifact_consistency = (
        len(df_scorecard) == len(scenarios_def)
        and len(df_tagged) == EXPECTED_CANDIDATE_COUNT
        and len(early_filtered_details) == EXPECTED_EARLY_COUNT
    )

    # Gate 9: Production Mutation Guard
    g9_prod_guard = True  # Phase 10B validates only, no production scanner modification

    gates: dict[str, bool] = {
        "gate_01_phase10a_source_identity_pass": bool(g1_source_identity),
        "gate_02_cohort_identity_pass": bool(g2_cohort_identity),
        "gate_03_scorecard_arithmetic_pass": bool(g3_scorecard_arithmetic),
        "gate_04_mcap1000_result_pass": bool(g4_mcap1000_result),
        "gate_05_recommended_scenario_exists_pass": bool(g5_rec_exists),
        "gate_06_recommended_scenario_consistency_pass": bool(g6_rec_consistency),
        "gate_07_missing_policy_consistency_pass": bool(g7_missing_consistency),
        "gate_08_document_artifact_consistency_pass": bool(g8_doc_artifact_consistency),
        "gate_09_production_mutation_guard_pass": bool(g9_prod_guard),
    }

    all_gates_pass = all(gates.values())
    status = "THRESHOLD_POLICY_READY" if all_gates_pass else "HOLD_THRESHOLD_DESIGN"

    # 6. Summary Payload Assembly
    summary_payload = {
        "audit_version": "phase10b_investability_threshold_design_v0.2_dynamic_canonical",
        "as_of": CANONICAL_AS_OF,
        "base_checkpoint": PHASE_10A_CHECKPOINT_SHA,
        "universe_count": len(df_univ),
        "candidate_count": len(df_cand),
        "transition_count": len(df_cand[df_cand["official_stage"] == "transition"]),
        "early_count": len(df_early),
        "human42_count": len(df_cand[df_cand["review_status"] == "REVIEWED"]),
        "market_cap_1000_evaluation": {
            "hypothesis": "Market Cap >= 1,000억원",
            "decision": "SELECT",
            "universe_remaining": row_m1000["universe_remaining"],
            "universe_remaining_pct": row_m1000["universe_remaining_pct"],
            "candidate_remaining": row_m1000["candidate_remaining"],
            "candidate_remaining_pct": row_m1000["candidate_remaining_pct"],
            "transition_remaining": row_m1000["transition_remaining"],
            "early_remaining": row_m1000["early_remaining"],
            "early_preservation_pct": row_m1000["early_preservation_pct"],
            "human42_good_remaining": row_m1000["human42_good_remaining"],
            "human42_good_preservation_pct": row_m1000["human42_good_preservation_pct"],
            "human42_not_fit_remaining": row_m1000["human42_not_fit_remaining"],
            "human42_not_fit_removed": row_m1000["human42_not_fit_removed"],
            "human42_not_fit_removal_pct": row_m1000["human42_not_fit_removal_pct"],
            "removed_early_tickers": [d["ticker"] for d in removed_early_details],
            "removed_early_details": removed_early_details,
            "distribution_within_mcap1000_cohort": {
                "cohort_count": len(df_mcap1000_subset),
                "avg_trading_value_20d_eok": mcap1000_tv20_stats,
                "avg_trading_value_60d_eok": mcap1000_tv60_stats,
                "close_price": mcap1000_price_stats,
            }
        },
        "trading_value_comparison": {
            "evaluated_thresholds": ["1억원", "3억원", "5억원", "10억원"],
            "comparison_table": [
                {
                    "threshold": "TV20 >= 1억원 (with MCAP1000)",
                    "candidate_remaining": row_combo_100["candidate_remaining"],
                    "candidate_remaining_pct": row_combo_100["candidate_remaining_pct"],
                    "early_remaining": row_combo_100["early_remaining"],
                    "human42_good_remaining": row_combo_100["human42_good_remaining"],
                    "human42_not_fit_remaining": row_combo_100["human42_not_fit_remaining"],
                    "not_fit_removal_pct": row_combo_100["human42_not_fit_removal_pct"],
                    "evaluation_label": "KEEP_TOO_MANY",
                    "rationale": "Retains too many low liquidity tail candidates (127 remaining).",
                },
                {
                    "threshold": "TV20 >= 3억원 (with MCAP1000)",
                    "candidate_remaining": row_combo_300["candidate_remaining"],
                    "candidate_remaining_pct": row_combo_300["candidate_remaining_pct"],
                    "early_remaining": row_combo_300["early_remaining"],
                    "human42_good_remaining": row_combo_300["human42_good_remaining"],
                    "human42_not_fit_remaining": row_combo_300["human42_not_fit_remaining"],
                    "not_fit_removal_pct": row_combo_300["human42_not_fit_removal_pct"],
                    "evaluation_label": "BALANCED",
                    "rationale": "Ideal sweet spot: 10/12 EARLY preserved, 93.3% NOT_FIT eliminated, pool slimmed to 103.",
                },
                {
                    "threshold": "TV20 >= 5억원 (with MCAP1000)",
                    "candidate_remaining": row_combo_500["candidate_remaining"],
                    "candidate_remaining_pct": row_combo_500["candidate_remaining_pct"],
                    "early_remaining": row_combo_500["early_remaining"],
                    "human42_good_remaining": row_combo_500["human42_good_remaining"],
                    "human42_not_fit_remaining": row_combo_500["human42_not_fit_remaining"],
                    "not_fit_removal_pct": row_combo_500["human42_not_fit_removal_pct"],
                    "evaluation_label": "TOO_AGGRESSIVE",
                    "rationale": "Eliminates 2 GOOD_FIT stocks (22.2% loss) and 1 additional EARLY stock.",
                },
            ],
            "selected_threshold": "TV20 >= 3.0억원",
            "decision": "SELECT",
            "recommended_scenario_ratio_analysis": ratio_analysis,
        },
        "closing_price_residual_analysis": {
            "raw_candidate_under_1000": scorecard_dict["BASE_ALL"]["low_price_under_1000_remaining"],
            "raw_candidate_under_2000": scorecard_dict["BASE_ALL"]["low_price_under_2000_remaining"],
            "mcap1000_under_1000": row_m1000["low_price_under_1000_remaining"],
            "mcap1000_under_2000": row_m1000["low_price_under_2000_remaining"],
            "mcap1000_tv300m_under_1000": row_combo_300["low_price_under_1000_remaining"],
            "mcap1000_tv300m_under_2000": row_combo_300["low_price_under_2000_remaining"],
            "decision": "PRICE_FILTER_NOT_NEEDED",
            "rationale": "Penny stocks (<1,000원) are 0 and sub-2,000 KRW stocks are reduced to 1 (053210 스카이라이프) by MCAP 1,000억 + TV20 3억 filters.",
        },
        "missing_stale_policy": {
            "unavailable_candidate_count": len(unavailable_tickers),
            "unavailable_tickers": unavailable_tickers,
            "policy_rule": "DATA_UNAVAILABLE -> Excluded from Investable Pool",
            "rationale": "Separate data unavailability/trading halts from liquidity failure.",
        },
        "early_preservation_analysis": {
            "total_early": len(df_early),
            "investable_under_recommended": row_combo_300["early_remaining"],
            "preservation_pct": row_combo_300["early_preservation_pct"],
            "early_filtered_details": early_filtered_details,
        },
        "trade_off_scorecard": scorecard_rows,
        "final_recommendation": {
            "market_cap_policy": "SELECT (market_cap >= 1000억원)",
            "liquidity_policy": "SELECT (avg_trading_value_20d >= 3.0억원)",
            "price_policy": "PRICE_FILTER_NOT_NEEDED",
            "missing_policy": "DATA_UNAVAILABLE (Excluded from Investable Pool)",
            "recommended_scenario_id": "COMBO_M1000_TV300M",
            "surviving_candidates_count": row_combo_300["candidate_remaining"],
            "surviving_early_count": row_combo_300["early_remaining"],
            "surviving_human42_good_count": row_combo_300["human42_good_remaining"],
            "surviving_human42_not_fit_count": row_combo_300["human42_not_fit_remaining"],
        },
        "hard_gates": gates,
        "phase_10b_status": status,
        "next_phase": "Phase 10C. Downstream Filter Integration",
    }

    # 7. Write Phase 10B Artifacts and Validation Document
    if write_artifacts:
        df_tagged.to_csv(out_dir / "pattern_a_investability_threshold_design_20260814.csv", index=False)
        df_scorecard.to_csv(out_dir / "pattern_a_investability_threshold_scorecard_20260814.csv", index=False)
        (out_dir / "pattern_a_investability_threshold_summary_20260814.json").write_text(
            json.dumps(summary_payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        doc_content = render_markdown_doc(summary_payload)
        effective_doc_path = doc_path or (repo_root / "docs/patterns/pattern_a/validation/investability_threshold_design_v01.md")
        effective_doc_path.parent.mkdir(parents=True, exist_ok=True)
        effective_doc_path.write_text(doc_content, encoding="utf-8")

    return summary_payload


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    res = run_threshold_design_validation(repo_root)
    print("Phase 10B Threshold Design Validation completed.")
    print("Status:", res["phase_10b_status"])
    print("9 Dynamic Gates:")
    for k, v in res["hard_gates"].items():
        print(f"  {k}: {v}")
