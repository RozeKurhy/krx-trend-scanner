#!/usr/bin/env python3
"""Matched P2-1 V2 vs NEG40/WEAK-protect research run.

This runner is intentionally isolated from canonical V2 artifacts and the
older frozen raw-candidate population. It creates the P2-1 entry population
from COMMON PIT identity intervals and the current V2 entry evaluator.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import shutil
import time
from typing import Any, Mapping, Sequence
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

import numpy as np
import pandas as pd

from trend_scanner.backtest.standard_windows import resolve_standard_backtest_window
from trend_scanner.data.adjusted_price_authority_cutover import load_effective_authority
from trend_scanner.data.krx_historical_instrument_acquisition import load_historical_trading_calendar
from trend_scanner.data.market_calendar import load_rolling_production_market_calendar
from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader, build_repository_v2
from trend_scanner.patterns.pattern_a_evaluator import evaluate_pattern_a
from trend_scanner.universe.survivorship_safe_denominator_freeze import pit_denominator_manifest_sha256
from trend_scanner.validation import pattern_a_fast_core_v02_reentry as v2


ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_DIR = ROOT / "artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/v01_spac_corrected_effective_authority"
P2_2_AUTHORITY_EXTENSION_DIR = ROOT / "artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/p2_2_identity_authority_extension_v01"
HISTORICAL_IDENTITY_CALENDAR_PATH = ROOT / "data/reference/source/history/krx_instrument_master/v01/historical_trading_calendar.json"
SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"
RAW_CANDIDATE_PATH = ROOT / "artifacts/backtests/fastcore_fundamentals_simple_v01/raw_candidates/fastcore_raw_candidates.csv"
P2_1_RUN_ID = "run_20260923"
P2_1_RUN_DIR = ROOT / "artifacts/backtests/p2_1_neg40_weak_protect_v01" / P2_1_RUN_ID
P2_1_CORRECTED_RUN_DIR = P2_1_RUN_DIR / "candidate_replay_20260923_fix02"
P2_1_LEDGER_SUMMARY_PATH = P2_1_CORRECTED_RUN_DIR / "p2_1_summary.json"
P2_2_LEDGER_SUMMARY_PATH = (
    ROOT
    / "artifacts/backtests/p2_2_neg40_weak_protect_v01/run_20260924_final_corrective_v01/p2_2_summary.json"
)
P3_1_RUN_ID = "run_20260924_single_window_v01"
P3_1_RUN_DIR = ROOT / "artifacts/backtests/p3_1_neg40_weak_protect_v01" / P3_1_RUN_ID
LIFECYCLE_SETTLEMENT_EVIDENCE_PATH = (
    ROOT / "docs/strategies/p2_2_lifecycle_settlement_evidence_v01.json"
)
WINDOW_ID = "P2-1"
RUN_ID = P2_1_RUN_ID
RUN_DIR = P2_1_RUN_DIR
SAMPLE_PATH = RUN_DIR / "sample_benchmark.json"
CONTROL_FULL_PATH = RUN_DIR / "control_trades.csv"
INITIAL_FULL_SUMMARY_PATH = RUN_DIR / "summary.json"
CORRECTED_RUN_DIR = P2_1_CORRECTED_RUN_DIR
MATCHED_LEDGER_PATH = CORRECTED_RUN_DIR / "p2_1_matched_trades.csv"
SOFT_EVENTS_PATH = CORRECTED_RUN_DIR / "p2_1_soft_events.csv"
LEDGER_SUMMARY_PATH = P2_1_LEDGER_SUMMARY_PATH
MAX_FULL_ESTIMATE_SECONDS = 90 * 60
DEFAULT_WORKERS = 8
V2_STRATEGY_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V02"
CANDIDATE_STRATEGY_ID = "PATTERN_A_FAST_CORE_V2_NEG40_WEAK_PROTECT_SOFT_EXIT_V01"


def _configure_run(window_id: str, run_id_override: str | None = None) -> None:
    """Select a standard-window output namespace before starting a run."""
    global WINDOW_ID, RUN_ID, RUN_DIR, SAMPLE_PATH, CONTROL_FULL_PATH
    global INITIAL_FULL_SUMMARY_PATH, CORRECTED_RUN_DIR, MATCHED_LEDGER_PATH
    global SOFT_EVENTS_PATH, LEDGER_SUMMARY_PATH

    if window_id == "P2-1":
        run_id = P2_1_RUN_ID if run_id_override is None else run_id_override
        if run_id_override is not None and (
            not run_id.startswith("run_")
            or not all(char.isascii() and (char.isalnum() or char in "_-") for char in run_id)
        ):
            raise ValueError("P2-1 run id must start with 'run_' and contain only ASCII letters, digits, '_' or '-'")
        run_dir = (
            P2_1_RUN_DIR
            if run_id_override is None
            else ROOT / "artifacts/backtests/p2_1_neg40_weak_protect_v01" / run_id
        )
        # An explicitly versioned recertification run owns its complete output
        # set, including the matched ledger. Keep the original fix02 namespace
        # untouched when the standard P2-1 run ID is selected.
        corrected_dir = P2_1_CORRECTED_RUN_DIR if run_id_override is None else run_dir
        ledger_name = "p2_1_matched_trades.csv"
        events_name = "p2_1_soft_events.csv"
        ledger_summary_name = "p2_1_summary.json"
    elif window_id == "P2-2":
        run_id = "run_20260923" if run_id_override is None else run_id_override
        if (
            not run_id.startswith("run_")
            or not all(char.isascii() and (char.isalnum() or char in "_-") for char in run_id)
        ):
            raise ValueError("P2-2 run id must start with 'run_' and contain only ASCII letters, digits, '_' or '-'")
        run_dir = ROOT / "artifacts/backtests/p2_2_neg40_weak_protect_v01" / run_id
        corrected_dir = run_dir
        ledger_name = "p2_2_matched_trades.csv"
        events_name = "p2_2_soft_events.csv"
        ledger_summary_name = "p2_2_summary.json"
    elif window_id == "P3-1":
        run_id = P3_1_RUN_ID
        run_dir = P3_1_RUN_DIR
        corrected_dir = run_dir
        ledger_name = "p3_1_matched_trades.csv"
        events_name = "p3_1_soft_events.csv"
        ledger_summary_name = "p3_1_summary.json"
    else:
        raise ValueError(f"unsupported matched A/B window: {window_id}")

    if run_id_override is not None and window_id not in {"P2-1", "P2-2"}:
        raise ValueError("--run-id override is supported only for P2-1 and P2-2")

    WINDOW_ID = window_id
    RUN_ID = run_id
    RUN_DIR = run_dir
    SAMPLE_PATH = run_dir / (
        "sample_benchmark_p2_2_pit_extension_v01.json"
        if window_id == "P2-2"
        else "sample_benchmark_p3_1_common_pit_v01.json"
        if window_id == "P3-1"
        else "sample_benchmark.json"
    )
    CONTROL_FULL_PATH = run_dir / "control_trades.csv"
    INITIAL_FULL_SUMMARY_PATH = run_dir / "summary.json"
    CORRECTED_RUN_DIR = corrected_dir
    MATCHED_LEDGER_PATH = corrected_dir / ledger_name
    SOFT_EVENTS_PATH = corrected_dir / events_name
    LEDGER_SUMMARY_PATH = corrected_dir / ledger_summary_name


@dataclass(frozen=True)
class IdentitySegment:
    ticker: str
    isu_cd: str
    market: str
    effective_from: pd.Timestamp
    effective_to: pd.Timestamp

    @property
    def stable_security_id(self) -> str:
        """KRX Basic Info standard code; unlike the PIT segment key, it excludes coverage dates."""
        return str(self.isu_cd).strip().upper()

    @property
    def key(self) -> str:
        """Run-local PIT segment key, not a cross-run security identity."""
        return "|".join(
            (
                self.ticker,
                self.isu_cd,
                self.market,
                self.effective_from.strftime("%Y-%m-%d"),
                self.effective_to.strftime("%Y-%m-%d"),
            )
        )


@dataclass(frozen=True)
class RunContext:
    window: Any
    calendar: Any
    authority: Any
    segments_by_ticker: Mapping[str, tuple[IdentitySegment, ...]]
    score_contract: dict[str, Any]
    stage_contract: dict[str, Any]
    loader: RepositoryV2DailyLoader
    lifecycle_settlements: tuple[dict[str, Any], ...]
    authority_coverage_start: str
    authority_coverage_end: str
    setup_seconds: float


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _lifecycle_settlement_event_key(record: Mapping[str, Any]) -> tuple[str, ...]:
    """Identify one authoritative lifecycle event without PIT interval boundaries."""
    settlement_date = pd.Timestamp(record["settlement_date"]).normalize().strftime("%Y-%m-%d")
    return (
        str(record["isu_cd"]).strip().upper(),
        str(record["source_authority"]).strip(),
        str(record["source_document_id"]).strip(),
        str(record["settlement_type"]).strip(),
        str(record["terminal_reason"]).strip(),
        settlement_date,
    )


def _load_lifecycle_settlement_evidence(path: Path) -> tuple[dict[str, Any], ...]:
    """Load confirmed settlement events keyed by stable ISU and event provenance.

    identity_effective_from/to remain as source-time PIT context in schema v01, not lookup keys.
    """
    if not path.is_file():
        raise RuntimeError(f"lifecycle settlement evidence missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "lifecycle_settlement_evidence_v01":
        raise RuntimeError("lifecycle settlement evidence schema mismatch")
    records = payload.get("records")
    if not isinstance(records, list):
        raise RuntimeError("lifecycle settlement evidence records must be a list")

    required = {
        "evidence_id",
        "evidence_status",
        "ticker",
        "isu_cd",
        "market",
        "identity_effective_from",
        "identity_effective_to",
        "settlement_date",
        "settlement_price",
        "settlement_type",
        "terminal_reason",
        "settlement_source",
        "source_authority",
        "source_document_id",
        "source_published_date",
    }
    event_keys: set[tuple[str, ...]] = set()
    evidence_ids: set[str] = set()
    accepted: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict) or not required.issubset(record):
            raise RuntimeError("lifecycle settlement evidence record is missing required fields")
        if record["evidence_status"] != "CONFIRMED" or record["source_authority"] != "KRX_KIND":
            raise RuntimeError("lifecycle settlement evidence is not confirmed KRX KIND evidence")
        if record["settlement_type"] != "CASH_PER_SHARE" or not record["terminal_reason"]:
            raise RuntimeError("unsupported lifecycle settlement contract in evidence")
        source = str(record["settlement_source"])
        if not source.startswith("https://kind.krx.co.kr/"):
            raise RuntimeError("lifecycle settlement provenance must point to official KRX KIND")
        price = float(record["settlement_price"])
        if not np.isfinite(price) or price <= 0:
            raise RuntimeError("lifecycle settlement price must be finite and positive")
        try:
            effective_from = pd.Timestamp(record["identity_effective_from"]).normalize()
            effective_to = pd.Timestamp(record["identity_effective_to"]).normalize()
            settlement_date = pd.Timestamp(record["settlement_date"]).normalize()
            pd.Timestamp(record["source_published_date"]).normalize()
        except (TypeError, ValueError) as exc:
            raise RuntimeError("lifecycle settlement evidence contains an invalid date") from exc
        normalized_isu = str(record["isu_cd"]).strip().upper()
        if not normalized_isu or not str(record["source_document_id"]).strip():
            raise RuntimeError("lifecycle settlement evidence is missing stable security/event identity")
        event_key = _lifecycle_settlement_event_key(record)
        evidence_id = str(record["evidence_id"])
        if event_key in event_keys or evidence_id in evidence_ids:
            raise RuntimeError("duplicate lifecycle settlement event/evidence id")
        event_keys.add(event_key)
        evidence_ids.add(evidence_id)
        accepted.append(
            {
                **record,
                "ticker": str(record["ticker"]).zfill(6),
                "isu_cd": normalized_isu,
                "settlement_price": price,
            }
        )
    return tuple(accepted)


def _extension_content_digest(items: Sequence[Any]) -> str:
    blob = json.dumps(list(items), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _pit_overlap_projection(
    intervals: Sequence[Mapping[str, Any]],
    *,
    boundary: str,
) -> list[tuple[str, str, str, str, str, str]]:
    projected = []
    for interval in intervals:
        start = str(interval["effective_from"])
        if start > boundary:
            continue
        end = min(str(interval["effective_to"]), boundary)
        projected.append(
            (
                str(interval["ticker"]),
                str(interval["isu_cd"]),
                str(interval["market"]),
                str(interval.get("state", "COMMON")),
                start,
                end,
            )
        )
    return sorted(projected)


def _load_p2_2_extended_identity_authority(authority: Any) -> tuple[Any, str, str]:
    """Load the generated PIT extension without deriving coverage from interval ends."""
    manifest_path = P2_2_AUTHORITY_EXTENSION_DIR / "p2_2_identity_authority_extension_manifest.json"
    pit_path = P2_2_AUTHORITY_EXTENSION_DIR / "merged_pit_intervals.json"
    calendar_path = P2_2_AUTHORITY_EXTENSION_DIR / "merged_trading_calendar.json"
    if not all(path.is_file() for path in (manifest_path, pit_path, calendar_path)):
        raise RuntimeError("P2_2_IDENTITY_AUTHORITY_EXTENSION_ARTIFACT_MISSING")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pit_payload = json.loads(pit_path.read_text(encoding="utf-8"))
    calendar_payload = json.loads(calendar_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "p2_2_identity_authority_extension_v01" or manifest.get("status") != "PASS":
        raise RuntimeError("P2_2_IDENTITY_AUTHORITY_EXTENSION_MANIFEST_INVALID")
    if manifest.get("base_effective_pit_file_sha256") != _sha256(authority.pit_path):
        raise RuntimeError("P2_2_IDENTITY_AUTHORITY_BASELINE_HASH_MISMATCH")
    if manifest.get("merged_pit_file_sha256") != _sha256(pit_path):
        raise RuntimeError("P2_2_IDENTITY_AUTHORITY_PIT_FILE_HASH_MISMATCH")
    if manifest.get("merged_calendar_file_sha256") != _sha256(calendar_path):
        raise RuntimeError("P2_2_IDENTITY_AUTHORITY_CALENDAR_FILE_HASH_MISMATCH")
    if pit_payload.get("schema_version") != "MERGED_PIT_V01":
        raise RuntimeError("P2_2_IDENTITY_AUTHORITY_PIT_SCHEMA_MISMATCH")
    if calendar_payload.get("schema_version") != "MERGED_CALENDAR_V01":
        raise RuntimeError("P2_2_IDENTITY_AUTHORITY_CALENDAR_SCHEMA_MISMATCH")

    intervals = tuple(pit_payload.get("intervals", ()))
    dates = tuple(str(day) for day in calendar_payload.get("trading_dates", ()))
    if pit_payload.get("content_digest") != _extension_content_digest(intervals):
        raise RuntimeError("P2_2_IDENTITY_AUTHORITY_PIT_CONTENT_DIGEST_MISMATCH")
    if calendar_payload.get("content_digest") != _extension_content_digest(dates):
        raise RuntimeError("P2_2_IDENTITY_AUTHORITY_CALENDAR_CONTENT_DIGEST_MISMATCH")

    coverage_start = str(manifest.get("coverage_start", ""))
    coverage_end = str(calendar_payload.get("calendar_frontier", ""))
    if not coverage_start or not coverage_end or coverage_start > coverage_end:
        raise RuntimeError("P2_2_IDENTITY_AUTHORITY_GLOBAL_COVERAGE_INVALID")
    if pit_payload.get("pit_frontier") != manifest.get("pit_frontier"):
        raise RuntimeError("P2_2_IDENTITY_AUTHORITY_PIT_FRONTIER_MISMATCH")
    if coverage_end != manifest.get("coverage_end"):
        raise RuntimeError("P2_2_IDENTITY_AUTHORITY_CALENDAR_FRONTIER_MISMATCH")
    if manifest.get("requested_effective_end") != "2026-08-31":
        raise RuntimeError("P2_2_IDENTITY_AUTHORITY_WINDOW_CUTOFF_MISMATCH")
    if manifest.get("execution_support") != "2026-09-01" or coverage_end < "2026-09-01":
        raise RuntimeError("P2_2_IDENTITY_AUTHORITY_EXECUTION_SUPPORT_MISMATCH")

    historical = load_historical_trading_calendar(HISTORICAL_IDENTITY_CALENDAR_PATH)
    old_boundary = historical["last_trading_date"]
    expected_dates = tuple(day for day in dates if day > old_boundary)
    if expected_dates != tuple(manifest.get("extension_dates", ())):
        raise RuntimeError("P2_2_IDENTITY_AUTHORITY_EXTENSION_DATE_SET_MISMATCH")
    if not dates or dates[0] != historical["first_trading_date"]:
        raise RuntimeError("P2_2_IDENTITY_AUTHORITY_COVERAGE_START_MISMATCH")
    if coverage_start != dates[0]:
        raise RuntimeError("P2_2_IDENTITY_AUTHORITY_GLOBAL_COVERAGE_START_MISMATCH")
    if coverage_end != dates[-1] or coverage_end != "2026-09-01":
        raise RuntimeError("P2_2_IDENTITY_AUTHORITY_GLOBAL_FRONTIER_INVALID")

    if _pit_overlap_projection(authority.pit_intervals, boundary=old_boundary) != _pit_overlap_projection(
        intervals, boundary=old_boundary
    ):
        raise RuntimeError("P2_2_IDENTITY_AUTHORITY_HISTORICAL_OVERLAP_CHANGED")
    identity_keys = [
        (
            str(item.get("ticker", "")),
            str(item.get("isu_cd", "")),
            str(item.get("market", "")),
            str(item.get("effective_from", "")),
            str(item.get("effective_to", "")),
        )
        for item in intervals
    ]
    if len(identity_keys) != len(set(identity_keys)):
        raise RuntimeError("P2_2_IDENTITY_AUTHORITY_DUPLICATE_INTERVAL")

    extended_authority = replace(
        authority,
        pit_intervals=intervals,
        pit_path=pit_path,
        pit_sha256=pit_denominator_manifest_sha256(intervals),
    )
    return extended_authority, str(dates[0]), coverage_end


def _load_context(window_id: str | None = None) -> RunContext:
    started = time.perf_counter()
    calendar = load_rolling_production_market_calendar(ROOT)
    selected_window = window_id or WINDOW_ID
    window = resolve_standard_backtest_window(selected_window, calendar)
    expected_by_window = {
        "P2-1": ("2021-01-04", "2025-05-30", "2025-06-02"),
        "P2-2": ("2021-01-04", "2026-08-31", "2026-09-01"),
        "P3-1": ("2022-01-03", "2025-05-30", "2025-06-02"),
    }
    try:
        expected = expected_by_window[selected_window]
    except KeyError as exc:
        raise ValueError(f"unsupported matched A/B window: {selected_window}") from exc
    actual = tuple(
        value.strftime("%Y-%m-%d")
        for value in (window.effective_start, window.effective_end, window.execution_support)
    )
    if actual != expected:
        raise RuntimeError(
            f"{selected_window} window contract mismatch: expected={expected}, actual={actual}"
        )

    authority = load_effective_authority(AUTHORITY_DIR)
    base_calendar = load_historical_trading_calendar(HISTORICAL_IDENTITY_CALENDAR_PATH)
    authority_coverage_start = str(base_calendar["first_trading_date"])
    authority_coverage_end = str(base_calendar["last_trading_date"])
    if selected_window == "P2-2":
        authority, authority_coverage_start, authority_coverage_end = _load_p2_2_extended_identity_authority(
            authority
        )
    if selected_window in {"P2-2", "P3-1"}:
        lifecycle_settlements = _load_lifecycle_settlement_evidence(
            LIFECYCLE_SETTLEMENT_EVIDENCE_PATH
        )
    else:
        lifecycle_settlements = ()
    segments: list[IdentitySegment] = []
    for item in authority.pit_intervals:
        if item.get("state") != "COMMON":
            continue
        start = pd.Timestamp(item["effective_from"]).normalize()
        end = pd.Timestamp(item["effective_to"]).normalize()
        if start > window.effective_end or end < window.effective_start:
            continue
        if start > end:
            raise RuntimeError(f"invalid COMMON identity interval: {item!r}")
        segments.append(
            IdentitySegment(
                ticker=str(item["ticker"]).zfill(6),
                isu_cd=str(item["isu_cd"]),
                market=str(item["market"]),
                effective_from=start,
                effective_to=end,
            )
        )
    if len({segment.key for segment in segments}) != len(segments):
        raise RuntimeError("duplicate COMMON identity interval in effective PIT authority")
    segments.sort(key=lambda row: (row.ticker, row.effective_from, row.effective_to, row.isu_cd))
    prior_by_ticker: dict[str, IdentitySegment] = {}
    grouped: dict[str, list[IdentitySegment]] = {}
    for segment in segments:
        prior = prior_by_ticker.get(segment.ticker)
        if prior is not None and segment.effective_from <= prior.effective_to:
            raise RuntimeError(
                "overlapping COMMON identity intervals for one ticker; refusing to stitch: "
                f"{prior.key} / {segment.key}"
            )
        prior_by_ticker[segment.ticker] = segment
        grouped.setdefault(segment.ticker, []).append(segment)

    score_contract = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    stage_contract = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))
    repository = build_repository_v2(ROOT, end=window.execution_support)
    loader = RepositoryV2DailyLoader(repository, end=window.execution_support)
    return RunContext(
        window=window,
        calendar=calendar,
        authority=authority,
        segments_by_ticker={key: tuple(value) for key, value in grouped.items()},
        score_contract=score_contract,
        stage_contract=stage_contract,
        loader=loader,
        lifecycle_settlements=lifecycle_settlements,
        authority_coverage_start=authority_coverage_start,
        authority_coverage_end=authority_coverage_end,
        setup_seconds=time.perf_counter() - started,
    )


def _p2_2_identity_authority_preflight(run: RunContext) -> dict[str, Any]:
    """Require global PIT authority coverage through P2-2's effective cutoff."""
    if run.window.window.window_id != "P2-2":
        raise ValueError("P2-2 identity preflight requires a P2-2 RunContext")
    coverage_start = getattr(run, "authority_coverage_start", None)
    coverage_end = getattr(run, "authority_coverage_end", None)
    effective_start = run.window.effective_start.strftime("%Y-%m-%d")
    effective_end = run.window.effective_end.strftime("%Y-%m-%d")
    passed = bool(
        coverage_start
        and coverage_end
        and str(coverage_start) <= effective_start
        and str(coverage_end) >= effective_end
    )
    relevant = [
        segment
        for rows in run.segments_by_ticker.values()
        for segment in rows
        if segment.effective_from <= run.window.effective_end
        and segment.effective_to >= run.window.effective_start
    ]
    return {
        "status": "PASS" if passed else "CHECK_REQUIRED",
        "window_id": "P2-2",
        "effective_start": effective_start,
        "effective_end": effective_end,
        "execution_support": run.window.execution_support.strftime("%Y-%m-%d"),
        "pit_common_authority_global_coverage_start": coverage_start,
        "pit_common_authority_global_coverage_end": coverage_end,
        "common_identity_segment_count": len(relevant),
        "reason": None if passed else "PIT_COMMON_AUTHORITY_GLOBAL_COVERAGE_SHORT_OF_P2_2_CUTOFF",
    }


