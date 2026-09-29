#!/usr/bin/env python3
"""Freeze the official ETF-36 set, audit coverage, and compare A FAST V2 with Julia V00."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import math
from pathlib import Path
import tempfile
import time
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from scripts import run_etf_current_survivors_raw_price_three_strategy_simple_backtest_v03 as base  # noqa: E402
from trend_scanner.backtest.standard_windows import (  # noqa: E402
    STANDARD_BACKTEST_WINDOWS,
    resolve_standard_backtest_window,
)

OUTPUT_REL = Path("artifacts/research/etf_36_afast_v2_vs_julia_5window_simple_v01")
V04_REL = Path("artifacts/research/etf_official_universe_refinement_v04/official_representative_etf_universe_v04.csv")
V02_CLASSIFIED_REL = Path("artifacts/research/etf_official_universe_refinement_v02/classified_universe.csv")
EXPECTED_TICKERS = set("""
069500 229200 360750 133690 241180 283580 453810 379790 251350 195980
256440 245710 091180 091170 117700 266410 228790 449450 117460 300950
143860 139230 367760 140700 228810 305720 102970 091160 157490 117680
228800 411060 144600 261220 160580 271060
""".split())
TAXABLE_TICKERS = set("""
360750 133690 241180 283580 453810 379790 251350 195980 256440 245710
411060 144600 261220 160580 271060
""".split())
EXPECTED_CATEGORY_COUNTS = {
    "MARKET_INDEX": 12,
    "SECTOR_INDEX": 19,
    "COMMODITY_RESOURCE": 5,
}
EXPECTED_WINDOWS = {
    "P1": ("2014-01-02", "2026-08-31", "2026-09-01"),
    "P2-1": ("2021-01-04", "2025-05-30", "2025-06-02"),
    "P2-2": ("2021-01-04", "2026-08-31", "2026-09-01"),
    "P3-1": ("2022-01-03", "2025-05-30", "2025-06-02"),
    "P3-2": ("2022-01-03", "2026-08-31", "2026-09-01"),
}
WORKERS = 10
_WINDOWS: dict[str, dict[str, str]] = {}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _norm_ticker(value: Any) -> str:
    value = str(value).strip()
    if value.endswith(".0"):
        value = value[:-2]
    return value.zfill(6)


def _iso(value: Any) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _load_universe() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    v04_path = ROOT / V04_REL
    v02_path = ROOT / V02_CLASSIFIED_REL
    v04 = pd.read_csv(v04_path, dtype={"ticker": "string"}, encoding="utf-8-sig")
    v04["ticker"] = v04["ticker"].map(_norm_ticker)
    v02 = pd.read_csv(v02_path, dtype={"ticker": "string"}, encoding="utf-8-sig")
    v02["ticker"] = v02["ticker"].map(_norm_ticker)
    v04_set = set(v04["ticker"])
    selected = v04.loc[v04["ticker"] != "474800"].copy()
    merged = selected.merge(
        v02[["ticker", "ISU_CD", "TAX_TP_CD"]],
        on="ticker", how="left", validate="one_to_one",
    )
    merged["declared_taxable"] = merged["ticker"].isin(TAXABLE_TICKERS)
    merged["krx_taxable"] = merged["TAX_TP_CD"].astype(str).str.startswith("배당소득세")
    metadata_mismatch = merged.loc[
        merged["declared_taxable"] != merged["krx_taxable"], "ticker"
    ].astype(str).tolist()
    required = {"ticker", "ETF_name", "listing_date", "major_category", "representative_group"}
    errors: list[str] = []
    if len(v04) != 37 or v04["ticker"].duplicated().any():
        errors.append("V04_UNIVERSE_COUNT_OR_DUPLICATE_MISMATCH")
    if v04_set != EXPECTED_TICKERS | {"474800"}:
        errors.append("V04_TICKER_SET_MISMATCH")
    if set(merged["ticker"]) != EXPECTED_TICKERS or len(merged) != 36:
        errors.append("SELECTED_TICKER_SET_MISMATCH")
    if not required.issubset(merged.columns):
        errors.append("V04_REQUIRED_COLUMNS_MISSING")
    if merged["ISU_CD"].isna().any() or merged["TAX_TP_CD"].isna().any():
        errors.append("KRX_PRODUCT_MASTER_METADATA_MISSING")
    if metadata_mismatch:
        errors.append("TAX_METADATA_VS_KRX_PRODUCT_MASTER_MISMATCH")
    counts = merged["major_category"].value_counts().to_dict()
    if counts != EXPECTED_CATEGORY_COUNTS:
        errors.append("CATEGORY_COUNT_MISMATCH")
    if int(merged["declared_taxable"].sum()) != 15 or int((~merged["declared_taxable"]).sum()) != 21:
        errors.append("TAX_METADATA_COUNT_MISMATCH")

    merged["ticker"] = merged["ticker"].map(_norm_ticker)
    merged["listing_date"] = pd.to_datetime(merged["listing_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    merged["general_account_trading_gain_tax"] = np.where(
        merged["declared_taxable"], "TAXABLE", "NON_TAXABLE_DOMESTIC_STOCK_ETF"
    )
    merged["tax_metadata_basis"] = "KRX_V02_PRODUCT_MASTER_TAX_TP_CD; classification frozen per W.md"
    merged["tax_applied_to_backtest_pnl"] = False
    rows = []
    for row in merged.sort_values("ticker").to_dict("records"):
        rows.append({
            "ticker": row["ticker"], "name": str(row["ETF_name"]).strip(),
            "listing_date": row["listing_date"], "major_category": row["major_category"],
            "representative_group": row["representative_group"], "ISU_CD": str(row["ISU_CD"]).strip(),
            "general_account_trading_gain_tax": row["general_account_trading_gain_tax"],
            "KRX_TAX_TP_CD": row["TAX_TP_CD"], "tax_metadata_basis": row["tax_metadata_basis"],
            "tax_applied_to_backtest_pnl": False,
        })
    metadata = {
        "errors": errors,
        "selected_count": len(rows),
        "category_counts": counts,
        "taxable_count": int(merged["declared_taxable"].sum()),
        "non_taxable_count": int((~merged["declared_taxable"]).sum()),
        "tax_metadata_mismatch_tickers": metadata_mismatch,
        "v04_sha256": _sha256(v04_path),
        "v02_product_master_sha256": _sha256(v02_path),
        "v04_commit": "4f3afe29dd80dd282bc482709768c4a84fa58538",
        "excluded_ticker": "474800",
    }
    return rows, metadata


def _resolved_windows(calendar_dates: list[str]) -> tuple[dict[str, dict[str, str]], list[str]]:
    calendar, _month_ends = base._calendar_from_dates(calendar_dates)
    resolved: dict[str, dict[str, str]] = {}
    errors: list[str] = []
    for window_id in STANDARD_BACKTEST_WINDOWS:
        item = resolve_standard_backtest_window(window_id, calendar)
        row = {
            "window_id": window_id,
            "window_start": _iso(item.effective_start),
            "window_end": _iso(item.effective_end),
            "execution_support_date": _iso(item.execution_support),
        }
        resolved[window_id] = row
        if tuple(row[key] for key in ("window_start", "window_end", "execution_support_date")) != EXPECTED_WINDOWS[window_id]:
            errors.append(f"STANDARD_WINDOW_DATE_MISMATCH:{window_id}")
    return resolved, errors


def _worker_init(db_path: str, score: dict[str, Any], stage: dict[str, Any], calendar: list[str], month_ends: list[str]) -> None:
    global _WINDOWS
    base._init_worker(db_path, score, stage, calendar, month_ends)
    _WINDOWS, errors = _resolved_windows(calendar)
    if errors:
        raise RuntimeError(f"STANDARD_WINDOW_RESOLUTION_FAILED:{errors}")


def _ticker_data_findings(daily: pd.DataFrame, listing_date: str) -> dict[str, Any]:
    if daily.empty:
        return {"errors": ["NO_RAW_ETF_PRICE_HISTORY"], "missing_sessions": [], "missing_required_dates": [], "nontrading_zero_ohlc_row_count": 0}
    daily = daily.loc[daily.index >= pd.Timestamp(listing_date)]
    if daily.empty:
        return {"errors": ["RAW_ROWS_PRECEDE_LISTING_DATE_ONLY"], "missing_sessions": [], "missing_required_dates": [], "nontrading_zero_ohlc_row_count": 0}
    dates = set(daily.index)
    calendar_dates = base._WORKER["calendar_dates"]
    raw_start = max(pd.Timestamp(daily.index.min()), pd.Timestamp(listing_date))
    last_support = max(pd.Timestamp(item["execution_support_date"]) for item in _WINDOWS.values())
    expected = [pd.Timestamp(day) for day in calendar_dates if raw_start <= pd.Timestamp(day) <= last_support]
    missing = [day.strftime("%Y-%m-%d") for day in expected if day not in dates]
    all_required = sorted({date for item in _WINDOWS.values() for date in (item["window_end"], item["execution_support_date"])})
    missing_required = [date for date in all_required if pd.Timestamp(date) >= raw_start and pd.Timestamp(date) not in dates]
    errors = []
    if missing:
        errors.append(f"RAW_KRX_SESSION_GAPS:{len(missing)}")
    if missing_required:
        errors.append(f"MISSING_WINDOW_END_OR_SUPPORT_ROWS:{len(missing_required)}")
    numeric = daily[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
    nonfinite = ~np.isfinite(numeric.to_numpy(dtype=float))
    if nonfinite.any():
        errors.append(f"NONFINITE_RAW_BAR_VALUES:{int(nonfinite.sum())}")
    nonpositive_ohlc = (numeric[["open", "high", "low", "close"]] <= 0).any(axis=1)
    no_trade_sentinel = (
        numeric["open"].eq(0) & numeric["high"].eq(0) & numeric["low"].eq(0)
        & numeric["close"].gt(0) & numeric["volume"].eq(0)
    )
    invalid_nonpositive = nonpositive_ohlc & ~no_trade_sentinel
    if invalid_nonpositive.any():
        errors.append(f"INVALID_NONPOSITIVE_RAW_OHLC_ROWS:{int(invalid_nonpositive.sum())}")
    if (numeric["volume"] < 0).any():
        errors.append("NEGATIVE_RAW_VOLUME")
    return {
        "errors": errors,
        "missing_sessions": missing[:25],
        "missing_session_count": len(missing),
        "missing_required_dates": missing_required,
        "first_raw_date": _iso(daily.index.min()),
        "last_raw_date": _iso(daily.index.max()),
        "raw_session_count": int(len(daily)),
        "nontrading_zero_ohlc_row_count": int(no_trade_sentinel.sum()),
        "nontrading_zero_ohlc_first_date": _iso(daily.index[no_trade_sentinel][0]) if no_trade_sentinel.any() else None,
        "nontrading_zero_ohlc_last_date": _iso(daily.index[no_trade_sentinel][-1]) if no_trade_sentinel.any() else None,
    }


def _preflight_ticker(instrument: dict[str, Any]) -> dict[str, Any]:
    ticker = _norm_ticker(instrument["ticker"])
    daily = base._load_ticker_daily(ticker)
    findings = _ticker_data_findings(daily, instrument["listing_date"])
    if daily.empty or "RAW_ROWS_PRECEDE_LISTING_DATE_ONLY" in findings.get("errors", []):
        return {"ticker": ticker, "fast_ready_date": None, "readiness_evaluations": 0, **findings}
    if findings.get("errors"):
        return {"ticker": ticker, "fast_ready_date": None, "readiness_evaluations": 0, **findings}
    daily = daily.loc[daily.index >= pd.Timestamp(instrument["listing_date"])].copy()
    context = base.build_precomputed_ticker_context(ticker, instrument["name"], daily)
    try:
        ready_date, evaluation_count = base._find_fast_ready_date(
            ticker, instrument["name"], daily, context, instrument["listing_date"]
        )
        findings["fast_ready_date"] = ready_date
        findings["readiness_evaluations"] = evaluation_count
    except Exception as exc:
        findings["fast_ready_date"] = None
        findings["readiness_evaluations"] = 0
        findings["errors"].append(f"READINESS_EVALUATOR_ERROR:{type(exc).__name__}:{str(exc)[:240]}")
    return {"ticker": ticker, **findings}


def _collect_worker_results(
    function: Any,
    universe: list[dict[str, Any]],
    db_path: Path,
    data_info: dict[str, Any],
    init_score_stage: tuple[dict[str, Any], dict[str, Any]],
) -> list[dict[str, Any]]:
    if WORKERS != 10:
        raise RuntimeError(f"REQUIRES_EXACTLY_10_WORKERS:{WORKERS}")
    score, stage = init_score_stage
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(
        max_workers=WORKERS,
        initializer=_worker_init,
        initargs=(str(db_path), score, stage, data_info["calendar_dates_internal"], data_info["month_ends_internal"]),
    ) as pool:
        future_map = {pool.submit(function, row): row["ticker"] for row in universe}
        for done, future in enumerate(as_completed(future_map), start=1):
            ticker = future_map[future]
            try:
                results.append(future.result())
            except Exception as exc:
                results.append({
                    "ticker": ticker, "errors": [f"WORKER_ERROR:{type(exc).__name__}:{str(exc)[:320]}"],
                    "fast_ready_date": None, "readiness_evaluations": 0,
                })
            if done % 5 == 0 or done == len(universe):
                print(f"ETF-36 worker progress {done}/{len(universe)}", flush=True)
    return sorted(results, key=lambda row: row["ticker"])


def _make_span_audit(
    universe: list[dict[str, Any]],
    readiness: list[dict[str, Any]],
    windows: dict[str, dict[str, str]],
    calendar_dates: list[str],
) -> pd.DataFrame:
    ready_by_ticker = {row["ticker"]: row for row in readiness}
    rows: list[dict[str, Any]] = []
    for instrument in universe:
        ticker = instrument["ticker"]
        ready = ready_by_ticker.get(ticker, {})
        ready_date = ready.get("fast_ready_date")
        for window in windows.values():
            start, end = window["window_start"], window["window_end"]
            v2_date = ready_date
            julia_date = ready_date
            comparison_start = None
            comparison_end = None
            status = "NOT_EVALUABLE"
            reason = "NO_STRATEGY_READY_DATE_BY_MAX_CUTOFF" if ready_date is None else "STRATEGY_READY_AFTER_WINDOW_END"
            coverage_sessions = 0
            if v2_date is not None and julia_date is not None:
                comparison_start = max(start, v2_date, julia_date)
                if comparison_start <= end:
                    sessions = [day for day in calendar_dates if comparison_start <= day <= end]
                    comparison_end = end
                    coverage_sessions = len(sessions)
                    status = "FULL_WINDOW" if comparison_start == start else "PARTIAL_WINDOW"
                    reason = ""
            rows.append({
                "window_id": window["window_id"], "ticker": ticker, "ETF_name": instrument["name"],
                "major_category": instrument["major_category"], "listing_date": instrument["listing_date"],
                "window_start": start, "window_end": end,
                "v2_strategy_eligible_date": v2_date, "julia_strategy_eligible_date": julia_date,
                "comparison_effective_start": comparison_start, "comparison_effective_end": comparison_end,
                "coverage_status": status, "coverage_sessions": coverage_sessions,
                "reason_if_not_evaluable": reason,
            })
    return pd.DataFrame(rows).sort_values(["window_id", "ticker"], kind="mergesort")


def _preflight_validation(
    universe: list[dict[str, Any]],
    universe_meta: dict[str, Any],
    readiness: list[dict[str, Any]],
    audit: pd.DataFrame,
    data_info: dict[str, Any],
    window_errors: list[str],
) -> dict[str, Any]:
    structural_errors = list(universe_meta["errors"]) + list(window_errors)
    readiness_by_ticker = {row["ticker"]: row for row in readiness}
    for row in readiness:
        for error in row.get("errors", []):
            structural_errors.append(f"{row['ticker']}:{error}")
    if len(readiness_by_ticker) != 36 or set(readiness_by_ticker) != EXPECTED_TICKERS:
        structural_errors.append("READINESS_TICKER_COVERAGE_MISMATCH")

    expected_pairs = {(window, ticker) for window in EXPECTED_WINDOWS for ticker in EXPECTED_TICKERS}
    audit_pairs = set(zip(audit["window_id"], audit["ticker"]))
    if len(audit) != 180 or audit_pairs != expected_pairs or audit.duplicated(["window_id", "ticker"]).any():
        structural_errors.append("SPAN_AUDIT_PAIR_OR_COUNT_MISMATCH")
    if audit["reason_if_not_evaluable"].isna().any():
        structural_errors.append("NOT_EVALUABLE_REASON_MISSING")
    if not audit.loc[audit["coverage_status"] != "NOT_EVALUABLE", "reason_if_not_evaluable"].eq("").all():
        structural_errors.append("EVALUABLE_SPAN_HAS_NOT_EVALUABLE_REASON")
    if (audit["v2_strategy_eligible_date"] != audit["julia_strategy_eligible_date"]).any():
        structural_errors.append("STRATEGY_ELIGIBILITY_DATE_PARITY_MISMATCH")

    coverage_rows = []
    for window_id in EXPECTED_WINDOWS:
        part = audit.loc[audit["window_id"] == window_id]
        counts = part["coverage_status"].value_counts().to_dict()
        coverage_rows.append({
            "window_id": window_id, "universe_count": len(part),
            "full_window_count": int(counts.get("FULL_WINDOW", 0)),
            "partial_window_count": int(counts.get("PARTIAL_WINDOW", 0)),
            "not_evaluable_count": int(counts.get("NOT_EVALUABLE", 0)),
        })
        if len(part) != 36 or sum(counts.get(key, 0) for key in ("FULL_WINDOW", "PARTIAL_WINDOW", "NOT_EVALUABLE")) != 36:
            structural_errors.append(f"COVERAGE_COUNT_MISMATCH:{window_id}")
    no_trade_rows = [row for row in readiness if int(row.get("nontrading_zero_ohlc_row_count", 0) or 0) > 0]
    raw_data_quality = {
        "no_trade_zero_ohlc_ticker_count": len(no_trade_rows),
        "no_trade_zero_ohlc_row_count": sum(int(row["nontrading_zero_ohlc_row_count"]) for row in no_trade_rows),
        "no_trade_zero_ohlc_tickers": [row["ticker"] for row in no_trade_rows],
        "raw_session_gap_ticker_count": sum(
            any(error.startswith("RAW_KRX_SESSION_GAPS") for error in row.get("errors", []))
            for row in readiness
        ),
    }
    data_meta = {
        key: value for key, value in data_info.items()
        if not key.endswith("_internal") and key not in {
            "cutoff_raw_tickers_not_in_current_universe",
            "cutoff_raw_tickers_not_in_current_universe_count",
        }
    }
    return {
        "verdict": "SPAN_PREFLIGHT_PASS" if not structural_errors else "CHECK_REQUIRED",
        "preflight_passed": not structural_errors,
        "backtest_started": False,
        "start_git_head": "4f3afe29dd80dd282bc482709768c4a84fa58538",
        "worker_count_requested": WORKERS, "worker_count_actual": WORKERS,
        "universe": {
            "selected_count": len(universe), "removed_ticker": "474800",
            "removed_ticker_present": "474800" in {row["ticker"] for row in universe},
            "removed_ticker_absent": "474800" not in {row["ticker"] for row in universe},
            "exact_v04_minus_474800_match": set(row["ticker"] for row in universe) == EXPECTED_TICKERS,
            "category_counts": universe_meta["category_counts"],
            "taxable_count": universe_meta["taxable_count"],
            "non_taxable_count": universe_meta["non_taxable_count"],
            "krx_tax_metadata_mismatches": universe_meta["tax_metadata_mismatch_tickers"],
            "market_refetch_count": 0, "forty_day_recomputation_count": 0,
            "tax_pnl_application_count": 0,
        },
        "source_authority": universe_meta,
        "windows": list(_WINDOWS.values()), "coverage_by_window": coverage_rows,
        "raw_data_quality": raw_data_quality,
        "raw_data_source": data_meta,
        "span_validation": {
            "audit_rows": len(audit), "expected_pairs": 180,
            "v2_julia_eligible_date_parity": not (audit["v2_strategy_eligible_date"] != audit["julia_strategy_eligible_date"]).any(),
            "not_evaluable_reason_missing_count": int(audit.loc[audit["coverage_status"] == "NOT_EVALUABLE", "reason_if_not_evaluable"].fillna("").eq("").sum()),
        },
        "structural_errors": structural_errors,
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _write_universe(path: Path, universe: list[dict[str, Any]]) -> None:
    pd.DataFrame(universe).sort_values("ticker", kind="mergesort").to_csv(path, index=False, encoding="utf-8")


def _preflight_summary(audit: pd.DataFrame, validation: Mapping[str, Any]) -> str:
    lines = [
        "# ETF-36 A FAST Core V2 vs Julia V00: 5-window 단순 비교",
        "",
        f"**상태:** `{validation['verdict']}` — 사전 span 점검 결과이며 백테스트는 아직 실행되지 않았어.",
        "",
        "## 동결 Universe",
        "",
        "V04 universe에서 `474800` 한 종목만 제외한 36개야. 시장 재조회·40D 재계산·세금 PnL 반영은 모두 0회야.",
        "",
        "## Effective span 사전 점검",
        "",
        "| Window | Universe | FULL | PARTIAL | NOT_EVALUABLE |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in validation["coverage_by_window"]:
        lines.append(f"| {row['window_id']} | {row['universe_count']} | {row['full_window_count']} | {row['partial_window_count']} | {row['not_evaluable_count']} |")
    lines += ["", "`comparison_effective_start = max(window_start, V2_ready_date, Julia_ready_date)`. V2와 Julia는 기존 공통 A FAST 입력의 첫 정상 READY 날짜를 사용하고, 첫 거래일은 시작일 산정에 쓰지 않아.", ""]
    not_eval = audit.loc[audit["coverage_status"] == "NOT_EVALUABLE"]
    if not not_eval.empty:
        lines += ["### 평가 불가 종목", "", "| Window | Ticker | 사유 |", "|---|---|---|"]
        for row in not_eval.to_dict("records"):
            lines.append(f"| {row['window_id']} | {row['ticker']} {row['ETF_name']} | {row['reason_if_not_evaluable']} |")
        lines.append("")
    if validation["structural_errors"]:
        lines += ["## 확인 필요", ""]
        lines.extend(f"- `{error}`" for error in validation["structural_errors"])
        lines.append("")
    else:
        lines += ["사전 점검 구조 검증은 통과했어. 이 시점에는 거래 재생을 아직 시작하지 않았어.", ""]
    lines += [
        "## 계약 및 한계", "",
        "- 가격은 기존 KRX raw ETF OHLCV 스냅샷을 사용해. 신호일 다음 KRX 세션 시가 체결, 종가 cutoff, 기존 수수료·슬리피지 계약을 재사용해.",
        "- 계좌 세금은 ETF universe metadata로만 남기고 수익률에는 반영하지 않아.",
        "- 단순 trade-level replay라 initial capital, 종목별 한도, 현금제약, 포트폴리오 CAGR/MDD는 계산하지 않아.",
        "- V2와 Julia는 기존 구현만 호출해. 세 번째 전략이나 threshold sweep은 없어.",
        "",
    ]
    return "\n".join(lines)


def run_preflight(output_dir: Path) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    universe, universe_meta = _load_universe()
    _write_universe(output_dir / "official_etf_universe_36.csv", universe)
    score, stage = base._read_contracts()
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="etf36-span-", dir="/private/tmp") as tmp:
        db_path = Path(tmp) / "raw_etf_prices.sqlite3"
        data_info = base._build_price_database(db_path, ROOT / base.RAW_STORE_REL, universe)
        global _WINDOWS
        _WINDOWS, window_errors = _resolved_windows(data_info["calendar_dates_internal"])
        readiness = _collect_worker_results(_preflight_ticker, universe, db_path, data_info, (score, stage))
    audit = _make_span_audit(universe, readiness, _WINDOWS, data_info["calendar_dates_internal"])
    audit.to_csv(output_dir / "effective_span_audit.csv", index=False, encoding="utf-8")
    validation = _preflight_validation(universe, universe_meta, readiness, audit, data_info, window_errors)
    validation["runtime_seconds"] = round(time.perf_counter() - started, 3)
    _write_json(output_dir / "validation.json", validation)
    (output_dir / "summary.md").write_text(_preflight_summary(audit, validation), encoding="utf-8")
    print(json.dumps({
        "verdict": validation["verdict"], "coverage_by_window": validation["coverage_by_window"],
        "structural_error_count": len(validation["structural_errors"]),
        "output_dir": str(output_dir), "runtime_seconds": validation["runtime_seconds"],
    }, ensure_ascii=False))
    return 0 if validation["preflight_passed"] else 2


def _span_context_rows(audit: pd.DataFrame) -> dict[tuple[str, str], dict[str, Any]]:
    return {(str(row["window_id"]), str(row["ticker"])): row for row in audit.to_dict("records")}


def _backtest_ticker(payload: tuple[dict[str, Any], list[dict[str, Any]]]) -> dict[str, Any]:
    instrument, span_rows = payload
    ticker = _norm_ticker(instrument["ticker"])
    daily = base._load_ticker_daily(ticker)
    findings = _ticker_data_findings(daily, instrument["listing_date"])
    if findings["errors"]:
        return {"ticker": ticker, "trades": [], "errors": findings["errors"], "ready_date": None}
    daily = daily.loc[daily.index >= pd.Timestamp(instrument["listing_date"])].copy()
    context = base.build_precomputed_ticker_context(ticker, instrument["name"], daily)
    ready_date, _eval_count = base._find_fast_ready_date(
        ticker, instrument["name"], daily, context, instrument["listing_date"]
    )
    errors: list[str] = []
    trades: list[dict[str, Any]] = []
    for span in span_rows:
        if ready_date != span["v2_strategy_eligible_date"] or ready_date != span["julia_strategy_eligible_date"]:
            errors.append(f"READINESS_CHANGED_SINCE_PREFLIGHT:{span['window_id']}")
            continue
        if span["coverage_status"] == "NOT_EVALUABLE":
            continue
        window = _WINDOWS[span["window_id"]]
        cutoff = pd.Timestamp(window["window_end"])
        support = pd.Timestamp(window["execution_support_date"])
        base.CUTOFF, base.EXECUTION_SUPPORT = cutoff, support
        common_start = span["comparison_effective_start"]
        eligible_dates, eligibility_metrics, _volume_ready, _eligibility_audit = base._raw_eligibility(
            daily, instrument["listing_date"], common_start
        )
        base._WORKER["eligibility_metrics"] = eligibility_metrics
        try:
            v2_records = base.simulate_ticker_core_v02_reentry(
                ticker=ticker, name=instrument["name"], market="ETF", daily=daily,
                score_contract=base._WORKER["score_contract"], stage_contract=base._WORKER["stage_contract"],
                cutoff_date=cutoff, snapshot_context=context, market_calendar=base._WORKER["calendar"],
                entry_search_start=pd.Timestamp(common_start), signal_cutoff_date=cutoff,
                execution_support_date=support, strict_errors=True,
                entry_execution_cutoff_date=cutoff, entry_signal_cutoff_date=cutoff,
                entry_signal_filter=lambda signal_date, _result: signal_date.strftime("%Y-%m-%d") in eligible_dates,
            )
            normalized_v2 = [
                base._normalize_strategy_trade(record, base.STRATEGY_A_FAST, ticker, instrument["name"],
                                               instrument["ISU_CD"], daily, common_start)
                for record in v2_records
            ]
            trades.extend(_enrich_trades(normalized_v2, instrument, span, window))
        except Exception as exc:
            errors.append(f"AFAST_REPLAY_ERROR:{span['window_id']}:{type(exc).__name__}:{str(exc)[:320]}")
        try:
            support_errors: list[str] = []
            julia_records = base._run_julia(
                ticker, instrument["name"], daily, context, common_start, eligible_dates, support_errors,
            )
            if support_errors:
                errors.extend(f"JULIA_EVALUATOR_ERROR:{span['window_id']}:{item}" for item in support_errors)
            normalized_julia = [
                base._normalize_strategy_trade(record, base.STRATEGY_JULIA, ticker, instrument["name"],
                                               instrument["ISU_CD"], daily, common_start)
                for record in julia_records
            ]
            trades.extend(_enrich_trades(normalized_julia, instrument, span, window))
        except Exception as exc:
            errors.append(f"JULIA_REPLAY_ERROR:{span['window_id']}:{type(exc).__name__}:{str(exc)[:320]}")
    return {"ticker": ticker, "trades": trades, "errors": errors, "ready_date": ready_date}


def _enrich_trades(
    trades: list[dict[str, Any]], instrument: Mapping[str, Any], span: Mapping[str, Any], window: Mapping[str, str]
) -> list[dict[str, Any]]:
    result = []
    for trade in trades:
        row = {
            **trade,
            "trade_identity": "|".join((trade["strategy_id"], span["window_id"], trade["ticker"], trade["signal_date"], trade["entry_execution_date"])),
            "strategy_label": "A FAST Core V2" if trade["strategy_id"] == base.STRATEGY_A_FAST else "Julia V00",
            "window_id": span["window_id"], "major_category": instrument["major_category"],
            "representative_group": instrument["representative_group"],
            "comparison_effective_start": span["comparison_effective_start"],
            "comparison_effective_end": span["comparison_effective_end"],
            "general_account_trading_gain_tax": instrument["general_account_trading_gain_tax"],
            "KRX_TAX_TP_CD": instrument["KRX_TAX_TP_CD"], "tax_applied_to_backtest_pnl": False,
            "execution_support_date": window["execution_support_date"],
        }
        result.append(row)
    return result


def _metric(values: Iterable[Any]) -> tuple[float | None, float | None]:
    series = pd.to_numeric(pd.Series(list(values), dtype="object"), errors="coerce").dropna()
    series = series[np.isfinite(series)]
    if series.empty:
        return None, None
    return float(series.mean()), float(series.median())


def _strategy_metrics(trades: pd.DataFrame, strategy_id: str) -> dict[str, Any]:
    part = trades.loc[trades["strategy_id"] == strategy_id] if not trades.empty else pd.DataFrame()
    returns = pd.to_numeric(part.get("commission_slippage_pre_tax_return_pct", pd.Series(dtype=float)), errors="coerce")
    realized = returns.loc[part.get("trade_status", pd.Series(dtype=str)).eq("REALIZED")] if not part.empty else pd.Series(dtype=float)
    holding = pd.to_numeric(part.get("holding_krx_sessions_inclusive", pd.Series(dtype=float)), errors="coerce")
    finite_returns = returns[np.isfinite(returns)]
    finite_realized = realized[np.isfinite(realized)]
    finite_holding = holding[np.isfinite(holding)]
    count = int(len(part))
    positive = int((finite_returns > 0).sum())
    return {
        "trade_count": count,
        "closed_trade_count": int(part.get("trade_status", pd.Series(dtype=str)).eq("REALIZED").sum()),
        "terminal_open_count": int(part.get("trade_status", pd.Series(dtype=str)).eq("OPEN_AT_CUTOFF").sum()),
        "positive_trade_count": positive,
        "win_rate_pct": (positive / count * 100) if count else None,
        "closed_positive_trade_count": int((finite_realized > 0).sum()),
        "closed_win_rate_pct": (float((finite_realized > 0).mean() * 100) if len(finite_realized) else None),
        "mean_terminal_mark_return_pct": float(finite_returns.mean()) if len(finite_returns) else None,
        "median_terminal_mark_return_pct": float(finite_returns.median()) if len(finite_returns) else None,
        "mean_realized_return_pct": float(finite_realized.mean()) if len(finite_realized) else None,
        "median_realized_return_pct": float(finite_realized.median()) if len(finite_realized) else None,
        "ge_50pct_count": int((finite_returns >= 50).sum()),
        "ge_100pct_count": int((finite_returns >= 100).sum()),
        "le_minus_15pct_count": int((finite_returns <= -15).sum()),
        "le_minus_30pct_count": int((finite_returns <= -30).sum()),
        "le_minus_40pct_count": int((finite_returns <= -40).sum()),
        "mean_holding_sessions": float(finite_holding.mean()) if len(finite_holding) else None,
        "median_holding_sessions": float(finite_holding.median()) if len(finite_holding) else None,
    }


def _build_summary(audit: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    categories = ["OVERALL", *EXPECTED_CATEGORY_COUNTS]
    rows = []
    for window_id in EXPECTED_WINDOWS:
        window_spans = audit.loc[audit["window_id"] == window_id]
        window_trades = trades.loc[trades["window_id"] == window_id] if not trades.empty else pd.DataFrame()
        for category in categories:
            scope_spans = window_spans if category == "OVERALL" else window_spans.loc[window_spans["major_category"] == category]
            scope_trades = window_trades if category == "OVERALL" or window_trades.empty else window_trades.loc[window_trades["major_category"] == category]
            evaluable_tickers = set(scope_spans.loc[scope_spans["coverage_status"].isin(["FULL_WINDOW", "PARTIAL_WINDOW"]), "ticker"])
            row: dict[str, Any] = {
                "window_id": window_id, "scope": category, "universe_etf_count": len(scope_spans),
                "full_window_etf_count": int(scope_spans["coverage_status"].eq("FULL_WINDOW").sum()),
                "partial_window_etf_count": int(scope_spans["coverage_status"].eq("PARTIAL_WINDOW").sum()),
                "not_evaluable_etf_count": int(scope_spans["coverage_status"].eq("NOT_EVALUABLE").sum()),
                "evaluated_etf_count": len(evaluable_tickers),
            }
            for strategy_id, prefix in ((base.STRATEGY_A_FAST, "afast_v2"), (base.STRATEGY_JULIA, "julia_v00")):
                metrics = _strategy_metrics(scope_trades, strategy_id)
                row.update({f"{prefix}_{key}": value for key, value in metrics.items()})
            for metric in ("win_rate_pct", "closed_win_rate_pct", "mean_terminal_mark_return_pct", "median_terminal_mark_return_pct",
                           "mean_realized_return_pct", "median_realized_return_pct", "mean_holding_sessions", "median_holding_sessions"):
                left, right = row[f"afast_v2_{metric}"], row[f"julia_v00_{metric}"]
                row[f"delta_julia_minus_v2_{metric}"] = (right - left) if left is not None and right is not None else None

            ticker_mean_diffs = []
            for ticker in sorted(evaluable_tickers):
                cell = window_trades.loc[window_trades["ticker"] == ticker] if not window_trades.empty else pd.DataFrame()
                if category != "OVERALL" and not cell.empty:
                    cell = cell.loc[cell["major_category"] == category]
                per_strategy = {}
                for strategy_id in (base.STRATEGY_A_FAST, base.STRATEGY_JULIA):
                    values = pd.to_numeric(cell.loc[cell.get("strategy_id", pd.Series(dtype=str)) == strategy_id, "commission_slippage_pre_tax_return_pct"], errors="coerce") if not cell.empty else pd.Series(dtype=float)
                    per_strategy[strategy_id] = float(values.mean()) if len(values.dropna()) else None
                if per_strategy[base.STRATEGY_A_FAST] is not None and per_strategy[base.STRATEGY_JULIA] is not None:
                    ticker_mean_diffs.append(per_strategy[base.STRATEGY_JULIA] - per_strategy[base.STRATEGY_A_FAST])
            row["paired_etf_window_count"] = len(ticker_mean_diffs)
            row["mean_paired_julia_minus_v2_etf_window_return_pp"] = float(np.mean(ticker_mean_diffs)) if ticker_mean_diffs else None
            rows.append(row)
    return pd.DataFrame(rows)


def _validate_backtest(audit: pd.DataFrame, trades: pd.DataFrame, summary: pd.DataFrame, worker_errors: list[str]) -> dict[str, Any]:
    errors = list(worker_errors)
    if len(summary) != 20 or summary.duplicated(["window_id", "scope"]).any():
        errors.append("SUMMARY_ROW_COUNT_OR_DUPLICATE_MISMATCH")
    expected_scopes = {(window, scope) for window in EXPECTED_WINDOWS for scope in ["OVERALL", *EXPECTED_CATEGORY_COUNTS]}
    if set(zip(summary.get("window_id", []), summary.get("scope", []))) != expected_scopes:
        errors.append("SUMMARY_WINDOW_SCOPE_SET_MISMATCH")
    if not trades.empty:
        realized = trades["trade_status"].eq("REALIZED")
        if trades["trade_identity"].duplicated().any():
            errors.append("DUPLICATE_TRADE_IDENTITY")
        if (pd.to_datetime(trades["signal_date"]) < pd.to_datetime(trades["comparison_effective_start"])).any():
            errors.append("ENTRY_SIGNAL_BEFORE_COMPARISON_START")
        if (pd.to_datetime(trades["entry_execution_date"]) > pd.to_datetime(trades["cutoff_date"])).any():
            errors.append("NEW_ENTRY_AFTER_CUTOFF")
        exits = trades["exit_execution_date"].dropna()
        supports = trades.loc[trades["exit_execution_date"].notna(), "execution_support_date"]
        if len(exits) and (pd.to_datetime(exits).reset_index(drop=True) > pd.to_datetime(supports).reset_index(drop=True)).any():
            errors.append("EXIT_AFTER_EXECUTION_SUPPORT")
        mandatory_numeric = [
            "entry_price_raw_open", "terminal_price_raw", "gross_return_pct",
            "commission_slippage_pre_tax_return_pct", "commission_rate_each_side",
            "slippage_rate_each_side", "ETF_sell_tax_rate", "holding_krx_sessions_inclusive",
        ]
        mandatory_values = trades[mandatory_numeric].to_numpy(dtype=float)
        nonfinite_mandatory_count = int((~np.isfinite(mandatory_values)).sum())
        realized_exit_values = pd.to_numeric(trades.loc[realized, "exit_price_raw_open"], errors="coerce").to_numpy(dtype=float)
        nonfinite_realized_exit_count = int((~np.isfinite(realized_exit_values)).sum())
        if nonfinite_mandatory_count or nonfinite_realized_exit_count:
            errors.append("NONFINITE_TRADE_METRIC")
        if not trades["tax_applied_to_backtest_pnl"].eq(False).all() or not trades["ETF_sell_tax_rate"].eq(0.0).all():
            errors.append("TAX_CHANGED_BACKTEST_PNL")
        statuses = set(trades["trade_status"])
        if not statuses.issubset({"REALIZED", "OPEN_AT_CUTOFF"}):
            errors.append("UNEXPECTED_TRADE_STATUS")
        realized = trades["trade_status"].eq("REALIZED")
        if trades.loc[realized, ["exit_signal_date", "exit_execution_date", "exit_price_raw_open"]].isna().any().any():
            errors.append("REALIZED_EXIT_FIELDS_MISSING")
        opens = ~realized
        if trades.loc[opens, "exit_execution_date"].notna().any() or trades.loc[opens, "exit_price_raw_open"].notna().any():
            errors.append("OPEN_TRADE_HAS_REALIZED_EXIT_FIELDS")

    # Independent ledger-to-summary reconciliation with 0.1 percentage-point tolerance.
    for row in summary.to_dict("records"):
        part = trades.loc[trades["window_id"] == row["window_id"]] if not trades.empty else pd.DataFrame()
        if row["scope"] != "OVERALL" and not part.empty:
            part = part.loc[part["major_category"] == row["scope"]]
        for strategy_id, prefix in ((base.STRATEGY_A_FAST, "afast_v2"), (base.STRATEGY_JULIA, "julia_v00")):
            expected = _strategy_metrics(part, strategy_id)
            for key in ("trade_count", "closed_trade_count", "terminal_open_count", "positive_trade_count", "ge_50pct_count", "ge_100pct_count", "le_minus_15pct_count", "le_minus_30pct_count", "le_minus_40pct_count"):
                if int(row[f"{prefix}_{key}"]) != int(expected[key]):
                    errors.append(f"SUMMARY_COUNT_RECONCILIATION:{row['window_id']}:{row['scope']}:{prefix}:{key}")
            for key in ("win_rate_pct", "mean_realized_return_pct", "median_realized_return_pct", "mean_holding_sessions", "median_holding_sessions"):
                actual, wanted = row[f"{prefix}_{key}"], expected[key]
                if pd.isna(actual) and wanted is None:
                    continue
                if actual is None or wanted is None or not math.isclose(float(actual), float(wanted), rel_tol=0, abs_tol=0.1):
                    errors.append(f"SUMMARY_FLOAT_RECONCILIATION:{row['window_id']}:{row['scope']}:{prefix}:{key}")
    return {
        "passed": not errors,
        "errors": errors,
        "checks": {
            "span_pairs": len(audit) == 180,
            "strategy_start_end_parity": bool((audit["v2_strategy_eligible_date"] == audit["julia_strategy_eligible_date"]).all()),
            "entry_before_comparison_start_count": int((pd.to_datetime(trades["signal_date"]) < pd.to_datetime(trades["comparison_effective_start"])).sum()) if not trades.empty else 0,
            "post_cutoff_entry_count": int((pd.to_datetime(trades["entry_execution_date"]) > pd.to_datetime(trades["cutoff_date"])).sum()) if not trades.empty else 0,
            "not_evaluable_reason_missing_count": int(audit["reason_if_not_evaluable"].isna().sum()),
            "unexpected_nan_or_inf_count": 0 if trades.empty else nonfinite_mandatory_count + nonfinite_realized_exit_count,
            "expected_open_trade_missing_exit_price_count": 0 if trades.empty else int((trades["trade_status"].eq("OPEN_AT_CUTOFF") & trades["exit_price_raw_open"].isna()).sum()),
            "duplicate_trade_identity_count": 0 if trades.empty else int(trades["trade_identity"].duplicated().sum()),
            "aggregate_float_tolerance_pp": 0.1,
            "tax_pnl_application_count": 0,
        },
    }


def _final_summary(audit: pd.DataFrame, summary: pd.DataFrame, validation: Mapping[str, Any], git_head: str | None) -> str:
    lines = [
        "# ETF-36 A FAST Core V2 vs Julia V00: 5-window 단순 비교", "",
        f"**Verdict:** `{validation['verdict']}`", "",
        "## Universe 및 coverage", "",
        "V04 공식 37개에서 `474800 KIWOOM 미국원유에너지기업`만 제거했고, 나머지 36개 ticker 집합을 동결했어. 분류는 MARKET_INDEX 12, SECTOR_INDEX 19, COMMODITY_RESOURCE 5야.",
        "일반계좌 매매차익 과세 표시는 KRX V02 product master `TAX_TP_CD`와 일치하는 metadata로만 보관했어(15 taxable / 21 domestic stock ETF non-taxable). 백테스트 PnL에는 추가 세금을 적용하지 않았어.", "",
        "| Window | Universe | FULL | PARTIAL | NOT_EVALUABLE |", "|---|---:|---:|---:|---:|",
    ]
    for window_id in EXPECTED_WINDOWS:
        part = audit.loc[audit["window_id"] == window_id]
        counts = part["coverage_status"].value_counts().to_dict()
        lines.append(f"| {window_id} | {len(part)} | {counts.get('FULL_WINDOW', 0)} | {counts.get('PARTIAL_WINDOW', 0)} | {counts.get('NOT_EVALUABLE', 0)} |")
    not_eval = audit.loc[audit["coverage_status"] == "NOT_EVALUABLE"]
    if not not_eval.empty:
        lines += ["", "평가 불가 종목:", ""]
        lines.extend(f"- {row.window_id} / {row.ticker} {row.ETF_name}: {row.reason_if_not_evaluable}" for row in not_eval.itertuples())
    lines += ["", "## 5-window OVERALL 비교", "", "수익률은 거래별 수수료·슬리피지 차감 후, 세금 차감 전이야. win rate와 임계수익 건수는 cutoff 종가 평가(open trade 포함), 평균·중앙 realized return은 종료 체결된 거래만 사용해.", "",
              "| Window | 전략 | ETF | Trades | Closed / Open | Win % | 평균·중앙 realized % | +50 / +100 | ≤−15 / −30 / −40 | 평균 보유 세션 |",
              "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for window_id in EXPECTED_WINDOWS:
        for prefix, label in (("afast_v2", "A FAST Core V2"), ("julia_v00", "Julia V00")):
            row = summary.loc[(summary["window_id"] == window_id) & (summary["scope"] == "OVERALL")].iloc[0]
            mean = row[f"{prefix}_mean_realized_return_pct"]
            median = row[f"{prefix}_median_realized_return_pct"]
            mean_median = "—" if pd.isna(mean) or pd.isna(median) else f"{mean:.2f} / {median:.2f}"
            lines.append(
                f"| {window_id} | {label} | {row['evaluated_etf_count']} | {row[f'{prefix}_trade_count']} | {row[f'{prefix}_closed_trade_count']} / {row[f'{prefix}_terminal_open_count']} | "
                f"{(row[f'{prefix}_win_rate_pct'] if pd.notna(row[f'{prefix}_win_rate_pct']) else float('nan')):.2f} | {mean_median} | "
                f"{row[f'{prefix}_ge_50pct_count']} / {row[f'{prefix}_ge_100pct_count']} | {row[f'{prefix}_le_minus_15pct_count']} / {row[f'{prefix}_le_minus_30pct_count']} / {row[f'{prefix}_le_minus_40pct_count']} | "
                f"{(row[f'{prefix}_mean_holding_sessions'] if pd.notna(row[f'{prefix}_mean_holding_sessions']) else float('nan')):.1f}"
                " |"
            )
    lines += ["", "## 카테고리 비교", "", "| Window | Category | 평가 ETF | V2/Julia 거래 수 | V2/Julia win rate % | V2/Julia median realized % | paired ETF-window | 평균 paired 차이 pp |", "|---|---|---:|---:|---:|---:|---:|---:|"]
    for window_id in EXPECTED_WINDOWS:
        for category in EXPECTED_CATEGORY_COUNTS:
            row = summary.loc[(summary["window_id"] == window_id) & (summary["scope"] == category)].iloc[0]
            w2, wj = row["afast_v2_win_rate_pct"], row["julia_v00_win_rate_pct"]
            m2, mj = row["afast_v2_median_realized_return_pct"], row["julia_v00_median_realized_return_pct"]
            fmt = lambda a, b: "—" if pd.isna(a) or pd.isna(b) else f"{a:.2f} / {b:.2f}"
            paired = row["mean_paired_julia_minus_v2_etf_window_return_pp"]
            lines.append(f"| {window_id} | {category} | {row['evaluated_etf_count']} | {row['afast_v2_trade_count']} / {row['julia_v00_trade_count']} | {fmt(w2, wj)} | {fmt(m2, mj)} | {row['paired_etf_window_count']} | {'—' if pd.isna(paired) else f'{paired:.2f}'} |")
    lines += ["", "## 반복 특성 읽기", ""]
    overall = summary.loc[summary["scope"] == "OVERALL"].set_index("window_id")
    comparisons = {
        "positive rate": sum(overall.loc[w, "julia_v00_win_rate_pct"] > overall.loc[w, "afast_v2_win_rate_pct"] for w in EXPECTED_WINDOWS if pd.notna(overall.loc[w, "julia_v00_win_rate_pct"]) and pd.notna(overall.loc[w, "afast_v2_win_rate_pct"])),
        "median realized return": sum(overall.loc[w, "julia_v00_median_realized_return_pct"] > overall.loc[w, "afast_v2_median_realized_return_pct"] for w in EXPECTED_WINDOWS if pd.notna(overall.loc[w, "julia_v00_median_realized_return_pct"]) and pd.notna(overall.loc[w, "afast_v2_median_realized_return_pct"])),
        "mean holding sessions": sum(overall.loc[w, "julia_v00_mean_holding_sessions"] > overall.loc[w, "afast_v2_mean_holding_sessions"] for w in EXPECTED_WINDOWS if pd.notna(overall.loc[w, "julia_v00_mean_holding_sessions"]) and pd.notna(overall.loc[w, "afast_v2_mean_holding_sessions"])),
    }
    lines.append(f"Julia가 V2보다 높은 window 수(최대 5개): win rate {comparisons['positive rate']}, median realized return {comparisons['median realized return']}, 평균 보유 세션 {comparisons['mean holding sessions']}.")
    lines.append("이 수치는 공식 ETF-36 단순 trade-level 비교의 특성 요약이야. 현실적 포트폴리오 테스트 전 최종 전략 채택 판정으로 해석하지 않아.")
    lines += ["", "## 실행 조건 / 검증", "", "- 기존 KRX raw ETF OHLCV를 재사용했고 시장 재조회 0회, 40D 재계산 0회.", "- 독립 ticker/window replay, worker 10개. 시작일 이후 신호만 허용, window cutoff 이후 신규 진입 금지, 기존 execution support만 exit 체결에 허용.", "- Portfolio/cash/capital/MDD 분석, 세금 PnL 계산, threshold sweep은 수행하지 않았어.", f"- 결과 검증: {'PASS' if validation['backtest']['validation']['passed'] else 'CHECK_REQUIRED'}; 오류 {len(validation['backtest']['validation']['errors'])}건.", "- commit/push 세부 결과는 `r.md`와 작업 완료 응답에 기록해.", ""]
    raw_quality = validation.get("raw_data_quality", {})
    runtime_diagnostics = validation.get("runtime_diagnostics", {})
    if raw_quality or runtime_diagnostics:
        lines += ["## 원시 무거래 행과 기존 계산 경고", ""]
        if raw_quality:
            lines.append(
                f"KRX raw에는 거래량 0, 종가 양수, 시가·고가·저가 0인 무거래 sentinel이 "
                f"{raw_quality.get('no_trade_zero_ohlc_row_count', 0)}개({raw_quality.get('no_trade_zero_ohlc_ticker_count', 0)} ETF)에 있었어. "
                "원시 데이터 계약대로 값을 보존했고 별도 보정은 하지 않았어."
            )
        warning_counts = runtime_diagnostics.get("warning_counts", {})
        if warning_counts:
            lines.append(
                "기존 feature 계산 중 divide-by-zero/invalid runtime warning이 "
                f"monthly {warning_counts.get('monthly_distance_from_low', 0)}, "
                f"weekly {warning_counts.get('weekly_distance_from_low', 0)}, "
                f"pivot {warning_counts.get('pivot_invalid_division', 0)}회 관측됐어. "
                "전략 로직은 바꾸지 않았고 거래 ledger의 필수 수치에는 NaN/Inf가 없어."
            )
        lines.append("이 현상은 특히 가장 이른 history 구간 해석의 한계야. 포트폴리오 단계 전 기존 feature 처리를 별도 검토해야 해.")
        lines.append("")
    if validation["backtest"]["validation"]["errors"]:
        lines += ["### 검증 오류", ""]
        lines.extend(f"- `{error}`" for error in validation["backtest"]["validation"]["errors"])
        lines.append("")
    return "\n".join(lines)


def run_backtest(output_dir: Path) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    preflight_path = output_dir / "validation.json"
    audit_path = output_dir / "effective_span_audit.csv"
    if not preflight_path.exists() or not audit_path.exists():
        raise RuntimeError("SPAN_PREFLIGHT_REQUIRED_BEFORE_BACKTEST")
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    if not preflight.get("preflight_passed") or preflight.get("verdict") != "SPAN_PREFLIGHT_PASS":
        raise RuntimeError("BACKTEST_BLOCKED_BY_SPAN_PREFLIGHT")
    audit = pd.read_csv(audit_path, dtype={"ticker": "string"}, keep_default_na=False)
    audit["ticker"] = audit["ticker"].map(_norm_ticker)
    universe, universe_meta = _load_universe()
    if universe_meta["errors"]:
        raise RuntimeError(f"UNIVERSE_REVALIDATION_FAILED:{universe_meta['errors']}")
    score, stage = base._read_contracts()
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="etf36-backtest-", dir="/private/tmp") as tmp:
        db_path = Path(tmp) / "raw_etf_prices.sqlite3"
        data_info = base._build_price_database(db_path, ROOT / base.RAW_STORE_REL, universe)
        if data_info["source_store_manifest_sha256"] != preflight["raw_data_source"]["source_store_manifest_sha256"]:
            raise RuntimeError("RAW_STORE_MANIFEST_CHANGED_AFTER_PREFLIGHT")
        global _WINDOWS
        _WINDOWS, window_errors = _resolved_windows(data_info["calendar_dates_internal"])
        if window_errors:
            raise RuntimeError(f"WINDOW_CHANGED_AFTER_PREFLIGHT:{window_errors}")
        span_map = _span_context_rows(audit)
        payloads = []
        for instrument in universe:
            spans = [span_map[(window, instrument["ticker"])] for window in EXPECTED_WINDOWS]
            payloads.append((instrument, spans))
        # The worker accepts one instrument directly, so bind its five frozen audit rows.
        def _task(payload: tuple[dict[str, Any], list[dict[str, Any]]]) -> dict[str, Any]:
            return _backtest_ticker(payload)
        results: list[dict[str, Any]] = []
        with ProcessPoolExecutor(
            max_workers=WORKERS, initializer=_worker_init,
            initargs=(str(db_path), score, stage, data_info["calendar_dates_internal"], data_info["month_ends_internal"]),
        ) as pool:
            future_map = {pool.submit(_backtest_ticker, payload): payload[0]["ticker"] for payload in payloads}
            for done, future in enumerate(as_completed(future_map), start=1):
                ticker = future_map[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    results.append({"ticker": ticker, "trades": [], "errors": [f"WORKER_ERROR:{type(exc).__name__}:{str(exc)[:320]}"]})
                if done % 3 == 0 or done == len(payloads):
                    print(f"ETF-36 replay progress {done}/{len(payloads)}", flush=True)
    worker_errors = [f"{result['ticker']}:{error}" for result in results for error in result.get("errors", [])]
    trade_rows = [trade for result in results for trade in result.get("trades", [])]
    trades = pd.DataFrame(trade_rows)
    if not trades.empty:
        trades = trades.sort_values(["window_id", "strategy_id", "signal_date", "ticker", "entry_execution_date"], kind="mergesort")
    trades.to_csv(output_dir / "trade_ledger.csv", index=False, encoding="utf-8")
    summary = _build_summary(audit, trades)
    summary.to_csv(output_dir / "window_comparison_summary.csv", index=False, encoding="utf-8")
    backtest_validation = _validate_backtest(audit, trades, summary, worker_errors)
    preflight["backtest_started"] = True
    preflight["backtest_runtime_seconds"] = round(time.perf_counter() - started, 3)
    preflight["backtest"] = {
        "strategy_ids": [base.STRATEGY_A_FAST, base.STRATEGY_JULIA],
        "worker_count_requested": WORKERS, "worker_count_actual": WORKERS,
        "trade_count": len(trades), "worker_errors": worker_errors,
        "validation": backtest_validation,
    }
    preflight["verdict"] = (
        "ETF_36_AFAST_V2_VS_JULIA_5WINDOW_SIMPLE_BACKTEST_COMPLETE"
        if backtest_validation["passed"] else "CHECK_REQUIRED"
    )
    _write_json(preflight_path, preflight)
    (output_dir / "summary.md").write_text(_final_summary(audit, summary, preflight, None), encoding="utf-8")
    print(json.dumps({
        "verdict": preflight["verdict"], "trade_count": len(trades),
        "validation_passed": backtest_validation["passed"], "validation_errors": len(backtest_validation["errors"]),
        "output_dir": str(output_dir), "runtime_seconds": preflight["backtest_runtime_seconds"],
    }, ensure_ascii=False))
    return 0 if backtest_validation["passed"] else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--span-preflight", action="store_true", help="Build universe and effective-span audit only.")
    mode.add_argument("--backtest", action="store_true", help="Run only after a passing span preflight.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / OUTPUT_REL)
    args = parser.parse_args()
    if args.span_preflight:
        return run_preflight(args.output_dir)
    return run_backtest(args.output_dir)


if __name__ == "__main__":
    raise SystemExit(main())
