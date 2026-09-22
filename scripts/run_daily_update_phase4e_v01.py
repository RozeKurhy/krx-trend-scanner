#!/usr/bin/env python3
"""Phase 4E integrated orchestration for the existing Phase 4A--4D runners.

This module only coordinates the existing entrypoints and normalizes their
results.  Analysis, strategy, ranking, data collection, and web payload logic
remain owned by the Phase 4A--4D modules.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
from datetime import date
import inspect
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
PASS = "PASS"
NOOP_ALREADY_COMPLETE = "NOOP_ALREADY_COMPLETE"
BLOCKED = "BLOCKED"
FAILED = "FAILED"
VALID_STATUSES = frozenset({PASS, NOOP_ALREADY_COMPLETE, BLOCKED, FAILED})

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_daily_update_phase4b_v01 as phase4b
from scripts import run_daily_update_phase4c_v01 as phase4c
from scripts import run_daily_update_phase4d_v01 as phase4d
from scripts import run_pattern_a_universe_scanner as phase4a


class Phase4EError(RuntimeError):
    """Integrated orchestration contract error."""


def _validate_target_as_of(target_as_of: str) -> str:
    if not isinstance(target_as_of, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", target_as_of):
        raise Phase4EError(f"INVALID_TARGET_AS_OF: {target_as_of!r}")
    try:
        date.fromisoformat(target_as_of)
    except ValueError as exc:
        raise Phase4EError(f"INVALID_TARGET_AS_OF: {target_as_of!r}") from exc
    return target_as_of


def normalize_status(value: Any) -> str:
    """Map a child result/status token to the exact Phase 4E enum."""

    raw = value
    if isinstance(value, Mapping):
        raw = value.get("status")
        if raw is None and value.get("promoted") is True:
            raw = PASS
        elif raw is None and value.get("promoted") is False:
            raw = FAILED
    if raw is True:
        return PASS
    if raw is False or raw is None:
        return FAILED

    token = str(raw).strip().upper()
    aliases = {
        "SUCCESS": PASS,
        "OK": PASS,
        "NOOP": NOOP_ALREADY_COMPLETE,
        "ALREADY_COMPLETE": NOOP_ALREADY_COMPLETE,
        "FAIL": FAILED,
        "ERROR": FAILED,
    }
    normalized = aliases.get(token, token)
    return normalized if normalized in VALID_STATUSES else FAILED


def synthesize_overall_status(statuses: Iterable[str]) -> str:
    """Apply the contract priority: FAILED, BLOCKED, all-NOOP, otherwise PASS."""

    normalized = [normalize_status(status) for status in statuses]
    if not normalized:
        return FAILED
    if FAILED in normalized:
        return FAILED
    if BLOCKED in normalized:
        return BLOCKED
    if all(status == NOOP_ALREADY_COMPLETE for status in normalized):
        return NOOP_ALREADY_COMPLETE
    return PASS


_BLOCKED_ERROR_CODES = frozenset(
    {
        "ROLLING_PRODUCTION_CALENDAR_UNAVAILABLE",
        "ROLLING_PRODUCTION_CALENDAR_INVALID",
        "ROLLING_PRODUCTION_CALENDAR_NO_DATE_AT_OR_BEFORE",
        "PHASE4B_SCANNER_CSV_MISSING",
        "PHASE4B_SCANNER_SUMMARY_MISSING",
        "PHASE4B_SCANNER_REQUESTED_AS_OF_MISMATCH",
        "PHASE4B_SCANNER_REFERENCE_MARKET_DATE_MISSING",
        "PHASE4B_SCANNER_REFERENCE_MARKET_DATE_AFTER_TARGET",
        "PHASE4B_PREVIOUS_CORPUS_NOT_FOUND",
        "OPEN_POSITION_OUTSIDE_CURRENT_COMMON",
        "PHASE4C_SCANNER_SUMMARY_MISSING",
        "PHASE4C_SCANNER_REQUESTED_AS_OF_MISMATCH",
        "PHASE4C_SCANNER_REFERENCE_MARKET_DATE_MISSING",
        "PHASE4C_SCANNER_REFERENCE_MARKET_DATE_AFTER_TARGET",
        "PHASE4C_BASIC_INFO_DIR_NOT_FOUND",
        "PHASE4C_BASIC_INFO_NO_SNAPSHOT_ON_OR_BEFORE_TARGET",
        "PHASE4C_REPORT_CORPUS_MISSING",
        "PHASE4C_REPORT_CORPUS_EMPTY",
        "PHASE4C_SECTOR_RS_AUTHORITY_MISSING",
        "PHASE4C_FOREIGN_NET_BUY_AUTHORITY_MISSING",
        "PHASE4C_SECTOR_RS_REQUESTED_AS_OF_MISMATCH",
        "PHASE4C_SECTOR_RS_REFERENCE_MARKET_DATE_MISMATCH",
        "PHASE4C_SECTOR_RS_AS_OF_MISMATCH",
        "PHASE4C_FOREIGN_NET_BUY_REQUESTED_AS_OF_MISMATCH",
        "PHASE4C_FOREIGN_NET_BUY_REFERENCE_MARKET_DATE_MISMATCH",
        "PHASE4C_FOREIGN_NET_BUY_AS_OF_MISMATCH",
        "PHASE4C_MARKET_RS_REQUESTED_AS_OF_MISMATCH",
        "PHASE4C_MARKET_RS_REFERENCE_MARKET_DATE_MISMATCH",
        "PHASE4C_HEALTH_DATE_MISMATCH",
        "PHASE4D_REPOSITORY_ROOT_MISMATCH",
        "PHASE4D_PHASE4C_PREREQUISITE_FAILED",
        "PHASE4D_REFERENCE_MARKET_DATE_INVALID",
        "PHASE4A_REFERENCE_MARKET_DATE_AUTHORITY_MISMATCH",
        "PHASE4D_REFERENCE_MARKET_DATE_AUTHORITY_MISMATCH",
    }
)


def _exception_status(exc: BaseException, *, phase_name: str | None = None) -> str:
    """Classify errors using explicit contract codes, never exception class names."""

    del phase_name  # Reserved for phase-specific mappings added by the owning contract.
    if isinstance(exc, FileNotFoundError):
        return BLOCKED
    if isinstance(exc, json.JSONDecodeError):
        return FAILED
    code = str(exc).split(":", 1)[0]
    return BLOCKED if code in _BLOCKED_ERROR_CODES else FAILED


def _failed_precheck(exc: BaseException) -> dict[str, Any]:
    return {
        "status": _exception_status(exc),
        "error": str(exc),
        "error_type": type(exc).__name__,
    }


def _expected_reference_market_date(root: Path, target_as_of: str) -> str:
    calendar = phase4a.load_rolling_production_market_calendar(root)
    return phase4a.resolve_reference_market_date(target_as_of, calendar)


def _phase4a_noop_precheck(target_as_of: str, *, root: Path) -> dict[str, Any] | None:
    csv_path, summary_path = phase4b._scanner_paths(root, target_as_of)
    if not csv_path.is_file() or not summary_path.is_file():
        return None
    rows, summary = phase4b.load_and_validate_scanner_input(root, target_as_of)
    phase4a.validate_full_common_scan(
        SimpleNamespace(**summary),
        is_full_common_scan=True,
    )
    expected_reference_market_date = _expected_reference_market_date(root, target_as_of)
    if str(summary["reference_market_date"]) != expected_reference_market_date:
        raise Phase4EError(
            "PHASE4A_REFERENCE_MARKET_DATE_AUTHORITY_MISMATCH: "
            f"expected {expected_reference_market_date}, got {summary['reference_market_date']}"
        )
    return {
        "status": NOOP_ALREADY_COMPLETE,
        "target_as_of": target_as_of,
        "requested_as_of": target_as_of,
        "reference_market_date": summary["reference_market_date"],
        "scanner_rows": len(rows),
        "reason": "VALID_EXACT_TARGET_SCANNER_ARTIFACTS",
    }


def _phase4b_noop_precheck(target_as_of: str, *, root: Path) -> dict[str, Any] | None:
    canonical_dir = root / "artifacts/reporting/stock_reports" / target_as_of.replace("-", "")
    json_dir = canonical_dir / "json"
    json_paths = list(json_dir.glob("*.json")) if json_dir.is_dir() else []
    markdown_paths = list(canonical_dir.glob("*.md")) if canonical_dir.is_dir() else []
    if not json_paths and not markdown_paths:
        return None

    rows, summary = phase4b.load_and_validate_scanner_input(root, target_as_of)
    reference_market_date = str(summary["reference_market_date"])
    previous_dir = phase4b.find_previous_canonical_report_dir(root, target_as_of)
    previous_audit = phase4b.audit_previous_corpus(previous_dir)
    target_tickers = set(
        phase4b.compute_report_target(
            previous_common=previous_audit.common,
            previous_open=previous_audit.open_tickers,
            current_common=phase4b.compute_current_common(rows),
            current_candidates=set(phase4b.select_candidate_tickers(rows)),
        )
    )
    corpus = phase4b.validate_corpus(
        canonical_dir,
        target_tickers,
        target_as_of,
        reference_market_date,
    )
    valid = (
        corpus["json_count"] == len(target_tickers)
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
    )
    if not valid:
        return {
            "status": FAILED,
            "target_as_of": target_as_of,
            "requested_as_of": target_as_of,
            "error": "PHASE4B_EXISTING_CORPUS_INVALID",
            "validation": corpus,
        }
    return {
        "status": NOOP_ALREADY_COMPLETE,
        "target_as_of": target_as_of,
        "requested_as_of": target_as_of,
        "reference_market_date": reference_market_date,
        "report_target_count": len(target_tickers),
        "reason": "VALID_EXACT_TARGET_REPORT_CORPUS",
    }


def _phase4c_noop_precheck(target_as_of: str, *, root: Path) -> dict[str, Any] | None:
    published = phase4d.inspect_published_payload(root, target_as_of)
    if published is None:
        return None
    return {
        "status": NOOP_ALREADY_COMPLETE,
        "target_as_of": target_as_of,
        "requested_as_of": target_as_of,
        "reference_market_date": published["reference_market_date"],
        "validation": published["validation"],
        "reason": "VALID_PUBLISHED_PHASE4D_PAYLOAD",
    }


def _phase4d_noop_precheck(target_as_of: str, *, root: Path) -> dict[str, Any] | None:
    published = phase4d.inspect_published_payload(root, target_as_of)
    if published is None:
        return None
    return {
        "status": NOOP_ALREADY_COMPLETE,
        "target_as_of": target_as_of,
        "requested_as_of": target_as_of,
        "reference_market_date": published["reference_market_date"],
        "validation": published["validation"],
        "reason": "VALID_EXACT_TARGET_WEB_PAYLOAD",
    }


def run_phase4a(target_as_of: str, *, root: Path = ROOT) -> dict[str, Any]:
    """Call the existing Phase 4A scanner adapter."""

    return phase4a.run_phase4a(target_as_of, root=root)


def run_phase4b(target_as_of: str, *, root: Path = ROOT) -> dict[str, Any]:
    """Call the existing Phase 4B runner."""

    return phase4b.run_phase4b(target_as_of, root=root, max_workers=5)


def run_phase4c(target_as_of: str, *, root: Path = ROOT) -> dict[str, Any]:
    """Call the existing Phase 4C runner."""

    return phase4c.run_phase4c(target_as_of, root=root)


def run_phase4d(
    target_as_of: str,
    *,
    execute_live: bool,
    root: Path = ROOT,
    phase4c_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call the existing Phase 4D runner with its explicit live flag."""

    return phase4d.run_phase4d(
        target_as_of,
        execute_live=execute_live,
        root=root,
        phase4c_result=phase4c_result,
    )


