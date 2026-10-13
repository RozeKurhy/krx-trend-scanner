#!/usr/bin/env python3
"""Phase 4B production runner: exact-target A FAST Core V2 + Stock Report v0.7.

Consumes only the 4A Scanner's exact-target artifacts
(``artifacts/patterns/pattern_a/production/scanner/pattern_a_universe_scan_{TARGET}.csv``
and its ``_summary.json``) and Phase 3B production Fundamentals artifacts
(``artifacts/fundamentals/production/{TARGET}/tickers/{ticker}.json``). It never
re-runs the Scanner, redefines the strategy, or hydrates Fundamentals -- it only
wires already-computed inputs into the existing ``generate_stock_report()`` /
A FAST Core V2 implementation.

Report target set (PHASE4B_REPORT_TARGET_CONTINUITY_FIX_V01): the Scanner's official
``candidate`` set alone is not the full publication target, because A FAST Core can
still hold an ``OPEN`` position on a ticker whose current Pattern A stage moved to
``LATE``/``WATCH``/``BLOCKED``. The target is therefore

    (previous_published_common ∩ current_scanner_common) ∪ current_scanner_candidates

where ``previous_published_common`` is read from the most recent canonical Stock
Report directory strictly before ``target_as_of`` (never ``web/data``, never the
target day's own -- possibly partial -- directory). Every previously published
``OPEN`` COMMON ticker must remain inside ``current_scanner_common``; if one falls
out of the current Scanner COMMON universe, this run fails closed
(``OPEN_POSITION_OUTSIDE_CURRENT_COMMON``) instead of silently including or
dropping it.

The existing target is then filtered by the canonical latest-quarter standalone
operating-income observation:

    (existing_report_target ∩ latest_quarter_operating_profit_positive) ∪ previous_open

The filter never reads TTM/annual values and never turns unavailable data into zero.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import inspect
import json
import logging
import math
import re
import shutil
import tempfile
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from trend_scanner.data.repository_v2_loader import build_production_repository_v2
from trend_scanner.data.rolling_market_data_refresh import (
    DEFAULT_ROLLING_AUTHORITY_DIR,
    load_rolling_authority,
    validate_merged_authority_coherence,
)
from trend_scanner.patterns.pattern_a_evaluator import PatternACandidateState
from trend_scanner.reporting.fundamentals_report import (
    FundamentalsArtifactUnavailable,
    load_fundamentals_section_from_production_artifact,
)
from trend_scanner.reporting.stock_report import generate_stock_report
from trend_scanner.universe.instrument_metadata import resolve_target_instrument_metadata
from trend_scanner.validation.pattern_a_fast_alignment_mcap_500b import (
    HISTORICAL_ALIGNMENT_REPLAY_MODE,
    AlignmentMcap500BGate,
    get_historical_alignment_replay_gate,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("run_daily_update_phase4b_v01")

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_STRATEGY_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V02"
PROMOTED_STRATEGY_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V02_ALIGNMENT_MCAP_500B"
ALLOWED_FAST_STRATEGY_IDS = {EXPECTED_STRATEGY_ID, PROMOTED_STRATEGY_ID}
FULL_HISTORY_ALIGNMENT_WEB = HISTORICAL_ALIGNMENT_REPLAY_MODE
EXPECTED_REPORT_VERSION = "0.7"
SUPPORTED_PREVIOUS_REPORT_VERSIONS = {"0.5", EXPECTED_REPORT_VERSION}
LATEST_QUARTER_OPERATING_PROFIT_POSITIVE = "POSITIVE"
LATEST_QUARTER_OPERATING_PROFIT_NON_POSITIVE = "NON_POSITIVE"
LATEST_QUARTER_OPERATING_PROFIT_UNAVAILABLE = "UNAVAILABLE"


class Phase4BError(RuntimeError):
    """Phase 4B fail-closed error (Scanner input validation, corpus validation)."""


def validate_replay_reference_authority(root: Path, reference_market_date: str) -> None:
    """Require the exact replay cutoff to be an exact certified KRX session."""
    authority_dir = Path(root) / DEFAULT_ROLLING_AUTHORITY_DIR
    try:
        manifest = load_rolling_authority(authority_dir)
        pit_payload, calendar_payload = validate_merged_authority_coherence(manifest, authority_dir)
    except Exception as exc:  # noqa: BLE001 -- authority failures stop generation
        raise Phase4BError(f"PHASE4B_ROLLING_AUTHORITY_INVALID: {exc}") from exc
    if (
        reference_market_date > manifest.certified_through
        or reference_market_date > str(pit_payload.get("pit_frontier") or "")[:10]
        or reference_market_date > str(manifest.merged_calendar_frontier or "")[:10]
        or reference_market_date not in set(calendar_payload.get("trading_dates") or [])
    ):
        raise Phase4BError(
            "PHASE4B_REFERENCE_MARKET_DATE_NOT_CERTIFIED_EXACT_SESSION: "
            f"{reference_market_date}"
        )


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _canonical_replay_core(core: dict[str, Any]) -> dict[str, Any]:
    """Normalize report serialization to the V02 replay digest contract."""
    normalized = dict(core)
    normalized.pop("strategy_replay_scope", None)
    normalized.pop("strategy_replay_digest", None)
    # Preserve the explicit empty dataclass values used by the V02 digest.
    normalized.setdefault("activation_intervals", [])
    normalized.setdefault("promotion_gate_status", None)
    normalized.setdefault("effective_signal_date", None)
    return normalized


def _full_history_replay_scope(
    common_reports: list[tuple[str, Path, dict[str, Any]]],
    requested_as_of: str,
    reference_market_date: str,
) -> dict[str, Any]:
    audit_rows: list[dict[str, Any]] = []
    for ticker, _path, report in common_reports:
        core = report.get("a_fast_core") or {}
        if core.get("strategy_id") != PROMOTED_STRATEGY_ID or core.get("strategy_replay_mode") != FULL_HISTORY_ALIGNMENT_WEB:
            raise Phase4BError(f"PHASE4B_FAST_REPLAY_MODE_OR_STRATEGY_MISMATCH: {ticker}")
        if core.get("activation_intervals") or core.get("promotion_gate_status") not in (None, "") or core.get("effective_signal_date") not in (None, ""):
            raise Phase4BError(f"PHASE4B_FAST_REPLAY_OPERATIONAL_METADATA_PRESENT: {ticker}")
        history = core.get("trade_history") or []
        if not isinstance(history, list):
            raise Phase4BError(f"PHASE4B_FAST_REPLAY_HISTORY_INVALID: {ticker}")
        for trade in history:
            if not isinstance(trade, dict):
                raise Phase4BError(f"PHASE4B_FAST_REPLAY_HISTORY_ROW_INVALID: {ticker}")
            if any(trade.get(field) != PROMOTED_STRATEGY_ID for field in (
                "strategy_id", "entry_strategy_id", "exit_strategy_id",
            )):
                raise Phase4BError(f"PHASE4B_FAST_REPLAY_MIXED_TRADE_LINEAGE: {ticker}")
        audits = core.get("promotion_gate_audit") or []
        if not isinstance(audits, list):
            raise Phase4BError(f"PHASE4B_FAST_REPLAY_GATE_AUDIT_INVALID: {ticker}")
        if any(not isinstance(row, dict) for row in audits):
            raise Phase4BError(f"PHASE4B_FAST_REPLAY_GATE_AUDIT_ROW_INVALID: {ticker}")
        audit_rows.extend(audits)

    signal_dates = [str(row.get("signal_date") or "")[:10] for row in audit_rows]
    signal_dates = [value for value in signal_dates if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)]
    passed_dates = [
        str(row.get("signal_date") or "")[:10]
        for row in audit_rows
        if row.get("allowed") is True
        and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(row.get("signal_date") or "")[:10])
    ]
    return {
        "type": "PUBLISHED_COMMON_REPORTS",
        "report_count": len(common_reports),
        "requested_as_of": requested_as_of,
        "reference_market_date": reference_market_date,
        "first_v2_candidate_signal_date": min(signal_dates) if signal_dates else None,
        "last_v2_candidate_signal_date": max(signal_dates) if signal_dates else None,
        "first_alignment_gate_pass_signal_date": min(passed_dates) if passed_dates else None,
        "base_candidate_signal_count": len(audit_rows),
        "alignment_gate_pass_count": sum(row.get("reason_code") == "PASS_ALIGNMENT_MCAP_500B" for row in audit_rows),
        "output_strategy_id": PROMOTED_STRATEGY_ID,
    }


def finalize_full_history_alignment_reports(
    staging_dir: Path,
    common_tickers: set[str],
    requested_as_of: str,
    reference_market_date: str,
) -> dict[str, Any]:
    """Attach one corpus-wide replay digest/scope after all 4B reports exist."""
    common_reports: list[tuple[str, Path, dict[str, Any]]] = []
    seen: set[str] = set()
    for path in sorted((Path(staging_dir) / "json").glob("*.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        ticker = str(report.get("ticker") or "").strip().upper().zfill(6)
        if report.get("asset_type") != "COMMON":
            continue
        if ticker in seen:
            raise Phase4BError(f"PHASE4B_FAST_REPLAY_DUPLICATE_TICKER: {ticker}")
        seen.add(ticker)
        if ticker not in {str(value).zfill(6) for value in common_tickers}:
            raise Phase4BError(f"PHASE4B_FAST_REPLAY_OUTSIDE_COMMON_SCOPE: {ticker}")
        if report.get("requested_as_of") != requested_as_of or report.get("reference_market_date") != reference_market_date:
            raise Phase4BError(f"PHASE4B_FAST_REPLAY_DATE_MISMATCH: {ticker}")
        common_reports.append((ticker, path, report))
    if seen != {str(value).zfill(6) for value in common_tickers}:
        raise Phase4BError("PHASE4B_FAST_REPLAY_COMMON_SCOPE_MISMATCH")

    scope = _full_history_replay_scope(common_reports, requested_as_of, reference_market_date)
    material = "".join(
        _canonical_json({"ticker": ticker, "a_fast_core": _canonical_replay_core(report["a_fast_core"])}) + "\n"
        for ticker, _path, report in sorted(common_reports)
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    for _ticker, path, report in common_reports:
        core = report["a_fast_core"]
        core.pop("activation_intervals", None)
        core.pop("promotion_gate_status", None)
        core.pop("effective_signal_date", None)
        core["strategy_replay_scope"] = scope
        core["strategy_replay_digest"] = digest
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return {
        "valid": True,
        "strategy_replay_mode": FULL_HISTORY_ALIGNMENT_WEB,
        "strategy_id": PROMOTED_STRATEGY_ID,
        "strategy_replay_digest": digest,
        "strategy_replay_scope": scope,
    }


def validate_full_history_alignment_corpus(
    staging_dir: Path,
    requested_as_of: str,
    reference_market_date: str,
    expected_common_tickers: set[str] | None = None,
) -> dict[str, Any]:
    """Verify one digest/scope, one Alignment lineage, and OPEN projection per COMMON report."""
    common_reports: list[tuple[str, Path, dict[str, Any]]] = []
    seen: set[str] = set()
    reasons: list[str] = []
    reported_digests: set[str] = set()
    reported_scopes: list[dict[str, Any]] = []
    trade_count = 0
    open_count = 0
    for path in sorted((Path(staging_dir) / "json").glob("*.json")):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            reasons.append("REPORT_JSON_INVALID")
            continue
        if report.get("asset_type") != "COMMON":
            continue
        ticker = str(report.get("ticker") or "").strip().upper().zfill(6)
        if not ticker or ticker in seen:
            reasons.append("COMMON_TICKER_DUPLICATE_OR_MISSING")
            continue
        seen.add(ticker)
        if report.get("requested_as_of") != requested_as_of or report.get("reference_market_date") != reference_market_date:
            reasons.append("REPORT_DATE_MISMATCH")
        core = report.get("a_fast_core") or {}
        if core.get("strategy_id") != PROMOTED_STRATEGY_ID or core.get("strategy_replay_mode") != FULL_HISTORY_ALIGNMENT_WEB:
            reasons.append("STRATEGY_ID_OR_REPLAY_MODE_MISMATCH")
        if core.get("activation_intervals") or core.get("promotion_gate_status") not in (None, "") or core.get("effective_signal_date") not in (None, ""):
            reasons.append("OPERATIONAL_ACTIVATION_METADATA_PRESENT")
        digest = core.get("strategy_replay_digest")
        scope = core.get("strategy_replay_scope")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) or not isinstance(scope, dict):
            reasons.append("REPLAY_PROVENANCE_MISSING_OR_INVALID")
        else:
            reported_digests.add(digest)
            reported_scopes.append(scope)
        history = core.get("trade_history") or []
        if not isinstance(history, list):
            reasons.append("TRADE_HISTORY_INVALID")
            history = []
        trade_count += len(history)
        current = core.get("current_trade")
        open_history = [row for row in history if isinstance(row, dict) and row.get("trade_status") == "OPEN_AT_CUTOFF"]
        if core.get("canonical_position") == "OPEN":
            open_count += 1
            if (
                not isinstance(current, dict)
                or current.get("trade_status") != "OPEN"
                or len(open_history) != 1
                or current.get("trade_id") != open_history[0].get("trade_id")
            ):
                reasons.append("OPEN_CURRENT_HISTORY_MISMATCH")
        elif current is not None or open_history:
            reasons.append("FLAT_CURRENT_HISTORY_MISMATCH")
        for trade in [*history, *([current] if isinstance(current, dict) else [])]:
            if any(trade.get(field) != PROMOTED_STRATEGY_ID for field in (
                "strategy_id", "entry_strategy_id", "exit_strategy_id",
            )):
                reasons.append("MIXED_TRADE_LINEAGE")
                break
        common_reports.append((ticker, path, report))

    if expected_common_tickers is not None and seen != {str(value).zfill(6) for value in expected_common_tickers}:
        reasons.append("COMMON_SCOPE_MISMATCH")
    if not common_reports:
        reasons.append("COMMON_REPORTS_MISSING")
    if len(reported_digests) != 1:
        reasons.append("REPLAY_DIGEST_INCONSISTENT")
    if reported_scopes and any(scope != reported_scopes[0] for scope in reported_scopes[1:]):
        reasons.append("REPLAY_SCOPE_INCONSISTENT")

    computed_digest = None
    computed_scope = None
    if common_reports:
        try:
            computed_scope = _full_history_replay_scope(common_reports, requested_as_of, reference_market_date)
            material = "".join(
                _canonical_json({"ticker": ticker, "a_fast_core": _canonical_replay_core(report["a_fast_core"])}) + "\n"
                for ticker, _path, report in sorted(common_reports)
            )
            computed_digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
            if reported_digests != {computed_digest}:
                reasons.append("REPLAY_DIGEST_RECOMPUTE_MISMATCH")
            if reported_scopes and any(scope != computed_scope for scope in reported_scopes):
                reasons.append("REPLAY_SCOPE_RECOMPUTE_MISMATCH")
        except (KeyError, TypeError, ValueError, Phase4BError):
            reasons.append("REPLAY_SCOPE_OR_DIGEST_CANNOT_RECOMPUTE")

    return {
        "valid": not reasons,
        "reason_codes": sorted(set(reasons)),
        "common_report_count": len(common_reports),
        "strategy_id": PROMOTED_STRATEGY_ID if common_reports else None,
        "strategy_replay_mode": FULL_HISTORY_ALIGNMENT_WEB if common_reports else None,
        "strategy_replay_digest": next(iter(reported_digests)) if len(reported_digests) == 1 else None,
        "computed_strategy_replay_digest": computed_digest,
        "strategy_replay_scope": computed_scope,
        "trade_count": trade_count,
        "current_open_position_count": open_count,
    }


def _scanner_paths(root: Path, target_as_of: str) -> tuple[Path, Path]:
    dt_clean = target_as_of.replace("-", "")
    base = root / "artifacts/patterns/pattern_a/production/scanner"
    return (
        base / f"pattern_a_universe_scan_{dt_clean}.csv",
        base / f"pattern_a_universe_scan_{dt_clean}_summary.json",
    )


def load_and_validate_scanner_input(root: Path, target_as_of: str) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """4A exact-target Scanner CSV/summary만 로드하고 최소 계약을 검증한다 (fail-closed)."""
    csv_path, summary_path = _scanner_paths(root, target_as_of)
    if not csv_path.exists():
        raise Phase4BError(f"PHASE4B_SCANNER_CSV_MISSING: {csv_path}")
    if not summary_path.exists():
        raise Phase4BError(f"PHASE4B_SCANNER_SUMMARY_MISSING: {summary_path}")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("requested_as_of") != target_as_of:
        raise Phase4BError(
            f"PHASE4B_SCANNER_REQUESTED_AS_OF_MISMATCH: expected {target_as_of}, "
            f"got {summary.get('requested_as_of')!r}"
        )
    reference_market_date = summary.get("reference_market_date")
    if not reference_market_date:
        raise Phase4BError("PHASE4B_SCANNER_REFERENCE_MARKET_DATE_MISSING")
    if str(reference_market_date) > target_as_of:
        raise Phase4BError(
            f"PHASE4B_SCANNER_REFERENCE_MARKET_DATE_AFTER_TARGET: "
            f"{reference_market_date} > {target_as_of}"
        )

    with csv_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    tickers = [r["ticker"] for r in rows]
    if len(tickers) != len(set(tickers)):
        raise Phase4BError("PHASE4B_SCANNER_DUPLICATE_TICKERS")

    rows_emitted = summary.get("rows_emitted")
    if rows_emitted != len(rows):
        raise Phase4BError(
            f"PHASE4B_SCANNER_ROW_COUNT_MISMATCH: csv rows={len(rows)}, "
            f"summary.rows_emitted={rows_emitted}"
        )

    return rows, summary


def select_candidate_tickers(rows: list[dict[str, str]]) -> list[str]:
    """Scanner 공식 candidate_state == CANDIDATE만, 실제 직렬화 값 기준으로 선택한다."""
    candidate_value = PatternACandidateState.CANDIDATE.value
    tickers = sorted(r["ticker"] for r in rows if r.get("candidate_state") == candidate_value)
    return tickers


def compute_current_common(rows: list[dict[str, str]]) -> set[str]:
    """4A exact-target scanner CSV의 전체 row는 이미 canonical COMMON 확정 집합이다."""
    return {r["ticker"] for r in rows}


_DATE_DIR_PATTERN = re.compile(r"^(\d{8})$")


def find_previous_canonical_report_dir(root: Path, target_as_of: str) -> Path:
    """``target_as_of``보다 엄격히 이전인 날짜 중 가장 최신의 유효한 canonical Stock
    Report directory를 선택한다. ``web/data``나 target 당일 디렉터리(예: 잘못 좁게
    생성된 기존 partial corpus)는 절대 previous source로 쓰지 않는다."""
    base = root / "artifacts/reporting/stock_reports"
    target_clean = target_as_of.replace("-", "")
    candidates: list[str] = []
    if base.exists():
        for p in base.iterdir():
            if not p.is_dir():
                continue
            if not _DATE_DIR_PATTERN.fullmatch(p.name):
                continue
            if p.name >= target_clean:
                continue
            json_dir = p / "json"
            if json_dir.is_dir() and any(json_dir.glob("*.json")):
                candidates.append(p.name)
    if not candidates:
        raise Phase4BError(
            f"PHASE4B_PREVIOUS_CORPUS_NOT_FOUND: no valid canonical report directory strictly before {target_as_of}"
        )
    return base / max(candidates)


@dataclass
class PreviousCorpusAudit:
    directory: Path
    total: int
    common: set[str]
    non_common: set[str]
    open_tickers: set[str]


_TICKER_RE = re.compile(r"^[0-9A-Z]{6}$")


def audit_previous_corpus(previous_dir: Path) -> PreviousCorpusAudit:
    """직전 canonical corpus를 read-only로 감사한다 (COMMON/non-COMMON, OPEN 포지션).

    PHASE4B_PRODUCTION_DEFAULT_FINAL_FIX_V01: continuity 계산의 authority가 되는
    선택된 previous corpus 단 하나에 대해 최소 무결성을 fail-closed로 검증한다
    (ticker 유효/중복 없음/report_version은 legacy v0.5 또는 v0.7 /
    requested_as_of==디렉터리 날짜/
    strategy_id==PATTERN_A_FAST_FINAL_STRATEGY_V02). previous corpus 선택 로직
    (``find_previous_canonical_report_dir``) 자체는 확대하지 않는다 -- 이미
    선택된 단 하나의 후보만 검증한다.
    """
    json_dir = previous_dir / "json"
    expected_as_of = f"{previous_dir.name[:4]}-{previous_dir.name[4:6]}-{previous_dir.name[6:]}"

    common: set[str] = set()
    non_common: set[str] = set()
    open_tickers: set[str] = set()
    seen_tickers: set[str] = set()
    strategy_ids_seen: set[str] = set()
    total = 0
    for p in sorted(json_dir.glob("*.json")):
        payload = json.loads(p.read_text(encoding="utf-8"))
        total += 1
        raw_ticker = str(payload.get("ticker", "")).strip().zfill(6)
        if not _TICKER_RE.fullmatch(raw_ticker):
            raise Phase4BError(f"PHASE4B_PREVIOUS_CORPUS_INVALID_TICKER: {raw_ticker!r} in {p}")
        if raw_ticker in seen_tickers:
            raise Phase4BError(f"PHASE4B_PREVIOUS_CORPUS_DUPLICATE_TICKER: {raw_ticker} in {previous_dir}")
        seen_tickers.add(raw_ticker)

        if payload.get("report_version") not in SUPPORTED_PREVIOUS_REPORT_VERSIONS:
            raise Phase4BError(
                f"PHASE4B_PREVIOUS_CORPUS_REPORT_VERSION_MISMATCH: {raw_ticker} "
                f"expected one of {sorted(SUPPORTED_PREVIOUS_REPORT_VERSIONS)!r}, "
                f"got {payload.get('report_version')!r} in {p}"
            )
        if payload.get("requested_as_of") != expected_as_of:
            raise Phase4BError(
                f"PHASE4B_PREVIOUS_CORPUS_AS_OF_MISMATCH: {raw_ticker} expected {expected_as_of!r}, "
                f"got {payload.get('requested_as_of')!r} in {p}"
            )
        strategy_id = (payload.get("a_fast_core") or {}).get("strategy_id")
        if strategy_id not in ALLOWED_FAST_STRATEGY_IDS:
            raise Phase4BError(
                f"PHASE4B_PREVIOUS_CORPUS_STRATEGY_ID_MISMATCH: {raw_ticker} expected one of {sorted(ALLOWED_FAST_STRATEGY_IDS)!r}, "
                f"got {strategy_id!r} in {p}"
            )
        strategy_ids_seen.add(str(strategy_id))

        ticker = raw_ticker
        asset_type = payload.get("asset_type")
        if asset_type == "COMMON":
            common.add(ticker)
            if (payload.get("a_fast_core") or {}).get("canonical_position") == "OPEN":
                open_tickers.add(ticker)
        else:
            non_common.add(ticker)
    if len(strategy_ids_seen) > 1:
        raise Phase4BError(
            f"PHASE4B_PREVIOUS_CORPUS_MIXED_FAST_STRATEGY_IDS: {sorted(strategy_ids_seen)!r} in {previous_dir}"
        )
    return PreviousCorpusAudit(
        directory=previous_dir, total=total, common=common, non_common=non_common, open_tickers=open_tickers,
    )


def compute_report_target(
    *,
    previous_common: set[str],
    previous_open: set[str],
    current_common: set[str],
    current_candidates: set[str],
) -> list[str]:
    """(previous_common ∩ current_common) ∪ current_candidates.

    previous_open ⊆ current_common이어야 한다 -- 그렇지 않으면 기존 OPEN 포지션 추적이
    끊기므로, 조용히 포함하거나 버리지 않고 fail-closed한다.
    """
    missing_open = previous_open - current_common
    if missing_open:
        raise Phase4BError(
            f"OPEN_POSITION_OUTSIDE_CURRENT_COMMON: {sorted(missing_open)}"
        )
    continuity = previous_common & current_common
    return sorted(continuity | current_candidates)


@dataclass(frozen=True)
class LatestQuarterOperatingProfit:
    """Canonical latest-quarter standalone operating-income classification."""

    status: str
    latest_quarter: str | None = None
    value: int | float | None = None
    reason: str | None = None


def classify_latest_quarter_operating_profit(
    artifact: dict[str, Any], *, target_as_of: str | None = None,
) -> LatestQuarterOperatingProfit:
    """Classify only the canonical latest standalone quarter operating income.

    The source is the production F2 artifact's ``latest_quarter`` and
    ``quarters`` observations. TTM, annual, margins, revenue and net income
    are deliberately not consulted. Missing, ambiguous or future observations
    remain unavailable; malformed or conflicting canonical authority metadata
    raises ``Phase4BError``.
    """
    f2 = artifact.get("f2")
    if f2 is None:
        return LatestQuarterOperatingProfit(
            LATEST_QUARTER_OPERATING_PROFIT_UNAVAILABLE, reason="F2_MISSING",
        )
    if not isinstance(f2, dict):
        raise Phase4BError("PHASE4B_FUNDAMENTALS_F2_INVALID")
    top_level_latest = artifact.get("f2_latest_quarter")
    f2_latest = f2.get("latest_quarter")
    top_level_present = top_level_latest not in (None, "")
    f2_latest_present = f2_latest not in (None, "")
    if top_level_present != f2_latest_present or (
        top_level_present and str(top_level_latest) != str(f2_latest)
    ):
        raise Phase4BError(
            "PHASE4B_FUNDAMENTALS_LATEST_QUARTER_AUTHORITY_MISMATCH"
        )
    if top_level_present and (
        not isinstance(top_level_latest, str)
        or re.fullmatch(r"\d{4}Q[1-4]", top_level_latest) is None
    ):
        raise Phase4BError("PHASE4B_FUNDAMENTALS_LATEST_QUARTER_INVALID")
    latest = str(top_level_latest or f2_latest or "").strip()
    match = re.fullmatch(r"(\d{4})(Q[1-4])", latest)
    if match is None:
        return LatestQuarterOperatingProfit(
            LATEST_QUARTER_OPERATING_PROFIT_UNAVAILABLE,
            latest_quarter=latest or None,
            reason="LATEST_QUARTER_UNAVAILABLE",
        )

    year, quarter = match.groups()
    quarters = f2.get("quarters")
    if quarters is None:
        return LatestQuarterOperatingProfit(
            LATEST_QUARTER_OPERATING_PROFIT_UNAVAILABLE,
            latest_quarter=latest,
            reason="LATEST_QUARTER_OPERATING_INCOME_UNAVAILABLE",
        )
    if not isinstance(quarters, list) or any(not isinstance(item, dict) for item in quarters):
        raise Phase4BError("PHASE4B_FUNDAMENTALS_QUARTERS_INVALID")
    observations = [
        item for item in quarters
        if str(item.get("fiscal_year")) == year
        and str(item.get("fiscal_period")) == quarter
        and item.get("metric") == "operating_income"
        and item.get("period_semantics") == "STANDALONE_QUARTER"
        and item.get("resolution_status") == "READY"
    ]
    if target_as_of is not None:
        target_clean = target_as_of.replace("-", "")
        observations = [
            item for item in observations
            if not item.get("pit_available_from")
            or str(item.get("pit_available_from")).replace("-", "")[:8] <= target_clean
        ]
    numeric = [
        item for item in observations
        if isinstance(item.get("value"), (int, float))
        and not isinstance(item.get("value"), bool)
        and math.isfinite(float(item.get("value")))
    ]
    if len(numeric) != 1:
        return LatestQuarterOperatingProfit(
            LATEST_QUARTER_OPERATING_PROFIT_UNAVAILABLE,
            latest_quarter=latest,
            reason="LATEST_QUARTER_OPERATING_INCOME_UNAVAILABLE",
        )
    value = numeric[0]["value"]
    return LatestQuarterOperatingProfit(
        LATEST_QUARTER_OPERATING_PROFIT_POSITIVE if value > 0 else LATEST_QUARTER_OPERATING_PROFIT_NON_POSITIVE,
        latest_quarter=latest,
        value=value,
    )


def load_latest_quarter_operating_profit(
    root: Path, ticker: str, target_as_of: str,
) -> LatestQuarterOperatingProfit:
    """Read one exact-target production Fundamentals artifact read-only."""
    day = target_as_of.replace("-", "")
    ticker_dir = root / "artifacts/fundamentals/production" / day / "tickers"
    if not ticker_dir.is_dir():
        raise Phase4BError(f"PHASE4B_FUNDAMENTALS_SOURCE_MISSING: {ticker_dir}")
    if not any(ticker_dir.glob("*.json")):
        raise Phase4BError(f"PHASE4B_FUNDAMENTALS_SOURCE_EMPTY: {ticker_dir}")
    path = ticker_dir / f"{ticker}.json"
    if not path.exists():
        return LatestQuarterOperatingProfit(
            LATEST_QUARTER_OPERATING_PROFIT_UNAVAILABLE, reason="FUNDAMENTALS_ARTIFACT_MISSING",
        )
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Phase4BError(
            f"PHASE4B_FUNDAMENTALS_ARTIFACT_INVALID: {path}"
        ) from exc
    if not isinstance(artifact, dict):
        raise Phase4BError(f"PHASE4B_FUNDAMENTALS_ARTIFACT_INVALID: {path}")
    if artifact.get("requested_as_of") != target_as_of:
        raise Phase4BError(
            "PHASE4B_FUNDAMENTALS_REQUESTED_AS_OF_MISMATCH: "
            f"{ticker} expected {target_as_of}, got {artifact.get('requested_as_of')}"
        )
    if artifact.get("asset_type") not in (None, "COMMON"):
        return LatestQuarterOperatingProfit(
            LATEST_QUARTER_OPERATING_PROFIT_UNAVAILABLE, reason="FUNDAMENTALS_NOT_COMMON",
        )
    return classify_latest_quarter_operating_profit(artifact, target_as_of=target_as_of)


def filter_report_target_by_fundamentals(
    *,
    existing_report_target: set[str],
    previous_open: set[str],
    statuses: dict[str, LatestQuarterOperatingProfit],
) -> tuple[list[str], dict[str, Any]]:
    """Apply the Phase 4B publication filter while protecting previous OPEN."""
    missing_open = previous_open - existing_report_target
    if missing_open:
        raise Phase4BError(
            f"PREVIOUS_OPEN_NOT_IN_EXISTING_REPORT_TARGET: {sorted(missing_open)}"
        )
    positive = {
        ticker for ticker in existing_report_target
        if statuses.get(ticker, LatestQuarterOperatingProfit(
            LATEST_QUARTER_OPERATING_PROFIT_UNAVAILABLE,
            reason="STATUS_MISSING",
        )).status == LATEST_QUARTER_OPERATING_PROFIT_POSITIVE
    }
    non_positive = {
        ticker for ticker in existing_report_target
        if statuses.get(ticker, LatestQuarterOperatingProfit(
            LATEST_QUARTER_OPERATING_PROFIT_UNAVAILABLE,
            reason="STATUS_MISSING",
        )).status == LATEST_QUARTER_OPERATING_PROFIT_NON_POSITIVE
    }
    unavailable = existing_report_target - positive - non_positive
    rescued = previous_open & (non_positive | unavailable)
    final_target = sorted((existing_report_target & positive) | previous_open)
    reason_counts = Counter(
        (statuses.get(ticker) or LatestQuarterOperatingProfit(
            LATEST_QUARTER_OPERATING_PROFIT_UNAVAILABLE,
            reason="STATUS_MISSING",
        )).reason or "NONE"
        for ticker in unavailable
    )
    return final_target, {
        "existing_report_target_count": len(existing_report_target),
        "fundamentals_positive_count": len(positive),
        "fundamentals_non_positive_count": len(non_positive),
        "fundamentals_unavailable_count": len(unavailable),
        "previous_open_count": len(previous_open),
        "rescued_previous_open_count": len(rescued),
        "filtered_target_count": len(final_target),
        "target_reduction_count": len(existing_report_target) - len(final_target),
        "target_reduction_pct": (
            (len(existing_report_target) - len(final_target)) / len(existing_report_target) * 100
            if existing_report_target else 0.0
        ),
        "fundamentals_unavailable_reason_counts": dict(reason_counts),
    }


def summarize_corpus_positions(staging_dir: Path) -> dict[str, Any]:
    """검증용 집계일 뿐 새 authority artifact가 아니다."""
    position_counts: Counter[str] = Counter()
    strategy_state_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()
    for p in sorted((staging_dir / "json").glob("*.json")):
        payload = json.loads(p.read_text(encoding="utf-8"))
        core = payload.get("a_fast_core") or {}
        position_counts[str(core.get("canonical_position"))] += 1
        strategy_state_counts[str(core.get("strategy_state"))] += 1
        action_counts[str(core.get("action"))] += 1
    return {
        "canonical_position_distribution": dict(position_counts),
        "strategy_state_distribution": dict(strategy_state_counts),
        "action_distribution": dict(action_counts),
    }


@dataclass
class GenerationOutcome:
    ticker: str
    status: str  # "OK" or "ERROR"
    error: str | None = None


def _generate_one(
    ticker: str, *, target_as_of: str, reference_market_date: str, repository: Any, root: Path, staging_dir: Path,
    instrument_metadata_resolver: Any | None = None,
    promotion_gate: AlignmentMcap500BGate | None = None,
) -> GenerationOutcome:
    try:
        fundamentals_section = load_fundamentals_section_from_production_artifact(
            ticker, target_as_of, root,
        )
        report_kwargs = {
            "ticker": ticker,
            "as_of": target_as_of,
            "repo_root": root,
            "repository": repository,
            "fundamentals_section": fundamentals_section,
            "reference_market_date": reference_market_date,
            "output_dir": staging_dir,
            "save_artifacts": True,
            "a_fast_replay_mode": FULL_HISTORY_ALIGNMENT_WEB,
            "promotion_gate": promotion_gate,
        }
        if (
            instrument_metadata_resolver is not None
            and "instrument_metadata_resolver" in inspect.signature(generate_stock_report).parameters
        ):
            report_kwargs["instrument_metadata_resolver"] = instrument_metadata_resolver
        generate_stock_report(
            **report_kwargs,
        )
        return GenerationOutcome(ticker=ticker, status="OK")
    except FundamentalsArtifactUnavailable as exc:
        return GenerationOutcome(ticker=ticker, status="ERROR", error=f"FUNDAMENTALS_FAIL_CLOSED: {exc}")
    except Exception as exc:  # noqa: BLE001 -- collected for full-batch visibility, not swallowed
        return GenerationOutcome(ticker=ticker, status="ERROR", error=str(exc))


# PHASE4B_STOCK_REPORT_PERFORMANCE_V01 (§14 병렬화, 공통 I/O/중복 계산 제거 후에도
# 1850개 예상 시간이 60분을 크게 초과해 마지막 수단으로 적용): 종목별 report 생성은
# 서로 완전히 독립적이고(공유 mutable state 없음, 파일도 ticker별로 분리되어 씀) 이미
# scripts/regenerate_stock_reports.py가 동일한 generate_stock_report() 호출에 대해
# ProcessPoolExecutor를 쓰는 선례가 있다. build_production_repository_v2()는
# 종목별이 아니라 실행당 1회 비용(약 130초)이므로, 워커 프로세스마다 최초 1회만
# 만들어 그 프로세스가 맡은 모든 티커에서 재사용한다(초기화 함수로 프로세스당 1회).
_POOL_STATE: dict[str, Any] = {}


def _pool_worker_init(root_str: str, target_as_of: str, staging_dir_str: str) -> None:
    root = Path(root_str)
    _POOL_STATE["root"] = root
    _POOL_STATE["staging_dir"] = Path(staging_dir_str)
    _POOL_STATE["repository"] = build_production_repository_v2(root, end=target_as_of)
    _POOL_STATE["promotion_gate"] = get_historical_alignment_replay_gate(str(root.resolve()))


def _pool_worker_generate(ticker: str, target_as_of: str, reference_market_date: str) -> GenerationOutcome:
    return _generate_one(
        ticker,
        target_as_of=target_as_of,
        reference_market_date=reference_market_date,
        repository=_POOL_STATE["repository"],
        root=_POOL_STATE["root"],
        staging_dir=_POOL_STATE["staging_dir"],
        instrument_metadata_resolver=resolve_target_instrument_metadata,
        promotion_gate=_POOL_STATE["promotion_gate"],
    )


def generate_candidate_reports(
    candidate_tickers: list[str],
    *,
    target_as_of: str,
    reference_market_date: str,
    repository: Any,
    root: Path,
    staging_dir: Path,
    max_workers: int = 1,
    instrument_metadata_resolver: Any | None = None,
    promotion_gate: AlignmentMcap500BGate | None = None,
) -> list[GenerationOutcome]:
    """staging_dir에 후보별 COMMON Stock Report v0.7을 생성한다. 개별 실패는 수집해 계속 진행하고
    (전체 생성 -> 전체 검증 -> promote 흐름을 위해), 최종 승격 여부는 호출자가 판단한다.

    ``max_workers <= 1``(기본값)이면 기존과 동일한 순차 in-process 경로를 그대로
    사용한다 -- 테스트가 ``generate_stock_report``를 monkeypatch로 대체할 수 있는
    것은 이 경로뿐이다(``ProcessPoolExecutor`` 자식 프로세스는 모듈을 새로 import하므로
    부모 프로세스의 monkeypatch를 볼 수 없다). ``max_workers > 1``이면 종목별로
    완전히 독립적인 계산을 별도 프로세스에 분산한다.
    """
    total = len(candidate_tickers)
    if max_workers <= 1:
        outcomes: list[GenerationOutcome] = []
        for i, ticker in enumerate(candidate_tickers, start=1):
            outcomes.append(
                _generate_one(
                    ticker, target_as_of=target_as_of, reference_market_date=reference_market_date,
                    repository=repository, root=root, staging_dir=staging_dir,
                    instrument_metadata_resolver=instrument_metadata_resolver,
                    promotion_gate=promotion_gate,
                )
            )
            if i % 25 == 0 or i == total:
                logger.info("Generated %d/%d candidate reports", i, total)
        return outcomes

    outcomes_by_ticker: dict[str, GenerationOutcome] = {}
    completed = 0
    with ProcessPoolExecutor(
        max_workers=max_workers,
        initializer=_pool_worker_init,
        initargs=(str(root), target_as_of, str(staging_dir)),
    ) as executor:
        futures = {
            executor.submit(_pool_worker_generate, ticker, target_as_of, reference_market_date): ticker
            for ticker in candidate_tickers
        }
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                outcome = future.result()
            except Exception as exc:  # noqa: BLE001 -- worker-process crash, still collected per ticker
                outcome = GenerationOutcome(ticker=ticker, status="ERROR", error=f"WORKER_PROCESS_ERROR: {exc}")
            outcomes_by_ticker[outcome.ticker] = outcome
            completed += 1
            if completed % 25 == 0 or completed == total:
                logger.info("Generated %d/%d candidate reports", completed, total)

    return [outcomes_by_ticker[t] for t in candidate_tickers]


def validate_corpus(
    staging_dir: Path,
    candidate_tickers: set[str],
    target_as_of: str,
    reference_market_date: str,
) -> dict[str, Any]:
    """staging_dir에 실제로 쓰여진 JSON/Markdown을 대상으로 전체 결과를 검증한다."""
    json_paths = sorted((staging_dir / "json").glob("*.json"))
    md_paths = sorted(staging_dir.glob("*.md"))
    json_tickers = {p.stem.split("_")[0] for p in json_paths}
    md_tickers = {p.stem.split("_")[0] for p in md_paths}

    report_version_mismatches: list[str] = []
    strategy_id_mismatches: list[str] = []
    strategy_ids_seen: set[str] = set()
    date_mismatches: list[str] = []

    for p in json_paths:
        payload = json.loads(p.read_text(encoding="utf-8"))
        ticker = p.stem.split("_")[0]
        if payload.get("report_version") != EXPECTED_REPORT_VERSION:
            report_version_mismatches.append(ticker)
        if payload.get("requested_as_of") != target_as_of or payload.get("reference_market_date") != reference_market_date:
            date_mismatches.append(ticker)
        strategy_id = (payload.get("a_fast_core") or {}).get("strategy_id")
        if strategy_id not in ALLOWED_FAST_STRATEGY_IDS:
            strategy_id_mismatches.append(ticker)
        elif strategy_id:
            strategy_ids_seen.add(str(strategy_id))

    if len(strategy_ids_seen) > 1:
        strategy_id_mismatches.extend(sorted(json_tickers))

    replay_validation = validate_full_history_alignment_corpus(
        staging_dir,
        target_as_of,
        reference_market_date,
        candidate_tickers,
    )
    return {
        "json_count": len(json_paths),
        "markdown_count": len(md_paths),
        "json_ticker_duplicate_count": len(json_paths) - len(json_tickers),
        "markdown_ticker_duplicate_count": len(md_paths) - len(md_tickers),
        "missing_tickers": sorted(candidate_tickers - json_tickers),
        "extra_tickers": sorted(json_tickers - candidate_tickers),
        "markdown_missing_tickers": sorted(candidate_tickers - md_tickers),
        "markdown_extra_tickers": sorted(md_tickers - candidate_tickers),
        "report_version_mismatch_count": len(report_version_mismatches),
        "strategy_id_mismatch_count": len(strategy_id_mismatches),
        "strategy_ids": sorted(strategy_ids_seen),
        "date_mismatch_count": len(date_mismatches),
        "full_history_alignment_replay_valid": replay_validation["valid"],
        "full_history_alignment_replay": replay_validation,
    }


def promote_staging(staging_dir: Path, canonical_dir: Path) -> None:
    """staging_dir을 canonical_dir로 원자적으로 승격한다. 기존 partial canonical_dir이
    있어도 merge하지 않고 완전히 교체한다."""
    parent = canonical_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    new_dir = Path(tempfile.mkdtemp(prefix=".phase4b-new-", dir=str(parent)))
    shutil.rmtree(new_dir)
    shutil.copytree(staging_dir, new_dir)
    if canonical_dir.exists():
        old_dir = parent / f".phase4b-old-{uuid4().hex}"
        canonical_dir.rename(old_dir)
        try:
            new_dir.rename(canonical_dir)
        except Exception:
            old_dir.rename(canonical_dir)
            raise
        shutil.rmtree(old_dir)
    else:
        new_dir.rename(canonical_dir)


def run_phase4b(target_as_of: str, root: Path = ROOT, *, max_workers: int = 1) -> dict[str, Any]:
    phase4b_started = time.perf_counter()
    rows, summary = load_and_validate_scanner_input(root, target_as_of)
    reference_market_date = str(summary["reference_market_date"])
    validate_replay_reference_authority(root, reference_market_date)
    promotion_gate = get_historical_alignment_replay_gate(str(Path(root).resolve()))
    current_common = compute_current_common(rows)
    current_candidates = set(select_candidate_tickers(rows))

    previous_dir = find_previous_canonical_report_dir(root, target_as_of)
    previous_audit = audit_previous_corpus(previous_dir)

    existing_report_target = set(compute_report_target(
        previous_common=previous_audit.common,
        previous_open=previous_audit.open_tickers,
        current_common=current_common,
        current_candidates=current_candidates,
    ))
    fundamentals_statuses = {
        ticker: load_latest_quarter_operating_profit(root, ticker, target_as_of)
        for ticker in sorted(existing_report_target)
    }
    target_tickers, fundamentals_filter = filter_report_target_by_fundamentals(
        existing_report_target=existing_report_target,
        previous_open=previous_audit.open_tickers,
        statuses=fundamentals_statuses,
    )
    target_ticker_set = set(target_tickers)
    continuity_count = len(previous_audit.common & current_common)

    logger.info(
        "Phase 4B target=%s: previous_dir=%s previous_common=%d previous_open=%d "
        "current_common=%d current_candidates=%d continuity=%d existing_target=%d "
        "positive=%d non_positive=%d unavailable=%d rescued_open=%d final_target=%d max_workers=%d",
        target_as_of, previous_dir.name, len(previous_audit.common), len(previous_audit.open_tickers),
        len(current_common), len(current_candidates), continuity_count,
        fundamentals_filter["existing_report_target_count"],
        fundamentals_filter["fundamentals_positive_count"],
        fundamentals_filter["fundamentals_non_positive_count"],
        fundamentals_filter["fundamentals_unavailable_count"],
        fundamentals_filter["rescued_previous_open_count"],
        len(target_tickers), max_workers,
    )

    # max_workers > 1이면 각 워커 프로세스가 자신만의 Repository V2를 1회 생성해
    # 재사용한다(_pool_worker_init) -- 메인 프로세스에서 미리 만들어도 자식
    # 프로세스로 넘겨줄 수 없으므로(피클 비용/불필요한 메모리) 순차 경로에서만
    # 여기서 만든다.
    repository = build_production_repository_v2(root, end=target_as_of) if max_workers <= 1 else None

    canonical_dir = root / "artifacts/reporting/stock_reports" / target_as_of.replace("-", "")
    staging_parent = canonical_dir.parent
    staging_parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=".phase4b-staging-", dir=str(staging_parent)) as temp_name:
        staging_dir = Path(temp_name) / canonical_dir.name
        staging_dir.mkdir(parents=True, exist_ok=True)

        outcomes = generate_candidate_reports(
            target_tickers,
            target_as_of=target_as_of,
            reference_market_date=reference_market_date,
            repository=repository,
            root=root,
            staging_dir=staging_dir,
            max_workers=max_workers,
            instrument_metadata_resolver=resolve_target_instrument_metadata,
            promotion_gate=promotion_gate,
        )
        errors = [o for o in outcomes if o.status == "ERROR"]

        replay_finalization: dict[str, Any] | None = None
        if not errors:
            try:
                replay_finalization = finalize_full_history_alignment_reports(
                    staging_dir,
                    target_ticker_set,
                    target_as_of,
                    reference_market_date,
                )
            except Exception as exc:  # noqa: BLE001 -- no promotion without complete provenance
                errors.append(GenerationOutcome(
                    ticker="*", status="ERROR", error=f"FAST_REPLAY_FINALIZATION_FAILED: {exc}",
                ))

        corpus = validate_corpus(staging_dir, target_ticker_set, target_as_of, reference_market_date)
        positions = summarize_corpus_positions(staging_dir)

        promoted = False
        success = (
            not errors
            and corpus["json_count"] == len(target_tickers)
            and corpus["markdown_count"] == len(target_tickers)
            and not corpus["missing_tickers"]
            and not corpus["extra_tickers"]
            and not corpus["markdown_missing_tickers"]
            and not corpus["markdown_extra_tickers"]
            and corpus["json_ticker_duplicate_count"] == 0
            and corpus["markdown_ticker_duplicate_count"] == 0
            and corpus["report_version_mismatch_count"] == 0
            and corpus["strategy_id_mismatch_count"] == 0
            and corpus["date_mismatch_count"] == 0
            and corpus["full_history_alignment_replay_valid"] is True
            and replay_finalization is not None
        )
        if success:
            promote_staging(staging_dir, canonical_dir)
            promoted = True
        else:
            logger.error("Phase 4B validation failed; canonical directory NOT promoted (staging discarded).")

    phase4b_runtime_seconds = time.perf_counter() - phase4b_started
    result = {
        "target_as_of": target_as_of,
        "requested_as_of": target_as_of,
        "reference_market_date": reference_market_date,
        "scanner_rows": len(rows),
        "scanner_common_count": len(current_common),
        "scanner_candidate_count": len(current_candidates),
        "previous_corpus_dir": str(previous_dir),
        "previous_total": previous_audit.total,
        "previous_common_count": len(previous_audit.common),
        "previous_non_common_count": len(previous_audit.non_common),
        "previous_open_count": len(previous_audit.open_tickers),
        "continuity_count": continuity_count,
        "new_candidate_count": len(current_candidates - previous_audit.common),
        "previous_common_removed_count": len(previous_audit.common - current_common),
        **fundamentals_filter,
        "report_target_count": len(target_tickers),
        "generation_error_count": len(errors),
        "generation_errors": [{"ticker": o.ticker, "error": o.error} for o in errors],
        **corpus,
        **positions,
        "report_generated_count": corpus["json_count"],
        "phase4b_runtime_seconds": phase4b_runtime_seconds,
        "reports_per_minute": (
            corpus["json_count"] / (phase4b_runtime_seconds / 60)
            if phase4b_runtime_seconds > 0 else 0.0
        ),
        "promoted": promoted,
        "canonical_dir": str(canonical_dir) if promoted else None,
        "full_history_alignment_replay_finalization": replay_finalization,
        "full_history_alignment_replay": corpus["full_history_alignment_replay"],
    }
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-as-of", required=True, help="explicit YYYY-MM-DD target (no default)")
    parser.add_argument(
        "--max-workers", type=int, default=5,
        help=(
            "candidate report 생성에 사용할 프로세스 수 (기본 5=운영 병렬 경로, "
            "2026-09-18 target 1452개 production이 worker=5로 1462.53초(24:23), "
            "59.57 reports/min, errors=0, canonical PASS를 기록했다). 종목별 계산은 완전히 "
            "독립적이므로 ProcessPoolExecutor로 병렬 생성한다"
            "(PHASE4B_STOCK_REPORT_PERFORMANCE_V01 §14). --max-workers 1로 기존 "
            "순차 in-process 디버그 경로를 명시적으로 선택할 수 있다."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result = run_phase4b(args.target_as_of, max_workers=args.max_workers)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, default=str))
    return 0 if result["promoted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
