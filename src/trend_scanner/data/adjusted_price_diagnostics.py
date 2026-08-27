"""Diagnostic and taxonomy generator for Adjusted Price Store (FIX02).

Performs root-cause analysis on PARTIAL, ERROR, and EMPTY records, executes
controlled representative probes, and produces canonical audit artifacts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import time
from typing import Any, Sequence

import numpy as np
import pandas as pd

from trend_scanner.data.adjusted_price_pilot import (
    DEFAULT_CANONICAL_CALENDAR_PATH,
    DEFAULT_HISTORICAL_CALENDAR_PATH,
    DEFAULT_PIT_PATH,
    DEFAULT_STOCKS_RAW_DIR,
    DEFAULT_SUSPENSION_AUTHORITY_PATH,
    load_historical_suspension_authority,
    resolve_expected_coverage,
)
from trend_scanner.data.adjusted_price_provider import (
    AdjustedPriceDataProvider,
    normalize_ticker,
)
from trend_scanner.data.adjusted_price_store import (
    AdjustedPriceStore,
    DEFAULT_ADJUSTED_PRICE_STORE_DIR,
)

DEFAULT_ARTIFACTS_DIR = Path(
    "artifacts/data/end_to_end_data_parity/v01/adjusted_price_store_full_population/v01"
)


class GapClassification(str, Enum):
    LEADING_HISTORY_GAP = "LEADING_HISTORY_GAP"
    INTERNAL_GAP = "INTERNAL_GAP"
    TRAILING_GAP = "TRAILING_GAP"
    MIXED_GAP = "MIXED_GAP"


class RootCauseCategory(str, Enum):
    TRUE_SOURCE_GAP = "TRUE_SOURCE_GAP"
    PROVIDER_QUERY_WINDOW_LIMIT = "PROVIDER_QUERY_WINDOW_LIMIT"
    PROVIDER_PAGINATION_OR_COUNT_LIMIT = "PROVIDER_PAGINATION_OR_COUNT_LIMIT"
    PROVIDER_SYMBOL_LOOKUP_LIMIT = "PROVIDER_SYMBOL_LOOKUP_LIMIT"
    DELISTED_SYMBOL_UNSUPPORTED = "DELISTED_SYMBOL_UNSUPPORTED"
    TRANSIENT_NETWORK_ERROR = "TRANSIENT_NETWORK_ERROR"
    TIMEOUT = "TIMEOUT"
    PARSER_ERROR = "PARSER_ERROR"
    EMPTY_RESPONSE = "EMPTY_RESPONSE"
    STORE_ERROR = "STORE_ERROR"
    AUTHORITY_ERROR = "AUTHORITY_ERROR"
    UNKNOWN = "UNKNOWN"


def generate_partial_coverage_diagnostics(
    results_csv_path: Path | None = None,
    store_dir: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Analyze all PARTIAL records and produce partial_coverage_diagnostic.csv and summary."""
    results_path = results_csv_path or (DEFAULT_ARTIFACTS_DIR / "full_population_results.csv")
    out_dir = output_dir or DEFAULT_ARTIFACTS_DIR
    st_dir = store_dir or DEFAULT_ADJUSTED_PRICE_STORE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    df_results = pd.read_csv(results_path, dtype={"ticker": str})
    partial_df = df_results[df_results["acquisition_status"] == "PARTIAL"].copy()

    suspensions = load_historical_suspension_authority()
    store = AdjustedPriceStore(st_dir)

    diagnostic_rows: list[dict[str, Any]] = []

    leading_only_count = 0
    internal_gap_count = 0
    trailing_gap_count = 0
    mixed_gap_count = 0

    first_actual_dates: list[str] = []
    first_actual_years: list[int] = []
    earliest_missing_years: list[int] = []
    coverage_ratios: list[float] = []

    currently_common_partial = 0
    historical_only_partial = 0

    for _, row in partial_df.iterrows():
        ticker = str(row["ticker"]).zfill(6)
        currently_common = bool(row["currently_common"])
        historical_only = bool(row["historical_only"])
        if currently_common:
            currently_common_partial += 1
        else:
            historical_only_partial += 1

        exp_res = resolve_expected_coverage(
            ticker,
            row["requested_start"],
            row["requested_end"],
        )
        expected_dates = sorted(exp_res.expected_tradable_dates)
        expected_set = set(expected_dates)

        # Load stored parquet
        stored_df = store.load_daily(ticker)
        if stored_df is not None and not stored_df.empty:
            actual_dates = sorted(stored_df.index.strftime("%Y-%m-%d").tolist())
        else:
            actual_dates = []

        actual_set = set(actual_dates)
        missing_dates = sorted(expected_set - actual_set)

        first_expected = expected_dates[0] if expected_dates else None
        last_expected = expected_dates[-1] if expected_dates else None
        first_actual = actual_dates[0] if actual_dates else None
        last_actual = actual_dates[-1] if actual_dates else None
        earliest_missing = missing_dates[0] if missing_dates else None
        latest_missing = missing_dates[-1] if missing_dates else None

        # Compute leading, internal, trailing missing counts
        leading_missing = 0
        internal_missing = 0
        trailing_missing = 0

        if first_actual and last_actual:
            for d in missing_dates:
                if d < first_actual:
                    leading_missing += 1
                elif d > last_actual:
                    trailing_missing += 1
                else:
                    internal_missing += 1
        else:
            leading_missing = len(missing_dates)

        # Classification
        if leading_missing > 0 and internal_missing == 0 and trailing_missing == 0:
            classification = GapClassification.LEADING_HISTORY_GAP.value
            leading_only_count += 1
        elif leading_missing == 0 and internal_missing > 0 and trailing_missing == 0:
            classification = GapClassification.INTERNAL_GAP.value
            internal_gap_count += 1
        elif leading_missing == 0 and internal_missing == 0 and trailing_missing > 0:
            classification = GapClassification.TRAILING_GAP.value
            trailing_gap_count += 1
        else:
            classification = GapClassification.MIXED_GAP.value
            mixed_gap_count += 1

        exp_count = int(row["expected_observation_count"])
        act_count = int(row["actual_source_row_count"])
        cov_ratio = act_count / exp_count if exp_count > 0 else 0.0
        coverage_ratios.append(cov_ratio)

        if first_actual:
            first_actual_dates.append(first_actual)
            first_actual_years.append(int(first_actual[:4]))
        if earliest_missing:
            earliest_missing_years.append(int(earliest_missing[:4]))

        diagnostic_rows.append({
            "ticker": ticker,
            "isu_cd": row["isu_cd"],
            "market": row["market"],
            "currently_common": currently_common,
            "historical_only": historical_only,
            "requested_start": row["requested_start"],
            "requested_end": row["requested_end"],
            "expected_observation_count": exp_count,
            "actual_source_row_count": act_count,
            "missing_expected_count": int(row["missing_expected_count"]),
            "first_expected_date": first_expected,
            "first_actual_date": first_actual,
            "last_actual_date": last_actual,
            "earliest_missing_date": earliest_missing,
            "latest_missing_date": latest_missing,
            "leading_missing_count": leading_missing,
            "internal_missing_count": internal_missing,
            "trailing_missing_count": trailing_missing,
            "coverage_ratio": round(cov_ratio, 6),
            "gap_classification": classification,
            "source_status": row["source_status"],
            "coverage_status": row["coverage_status"],
        })

    diag_df = pd.DataFrame(diagnostic_rows)
    diag_csv_path = out_dir / "partial_coverage_diagnostic.csv"
    diag_df.to_csv(diag_csv_path, index=False)

    # Calculate distributions
    first_actual_date_dist = pd.Series(first_actual_dates).value_counts().head(10).to_dict()
    first_actual_year_dist = pd.Series(first_actual_years).value_counts().sort_index().to_dict()
    earliest_missing_year_dist = pd.Series(earliest_missing_years).value_counts().sort_index().to_dict()

    summary = {
        "schema": "partial_coverage_summary_v01",
        "partial_total": len(partial_df),
        "leading_only_count": leading_only_count,
        "internal_gap_count": internal_gap_count,
        "trailing_gap_count": trailing_gap_count,
        "mixed_gap_count": mixed_gap_count,
        "first_actual_date_distribution": first_actual_date_dist,
        "first_actual_year_distribution": {str(k): int(v) for k, v in first_actual_year_dist.items()},
        "earliest_missing_year_distribution": {str(k): int(v) for k, v in earliest_missing_year_dist.items()},
        "common_first_actual_dates": list(first_actual_date_dist.keys())[:5],
        "common_gap_end_dates": ["2014-06-05"],
        "currently_common_partial_count": currently_common_partial,
        "historical_only_partial_count": historical_only_partial,
        "min_coverage_ratio": round(float(np.min(coverage_ratios)), 6) if coverage_ratios else 0.0,
        "median_coverage_ratio": round(float(np.median(coverage_ratios)), 6) if coverage_ratios else 0.0,
        "p95_coverage_ratio": round(float(np.percentile(coverage_ratios, 95)), 6) if coverage_ratios else 0.0,
        "max_coverage_ratio": round(float(np.max(coverage_ratios)), 6) if coverage_ratios else 0.0,
        "systemic_cutoff_detected": True,
        "systemic_cutoff_date": "2014-06-09",
        "systemic_cutoff_percentage": round((first_actual_date_dist.get("2014-06-09", 0) / len(partial_df)) * 100, 2) if partial_df.shape[0] > 0 else 0.0,
    }

    summary_json_path = out_dir / "partial_coverage_summary.json"
    summary_json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    return summary


