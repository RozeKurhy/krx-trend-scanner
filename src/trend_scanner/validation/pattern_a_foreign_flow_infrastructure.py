"""Phase 11. Foreign Flow Confirmation Infrastructure Validation Suite.

Pattern A 및 Investability Filter를 통과한 종목군에 대해 Point-In-Time 외국인 수급
확증 인프라(1D/5D/20D/60D Signed Flow, Normalized Intensity, Positive Days, Readiness)를
검증하고 10대 Dynamic Hard Gates 및 Canonical Artifacts를 생성한다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.foreign_flow_provider import compute_file_sha256
from trend_scanner.filters.investability import InvestabilityStatus
from trend_scanner.flow.foreign_flow import (
    FlowDataStatus,
    ForeignFlowFeatureResult,
    compute_foreign_flow_features,
)
from trend_scanner.patterns.pattern_a_evaluator import PatternACandidateState
from trend_scanner.patterns.pattern_a_feature_set import PatternAStage
from trend_scanner.scanner.full_universe_scanner import (
    PatternAUniverseScanResult,
    scan_pattern_a_universe,
)

logger = logging.getLogger(__name__)

CANONICAL_AS_OF = "2026-08-14"
BASE_CHECKPOINT_SHA = "75afa32fe29608dbca0b0a60bf902f538fdb2c0b"

EXPECTED_UNIVERSE_COUNT = 2528
EXPECTED_RAW_CANDIDATES = 180
EXPECTED_TRANSITION_COUNT = 168
EXPECTED_EARLY_COUNT = 12

EXPECTED_INVESTABLE_COUNT = 103
EXPECTED_FILTERED_MARKET_CAP_COUNT = 42
EXPECTED_FILTERED_LIQUIDITY_COUNT = 31
EXPECTED_DATA_UNAVAILABLE_COUNT = 4


def _read_pytest_report(repo_root: Path) -> tuple[int, int, int]:
    """Read machine-readable pytest report artifact with strict fail-closed semantics."""
    report_file = repo_root / ".pytest_results" / "report.json"
    if not report_file.exists():
        return -1, -1, -1
    try:
        data = json.loads(report_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return -1, -1, -1
        required_keys = ("exit_code", "failed", "blocking_failed", "passed")
        for k in required_keys:
            if k not in data:
                return -1, -1, -1
        exit_code = int(data["exit_code"])
        failed = int(data["failed"])
        blocking_failed = int(data["blocking_failed"])
        return exit_code, failed, blocking_failed
    except Exception:
        return -1, -1, -1


def _calc_distribution_stats(series: pd.Series) -> dict[str, Any]:
    """Calculate descriptive distribution stats (min, P10, P25, median, P75, P90, max)."""
    valid = series.dropna()
    if len(valid) == 0:
        return {
            "available_count": 0,
            "missing_count": int(series.isna().sum()),
            "min": None,
            "p10": None,
            "p25": None,
            "median": None,
            "p75": None,
            "p90": None,
            "max": None,
        }
    arr = valid.to_numpy(dtype=float)
    return {
        "available_count": int(len(arr)),
        "missing_count": int(series.isna().sum()),
        "min": round(float(np.min(arr)), 4),
        "p10": round(float(np.percentile(arr, 10)), 4),
        "p25": round(float(np.percentile(arr, 25)), 4),
        "median": round(float(np.median(arr)), 4),
        "p75": round(float(np.percentile(arr, 75)), 4),
        "p90": round(float(np.percentile(arr, 90)), 4),
        "max": round(float(np.max(arr)), 4),
    }


def render_flow_markdown_doc(summary: dict[str, Any]) -> str:
    """Generate docs/patterns/pattern_a/validation/flow_confirmation_infrastructure_v01.md deterministically."""
    gates = summary["hard_gates"]
    gate_table_rows = []
    for g_id, (g_name, g_pass) in enumerate(gates.items(), 1):
        status_str = "PASS" if g_pass else "FAIL"
        gate_table_rows.append(f"| Gate {g_id:02d} | {g_name} | {status_str} |")
    gate_table = "\n".join(gate_table_rows)

    early_rows = []
    for r in summary.get("early_10_table", []):
        nb5 = f"{r['foreign_net_buy_value_5d'] / 1e8:,.2f}억" if r.get('foreign_net_buy_value_5d') is not None else "-"
        nb20 = f"{r['foreign_net_buy_value_20d'] / 1e8:,.2f}억" if r.get('foreign_net_buy_value_20d') is not None else "-"
        nb60 = f"{r['foreign_net_buy_value_60d'] / 1e8:,.2f}억" if r.get('foreign_net_buy_value_60d') is not None else "-"
        int20 = f"{r['foreign_flow_intensity_20d'] * 100:.2f}%" if r.get('foreign_flow_intensity_20d') is not None else "-"
        pos20 = f"{r['foreign_positive_day_ratio_20d'] * 100:.1f}%" if r.get('foreign_positive_day_ratio_20d') is not None else "-"
        early_rows.append(
            f"| {r['ticker']} | {r['name']} | {nb5} | {nb20} | {nb60} | {int20} | {pos20} | {r['foreign_flow_data_status']} |"
        )
    early_table = "\n".join(early_rows)

    return f"""pattern_a_flow_confirmation_infrastructure_v01.md

