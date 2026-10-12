#!/usr/bin/env python3
"""Seal P1 dates, PIT exclusions, bounded Repository V2 input and sample list."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data.market_calendar import load_rolling_production_market_calendar
from trend_scanner.data.repository_v2 import _session_projection_evidence
from trend_scanner.data.repository_v2_loader import build_repository_v2
from trend_scanner.data.rolling_market_data_refresh import load_rolling_authority, validate_merged_authority_coherence
from trend_scanner.universe.permanent_identity_exclusions import PERMANENT_IDENTITY_EXCLUSIONS

TASK_ID = "FAST_CORE_V2_ALIGNMENT_500B_P1_OFFICIAL_REALISTIC_184_V01"
CALENDAR_START = pd.Timestamp("2014-01-01")
EVAL_START = pd.Timestamp("2014-01-02")
CUTOFF = pd.Timestamp("2026-08-31")
SUPPORT = pd.Timestamp("2026-09-01")
WARMUP_START = pd.Timestamp("2009-01-01")
WORKERS = 10
PRICE_DIR = ROOT / "data/market/adjusted/stocks"
ROLLING = ROOT / "data/market/rolling_authority"
RAW_DIR = ROOT / "data/market/raw/krx_stocks/v01"
EXPECTED_EXCLUSION_HASH = "5d3bd9a1e27e7e558235f0fba211263cdc90eb0b477978c8338eb019b1a6ec2e"
TARGET_380440 = ("380440", "KR7380440008")
P31 = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01"
P3117 = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_117_price_nav_closure_v01"
P32DATA = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_data_nav_closure_v01"
P32READJ = ROOT / "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_gate_readjudication_v01"

REFERENCE_PATHS = [
    "docs/validation/backtest_common_rules.md",
    "docs/validation/official_strategy_adoption_criteria.md",
    "docs/strategies/strategy_lifecycle.md",
    "docs/patterns/pattern_a_fast/strategy/version_02/README.md",
    "docs/patterns/pattern_a_fast/strategy/version_02/OFFICIAL_ADOPTION_REVALIDATION_PLAN_V02.md",
    "src/trend_scanner/universe/permanent_identity_exclusions.py",
    "src/trend_scanner/validation/pattern_a_fast_core_v02_reentry.py",
    "scripts/run_v2_official_adoption_revalidation_v02.py",
    "scripts/run_fastcore_neg40_weak_protect_p2_1.py",
    "src/trend_scanner/data/repository_v2.py",
    "src/trend_scanner/data/repository_v2_loader.py",
    "src/trend_scanner/data/repository_v2_session_authority.py",
    "src/trend_scanner/data/market_calendar.py",
    "src/trend_scanner/data/rolling_market_data_refresh.py",
    "src/trend_scanner/data/krx_raw_stock_store.py",
    "src/trend_scanner/backtest/snapshot_context.py",
    "src/trend_scanner/patterns/pattern_a_stage.py",
    "src/trend_scanner/validation/feature_report.py",
    "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json",
    "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01/plan.md",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01/execution_contract.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01/run_official_realistic_replay.py",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01/seal_preflight.py",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01/report.md",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_117_price_nav_closure_v01/run_targeted_evaluation.py",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_117_price_nav_closure_v01/run_portfolio_replay.py",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_117_price_nav_closure_v01/report.md",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_data_nav_closure_v01/report.md",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_data_nav_closure_v01/price_input_124_audit.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_data_nav_closure_v01/integrity_validation.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_data_nav_closure_v01/corporate_action_audit.md",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_gate_readjudication_v01/report.md",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_gate_readjudication_v01/identity_policy_transition.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_gate_readjudication_v01/nav_missing_marks.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01/execution_contract.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01/source_manifest.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01/full_run_execution.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01/gate_results.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01/integrity_audit.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01/artifact_hashes.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01/control_trades.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01/candidate_trades.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01/control_portfolio_events.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01/candidate_portfolio_events.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01/control_cash_events.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01/candidate_cash_events.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01/control_daily_equity.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01/candidate_daily_equity.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01/control_missing_marks.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01/candidate_missing_marks.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_117_price_nav_closure_v01/report.md",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_117_price_nav_closure_v01/source_manifest.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_117_price_nav_closure_v01/gate_results.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_117_price_nav_closure_v01/artifact_hashes.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_117_price_nav_closure_v01/control_trades.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_117_price_nav_closure_v01/candidate_trades.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_realistic_v01/execution_contract.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_realistic_v01/source_manifest.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_realistic_v01/full_run_execution.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_realistic_v01/gate_results.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_realistic_v01/integrity_audit.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_realistic_v01/artifact_hashes.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_realistic_v01/control_trades.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_realistic_v01/candidate_trades.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_realistic_v01/control_portfolio_events.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_realistic_v01/candidate_portfolio_events.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_realistic_v01/control_cash_events.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_realistic_v01/candidate_cash_events.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_realistic_v01/control_daily_equity.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_realistic_v01/candidate_daily_equity.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_realistic_v01/control_missing_marks.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_realistic_v01/candidate_missing_marks.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_gate_readjudication_v01/report.md",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_gate_readjudication_v01/source_manifest.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_gate_readjudication_v01/gate_results.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_gate_readjudication_v01/integrity_audit.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_gate_readjudication_v01/artifact_hashes.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_exclusion_184_p3_rejudgment_p2_2_replay_v01/report.md",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_exclusion_184_p3_rejudgment_p2_2_replay_v01/execution_contract.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_exclusion_184_p3_rejudgment_p2_2_replay_v01/preflight.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_exclusion_184_p3_rejudgment_p2_2_replay_v01/source_manifest.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_exclusion_184_p3_rejudgment_p2_2_replay_v01/full_run_execution.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_exclusion_184_p3_rejudgment_p2_2_replay_v01/gate_results.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_exclusion_184_p3_rejudgment_p2_2_replay_v01/integrity_audit.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_exclusion_184_p3_rejudgment_p2_2_replay_v01/artifact_hashes.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_exclusion_184_p3_rejudgment_p2_2_replay_v01/control_trades.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_exclusion_184_p3_rejudgment_p2_2_replay_v01/candidate_trades.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_exclusion_184_p3_rejudgment_p2_2_replay_v01/control_portfolio_events.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_exclusion_184_p3_rejudgment_p2_2_replay_v01/candidate_portfolio_events.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_exclusion_184_p3_rejudgment_p2_2_replay_v01/control_cash_events.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_exclusion_184_p3_rejudgment_p2_2_replay_v01/candidate_cash_events.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_exclusion_184_p3_rejudgment_p2_2_replay_v01/control_daily_equity.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_exclusion_184_p3_rejudgment_p2_2_replay_v01/candidate_daily_equity.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_exclusion_184_p3_rejudgment_p2_2_replay_v01/control_missing_marks.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_exclusion_184_p3_rejudgment_p2_2_replay_v01/candidate_missing_marks.csv",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p2_1_official_realistic_184_v01/plan.md",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p2_1_official_realistic_184_v01/execution_contract.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p2_1_official_realistic_184_v01/source_manifest.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p2_1_official_realistic_184_v01/report.md",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p2_1_official_realistic_184_v01/gate_results.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p2_1_official_realistic_184_v01/integrity_audit.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p2_1_official_realistic_184_v01/artifact_hashes.json",
    "artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p2_1_official_realistic_184_v01/run_p2_1_replay.py",
]


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def identity_key(row: dict[str, Any]) -> tuple[str, str]:
    return str(row["ticker"]).zfill(6), str(row["isu_cd"]).strip().upper()


def canonical_exclusion_payload() -> dict[str, Any]:
    pairs = sorted((str(t).zfill(6), str(i).strip().upper()) for t, i in PERMANENT_IDENTITY_EXCLUSIONS)
    return {"schema": "sorted_exact_pair_json_v01", "pairs": [list(item) for item in pairs]}


def adjusted_file_metadata(ticker: str) -> dict[str, Any]:
    path = PRICE_DIR / f"{ticker}.parquet"
    base = {"ticker": ticker, "path": str(path.relative_to(ROOT)), "exists": path.is_file(), "sha256": None, "first_date": None, "last_date": None, "date_rows": 0, "read_error": None}
    if not path.is_file():
        return base
    try:
        dates = pd.to_datetime(pq.read_table(path, columns=["date"]).column("date").to_pandas(), errors="coerce").dropna()
        base.update(sha256=sha(path), first_date=dates.min().strftime("%Y-%m-%d") if len(dates) else None, last_date=dates.max().strftime("%Y-%m-%d") if len(dates) else None, date_rows=int(len(dates)))
    except Exception as exc:
        base["read_error"] = type(exc).__name__
    return base


def bounded_start_for_ticker(segments: list[dict[str, Any]], price_meta: dict[str, Any]) -> pd.Timestamp | None:
    first = price_meta.get("first_date")
    if not first:
        return None
    pit_start = min(pd.Timestamp(item["effective_from"]).normalize() for item in segments)
    # The PIT interval bounds which identity is eligible. It is not replaced by
    # the P2 window boundary, so the prior completed bars remain available when
    # the exact identity was already present in the validated PIT history.
    return max(pd.Timestamp(first).normalize(), pit_start)


def inspect_repository_input(repository: Any, ticker: str, segments: list[dict[str, Any]], meta: dict[str, Any], calendar_dates: pd.DatetimeIndex) -> dict[str, Any]:
    start = bounded_start_for_ticker(segments, meta)
    last = meta.get("last_date")
    if start is None or last is None:
        return {"ticker": ticker, "load_status": "ADJUSTED_FILE_UNAVAILABLE", "bounded_load_start": None if start is None else start.strftime("%Y-%m-%d"), "bounded_load_end": None, "first_error": meta.get("read_error") or "ADJUSTED_FILE_MISSING_OR_EMPTY", "adjusted_file_sha256": meta.get("sha256"), "adjusted_first_date": meta.get("first_date"), "adjusted_last_date": last}
    # Request through support even when the adjusted file ends earlier. This is
    # necessary to expose raw-only tails and distinguish authorized zero-volume
    # placeholders from unresolved active-session projection gaps.
    end = SUPPORT
    start_text, end_text = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    result: dict[str, Any] = {
        "ticker": ticker,
        "isu_pairs": ";".join(sorted({"|".join(identity_key(item)) for item in segments})),
        "markets": ";".join(sorted({str(item["market"]).upper() for item in segments})),
        "pit_segment_count": len(segments),
        "pit_effective_from_min": min(str(item["effective_from"])[:10] for item in segments),
        "pit_effective_to_max": max(str(item["effective_to"])[:10] for item in segments),
        "adjusted_file_sha256": meta.get("sha256"),
        "adjusted_first_date": meta.get("first_date"),
        "adjusted_last_date": meta.get("last_date"),
        "bounded_load_start": start_text,
        "bounded_load_end": end_text,
        "load_status": "ERROR",
        "first_error": None,
        "repository_v2_rows": 0,
        "repository_v2_first_date": None,
        "repository_v2_last_date": None,
        "adjusted_only_count": None,
        "unexplained_adjusted_only_count": None,
        "raw_only_count": None,
        "rejected_raw_only_count": None,
        "confirmed_nontrading_placeholder_count": None,
        "silent_inner_drop_count": None,
        "active_pit_expected_sessions": 0,
        "active_pit_sessions_missing_both_sources": 0,
        "first_missing_pit_sessions": "",
        "warmup_adjusted_months_before_first_p1_signal": None,
        "warmup_available_from_month": None,
    }
    try:
        frame = repository.get_daily(ticker, start_text, end_text)
        if frame is None or frame.empty:
            raise RuntimeError("REPOSITORY_V2_EMPTY")
        audit = frame.attrs.get("session_projection_audit", {})
        adjusted_dates = set(pd.to_datetime(audit.get("adjusted_dates", ())).normalize())
        raw_dates = set(pd.to_datetime(audit.get("raw_dates", ())).normalize())
        result.update(
            load_status="AVAILABLE",
            first_error="",
            repository_v2_rows=len(frame),
            repository_v2_first_date=frame.index.min().strftime("%Y-%m-%d"),
            repository_v2_last_date=frame.index.max().strftime("%Y-%m-%d"),
            adjusted_only_count=len(audit.get("adjusted_only_dates", ())),
            unexplained_adjusted_only_count=len(audit.get("unexplained_adjusted_only_dates", ())),
            raw_only_count=len(audit.get("raw_only_dates", ())),
            rejected_raw_only_count=len(audit.get("rejected_raw_only_dates", ())),
            confirmed_nontrading_placeholder_count=int(audit.get("confirmed_nontrading_shared_count", 0) or 0) + len(audit.get("accepted_placeholder_dates", ())),
            adjusted_analytic_invalid_count=int(audit.get("adjusted_analytic_invalid_count", 0) or 0),
            known_adjusted_gap_count=len(audit.get("known_adjusted_gap_dates", ())),
            silent_inner_drop_count=int(audit.get("silent_inner_drop_count", 0) or 0),
            adjusted_only_dates=";".join(pd.Timestamp(day).strftime("%Y-%m-%d") for day in audit.get("adjusted_only_dates", ())),
            unexplained_adjusted_only_dates=";".join(pd.Timestamp(day).strftime("%Y-%m-%d") for day in audit.get("unexplained_adjusted_only_dates", ())),
            raw_only_dates=";".join(pd.Timestamp(day).strftime("%Y-%m-%d") for day in audit.get("raw_only_dates", ())),
            rejected_raw_only_dates=";".join(pd.Timestamp(day).strftime("%Y-%m-%d") for day in audit.get("rejected_raw_only_dates", ())),
            accepted_placeholder_dates=";".join(pd.Timestamp(day).strftime("%Y-%m-%d") for day in audit.get("accepted_placeholder_dates", ())),
        )
    except Exception as exc:
        result["first_error"] = f"{type(exc).__name__}:{str(exc)[:250]}"
        # Inspect exact projected source dates on Repository V2 composition
        # failures so out-of-bound raw-only rows are distinguishable from gaps
        # within the required identity/warmup range.
        try:
            adjusted = repository._load_adjusted(ticker, start, end)
            raw = repository._load_raw(ticker, start, end)
            evidence = _session_projection_evidence(adjusted, raw)
            result.update(
                adjusted_only_count=len(evidence.get("adjusted_only_dates", ())),
                unexplained_adjusted_only_count=len(evidence.get("unexplained_adjusted_only_dates", ())),
                raw_only_count=len(evidence.get("raw_only_dates", ())),
                rejected_raw_only_count=len(evidence.get("rejected_raw_only_dates", ())),
                confirmed_nontrading_placeholder_count=int(evidence.get("confirmed_nontrading_shared_count", 0) or 0) + len(evidence.get("accepted_placeholder_dates", ())),
                silent_inner_drop_count=int(evidence.get("silent_inner_drop_count", 0) or 0),
                adjusted_only_dates=";".join(pd.Timestamp(day).strftime("%Y-%m-%d") for day in evidence.get("adjusted_only_dates", ())),
                unexplained_adjusted_only_dates=";".join(pd.Timestamp(day).strftime("%Y-%m-%d") for day in evidence.get("unexplained_adjusted_only_dates", ())),
                raw_only_dates=";".join(pd.Timestamp(day).strftime("%Y-%m-%d") for day in evidence.get("raw_only_dates", ())),
                rejected_raw_only_dates=";".join(pd.Timestamp(day).strftime("%Y-%m-%d") for day in evidence.get("rejected_raw_only_dates", ())),
                accepted_placeholder_dates=";".join(pd.Timestamp(day).strftime("%Y-%m-%d") for day in evidence.get("accepted_placeholder_dates", ())),
            )
            bad = sorted(set(evidence.get("unexplained_adjusted_only_dates", ())) | set(evidence.get("rejected_raw_only_dates", ())))
            result["first_unresolved_source_dates"] = ";".join(pd.Timestamp(day).strftime("%Y-%m-%d") for day in bad[:20])
        except Exception as detail_exc:
            result["source_gap_detail_error"] = type(detail_exc).__name__
    active_days: set[pd.Timestamp] = set()
    for seg in segments:
        s = max(pd.Timestamp(seg["effective_from"]).normalize(), EVAL_START)
        e = min(pd.Timestamp(seg["effective_to"]).normalize(), CUTOFF)
        if s <= e:
            active_days.update(calendar_dates[(calendar_dates >= s) & (calendar_dates <= e)])
    if active_days:
        source_dates = set()
        if result["load_status"] == "AVAILABLE":
            source_dates = set(frame.index.normalize()) & active_days
        missing_active = sorted(active_days - source_dates)
        result["active_pit_expected_sessions"] = len(active_days)
        result["active_pit_sessions_missing_both_sources"] = len(missing_active)
        result["first_missing_pit_sessions"] = ";".join(day.strftime("%Y-%m-%d") for day in missing_active[:20])
        if result["load_status"] == "AVAILABLE":
            projection = frame.attrs.get("session_projection_audit", {})
            raw_only = {pd.Timestamp(day).normalize() for day in projection.get("raw_only_dates", ())}
            adjusted_only = {pd.Timestamp(day).normalize() for day in projection.get("adjusted_only_dates", ())}
            accepted_placeholders = {pd.Timestamp(day).normalize() for day in projection.get("accepted_placeholder_dates", ())}
            shared_placeholders = {pd.Timestamp(day).normalize() for day in projection.get("confirmed_nontrading_shared_dates", ())}
            adjusted_invalid = {pd.Timestamp(day).normalize() for day in projection.get("adjusted_analytic_invalid_dates", ())}
            known_gaps = {pd.Timestamp(day).normalize() for day in projection.get("known_adjusted_gap_dates", ())}
            outside_lifecycle = {pd.Timestamp(day).normalize() for day in projection.get("outside_identity_lifecycle_dates", ())}
            nonusable = {pd.Timestamp(day).normalize() for day in projection.get("adjusted_source_nonusable_dates", ())}
            raw_details = {pd.Timestamp(item["date"]).normalize(): item for item in projection.get("raw_only_row_details", ())}
            details = []
            for missing_day in missing_active:
                if missing_day in accepted_placeholders:
                    reason = "AUTHORIZED_RAW_NONTRADING_PLACEHOLDER_EXCLUDED_FROM_SIGNALS"
                elif missing_day in shared_placeholders:
                    reason = "CONFIRMED_SHARED_NONTRADING_PLACEHOLDER_EXCLUDED_FROM_SIGNALS"
                elif missing_day in adjusted_invalid:
                    reason = "ADJUSTED_ANALYTICALLY_INVALID_EXCLUDED"
                elif missing_day in known_gaps:
                    reason = "KNOWN_ADJUSTED_SOURCE_GAP"
                elif missing_day in outside_lifecycle:
                    reason = "RAW_ROW_OUTSIDE_IDENTITY_LIFECYCLE"
                elif missing_day in nonusable:
                    reason = "ADJUSTED_SOURCE_NONUSABLE"
                elif missing_day in raw_only:
                    reason = "RAW_ONLY_UNRESOLVED"
                elif missing_day in adjusted_only:
                    reason = "ADJUSTED_ONLY_UNRESOLVED"
                else:
                    reason = "BOTH_SOURCES_MISSING_UNCLASSIFIED"
                raw_detail = raw_details.get(missing_day, {})
                details.append({"ticker": ticker, "date": missing_day.strftime("%Y-%m-%d"), "reason": reason, "raw_row_present": missing_day in raw_only, "adjusted_row_present": missing_day in adjusted_only, "raw_classification": raw_detail.get("classification"), "raw_close": raw_detail.get("close"), "raw_volume": raw_detail.get("volume"), "raw_trading_value": raw_detail.get("trading_value")})
            result["_active_pit_missing_session_rows"] = details
    # P1 begins before 60 completed monthly bars are available from the
    # Repository V2 source. Record the exact shortfall; the frozen candidate
    # filter rejects only affected signals as MA_UNAVAILABLE.
    if result["load_status"] == "AVAILABLE":
        available_months = pd.PeriodIndex(frame.index.to_period("M").unique()).sort_values()
        required = pd.period_range("2009-01", "2013-12", freq="M")
        available_required = required.intersection(available_months)
        result["warmup_adjusted_months_before_first_p1_signal"] = len(available_required)
        result["warmup_available_from_month"] = None if not len(available_months) else str(available_months.min())
    return result


def sample_universe(common_segments: list[dict[str, Any]], identity_audits: list[dict[str, Any]], raw_store: KrxRawStockStore, calendar: Any) -> dict[str, list[str]]:
    eligible = {str(row["ticker"]).zfill(6) for row in common_segments}
    reasons: dict[str, list[str]] = {}

    def add(ticker: str, reason: str) -> None:
        ticker = str(ticker).zfill(6)
        if ticker in eligible:
            reasons.setdefault(ticker, []).append(reason)

    # These names are deterministic sample anchors only; no prior P1 simple
    # trade or signal result is reused as an expected portfolio result.
    for ticker in ("005930", "000660", "005380", "000270", "035420", "005300", "029960", "128940", "003690", "058530", "058220", "099520"):
        add(ticker, "FOCUS_OR_P1_HISTORY_EDGE_CASE")

    # Pick five exact signal-date market partitions with the smallest absolute
    # distance to KRW 500B among exact active PIT identities, plus up to two
    # zero/invalid cap observations. These observations drive sample selection;
    # only evaluator-generated signals are counted as filter evaluations.
    identity_by_market: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for segment in common_segments:
        identity_by_market.setdefault((str(segment["market"]).upper(), str(segment["ticker"]).zfill(6)), []).append(segment)
    cmes = [pd.Timestamp(x).normalize() for x in calendar.completed_month_ends if EVAL_START <= pd.Timestamp(x).normalize() <= CUTOFF]
    all_caps: list[tuple[int, str, str]] = []
    zero_caps: list[tuple[str, str]] = []
    for day in cmes:
        day_text = day.strftime("%Y-%m-%d")
        for market in ("KOSPI", "KOSDAQ"):
            manifest = raw_store.get_manifest(market, day_text)
            if not manifest or manifest.get("status") != "COMPLETE":
                continue
            frame = raw_store.load_snapshot(market, day_text)
            for row in frame.loc[:, ["ticker", "market_cap"]].itertuples(index=False):
                ticker = str(row.ticker).zfill(6)
                if (market, ticker) not in identity_by_market:
                    continue
                active = any(pd.Timestamp(seg["effective_from"]) <= day <= pd.Timestamp(seg["effective_to"]) for seg in identity_by_market[(market, ticker)])
                if not active:
                    continue
                try:
                    cap = int(row.market_cap)
                except (TypeError, ValueError, OverflowError):
                    cap = 0
                if cap > 0:
                    all_caps.append((abs(cap - 500_000_000_000), ticker, day_text))
                else:
                    zero_caps.append((ticker, day_text))
    for _, ticker, _ in sorted(all_caps)[:5]:
        add(ticker, "NEAR_500B_RAW_MCAP_SAMPLE")
    for ticker, _ in sorted(set(zero_caps))[:2]:
        add(ticker, "ZERO_OR_INVALID_RAW_MCAP_SAMPLE")

    # Cover identity interval edges and first/last years without selecting on
    # performance. Then fill by a stable SHA-256 order to ~30 identities.
    by_start = sorted(common_segments, key=lambda r: (str(r["effective_from"]), str(r["ticker"]), str(r["isu_cd"])))
    for row in by_start[:2] + by_start[-2:]:
        add(row["ticker"], "PIT_INTERVAL_EDGE")
    # Include market-transfer/reused-ticker identity histories where present.
    by_exact_identity: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for segment in common_segments:
        by_exact_identity.setdefault((str(segment["ticker"]).zfill(6), str(segment["isu_cd"]).upper()), []).append(segment)
    transfer_tickers = sorted({ticker for (ticker, _isu), rows in by_exact_identity.items() if len({str(row["market"]).upper() for row in rows}) > 1})
    for ticker in transfer_tickers[:3]:
        add(ticker, "P1_MARKET_TRANSFER_IDENTITY")
    reused_tickers = sorted({ticker for ticker in eligible if len({str(row["isu_cd"]).upper() for row in common_segments if str(row["ticker"]).zfill(6) == ticker}) > 1})
    for ticker in reused_tickers[:3]:
        add(ticker, "P1_SEQUENTIAL_IDENTITY_HISTORY")

    ranked = sorted(eligible, key=lambda ticker: hashlib.sha256(f"P1:{ticker}".encode()).hexdigest())
    for ticker in ranked:
        if len(reasons) >= 30:
            break
        add(ticker, "DETERMINISTIC_SHA256_FILL")
    priority = ("FOCUS_OR_P1_HISTORY_EDGE_CASE", "P1_MARKET_TRANSFER_IDENTITY", "P1_SEQUENTIAL_IDENTITY_HISTORY", "PIT_INTERVAL_EDGE", "PIT_SOURCE_ANOMALY_SAMPLE", "NEAR_500B_RAW_MCAP_SAMPLE", "ZERO_OR_INVALID_RAW_MCAP_SAMPLE")
    selected = sorted(reasons, key=lambda ticker: (min((priority.index(r) for r in reasons[ticker] if r in priority), default=len(priority)), hashlib.sha256(f"P1:{ticker}".encode()).hexdigest()))[:30]
    reasons = {ticker: reasons[ticker] for ticker in selected}
    return {"tickers": selected, "reasons_by_ticker": reasons}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    origin = subprocess.check_output(["git", "rev-parse", "origin/main"], cwd=ROOT, text=True).strip()
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    tracked_status = subprocess.check_output(["git", "status", "--short", "--untracked-files=no"], cwd=ROOT, text=True)

    started = time.perf_counter()
    manifest = load_rolling_authority(ROLLING)
    pit_payload, calendar_payload = validate_merged_authority_coherence(manifest, ROLLING)
    calendar = load_rolling_production_market_calendar(ROOT)
    if calendar is None:
        raise RuntimeError("ROLLING_PRODUCTION_CALENDAR_UNAVAILABLE")
    dates = pd.DatetimeIndex(calendar.trading_dates).normalize()
    eval_dates = dates[(dates >= CALENDAR_START) & (dates <= CUTOFF)]
    support_is_next = bool(len(dates[dates > CUTOFF]) and dates[dates > CUTOFF][0] == SUPPORT)
    completed_months = sorted({pd.Timestamp(d).to_period("M") for d in calendar.completed_month_ends})
    prior_months = [month for month in completed_months if month < EVAL_START.to_period("M")]
    warmup_60 = prior_months[-60:]
    required_initial_months = pd.period_range("2009-01", "2013-12", freq="M")
    initial_months_available = required_initial_months.intersection(completed_months)
    first_ma60_possible_month = next((str(month) for month in completed_months if len([prior for prior in completed_months if prior < month]) >= 60 and [prior for prior in completed_months if prior < month][-60:] == pd.period_range(str([prior for prior in completed_months if prior < month][-60]), str([prior for prior in completed_months if prior < month][-1]), freq="M").tolist()), None)

    exclusion_payload = canonical_exclusion_payload()
    canonical_sha = hashlib.sha256(json.dumps(exclusion_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    excluded = {(str(t).zfill(6), str(i).strip().upper()) for t, i in PERMANENT_IDENTITY_EXCLUSIONS}
    if len(excluded) != 184 or canonical_sha != EXPECTED_EXCLUSION_HASH or TARGET_380440 not in excluded:
        raise RuntimeError(f"PERMANENT_EXCLUSION_POLICY_MISMATCH:{len(excluded)}:{canonical_sha}")

    common_before: list[dict[str, Any]] = []
    for row in pit_payload.get("intervals", []):
        if row.get("state") != "COMMON":
            continue
        start = pd.Timestamp(row["effective_from"]).normalize()
        end = pd.Timestamp(row["effective_to"]).normalize()
        if start > CUTOFF or end < CALENDAR_START:
            continue
        common_before.append({"ticker": str(row["ticker"]).zfill(6), "isu_cd": str(row["isu_cd"]).strip().upper(), "market": str(row["market"]).strip().upper(), "effective_from": start.strftime("%Y-%m-%d"), "effective_to": end.strftime("%Y-%m-%d")})
    excluded_overlap = [row for row in common_before if identity_key(row) in excluded]
    common = [row for row in common_before if identity_key(row) not in excluded]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in common:
        grouped.setdefault(row["ticker"], []).append(row)
    for ticker, segments in grouped.items():
        segments.sort(key=lambda row: (row["effective_from"], row["effective_to"], row["isu_cd"], row["market"]))
        for left, right in zip(segments, segments[1:]):
            if pd.Timestamp(right["effective_from"]) <= pd.Timestamp(left["effective_to"]):
                raise RuntimeError(f"OVERLAPPING_PIT_IDENTITY:{ticker}:{left}:{right}")

    price_meta: dict[str, dict[str, Any]] = {}
    for ticker in sorted(grouped):
        price_meta[ticker] = adjusted_file_metadata(ticker)

    repository = build_repository_v2(ROOT, end=SUPPORT)
    def inspect(ticker: str) -> dict[str, Any]:
        return inspect_repository_input(repository, ticker, grouped[ticker], price_meta[ticker], dates)
    with ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="p2-2-v2-preflight") as pool:
        input_audits = list(pool.map(inspect, sorted(grouped)))
    input_audits.sort(key=lambda row: row["ticker"])
    missing_session_rows = [detail for row in input_audits for detail in row.get("_active_pit_missing_session_rows", [])]
    pd.DataFrame([{key: value for key, value in row.items() if not key.startswith("_")} for row in input_audits]).to_csv(OUT / "identity_price_preflight.csv", index=False)
    pd.DataFrame(missing_session_rows).to_csv(OUT / "active_pit_missing_sessions.csv", index=False)

    raw_store = KrxRawStockStore(RAW_DIR)
    raw_partition_rows = []
    for day in list(eval_dates) + ([SUPPORT] if SUPPORT not in set(eval_dates) else []):
        date_text = pd.Timestamp(day).strftime("%Y-%m-%d")
        for market in ("KOSPI", "KOSDAQ"):
            item = raw_store.get_manifest(market, date_text)
            raw_partition_rows.append({
                "market": market,
                "partition_date": date_text,
                "status": None if item is None else item.get("status"),
                "file_path": None if item is None else item.get("file_path"),
                "file_sha256": None if item is None else item.get("file_sha256"),
                "content_sha256": None if item is None else item.get("content_sha256"),
                "row_count": None if item is None else item.get("row_count"),
            })
    pd.DataFrame(raw_partition_rows).to_csv(OUT / "raw_partition_preflight.csv", index=False)
    exclusions_rows = [{"ticker": ticker, "standard_isu_cd": isu, **PERMANENT_IDENTITY_EXCLUSIONS[(ticker, isu)]} for ticker, isu in sorted(excluded)]
    pd.DataFrame(exclusions_rows).to_csv(OUT / "permanent_exclusion_pairs.csv", index=False)

    sample = sample_universe(common, input_audits, raw_store, calendar)
    # Exercise every source anomaly that is not already classified as an
    # approved non-trading placeholder or an analytically-invalid adjusted
    # row. This keeps the residual exact-date cases in the representative
    # evaluator/portfolio path without selecting on backtest performance.
    source_anomaly_by_reason: dict[str, set[str]] = {}
    for row in missing_session_rows:
        if row["reason"] in {
            "ADJUSTED_SOURCE_NONUSABLE",
            "KNOWN_ADJUSTED_SOURCE_GAP",
            "RAW_ROW_OUTSIDE_IDENTITY_LIFECYCLE",
            "RAW_ONLY_UNRESOLVED",
            "ADJUSTED_ONLY_UNRESOLVED",
            "BOTH_SOURCES_MISSING_UNCLASSIFIED",
        }:
            source_anomaly_by_reason.setdefault(str(row["reason"]), set()).add(str(row["ticker"]).zfill(6))
    source_anomaly_tickers = sorted({
        min(tickers, key=lambda ticker: hashlib.sha256(f"P1:{reason}:{ticker}".encode()).hexdigest())
        for reason, tickers in source_anomaly_by_reason.items() if tickers
    })
    for ticker in source_anomaly_tickers:
        sample["reasons_by_ticker"].setdefault(ticker, []).append("PIT_SOURCE_ANOMALY_SAMPLE")
    sample_priority = ("FOCUS_OR_P1_HISTORY_EDGE_CASE", "P1_MARKET_TRANSFER_IDENTITY", "P1_SEQUENTIAL_IDENTITY_HISTORY", "PIT_INTERVAL_EDGE", "PIT_SOURCE_ANOMALY_SAMPLE", "NEAR_500B_RAW_MCAP_SAMPLE", "ZERO_OR_INVALID_RAW_MCAP_SAMPLE")
    sample["tickers"] = sorted(
        sample["reasons_by_ticker"],
        key=lambda ticker: (min((sample_priority.index(r) for r in sample["reasons_by_ticker"][ticker] if r in sample_priority), default=len(sample_priority)), hashlib.sha256(f"P1:{ticker}".encode()).hexdigest()),
    )[:30]
    sample["reasons_by_ticker"] = {ticker: sample["reasons_by_ticker"][ticker] for ticker in sample["tickers"]}
    write_json(OUT / "sample_tickers.json", sample)

    refs = []
    missing_refs = []
    for path_text in REFERENCE_PATHS:
        path = ROOT / path_text
        row = {"path": path_text, "exists": path.is_file(), "sha256": sha(path) if path.is_file() else None, "bytes": path.stat().st_size if path.is_file() else None}
        refs.append(row)
        if not path.is_file():
            missing_refs.append(path_text)

    statuses = pd.Series([row["load_status"] for row in input_audits], dtype="string").value_counts().sort_index().to_dict()
    errors = [row for row in input_audits if row["load_status"] != "AVAILABLE"]
    unresolved_active = [row["ticker"] for row in input_audits if int(row.get("active_pit_sessions_missing_both_sources") or 0) > 0]
    silent_drops = [row["ticker"] for row in input_audits if int(row.get("silent_inner_drop_count") or 0) > 0]
    projection_unexplained = [row["ticker"] for row in input_audits if int(row.get("unexplained_adjusted_only_count") or 0) > 0 or int(row.get("rejected_raw_only_count") or 0) > 0]
    raw_counts = pd.DataFrame(raw_partition_rows)["status"].fillna("MISSING").value_counts().sort_index().to_dict()
    raw_unavailable = [row for row in raw_partition_rows if row["status"] != "COMPLETE"]
    preflight = {
        "schema": "fast_core_v2_alignment_500b_p1_preflight_v01",
        "task_id": TASK_ID,
        "generated_before_sample_or_full_run": True,
        "baseline": {"branch": branch, "head": head, "origin_main": origin, "head_matches_origin_main": head == origin, "tracked_tree_clean_at_start": not bool(tracked_status.strip()), "existing_untracked_items_preserved": True},
        "date_authorities": {
            "calendar_authority": calendar.source_name,
            "calendar_manifest_sha256": manifest.manifest_sha256,
            "calendar_frontier": manifest.merged_calendar_frontier,
            "calendar_start": CALENDAR_START.strftime("%Y-%m-%d"),
            "evaluation_start": None if eval_dates.empty else eval_dates.min().strftime("%Y-%m-%d"),
            "evaluation_end": None if eval_dates.empty else eval_dates.max().strftime("%Y-%m-%d"),
            "evaluation_sessions": int(len(eval_dates)),
            "support_date": SUPPORT.strftime("%Y-%m-%d"),
            "support_is_next_exact_krx_session": support_is_next,
            "completed_ma60_month_count_before_first_p1_signal": len(prior_months),
            "completed_ma60_first_month_before_p1": str(prior_months[0]) if prior_months else None,
            "completed_ma60_last_month_before_p1": str(prior_months[-1]) if prior_months else None,
            "initial_ma60_required_months": [str(required_initial_months[0]), str(required_initial_months[-1])],
            "initial_ma60_required_count": len(required_initial_months),
            "initial_ma60_available_count_from_repository_calendar": len(initial_months_available),
            "first_possible_ma60_signal_month_calendar_only": first_ma60_possible_month,
            "signal_month_excluded": True,
        },
        "universe": {
            "authority": "validated rolling merged PIT COMMON; exact signal-date ticker + standard ISU_CD + market",
            "common_intervals_overlapping_p1_before_exclusions": len(common_before),
            "common_intervals_after_exclusions": len(common),
            "eligible_tickers_after_exclusions": len(grouped),
            "overlapping_excluded_pit_intervals": len(excluded_overlap),
            "current_exclusion_pair_count": len(excluded),
            "permanent_exclusion_file_sha256": sha(ROOT / "src/trend_scanner/universe/permanent_identity_exclusions.py"),
            "permanent_exclusion_canonical_sha256": canonical_sha,
            "permanent_exclusion_hash_matches_directive": canonical_sha == EXPECTED_EXCLUSION_HASH,
            "380440_exact_pair_in_registry": TARGET_380440 in excluded,
            "380440_p1_common_overlap_rows_before_exclusion": [row for row in common_before if identity_key(row) == TARGET_380440],
            "380440_in_eligible_universe": any(identity_key(row) == TARGET_380440 for row in common),
            "tickers_with_multiple_nonoverlapping_p2_identities": sum(len({(item["isu_cd"], item["market"]) for item in rows}) > 1 for rows in grouped.values()),
            "identity_overlap_check": "PASS; multiple sequential ticker/ISU/market intervals are allowed, but more than one active exact identity on a signal date is rejected by the evaluator",
        },
        "repository_v2_input_preflight": {
            "load_bounds": "max(adjusted source first date, earliest overlapping exact COMMON identity effective_from) .. support session; classify raw-only tail dates",
            "worker_count": WORKERS,
            "unique_tickers_checked": len(input_audits),
            "load_status_counts": statuses,
            "unavailable_or_error_tickers": [row["ticker"] for row in errors],
            "unavailable_reasons": pd.Series([str(row.get("first_error") or "") for row in errors], dtype="string").value_counts().sort_index().to_dict(),
            "tickers_with_unresolved_active_pit_sessions": unresolved_active,
            "tickers_with_silent_repository_projection_drops": silent_drops,
            "tickers_with_unexplained_repository_projection_mismatches": projection_unexplained,
            "active_pit_missing_source_rows_total": int(sum(int(row.get("active_pit_sessions_missing_both_sources") or 0) for row in input_audits)),
            "active_pit_missing_session_reason_counts": pd.DataFrame(missing_session_rows)["reason"].value_counts().sort_index().to_dict() if missing_session_rows else {},
            "active_pit_missing_session_detail_path": "active_pit_missing_sessions.csv",
            "raw_only_unclassified_sessions_total": int(sum(int(row.get("rejected_raw_only_count") or 0) for row in input_audits)),
            "adjusted_only_unexplained_sessions_total": int(sum(int(row.get("unexplained_adjusted_only_count") or 0) for row in input_audits)),
            "pit_internal_projection_failures": [row["ticker"] for row in input_audits if row["load_status"] != "AVAILABLE"],
            "detailed_audit_path": "identity_price_preflight.csv",
            "adjusted_file_hash_inventory_count": len(price_meta),
            "all_adjusted_files_hashed": all(bool(meta.get("sha256")) for meta in price_meta.values()),
        },
        "krx_raw_signal_partition_preflight": {"market_partition_count": len(raw_partition_rows), "status_counts": raw_counts, "unavailable_partition_count": len(raw_unavailable), "unavailable_partition_examples": raw_unavailable[:30], "support_date_included_for_exit_only": True, "detailed_path": "raw_partition_preflight.csv"},
        "sample_selection": {"selected_ticker_count": len(sample["tickers"]), "selection_file": "sample_tickers.json", "deterministic_selection": True, "includes_005300_early_ma60_case": "005300" in sample["tickers"], "includes_market_transfer_or_sequential_identity_history": any(any(reason in {"P1_MARKET_TRANSFER_IDENTITY", "P1_SEQUENTIAL_IDENTITY_HISTORY"} for reason in reasons) for reasons in sample["reasons_by_ticker"].values()), "includes_near_500b_raw_mcap": any("NEAR_500B_RAW_MCAP_SAMPLE" in r for rs in sample["reasons_by_ticker"].values() for r in rs), "includes_representative_classified_source_anomalies": any("PIT_SOURCE_ANOMALY_SAMPLE" in rs for rs in sample["reasons_by_ticker"].values()), "classified_source_anomaly_tickers_total": int(sum(len(tickers) for tickers in source_anomaly_by_reason.values())), "classified_source_anomaly_sample_tickers": source_anomaly_tickers},
        "source_references": refs,
        "missing_required_sources": missing_refs,
        "external_api_requests": 0,
        "preflight_elapsed_seconds": round(time.perf_counter() - started, 3),
        "preflight_status": "PASS" if head == origin and not tracked_status.strip() and not missing_refs and support_is_next and len(eval_dates) > 0 and eval_dates[0] == EVAL_START and eval_dates[-1] == CUTOFF and len(grouped) > 0 and canonical_sha == EXPECTED_EXCLUSION_HASH and not errors and not silent_drops and not projection_unexplained and not raw_unavailable else "CHECK_REQUIRED",
        "status_note": "Active PIT sessions without a composed adjusted+raw row are itemized by exact date and source evidence. Authorized non-trading placeholders are excluded from signal data; actual missing held-position marks are audited during portfolio replay. Repository V2 projection errors and data-unavailable identities remain blocking preflight findings.",
    }
    write_json(OUT / "preflight.json", preflight)
    print(json.dumps({"status": preflight["preflight_status"], "evaluation_sessions": len(eval_dates), "eligible_tickers": len(grouped), "input_status_counts": statuses, "unavailable_or_error_count": len(errors), "active_pit_missing_source_tickers": len(unresolved_active), "pre_p1_completed_months": len(prior_months), "initial_ma60_months_available": len(initial_months_available), "first_possible_ma60_signal_month_calendar_only": first_ma60_possible_month, "sample_ticker_count": len(sample["tickers"]), "sample_tickers": sample["tickers"], "elapsed_seconds": preflight["preflight_elapsed_seconds"]}, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