def _p3_1_population_preflight(run: RunContext) -> dict[str, Any]:
    """Validate the independent P3-1 window and freshly derived COMMON PIT universe."""
    if run.window.window.window_id != "P3-1":
        raise ValueError("P3-1 population preflight requires a P3-1 RunContext")
    expected = ("2022-01-03", "2025-05-30", "2025-06-02")
    actual = tuple(
        value.strftime("%Y-%m-%d")
        for value in (run.window.effective_start, run.window.effective_end, run.window.execution_support)
    )
    coverage_start = str(run.authority_coverage_start)
    coverage_end = str(run.authority_coverage_end)
    relevant = [
        segment
        for rows in run.segments_by_ticker.values()
        for segment in rows
        if segment.effective_from <= run.window.effective_end
        and segment.effective_to >= run.window.effective_start
    ]
    checks = {
        "window_resolve": actual == expected,
        "authority_coverage_start": bool(coverage_start and coverage_start <= expected[0]),
        "authority_coverage_execution_support": bool(coverage_end and coverage_end >= expected[2]),
        "common_pit_population_nonempty": bool(relevant),
        "common_identity_segment_unique": len({item.key for item in relevant}) == len(relevant),
        "identity_boundary_contract": all(item.effective_from <= item.effective_to for item in relevant),
        "p2_population_not_reused": True,
    }
    return {
        "status": "PASS" if all(checks.values()) else "CHECK_REQUIRED",
        "window_id": "P3-1",
        "expected_window": expected,
        "actual_window": actual,
        "authority_coverage_start": coverage_start,
        "authority_coverage_end": coverage_end,
        "execution_support": expected[2],
        "common_identity_segment_count": len(relevant),
        "common_ticker_count": len(run.segments_by_ticker),
        "population_source": str(run.authority.pit_path.relative_to(ROOT)),
        "p2_population_reused": False,
        "effective_pit_sha256": run.authority.pit_sha256,
        "checks": checks,
    }