def _run_one(
    phase_name: str,
    target_as_of: str,
    runner: Callable[..., Any],
    *,
    execute_live: bool = False,
    root: Path,
    phase4c_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        kwargs: dict[str, Any] = {"root": root}
        if phase_name == "4D":
            kwargs["execute_live"] = execute_live
            parameters = inspect.signature(runner).parameters
            accepts_context = "phase4c_result" in parameters or any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            )
            if phase4c_result is not None and accepts_context:
                kwargs["phase4c_result"] = phase4c_result
        raw_result = runner(target_as_of, **kwargs)
        status = normalize_status(raw_result)
        return {"status": status, "result": raw_result}
    except Exception as exc:  # phase boundary: preserve the error as structured diagnostic
        return {
            "status": _exception_status(exc, phase_name=phase_name),
            "error": str(exc),
            "error_type": type(exc).__name__,
        }


def run_phase4e(
    target_as_of: str,
    *,
    execute_live: bool = False,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Run 4A → 4B → 4C → 4D and synthesize one structured result."""

    target_as_of = _validate_target_as_of(target_as_of)
    root = Path(root)
    phase_runners: tuple[tuple[str, Callable[..., Any]], ...] = (
        ("4A", run_phase4a),
        ("4B", run_phase4b),
        ("4C", run_phase4c),
        ("4D", run_phase4d),
    )
    phase_prechecks: dict[str, Callable[..., dict[str, Any] | None]] = {
        "4A": _phase4a_noop_precheck,
        "4B": _phase4b_noop_precheck,
        "4C": _phase4c_noop_precheck,
        "4D": _phase4d_noop_precheck,
    }

    phases: dict[str, dict[str, Any]] = {}
    for phase_name, runner in phase_runners:
        try:
            prechecked = phase_prechecks[phase_name](target_as_of, root=root)
        except Exception as exc:
            prechecked = _failed_precheck(exc)
        if prechecked is not None:
            phase_result = {
                "status": normalize_status(prechecked),
                "result": prechecked,
            }
        else:
            phase4c_context = (phases.get("4C") or {}).get("result")
            phase_result = _run_one(
                phase_name,
                target_as_of,
                runner,
                execute_live=execute_live,
                root=root,
                phase4c_result=phase4c_context if isinstance(phase4c_context, dict) else None,
            )
        phases[phase_name] = phase_result
        if phase_result["status"] in {FAILED, BLOCKED}:
            break

    return {
        "target_as_of": target_as_of,
        "execute_live": execute_live,
        "overall_status": synthesize_overall_status(item["status"] for item in phases.values()),
        "phases": phases,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-as-of", required=True, help="explicit YYYY-MM-DD target (no default)")
    parser.add_argument(
        "--execute-live",
        action="store_true",
        help="explicitly promote Phase 4D validated staging into web/data",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_phase4e(args.target_as_of, execute_live=args.execute_live)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, default=str))
    return 0 if result["overall_status"] in {PASS, NOOP_ALREADY_COMPLETE} else 1


if __name__ == "__main__":
    raise SystemExit(main())