================================================================================
Phase 11. Foreign Flow Confirmation Infrastructure Validation Report
================================================================================

[기본 정보]
- Validation Version: phase11_flow_confirmation_infrastructure_v0.1
- Evaluation As-Of: {summary['as_of']}
- Base Checkpoint SHA: {summary['base_checkpoint']}
- Phase 11 Status: {summary['phase_11_status']}

--------------------------------------------------------------------------------
1. Executive Summary
--------------------------------------------------------------------------------
Phase 11은 Pattern A(구조) 및 Investability Filter(거래가능성: 시총 >= 1,000억, TV20 >= 3억원)를 통과한
후보군에 대해 "실제로 외국인 자금이 유입되고 있는가?"를 독립적으로 확인하는
Point-In-Time Flow Confirmation Infrastructure를 성공적으로 구축하고 검증하였다.

[핵심 불변성 검증]
+------------------------------------+----------------+----------------+
| Metric                             | Expected       | Actual         |
+------------------------------------+----------------+----------------+
| Official COMMON Universe           | 2,528          | {summary['universe_count']}          |
| Raw Candidate Total                | 180            | {summary['candidate_count']}            |
| - TRANSITION                       | 168            | {summary['transition_count']}            |
| - EARLY_TREND                      | 12             | {summary['early_count']}             |
| Investable Candidates              | 103            | {summary['investable_count']}            |
| - Filtered Market Cap              | 42             | {summary['filtered_market_cap_count']}             |
| - Filtered Liquidity (TV20 < 3억)  | 31             | {summary['filtered_liquidity_count']}             |
| - Data Unavailable                 | 4              | {summary['data_unavailable_count']}              |
+------------------------------------+----------------+----------------+

[Phase 10 Identity Parity Mismatch Audit]
- Candidate Ticker Set Mismatches: {summary['candidate_ticker_mismatches']}
- Stage Parity Mismatches: {summary['stage_mismatches']}
- Score Parity Mismatches: {summary['score_mismatches']}
- Candidate State Mismatches: {summary['candidate_state_mismatches']}
- Investability Status Mismatches: {summary['investability_mismatches']}

--------------------------------------------------------------------------------
2. Foreign Flow Coverage & Readiness (Investable 103)
--------------------------------------------------------------------------------
- Flow READY: {summary['investable_flow_ready_count']} ({summary['investable_flow_ready_pct']}%)
- Flow PARTIAL: {summary['investable_flow_partial_count']} ({summary['investable_flow_partial_pct']}%)
- Flow DATA_UNAVAILABLE: {summary['investable_flow_unavail_count']} ({summary['investable_flow_unavail_pct']}%)
  (계약: DATA_UNAVAILABLE row의 flow 숫자는 production confirmation / ranking에 절대 사용 금지)

[20D Foreign Net Buy Direction Breakdown]
- Net Buy Positive (> 0): {summary['net_buy_20d_pos_count']} ({summary['net_buy_20d_pos_pct']}%)
- Net Buy Zero (== 0): {summary['net_buy_20d_zero_count']} ({summary['net_buy_20d_zero_pct']}%)
- Net Buy Negative (< 0): {summary['net_buy_20d_neg_count']} ({summary['net_buy_20d_neg_pct']}%)

[5D / 20D Flow Regime Combination]
- 5D Positive + 20D Positive (Sustained Inflow): {summary['regime_5d_pos_20d_pos']}
- 5D Positive + 20D Non-positive (Inflow Reversal): {summary['regime_5d_pos_20d_nonpos']}
- 5D Non-positive + 20D Positive (Short-term Pullback Inflow): {summary['regime_5d_nonpos_20d_pos']}
- 5D Non-positive + 20D Non-positive (Sustained Outflow): {summary['regime_5d_nonpos_20d_nonpos']}

[Canonical Flow Arithmetic & Normalization Parity]
- 5D Signed Flow Mismatches: {summary['signed_flow_5d_mismatches']}
- 20D Signed Flow Mismatches: {summary['signed_flow_20d_mismatches']}
- 60D Signed Flow Mismatches: {summary['signed_flow_60d_mismatches']}
- 5D Intensity Mismatches: {summary['intensity_5d_mismatches']}
- 20D Intensity Mismatches: {summary['intensity_20d_mismatches']}
- 60D Intensity Mismatches: {summary['intensity_60d_mismatches']}