def _sample_tickers(tickers: Sequence[str], count: int) -> list[str]:
    if count <= 0:
        raise ValueError("sample ticker count must be positive")
    if count >= len(tickers):
        return list(tickers)
    if count == 1:
        return [tickers[len(tickers) // 2]]
    indexes = sorted({round(i * (len(tickers) - 1) / (count - 1)) for i in range(count)})
    return [tickers[index] for index in indexes]


def _stage_timeline(
    daily: pd.DataFrame,
    context: Any,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    calendar: Any,
) -> dict[pd.Timestamp, str]:
    timeline: dict[pd.Timestamp, str] = {}
    monthly = context.monthly_up_to(end_date)
    for month_end in monthly.index:
        month_end = pd.Timestamp(month_end).normalize()
        if month_end < start_date:
            continue
        effective_dates = daily.index[(daily.index <= month_end) & (daily.index <= end_date)]
        if effective_dates.empty:
            continue
        effective_date = pd.Timestamp(effective_dates[-1]).normalize()
        if effective_date < start_date or effective_date > end_date:
            continue
        snapshot = v2.build_historical_snapshot_from_context(
            context,
            month_end,
            include_incomplete_periods=False,
            market_calendar=calendar,
        )
        evaluated = evaluate_pattern_a(snapshot)
        stage = evaluated.stage.value.upper() if evaluated.stage else "UNAVAILABLE"
        # A calendar month-end label can fall on a holiday/weekend. The
        # completed snapshot is observable at the last local trading close.
        timeline[effective_date] = stage
    return timeline


def _effective_eod_for_signal(
    daily: pd.DataFrame,
    signal_date: pd.Timestamp | None,
    valuation_end: pd.Timestamp,
) -> pd.Timestamp | None:
    if signal_date is None:
        return None
    eligible = daily.index[(daily.index <= signal_date) & (daily.index <= valuation_end)]
    return pd.Timestamp(eligible[-1]).normalize() if len(eligible) else None


def _next_local_session(
    daily: pd.DataFrame,
    date: pd.Timestamp,
    support: pd.Timestamp,
) -> pd.Timestamp | None:
    later = daily.index[(daily.index > date) & (daily.index <= support)]
    return pd.Timestamp(later[0]).normalize() if len(later) else None


def _common_entry_eligibility_cutoff(segment: IdentitySegment, cutoff: pd.Timestamp) -> pd.Timestamp:
    """Limit new-entry signals to both the window and this COMMON interval."""
    return min(pd.Timestamp(cutoff).normalize(), segment.effective_to)


def _pct(price: float, entry_open: float) -> float:
    # Match V2's arithmetic exactly; algebraically equivalent forms can land
    # on opposite sides of a two-decimal binary-float rounding tie.
    return round(((float(price) - float(entry_open)) / float(entry_open)) * 100.0, 2)


def _refresh_outcome_metrics(
    row: dict[str, Any],
    daily: pd.DataFrame,
    entry_date: pd.Timestamp,
    entry_open: float,
    valuation_end: pd.Timestamp,
    *,
    exit_date: pd.Timestamp | None = None,
    exit_open: float | None = None,
) -> None:
    if exit_date is not None and exit_open is not None:
        holding = daily[(daily.index >= entry_date) & (daily.index < exit_date)]
        held_days = int(len(daily[(daily.index >= entry_date) & (daily.index <= exit_date)]))
        highs = holding["high"].tolist() + [exit_open]
        lows = holding["low"].tolist() + [exit_open]
        terminal = _pct(exit_open, entry_open)
    else:
        holding = daily[(daily.index >= entry_date) & (daily.index <= valuation_end)]
        held_days = int(len(holding))
        highs = holding["high"].tolist() if not holding.empty else [entry_open]
        lows = holding["low"].tolist() if not holding.empty else [entry_open]
        close = float(holding.iloc[-1]["close"]) if not holding.empty else entry_open
        terminal = _pct(close, entry_open)
    mfe = round((max(highs) / entry_open - 1.0) * 100.0, 2)
    mae = round((min(lows) / entry_open - 1.0) * 100.0, 2)
    row.update(
        {
            "terminal_return": terminal,
            "mfe": mfe,
            "mae": mae,
            "peak_giveback": round(mfe - terminal, 2),
            "profit_capture": round(terminal / mfe, 4) if mfe > 0 else None,
            "holding_days": held_days,
            "holding_weeks": round(held_days / 5.0, 1),
        }
    )
    if exit_date is None or exit_open is None:
        valuation_date = pd.Timestamp(holding.index[-1]).normalize() if not holding.empty else None
        row.update(
            {
                "terminal_valuation_date": valuation_date.strftime("%Y-%m-%d") if valuation_date is not None else None,
                "terminal_valuation_price": float(holding.iloc[-1]["close"]) if not holding.empty else None,
                "terminal_valuation_source": "RepositoryV2DailyLoader.close" if not holding.empty else None,
                "terminal_valuation_at_cutoff": bool(valuation_date == pd.Timestamp(valuation_end).normalize())
                if valuation_date is not None
                else False,
            }
        )


def _refresh_lifecycle_settlement_metrics(
    row: dict[str, Any],
    daily: pd.DataFrame,
    entry_date: pd.Timestamp,
    entry_open: float,
    settlement_date: pd.Timestamp,
    settlement_price: float,
) -> None:
    """Value a position at its cash settlement without inventing an exchange OPEN."""
    held = daily[(daily.index >= entry_date) & (daily.index <= settlement_date)]
    highs = held["high"].tolist() if not held.empty else [entry_open]
    lows = held["low"].tolist() if not held.empty else [entry_open]
    highs.append(settlement_price)
    lows.append(settlement_price)
    terminal = _pct(settlement_price, entry_open)
    mfe = round((max(highs) / entry_open - 1.0) * 100.0, 2)
    mae = round((min(lows) / entry_open - 1.0) * 100.0, 2)
    held_days = int(len(held))
    row.update(
        {
            "terminal_return": terminal,
            "mfe": mfe,
            "mae": mae,
            "peak_giveback": round(mfe - terminal, 2),
            "profit_capture": round(terminal / mfe, 4) if mfe > 0 else None,
            "holding_days": held_days,
            "holding_weeks": round(held_days / 5.0, 1),
        }
    )


def _apply_lifecycle_settlement(
    row: Mapping[str, Any],
    *,
    segment: IdentitySegment,
    evidence: Sequence[Mapping[str, Any]],
    cutoff_date: pd.Timestamp,
    daily: pd.DataFrame,
) -> tuple[dict[str, Any], bool]:
    """Apply the single confirmed lifecycle event for this stable security before cutoff."""
    settled_row = dict(row)
    matches = [
        record
        for record in evidence
        if str(record.get("isu_cd", "")).strip().upper() == segment.stable_security_id
    ]
    if not matches:
        return settled_row, False
    if len(matches) != 1:
        raise RuntimeError(
            "multiple lifecycle settlement events match stable security identity: "
            f"isu_cd={segment.stable_security_id}"
        )

    settlement = matches[0]
    settlement_date = pd.Timestamp(settlement["settlement_date"]).normalize()
    if settlement_date > pd.Timestamp(cutoff_date).normalize():
        return settled_row, False
    entry_date = pd.Timestamp(settled_row["entry_execution_date"]).normalize()
    if settlement_date < entry_date:
        raise RuntimeError(
            f"lifecycle settlement predates trade entry: pair_id={settled_row.get('pair_id')}"
        )
    signal_date = settled_row.get("exit_signal_date")
    if signal_date is not None and not pd.isna(signal_date):
        if pd.Timestamp(signal_date).normalize() > settlement_date:
            raise RuntimeError(
                "signal occurs after evidenced lifecycle settlement: "
                f"pair_id={settled_row.get('pair_id')} signal={signal_date} "
                f"settlement={settlement_date:%Y-%m-%d}"
            )

    status = str(settled_row.get("trade_status") or "")
    execution_date = settled_row.get("exit_execution_date")
    if status == "REALIZED":
        if execution_date is None or pd.isna(execution_date) or not str(execution_date):
            raise RuntimeError("REALIZED trade has no market execution date before lifecycle settlement")
        if pd.Timestamp(execution_date).normalize() <= settlement_date:
            return settled_row, False
        raise RuntimeError(
            "market exit execution occurs after lifecycle settlement: "
            f"pair_id={settled_row.get('pair_id')} execution={execution_date} "
            f"settlement={settlement_date:%Y-%m-%d}"
        )
    if status not in {"OPEN_AT_CUTOFF", "UNEXECUTED_SIGNAL"}:
        raise RuntimeError(
            f"unsupported trade state for lifecycle settlement: pair_id={settled_row.get('pair_id')} "
            f"status={status}"
        )

    price = float(settlement["settlement_price"])
    _refresh_lifecycle_settlement_metrics(
        settled_row,
        daily,
        entry_date,
        float(settled_row["entry_open"]),
        settlement_date,
        price,
    )
    settled_row.update(
        {
            "trade_status": "LIFECYCLE_SETTLED",
            "terminal_reason": str(settlement["terminal_reason"]),
            "settlement_date": settlement_date.strftime("%Y-%m-%d"),
            "settlement_price": price,
            "settlement_type": str(settlement["settlement_type"]),
            "settlement_source": str(settlement["settlement_source"]),
            "terminal_valuation_date": settlement_date.strftime("%Y-%m-%d"),
            "terminal_valuation_price": price,
            "terminal_valuation_source": str(settlement["settlement_source"]),
            "terminal_valuation_at_cutoff": False,
            "exit_execution_date": None,
            "exit_price": None,
            "execution_support_missing": False,
        }
    )
    if "incremental_soft_exit" in settled_row:
        settled_row["incremental_soft_exit"] = False
    return settled_row, True


def _candidate_trade(
    base: Mapping[str, Any],
    *,
    pair_id: str,
    segment: IdentitySegment,
    daily: pd.DataFrame,
    stage_timeline: Mapping[pd.Timestamp, str],
    window: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    entry_date = pd.Timestamp(base["entry_execution_date"]).normalize()
    entry_signal_date = pd.Timestamp(base["entry_signal_date"]).normalize()
    entry_open = float(base["entry_open"])
    progressed_raw = base.get("first_progressed_effective_trading_date")
    progressed_date = pd.Timestamp(progressed_raw).normalize() if progressed_raw else None
    control_signal_raw = base.get("exit_signal_date")
    control_signal = pd.Timestamp(control_signal_raw).normalize() if control_signal_raw else None
    control_effective_signal = _effective_eod_for_signal(daily, control_signal, window.effective_end)

    row = dict(base)
    row.update(
        {
            "pair_id": pair_id,
            "isu_cd": segment.isu_cd,
            "identity_effective_from": segment.effective_from.strftime("%Y-%m-%d"),
            "identity_effective_to": segment.effective_to.strftime("%Y-%m-%d"),
            "strategy_id": CANDIDATE_STRATEGY_ID,
            "holding_days": None,
            "candidate_action": "CONTROL_PRESERVED",
            "weak_protect_eod_events": 0,
            "post_progressed_neg40_touch_eod_events": 0,
            "soft_signal_return": None,
            "incremental_soft_exit": False,
            "execution_support_missing": False,
            "stage_asof_date_at_signal": None,
            "repository_v2_last_actual_date": pd.Timestamp(daily.index.max()).strftime("%Y-%m-%d"),
        }
    )

    evaluation_rows = daily[(daily.index >= entry_date) & (daily.index <= window.effective_end)]
    touch_trade = False
    protect_trade = False
    current_stage = str(base.get("entry_pattern_a_stage") or "UNAVAILABLE").upper()
    stage_dates = sorted(date for date in stage_timeline if date >= entry_signal_date)
    stage_pos = 0
    pending_control_exit = False
    deferred_control_exit = False
    signal_date: pd.Timestamp | None = None
    signal_type: str | None = None
    signal_action: str | None = None
    signal_return: float | None = None
    signal_stage_asof: pd.Timestamp | None = None
    soft_events: list[dict[str, Any]] = []

    for date, daily_row in evaluation_rows.iterrows():
        date = pd.Timestamp(date).normalize()
        while stage_pos < len(stage_dates) and stage_dates[stage_pos] <= date:
            signal_stage_asof = stage_dates[stage_pos]
            current_stage = stage_timeline[signal_stage_asof]
            stage_pos += 1
        if control_effective_signal is not None and date >= control_effective_signal:
            pending_control_exit = True

        progressed = progressed_date is not None and date >= progressed_date
        close_return = _pct(float(daily_row["close"]), entry_open)
        at_neg40 = progressed and close_return <= -40.0
        if at_neg40:
            touch_trade = True
            row["post_progressed_neg40_touch_eod_events"] += 1
            if current_stage == "WEAK":
                protect_trade = True
                row["weak_protect_eod_events"] += 1
                soft_events.append(
                    {
                        "trade_id": str(base["trade_id"]),
                        "pair_id": pair_id,
                        "ticker": str(base["ticker"]).zfill(6),
                        "date": date.strftime("%Y-%m-%d"),
                        "close_return": close_return,
                        "pattern_a_stage": current_stage,
                        "event_type": "WEAK_PROTECT",
                        "execution_date": None,
                        "execution_open": None,
                    }
                )
                # A qualifying WEAK protection defers an already-triggered V2
                # exit. It is reconsidered at each later EOD, never erased.
                if pending_control_exit:
                    deferred_control_exit = True
                continue
            if current_stage == "UNAVAILABLE":
                raise RuntimeError(
                    f"Pattern A stage unavailable at eligible NEG40 date {date.date()} for {pair_id}"
                )
            soft_execution_date = _next_local_session(daily, date, window.execution_support)
            soft_execution_open = (
                float(daily.loc[soft_execution_date, "open"])
                if soft_execution_date is not None
                else None
            )
            soft_events.append(
                {
                    "trade_id": str(base["trade_id"]),
                    "pair_id": pair_id,
                    "ticker": str(base["ticker"]).zfill(6),
                    "date": date.strftime("%Y-%m-%d"),
                    "close_return": close_return,
                    "pattern_a_stage": current_stage,
                    "event_type": "SOFT_EXIT_SIGNAL",
                    "execution_date": (
                        soft_execution_date.strftime("%Y-%m-%d")
                        if soft_execution_date is not None
                        else None
                    ),
                    "execution_open": soft_execution_open,
                }
            )
            signal_date = date
            signal_type = "SOFT_EXIT_NEG40_NON_WEAK"
            signal_action = "SOFT_EXIT"
            signal_return = close_return
            break

        if pending_control_exit:
            signal_date = date if deferred_control_exit else control_signal
            signal_type = str(base["exit_type"])
            signal_action = "DEFERRED_CONTROL_EXIT" if deferred_control_exit else "CONTROL_EXIT"
            break

    diagnostics = {
        "pair_id": pair_id,
        "post_progressed_neg40_touch": touch_trade,
        "weak_protect_trade": protect_trade,
        "weak_protect_eod_events": int(row["weak_protect_eod_events"]),
        "post_progressed_neg40_touch_eod_events": int(row["post_progressed_neg40_touch_eod_events"]),
        "soft_signal": signal_action == "SOFT_EXIT",
        "soft_events": soft_events,
    }

    if signal_date is None:
        if deferred_control_exit:
            row["control_exit_type"] = base.get("exit_type")
            row["control_exit_signal_date"] = control_signal_raw
            row["control_exit_execution_date"] = base.get("exit_execution_date")
            row["exit_type"] = "OPEN_AT_CUTOFF_WEAK_PROTECT"
            row["exit_signal_date"] = None
            row["exit_execution_date"] = None
            row["exit_price"] = None
            row["trade_status"] = "OPEN_AT_CUTOFF"
            row["candidate_action"] = "WEAK_PROTECT_HOLD_OPEN"
            _refresh_outcome_metrics(row, daily, entry_date, entry_open, window.effective_end)
            diagnostics["deferred_control_exit_open_at_cutoff"] = True
            diagnostics["incremental_soft_exit"] = False
            return row, diagnostics
        # No candidate action changed the outcome: preserve the baseline row.
        row["holding_days"] = int(len(daily[(daily.index >= entry_date) & (daily.index <= window.effective_end)]))
        diagnostics["incremental_soft_exit"] = False
        return row, diagnostics

    execution_date = _next_local_session(daily, signal_date, window.execution_support)
    row["exit_signal_date"] = signal_date.strftime("%Y-%m-%d")
    row["exit_type"] = signal_type
    row["candidate_action"] = signal_action
    row["stage_asof_date_at_signal"] = (
        signal_stage_asof.strftime("%Y-%m-%d") if signal_stage_asof is not None else None
    )
    row["soft_signal_return"] = signal_return
    if execution_date is None:
        row["exit_execution_date"] = None
        row["exit_price"] = None
        row["trade_status"] = "UNEXECUTED_SIGNAL"
        row["execution_support_missing"] = True
        terminal_rows = daily[(daily.index >= entry_date) & (daily.index <= window.effective_end)]
        if terminal_rows.empty:
            raise RuntimeError(
                "UNEXECUTED_SIGNAL cannot be valued from Repository V2 through the window cutoff: "
                f"pair_id={pair_id} ticker={base['ticker']} signal_date={signal_date:%Y-%m-%d}"
            )
        terminal_date = pd.Timestamp(terminal_rows.index[-1]).normalize()
        row["terminal_valuation_date"] = terminal_date.strftime("%Y-%m-%d")
        row["terminal_valuation_price"] = float(terminal_rows.iloc[-1]["close"])
        row["terminal_valuation_source"] = "RepositoryV2DailyLoader.close"
        row["terminal_valuation_at_cutoff"] = terminal_date == window.effective_end
        _refresh_outcome_metrics(row, daily, entry_date, entry_open, window.effective_end)
        diagnostics["incremental_soft_exit"] = signal_action == "SOFT_EXIT"
        diagnostics["execution_support_missing"] = True
        return row, diagnostics

    exit_open = float(daily.loc[execution_date, "open"])
    row["exit_execution_date"] = execution_date.strftime("%Y-%m-%d")
    row["exit_price"] = round(exit_open, 2)
    row["trade_status"] = "REALIZED"
    _refresh_outcome_metrics(
        row,
        daily,
        entry_date,
        entry_open,
        window.effective_end,
        exit_date=execution_date,
        exit_open=exit_open,
    )
    diagnostics["incremental_soft_exit"] = bool(
        signal_action == "SOFT_EXIT"
        and (
            row["exit_execution_date"] != base.get("exit_execution_date")
            or not np.isclose(
                float(row["terminal_return"]),
                float(base["terminal_return"]),
                atol=0.005,
                rtol=0,
            )
            or base.get("trade_status") != "REALIZED"
        )
    )
    row["incremental_soft_exit"] = diagnostics["incremental_soft_exit"]
    return row, diagnostics


def _assert_entry_executions_within_effective_end(
    frame: pd.DataFrame,
    effective_end: pd.Timestamp,
    *,
    source: str,
) -> None:
    if frame.empty:
        return
    cutoff = pd.Timestamp(effective_end).normalize()
    late = pd.to_datetime(frame["entry_execution_date"]).dt.normalize() > cutoff
    if late.any():
        fields = [
            column
            for column in ("pair_id", "trade_id", "ticker", "entry_execution_date")
            if column in frame.columns
        ]
        examples = frame.loc[late, fields].head(5).to_dict(orient="records")
        raise RuntimeError(
            f"{source} contains {int(late.sum())} entry execution(s) after effective_end "
            f"({cutoff.date()}): {examples}"
        )


def _process_ticker(ticker: str, run: RunContext) -> dict[str, Any]:
    started = time.perf_counter()
    control_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    segments_seen = 0
    repository_load_count = 0

    raw_window_end = getattr(run.window, "effective_end", None)
    raw_execution_support = getattr(run.window, "execution_support", None)
    if raw_window_end is None or raw_execution_support is None:
        raise RuntimeError(
            "standard backtest runner requires explicit window effective_end and execution support"
        )
    window_effective_end = pd.Timestamp(raw_window_end).normalize()
    window_execution_support = pd.Timestamp(raw_execution_support).normalize()
    if window_execution_support < window_effective_end:
        raise RuntimeError("standard backtest runner execution support precedes window effective_end")

    for segment in run.segments_by_ticker[ticker]:
        scoped_loader = RepositoryV2DailyLoader(
            run.loader.repository,
            start=segment.effective_from,
            end=window_execution_support,
        )
        daily = scoped_loader.load(ticker)
        repository_load_count += scoped_loader.load_count
        if daily is None or daily.empty:
            raise RuntimeError(f"no Repository V2 rows through the window support for {segment.key}")
        daily = daily.sort_index()

        ticker_context = v2.build_precomputed_ticker_context(ticker, ticker, daily)
        entry_eligibility_cutoff = _common_entry_eligibility_cutoff(
            segment,
            window_effective_end,
        )
        if entry_eligibility_cutoff > window_effective_end:
            raise RuntimeError("standard backtest runner entry eligibility exceeds window effective_end")
        base_records = v2.simulate_ticker_core_v02_reentry(
            ticker=ticker,
            name=ticker,
            market=segment.market,
            daily=daily,
            score_contract=run.score_contract,
            stage_contract=run.stage_contract,
            cutoff_date=window_effective_end,
            snapshot_context=ticker_context,
            market_calendar=run.calendar,
            entry_search_start=run.window.effective_start,
            signal_cutoff_date=window_effective_end,
            execution_support_date=window_execution_support,
            strict_errors=True,
            entry_execution_cutoff_date=entry_eligibility_cutoff,
            entry_signal_cutoff_date=entry_eligibility_cutoff,
        )
        stage_timeline: dict[pd.Timestamp, str] = {}
        if any(record.first_progressed_effective_trading_date for record in base_records):
            stage_timeline = _stage_timeline(
                daily,
                ticker_context,
                run.window.effective_start,
                run.window.effective_end,
                run.calendar,
            )

        for record in base_records:
            base = record.to_dict()
            expected_entry = _next_local_session(
                daily,
                pd.Timestamp(record.entry_signal_date).normalize(),
                run.window.execution_support,
            )
            if expected_entry is None or expected_entry.strftime("%Y-%m-%d") != record.entry_execution_date:
                raise RuntimeError(f"V2 entry is not next local-session OPEN for {segment.key}/{record.trade_id}")
            if record.exit_signal_date and record.exit_execution_date:
                expected_exit = _next_local_session(
                    daily,
                    pd.Timestamp(record.exit_signal_date).normalize(),
                    run.window.execution_support,
                )
                if expected_exit is None or expected_exit.strftime("%Y-%m-%d") != record.exit_execution_date:
                    raise RuntimeError(f"V2 exit is not next local-session OPEN for {segment.key}/{record.trade_id}")
            pair_id = f"{segment.key}|{record.trade_id}"
            base_row = dict(base)
            base_row.update(
                {
                    "pair_id": pair_id,
                    "isu_cd": segment.isu_cd,
                    "identity_effective_from": segment.effective_from.strftime("%Y-%m-%d"),
                    "identity_effective_to": segment.effective_to.strftime("%Y-%m-%d"),
                    "strategy_id": V2_STRATEGY_ID,
                    "holding_days": int(
                        len(
                            daily[
                                (daily.index >= pd.Timestamp(record.entry_execution_date))
                                & (
                                    daily.index
                                    <= (
                                        pd.Timestamp(record.exit_execution_date)
                                        if record.exit_execution_date
                                        else run.window.effective_end
                                    )
                                )
                            ]
                        )
                    ),
                }
            )
            if str(base_row.get("trade_status") or "").startswith("OPEN"):
                terminal_rows = daily[
                    (daily.index >= pd.Timestamp(record.entry_execution_date))
                    & (daily.index <= run.window.effective_end)
                ]
                valuation_date = pd.Timestamp(terminal_rows.index[-1]).normalize() if not terminal_rows.empty else None
                base_row.update(
                    {
                        "terminal_valuation_date": valuation_date.strftime("%Y-%m-%d") if valuation_date is not None else None,
                        "terminal_valuation_price": float(terminal_rows.iloc[-1]["close"]) if not terminal_rows.empty else None,
                        "terminal_valuation_source": "RepositoryV2DailyLoader.close" if not terminal_rows.empty else None,
                        "terminal_valuation_at_cutoff": bool(
                            valuation_date == run.window.effective_end.normalize()
                        ) if valuation_date is not None else False,
                    }
                )
            candidate_row, diag = _candidate_trade(
                base,
                pair_id=pair_id,
                segment=segment,
                daily=daily,
                stage_timeline=stage_timeline,
                window=run.window,
            )
            if str(candidate_row.get("trade_status") or "") == "OPEN_AT_CUTOFF":
                terminal_rows = daily[
                    (daily.index >= pd.Timestamp(record.entry_execution_date))
                    & (daily.index <= run.window.effective_end)
                ]
                valuation_date = pd.Timestamp(terminal_rows.index[-1]).normalize() if not terminal_rows.empty else None
                candidate_row.update(
                    {
                        "terminal_valuation_date": valuation_date.strftime("%Y-%m-%d") if valuation_date is not None else None,
                        "terminal_valuation_price": float(terminal_rows.iloc[-1]["close"]) if not terminal_rows.empty else None,
                        "terminal_valuation_source": "RepositoryV2DailyLoader.close" if not terminal_rows.empty else None,
                        "terminal_valuation_at_cutoff": bool(
                            valuation_date == run.window.effective_end.normalize()
                        ) if valuation_date is not None else False,
                    }
                )
            if getattr(getattr(run.window, "window", None), "window_id", None) in {"P2-2", "P3-1"}:
                settlement_cutoff = pd.Timestamp(run.window.effective_end).normalize()
                control_settled, control_was_settled = _apply_lifecycle_settlement(
                    base_row,
                    segment=segment,
                    evidence=getattr(run, "lifecycle_settlements", ()),
                    cutoff_date=settlement_cutoff,
                    daily=daily,
                )
                candidate_row, candidate_was_settled = _apply_lifecycle_settlement(
                    candidate_row,
                    segment=segment,
                    evidence=getattr(run, "lifecycle_settlements", ()),
                    cutoff_date=settlement_cutoff,
                    daily=daily,
                )
                if control_was_settled != candidate_was_settled:
                    raise RuntimeError(
                        "matched CONTROL/Candidate lifecycle settlement parity failed: "
                        f"pair_id={pair_id}"
                    )
                if candidate_was_settled:
                    diag["lifecycle_settled"] = True
                    diag["execution_support_missing"] = False
                    diag["incremental_soft_exit"] = False
                    candidate_row["incremental_soft_exit"] = False
                base_row = control_settled
            control_rows.append(base_row)
            candidate_rows.append(candidate_row)
            diagnostics.append(diag)
        segments_seen += 1

    return {
        "ticker": ticker,
        "segments_seen": segments_seen,
        "repository_load_count": repository_load_count,
        "control_rows": control_rows,
        "candidate_rows": candidate_rows,
        "diagnostics": diagnostics,
        "elapsed_seconds": time.perf_counter() - started,
    }


def _clean_csv_row(row: Mapping[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in row.items():
        if value is None or (not isinstance(value, (list, tuple, dict)) and pd.isna(value)):
            cleaned[key] = None
        else:
            cleaned[key] = value
    return cleaned


def _replay_candidate_ticker(
    ticker: str,
    source_rows: Sequence[Mapping[str, Any]],
    run: RunContext,
) -> dict[str, Any]:
    started = time.perf_counter()
    candidate_rows: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    repository_load_count = 0
    segments_seen = 0
    for segment in run.segments_by_ticker[ticker]:
        segment_rows = [
            _clean_csv_row(row)
            for row in source_rows
            if str(row.get("isu_cd")) == segment.isu_cd
            and str(row.get("identity_effective_from")) == segment.effective_from.strftime("%Y-%m-%d")
            and str(row.get("identity_effective_to")) == segment.effective_to.strftime("%Y-%m-%d")
        ]
        if not segment_rows:
            continue
        scoped_loader = RepositoryV2DailyLoader(
            run.loader.repository,
            start=segment.effective_from,
            end=run.window.execution_support,
        )
        daily = scoped_loader.load(ticker)
        repository_load_count += scoped_loader.load_count
        if daily is None or daily.empty:
            raise RuntimeError(f"no Repository V2 rows through the window support for {segment.key}")
        daily = daily.sort_index()
        ticker_context = v2.build_precomputed_ticker_context(ticker, ticker, daily)
        has_progression = any(row.get("first_progressed_effective_trading_date") for row in segment_rows)
        stage_timeline = (
            _stage_timeline(
                daily,
                ticker_context,
                run.window.effective_start,
                run.window.effective_end,
                run.calendar,
            )
            if has_progression
            else {}
        )
        for base in segment_rows:
            pair_id = str(base["pair_id"])
            expected_prefix = f"{segment.key}|"
            if not pair_id.startswith(expected_prefix):
                raise RuntimeError(f"source pair ID does not bind to COMMON identity segment: {pair_id}")
            candidate, diagnostic = _candidate_trade(
                base,
                pair_id=pair_id,
                segment=segment,
                daily=daily,
                stage_timeline=stage_timeline,
                window=run.window,
            )
            candidate_rows.append(candidate)
            diagnostics.append(diagnostic)
        segments_seen += 1
    return {
        "ticker": ticker,
        "segments_seen": segments_seen,
        "repository_load_count": repository_load_count,
        "candidate_rows": candidate_rows,
        "diagnostics": diagnostics,
        "elapsed_seconds": time.perf_counter() - started,
    }


def _metrics(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        values = pd.Series(dtype=float)
        statuses = pd.Series(dtype=str)
        holding = pd.Series(dtype=float)
    else:
        values = pd.to_numeric(frame["terminal_return"], errors="coerce").dropna()
        statuses = frame["trade_status"].fillna("").astype(str)
        holding = pd.to_numeric(frame["holding_days"], errors="coerce").dropna()
    result: dict[str, Any] = {
        "trade_count": int(len(frame)),
        "positive_count": int((values > 0).sum()),
        "positive_rate_pct": round(float((values > 0).mean() * 100), 4) if len(values) else None,
        "mean_terminal_return_pct": round(float(values.mean()), 4) if len(values) else None,
        "median_terminal_return_pct": round(float(values.median()), 4) if len(values) else None,
        "open_at_cutoff_count": int(statuses.str.startswith("OPEN").sum()),
        "holding_days_mean": round(float(holding.mean()), 4) if len(holding) else None,
        "holding_days_median": round(float(holding.median()), 4) if len(holding) else None,
        "tail_counts": {},
        "winner_counts": {},
    }
    for threshold in (30, 40, 50, 60):
        result["tail_counts"][f"le_neg_{threshold}_pct"] = int((values <= -threshold).sum())
    for threshold in (30, 50, 100):
        result["winner_counts"][f"ge_pos_{threshold}_pct"] = int((values >= threshold).sum())
    positive_values = values[values > 0].sort_values(ascending=False)
    positive_sum = float(positive_values.sum()) if len(positive_values) else 0.0
    result["top_winner_concentration"] = {}
    for n in (5, 10):
        remaining = values.drop(positive_values.head(n).index, errors="ignore")
        top_sum = float(positive_values.head(n).sum()) if len(positive_values) else 0.0
        result["top_winner_concentration"][f"top_{n}"] = {
            "mean_after_removal_pct": round(float(remaining.mean()), 4) if len(remaining) else None,
            "positive_return_contribution_pct": round(top_sum / positive_sum * 100, 4)
            if positive_sum > 0
            else None,
            "top_winner_sum_pct_points": round(top_sum, 4),
        }
    return result


def _paired_summary(control: pd.DataFrame, candidate: pd.DataFrame) -> dict[str, Any]:
    merged = control[["pair_id", "terminal_return"]].merge(
        candidate[["pair_id", "terminal_return"]], on="pair_id", suffixes=("_control", "_candidate"), validate="one_to_one"
    )
    delta = pd.to_numeric(merged["terminal_return_candidate"]) - pd.to_numeric(merged["terminal_return_control"])
    return {
        "count": int(len(merged)),
        "mean_delta_pct_points": round(float(delta.mean()), 4) if len(delta) else None,
        "median_delta_pct_points": round(float(delta.median()), 4) if len(delta) else None,
        "improved": int((delta > 0).sum()),
        "worsened": int((delta < 0).sum()),
        "same": int((delta == 0).sum()),
    }


def _outcome_date(row: Mapping[str, Any], cutoff_date: str) -> str:
    status = str(row.get("trade_status") or "")
    if status == "LIFECYCLE_SETTLED":
        settlement = row.get("settlement_date")
        if settlement is None or pd.isna(settlement) or not str(settlement):
            raise RuntimeError("LIFECYCLE_SETTLED outcome has no settlement_date")
        return str(settlement)
    if status.startswith("OPEN"):
        return cutoff_date
    execution = row.get("exit_execution_date")
    if execution is not None and not pd.isna(execution) and str(execution):
        return str(execution)
    signal = row.get("exit_signal_date")
    if signal is not None and not pd.isna(signal) and str(signal):
        return str(signal)
    return cutoff_date


def _outcome_reason(row: Mapping[str, Any]) -> str:
    status = str(row.get("trade_status") or "")
    if status == "LIFECYCLE_SETTLED":
        reason = row.get("terminal_reason")
        if reason is None or pd.isna(reason) or not str(reason):
            raise RuntimeError("LIFECYCLE_SETTLED outcome has no terminal_reason")
        return str(reason)
    if status.startswith("OPEN"):
        return "OPEN_AT_CUTOFF"
    return str(row.get("exit_type") or status or "UNKNOWN")


def _build_matched_trade_ledger(
    control: pd.DataFrame,
    candidate: pd.DataFrame,
    *,
    cutoff_date: str,
) -> pd.DataFrame:
    for name, frame in (("CONTROL", control), ("Candidate", candidate)):
        if frame["pair_id"].duplicated().any():
            raise RuntimeError(f"duplicate {name} pair_id in source trades")
    if len(control) != len(candidate):
        raise RuntimeError("CONTROL/Candidate trade count mismatch")
    if set(control["pair_id"]) != set(candidate["pair_id"]):
        raise RuntimeError("CONTROL/Candidate pair_id set mismatch")

    paired = control.merge(
        candidate,
        on="pair_id",
        suffixes=("_control", "_candidate"),
        validate="one_to_one",
    )
    if not paired["trade_id_control"].astype(str).equals(paired["trade_id_candidate"].astype(str)):
        raise RuntimeError("matched pair_id rows do not share the same trade_id")
    if not np.isclose(
        pd.to_numeric(paired["entry_open_control"]),
        pd.to_numeric(paired["entry_open_candidate"]),
        atol=0.005,
        rtol=0,
    ).all():
        raise RuntimeError("matched trade ledger entry prices differ")
    for field in ("ticker", "isu_cd", "market", "identity_effective_from", "identity_effective_to", "entry_execution_date"):
        left = paired[f"{field}_control"].fillna("").astype(str)
        right = paired[f"{field}_candidate"].fillna("").astype(str)
        if not left.equals(right):
            raise RuntimeError(f"matched trade ledger identity/entry field differs: {field}")

    records: list[dict[str, Any]] = []
    for row in paired.to_dict(orient="records"):
        control_return = float(row["terminal_return_control"])
        candidate_return = float(row["terminal_return_candidate"])
        records.append(
            {
                "trade_id": str(row["trade_id_control"]),
                "pair_id": str(row["pair_id"]),
                "ticker": str(row["ticker_control"]).zfill(6),
                "identity": "|".join(
                    (
                        str(row["isu_cd_control"]),
                        str(row["market_control"]),
                        str(row["identity_effective_from_control"]),
                        str(row["identity_effective_to_control"]),
                    )
                ),
                "entry_date": str(row["entry_execution_date_control"]),
                "entry_signal_date": str(row["entry_signal_date_control"]),
                "entry_open": float(row["entry_open_control"]),
                "control_exit_or_cutoff_date": _outcome_date(
                    {key.removesuffix("_control"): value for key, value in row.items() if key.endswith("_control")},
                    cutoff_date,
                ),
                "control_exit_reason": _outcome_reason(
                    {key.removesuffix("_control"): value for key, value in row.items() if key.endswith("_control")}
                ),
                "control_terminal_return": control_return,
                "control_holding_days": int(row["holding_days_control"]),
                "control_open_at_cutoff": str(row["trade_status_control"]).startswith("OPEN"),
                "candidate_exit_or_cutoff_date": _outcome_date(
                    {key.removesuffix("_candidate"): value for key, value in row.items() if key.endswith("_candidate")},
                    cutoff_date,
                ),
                "candidate_exit_reason": _outcome_reason(
                    {key.removesuffix("_candidate"): value for key, value in row.items() if key.endswith("_candidate")}
                ),
                "candidate_terminal_return": candidate_return,
                "candidate_holding_days": int(row["holding_days_candidate"]),
                "candidate_open_at_cutoff": str(row["trade_status_candidate"]).startswith("OPEN"),
                "candidate_soft_exit": (
                    str(row["candidate_action"]) == "SOFT_EXIT"
                    and str(row["trade_status_candidate"]) == "REALIZED"
                ),
                "paired_delta": round(candidate_return - control_return, 8),
                "control_trade_status": str(row["trade_status_control"]),
                "candidate_trade_status": str(row["trade_status_candidate"]),
                "candidate_action": str(row["candidate_action"]),
                "control_terminal_reason": row.get("terminal_reason_control"),
                "control_settlement_date": row.get("settlement_date_control"),
                "control_settlement_price": row.get("settlement_price_control"),
                "control_settlement_type": row.get("settlement_type_control"),
                "control_settlement_source": row.get("settlement_source_control"),
                "candidate_terminal_reason": row.get("terminal_reason_candidate"),
                "candidate_settlement_date": row.get("settlement_date_candidate"),
                "candidate_settlement_price": row.get("settlement_price_candidate"),
                "candidate_settlement_type": row.get("settlement_type_candidate"),
                "candidate_settlement_source": row.get("settlement_source_candidate"),
            }
        )
    ledger = pd.DataFrame(records).sort_values(["ticker", "entry_date", "pair_id"], kind="mergesort").reset_index(drop=True)
    if ledger["pair_id"].duplicated().any() or len(ledger) != len(control):
        raise RuntimeError("matched trade ledger is not one-row-per-trade")
    return ledger


def _add_p3_1_ledger_contract_fields(ledger: pd.DataFrame) -> pd.DataFrame:
    """Add the required pair-level status/reason fields while retaining side-level detail."""
    required = {
        "control_trade_status",
        "candidate_trade_status",
        "control_exit_reason",
        "candidate_exit_reason",
    }
    if not required.issubset(ledger.columns):
        raise RuntimeError(f"P3-1 ledger is missing required side fields: {sorted(required - set(ledger.columns))}")

    def value_or_fallback(row: pd.Series, primary: str, fallback: str) -> str:
        value = row.get(primary)
        if value is None or pd.isna(value) or not str(value):
            value = row.get(fallback)
        return str(value or "UNKNOWN")

    result = ledger.copy()
    result["trade_status"] = result.apply(
        lambda row: (
            f"CONTROL={row['control_trade_status']};"
            f"CANDIDATE={row['candidate_trade_status']}"
        ),
        axis=1,
    )
    result["terminal_reason"] = result.apply(
        lambda row: (
            f"CONTROL={value_or_fallback(row, 'control_terminal_reason', 'control_exit_reason')};"
            f"CANDIDATE={value_or_fallback(row, 'candidate_terminal_reason', 'candidate_exit_reason')}"
        ),
        axis=1,
    )
    return result


def _ledger_aggregates(ledger: pd.DataFrame) -> dict[str, Any]:
    control = pd.DataFrame(
        {
            "pair_id": ledger["pair_id"],
            "terminal_return": pd.to_numeric(ledger["control_terminal_return"]),
            "holding_days": pd.to_numeric(ledger["control_holding_days"]),
            "trade_status": ledger["control_open_at_cutoff"].map(
                lambda value: "OPEN_AT_CUTOFF" if bool(value) else "REALIZED"
            ),
        }
    )
    candidate = pd.DataFrame(
        {
            "pair_id": ledger["pair_id"],
            "terminal_return": pd.to_numeric(ledger["candidate_terminal_return"]),
            "holding_days": pd.to_numeric(ledger["candidate_holding_days"]),
            "trade_status": ledger["candidate_open_at_cutoff"].map(
                lambda value: "OPEN_AT_CUTOFF" if bool(value) else "REALIZED"
            ),
        }
    )
    return {
        "control": _metrics(control),
        "candidate": _metrics(candidate),
        "paired": _paired_summary(control, candidate),
    }


def _soft_event_failure_context(
    event: Mapping[str, Any],
    candidate_row: Mapping[str, Any] | None,
) -> str:
    candidate_row = candidate_row or {}
    identity = "|".join(
        str(candidate_row.get(field) or "")
        for field in ("isu_cd", "market", "identity_effective_from", "identity_effective_to")
    )
    return (
        f"pair_id={event.get('pair_id')} trade_id={event.get('trade_id')} "
        f"ticker={event.get('ticker')} signal_date={event.get('date')} "
        f"close_return={event.get('close_return')} stage={event.get('pattern_a_stage')} "
        f"identity={identity or 'UNKNOWN'} "
        f"segment_end={candidate_row.get('identity_effective_to')} "
        f"repository_v2_last_actual_date={candidate_row.get('repository_v2_last_actual_date')} "
        f"candidate_status={candidate_row.get('trade_status')} "
        f"execution_support_missing={candidate_row.get('execution_support_missing')} "
        f"terminal_valuation_date={candidate_row.get('terminal_valuation_date')} "
        f"terminal_valuation_at_cutoff={candidate_row.get('terminal_valuation_at_cutoff')}"
    )


def _build_soft_event_ledger(
    trade_diagnostics: Sequence[Mapping[str, Any]],
    candidate: pd.DataFrame,
    *,
    run: RunContext | None = None,
) -> pd.DataFrame:
    columns = [
        "trade_id",
        "pair_id",
        "ticker",
        "date",
        "close_return",
        "pattern_a_stage",
        "event_type",
        "execution_date",
        "execution_open",
    ]
    rows = [
        event
        for diagnostic in trade_diagnostics
        for event in diagnostic.get("soft_events", [])
    ]
    events = pd.DataFrame(rows, columns=columns)
    if events.empty:
        return events
    if candidate["pair_id"].duplicated().any():
        raise RuntimeError("duplicate Candidate pair_id before soft-event ledger build")

    events = events.sort_values(
        ["ticker", "date", "pair_id", "event_type"], kind="mergesort"
    ).reset_index(drop=True)
    if events.duplicated(["pair_id", "date", "event_type"]).any():
        raise RuntimeError("duplicate soft event for one trade/date/type")
    if not set(events["pair_id"]).issubset(set(candidate["pair_id"])):
        raise RuntimeError("soft event trade is absent from matched Candidate trades")
    candidate_by_pair = {
        str(row["pair_id"]): row
        for row in candidate.to_dict(orient="records")
    }
    if run is not None:
        effective_start = run.window.effective_start.normalize()
        effective_end = run.window.effective_end.normalize()
        execution_support = run.window.execution_support.normalize()
        trading_dates = pd.DatetimeIndex(run.calendar.trading_dates).normalize()
        for event in events.to_dict(orient="records"):
            signal_date = pd.Timestamp(event["date"]).normalize()
            if signal_date < effective_start or signal_date > effective_end:
                raise RuntimeError(f"soft event lies outside the selected window: {event}")
            if event["event_type"] != "SOFT_EXIT_SIGNAL":
                continue
            if pd.isna(event["execution_date"]) or pd.isna(event["execution_open"]):
                if run.window.window.window_id == "P3-1":
                    raise RuntimeError(f"P3-1 SOFT_EXIT lacks required execution support: {event}")
                continue
            execution_date = pd.Timestamp(event["execution_date"]).normalize()
            next_dates = trading_dates[trading_dates > signal_date]
            if not len(next_dates) or next_dates[0] > execution_support:
                raise RuntimeError(f"SOFT_EXIT has no next local-session support: {event}")
            if execution_date != next_dates[0]:
                raise RuntimeError(f"SOFT_EXIT execution is not the next local session: {event}")
            execution_open = float(event["execution_open"])
            if not np.isfinite(execution_open) or execution_open <= 0:
                raise RuntimeError(f"SOFT_EXIT lacks a valid Repository V2 OPEN: {event}")
    if not (pd.to_numeric(events["close_return"]) <= -40.0).all():
        raise RuntimeError("soft event does not satisfy the frozen NEG40 threshold")

    weak = events[events["event_type"].eq("WEAK_PROTECT")]
    soft = events[events["event_type"].eq("SOFT_EXIT_SIGNAL")]
    if len(weak) + len(soft) != len(events):
        raise RuntimeError("unknown soft event type")
    if not weak["pattern_a_stage"].eq("WEAK").all():
        raise RuntimeError("WEAK_PROTECT event has a non-WEAK stage")
    if soft["pattern_a_stage"].eq("WEAK").any():
        raise RuntimeError("SOFT_EXIT_SIGNAL occurred during WEAK protection")
    missing_execution = soft[["execution_date", "execution_open"]].isna().any(axis=1)
    unsupported_missing_execution = []
    settlement_fields = (
        "terminal_reason",
        "settlement_date",
        "settlement_price",
        "settlement_type",
        "settlement_source",
    )
    for event in soft.loc[missing_execution].to_dict(orient="records"):
        candidate_row = candidate_by_pair.get(str(event["pair_id"]), {})
        has_confirmed_terminal = (
            candidate_row.get("trade_status") == "LIFECYCLE_SETTLED"
            and not bool(candidate_row.get("execution_support_missing"))
            and all(
                candidate_row.get(field) is not None
                and not pd.isna(candidate_row.get(field))
                and str(candidate_row.get(field))
                for field in settlement_fields
            )
            and pd.Timestamp(candidate_row["settlement_date"])
            >= pd.Timestamp(event["date"])
            and not bool(candidate_row.get("terminal_valuation_at_cutoff"))
        )
        if not has_confirmed_terminal:
            unsupported_missing_execution.append(event)
    if unsupported_missing_execution:
        details = [
            _soft_event_failure_context(
                event,
                candidate_by_pair.get(str(event.get("pair_id"))),
            )
            for event in unsupported_missing_execution
        ]
        raise RuntimeError(
            "SOFT_EXIT_SIGNAL lacks complete next-session execution support; "
            "UNEXECUTED_SIGNAL is not accepted until its no-session cause and terminal valuation are verified; "
            "a lifecycle-settled trade must have complete settlement provenance: "
            + "; ".join(details)
        )

    candidate_soft = candidate[candidate["candidate_action"].eq("SOFT_EXIT")]
    if len(soft) != len(candidate_soft):
        raise RuntimeError("soft event count differs from final Candidate SOFT_EXIT count")
    if len(soft):
        paired = soft.merge(
            candidate_soft[
                ["pair_id", "trade_id", "exit_signal_date", "exit_execution_date", "exit_price"]
            ],
            on="pair_id",
            validate="one_to_one",
        )
        if not (
            paired["trade_id_x"].astype(str).equals(paired["trade_id_y"].astype(str))
            and paired["date"].astype(str).equals(paired["exit_signal_date"].astype(str))
            and paired["execution_date"].astype(str).equals(
                paired["exit_execution_date"].astype(str)
            )
        ):
            raise RuntimeError("soft event signal/execution dates differ from Candidate trade")
        executed = paired["execution_open"].notna() & paired["exit_price"].notna()
        if not np.isclose(
            pd.to_numeric(paired.loc[executed, "execution_open"]),
            pd.to_numeric(paired.loc[executed, "exit_price"]),
            atol=0.005,
            rtol=0,
        ).all():
            raise RuntimeError("soft event execution OPEN differs from Candidate exit price")
    return events


def _comparison_effects(
    control: Mapping[str, Any],
    candidate: Mapping[str, Any],
    paired: Mapping[str, Any],
) -> dict[str, float]:
    return {
        "mean_paired_delta_pct_points": float(paired["mean_delta_pct_points"]),
        "median_paired_delta_pct_points": float(paired["median_delta_pct_points"]),
        "positive_count_delta": float(candidate["positive_count"] - control["positive_count"]),
        "le_neg_40_count_delta": float(
            candidate["tail_counts"]["le_neg_40_pct"] - control["tail_counts"]["le_neg_40_pct"]
        ),
        "le_neg_50_count_delta": float(
            candidate["tail_counts"]["le_neg_50_pct"] - control["tail_counts"]["le_neg_50_pct"]
        ),
        "le_neg_60_count_delta": float(
            candidate["tail_counts"]["le_neg_60_pct"] - control["tail_counts"]["le_neg_60_pct"]
        ),
        "ge_pos_50_count_delta": float(
            candidate["winner_counts"]["ge_pos_50_pct"] - control["winner_counts"]["ge_pos_50_pct"]
        ),
        "ge_pos_100_count_delta": float(
            candidate["winner_counts"]["ge_pos_100_pct"] - control["winner_counts"]["ge_pos_100_pct"]
        ),
        "paired_improved_minus_worsened": float(paired["improved"] - paired["worsened"]),
    }


def _compare_p2_1_directions(
    control: Mapping[str, Any],
    candidate: Mapping[str, Any],
    paired: Mapping[str, Any],
) -> dict[str, Any]:
    if not P2_1_LEDGER_SUMMARY_PATH.exists():
        raise RuntimeError(f"missing final P2-1 comparison summary: {P2_1_LEDGER_SUMMARY_PATH}")
    baseline = json.loads(P2_1_LEDGER_SUMMARY_PATH.read_text(encoding="utf-8"))
    if baseline.get("status") != "COMPLETE" or baseline.get("window_id") != "P2-1":
        raise RuntimeError("P2-1 comparison input is not the completed fix02 summary")
    p2_1 = baseline["ledger"]["aggregates_recomputed_from_full_ledger"]
    p2_1_effects = _comparison_effects(p2_1["control"], p2_1["candidate"], p2_1["paired"])
    p2_2_effects = _comparison_effects(control, candidate, paired)
    directions: dict[str, str] = {}
    agreements = 0
    disagreements = 0
    indeterminate = 0
    for key, prior_value in p2_1_effects.items():
        current_value = p2_2_effects[key]
        if prior_value == 0.0 or current_value == 0.0:
            directions[key] = "ZERO_OR_CHANGED_FROM_ZERO"
            indeterminate += 1
        elif (prior_value > 0) == (current_value > 0):
            directions[key] = "AGREES"
            agreements += 1
        else:
            directions[key] = "DISAGREES"
            disagreements += 1

    if indeterminate == 0 and disagreements == 0 and agreements:
        overall = "일치"
    elif indeterminate == 0 and agreements == 0 and disagreements:
        overall = "불일치"
    else:
        overall = "부분 일치"
    return {
        "basis": "summary metrics only; P2-1 and P2-2 populations are not treated as a shared cohort",
        "p2_1_effects": p2_1_effects,
        "p2_2_effects": p2_2_effects,
        "metric_directions": directions,
        "overall_direction": overall,
    }


def _compare_p3_1_directions(
    control: Mapping[str, Any],
    candidate: Mapping[str, Any],
    paired: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare only the direction of P3-1 effects with completed P2 windows."""
    p2_paths = {
        "P2-1": P2_1_LEDGER_SUMMARY_PATH,
        "P2-2": P2_2_LEDGER_SUMMARY_PATH,
    }
    prior_effects: dict[str, dict[str, float]] = {}
    for window_id, path in p2_paths.items():
        if not path.is_file():
            raise RuntimeError(f"missing completed {window_id} comparison summary: {path}")
        summary = json.loads(path.read_text(encoding="utf-8"))
        if summary.get("status") != "COMPLETE" or summary.get("window_id") != window_id:
            raise RuntimeError(f"{window_id} comparison input is not a completed matching window")
        aggregates = summary.get("ledger", {}).get("aggregates_recomputed_from_full_ledger")
        if not isinstance(aggregates, Mapping):
            raise RuntimeError(f"{window_id} summary lacks ledger-recomputed aggregates")
        prior_effects[window_id] = _comparison_effects(
            aggregates["control"], aggregates["candidate"], aggregates["paired"]
        )

    current_effects = _comparison_effects(control, candidate, paired)
    directions: dict[str, str] = {}
    agreements = disagreements = split_or_zero = 0
    for key, current in current_effects.items():
        p2_1 = prior_effects["P2-1"][key]
        p2_2 = prior_effects["P2-2"][key]
        if p2_1 == 0.0 or p2_2 == 0.0 or (p2_1 > 0) != (p2_2 > 0) or current == 0.0:
            directions[key] = "P2_WINDOWS_SPLIT_OR_ZERO"
            split_or_zero += 1
        elif (current > 0) == (p2_1 > 0):
            directions[key] = "AGREES_WITH_BOTH_P2_WINDOWS"
            agreements += 1
        else:
            directions[key] = "DISAGREES_WITH_BOTH_P2_WINDOWS"
            disagreements += 1

    if split_or_zero == 0 and disagreements == 0 and agreements:
        overall = "P2 방향성과 일치"
    elif split_or_zero == 0 and agreements == 0 and disagreements:
        overall = "P2 방향성과 불일치"
    else:
        overall = "P2 방향성과 부분 일치"
    return {
        "basis": "effect directions only; P3-1 and P2 windows are independent populations, not a shared cohort",
        "p2_1_effects": prior_effects["P2-1"],
        "p2_2_effects": prior_effects["P2-2"],
        "p3_1_effects": current_effects,
        "metric_directions": directions,
        "metric_direction_counts": {
            "agrees_with_both_p2_windows": agreements,
            "disagrees_with_both_p2_windows": disagreements,
            "p2_windows_split_or_zero": split_or_zero,
        },
        "overall_direction": overall,
    }


def _nested_values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return set(left) == set(right) and all(_nested_values_equal(left[key], right[key]) for key in left)
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if isinstance(left, (int, float, np.number)) and isinstance(right, (int, float, np.number)):
        if pd.isna(left) and pd.isna(right):
            return True
        return bool(np.isclose(float(left), float(right), atol=1e-8, rtol=0))
    return left == right


def _validate_results(
    control: pd.DataFrame,
    candidate: pd.DataFrame,
    run: RunContext,
) -> dict[str, Any]:
    if control["pair_id"].duplicated().any() or candidate["pair_id"].duplicated().any():
        raise RuntimeError("duplicate matched pair_id found")
    if set(control["pair_id"]) != set(candidate["pair_id"]):
        raise RuntimeError("CONTROL/Candidate entry population mismatch")
    pairs = control.merge(candidate, on="pair_id", suffixes=("_control", "_candidate"), validate="one_to_one")
    for field in ("ticker", "isu_cd", "entry_signal_date", "entry_execution_date", "entry_open", "market"):
        left, right = pairs[f"{field}_control"], pairs[f"{field}_candidate"]
        if field == "entry_open":
            equal = np.isclose(pd.to_numeric(left), pd.to_numeric(right), atol=0.005, rtol=0).all()
        else:
            equal = left.fillna("").astype(str).equals(right.fillna("").astype(str))
        if not equal:
            raise RuntimeError(f"matched entry parity failed for {field}")

    start, end, support = run.window.effective_start, run.window.effective_end, run.window.execution_support
    entry_signal_dates = pd.to_datetime(control["entry_signal_date"])
    entry_identity_from = pd.to_datetime(control["identity_effective_from"])
    entry_identity_to = pd.to_datetime(control["identity_effective_to"])
    if ((entry_signal_dates < start) | (entry_signal_dates > end)).any():
        raise RuntimeError(f"entry signal outside {run.window.window.window_id} effective window")
    if ((entry_signal_dates < entry_identity_from) | (entry_signal_dates > entry_identity_to)).any():
        raise RuntimeError("entry signal outside COMMON eligibility interval")
    _assert_entry_executions_within_effective_end(
        control,
        end,
        source=f"{run.window.window.window_id} CONTROL population",
    )
    if ((pd.to_datetime(control["entry_execution_date"]) < entry_identity_from) | (pd.to_datetime(control["entry_execution_date"]) > entry_identity_to)).any():
        raise RuntimeError("entry execution outside COMMON eligibility interval")

    exit_window_violations = 0
    for frame in (control, candidate):
        signal_dates = pd.to_datetime(frame["exit_signal_date"], errors="coerce")
        execution_dates = pd.to_datetime(frame["exit_execution_date"], errors="coerce")
        exit_window_violations += int(
            (
                signal_dates.notna()
                & ((signal_dates < start) | (signal_dates > end))
            ).sum()
        )
        exit_window_violations += int(
            (
                execution_dates.notna()
                & ((execution_dates < start) | (execution_dates > support))
            ).sum()
        )
    if exit_window_violations:
        raise RuntimeError(f"exit signal/execution outside window or allowed support: {exit_window_violations}")

    for name, frame in (("CONTROL", control), ("Candidate", candidate)):
        settled = frame[frame["trade_status"] == "LIFECYCLE_SETTLED"]
        if settled.empty:
            continue
        required_fields = ("terminal_reason", "settlement_date", "settlement_price", "settlement_type", "settlement_source")
        if settled[list(required_fields)].isna().any().any():
            raise RuntimeError(f"{name} lifecycle settlement provenance is incomplete")
        if pd.to_numeric(settled["settlement_price"], errors="coerce").le(0).any():
            raise RuntimeError(f"{name} lifecycle settlement price must be positive")
        if settled["execution_support_missing"].fillna(False).astype(bool).any():
            raise RuntimeError(f"{name} lifecycle settlement incorrectly reports missing market execution")
        if settled["terminal_valuation_at_cutoff"].fillna(False).astype(bool).any():
            raise RuntimeError(f"{name} lifecycle settlement is mislabeled as cutoff valuation")

    control_overlap = _overlap_count(control)
    candidate_overlap = _overlap_count(candidate)
    missing_support = int(candidate["execution_support_missing"].fillna(False).astype(bool).sum())
    unexecuted_signal_count = int(candidate["trade_status"].eq("UNEXECUTED_SIGNAL").sum())
    lifecycle_settled_count = int(candidate["trade_status"].eq("LIFECYCLE_SETTLED").sum())
    common_interval_end_before_cutoff_open_count = int(
        sum(
            (
                frame["trade_status"].eq("OPEN_AT_CUTOFF")
                & (pd.to_datetime(frame["identity_effective_to"]) < end)
            ).sum()
            for frame in (control, candidate)
        )
    )
    unresolved_open_valuation_count = int(
        sum(
            (
                frame["trade_status"].eq("OPEN_AT_CUTOFF")
                & (
                    frame.get("terminal_valuation_date", pd.Series(index=frame.index, dtype=object)).isna()
                    | ~frame.get(
                        "terminal_valuation_at_cutoff",
                        pd.Series(False, index=frame.index, dtype=bool),
                    ).fillna(False).astype(bool)
                )
            ).sum()
            for frame in (control, candidate)
        )
    )
    preserved = candidate[
        candidate["candidate_action"].isin(["CONTROL_PRESERVED", "CONTROL_EXIT"])
        & candidate["trade_status"].ne("LIFECYCLE_SETTLED")
    ]
    preserved_without_exit = int(candidate["candidate_action"].eq("CONTROL_PRESERVED").sum())
    preserved_control_exits = int(candidate["candidate_action"].eq("CONTROL_EXIT").sum())
    unchanged_preserved = int(
        (
            np.isclose(
                pd.to_numeric(preserved["terminal_return"], errors="coerce"),
                pd.to_numeric(
                    control.set_index("pair_id").loc[preserved["pair_id"], "terminal_return"].to_numpy(),
                    errors="coerce",
                ),
                atol=0.005,
                rtol=0,
            )
        ).sum()
    ) if len(preserved) else 0
    if control_overlap:
        raise RuntimeError(f"V2 CONTROL unexpectedly overlaps positions: {control_overlap}")
    return {
        "duplicate_pair_ids": 0,
        "entry_population_parity": True,
        "entry_field_parity": True,
        "entry_signal_window_violations": 0,
        "entry_support_violations": 0,
        "identity_entry_violations": 0,
        "control_overlap_count": control_overlap,
        "candidate_overlap_count": candidate_overlap,
        "candidate_execution_support_missing_count": missing_support,
        "candidate_unexecuted_signal_count": unexecuted_signal_count,
        "candidate_lifecycle_settled_count": lifecycle_settled_count,
        "common_interval_end_before_cutoff_open_count": common_interval_end_before_cutoff_open_count,
        # Backward-compatible alias for existing summary consumers.
        "identity_end_before_cutoff_open_count": common_interval_end_before_cutoff_open_count,
        "open_terminal_valuation_unresolved_count": unresolved_open_valuation_count,
        "exit_window_violations": exit_window_violations,
        # Backward-compatible alias; the count now covers only window/support rules.
        "identity_signal_or_execution_violations": exit_window_violations,
        "control_preserved_rows": preserved_without_exit,
        "control_exit_rows": preserved_control_exits,
        "control_unchanged_rows": int(len(preserved)),
        "control_unchanged_return_matches": unchanged_preserved,
        "candidate_stage_asof_future_violations": int(
            sum(
                pd.Timestamp(row.stage_asof_date_at_signal) > pd.Timestamp(row.exit_signal_date)
                for row in candidate.itertuples()
                if pd.notna(row.stage_asof_date_at_signal) and pd.notna(row.exit_signal_date)
            )
        ),
        "lookahead": "completed monthly Pattern A snapshots only; no snapshot later than EOD signal",
    }


def _overlap_count(frame: pd.DataFrame) -> int:
    count = 0
    if frame.empty:
        return count
    for _, group in frame.groupby(["ticker", "isu_cd", "identity_effective_from"], sort=False):
        group = group.copy()
        group["entry_sort"] = pd.to_datetime(group["entry_execution_date"])
        group["exit_sort"] = pd.to_datetime(group["exit_execution_date"], errors="coerce")
        if "settlement_date" in group:
            settlement_dates = pd.to_datetime(group["settlement_date"], errors="coerce")
            lifecycle_settled = group["trade_status"].eq("LIFECYCLE_SETTLED")
            group.loc[lifecycle_settled, "exit_sort"] = settlement_dates.loc[lifecycle_settled]
        group = group.sort_values(["entry_sort", "trade_sequence"], kind="mergesort")
        prior_exit: pd.Timestamp | None = None
        for row in group.itertuples():
            entry = pd.Timestamp(row.entry_sort)
            if prior_exit is not None and entry <= prior_exit:
                count += 1
            if pd.notna(row.exit_sort):
                prior_exit = pd.Timestamp(row.exit_sort)
            else:
                prior_exit = pd.Timestamp.max
    return count


def _candidate_diagnostics(
    control: pd.DataFrame,
    candidate: pd.DataFrame,
) -> dict[str, Any]:
    diag_cols = [
        "pair_id",
        "post_progressed_neg40_touch_eod_events",
        "weak_protect_eod_events",
        "soft_signal_return",
        "incremental_soft_exit",
        "candidate_action",
    ]
    d = candidate[diag_cols].copy()
    d["post_progressed_neg40_touch_trade"] = d["post_progressed_neg40_touch_eod_events"] > 0
    d["weak_protect_trade"] = d["weak_protect_eod_events"] > 0
    base = control[["pair_id", "terminal_return"]].rename(columns={"terminal_return": "control_return"})
    cand = candidate[["pair_id", "terminal_return", "exit_signal_date", "exit_execution_date", "exit_price", "exit_type"]].rename(
        columns={
            "terminal_return": "candidate_return",
            "exit_signal_date": "candidate_signal_date",
            "exit_execution_date": "candidate_execution_date",
            "exit_price": "candidate_execution_open",
            "exit_type": "candidate_exit_type",
        }
    )
    detail = base.merge(cand, on="pair_id", validate="one_to_one")
    detail = detail.merge(
        control[["pair_id", "ticker", "trade_id", "entry_signal_date", "entry_open"]],
        on="pair_id",
        validate="one_to_one",
    )
    detail = detail.merge(d, on="pair_id", validate="one_to_one")
    detail["paired_delta"] = detail["candidate_return"] - detail["control_return"]
    detail["execution_open_return_pct"] = (
        (pd.to_numeric(detail["candidate_execution_open"], errors="coerce") / pd.to_numeric(detail["entry_open"], errors="coerce") - 1.0)
        * 100.0
    ).round(2)

    winner_50 = detail[detail["control_return"] >= 50.0]
    winner_100 = detail[detail["control_return"] >= 100.0]
    tails = {}
    for threshold in (40, 50, 60):
        tails[str(threshold)] = int(((detail["control_return"] <= -threshold) & (detail["candidate_return"] > -threshold)).sum())
    out: dict[str, Any] = {
        "post_progressed_neg40_touch_trade_count": int(d["post_progressed_neg40_touch_trade"].sum()),
        "post_progressed_neg40_touch_eod_event_count": int(d["post_progressed_neg40_touch_eod_events"].sum()),
        "weak_protect_trade_count": int(d["weak_protect_trade"].sum()),
        "weak_protect_eod_event_count": int(d["weak_protect_eod_events"].sum()),
        "soft_signal_count": int(candidate["candidate_action"].eq("SOFT_EXIT").sum()),
        "incremental_soft_exit_count": int(candidate["incremental_soft_exit"].fillna(False).astype(bool).sum()),
        "control_exit_deferred_then_resumed_count": int(candidate["candidate_action"].eq("DEFERRED_CONTROL_EXIT").sum()),
        "control_exit_deferred_open_at_cutoff_count": int(candidate["candidate_action"].eq("WEAK_PROTECT_HOLD_OPEN").sum()),
        "control_ge_50_winner_damaged_count": int((winner_50["candidate_return"] < 50.0).sum()),
        "control_ge_100_winner_damaged_count": int((winner_100["candidate_return"] < 100.0).sum()),
        "control_deep_tail_improved_counts": tails,
        "new_candidate_le_neg40_from_control_gt_neg40_count": int(
            ((detail["control_return"] > -40.0) & (detail["candidate_return"] <= -40.0)).sum()
        ),
    }
    if out["new_candidate_le_neg40_from_control_gt_neg40_count"]:
        new_deep = detail[(detail["control_return"] > -40.0) & (detail["candidate_return"] <= -40.0)].copy()
        out["new_candidate_le_neg40_trades"] = new_deep[
            [
                "pair_id",
                "trade_id",
                "ticker",
                "control_return",
                "candidate_return",
                "candidate_signal_date",
                "soft_signal_return",
                "candidate_execution_date",
                "execution_open_return_pct",
                "paired_delta",
            ]
        ].rename(
            columns={
                "control_return": "control_terminal_pct",
                "candidate_return": "candidate_terminal_pct",
                "candidate_signal_date": "soft_signal_date",
                "soft_signal_return": "signal_return_pct",
                "candidate_execution_date": "execution_date",
                "paired_delta": "paired_delta_pct_points",
            }
        ).to_dict(orient="records")
    return out


def _verdict(summary: Mapping[str, Any], validation: Mapping[str, Any]) -> str:
    if (
        validation.get("candidate_overlap_count", 0)
        or validation.get("candidate_execution_support_missing_count", 0)
        or validation.get("candidate_unexecuted_signal_count", 0)
        or validation.get("candidate_stage_asof_future_violations", 0)
    ):
        return "CHECK_REQUIRED"
    if summary.get("window_id") == "P3-1" and validation.get(
        "common_interval_end_before_cutoff_open_count",
        validation.get("identity_end_before_cutoff_open_count", 0),
    ):
        return "CHECK_REQUIRED"
    if summary.get("window_id") == "P3-1" and validation.get(
        "open_terminal_valuation_unresolved_count", 0
    ):
        return "CHECK_REQUIRED"
    control = summary["control"]
    candidate = summary["candidate"]
    if candidate["trade_count"] != control["trade_count"]:
        return "CHECK_REQUIRED"
    tail40 = control["tail_counts"]["le_neg_40_pct"] - candidate["tail_counts"]["le_neg_40_pct"]
    tail50 = control["tail_counts"]["le_neg_50_pct"] - candidate["tail_counts"]["le_neg_50_pct"]
    winner_damage = summary["candidate_diagnostics"]["control_ge_50_winner_damaged_count"]
    paired = summary["paired"]
    if (tail40 > 0 or tail50 > 0) and winner_damage <= max(1, round(control["trade_count"] * 0.01)):
        if (
            paired["mean_delta_pct_points"] is not None
            and paired["mean_delta_pct_points"] >= -1.0
            and paired["improved"] >= paired["worsened"]
        ):
            return "PROMISING"
        return "MIXED"
    if candidate["mean_terminal_return_pct"] is not None and control["mean_terminal_return_pct"] is not None:
        if candidate["mean_terminal_return_pct"] < control["mean_terminal_return_pct"] - 3.0 and tail40 <= 0:
            return "REJECT"
    return "MIXED"


def _json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _run_candidate_replay(workers: int) -> dict[str, Any]:
    if workers < 1:
        raise ValueError("workers must be positive")
    if not SAMPLE_PATH.exists() or not CONTROL_FULL_PATH.exists() or not INITIAL_FULL_SUMMARY_PATH.exists():
        raise RuntimeError("candidate replay requires the completed P2-1 sample and CONTROL full-run artifacts")
    sample = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    if sample.get("worker_count") != workers:
        raise RuntimeError("candidate replay worker count must match the final same-path sample")
    if float(sample.get("estimated_full_seconds", float("inf"))) > MAX_FULL_ESTIMATE_SECONDS:
        raise RuntimeError("candidate replay refused: corrected-path estimate exceeds 90 minutes")
    for filename in ("control_trades.csv", "candidate_trades.csv", "paired_trades.csv", "summary.json", "run_manifest.json"):
        if (CORRECTED_RUN_DIR / filename).exists():
            raise RuntimeError(f"refusing to overwrite corrected replay output: {CORRECTED_RUN_DIR / filename}")

    original_summary = json.loads(INITIAL_FULL_SUMMARY_PATH.read_text(encoding="utf-8"))
    control = pd.read_csv(
        CONTROL_FULL_PATH,
        dtype={"ticker": str, "isu_cd": str, "trade_id": str, "pair_id": str},
    )
    if control.empty or control["pair_id"].duplicated().any():
        raise RuntimeError("completed CONTROL artifact is empty or has duplicate pair IDs")
    source_rows_by_ticker: dict[str, list[dict[str, Any]]] = {}
    for row in control.to_dict(orient="records"):
        source_rows_by_ticker.setdefault(str(row["ticker"]).zfill(6), []).append(row)

    run = _load_context()
    _assert_entry_executions_within_effective_end(
        control,
        run.window.effective_end,
        source="candidate replay CONTROL source",
    )
    started = time.perf_counter()
    outcomes: list[dict[str, Any]] = []
    errors: list[str] = []
    ticker_rows = sorted(source_rows_by_ticker)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_replay_candidate_ticker, ticker, rows, run): ticker
            for ticker, rows in source_rows_by_ticker.items()
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            ticker = futures[future]
            try:
                outcomes.append(future.result())
            except Exception as exc:
                errors.append(f"{ticker}: {type(exc).__name__}: {exc}")
            if completed % 10 == 0 or completed == len(futures):
                print(
                    f"REPLAY progress: {completed}/{len(futures)} entry tickers; "
                    f"candidate_trades={sum(len(item['candidate_rows']) for item in outcomes)}; "
                    f"elapsed={time.perf_counter() - started:.1f}s; errors={len(errors)}",
                    flush=True,
                )
    elapsed = time.perf_counter() - started
    if errors:
        CORRECTED_RUN_DIR.mkdir(parents=True, exist_ok=True)
        _json_write(
            CORRECTED_RUN_DIR / "replay_failure.json",
            {
                "status": "FAILED",
                "errors": errors,
                "completed_tickers": len(outcomes),
                "target_tickers": len(ticker_rows),
                "elapsed_seconds": round(elapsed, 3),
            },
        )
        raise RuntimeError(f"corrected candidate replay encountered {len(errors)} errors")

    candidate = pd.DataFrame(
        [row for result in outcomes for row in result["candidate_rows"]]
    ).sort_values(["ticker", "identity_effective_from", "trade_sequence"], kind="mergesort").reset_index(drop=True)
    control = control.sort_values(["ticker", "identity_effective_from", "trade_sequence"], kind="mergesort").reset_index(drop=True)
    if len(candidate) != len(control):
        raise RuntimeError(f"candidate replay count mismatch: {len(candidate)} != {len(control)}")
    validation = _validate_results(control, candidate, run)
    paired = control.merge(candidate, on="pair_id", suffixes=("_control", "_candidate"), validate="one_to_one")
    diagnostics = _candidate_diagnostics(control, candidate)
    replay_loads = sum(int(result["repository_load_count"]) for result in outcomes)
    base_run_seconds = float(original_summary["execution"]["actual_full_seconds"])
    base_setup_seconds = float(original_summary["execution"]["setup_seconds"])
    corrected_summary: dict[str, Any] = {
        "status": "COMPLETE",
        "work_id": "P2_1_NEG40_WEAK_PROTECT_MATCHED_AB_V01_CORRECTED_CANDIDATE_REPLAY",
        "window_id": "P2-1",
        "head": original_summary["head"],
        "strategy_ids": original_summary["strategy_ids"],
        "window": original_summary["window"],
        "population": {
            **original_summary["population"],
            "control_entry_count": len(control),
            "candidate_entry_count": len(candidate),
            "raw_candidate_artifact_reused": False,
        },
        "execution": {
            "sample_wall_seconds": sample["sample_wall_seconds"],
            "estimated_full_seconds": sample["estimated_full_seconds"],
            "base_control_worker_seconds": round(base_run_seconds, 3),
            "base_control_setup_seconds": round(base_setup_seconds, 3),
            "candidate_replay_worker_seconds": round(elapsed, 3),
            "candidate_replay_setup_seconds": round(run.setup_seconds, 3),
            "combined_p2_1_seconds": round(
                base_run_seconds + base_setup_seconds + elapsed + run.setup_seconds,
                3,
            ),
            "workers": workers,
            "candidate_replay_repository_v2_load_count": replay_loads,
        },
        "data_authority": original_summary["data_authority"],
        "control": _metrics(control),
        "candidate": _metrics(candidate),
        "paired": _paired_summary(control, candidate),
        "candidate_diagnostics": diagnostics,
        "validation": validation,
        "candidate_replay_correction": {
            "status": "APPLIED",
            "reason": "V2 monthly signal labels are mapped to the last local trading EOD, and candidate return arithmetic matches V2 exactly.",
            "initial_false_deferred_control_exit_rows": int(
                original_summary.get("candidate_diagnostics", {}).get("control_exit_deferred_then_resumed_count", 0)
            ),
            "initial_false_deferred_rows_had_zero_weak_protect_events": True,
            "initial_rows_with_changed_terminal_return": 135,
            "prior_corrected_replay_superseded": str((RUN_DIR / "candidate_replay_20260923_fix01" / "summary.json").relative_to(ROOT)),
            "candidate_replayed_against_same_frozen_control_entry_population": True,
        },
        "supersedes": str(INITIAL_FULL_SUMMARY_PATH.relative_to(ROOT)),
        "verdict": None,
    }
    corrected_summary["verdict"] = _verdict(corrected_summary, validation)

    CORRECTED_RUN_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CONTROL_FULL_PATH, CORRECTED_RUN_DIR / "control_trades.csv")
    candidate.to_csv(CORRECTED_RUN_DIR / "candidate_trades.csv", index=False)
    paired.to_csv(CORRECTED_RUN_DIR / "paired_trades.csv", index=False)
    _json_write(CORRECTED_RUN_DIR / "summary.json", corrected_summary)
    _json_write(
        CORRECTED_RUN_DIR / "run_manifest.json",
        {
            "run_id": "run_20260923_candidate_replay_20260923_fix02",
            "start_head": corrected_summary["head"],
            "window_id": "P2-1",
            "p2_1_only": True,
            "base_control_source": str(CONTROL_FULL_PATH.relative_to(ROOT)),
            "candidate_replay_correction": corrected_summary["candidate_replay_correction"],
            "effective_pit_sha256": run.authority.pit_sha256,
            "outputs": ["control_trades.csv", "candidate_trades.csv", "paired_trades.csv", "summary.json"],
        },
    )
    _json_write(
        RUN_DIR / "superseded_notice.json",
        {
            "status": "SUPERSEDED_CANDIDATE_ONLY",
            "reason": "The initial candidate replay had a monthly-signal calendar-label bug; its first correction had one unchanged-trade rounding mismatch. The final replay fixes both.",
            "corrected_result": str((CORRECTED_RUN_DIR / "summary.json").relative_to(ROOT)),
            "prior_corrected_result_superseded": str((RUN_DIR / "candidate_replay_20260923_fix01" / "summary.json").relative_to(ROOT)),
            "control_trades_remain_authoritative": True,
            "no_source_or_canonical_artifact_was_deleted": True,
        },
    )
    return corrected_summary


def _run_ledger_export(workers: int) -> dict[str, Any]:
    if workers < 1:
        raise ValueError("workers must be positive")
    required = (
        CORRECTED_RUN_DIR / "control_trades.csv",
        CORRECTED_RUN_DIR / "candidate_trades.csv",
        CORRECTED_RUN_DIR / "summary.json",
        SAMPLE_PATH,
    )
    if not all(path.exists() for path in required):
        raise RuntimeError("P2-1 ledger export requires the completed corrected fix02 result")
    for path in (MATCHED_LEDGER_PATH, SOFT_EVENTS_PATH, LEDGER_SUMMARY_PATH):
        if path.exists():
            raise RuntimeError(f"refusing to overwrite existing ledger artifact: {path}")

    sample = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    if sample.get("worker_count") != workers:
        raise RuntimeError("ledger replay worker count must match the P2-1 same-path sample")
    source_summary = json.loads((CORRECTED_RUN_DIR / "summary.json").read_text(encoding="utf-8"))
    if source_summary.get("status") != "COMPLETE" or source_summary.get("window_id") != "P2-1":
        raise RuntimeError("ledger export source is not a completed P2-1 fix02 run")

    control = pd.read_csv(
        CORRECTED_RUN_DIR / "control_trades.csv",
        dtype={"ticker": str, "isu_cd": str, "trade_id": str, "pair_id": str},
    )
    candidate = pd.read_csv(
        CORRECTED_RUN_DIR / "candidate_trades.csv",
        dtype={"ticker": str, "isu_cd": str, "trade_id": str, "pair_id": str},
    )
    source_rows_by_ticker: dict[str, list[dict[str, Any]]] = {}
    for row in control.to_dict(orient="records"):
        source_rows_by_ticker.setdefault(str(row["ticker"]).zfill(6), []).append(row)

    run = _load_context()
    started = time.perf_counter()
    outcomes: list[dict[str, Any]] = []
    errors: list[str] = []
    ticker_rows = sorted(source_rows_by_ticker)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_replay_candidate_ticker, ticker, rows, run): ticker
            for ticker, rows in source_rows_by_ticker.items()
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            ticker = futures[future]
            try:
                outcomes.append(future.result())
            except Exception as exc:
                errors.append(f"{ticker}: {type(exc).__name__}: {exc}")
            if completed % 50 == 0 or completed == len(futures):
                print(
                    f"LEDGER P2-1 event replay: {completed}/{len(futures)} entry tickers; "
                    f"elapsed={time.perf_counter() - started:.1f}s; errors={len(errors)}",
                    flush=True,
                )
    replay_seconds = time.perf_counter() - started
    if errors:
        raise RuntimeError(f"P2-1 ledger event replay encountered {len(errors)} errors: {errors[:20]}")

    replayed_candidate = pd.DataFrame(
        [row for result in outcomes for row in result["candidate_rows"]]
    )
    if replayed_candidate.empty or len(replayed_candidate) != len(candidate):
        raise RuntimeError(
            f"P2-1 ledger event replay row count mismatch: {len(replayed_candidate)} != {len(candidate)}"
        )
    if replayed_candidate["pair_id"].duplicated().any() or candidate["pair_id"].duplicated().any():
        raise RuntimeError("duplicate pair_id during P2-1 ledger parity check")
    replay_parity = replayed_candidate.merge(
        candidate,
        on="pair_id",
        suffixes=("_replayed", "_stored"),
        validate="one_to_one",
    )
    if len(replay_parity) != len(candidate):
        raise RuntimeError("P2-1 event replay pair population differs from stored fix02 candidate")
    for field in (
        "trade_id",
        "candidate_action",
        "exit_type",
        "exit_signal_date",
        "exit_execution_date",
        "trade_status",
    ):
        left = replay_parity[f"{field}_replayed"].fillna("").astype(str)
        right = replay_parity[f"{field}_stored"].fillna("").astype(str)
        if not left.equals(right):
            raise RuntimeError(f"P2-1 event replay differs from stored fix02 candidate: {field}")
    for field in ("entry_open", "exit_price", "terminal_return", "holding_days"):
        left = pd.to_numeric(replay_parity[f"{field}_replayed"], errors="coerce")
        right = pd.to_numeric(replay_parity[f"{field}_stored"], errors="coerce")
        equal = np.isclose(left, right, atol=0.005, rtol=0, equal_nan=True)
        if not equal.all():
            raise RuntimeError(f"P2-1 event replay differs from stored fix02 candidate: {field}")

    cutoff_date = str(source_summary["window"]["effective_end"])
    ledger = _build_matched_trade_ledger(control, candidate, cutoff_date=cutoff_date)
    if ledger.empty:
        raise RuntimeError("P2-1 matched trade ledger is empty")
    ledger_aggregates = _ledger_aggregates(ledger)
    reconciliation = {
        "control_metrics_match_source_summary": _nested_values_equal(
            ledger_aggregates["control"], source_summary["control"]
        ),
        "candidate_metrics_match_source_summary": _nested_values_equal(
            ledger_aggregates["candidate"], source_summary["candidate"]
        ),
        "paired_metrics_match_source_summary": _nested_values_equal(
            ledger_aggregates["paired"], source_summary["paired"]
        ),
    }
    if not all(reconciliation.values()):
        raise RuntimeError(f"P2-1 ledger-derived aggregates do not reconcile: {reconciliation}")

    soft_event_rows = [
        event
        for result in outcomes
        for diagnostic in result["diagnostics"]
        for event in diagnostic.get("soft_events", [])
    ]
    event_columns = [
        "trade_id",
        "ticker",
        "date",
        "close_return",
        "pattern_a_stage",
        "event_type",
        "execution_date",
        "execution_open",
    ]
    events = pd.DataFrame(soft_event_rows, columns=event_columns)
    if events.empty:
        raise RuntimeError("P2-1 soft event ledger unexpectedly contains no qualifying EOD events")
    events = events.sort_values(["ticker", "date", "trade_id", "event_type"], kind="mergesort").reset_index(drop=True)
    if events.duplicated(["trade_id", "date", "event_type"]).any():
        raise RuntimeError("duplicate P2-1 soft event for one trade/date/type")
    if not set(events["trade_id"]).issubset(set(ledger["trade_id"])):
        raise RuntimeError("P2-1 soft events contain a trade absent from the matched ledger")
    if not (pd.to_numeric(events["close_return"]) <= -40.0).all():
        raise RuntimeError("P2-1 soft event does not satisfy the existing NEG40 threshold")

    weak_events = events[events["event_type"] == "WEAK_PROTECT"]
    soft_events = events[events["event_type"] == "SOFT_EXIT_SIGNAL"]
    if len(weak_events) + len(soft_events) != len(events):
        raise RuntimeError("unknown P2-1 soft event type")
    if not weak_events["pattern_a_stage"].eq("WEAK").all():
        raise RuntimeError("WEAK_PROTECT event recorded with a non-WEAK stage")
    if (soft_events["pattern_a_stage"] == "WEAK").any():
        raise RuntimeError("SOFT_EXIT_SIGNAL incorrectly recorded during WEAK protection")
    if soft_events[["execution_date", "execution_open"]].isna().any().any():
        raise RuntimeError("P2-1 soft exit event lacks next-session execution support")
    stored_soft_count = int(candidate["candidate_action"].eq("SOFT_EXIT").sum())
    stored_weak_count = int(source_summary["candidate_diagnostics"]["weak_protect_eod_event_count"])
    if len(soft_events) != stored_soft_count:
        raise RuntimeError(f"soft exit event count mismatch: {len(soft_events)} != {stored_soft_count}")
    if len(weak_events) != stored_weak_count:
        raise RuntimeError(f"WEAK_PROTECT event count mismatch: {len(weak_events)} != {stored_weak_count}")

    soft_join = soft_events.merge(
        candidate[["trade_id", "exit_signal_date", "exit_execution_date", "exit_price", "candidate_action"]],
        on="trade_id",
        validate="one_to_one",
    )
    if not (
        soft_join["event_type"].eq("SOFT_EXIT_SIGNAL").all()
        and soft_join["candidate_action"].eq("SOFT_EXIT").all()
        and soft_join["date"].astype(str).equals(soft_join["exit_signal_date"].astype(str))
        and soft_join["execution_date"].astype(str).equals(soft_join["exit_execution_date"].astype(str))
    ):
        raise RuntimeError("soft event signal/execution does not match the final candidate trade")
    if not np.isclose(
        pd.to_numeric(soft_join["execution_open"]),
        pd.to_numeric(soft_join["exit_price"]),
        atol=0.005,
        rtol=0,
    ).all():
        raise RuntimeError("soft event execution_open differs from final candidate exit price")

    event_type_counts = {
        str(kind): int(count)
        for kind, count in events["event_type"].value_counts().sort_index().items()
    }
    event_trade_counts = {
        str(kind): int(events.loc[events["event_type"] == kind, "trade_id"].nunique())
        for kind in sorted(events["event_type"].unique())
    }
    summary = {
        "status": "COMPLETE",
        "work_id": "P2_1_NEG40_WEAK_PROTECT_MATCHED_AB_V01_FULL_TRADE_LEDGER",
        "window_id": "P2-1",
        "p2_1_only": True,
        "head": source_summary["head"],
        "strategy_ids": source_summary["strategy_ids"],
        "window": source_summary["window"],
        "population": source_summary["population"],
        "ledger": {
            "path": str(MATCHED_LEDGER_PATH.relative_to(ROOT)),
            "row_count": int(len(ledger)),
            "trade_id_unique_count": int(ledger["trade_id"].nunique()),
            "control_candidate_trade_count_equal": True,
            "control_candidate_trade_id_sets_equal": True,
            "aggregates_recomputed_from_full_ledger": ledger_aggregates,
            "aggregate_reconciliation": reconciliation,
        },
        "soft_events": {
            "path": str(SOFT_EVENTS_PATH.relative_to(ROOT)),
            "row_count": int(len(events)),
            "event_type_counts": event_type_counts,
            "distinct_trade_counts_by_event_type": event_trade_counts,
            "replay_matches_final_candidate_trades": True,
        },
        "execution": {
            "scope": "P2-1 candidate event replay only; no other window run",
            "workers": workers,
            "setup_seconds": round(run.setup_seconds, 3),
            "candidate_event_replay_seconds": round(replay_seconds, 3),
            "repository_v2_load_count": sum(int(result["repository_load_count"]) for result in outcomes),
            "network_calls": 0,
        },
        "source_backtest_summary": str((CORRECTED_RUN_DIR / "summary.json").relative_to(ROOT)),
        "validation": {
            "trade_id_unique_in_ledger": True,
            "entry_identity_parity": True,
            "candidate_replay_matches_fix02": True,
            "all_soft_events_at_or_below_neg40_pct": True,
            "weak_protect_events_have_weak_stage": True,
            "soft_exit_signals_are_nonweak": True,
            "soft_exit_execution_support_complete": True,
            "soft_event_duplicates": 0,
            "all_ledger_aggregates_match_source_summary": True,
        },
        "verdict": source_summary["verdict"],
    }

    # Do not leave a partial set of deliverables if generation or validation failed.
    ledger.to_csv(MATCHED_LEDGER_PATH, index=False, float_format="%.8f")
    events.to_csv(SOFT_EVENTS_PATH, index=False, float_format="%.8f")
    _json_write(LEDGER_SUMMARY_PATH, summary)

    manifest_path = CORRECTED_RUN_DIR / "run_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for output in (MATCHED_LEDGER_PATH.name, SOFT_EVENTS_PATH.name, LEDGER_SUMMARY_PATH.name):
            if output not in manifest.setdefault("outputs", []):
                manifest["outputs"].append(output)
        manifest["full_trade_ledger"] = True
        _json_write(manifest_path, manifest)
    return summary


def _run(
    mode: str,
    workers: int,
    sample_count: int,
    window_id: str | None = None,
) -> dict[str, Any]:
    if mode not in {"sample", "full"}:
        raise ValueError("mode must be sample or full")
    if workers < 1:
        raise ValueError("workers must be positive")
    selected_window = window_id or WINDOW_ID
    if selected_window != WINDOW_ID:
        raise RuntimeError("configure the selected window before starting the run")
    if mode == "sample" and SAMPLE_PATH.exists():
        raise RuntimeError(f"refusing to overwrite existing sample benchmark: {SAMPLE_PATH}")
    if mode == "full":
        if not SAMPLE_PATH.exists():
            raise RuntimeError(f"full {selected_window} refused: run the same-path sample first")
        sample = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
        if sample.get("window_id") != selected_window:
            raise RuntimeError("full run window must match the measured sample window")
        if sample.get("worker_count") != workers:
            raise RuntimeError(f"full {selected_window} worker count must match the measured sample")
        if float(sample.get("estimated_full_seconds", float("inf"))) > MAX_FULL_ESTIMATE_SECONDS:
            raise RuntimeError(
                f"full {selected_window} refused because measured runtime estimate exceeds 90 minutes; "
                "inspect/optimize only accuracy-preserving bottlenecks first"
            )
        expected_outputs = [
            "control_trades.csv",
            "candidate_trades.csv",
            "paired_trades.csv",
            "summary.json",
            "run_manifest.json",
        ]
        if selected_window == "P2-2":
            expected_outputs.extend(
                ("p2_2_matched_trades.csv", "p2_2_soft_events.csv", "p2_2_summary.json")
            )
        elif selected_window == "P3-1":
            expected_outputs.extend(
                ("p3_1_matched_trades.csv", "p3_1_soft_events.csv", "p3_1_summary.json")
            )
        elif selected_window == "P2-1" and CORRECTED_RUN_DIR == RUN_DIR:
            expected_outputs.extend(
                ("p2_1_matched_trades.csv", "p2_1_soft_events.csv", "p2_1_summary.json")
            )
        for filename in expected_outputs:
            if (RUN_DIR / filename).exists():
                raise RuntimeError(f"refusing to overwrite existing run output: {RUN_DIR / filename}")

    run = _load_context(selected_window)
    if mode == "full" and selected_window == "P2-2":
        preflight = _p2_2_identity_authority_preflight(run)
        if preflight["status"] != "PASS":
            raise RuntimeError(
                "P2-2 full run blocked by identity-authority preflight: "
                + json.dumps(preflight, ensure_ascii=False, sort_keys=True)
            )
    p3_1_preflight: dict[str, Any] | None = None
    if selected_window == "P3-1":
        p3_1_preflight = _p3_1_population_preflight(run)
        if p3_1_preflight["status"] != "PASS":
            raise RuntimeError(
                "P3-1 replay blocked by population preflight: "
                + json.dumps(p3_1_preflight, ensure_ascii=False, sort_keys=True)
            )
        if mode == "full":
            sample = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
            sample_preflight = sample.get("population_preflight", {})
            if (
                sample_preflight.get("status") != "PASS"
                or sample_preflight.get("effective_pit_sha256")
                != p3_1_preflight["effective_pit_sha256"]
                or sample_preflight.get("common_identity_segment_count")
                != p3_1_preflight["common_identity_segment_count"]
            ):
                raise RuntimeError("P3-1 full replay authority differs from its sample benchmark")
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    all_tickers = sorted(run.segments_by_ticker)
    if not all_tickers:
        raise RuntimeError(f"{selected_window} COMMON identity population is empty")
    tickers = _sample_tickers(all_tickers, sample_count) if mode == "sample" else all_tickers
    started = time.perf_counter()
    outcomes: list[dict[str, Any]] = []
    errors: list[str] = []
    times: list[float] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_process_ticker, ticker, run): ticker for ticker in tickers}
        for completed, future in enumerate(as_completed(futures), start=1):
            ticker = futures[future]
            try:
                result = future.result()
                outcomes.append(result)
                times.append(float(result["elapsed_seconds"]))
            except Exception as exc:
                errors.append(f"{ticker}: {type(exc).__name__}: {exc}")
            if completed % 10 == 0 or completed == len(tickers):
                print(
                    f"{mode.upper()} progress: {completed}/{len(tickers)} tickers; "
                    f"trades={sum(len(item['control_rows']) for item in outcomes)}; "
                    f"elapsed={time.perf_counter() - started:.1f}s; errors={len(errors)}",
                    flush=True,
                )
    elapsed = time.perf_counter() - started
    if errors:
        failure = {
            "status": "FAILED",
            "mode": mode,
            "errors": errors,
            "completed_tickers": len(outcomes),
            "target_tickers": len(tickers),
            "elapsed_seconds": round(elapsed, 3),
        }
        _json_write(RUN_DIR / f"{mode}_failure.json", failure)
        raise RuntimeError(f"{mode} run encountered {len(errors)} ticker errors; see {mode}_failure.json")

    total_segments = sum(int(result["segments_seen"]) for result in outcomes)
    control_rows = [row for result in outcomes for row in result["control_rows"]]
    candidate_rows = [row for result in outcomes for row in result["candidate_rows"]]
    trade_diagnostics = [row for result in outcomes for row in result["diagnostics"]]
    if mode == "sample":
        estimated = run.setup_seconds + elapsed * len(all_tickers) / max(len(tickers), 1)
        sample_control = pd.DataFrame(control_rows)
        sample_candidate = pd.DataFrame(candidate_rows)
        sample_validation = _validate_results(sample_control, sample_candidate, run)
        p3_sample_ledger_reconciliation: dict[str, bool] | None = None
        p3_sample_event_counts: dict[str, int] | None = None
        if selected_window == "P3-1":
            sample_ledger = _add_p3_1_ledger_contract_fields(
                _build_matched_trade_ledger(
                    sample_control,
                    sample_candidate,
                    cutoff_date=run.window.effective_end.strftime("%Y-%m-%d"),
                )
            )
            sample_aggregates = _ledger_aggregates(sample_ledger)
            p3_sample_ledger_reconciliation = {
                "control": _nested_values_equal(sample_aggregates["control"], _metrics(sample_control)),
                "candidate": _nested_values_equal(sample_aggregates["candidate"], _metrics(sample_candidate)),
                "paired": _nested_values_equal(
                    sample_aggregates["paired"],
                    _paired_summary(sample_control, sample_candidate),
                ),
            }
            sample_events = _build_soft_event_ledger(trade_diagnostics, sample_candidate, run=run)
            p3_sample_event_counts = {
                str(event_type): int(count)
                for event_type, count in sample_events["event_type"].value_counts().sort_index().items()
            }
            sample_validation.update(
                {
                    "ledger_pair_id_unique": bool(sample_ledger["pair_id"].is_unique),
                    "control_candidate_pair_id_sets_equal": set(sample_control["pair_id"])
                    == set(sample_candidate["pair_id"]),
                    "control_candidate_source_trade_id_equal_by_pair": bool(
                        sample_control.set_index("pair_id")["trade_id"].astype(str).sort_index().equals(
                            sample_candidate.set_index("pair_id")["trade_id"].astype(str).sort_index()
                        )
                    ),
                    "ledger_aggregate_reconciliation": p3_sample_ledger_reconciliation,
                    "ledger_build_feasible": True,
                    "soft_event_execution_contract_pass": True,
                    "soft_event_duplicates": int(
                        sample_events.duplicated(["pair_id", "date", "event_type"]).sum()
                    ),
                    "unexecuted_signal_count": int(
                        sample_candidate["trade_status"].eq("UNEXECUTED_SIGNAL").sum()
                    ),
                }
            )
            if (
                not all(p3_sample_ledger_reconciliation.values())
                or not sample_validation["ledger_pair_id_unique"]
                or not sample_validation["control_candidate_pair_id_sets_equal"]
                or not sample_validation["control_candidate_source_trade_id_equal_by_pair"]
                or sample_validation["soft_event_duplicates"]
                or sample_validation["unexecuted_signal_count"]
            ):
                raise RuntimeError("P3-1 sample ledger/execution feasibility preflight failed")
        benchmark = {
            "status": "COMPLETE",
            "mode": "same_path_sample_only",
            "window_id": selected_window,
            "window": {
                "calendar_start": run.window.window.calendar_start.strftime("%Y-%m-%d"),
                "calendar_end": run.window.window.calendar_end.strftime("%Y-%m-%d"),
                "effective_start": run.window.effective_start.strftime("%Y-%m-%d"),
                "effective_end": run.window.effective_end.strftime("%Y-%m-%d"),
                "execution_support": run.window.execution_support.strftime("%Y-%m-%d"),
            },
            "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "worker_count": workers,
            "target_common_identity_segments": sum(map(len, run.segments_by_ticker.values())),
            "target_unique_tickers": len(all_tickers),
            "sample_segments_processed": total_segments,
            "sample_tickers_processed": len(tickers),
            "setup_seconds": round(run.setup_seconds, 3),
            "sample_wall_seconds": round(elapsed, 3),
            "sample_seconds_per_ticker_mean": round(statistics.mean(times), 4) if times else None,
            "sample_seconds_per_ticker_p50": round(float(np.percentile(times, 50)), 4) if times else None,
            "sample_seconds_per_ticker_p90": round(float(np.percentile(times, 90)), 4) if times else None,
            "sample_ticker_timings": [
                {
                    "ticker": item["ticker"],
                    "identity_segments": item["segments_seen"],
                    "elapsed_seconds": round(float(item["elapsed_seconds"]), 4),
                }
                for item in sorted(outcomes, key=lambda value: value["ticker"])
            ],
            "estimated_full_seconds": round(estimated, 3),
            "estimated_full_minutes": round(estimated / 60, 2),
            "max_estimate_minutes": 90,
            "control_trade_rows_in_sample_not_used_for_performance_tuning": len(control_rows),
            "candidate_trade_rows_in_sample_not_used_for_performance_tuning": len(candidate_rows),
            "sample_invariants": sample_validation,
            "sample_ledger_aggregate_reconciliation": p3_sample_ledger_reconciliation,
            "sample_soft_event_type_counts": p3_sample_event_counts,
            "raw_candidate_artifact_reused": False,
            "population_preflight": p3_1_preflight,
            "authority_sha256": run.authority.pit_sha256,
            "authority_interval_count": run.authority.pit_count,
            "contract_sha256": {
                "score": _sha256(SCORE_CONTRACT_PATH),
                "stage": _sha256(STAGE_CONTRACT_PATH),
            },
            "errors": [],
        }
        if selected_window == "P2-1":
            benchmark["raw_candidate_path_sha256_for_provenance_only"] = _sha256(
                RAW_CANDIDATE_PATH
            )
        _json_write(SAMPLE_PATH, benchmark)
        print(
            f"{selected_window} sample benchmark: "
            f"estimated_full_minutes={benchmark['estimated_full_minutes']:.2f}",
            flush=True,
        )
        return benchmark

    control = pd.DataFrame(control_rows).sort_values(["ticker", "identity_effective_from", "trade_sequence"], kind="mergesort").reset_index(drop=True)
    candidate = pd.DataFrame(candidate_rows).sort_values(["ticker", "identity_effective_from", "trade_sequence"], kind="mergesort").reset_index(drop=True)
    if control.empty:
        raise RuntimeError(f"{selected_window} full run produced zero CONTROL entries")
    validation = _validate_results(control, candidate, run)
    paired = control.merge(candidate, on="pair_id", suffixes=("_control", "_candidate"), validate="one_to_one")
    control_metrics = _metrics(control)
    candidate_metrics = _metrics(candidate)
    paired_metrics = _paired_summary(control, candidate)
    candidate_diagnostics = _candidate_diagnostics(control, candidate)
    p2_2_ledger: pd.DataFrame | None = None
    p2_2_events: pd.DataFrame | None = None
    ledger_aggregates: dict[str, Any] | None = None
    ledger_reconciliation: dict[str, bool] | None = None
    p2_1_comparison: dict[str, Any] | None = None
    p3_1_comparison: dict[str, Any] | None = None
    if selected_window in {"P2-2", "P3-1"}:
        cutoff_date = run.window.effective_end.strftime("%Y-%m-%d")
        p2_2_ledger = _build_matched_trade_ledger(
            control,
            candidate,
            cutoff_date=cutoff_date,
        )
        if selected_window == "P3-1":
            p2_2_ledger = _add_p3_1_ledger_contract_fields(p2_2_ledger)
        ledger_aggregates = _ledger_aggregates(p2_2_ledger)
        ledger_reconciliation = {
            "control_metrics_match_summary": _nested_values_equal(
                ledger_aggregates["control"], control_metrics
            ),
            "candidate_metrics_match_summary": _nested_values_equal(
                ledger_aggregates["candidate"], candidate_metrics
            ),
            "paired_metrics_match_summary": _nested_values_equal(
                ledger_aggregates["paired"], paired_metrics
            ),
        }
        if not all(ledger_reconciliation.values()):
            raise RuntimeError(f"{selected_window} ledger aggregates do not reconcile: {ledger_reconciliation}")
        p2_2_events = _build_soft_event_ledger(trade_diagnostics, candidate, run=run)
        event_counts = {
            str(event_type): int(count)
            for event_type, count in p2_2_events["event_type"].value_counts().sort_index().items()
        }
        if event_counts.get("WEAK_PROTECT", 0) != candidate_diagnostics["weak_protect_eod_event_count"]:
            raise RuntimeError(f"{selected_window} WEAK_PROTECT event ledger count differs from candidate diagnostics")
        if event_counts.get("SOFT_EXIT_SIGNAL", 0) != candidate_diagnostics["soft_signal_count"]:
            raise RuntimeError(f"{selected_window} SOFT_EXIT_SIGNAL ledger count differs from candidate trades")
        if selected_window == "P2-2":
            p2_1_comparison = _compare_p2_1_directions(
                control_metrics,
                candidate_metrics,
                paired_metrics,
            )
        else:
            p3_1_comparison = _compare_p3_1_directions(
                control_metrics,
                candidate_metrics,
                paired_metrics,
            )
        validation.update(
            {
                "ledger_pair_id_unique": bool(
                    p2_2_ledger["pair_id"].nunique() == len(p2_2_ledger)
                ),
                "control_candidate_pair_id_sets_equal": set(control["pair_id"])
                == set(candidate["pair_id"]),
                "control_candidate_source_trade_id_equal_by_pair": bool(
                    paired["trade_id_control"].astype(str).equals(
                        paired["trade_id_candidate"].astype(str)
                    )
                ),
                "all_ledger_aggregates_match_summary": all(ledger_reconciliation.values()),
                "soft_event_duplicates": int(
                    p2_2_events.duplicated(["pair_id", "date", "event_type"]).sum()
                ),
                "soft_event_replay_consistency": True,
            }
        )
        lifecycle_settled_control = control[control["trade_status"] == "LIFECYCLE_SETTLED"]
        lifecycle_settled_candidate = candidate[candidate["trade_status"] == "LIFECYCLE_SETTLED"]
        validation["control_candidate_lifecycle_settlement_counts_equal"] = (
            len(lifecycle_settled_control) == len(lifecycle_settled_candidate)
        )
        settlement_fields = {
            "terminal_reason",
            "settlement_date",
            "settlement_price",
            "settlement_type",
            "settlement_source",
        }
        validation["lifecycle_settlement_provenance_complete"] = bool(
            all(
                frame.loc[frame["trade_status"] == "LIFECYCLE_SETTLED"].empty
                or (
                    settlement_fields.issubset(frame.columns)
                    and frame.loc[
                        frame["trade_status"] == "LIFECYCLE_SETTLED", sorted(settlement_fields)
                    ].notna().all().all()
                )
                for frame in (control, candidate)
            )
        )

    population = {
        "filter_contract": "no separate market-cap, minimum trading-value/volume, or fundamentals filter",
        "identity_policy": "COMMON PIT identity intervals; no ticker-list broadcast; no identity stitching; no future fallback",
        "common_identity_segments": total_segments,
        "unique_tickers_processed": len(outcomes),
        "tickers_with_entries": int(control["ticker"].nunique()),
        "control_entry_count": len(control),
        "candidate_entry_count": len(candidate),
        "raw_candidate_artifact_reused": False,
    }
    if selected_window == "P2-1":
        population["raw_candidate_artifact"] = str(RAW_CANDIDATE_PATH.relative_to(ROOT))
    elif selected_window == "P3-1":
        population.update(
            {
                "population_id": "P3-1_COMMON_PIT_DERIVED_FRESH_V01",
                "source_authority": str(run.authority.pit_path.relative_to(ROOT)),
                "p2_population_reused": False,
            }
        )

    summary: dict[str, Any] = {
        "status": "COMPLETE",
        "work_id": f"{selected_window.replace('-', '_')}_NEG40_WEAK_PROTECT_MATCHED_AB_V01",
        "window_id": selected_window,
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "runner_sha256": _sha256(Path(__file__).resolve()),
        "strategy_ids": {"control": V2_STRATEGY_ID, "candidate": CANDIDATE_STRATEGY_ID},
        "window": {
            "calendar_start": run.window.window.calendar_start.strftime("%Y-%m-%d"),
            "calendar_end": run.window.window.calendar_end.strftime("%Y-%m-%d"),
            "effective_start": run.window.effective_start.strftime("%Y-%m-%d"),
            "effective_end": run.window.effective_end.strftime("%Y-%m-%d"),
            "execution_support": run.window.execution_support.strftime("%Y-%m-%d"),
        },
        "population": population,
        "execution": {
            "sample_wall_seconds": json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))["sample_wall_seconds"],
            "estimated_full_seconds": json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))["estimated_full_seconds"],
            "actual_full_seconds": round(elapsed, 3),
            "setup_seconds": round(run.setup_seconds, 3),
            "workers": workers,
            "repository_v2_load_count": sum(int(item["repository_load_count"]) for item in outcomes),
        },
        "data_authority": {
            "repository": "Repository V2 local adjusted/raw composition",
            "authority_sha256": run.authority.pit_sha256,
            "authority_interval_count": run.authority.pit_count,
            "calendar_certified_through": run.calendar.metadata.get("certified_through"),
            "market_calendar_sha256": run.calendar.metadata.get("manifest_sha256"),
            "network_calls": 0,
        },
        "control": control_metrics,
        "candidate": candidate_metrics,
        "paired": paired_metrics,
        "candidate_diagnostics": candidate_diagnostics,
        "validation": validation,
        "verdict": None,
    }
    summary["verdict"] = _verdict(summary, validation)

    if selected_window == "P2-2":
        assert p2_2_ledger is not None and p2_2_events is not None
        assert ledger_aggregates is not None and ledger_reconciliation is not None
        summary["ledger"] = {
            "path": str(MATCHED_LEDGER_PATH.relative_to(ROOT)),
            "row_count": int(len(p2_2_ledger)),
            "pair_id_unique_count": int(p2_2_ledger["pair_id"].nunique()),
            "distinct_source_trade_id_count": int(p2_2_ledger["trade_id"].nunique()),
            "source_trade_id_preserved": True,
            "control_candidate_trade_count_equal": len(control) == len(candidate),
            "control_candidate_pair_id_sets_equal": set(control["pair_id"])
            == set(candidate["pair_id"]),
            "control_candidate_source_trade_id_equal_by_pair": bool(
                paired["trade_id_control"].astype(str).equals(
                    paired["trade_id_candidate"].astype(str)
                )
            ),
            "aggregates_recomputed_from_full_ledger": ledger_aggregates,
            "aggregate_reconciliation": ledger_reconciliation,
        }
        summary["soft_events"] = {
            "path": str(SOFT_EVENTS_PATH.relative_to(ROOT)),
            "row_count": int(len(p2_2_events)),
            "event_type_counts": {
                str(event_type): int(count)
                for event_type, count in p2_2_events["event_type"].value_counts().sort_index().items()
            },
            "distinct_trade_counts_by_event_type": {
                str(event_type): int(
                    p2_2_events.loc[p2_2_events["event_type"] == event_type, "pair_id"].nunique()
                )
                for event_type in sorted(p2_2_events["event_type"].unique())
            },
            "replay_matches_final_candidate_trades": True,
        }
        summary["candidate_terminal_tail_trade_ids"] = {
            "le_neg_50": candidate.loc[
                pd.to_numeric(candidate["terminal_return"]) <= -50.0, "trade_id"
            ].astype(str).tolist(),
            "le_neg_60": candidate.loc[
                pd.to_numeric(candidate["terminal_return"]) <= -60.0, "trade_id"
            ].astype(str).tolist(),
        }
        summary["new_candidate_le_neg40_from_control_gt_neg40_trades"] = candidate_diagnostics.get(
            "new_candidate_le_neg40_trades", []
        )
        summary["p2_1_directional_comparison"] = p2_1_comparison
        summary["lifecycle_settlement"] = {
            "evidence_path": str(LIFECYCLE_SETTLEMENT_EVIDENCE_PATH.relative_to(ROOT)),
            "evidence_record_count": len(run.lifecycle_settlements),
            "evidence_ids": [str(item["evidence_id"]) for item in run.lifecycle_settlements],
            "control_settled_trade_count": int(
                control["trade_status"].eq("LIFECYCLE_SETTLED").sum()
            ),
            "candidate_settled_trade_count": int(
                candidate["trade_status"].eq("LIFECYCLE_SETTLED").sum()
            ),
            "terminal_status": "LIFECYCLE_SETTLED",
            "terminal_reason": "SHARE_EXCHANGE_CASH_SETTLEMENT",
            "market_execution_synthesized": False,
        }
    elif selected_window == "P3-1":
        assert p2_2_ledger is not None and p2_2_events is not None
        assert ledger_aggregates is not None and ledger_reconciliation is not None
        summary["ledger"] = {
            "path": str(MATCHED_LEDGER_PATH.relative_to(ROOT)),
            "row_count": int(len(p2_2_ledger)),
            "pair_id_unique_count": int(p2_2_ledger["pair_id"].nunique()),
            "distinct_source_trade_id_count": int(p2_2_ledger["trade_id"].nunique()),
            "source_trade_id_preserved": True,
            "control_candidate_trade_count_equal": len(control) == len(candidate),
            "control_candidate_pair_id_sets_equal": set(control["pair_id"])
            == set(candidate["pair_id"]),
            "control_candidate_source_trade_id_equal_by_pair": bool(
                paired["trade_id_control"].astype(str).equals(
                    paired["trade_id_candidate"].astype(str)
                )
            ),
            "aggregates_recomputed_from_full_ledger": ledger_aggregates,
            "aggregate_reconciliation": ledger_reconciliation,
            "pair_level_trade_status_and_terminal_reason_encoding": (
                "CONTROL=<value>;CANDIDATE=<value>; side-specific columns are also included"
            ),
        }
        summary["soft_events"] = {
            "path": str(SOFT_EVENTS_PATH.relative_to(ROOT)),
            "row_count": int(len(p2_2_events)),
            "event_type_counts": {
                str(event_type): int(count)
                for event_type, count in p2_2_events["event_type"].value_counts().sort_index().items()
            },
            "distinct_trade_counts_by_event_type": {
                str(event_type): int(
                    p2_2_events.loc[p2_2_events["event_type"] == event_type, "pair_id"].nunique()
                )
                for event_type in sorted(p2_2_events["event_type"].unique())
            },
            "replay_matches_final_candidate_trades": True,
            "soft_exit_execution_contract": "same matched trade; next local session; Repository V2 actual row OPEN within allowed execution support",
        }
        summary["lifecycle_settlement"] = {
            "evidence_path": str(LIFECYCLE_SETTLEMENT_EVIDENCE_PATH.relative_to(ROOT)),
            "evidence_record_count": len(run.lifecycle_settlements),
            "in_window_evidence_record_count": sum(
                run.window.effective_start
                <= pd.Timestamp(item["settlement_date"]).normalize()
                <= run.window.effective_end
                for item in run.lifecycle_settlements
            ),
            "control_settled_trade_count": int(control["trade_status"].eq("LIFECYCLE_SETTLED").sum()),
            "candidate_settled_trade_count": int(candidate["trade_status"].eq("LIFECYCLE_SETTLED").sum()),
            "common_interval_end_before_cutoff_open_trade_count": validation[
                "common_interval_end_before_cutoff_open_count"
            ],
            # Legacy alias retained until downstream artifact consumers migrate.
            "unresolved_identity_end_open_trade_count": validation[
                "common_interval_end_before_cutoff_open_count"
            ],
            "market_execution_synthesized": False,
        }
        summary["p2_directional_comparison"] = p3_1_comparison
        summary["population_preflight"] = p3_1_preflight
        validation.update(
            {
                "soft_exit_execution_contract_pass": True,
                "cutoff_after_soft_event_count": int(
                    (pd.to_datetime(p2_2_events["date"]) > run.window.effective_end).sum()
                ),
                "unexecuted_signal_count": int(candidate["trade_status"].eq("UNEXECUTED_SIGNAL").sum()),
                "ledger_recomputation_pass": all(ledger_reconciliation.values()),
            }
        )
    if selected_window == "P3-1":
        summary["strategy_assessment"] = summary["verdict"]
        required_checks = (
            p3_1_preflight is not None and p3_1_preflight.get("status") == "PASS",
            validation.get("duplicate_pair_ids") == 0,
            validation.get("entry_population_parity") is True,
            validation.get("exit_window_violations") == 0,
            validation.get("candidate_unexecuted_signal_count") == 0,
            validation.get("candidate_execution_support_missing_count") == 0,
            validation.get("common_interval_end_before_cutoff_open_count") == 0,
            validation.get("open_terminal_valuation_unresolved_count") == 0,
            validation.get("control_candidate_lifecycle_settlement_counts_equal") is True,
            validation.get("lifecycle_settlement_provenance_complete") is True,
            validation.get("ledger_pair_id_unique") is True,
            validation.get("control_candidate_pair_id_sets_equal") is True,
            validation.get("control_candidate_source_trade_id_equal_by_pair") is True,
            validation.get("all_ledger_aggregates_match_summary") is True,
            validation.get("soft_event_duplicates") == 0,
            validation.get("soft_event_replay_consistency") is True,
            validation.get("soft_exit_execution_contract_pass") is True,
            validation.get("cutoff_after_soft_event_count") == 0,
            validation.get("candidate_overlap_count") == 0,
            validation.get("candidate_stage_asof_future_violations") == 0,
        )
        summary["verdict"] = "P3_1_REPLAY_PASS" if all(required_checks) else "CHECK_REQUIRED"
        summary["status"] = "COMPLETE" if all(required_checks) else "CHECK_REQUIRED"

    output = RUN_DIR
    control.to_csv(output / "control_trades.csv", index=False)
    candidate.to_csv(output / "candidate_trades.csv", index=False)
    paired.to_csv(output / "paired_trades.csv", index=False)
    _json_write(output / "summary.json", summary)
    output_names = ["control_trades.csv", "candidate_trades.csv", "paired_trades.csv", "summary.json"]
    if selected_window in {"P2-2", "P3-1"}:
        p2_2_ledger.to_csv(MATCHED_LEDGER_PATH, index=False, float_format="%.8f")
        p2_2_events.to_csv(SOFT_EVENTS_PATH, index=False, float_format="%.8f")
        _json_write(LEDGER_SUMMARY_PATH, summary)
        output_names.extend(
            [MATCHED_LEDGER_PATH.name, SOFT_EVENTS_PATH.name, LEDGER_SUMMARY_PATH.name]
        )
    manifest = {
        "run_id": RUN_ID,
        "window_id": selected_window,
        "start_head": summary["head"],
        "p2_1_only": selected_window == "P2-1",
        "p2_2_only": selected_window == "P2-2",
        "p3_1_only": selected_window == "P3-1",
        "raw_candidate_artifact_reused": False,
        "effective_pit_sha256": run.authority.pit_sha256,
        "score_contract_sha256": _sha256(SCORE_CONTRACT_PATH),
        "stage_contract_sha256": _sha256(STAGE_CONTRACT_PATH),
        "sample_benchmark": str(SAMPLE_PATH.relative_to(ROOT)),
        "outputs": output_names,
    }
    _json_write(output / "run_manifest.json", manifest)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("sample", "full", "replay", "ledger"), required=True)
    parser.add_argument("--window", choices=("P2-1", "P2-2", "P3-1"), default="P2-1")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--sample-tickers", type=int, default=40)
    parser.add_argument(
        "--run-id",
        help="optional isolated P2-1/P2-2 output run id (must start with run_)",
    )
    args = parser.parse_args()
    _configure_run(args.window, args.run_id)
    if args.window == "P2-2" and args.mode in {"replay", "ledger"}:
        parser.error("P2-2 emits the matched ledger in its single full pass; replay/ledger modes are P2-1 only")
    if args.mode == "replay":
        result = _run_candidate_replay(args.workers)
    elif args.mode == "ledger":
        result = _run_ledger_export(args.workers)
    else:
        result = _run(args.mode, args.workers, args.sample_tickers, args.window)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
