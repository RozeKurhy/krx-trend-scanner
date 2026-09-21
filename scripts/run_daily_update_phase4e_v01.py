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
import json
from pathlib import Path
import re
import sys
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


def _exception_status(exc: BaseException) -> str:
    """Classify expected fail-closed phase errors without inventing statuses."""

    name = type(exc).__name__
    message = str(exc).upper()
    if name in {"Phase4BError", "Phase4CError", "Phase4DError"}:
        return BLOCKED
    blocked_markers = (
        "BLOCKED",
        "MISSING",
        "UNAVAILABLE",
        "NO_DATE",
        "MISMATCH",
        "REQUIRED_INPUT",
        "AUTHORITY",
    )
    return BLOCKED if any(marker in message for marker in blocked_markers) else FAILED


def run_phase4a(target_as_of: str, *, root: Path = ROOT) -> dict[str, Any]:
    """Call the existing Phase 4A scanner adapter."""

    return phase4a.run_phase4a(target_as_of, root=root)


def run_phase4b(target_as_of: str, *, root: Path = ROOT) -> dict[str, Any]:
    """Call the existing Phase 4B runner."""

    return phase4b.run_phase4b(target_as_of, root=root)


def run_phase4c(target_as_of: str, *, root: Path = ROOT) -> dict[str, Any]:
    """Call the existing Phase 4C runner."""

    return phase4c.run_phase4c(target_as_of, root=root)


def run_phase4d(
    target_as_of: str,
    *,
    execute_live: bool,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Call the existing Phase 4D runner with its explicit live flag."""

    return phase4d.run_phase4d(target_as_of, execute_live=execute_live, root=root)


def _run_one(
    phase_name: str,
    target_as_of: str,
    runner: Callable[..., Any],
    *,
    execute_live: bool = False,
    root: Path,
) -> dict[str, Any]:
    try:
        if phase_name == "4D":
            raw_result = runner(target_as_of, execute_live=execute_live, root=root)
        else:
            raw_result = runner(target_as_of, root=root)
        status = normalize_status(raw_result)
        return {"status": status, "result": raw_result}
    except Exception as exc:  # phase boundary: preserve the error as structured diagnostic
        return {
            "status": _exception_status(exc),
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

    phases: dict[str, dict[str, Any]] = {}
    for phase_name, runner in phase_runners:
        phase_result = _run_one(
            phase_name,
            target_as_of,
            runner,
            execute_live=execute_live,
            root=root,
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