--------------------------------------------------------------------------------
3. Investable EARLY_TREND 10 Foreign Flow Audit
--------------------------------------------------------------------------------
+--------+--------------+----------+----------+----------+----------+----------+------------------+
| Ticker | Name         | 5D NetBuy| 20D NetBuy| 60D NetBuy| 20D Int  | 20D Pos  | Flow Status      |
+--------+--------------+----------+----------+----------+----------+----------+------------------+
{early_table}
+--------+--------------+----------+----------+----------+----------+----------+------------------+

--------------------------------------------------------------------------------
4. 10 Dynamic Hard Gates Evaluation
--------------------------------------------------------------------------------
+---------+------------------------------------------------------+--------+
| Gate ID | Hard Gate Contract                                   | Status |
+---------+------------------------------------------------------+--------+
{gate_table}
+---------+------------------------------------------------------+--------+

--------------------------------------------------------------------------------
5. Final Decision
--------------------------------------------------------------------------------
- Hard Gates Result: {"ALL 10 GATES PASSED (100%)" if summary['phase_11_status'] == "FLOW_INFRA_READY" else "GATE FAILURE"}
- Final Milestone State: {summary['phase_11_status']}
- Next Step: {summary['next_milestone']}
"""


def run_foreign_flow_infrastructure_validation(
    repo_root: Path,
    output_dir: Path | None = None,
    doc_path: Path | None = None,
    write_artifacts: bool = True,
    integration_oracle_path: Path | None = None,
    candidate_oracle_path: Path | None = None,
) -> dict[str, Any]:
    """Execute Phase 11 Foreign Flow Confirmation Infrastructure Validation."""
    cache_dir = repo_root / "data" / "raw" / "stocks"
    parquet_cache = ParquetCache(base_dir=cache_dir)
    out_dir = output_dir or (repo_root / "artifacts/patterns/pattern_a/production/flow")
    if write_artifacts:
        out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load Canonical Source Artifact & Checksum
    source_parquet = repo_root / "artifacts/patterns/pattern_a/production/flow/source/foreign_flow_daily_20260814.parquet"
    source_meta_file = repo_root / "artifacts/patterns/pattern_a/production/flow/source/foreign_flow_daily_20260814_meta.json"

    source_exists = source_parquet.exists() and source_meta_file.exists()
    source_sha256 = compute_file_sha256(source_parquet) if source_parquet.exists() else ""
    df_flow = pd.read_parquet(source_parquet) if source_parquet.exists() else pd.DataFrame()
    meta_json = json.loads(source_meta_file.read_text(encoding="utf-8")) if source_meta_file.exists() else {}

    # 2. Execute Production Full Universe Scanner with Flow Enrichment
    scan_result: PatternAUniverseScanResult = scan_pattern_a_universe(
        cache=parquet_cache,
        as_of=CANONICAL_AS_OF,
        flow_df=df_flow,
        enrich_flow_for_candidates=True,
    )
    df_scan = scan_result.to_dataframe()

    # 3. Filter Cohorts
    df_candidates = df_scan[df_scan["candidate_state"] == PatternACandidateState.CANDIDATE.value].copy()
    tot_cand = len(df_candidates)
    trans_cnt = int((df_candidates["official_stage"] == PatternAStage.TRANSITION.value).sum())
    early_cnt = int((df_candidates["official_stage"] == PatternAStage.EARLY_TREND.value).sum())

    # Investability Cohorts
    df_investable = df_candidates[df_candidates["investability_status"] == InvestabilityStatus.INVESTABLE.value].copy()
    tot_inv = len(df_investable)
    mcap_cnt = int((df_candidates["investability_status"] == InvestabilityStatus.FILTERED_MARKET_CAP.value).sum())
    liq_cnt = int((df_candidates["investability_status"] == InvestabilityStatus.FILTERED_LIQUIDITY.value).sum())
    unavail_cnt = int((df_candidates["investability_status"] == InvestabilityStatus.DATA_UNAVAILABLE.value).sum())

    # 4. Phase 10 Frozen Baseline Exact Parity Check (Phase 10C Canonical Oracle)
    integration_oracle_csv = integration_oracle_path or (
        repo_root / "artifacts/patterns/pattern_a/production/investability/pattern_a_investability_integration_20260814.csv"
    )
    candidate_oracle_csv = candidate_oracle_path or (
        repo_root / "artifacts/patterns/pattern_a/production/investability/pattern_a_investability_candidates_20260814.csv"
    )

    oracle_available = False
    cand_ticker_mismatches = 0
    stage_mismatches = 0
    score_mismatches = 0
    cand_state_mismatches = 0
    investability_mismatches = 0

    if integration_oracle_csv.exists() and candidate_oracle_csv.exists():
        oracle_available = True
        df_int_oracle = pd.read_csv(integration_oracle_csv)
        df_cand_oracle = pd.read_csv(candidate_oracle_csv)

        df_int_oracle["ticker"] = df_int_oracle["ticker"].astype(str).str.zfill(6)
        df_cand_oracle["ticker"] = df_cand_oracle["ticker"].astype(str).str.zfill(6)
        df_candidates["ticker_z"] = df_candidates["ticker"].astype(str).str.zfill(6)

        cand_set_actual = set(df_candidates["ticker_z"])
        cand_set_oracle = set(df_int_oracle["ticker"])
        cand_ticker_mismatches = len(cand_set_actual.symmetric_difference(cand_set_oracle))

        int_oracle_map = df_int_oracle.set_index("ticker")
        cand_oracle_map = df_cand_oracle.set_index("ticker")
        actual_map = df_candidates.set_index("ticker_z")

        for t in cand_set_actual.intersection(cand_set_oracle):
            a_row = actual_map.loc[t]
            i_row = int_oracle_map.loc[t]

            # Stage parity
            if str(a_row["official_stage"]) != str(i_row["official_stage"]):
                stage_mismatches += 1

            # Candidate state parity
            if str(a_row["candidate_state"]) != str(i_row["candidate_state"]):
                cand_state_mismatches += 1

            # Investability status ticker-level parity
            if str(a_row["investability_status"]) != str(i_row["investability_status"]):
                investability_mismatches += 1

            # Score parity (from cand_oracle_map)
            if t in cand_oracle_map.index:
                c_row = cand_oracle_map.loc[t]
                if a_row["pattern_a_score"] is not None and c_row["pattern_a_score"] is not None:
                    if abs(float(a_row["pattern_a_score"]) - float(c_row["pattern_a_score"])) > 1e-4:
                        score_mismatches += 1
                elif a_row["pattern_a_score"] != c_row["pattern_a_score"]:
                    score_mismatches += 1
    else:
        oracle_available = False
        cand_ticker_mismatches = EXPECTED_RAW_CANDIDATES
        stage_mismatches = EXPECTED_RAW_CANDIDATES
        score_mismatches = EXPECTED_RAW_CANDIDATES
        cand_state_mismatches = EXPECTED_RAW_CANDIDATES
        investability_mismatches = EXPECTED_RAW_CANDIDATES

    # 5. Investable Flow Distribution & Readiness
    inv_ready_cnt = int((df_investable["foreign_flow_data_status"] == FlowDataStatus.READY.value).sum())
    inv_partial_cnt = int((df_investable["foreign_flow_data_status"] == FlowDataStatus.PARTIAL.value).sum())
    inv_unavail_cnt = int((df_investable["foreign_flow_data_status"] == FlowDataStatus.DATA_UNAVAILABLE.value).sum())

    # Flow Net Buy Direction Breakdown on Investable 103
    nb20 = df_investable["foreign_net_buy_value_20d"].dropna()
    nb20_pos = int((nb20 > 0).sum())
    nb20_zero = int((nb20 == 0).sum())
    nb20_neg = int((nb20 < 0).sum())

    # 5D / 20D Regime
    nb5 = df_investable["foreign_net_buy_value_5d"]
    regime_pos_pos = int(((nb5 > 0) & (df_investable["foreign_net_buy_value_20d"] > 0)).sum())
    regime_pos_nonpos = int(((nb5 > 0) & (df_investable["foreign_net_buy_value_20d"] <= 0)).sum())
    regime_nonpos_pos = int(((nb5 <= 0) & (df_investable["foreign_net_buy_value_20d"] > 0)).sum())
    regime_nonpos_nonpos = int(((nb5 <= 0) & (df_investable["foreign_net_buy_value_20d"] <= 0)).sum())

    # 6. Canonical Arithmetic & Normalization Parity (Investable 103 전수 검증)
    signed_flow_5d_mismatches = 0
    signed_flow_20d_mismatches = 0
    signed_flow_60d_mismatches = 0

    intensity_5d_mismatches = 0
    intensity_20d_mismatches = 0
    intensity_60d_mismatches = 0

    def _compare_signed_flow(act_val: Any, exp_val: float | None) -> bool:
        """Null semantics & tolerance comparison for signed flow (KRW)."""
        if (act_val is None or pd.isna(act_val)) and (exp_val is None or pd.isna(exp_val)):
            return True
        if (act_val is None or pd.isna(act_val)) or (exp_val is None or pd.isna(exp_val)):
            return False
        return abs(float(act_val) - float(exp_val)) <= 1.0

    def _compare_intensity(act_val: Any, exp_val: float | None) -> bool:
        """Null semantics & tolerance comparison for normalized intensity."""
        if (act_val is None or pd.isna(act_val)) and (exp_val is None or pd.isna(exp_val)):
            return True
        if (act_val is None or pd.isna(act_val)) or (exp_val is None or pd.isna(exp_val)):
            return False
        return abs(float(act_val) - float(exp_val)) <= 1e-4

    for _, inv_row in df_investable.iterrows():
        t_code = inv_row["ticker"]
        t_flow_sub = df_flow[df_flow["ticker"] == t_code].sort_values(by="date")

        # 1) Signed Flow Check
        exp_5d = float(t_flow_sub["foreign_net_buy_value"].iloc[-5:].sum()) if len(t_flow_sub) >= 5 else None
        act_5d = inv_row.get("foreign_net_buy_value_5d")
        if not _compare_signed_flow(act_5d, exp_5d):
            signed_flow_5d_mismatches += 1

        exp_20d = float(t_flow_sub["foreign_net_buy_value"].iloc[-20:].sum()) if len(t_flow_sub) >= 20 else None
        act_20d = inv_row.get("foreign_net_buy_value_20d")
        if not _compare_signed_flow(act_20d, exp_20d):
            signed_flow_20d_mismatches += 1

        exp_60d = float(t_flow_sub["foreign_net_buy_value"].iloc[-60:].sum()) if len(t_flow_sub) >= 60 else None
        act_60d = inv_row.get("foreign_net_buy_value_60d")
        if not _compare_signed_flow(act_60d, exp_60d):
            signed_flow_60d_mismatches += 1

        # 2) Intensity Parity Check via Price Cache (5D, 20D, 60D All Recomputed)
        daily_stock = parquet_cache.load(t_code)
        exp_int_5d = None
        exp_int_20d = None
        exp_int_60d = None

        if daily_stock is not None and not daily_stock.empty and "trading_value" in daily_stock.columns:
            daily_as_of = daily_stock[daily_stock.index <= pd.Timestamp(CANONICAL_AS_OF)].copy()
            daily_as_of["date_str"] = daily_as_of.index.strftime("%Y-%m-%d")

            # 5D Intensity
            if len(t_flow_sub) >= 5:
                t_flow_5 = t_flow_sub.iloc[-5:].copy()
                t_flow_5["date_str"] = t_flow_5["date"].astype(str)
                merged5 = pd.merge(t_flow_5, daily_as_of, on="date_str")
                if len(merged5) == 5:
                    tv_sum5 = float(merged5["trading_value"].sum())
                    nb_sum5 = float(merged5["foreign_net_buy_value"].sum())
                    if tv_sum5 > 0:
                        exp_int_5d = nb_sum5 / tv_sum5

            # 20D Intensity
            if len(t_flow_sub) >= 20:
                t_flow_20 = t_flow_sub.iloc[-20:].copy()
                t_flow_20["date_str"] = t_flow_20["date"].astype(str)
                merged20 = pd.merge(t_flow_20, daily_as_of, on="date_str")
                if len(merged20) == 20:
                    tv_sum20 = float(merged20["trading_value"].sum())
                    nb_sum20 = float(merged20["foreign_net_buy_value"].sum())
                    if tv_sum20 > 0:
                        exp_int_20d = nb_sum20 / tv_sum20

            # 60D Intensity
            if len(t_flow_sub) >= 60:
                t_flow_60 = t_flow_sub.iloc[-60:].copy()
                t_flow_60["date_str"] = t_flow_60["date"].astype(str)
                merged60 = pd.merge(t_flow_60, daily_as_of, on="date_str")
                if len(merged60) == 60:
                    tv_sum60 = float(merged60["trading_value"].sum())
                    nb_sum60 = float(merged60["foreign_net_buy_value"].sum())
                    if tv_sum60 > 0:
                        exp_int_60d = nb_sum60 / tv_sum60

        act_int_5d = inv_row.get("foreign_flow_intensity_5d")
        if not _compare_intensity(act_int_5d, exp_int_5d):
            intensity_5d_mismatches += 1

        act_int_20d = inv_row.get("foreign_flow_intensity_20d")
        if not _compare_intensity(act_int_20d, exp_int_20d):
            intensity_20d_mismatches += 1

        act_int_60d = inv_row.get("foreign_flow_intensity_60d")
        if not _compare_intensity(act_int_60d, exp_int_60d):
            intensity_60d_mismatches += 1

    # Distributions
    dist_payload = {
        "investable_103_distribution": {
            "foreign_net_buy_value_5d": _calc_distribution_stats(df_investable["foreign_net_buy_value_5d"]),
            "foreign_net_buy_value_20d": _calc_distribution_stats(df_investable["foreign_net_buy_value_20d"]),
            "foreign_net_buy_value_60d": _calc_distribution_stats(df_investable["foreign_net_buy_value_60d"]),
            "foreign_flow_intensity_5d": _calc_distribution_stats(df_investable["foreign_flow_intensity_5d"]),
            "foreign_flow_intensity_20d": _calc_distribution_stats(df_investable["foreign_flow_intensity_20d"]),
            "foreign_flow_intensity_60d": _calc_distribution_stats(df_investable["foreign_flow_intensity_60d"]),
            "foreign_positive_day_ratio_5d": _calc_distribution_stats(df_investable["foreign_positive_day_ratio_5d"]),
            "foreign_positive_day_ratio_20d": _calc_distribution_stats(df_investable["foreign_positive_day_ratio_20d"]),
            "foreign_positive_day_ratio_60d": _calc_distribution_stats(df_investable["foreign_positive_day_ratio_60d"]),
        },
        "investable_early_10_distribution": {
            "foreign_net_buy_value_20d": _calc_distribution_stats(
                df_investable[df_investable["official_stage"] == PatternAStage.EARLY_TREND.value]["foreign_net_buy_value_20d"]
            ),
            "foreign_flow_intensity_20d": _calc_distribution_stats(
                df_investable[df_investable["official_stage"] == PatternAStage.EARLY_TREND.value]["foreign_flow_intensity_20d"]
            ),
            "foreign_positive_day_ratio_20d": _calc_distribution_stats(
                df_investable[df_investable["official_stage"] == PatternAStage.EARLY_TREND.value]["foreign_positive_day_ratio_20d"]
            ),
        },
        "investable_transition_93_distribution": {
            "foreign_net_buy_value_20d": _calc_distribution_stats(
                df_investable[df_investable["official_stage"] == PatternAStage.TRANSITION.value]["foreign_net_buy_value_20d"]
            ),
            "foreign_flow_intensity_20d": _calc_distribution_stats(
                df_investable[df_investable["official_stage"] == PatternAStage.TRANSITION.value]["foreign_flow_intensity_20d"]
            ),
            "foreign_positive_day_ratio_20d": _calc_distribution_stats(
                df_investable[df_investable["official_stage"] == PatternAStage.TRANSITION.value]["foreign_positive_day_ratio_20d"]
            ),
        },
    }

    # EARLY 10 Table Rows
    early_10_rows = []
    df_early_10 = df_investable[df_investable["official_stage"] == PatternAStage.EARLY_TREND.value].sort_values(by="ticker")
    for _, r in df_early_10.iterrows():
        early_10_rows.append({
            "ticker": r["ticker"],
            "name": r["name"],
            "official_stage": r["official_stage"],
            "foreign_net_buy_value_1d": r.get("foreign_net_buy_value_1d"),
            "foreign_net_buy_value_5d": r.get("foreign_net_buy_value_5d"),
            "foreign_net_buy_value_20d": r.get("foreign_net_buy_value_20d"),
            "foreign_net_buy_value_60d": r.get("foreign_net_buy_value_60d"),
            "foreign_flow_intensity_20d": r.get("foreign_flow_intensity_20d"),
            "foreign_positive_day_ratio_20d": r.get("foreign_positive_day_ratio_20d"),
            "foreign_flow_data_status": r.get("foreign_flow_data_status"),
        })

    # 7. Synthetic Fail-Closed Negative Tests for Gate 7
    stale_test_passed = False
    empty_test_passed = False
    dup_test_passed = False

    # Stale Test: 20 obs but latest is 2026-08-12
    stale_dates = [f"2026-07-{i:02d}" for i in range(1, 21)]  # latest is 2026-07-20 < 2026-08-14
    stale_flow_df = pd.DataFrame({
        "date": stale_dates,
        "ticker": ["005930"] * len(stale_dates),
        "foreign_net_buy_value": [100.0] * len(stale_dates),
    })
    stale_res = compute_foreign_flow_features("005930", CANONICAL_AS_OF, stale_flow_df)
    if stale_res.data_status == FlowDataStatus.DATA_UNAVAILABLE:
        stale_test_passed = True

    # Empty Test
    empty_res = compute_foreign_flow_features("005930", CANONICAL_AS_OF, None)
    if empty_res.data_status == FlowDataStatus.DATA_UNAVAILABLE:
        empty_test_passed = True

    # Dup Test
    dup_flow_df = pd.DataFrame({
        "date": ["2026-08-14", "2026-08-14"],
        "ticker": ["005930", "005930"],
        "foreign_net_buy_value": [100.0, 200.0],
    })
    try:
        compute_foreign_flow_features("005930", CANONICAL_AS_OF, dup_flow_df)
    except MarketDataError:
        dup_test_passed = True

    # 8. 10 Dynamic Hard Gates Evaluation
    # Gate 1: Phase 10 Frozen Identity & Exact Parity PASS
    g1 = (
        oracle_available
        and len(df_scan) == EXPECTED_UNIVERSE_COUNT
        and tot_cand == EXPECTED_RAW_CANDIDATES
        and trans_cnt == EXPECTED_TRANSITION_COUNT
        and early_cnt == EXPECTED_EARLY_COUNT
        and tot_inv == EXPECTED_INVESTABLE_COUNT
        and mcap_cnt == EXPECTED_FILTERED_MARKET_CAP_COUNT
        and liq_cnt == EXPECTED_FILTERED_LIQUIDITY_COUNT
        and unavail_cnt == EXPECTED_DATA_UNAVAILABLE_COUNT
        and cand_ticker_mismatches == 0
        and stage_mismatches == 0
        and score_mismatches == 0
        and cand_state_mismatches == 0
        and investability_mismatches == 0
    )

    # Gate 2: Foreign Flow Source Identity Exact Match PASS
    g2 = (
        source_exists
        and source_sha256 == meta_json.get("parquet_sha256")
        and len(df_flow) == meta_json.get("row_count")
        and df_flow["ticker"].nunique() == meta_json.get("ticker_count")
        and df_flow["date"].min() == meta_json.get("date_min")
        and df_flow["date"].max() == meta_json.get("date_max")
        and meta_json.get("requested_as_of") == CANONICAL_AS_OF
    )

    # Gate 3: PIT / No Lookahead PASS
    flow_dates = df_candidates["foreign_flow_last_observation_date"].dropna()
    g3 = bool(
        (pd.to_datetime(flow_dates) <= pd.Timestamp(CANONICAL_AS_OF)).all()
        and (pd.to_datetime(df_flow["date"]) <= pd.Timestamp(CANONICAL_AS_OF)).all()
    ) if len(flow_dates) > 0 else True

    # Gate 4: Window Contract & Exact Freshness PASS
    ready_cands = df_candidates[df_candidates["foreign_flow_data_status"] == FlowDataStatus.READY.value]
    g4 = bool(
        len(ready_cands) > 0
        and (ready_cands["foreign_flow_last_observation_date"] == CANONICAL_AS_OF).all()
        and (ready_cands["foreign_net_buy_value_5d"].notna() & ready_cands["foreign_net_buy_value_20d"].notna()).all()
    )

    # Gate 5: Signed Flow Canonical Arithmetic Parity PASS
    g5 = (
        signed_flow_5d_mismatches == 0
        and signed_flow_20d_mismatches == 0
        and signed_flow_60d_mismatches == 0
    )

    # Gate 6: Normalized Flow Canonical Arithmetic Parity PASS
    intensities = df_candidates["foreign_flow_intensity_20d"].dropna()
    g6 = (
        bool(np.isfinite(intensities).all())
        and intensity_5d_mismatches == 0
        and intensity_20d_mismatches == 0
        and intensity_60d_mismatches == 0
    )

    # Gate 7: Missing / Stale Fail Closed PASS
    g7 = bool(
        stale_test_passed
        and empty_test_passed
        and dup_test_passed
        and df_candidates["foreign_flow_data_status"].isin([s.value for s in FlowDataStatus]).all()
    )

    # Gate 8: Scanner Output Schema Compatibility PASS
    required_cols = {
        "foreign_flow_data_status",
        "foreign_flow_last_observation_date",
        "foreign_flow_first_observation_date",
        "foreign_flow_observation_count",
        "foreign_net_buy_value_1d",
        "foreign_net_buy_value_5d",
        "foreign_net_buy_value_20d",
        "foreign_net_buy_value_60d",
        "foreign_flow_intensity_5d",
        "foreign_flow_intensity_20d",
        "foreign_flow_intensity_60d",
        "foreign_positive_days_5d",
        "foreign_positive_days_20d",
        "foreign_positive_days_60d",
        "foreign_positive_day_ratio_5d",
        "foreign_positive_day_ratio_20d",
        "foreign_positive_day_ratio_60d",
        "foreign_net_buy_avg_5d",
        "foreign_net_buy_avg_20d",
        "foreign_net_buy_avg_60d",
    }
    g8 = required_cols.issubset(set(df_scan.columns))

    # Gate 9: Raw180 / Investable103 Preservation PASS
    g9 = bool(
        oracle_available
        and tot_cand == EXPECTED_RAW_CANDIDATES
        and tot_inv == EXPECTED_INVESTABLE_COUNT
        and cand_ticker_mismatches == 0
    )

    # Gate 10: Full Test Suite PASS
    py_exit, py_fail, py_block = _read_pytest_report(repo_root)
    g10 = (py_exit == 0 and py_fail == 0 and py_block == 0)

    gates = {
        "gate_01_phase10_frozen_identity_parity_pass": bool(g1),
        "gate_02_foreign_flow_source_exact_identity_pass": bool(g2),
        "gate_03_pit_no_lookahead_pass": bool(g3),
        "gate_04_window_contract_exact_freshness_pass": bool(g4),
        "gate_05_signed_flow_arithmetic_parity_pass": bool(g5),
        "gate_06_normalized_flow_arithmetic_parity_pass": bool(g6),
        "gate_07_missing_stale_fail_closed_pass": bool(g7),
        "gate_08_scanner_schema_compatibility_pass": bool(g8),
        "gate_09_raw180_investable103_preservation_pass": bool(g9),
        "gate_10_production_test_suite_pass": bool(g10),
    }

    all_pass = all(gates.values())
    status = "FLOW_INFRA_READY" if all_pass else "HOLD_FLOW_INFRA"

    summary_payload = {
        "audit_version": "phase11_flow_confirmation_infrastructure_v0.1",
        "as_of": CANONICAL_AS_OF,
        "base_checkpoint": BASE_CHECKPOINT_SHA,
        "source_name": "KRX_PYKRX_FOREIGN_FLOW",
        "source_sha256": source_sha256,
        "source_row_count": len(df_flow),
        "universe_count": len(df_scan),
        "candidate_count": tot_cand,
        "transition_count": trans_cnt,
        "early_count": early_cnt,
        "investable_count": tot_inv,
        "filtered_market_cap_count": mcap_cnt,
        "filtered_liquidity_count": liq_cnt,
        "data_unavailable_count": unavail_cnt,
        "candidate_ticker_mismatches": cand_ticker_mismatches,
        "stage_mismatches": stage_mismatches,
        "score_mismatches": score_mismatches,
        "candidate_state_mismatches": cand_state_mismatches,
        "investability_mismatches": investability_mismatches,
        "investable_flow_ready_count": inv_ready_cnt,
        "investable_flow_ready_pct": round(inv_ready_cnt / tot_inv * 100, 2) if tot_inv > 0 else 0.0,
        "investable_flow_partial_count": inv_partial_cnt,
        "investable_flow_partial_pct": round(inv_partial_cnt / tot_inv * 100, 2) if tot_inv > 0 else 0.0,
        "investable_flow_unavail_count": inv_unavail_cnt,
        "investable_flow_unavail_pct": round(inv_unavail_cnt / tot_inv * 100, 2) if tot_inv > 0 else 0.0,
        "net_buy_20d_pos_count": nb20_pos,
        "net_buy_20d_pos_pct": round(nb20_pos / tot_inv * 100, 2) if tot_inv > 0 else 0.0,
        "net_buy_20d_zero_count": nb20_zero,
        "net_buy_20d_zero_pct": round(nb20_zero / tot_inv * 100, 2) if tot_inv > 0 else 0.0,
        "net_buy_20d_neg_count": nb20_neg,
        "net_buy_20d_neg_pct": round(nb20_neg / tot_inv * 100, 2) if tot_inv > 0 else 0.0,
        "regime_5d_pos_20d_pos": regime_pos_pos,
        "regime_5d_pos_20d_nonpos": regime_pos_nonpos,
        "regime_5d_nonpos_20d_pos": regime_nonpos_pos,
        "regime_5d_nonpos_20d_nonpos": regime_nonpos_nonpos,
        "signed_flow_5d_mismatches": signed_flow_5d_mismatches,
        "signed_flow_20d_mismatches": signed_flow_20d_mismatches,
        "signed_flow_60d_mismatches": signed_flow_60d_mismatches,
        "intensity_5d_mismatches": intensity_5d_mismatches,
        "intensity_20d_mismatches": intensity_20d_mismatches,
        "intensity_60d_mismatches": intensity_60d_mismatches,
        "early_10_table": early_10_rows,
        "hard_gates": gates,
        "phase_11_status": status,
        "next_milestone": "Phase 11 DONE -> Phase 12. Relative Strength Confirmation Infrastructure",
    }

    if write_artifacts:
        # 1. Candidate Features CSV
        cand_csv_path = out_dir / "pattern_a_foreign_flow_features_20260814.csv"
        df_candidates.to_csv(cand_csv_path, index=False)

        # 2. Distribution JSON
        dist_json_path = out_dir / "pattern_a_foreign_flow_distribution_20260814.json"
        with open(dist_json_path, "w", encoding="utf-8") as f:
            json.dump(dist_payload, f, indent=2, ensure_ascii=False)

        # 3. Summary JSON
        summary_json_path = out_dir / "pattern_a_foreign_flow_summary_20260814.json"
        with open(summary_json_path, "w", encoding="utf-8") as f:
            json.dump(summary_payload, f, indent=2, ensure_ascii=False)

        # 4. Markdown Document
        final_doc_path = doc_path or (repo_root / "docs/patterns/pattern_a/validation/flow_confirmation_infrastructure_v01.md")
        final_doc_path.parent.mkdir(parents=True, exist_ok=True)
        rendered_md = render_flow_markdown_doc(summary_payload)
        final_doc_path.write_text(rendered_md, encoding="utf-8")

        print(f"Phase 11 Validation completed. Status: {status}")
        print(f"Artifacts written to {out_dir} and doc to {final_doc_path}")

    return summary_payload


if __name__ == "__main__":
    _root = Path(__file__).resolve().parent.parent.parent.parent
    res = run_foreign_flow_infrastructure_validation(_root)
    print("Hard Gates:")
    for k, v in res["hard_gates"].items():
        print(f"  {k}: {v}")
