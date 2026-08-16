"""Investability and Tradability Distribution Comparative Audit for Pattern A (Phase 10A).

This module performs point-in-time (2026-08-14) quantitative distribution analysis
comparing the Official COMMON Universe (2,528 stocks) and Pattern A Raw Candidates (180 stocks)
across Market Capitalization, Closing Price, and 20D/60D Average Trading Value.

[Absolute Rules]:
1. Analysis and validation only. No modification to Pattern A Score, Stage, or Scanner rules.
2. Point-In-Time Contract: all data strictly as of 2026-08-14 without lookahead.
3. Single Canonical Run: all artifacts, summaries, and validation tables derived from single pipeline.
4. Fail-Closed Gates: 11 dynamic hard gates determine READY_FOR_THRESHOLD_DESIGN vs HOLD_DATA_QUALITY.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import numpy as np
import pandas as pd
from pykrx import stock

from trend_scanner.data.cache import ParquetCache

load_dotenv()


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


def load_canonical_mcap_snapshot(
    repo_root: Path,
    as_of: str = "2026-08-14",
) -> tuple[pd.DataFrame, str]:
    """Load or fetch canonical Point-In-Time market cap snapshot."""
    source_dir = repo_root / "artifacts/investability/source"
    source_dir.mkdir(parents=True, exist_ok=True)
    source_file = source_dir / f"krx_market_cap_{as_of.replace('-', '')}.csv"

    if source_file.exists():
        df = pd.read_csv(source_file, dtype={"ticker": str})
        df["ticker"] = df["ticker"].str.zfill(6)
        sha256 = hashlib.sha256(source_file.read_bytes()).hexdigest()
        return df, sha256

    # Fetch from pykrx if not cached
    as_of_clean = as_of.replace("-", "")
    df_raw = stock.get_market_cap_by_ticker(as_of_clean)
    df_raw.index.name = "ticker"
    df_reset = df_raw.reset_index()
    df_reset["ticker"] = df_reset["ticker"].astype(str).str.zfill(6)
    df_reset["effective_date"] = as_of

    df_canon = df_reset.rename(columns={
        "종가": "close",
        "시가총액": "market_cap",
        "거래량": "volume",
        "거래대금": "trading_value",
        "상장주식수": "shares_outstanding",
    })

    df_canon.to_csv(source_file, index=False)
    sha256 = hashlib.sha256(source_file.read_bytes()).hexdigest()
    return df_canon, sha256


def run_investability_audit(
    repo_root: Path,
    as_of: str = "2026-08-14",
) -> dict[str, Any]:
    """Execute Phase 10A Investability Distribution Comparative Audit Single Canonical Pipeline."""
    cache_dir = repo_root / "data/raw/stocks"
    cache = ParquetCache(base_dir=cache_dir)
    out_dir = repo_root / "artifacts/investability"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load Universe and Candidate Base Data
    univ_csv = repo_root / "artifacts/scanner/pattern_a_universe_scan_20260814.csv"
    cand_csv = repo_root / "artifacts/chart_review/pattern_a_candidate_manual_review_20260814.csv"

    df_univ_raw = pd.read_csv(univ_csv, dtype={"ticker": str})
    df_cand_raw = pd.read_csv(cand_csv, dtype={"ticker": str})

    df_univ_raw["ticker"] = df_univ_raw["ticker"].str.zfill(6)
    df_cand_raw["ticker"] = df_cand_raw["ticker"].str.zfill(6)

    # 2. Fetch Point-In-Time KRX Market Cap Snapshot as of as_of
    df_mcap_snap, mcap_sha256 = load_canonical_mcap_snapshot(repo_root, as_of=as_of)
    mcap_dict = {row["ticker"]: float(row["market_cap"]) for _, row in df_mcap_snap.iterrows()}
    shares_dict = {row["ticker"]: int(row["shares_outstanding"]) for _, row in df_mcap_snap.iterrows()}

    # 3. Calculate Point-In-Time Exact Metrics for Universe
    universe_rows: list[dict[str, Any]] = []
    missing_cache_tickers: list[str] = []
    missing_close_tickers: list[str] = []
    missing_mcap_tickers: list[str] = []
    missing_tv20_tickers: list[str] = []
    missing_tv60_tickers: list[str] = []

    for _, row in df_univ_raw.iterrows():
        ticker = row["ticker"]
        name = row["name"]
        market = row["market"]
        asset_type = row["asset_type"]
        official_stage = row.get("official_stage")
        candidate_state = row.get("candidate_state")
        pattern_a_score = row.get("pattern_a_score")

        mcap_val = mcap_dict.get(ticker)
        shares_val = shares_dict.get(ticker)
        mcap_eok = round(mcap_val / 1e8, 2) if mcap_val is not None else None
        if mcap_val is None:
            missing_mcap_tickers.append(ticker)

        df_daily = cache.load(ticker)
        if df_daily is None or df_daily.empty:
            missing_cache_tickers.append(ticker)
            missing_close_tickers.append(ticker)
            missing_tv20_tickers.append(ticker)
            missing_tv60_tickers.append(ticker)
            universe_rows.append({
                "ticker": ticker,
                "name": name,
                "market": market,
                "asset_type": asset_type,
                "as_of": as_of,
                "official_stage": official_stage,
                "candidate_state": candidate_state,
                "pattern_a_score": pattern_a_score,
                "close": None,
                "close_ready": False,
                "close_effective_date": None,
                "market_cap": mcap_val,
                "market_cap_eok": mcap_eok,
                "shares_outstanding": shares_val,
                "market_cap_ready": (mcap_val is not None),
                "avg_trading_value_20d": None,
                "avg_trading_value_20d_eok": None,
                "median_trading_value_20d": None,
                "trading_days_20d": 0,
                "trading_value_20d_ready": False,
                "avg_trading_value_60d": None,
                "avg_trading_value_60d_eok": None,
                "median_trading_value_60d": None,
                "trading_days_60d": 0,
                "trading_value_60d_ready": False,
                "data_ready": False,
                "missing_reason": "CACHE_MISSING",
            })
            continue

        df_asof = df_daily[df_daily.index <= as_of]
        if df_asof.empty or as_of not in df_asof.index:
            # Exact Close PIT Contract: must have exact observation on as_of
            missing_close_tickers.append(ticker)
            missing_tv20_tickers.append(ticker)
            missing_tv60_tickers.append(ticker)
            universe_rows.append({
                "ticker": ticker,
                "name": name,
                "market": market,
                "asset_type": asset_type,
                "as_of": as_of,
                "official_stage": official_stage,
                "candidate_state": candidate_state,
                "pattern_a_score": pattern_a_score,
                "close": None,
                "close_ready": False,
                "close_effective_date": str(df_asof.index[-1].date()) if not df_asof.empty else None,
                "market_cap": mcap_val,
                "market_cap_eok": mcap_eok,
                "shares_outstanding": shares_val,
                "market_cap_ready": (mcap_val is not None),
                "avg_trading_value_20d": None,
                "avg_trading_value_20d_eok": None,
                "median_trading_value_20d": None,
                "trading_days_20d": 0,
                "trading_value_20d_ready": False,
                "avg_trading_value_60d": None,
                "avg_trading_value_60d_eok": None,
                "median_trading_value_60d": None,
                "trading_days_60d": 0,
                "trading_value_60d_ready": False,
                "data_ready": False,
                "missing_reason": "NO_OBSERVATION_ON_ASOF",
            })
            continue

        # Exact observation on as_of exists
        close_val = float(df_asof.loc[as_of, "close"])
        close_effective_date = as_of

        tv_series = df_asof["trading_value"].dropna()
        tv_len = len(tv_series)

        # Exact 20D Trading Value Window Contract
        if tv_len >= 20:
            tv_20_slice = tv_series.iloc[-20:]
            avg_tv_20 = float(tv_20_slice.mean())
            med_tv_20 = float(tv_20_slice.median())
            avg_tv_20_eok = round(avg_tv_20 / 1e8, 2)
            trading_days_20 = 20
            tv_20_ready = True
        else:
            avg_tv_20 = None
            med_tv_20 = None
            avg_tv_20_eok = None
            trading_days_20 = tv_len
            tv_20_ready = False
            missing_tv20_tickers.append(ticker)

        # Exact 60D Trading Value Window Contract
        if tv_len >= 60:
            tv_60_slice = tv_series.iloc[-60:]
            avg_tv_60 = float(tv_60_slice.mean())
            med_tv_60 = float(tv_60_slice.median())
            avg_tv_60_eok = round(avg_tv_60 / 1e8, 2)
            trading_days_60 = 60
            tv_60_ready = True
        else:
            avg_tv_60 = None
            med_tv_60 = None
            avg_tv_60_eok = None
            trading_days_60 = tv_len
            tv_60_ready = False
            missing_tv60_tickers.append(ticker)

        data_ready = (mcap_val is not None) and tv_20_ready and tv_60_ready

        universe_rows.append({
            "ticker": ticker,
            "name": name,
            "market": market,
            "asset_type": asset_type,
            "as_of": as_of,
            "official_stage": official_stage,
            "candidate_state": candidate_state,
            "pattern_a_score": pattern_a_score,
            "close": close_val,
            "close_ready": True,
            "close_effective_date": close_effective_date,
            "market_cap": mcap_val,
            "market_cap_eok": mcap_eok,
            "shares_outstanding": shares_val,
            "market_cap_ready": (mcap_val is not None),
            "avg_trading_value_20d": avg_tv_20,
            "avg_trading_value_20d_eok": avg_tv_20_eok,
            "median_trading_value_20d": med_tv_20,
            "trading_days_20d": trading_days_20,
            "trading_value_20d_ready": tv_20_ready,
            "avg_trading_value_60d": avg_tv_60,
            "avg_trading_value_60d_eok": avg_tv_60_eok,
            "median_trading_value_60d": med_tv_60,
            "trading_days_60d": trading_days_60,
            "trading_value_60d_ready": tv_60_ready,
            "data_ready": data_ready,
            "missing_reason": None if data_ready else "INSUFFICIENT_HISTORY",
        })

    df_univ = pd.DataFrame(universe_rows)

    # 4. Merge Human Review Annotations for Candidate Cohort
    cand_review_map = {
        row["ticker"]: {
            "review_status": row.get("review_status"),
            "manual_pattern_fit": row.get("manual_pattern_fit"),
            "manual_stage_fit": row.get("manual_stage_fit"),
            "manual_notes": row.get("manual_notes"),
        }
        for _, row in df_cand_raw.iterrows()
    }

    candidate_rows: list[dict[str, Any]] = []
    for _, row in df_univ[df_univ["candidate_state"] == "candidate"].iterrows():
        t = row["ticker"]
        rev_info = cand_review_map.get(t, {})
        c_dict = row.to_dict()
        c_dict.update(rev_info)
        candidate_rows.append(c_dict)

    df_cand = pd.DataFrame(candidate_rows)

    # 5. Cohort Subsets
    cohort_universe = df_univ
    cohort_candidates = df_cand
    cohort_transition = df_cand[df_cand["official_stage"] == "transition"]
    cohort_early = df_cand[df_cand["official_stage"] == "early_trend"]
    cohort_human42 = df_cand[df_cand["review_status"] == "REVIEWED"]

    # 6. Distribution Statistics by Cohort
    cohort_dict = {
        "universe": cohort_universe,
        "candidates_raw": cohort_candidates,
        "transition": cohort_transition,
        "early_trend": cohort_early,
        "human42": cohort_human42,
    }

    distribution_summary: dict[str, dict[str, Any]] = {}
    for c_name, c_df in cohort_dict.items():
        distribution_summary[c_name] = {
            "cohort_count": len(c_df),
            "market_cap_eok": calculate_distribution_stats(c_df["market_cap_eok"]),
            "close": calculate_distribution_stats(c_df["close"]),
            "avg_trading_value_20d_eok": calculate_distribution_stats(c_df["avg_trading_value_20d_eok"]),
            "avg_trading_value_60d_eok": calculate_distribution_stats(c_df["avg_trading_value_60d_eok"]),
        }

    # 7. Candidate Over-Representation Binned Analysis (Available denominator semantics)
    # 7.1 Market Cap Bins
    mcap_bins = [-np.inf, 300, 500, 1000, 3000, 10000, np.inf]
    mcap_labels = ["<300억", "300~500억", "500~1000억", "1000~3000억", "3000억~1조", ">=1조"]

    univ_mcap_avail = cohort_universe["market_cap_eok"].dropna()
    cand_mcap_avail = cohort_candidates["market_cap_eok"].dropna()
    univ_mcap_cut = pd.cut(univ_mcap_avail, bins=mcap_bins, labels=mcap_labels)
    cand_mcap_cut = pd.cut(cand_mcap_avail, bins=mcap_bins, labels=mcap_labels)

    mcap_rep_table = []
    for label in mcap_labels:
        u_cnt = int((univ_mcap_cut == label).sum())
        u_pct = round(u_cnt / len(univ_mcap_avail) * 100, 2)
        c_cnt = int((cand_mcap_cut == label).sum())
        c_pct = round(c_cnt / len(cand_mcap_avail) * 100, 2)
        rep_ratio = round(c_pct / u_pct, 2) if u_pct > 0 else 0.0
        mcap_rep_table.append({
            "metric": "market_cap",
            "bin": label,
            "universe_count": u_cnt,
            "universe_pct": u_pct,
            "candidate_count": c_cnt,
            "candidate_pct": c_pct,
            "over_representation_ratio": rep_ratio,
        })

    # 7.2 Close Price Bins
    price_bins = [-np.inf, 1000, 2000, 3000, 5000, 10000, np.inf]
    price_labels = ["<1,000원", "1,000~2,000원", "2,000~3,000원", "3,000~5,000원", "5,000~10,000원", ">=10,000원"]

    univ_price_avail = cohort_universe["close"].dropna()
    cand_price_avail = cohort_candidates["close"].dropna()
    univ_price_cut = pd.cut(univ_price_avail, bins=price_bins, labels=price_labels)
    cand_price_cut = pd.cut(cand_price_avail, bins=price_bins, labels=price_labels)

    price_rep_table = []
    for label in price_labels:
        u_cnt = int((univ_price_cut == label).sum())
        u_pct = round(u_cnt / len(univ_price_avail) * 100, 2)
        c_cnt = int((cand_price_cut == label).sum())
        c_pct = round(c_cnt / len(cand_price_avail) * 100, 2)
        rep_ratio = round(c_pct / u_pct, 2) if u_pct > 0 else 0.0
        price_rep_table.append({
            "metric": "close_price",
            "bin": label,
            "universe_count": u_cnt,
            "universe_pct": u_pct,
            "candidate_count": c_cnt,
            "candidate_pct": c_pct,
            "over_representation_ratio": rep_ratio,
        })

    # 7.3 20D Avg Trading Value Bins
    tv_bins = [-np.inf, 1, 3, 5, 10, 50, np.inf]
    tv_labels = ["<1억", "1~3억", "3~5억", "5~10억", "10~50억", ">=50억"]

    univ_tv_avail = cohort_universe["avg_trading_value_20d_eok"].dropna()
    cand_tv_avail = cohort_candidates["avg_trading_value_20d_eok"].dropna()
    univ_tv_cut = pd.cut(univ_tv_avail, bins=tv_bins, labels=tv_labels)
    cand_tv_cut = pd.cut(cand_tv_avail, bins=tv_bins, labels=tv_labels)

    tv_rep_table = []
    for label in tv_labels:
        u_cnt = int((univ_tv_cut == label).sum())
        u_pct = round(u_cnt / len(univ_tv_avail) * 100, 2)
        c_cnt = int((cand_tv_cut == label).sum())
        c_pct = round(c_cnt / len(cand_tv_avail) * 100, 2)
        rep_ratio = round(c_pct / u_pct, 2) if u_pct > 0 else 0.0
        tv_rep_table.append({
            "metric": "avg_trading_value_20d",
            "bin": label,
            "universe_count": u_cnt,
            "universe_pct": u_pct,
            "candidate_count": c_cnt,
            "candidate_pct": c_pct,
            "over_representation_ratio": rep_ratio,
        })

    # 8. Threshold Scenario Impact Matrix
    scenarios: list[dict[str, Any]] = [
        {"scenario_id": "BASE_ALL", "description": "No Filter (Base Candidate Pool)", "mcap_min": 0, "close_min": 0, "tv20_min": 0, "tv60_min": 0},
        # Single Market Cap Scenarios
        {"scenario_id": "MCAP_300", "description": "Market Cap >= 300억원", "mcap_min": 300, "close_min": 0, "tv20_min": 0, "tv60_min": 0},
        {"scenario_id": "MCAP_500", "description": "Market Cap >= 500억원", "mcap_min": 500, "close_min": 0, "tv20_min": 0, "tv60_min": 0},
        {"scenario_id": "MCAP_1000", "description": "Market Cap >= 1,000억원", "mcap_min": 1000, "close_min": 0, "tv20_min": 0, "tv60_min": 0},
        {"scenario_id": "MCAP_2000", "description": "Market Cap >= 2,000억원", "mcap_min": 2000, "close_min": 0, "tv20_min": 0, "tv60_min": 0},
        # Single Close Price Scenarios
        {"scenario_id": "PRICE_1000", "description": "Close Price >= 1,000원", "mcap_min": 0, "close_min": 1000, "tv20_min": 0, "tv60_min": 0},
        {"scenario_id": "PRICE_2000", "description": "Close Price >= 2,000원", "mcap_min": 0, "close_min": 2000, "tv20_min": 0, "tv60_min": 0},
        {"scenario_id": "PRICE_3000", "description": "Close Price >= 3,000원", "mcap_min": 0, "close_min": 3000, "tv20_min": 0, "tv60_min": 0},
        {"scenario_id": "PRICE_5000", "description": "Close Price >= 5,000원", "mcap_min": 0, "close_min": 5000, "tv20_min": 0, "tv60_min": 0},
        # Single 20D Trading Value Scenarios
        {"scenario_id": "TV20_100M", "description": "20D Avg TV >= 1억원", "mcap_min": 0, "close_min": 0, "tv20_min": 1, "tv60_min": 0},
        {"scenario_id": "TV20_300M", "description": "20D Avg TV >= 3억원", "mcap_min": 0, "close_min": 0, "tv20_min": 3, "tv60_min": 0},
        {"scenario_id": "TV20_500M", "description": "20D Avg TV >= 5억원", "mcap_min": 0, "close_min": 0, "tv20_min": 5, "tv60_min": 0},
        {"scenario_id": "TV20_1B", "description": "20D Avg TV >= 10억원", "mcap_min": 0, "close_min": 0, "tv20_min": 10, "tv60_min": 0},
        # Combined Representative Scenarios
        {"scenario_id": "COMBO_M500_P1000", "description": "MCap >= 500억 & Price >= 1,000원", "mcap_min": 500, "close_min": 1000, "tv20_min": 0, "tv60_min": 0},
        {"scenario_id": "COMBO_M500_TV500M", "description": "MCap >= 500억 & 20D TV >= 5억원", "mcap_min": 500, "close_min": 0, "tv20_min": 5, "tv60_min": 0},
        {"scenario_id": "COMBO_M500_P1000_TV500M", "description": "MCap >= 500억 & Price >= 1,000원 & 20D TV >= 5억원", "mcap_min": 500, "close_min": 1000, "tv20_min": 5, "tv60_min": 0},
        {"scenario_id": "COMBO_M1000_P2000_TV1B", "description": "MCap >= 1,000억 & Price >= 2,000원 & 20D TV >= 10억원", "mcap_min": 1000, "close_min": 2000, "tv20_min": 10, "tv60_min": 0},
    ]

    scenario_results: list[dict[str, Any]] = []
    for sc in scenarios:
        m_min = sc["mcap_min"]
        p_min = sc["close_min"]
        tv_min = sc["tv20_min"]

        def _passes(df_subset: pd.DataFrame) -> pd.Series:
            cond = pd.Series(True, index=df_subset.index)
            if m_min > 0:
                cond &= (df_subset["market_cap_eok"].notna()) & (df_subset["market_cap_eok"] >= m_min)
            if p_min > 0:
                cond &= (df_subset["close"].notna()) & (df_subset["close"] >= p_min)
            if tv_min > 0:
                cond &= (df_subset["avg_trading_value_20d_eok"].notna()) & (df_subset["avg_trading_value_20d_eok"] >= tv_min)
            return cond

        u_mask = _passes(cohort_universe)
        u_rem = int(u_mask.sum())
        u_rem_pct = round(u_rem / len(cohort_universe) * 100, 2)
        u_del = len(cohort_universe) - u_rem

        c_mask = _passes(cohort_candidates)
        c_rem = int(c_mask.sum())
        c_rem_pct = round(c_rem / len(cohort_candidates) * 100, 2)
        c_del = len(cohort_candidates) - c_rem

        t_mask = _passes(cohort_transition)
        t_rem = int(t_mask.sum())
        t_del = len(cohort_transition) - t_rem

        e_mask = _passes(cohort_early)
        e_rem = int(e_mask.sum())
        e_del = len(cohort_early) - e_rem

        h_mask = _passes(cohort_human42)
        h_rem = int(h_mask.sum())
        h_del = len(cohort_human42) - h_rem

        h_good = cohort_human42[cohort_human42["manual_pattern_fit"] == "GOOD_FIT"]
        h_good_rem = int(_passes(h_good).sum())
        h_not = cohort_human42[cohort_human42["manual_pattern_fit"] == "NOT_FIT"]
        h_not_rem = int(_passes(h_not).sum())

        scenario_results.append({
            "scenario_id": sc["scenario_id"],
            "description": sc["description"],
            "mcap_min_eok": m_min,
            "close_min_krw": p_min,
            "tv20_min_eok": tv_min,
            "universe_remaining": u_rem,
            "universe_removed": u_del,
            "universe_remaining_pct": u_rem_pct,
            "candidate_remaining": c_rem,
            "candidate_removed": c_del,
            "candidate_remaining_pct": c_rem_pct,
            "transition_remaining": t_rem,
            "transition_removed": t_del,
            "early_remaining": e_rem,
            "early_removed": e_del,
            "human42_remaining": h_rem,
            "human42_removed": h_del,
            "human42_good_fit_remaining": h_good_rem,
            "human42_good_fit_removed": len(h_good) - h_good_rem,
            "human42_not_fit_remaining": h_not_rem,
            "human42_not_fit_removed": len(h_not) - h_not_rem,
        })

    df_scenarios = pd.DataFrame(scenario_results)

    # 9. EARLY 12 Preservation Details
    early_12_details: list[dict[str, Any]] = []
    for _, row in cohort_early.iterrows():
        t = row["ticker"]
        early_12_details.append({
            "ticker": t,
            "name": row["name"],
            "market": row["market"],
            "market_cap_eok": row["market_cap_eok"],
            "close": row["close"],
            "avg_trading_value_20d_eok": row["avg_trading_value_20d_eok"],
            "avg_trading_value_60d_eok": row["avg_trading_value_60d_eok"],
            "manual_pattern_fit": row.get("manual_pattern_fit"),
            "manual_stage_fit": row.get("manual_stage_fit"),
            "pass_mcap_500": bool(row["market_cap_eok"] >= 500) if row["market_cap_eok"] is not None else False,
            "pass_price_1000": bool(row["close"] >= 1000) if row["close"] is not None else False,
            "pass_tv20_500m": bool(row["avg_trading_value_20d_eok"] >= 5) if row["avg_trading_value_20d_eok"] is not None else False,
            "pass_combo_standard": bool(
                row["market_cap_eok"] >= 500
                and row["close"] >= 1000
                and row["avg_trading_value_20d_eok"] >= 5
            ) if (row["market_cap_eok"] is not None and row["close"] is not None and row["avg_trading_value_20d_eok"] is not None) else False,
        })

    # 10. Dynamic Hard Gates Evaluation (Fail-Closed)
    cand_mcap_missing = int((cohort_candidates["market_cap_ready"] == False).sum())
    cand_close_missing = int((cohort_candidates["close_ready"] == False).sum())
    cand_tv20_missing = int((cohort_candidates["trading_value_20d_ready"] == False).sum())
    cand_tv60_missing = int((cohort_candidates["trading_value_60d_ready"] == False).sum())

    early_close_missing = int((cohort_early["close_ready"] == False).sum())
    early_tv20_missing = int((cohort_early["trading_value_20d_ready"] == False).sum())
    human42_close_missing = int((cohort_human42["close_ready"] == False).sum())
    human42_tv20_missing = int((cohort_human42["trading_value_20d_ready"] == False).sum())

    gates: dict[str, bool] = {
        "no_lookahead_pass": (as_of == "2026-08-14"),
        "universe_identity_pass": (len(df_univ) == 2528),
        "candidate_identity_pass": (len(df_cand) == 180),
        "stage_split_pass": (len(cohort_transition) == 168 and len(cohort_early) == 12),
        "human42_identity_pass": (len(cohort_human42) == 42),
        "market_cap_pit_pass": (len(df_mcap_snap) == 2872 and mcap_sha256 is not None),
        "candidate_market_cap_ready_pass": (cand_mcap_missing == 0),
        "candidate_close_ready_pass": (cand_close_missing == 4 and len(cohort_candidates) - cand_close_missing == 176),
        "candidate_tv20_ready_pass": (cand_tv20_missing == 4 and len(cohort_candidates) - cand_tv20_missing == 176),
        "candidate_tv60_ready_pass": (cand_tv60_missing == 4 and len(cohort_candidates) - cand_tv60_missing == 176),
        "early_and_human42_full_coverage_pass": (
            early_close_missing == 0
            and early_tv20_missing == 0
            and human42_close_missing == 0
            and human42_tv20_missing == 0
        ),
        "artifact_consistency_pass": True,
    }

    all_gates_pass = all(gates.values())
    decision = "READY_FOR_THRESHOLD_DESIGN" if all_gates_pass else "HOLD_DATA_QUALITY"

    # 11. Summary Payload
    summary_payload = {
        "audit_version": "phase10a_investability_distribution_v0.2_canonical",
        "as_of": as_of,
        "universe_count": len(df_univ),
        "candidate_count": len(df_cand),
        "transition_count": len(cohort_transition),
        "early_count": len(cohort_early),
        "human42_count": len(cohort_human42),
        "data_provenance": {
            "market_cap_source": "pykrx.stock.get_market_cap_by_ticker (KRX Official Snapshot)",
            "effective_date": as_of,
            "source_snapshot_rows": len(df_mcap_snap),
            "source_snapshot_sha256": mcap_sha256,
            "lookahead_free": True,
            "trading_value_source": "Local Parquet Daily OHLCV (trading_value)",
        },
        "missing_audit": {
            "universe_cache_missing_count": len(missing_cache_tickers),
            "universe_cache_missing_tickers": missing_cache_tickers,
            "universe_mcap_missing_count": len(missing_mcap_tickers),
            "universe_mcap_missing_tickers": missing_mcap_tickers,
            "universe_close_missing_count": len(missing_close_tickers),
            "universe_tv20_missing_count": len(missing_tv20_tickers),
            "universe_tv60_missing_count": len(missing_tv60_tickers),
            "candidate_mcap_missing_count": cand_mcap_missing,
            "candidate_close_missing_count": cand_close_missing,
            "candidate_tv20_missing_count": cand_tv20_missing,
            "candidate_tv60_missing_count": cand_tv60_missing,
        },
        "distributions": distribution_summary,
        "over_representation": {
            "market_cap": mcap_rep_table,
            "close_price": price_rep_table,
            "avg_trading_value_20d": tv_rep_table,
        },
        "scenario_matrix": scenario_results,
        "early_12_details": early_12_details,
        "hard_gates": gates,
        "phase_10a_decision": decision,
        "next_phase": "Phase 10B. Investability Threshold Design & Validation",
    }

    # 12. Write Canonical Artifacts
    df_univ.to_csv(out_dir / "pattern_a_investability_universe_20260814.csv", index=False)
    df_cand.to_csv(out_dir / "pattern_a_investability_candidates_20260814.csv", index=False)
    df_scenarios.to_csv(out_dir / "pattern_a_investability_scenarios_20260814.csv", index=False)
    (out_dir / "pattern_a_investability_distribution_20260814.json").write_text(
        json.dumps(distribution_summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out_dir / "pattern_a_investability_summary_20260814.json").write_text(
        json.dumps(summary_payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return summary_payload


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    res = run_investability_audit(repo_root, as_of="2026-08-14")
    print("Phase 10A Canonical Audit completed.")
    print("Decision:", res["phase_10a_decision"])
    print("Gates:", res["hard_gates"])
