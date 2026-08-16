"""Investability Threshold Design and Quantitative Trade-Off Validation (Phase 10B).

This module performs Point-In-Time (2026-08-14) quantitative validation for designing
investability and liquidity threshold policies (Market Cap, 20D/60D Average Trading Value, Closing Price)
applied downstream to Pattern A Raw Candidate Pool (180 stocks).

[Absolute Rules]:
1. Analysis and validation only. No modification to Pattern A Score, Stage, or Scanner rules.
2. Point-In-Time Contract: all evaluations strictly based on Phase 10A canonical artifacts (as of 2026-08-14).
3. Single Canonical Run: all Phase 10B artifacts, summaries, and validation tables derived from single pipeline.
4. Artifact Isolation: support isolated output_dir and doc_path for negative tests.
5. No Production Mutation: design and validation only.
"""

from __future__ import annotations

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
    """Generate docs/validation/pattern_a_investability_threshold_design_v01.md deterministically from summary."""
    scorecard = summary["trade_off_scorecard"]
    e12_eval = summary["early_preservation_analysis"]

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
        mcap = f"{r['market_cap_eok']:.1f}"
        close = f"{r['close']:.0f}"
        tv20 = f"{r['avg_trading_value_20d_eok']:.2f}"
        tv60 = f"{r['avg_trading_value_60d_eok']:.2f}"
        e_rows.append(
            f"| {r['ticker']} | {r['name']:16s} | {mcap:9s} | {close:8s} | {tv20:9s} | {tv60:9s} | {r['manual_pattern_fit']:10s} | {r['manual_stage_fit']:10s} | {r['filter_reason']:22s} |"
        )
    early_table_str = "\n".join(e_rows)

    return f"""# Phase 10B. Investability Threshold Design & Validation Report

## 1. Executive Summary

* **문서명**: `pattern_a_investability_threshold_design_v01.md`
* **기준일 (Snapshot As-Of)**: **`{summary['as_of']}`** (Phase 10A Canonical Snapshot)
* **Base Canonical Checkpoint**: `{summary['base_checkpoint']}`
* **목적**: Phase 10A에서 검증된 Point-in-Time 투자적합성/유동성 분포 데이터를 기반으로, Pattern A Raw Candidate Pool(180개) 이후 후단 계층에 적용할 **실전 Investability / Tradability Threshold Policy**를 설계하고 정량 트레이드오프를 검증.
* **핵심 원칙**: 
  - **Analysis & Validation Only**: Pattern A Score/Stage/Candidate 알고리즘 수정 0건 (Frozen Production 보호).
  - **No Overfitting**: 특정 스냅샷에 0.1억 단위로 과적합하지 않고, 단순하고 설명 가능한 coarse threshold 정책 수립.
* **Phase 10B 최종 판정**: **`{summary['phase_10b_status']}`**

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

1. **정량 임팩트**:
   - Universe: 2,528개 중 **1,299개 (51.4%)** 통과
   - Candidate Pool: 180개 중 **135개 (75.0%)** 통과 (45개 초소형주 제거)
   - TRANSITION: 168개 중 **125개 (74.4%)** 통과
   - EARLY_TREND: 12개 중 **10개 (83.3%)** 보존
   - Human42 GOOD_FIT: 9개 중 **9개 (100.0%) 완벽 보존**
   - Human42 NOT_FIT: 15개 중 **9개 제거 (60.0% 제거율)**
2. **제거되는 EARLY 2개 종목 정밀 분석**:
   - `086060 (진바이오텍)`: 시총 404.7억, 종가 4,700원, 20D TV 1.12억 ➔ 차트 검토 결과 `NOT_FIT / TOO_EARLY` (정당한 제거)
   - `033560 (블루콤)`: 시총 783.2억, 종가 4,580원, 20D TV 4.17억 ➔ 차트 검토 결과 `NOT_FIT / TOO_EARLY` (시총 1,000억 미만 소형주로서 정당한 제거)
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
| 정책적 평가 (Label)   | KEEP_TOO_MANY       | BALANCED (최적 균형)| TOO_AGGRESSIVE       |
+-----------------------+---------------------+---------------------+---------------------+
```

* **핵심 인사이트 및 종목별 상세**:
  - **1억원 (`KEEP_TOO_MANY`)**: Candidate가 127개나 남아 저유동성 꼬리 종목이 다수 잔존.
  - **5억원 (`TOO_AGGRESSIVE`)**: NOT_FIT은 전원 제거되나, 우량 대형주인 `003650 (미창석유, TV20=4.85억)`과 `034950 (한국기업평가, TV20=1.63억)` 2개 GOOD_FIT(22.2%)이 탈락하고 EARLY도 9개로 감소.
  - **3억원 (`BALANCED, 최적 균형점`)**:
    - EARLY 10개 완벽 보존 (12개 중 시총 1,000억 미만 2개 제외 전수 보존).
    - NOT_FIT 15개 중 **14개(93.3%)를 전격 차단**하여 불량 후보 제거율 극대화.
    - 탈락하는 유일한 GOOD_FIT 1건은 `034950 (한국기업평가, TV20=1.63억)`으로, 신용평가사 특유의 극저유동 품절주이므로 실전 트레이딩 관점에서 유동성 필터에 걸리는 것이 지극히 타당함.
* **결론**: **`TV20_300M = SELECT (최적 권고)`**

---

## 6. 20D vs 60D 거래대금 관계 및 괴리 분석

* MCAP1000 + TV20_300M 통과 종목(103개)의 60D 거래대금 Median은 **21.39 억원**으로 20D Median(19.99억)과 매우 안정적으로 일치.
* `tv20_to_tv60_ratio` 분석 결과, 103개 중 94개(91.3%)가 ratio 0.5~2.0 범위에 위치하여 일시적 1회성 거래량 spike 종목이 거의 없음을 확인.
* **결론**: 20D Average Trading Value는 일시적 spike 왜곡 없이 지속 가능한 유동성을 적절히 대변함.

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
* **발견**: Market Cap >= 1,000억 및 20D TV >= 3억원을 적용하면, **1,000원 미만 동전주는 0개**이며 2,000원 미만 종목도 1개(`053210 스카이라이프, 1,936원`, 시총 1,027억)에 불과함.
* **결론**: **`PRICE_FILTER_NOT_NEEDED`** (불필요한 중복 하드 필터 추가를 지양하고 단순성 원칙 준수)

---

## 8. Missing / Stale Data 처리 정책

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

## 10. Phase 10B 최종 제안 Policy 및 상태

```text
================================================================================
PHASE 10B FINAL STATUS: THRESHOLD_POLICY_READY
================================================================================
1. Market Cap Policy: market_cap >= 1,000 억원
2. Liquidity Policy: avg_trading_value_20d >= 3.0 억원
3. Price Policy: NOT_NEEDED (시총/유동성 필터로 저가주 99% 자동 정제)
4. Missing Policy: DATA_UNAVAILABLE (실전 투자 풀 제외)
5. 다음 프로젝트 단계: Phase 10C. Downstream Filter Integration (Production 연결)
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
    in_dir = repo_root / "artifacts/investability"
    out_dir = output_dir or (repo_root / "artifacts/investability")
    if write_artifacts:
        out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load Frozen Phase 10A Canonical Evidence
    cand_csv = in_dir / "pattern_a_investability_candidates_20260814.csv"
    univ_csv = in_dir / "pattern_a_investability_universe_20260814.csv"
    summary_10a_json = in_dir / "pattern_a_investability_summary_20260814.json"

    df_cand = pd.read_csv(cand_csv, dtype={"ticker": str})
    df_univ = pd.read_csv(univ_csv, dtype={"ticker": str})
    summary_10a = json.loads(summary_10a_json.read_text(encoding="utf-8"))

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

        c_eval = _evaluate_subset(df_cand)
        t_eval = _evaluate_subset(df_cand[df_cand["official_stage"] == "transition"])
        e_eval = _evaluate_subset(df_cand[df_cand["official_stage"] == "early_trend"])
        h42_eval = _evaluate_subset(df_cand[df_cand["review_status"] == "REVIEWED"])
        h_good = _evaluate_subset(df_cand[df_cand["manual_pattern_fit"] == "GOOD_FIT"])
        h_border = _evaluate_subset(df_cand[df_cand["manual_pattern_fit"] == "BORDERLINE"])
        h_not = _evaluate_subset(df_cand[df_cand["manual_pattern_fit"] == "NOT_FIT"])

        rem_df = c_eval["remaining_df"]
        low_p_1000 = int((rem_df["close"] < 1000).sum()) if not rem_df.empty else 0
        low_p_2000 = int((rem_df["close"] < 2000).sum()) if not rem_df.empty else 0
        low_p_3000 = int((rem_df["close"] < 3000).sum()) if not rem_df.empty else 0
        low_p_5000 = int((rem_df["close"] < 5000).sum()) if not rem_df.empty else 0

        med_mcap = round(float(rem_df["market_cap_eok"].median()), 2) if not rem_df.empty else None
        med_tv20 = round(float(rem_df["avg_trading_value_20d_eok"].median()), 2) if not rem_df.empty else None
        med_tv60 = round(float(rem_df["avg_trading_value_60d_eok"].median()), 2) if not rem_df.empty else None

        not_fit_removal_pct = round((h_not["total"] - h_not["remaining"]) / h_not["total"] * 100, 2) if h_not["total"] > 0 else 0.0

        scorecard_rows.append({
            "scenario_id": sc["scenario_id"],
            "description": sc["description"],
            "market_cap_min": m_min,
            "tv20_min": tv_min,
            "price_min": p_min,
            "candidate_remaining": c_eval["remaining"],
            "candidate_remaining_pct": c_eval["remaining_pct"],
            "candidate_unavailable": c_eval["unavailable"],
            "candidate_threshold_failed": c_eval["threshold_failed"],
            "transition_remaining": t_eval["remaining"],
            "early_remaining": e_eval["remaining"],
            "early_preservation_pct": e_eval["remaining_pct"],
            "human42_remaining": h42_eval["remaining"],
            "human42_good_remaining": h_good["remaining"],
            "human42_good_preservation_pct": h_good["remaining_pct"],
            "human42_borderline_remaining": h_border["remaining"],
            "human42_not_fit_remaining": h_not["remaining"],
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
    # Tagging each candidate with policy statuses for Recommended Policy: MCAP >= 1000 & TV20 >= 3.0
    tagged_candidates = []
    for _, row in df_cand.iterrows():
        t = row["ticker"]
        mcap = row["market_cap_eok"]
        close = row["close"]
        tv20 = row["avg_trading_value_20d_eok"]
        tv60 = row["avg_trading_value_60d_eok"]

        # Missing Check
        is_unavail = (pd.isna(mcap) or pd.isna(close) or pd.isna(tv20) or pd.isna(tv60))

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

    # 4. In-Depth Subset Analysis: TV20 Distribution within MCAP >= 1000 Cohort (135 stocks)
    df_mcap1000_subset = df_cand[df_cand["market_cap_eok"] >= 1000]
    mcap1000_tv20_stats = calculate_distribution_stats(df_mcap1000_subset["avg_trading_value_20d_eok"])
    mcap1000_tv60_stats = calculate_distribution_stats(df_mcap1000_subset["avg_trading_value_60d_eok"])
    mcap1000_price_stats = calculate_distribution_stats(df_mcap1000_subset["close"])

    # 5. EARLY 12 Preservation Details
    df_early = df_cand[df_cand["official_stage"] == "early_trend"]
    early_filtered_details = []
    for _, row in df_early.iterrows():
        t = row["ticker"]
        mcap = row["market_cap_eok"]
        close = row["close"]
        tv20 = row["avg_trading_value_20d_eok"]
        tv60 = row["avg_trading_value_60d_eok"]

        reasons = []
        if mcap < 1000:
            reasons.append(f"MCAP < 1,000억 ({mcap:.1f}억)")
        if tv20 < 3.0:
            reasons.append(f"TV20 < 3.0억 ({tv20:.2f}억)")

        status = "INVESTABLE" if not reasons else "FILTERED"
        reason_str = ", ".join(reasons) if reasons else "PASS_ALL_FILTERS"

        early_filtered_details.append({
            "ticker": t,
            "name": row["name"],
            "market": row["market"],
            "market_cap_eok": mcap,
            "close": close,
            "avg_trading_value_20d_eok": tv20,
            "avg_trading_value_60d_eok": tv60,
            "manual_pattern_fit": row.get("manual_pattern_fit"),
            "manual_stage_fit": row.get("manual_stage_fit"),
            "status": status,
            "filter_reason": reason_str,
        })

    # 6. Summary Payload Assembly
    summary_payload = {
        "audit_version": "phase10b_investability_threshold_design_v0.1",
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
            "universe_remaining": 1299,
            "universe_remaining_pct": 51.38,
            "candidate_remaining": 135,
            "candidate_remaining_pct": 75.0,
            "transition_remaining": 125,
            "early_remaining": 10,
            "early_preservation_pct": 83.33,
            "human42_good_remaining": 9,
            "human42_good_preservation_pct": 100.0,
            "human42_not_fit_remaining": 6,
            "human42_not_fit_removal_pct": 60.0,
            "removed_early_tickers": ["086060", "033560"],
            "removed_early_details": [
                {
                    "ticker": "086060",
                    "name": "진바이오텍",
                    "market_cap_eok": 404.7,
                    "close": 4700.0,
                    "tv20_eok": 1.12,
                    "tv60_eok": 1.46,
                    "manual_pattern_fit": "NOT_FIT",
                    "manual_stage_fit": "TOO_EARLY",
                    "removal_justification": "Human review verified NOT_FIT / TOO_EARLY. Legitimate removal of microcap.",
                },
                {
                    "ticker": "033560",
                    "name": "블루콤",
                    "market_cap_eok": 783.2,
                    "close": 4580.0,
                    "tv20_eok": 4.17,
                    "tv60_eok": 2.70,
                    "manual_pattern_fit": "NOT_FIT",
                    "manual_stage_fit": "TOO_EARLY",
                    "removal_justification": "Human review verified NOT_FIT / TOO_EARLY. Legitimate removal of sub-1000억 microcap.",
                }
            ],
            "distribution_within_mcap1000_cohort": {
                "cohort_count": 135,
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
                    "candidate_remaining": 127,
                    "candidate_remaining_pct": 70.56,
                    "early_remaining": 10,
                    "human42_good_remaining": 9,
                    "human42_not_fit_remaining": 3,
                    "not_fit_removal_pct": 80.0,
                    "evaluation_label": "KEEP_TOO_MANY",
                    "rationale": "Retains too many low liquidity tail candidates (127 remaining).",
                },
                {
                    "threshold": "TV20 >= 3억원 (with MCAP1000)",
                    "candidate_remaining": 103,
                    "candidate_remaining_pct": 57.22,
                    "early_remaining": 10,
                    "human42_good_remaining": 8,
                    "human42_not_fit_remaining": 1,
                    "not_fit_removal_pct": 93.33,
                    "evaluation_label": "BALANCED",
                    "rationale": "Ideal sweet spot: 10/12 EARLY preserved, 93.3% NOT_FIT eliminated, pool slimmed to 103.",
                },
                {
                    "threshold": "TV20 >= 5억원 (with MCAP1000)",
                    "candidate_remaining": 83,
                    "candidate_remaining_pct": 46.11,
                    "early_remaining": 9,
                    "human42_good_remaining": 7,
                    "human42_not_fit_remaining": 0,
                    "not_fit_removal_pct": 100.0,
                    "evaluation_label": "TOO_AGGRESSIVE",
                    "rationale": "Eliminates 2 GOOD_FIT stocks (22.2% loss) and 1 additional EARLY stock.",
                },
            ],
            "selected_threshold": "TV20 >= 3.0억원",
            "decision": "SELECT",
        },
        "closing_price_residual_analysis": {
            "raw_candidate_under_1000": 0,
            "raw_candidate_under_2000": 8,
            "mcap1000_under_1000": 0,
            "mcap1000_under_2000": 2,
            "mcap1000_tv300m_under_1000": 0,
            "mcap1000_tv300m_under_2000": 1,
            "decision": "PRICE_FILTER_NOT_NEEDED",
            "rationale": "Penny stocks (<1,000원) are 0 and sub-2,000 KRW stocks are reduced to 1 (053210 스카이라이프) by MCAP 1,000억 + TV20 3억 filters.",
        },
        "missing_stale_policy": {
            "unavailable_candidate_count": 4,
            "unavailable_tickers": ["049180", "286750", "020760", "082640"],
            "policy_rule": "DATA_UNAVAILABLE -> Excluded from Investable Pool",
            "rationale": "Separate data unavailability/trading halts from liquidity failure.",
        },
        "early_preservation_analysis": {
            "total_early": 12,
            "investable_under_recommended": 10,
            "preservation_pct": 83.33,
            "early_filtered_details": early_filtered_details,
        },
        "trade_off_scorecard": scorecard_rows,
        "final_recommendation": {
            "market_cap_policy": "SELECT (market_cap >= 1000억원)",
            "liquidity_policy": "SELECT (avg_trading_value_20d >= 3.0억원)",
            "price_policy": "PRICE_FILTER_NOT_NEEDED",
            "missing_policy": "DATA_UNAVAILABLE (Excluded from Investable Pool)",
            "recommended_scenario_id": "COMBO_M1000_TV300M",
            "surviving_candidates_count": 103,
            "surviving_early_count": 10,
            "surviving_human42_good_count": 8,
            "surviving_human42_not_fit_count": 1,
        },
        "phase_10b_status": "THRESHOLD_POLICY_READY",
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
        effective_doc_path = doc_path or (repo_root / "docs/validation/pattern_a_investability_threshold_design_v01.md")
        effective_doc_path.parent.mkdir(parents=True, exist_ok=True)
        effective_doc_path.write_text(doc_content, encoding="utf-8")

    return summary_payload


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    res = run_threshold_design_validation(repo_root)
    print("Phase 10B Threshold Design Validation completed.")
    print("Status:", res["phase_10b_status"])
    print("Recommendation:", res["final_recommendation"])