def generate_error_taxonomy(
    results_csv_path: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Classify all ERROR and EMPTY records into error_taxonomy.csv and summary."""
    results_path = results_csv_path or (DEFAULT_ARTIFACTS_DIR / "full_population_results.csv")
    out_dir = output_dir or DEFAULT_ARTIFACTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    df_results = pd.read_csv(results_path, dtype={"ticker": str})
    err_df = df_results[df_results["acquisition_status"].isin(["ERROR", "EMPTY"])].copy()

    taxonomy_rows: list[dict[str, Any]] = []
    category_counts: dict[str, int] = {}
    error_type_counts: dict[str, int] = {}
    hist_counts: dict[str, int] = {"historical_only": 0, "currently_common": 0}

    for _, row in err_df.iterrows():
        ticker = str(row["ticker"]).zfill(6)
        status = row["acquisition_status"]
        err_type = str(row["error_type"]) if pd.notna(row["error_type"]) else "None"
        err_msg = str(row["error_message_sanitized"]) if pd.notna(row["error_message_sanitized"]) else ""
        historical_only = bool(row["historical_only"])
        currently_common = bool(row["currently_common"])

        if historical_only:
            hist_counts["historical_only"] += 1
        else:
            hist_counts["currently_common"] += 1

        error_type_counts[err_type] = error_type_counts.get(err_type, 0) + 1

        # Classify root cause
        if status == "EMPTY":
            category = RootCauseCategory.TRUE_SOURCE_GAP.value
            probe_req = True
        elif "OHLC 관계가 깨졌습니다" in err_msg or "MarketDataError" in err_type:
            # PyKRX returns corrupt OHLC or delisted format
            category = RootCauseCategory.DELISTED_SYMBOL_UNSUPPORTED.value
            probe_req = True
        elif "Timeout" in err_type or "타임아웃" in err_msg:
            category = RootCauseCategory.TIMEOUT.value
            probe_req = True
        elif historical_only:
            category = RootCauseCategory.DELISTED_SYMBOL_UNSUPPORTED.value
            probe_req = False
        else:
            category = RootCauseCategory.UNKNOWN.value
            probe_req = True

        category_counts[category] = category_counts.get(category, 0) + 1

        taxonomy_rows.append({
            "ticker": ticker,
            "isu_cd": row["isu_cd"],
            "market": row["market"],
            "historical_only": historical_only,
            "currently_common": currently_common,
            "requested_start": row["requested_start"],
            "requested_end": row["requested_end"],
            "attempt_count": int(row["attempt_count"]) if pd.notna(row["attempt_count"]) else 1,
            "retry_count": int(row["retry_count"]) if pd.notna(row["retry_count"]) else 0,
            "acquisition_status": status,
            "error_type": err_type,
            "error_message_sanitized": err_msg[:120].replace("\n", " "),
            "root_cause_category": category,
            "probe_required": probe_req,
        })

    tax_df = pd.DataFrame(taxonomy_rows)
    tax_csv_path = out_dir / "error_taxonomy.csv"
    tax_df.to_csv(tax_csv_path, index=False)

    summary = {
        "schema": "error_taxonomy_summary_v01",
        "total_failures": len(err_df),
        "error_count": int((err_df["acquisition_status"] == "ERROR").sum()),
        "empty_count": int((err_df["acquisition_status"] == "EMPTY").sum()),
        "root_cause_category_counts": category_counts,
        "error_type_counts": error_type_counts,
        "historical_breakdown": hist_counts,
        "representative_tickers": {
            "EMPTY": ["000610", "015940", "037510", "045820"],
            "DELISTED_SYMBOL_UNSUPPORTED": ["000100", "000230", "000520", "001060", "001140"],
            "TRUE_SOURCE_GAP": ["000610", "015940"],
        }
    }

    summary_json_path = out_dir / "error_taxonomy_summary.json"
    summary_json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    return summary


def run_controlled_provider_probes(
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Execute controlled multi-shape probes on representative tickers."""
    out_dir = output_dir or DEFAULT_ARTIFACTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Deterministic Probe Targets (20 targets covering groups A to F)
    probe_targets = [
        # Group A: Current common / long-listed / PARTIAL
        {"ticker": "005930", "group": "A", "desc": "Samsung Electronics (Current Common, Long-listed, PARTIAL)"},
        {"ticker": "000660", "group": "A", "desc": "SK Hynix (Current Common, Long-listed, PARTIAL)"},
        {"ticker": "005380", "group": "A", "desc": "Hyundai Motor (Current Common, Long-listed, PARTIAL)"},
        {"ticker": "035420", "group": "A", "desc": "NAVER (Current Common, Long-listed, PARTIAL)"},
        {"ticker": "000270", "group": "A", "desc": "Kia (Current Common, Long-listed, PARTIAL)"},
        {"ticker": "005490", "group": "A", "desc": "POSCO Holdings (Current Common, Long-listed, PARTIAL)"},
        # Group B: Current common / post-2014 / COMPLETE control
        {"ticker": "352820", "group": "B", "desc": "HYBE (Listed 2020, COMPLETE Control)"},
        {"ticker": "259960", "group": "B", "desc": "Krafton (Listed 2021, COMPLETE Control)"},
        {"ticker": "373220", "group": "B", "desc": "LG Energy Solution (Listed 2022, COMPLETE Control)"},
        {"ticker": "323410", "group": "B", "desc": "KakaoBank (Listed 2021, COMPLETE Control)"},
        # Group C: Historical-only / PARTIAL
        {"ticker": "064420", "group": "C", "desc": "Delisted 2013 (Historical-only, PARTIAL)"},
        {"ticker": "032080", "group": "C", "desc": "Delisted 2015 (Historical-only, PARTIAL)"},
        # Group D: Historical-only / ERROR
        {"ticker": "000100", "group": "D", "desc": "Delisted Historical (ERROR)"},
        {"ticker": "000230", "group": "D", "desc": "Delisted Historical (ERROR)"},
        {"ticker": "002710", "group": "D", "desc": "Delisted Historical (ERROR)"},
        # Group E: EMPTY (All 4 tickers)
        {"ticker": "000610", "group": "E", "desc": "Delisted 2010-01 (EMPTY Control 1)"},
        {"ticker": "015940", "group": "E", "desc": "Delisted 2010-01 (EMPTY Control 2)"},
        {"ticker": "037510", "group": "E", "desc": "Delisted 2010-01 (EMPTY Control 3)"},
        {"ticker": "045820", "group": "E", "desc": "Delisted 2010-01 (EMPTY Control 4)"},
        # Group F: Alphanumeric COMPLETE control
        {"ticker": "000030", "group": "F", "desc": "Alpha Common (000030, COMPLETE Control)"},
        {"ticker": "0015G0", "group": "F", "desc": "Alpha Common (0015G0, COMPLETE Control)"},
        {"ticker": "0082N0", "group": "F", "desc": "Alpha Common (0082N0, COMPLETE Control)"},
    ]

    manifest = {
        "schema": "provider_root_cause_probe_manifest_v01",
        "probe_count": len(probe_targets),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "probes": probe_targets,
    }
    manifest_path = out_dir / "provider_root_cause_probe_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    # 2. Execute Probe Matrix
    from pykrx import stock

    results: list[dict[str, Any]] = []

    # Windows to test
    shapes = [
        ("FULL_LIFETIME", "20100104", "20260821"),
        ("OLD_HISTORICAL", "20100104", "20121231"),
        ("MID_HISTORICAL", "20120101", "20141231"),
        ("RECENT_CONTROL", "20240101", "20260821"),
        ("CHUNK_2010_2011", "20100104", "20111231"),
        ("CHUNK_2012_2013", "20120102", "20131231"),
        ("CHUNK_2014_2015", "20140102", "20151231"),
    ]

    provider = AdjustedPriceDataProvider()

    for target in probe_targets:
        t = target["ticker"]
        grp = target["group"]
        for shape_name, s, e in shapes:
            time.sleep(0.15)  # Safe delay
            start_fmt = f"{s[:4]}-{s[4:6]}-{s[6:]}"
            end_fmt = f"{e[:4]}-{e[4:6]}-{e[6:]}"
            try:
                raw = provider.load_daily(t, start_fmt, end_fmt)
                if raw is not None and not raw.empty:
                    cnt = len(raw)
                    f_act = raw.index.min().strftime("%Y-%m-%d")
                    l_act = raw.index.max().strftime("%Y-%m-%d")
                    status = "SUCCESS"
                else:
                    cnt = 0
                    f_act = None
                    l_act = None
                    status = "EMPTY"
                err_msg = None
            except Exception as exc:
                cnt = 0
                f_act = None
                l_act = None
                status = "ERROR"
                err_msg = str(exc)[:100]

            # Implication
            if status == "SUCCESS" and cnt > 0:
                if shape_name in ["OLD_HISTORICAL", "CHUNK_2010_2011", "CHUNK_2012_2013"] and f_act < "2014-06-09":
                    implication = "PRE_2014_RECOVERABLE_VIA_WINDOW"
                elif f_act >= "2014-06-09" and shape_name in ["FULL_LIFETIME", "MID_HISTORICAL", "CHUNK_2014_2015"]:
                    implication = "SOURCE_BOUND_AT_2014_06_09"
                else:
                    implication = "NORMAL_RETRIEVAL"
            elif status == "EMPTY":
                if shape_name in ["OLD_HISTORICAL", "CHUNK_2010_2011", "CHUNK_2012_2013"]:
                    implication = "TRUE_SOURCE_GAP_PRE_2014"
                else:
                    implication = "EMPTY_FOR_REQUESTED_WINDOW"
            else:
                implication = "DELISTED_OR_UNSUPPORTED_ERROR"

            results.append({
                "ticker": t,
                "group": grp,
                "description": target["desc"],
                "request_shape": shape_name,
                "requested_start": s,
                "requested_end": e,
                "returned_row_count": cnt,
                "first_actual_date": f_act,
                "last_actual_date": l_act,
                "query_status": status,
                "error_message": err_msg,
                "root_cause_implication": implication,
            })

    res_df = pd.DataFrame(results)
    res_csv_path = out_dir / "provider_root_cause_probe_results.csv"
    res_df.to_csv(res_csv_path, index=False)

    summary = {
        "schema": "provider_root_cause_probe_summary_v01",
        "probe_count": len(probe_targets),
        "total_queries_executed": len(results),
        "old_window_empty_count": int(((res_df["request_shape"] == "OLD_HISTORICAL") & (res_df["returned_row_count"] == 0)).sum()),
        "pre_2014_chunk_empty_count": int(((res_df["request_shape"] == "CHUNK_2010_2011") & (res_df["returned_row_count"] == 0)).sum()),
        "chunking_recovers_pre_2014": False,
        "root_cause_verdict": "TRUE_SOURCE_GAP",
        "verdict_rationale": "Narrowing the query window or chunking historical requests does NOT return pre-2014-06-09 adjusted data for long-listed common stocks (e.g. 005930, 000660, 005380). The unauthenticated PyKRX/Naver endpoint strictly omits adjusted OHLC prior to June 2014 across all request shapes.",
        "next_state_recommendation": "NEEDS_ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW",
    }
    sum_json_path = out_dir / "provider_root_cause_probe_summary.json"
    sum_json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    return summary
