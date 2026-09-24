#!/usr/bin/env python3
"""Pattern B full-universe operational audit V01 (audit only; no rule/feature/contract change).

Record: docs/patterns/pattern_b/validation/full_universe_operational_audit_v01.md

Applies the official Pattern B evaluator once to every target PIT COMMON ticker
(``load_target_pit_common_tickers``) as of ``--target-as-of``:

1. The target date must be a merged-calendar trading date on or before the rolling
   authority ``certified_through``; no silent fallback.
2. Each ticker must have exactly one active COMMON KOSPI/KOSDAQ interval in the merged
   PIT authority; its market must equal the target Basic Info market.
3. Prices come from one production Repository V2 per run, via ``RepositoryV2DailyLoader``
   with ``start=identity_effective_from`` and ``end=target_as_of``.
4. Loaded frames are evaluated only with ``evaluate_pattern_b``.
5. A deterministic 20-ticker sample is reloaded with a new repository and compared.

Data is read from ``--data-root`` (read-only); artifacts are written under this repo.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from trend_scanner.data.repository_v2_loader import (  # noqa: E402
    RepositoryV2DailyLoader,
    build_production_repository_v2,
)
from trend_scanner.data.rolling_market_data_refresh import (  # noqa: E402
    DEFAULT_ROLLING_AUTHORITY_DIR,
    RollingAuthorityError,
)
from trend_scanner.patterns import pattern_b_state_v02 as rule  # noqa: E402
from trend_scanner.patterns.pattern_b_evaluator import (  # noqa: E402
    FEATURE_CONTRACT_VERSION,
    STATE_RULE_VERSION,
    PatternBEvaluationStatus,
    evaluate_pattern_b,
)
from trend_scanner.universe.instrument_metadata import (  # noqa: E402
    load_target_basic_info_universe,
    load_target_pit_common_tickers,
)

DEFAULT_OUT_DIR = ROOT / "artifacts/patterns/pattern_b/operational_audit_v01"
RESULTS_NAME = "pattern_b_full_universe_results.csv"
SUMMARY_NAME = "pattern_b_full_universe_summary.json"
MARKETS = ("KOSPI", "KOSDAQ")
STATUSES = tuple(s.value for s in PatternBEvaluationStatus)
REPLAY_SIZE = 20
LOADED, DATA_UNAVAILABLE, ERROR = "LOADED", "DATA_UNAVAILABLE", "ERROR"
CODE_FILES = (
    "src/trend_scanner/patterns/pattern_b_evaluator.py",
    "src/trend_scanner/patterns/pattern_b_features_v01.py",
    "src/trend_scanner/patterns/pattern_b_state_v02.py",
)
RESULT_FIELDS = (
    "ticker", "name", "market", "isu_cd", "identity_effective_from", "identity_effective_to",
    "repository_status", "repository_reason", "row_count", "first_daily_date", "last_daily_date",
    "evaluation_status", "pattern_b_state", "reason_codes", "reason_details",
    "range_36m", "monthly_ma24_distance", "range_52w", "monthly_last_bar", "weekly_last_bar",
    "feature_contract_version", "state_rule_version",
    "error", "prior_same_isu_segment", "stale_monthly_bar", "stale_weekly_bar",
)
REPLAY_FIELDS = (
    "evaluation_status", "pattern_b_state", "range_36m", "monthly_ma24_distance", "range_52w",
    "monthly_last_bar", "weekly_last_bar", "feature_contract_version", "state_rule_version",
)


class AuditCheckRequired(RuntimeError):
    """Run-level precondition failed; the audit cannot produce a verdict."""


# ---------------------------------------------------------------- pure functions


def active_intervals(intervals: list[dict], target: str) -> dict[str, list[dict]]:
    """Active COMMON KOSPI/KOSDAQ intervals containing ``target``, grouped by ticker."""
    out: dict[str, list[dict]] = {}
    for iv in intervals:
        if (iv.get("state") == "COMMON" and str(iv.get("market", "")).upper() in MARKETS
                and str(iv["effective_from"]) <= target <= str(iv["effective_to"])):
            out.setdefault(str(iv["ticker"]).strip().upper(), []).append(iv)
    return out


def resolve_identities(
    universe: set[str], basic_rows: list[dict], intervals: list[dict], target: str,
) -> tuple[dict[str, dict], dict[str, list[str]]]:
    """Exactly one active interval per universe ticker; fail-closed problems are returned, never guessed."""
    active = active_intervals(intervals, target)
    basic = {str(r["ticker"]): r for r in basic_rows}
    problems: dict[str, list[str]] = {"missing_interval": [], "ambiguous_interval": [],
                                      "market_mismatch": [], "missing_basic_info": []}
    resolved: dict[str, dict] = {}
    for ticker in sorted(universe):
        found = active.get(ticker, [])
        if not found:
            problems["missing_interval"].append(ticker)
            continue
        if len(found) > 1:
            problems["ambiguous_interval"].append(ticker)
            continue
        iv = found[0]
        row = basic.get(ticker)
        if row is None:
            problems["missing_basic_info"].append(ticker)
            continue
        if str(row["market"]).upper() != str(iv["market"]).upper():
            problems["market_mismatch"].append(ticker)
            continue
        resolved[ticker] = {
            "ticker": ticker, "name": str(row["name"]), "market": str(iv["market"]).upper(),
            "isu_cd": str(iv["isu_cd"]), "identity_effective_from": str(iv["effective_from"]),
            "identity_effective_to": str(iv["effective_to"]),
        }
    return resolved, problems


def prior_same_isu_segments(resolved: dict[str, dict], intervals: list[dict]) -> set[str]:
    """Tickers whose ISIN also has an interval ending before the active segment starts."""
    ends: dict[str, list[str]] = {}
    for iv in intervals:
        ends.setdefault(str(iv["isu_cd"]), []).append(str(iv["effective_to"]))
    return {t for t, r in resolved.items()
            if any(end < r["identity_effective_from"] for end in ends.get(r["isu_cd"], []))}


def expected_last_bars(target: str) -> tuple[str, str]:
    """Latest completed month-end and W-FRI labels on or before ``target``."""
    ts = pd.Timestamp(target)
    month = ts if ts.is_month_end else ts - pd.offsets.MonthEnd(1)
    friday = ts if ts.weekday() == 4 else ts - pd.offsets.Week(weekday=4)
    return month.date().isoformat(), friday.date().isoformat()


def replay_sample(tickers, n: int = REPLAY_SIZE) -> list[str]:
    """First ``n`` tickers by SHA-256 of the ticker string."""
    return sorted(tickers, key=lambda t: hashlib.sha256(str(t).encode("utf-8")).hexdigest())[:n]


def _is_null(value: Any) -> bool:
    return value is None or value == "" or (isinstance(value, float) and math.isnan(value))


def check_invariants(rows: list[dict], universe: set[str]) -> dict[str, Any]:
    """Structural counts that must be zero, plus coverage equalities."""
    tickers = [r["ticker"] for r in rows]
    counts = Counter(tickers)
    loaded = [r for r in rows if r["repository_status"] == LOADED and not r["error"]]
    ready = [r for r in loaded if r["evaluation_status"] == "READY"]
    unavailable = [r for r in loaded if r["evaluation_status"] == "UNAVAILABLE"]
    state_counts = Counter(r["pattern_b_state"] for r in ready)
    zero = {
        "duplicate_ticker": sum(1 for c in counts.values() if c > 1),
        "unprocessed_ticker": len(universe - set(tickers)),
        "extra_ticker": len(set(tickers) - universe),
        "repository_data_unavailable": sum(r["repository_status"] == DATA_UNAVAILABLE for r in rows),
        "hard_error": sum(bool(r["error"]) for r in rows),
        "unknown_evaluation_status": sum(r["evaluation_status"] not in STATUSES for r in loaded),
        "unknown_pattern_b_state": sum(
            not _is_null(r["pattern_b_state"]) and r["pattern_b_state"] not in rule.STATES for r in loaded),
        "ready_null_state": sum(_is_null(r["pattern_b_state"]) for r in ready),
        "unavailable_with_state": sum(not _is_null(r["pattern_b_state"]) for r in unavailable),
        "identity_boundary_violation": sum(bool(r.get("_boundary_violation")) for r in rows),
        "post_as_of_row": sum(bool(r.get("_post_as_of")) for r in rows),
        "wrong_repository_authority": sum(bool(r.get("_wrong_authority")) for r in rows),
        "wrong_versions": sum(
            (r["feature_contract_version"], r["state_rule_version"]) != (FEATURE_CONTRACT_VERSION, STATE_RULE_VERSION)
            for r in loaded),
    }
    equalities = {
        "processed_equals_universe": len(rows) == len(universe),
        "ready_plus_unavailable_equals_universe": len(ready) + len(unavailable) == len(universe),
        "state_sum_equals_ready": sum(state_counts.values()) == len(ready),
    }
    return {"zero_checks": zero, "equalities": equalities,
            "pass": all(v == 0 for v in zero.values()) and all(equalities.values())}


def distribution(rows: list[dict]) -> dict[str, Any]:
    ready = [r for r in rows if r["evaluation_status"] == "READY"]
    unavailable = [r for r in rows if r["evaluation_status"] == "UNAVAILABLE"]
    n = len(rows)
    codes = Counter(code for r in unavailable for code in str(r["reason_codes"]).split("|") if code)
    combos = Counter(str(r["reason_codes"]) for r in unavailable)
    return {
        "count": n,
        "ready": len(ready), "ready_rate": round(len(ready) / n, 4) if n else None,
        "unavailable": len(unavailable), "unavailable_rate": round(len(unavailable) / n, 4) if n else None,
        "states": {s: sum(r["pattern_b_state"] == s for r in ready) for s in rule.STATES},
        "unavailable_reason_codes": dict(sorted(codes.items())),
        "unavailable_reason_combinations": dict(sorted(combos.items())),
    }


# ---------------------------------------------------------------- data access


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def authority_fingerprint(data_root: Path) -> dict[str, Any]:
    directory = data_root / DEFAULT_ROLLING_AUTHORITY_DIR
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    pit = json.loads((directory / "merged_pit_intervals.json").read_text(encoding="utf-8"))
    status = subprocess.run(["git", "-C", str(data_root), "status", "--porcelain"],
                            capture_output=True, text=True, check=False).stdout
    return {
        "certified_through": manifest["certified_through"],
        "common_adjusted_boundary": manifest["leg_boundaries"]["common_adjusted"],
        "manifest_sha256_field": manifest["manifest_sha256"],
        "manifest_file_sha256": _sha(directory / "manifest.json"),
        "merged_pit_file_sha256": _sha(directory / "merged_pit_intervals.json"),
        "merged_pit_content_digest": pit["content_digest"],
        "merged_pit_frontier": pit["pit_frontier"],
        "merged_calendar_file_sha256": _sha(directory / "merged_trading_calendar.json"),
        "data_root_git_status_sha256": hashlib.sha256(status.encode("utf-8")).hexdigest(),
    }


def _calendar_dates(data_root: Path) -> set[str]:
    payload = json.loads((data_root / DEFAULT_ROLLING_AUTHORITY_DIR / "merged_trading_calendar.json")
                         .read_text(encoding="utf-8"))
    for key in ("dates", "trading_dates", "calendar_dates"):
        if key in payload:
            return {str(d)[:10] for d in payload[key]}
    raise AuditCheckRequired(f"merged trading calendar has no date list: keys={sorted(payload)}")


def validate_target(data_root: Path, target: str, fingerprint: dict) -> None:
    if target > fingerprint["certified_through"] or target > fingerprint["common_adjusted_boundary"]:
        raise AuditCheckRequired(f"target {target} is after certified COMMON boundary")
    if target not in _calendar_dates(data_root):
        raise AuditCheckRequired(f"target {target} is not a merged-calendar trading date")


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return repr(value)
    return str(value)


def evaluate_one(repository, identity: dict, target: str, last_month: str, last_week: str) -> dict:
    row: dict[str, Any] = {**identity, "repository_status": "", "repository_reason": "", "row_count": 0,
                           "first_daily_date": "", "last_daily_date": "", "evaluation_status": "",
                           "pattern_b_state": None, "reason_codes": "", "reason_details": "",
                           "range_36m": None, "monthly_ma24_distance": None, "range_52w": None,
                           "monthly_last_bar": "", "weekly_last_bar": "",
                           "feature_contract_version": "", "state_rule_version": "", "error": ""}
    ticker = identity["ticker"]
    loader = RepositoryV2DailyLoader(repository, start=identity["identity_effective_from"], end=target)
    try:
        frame = loader.load(ticker)
    except RollingAuthorityError as exc:
        if str(exc).startswith("IDENTITY_"):
            row.update(repository_status=ERROR, error=f"RollingAuthorityError: {exc}")
            return row
        raise
    except Exception as exc:  # noqa: BLE001 - recorded as a hard error, never hidden
        row.update(repository_status=ERROR, error=f"{type(exc).__name__}: {exc}")
        return row
    if frame is None:
        audit = repository.query_audit.get(ticker.zfill(6), {})
        row.update(repository_status=DATA_UNAVAILABLE, repository_reason=str(audit.get("reason") or ""))
        return row
    first, last = frame.index.min(), frame.index.max()
    row.update(repository_status=LOADED, row_count=len(frame),
               first_daily_date=first.date().isoformat(), last_daily_date=last.date().isoformat())
    row["_wrong_authority"] = frame.attrs.get("data_authority") != "MarketDataRepositoryV2"
    row["_boundary_violation"] = first < pd.Timestamp(identity["identity_effective_from"])
    row["_post_as_of"] = last > pd.Timestamp(target)
    try:
        result = evaluate_pattern_b(ticker, frame, target, name=identity["name"])
    except Exception as exc:  # noqa: BLE001
        row.update(error=f"{type(exc).__name__}: {exc}")
        return row
    row.update(
        evaluation_status=result.evaluation_status.value, pattern_b_state=result.pattern_b_state,
        reason_codes="|".join(result.reason_codes), reason_details="|".join(result.reason_details),
        range_36m=result.range_36m, monthly_ma24_distance=result.monthly_ma24_distance,
        range_52w=result.range_52w, monthly_last_bar=result.monthly_last_bar or "",
        weekly_last_bar=result.weekly_last_bar or "",
        feature_contract_version=result.feature_contract_version,
        state_rule_version=result.state_rule_version,
    )
    row["stale_monthly_bar"] = bool(result.monthly_last_bar) and result.monthly_last_bar < last_month
    row["stale_weekly_bar"] = bool(result.weekly_last_bar) and result.weekly_last_bar < last_week
    return row


def run(data_root: Path, target: str, out_dir: Path, *, limit: int | None = None) -> dict[str, Any]:
    started = time.time()
    before = authority_fingerprint(data_root)
    validate_target(data_root, target, before)
    universe = load_target_pit_common_tickers(data_root, target)
    basic_rows, snapshot_date = load_target_basic_info_universe(data_root, target)
    pit = json.loads((data_root / DEFAULT_ROLLING_AUTHORITY_DIR / "merged_pit_intervals.json")
                     .read_text(encoding="utf-8"))
    intervals = pit["intervals"]
    resolved, problems = resolve_identities(universe, basic_rows, intervals, target)
    active = active_intervals(intervals, target)
    classification_excluded = sorted(set(active) - universe)
    prior = prior_same_isu_segments(resolved, intervals)
    floor = min(str(iv["effective_from"]) for iv in intervals)
    last_month, last_week = expected_last_bars(target)

    targets = sorted(resolved)
    if limit is not None:
        targets = targets[:limit]
        universe = set(targets) | {t for t in universe if t not in resolved}
    repository = build_production_repository_v2(data_root, end=target)
    rows = []
    for i, ticker in enumerate(targets, 1):
        row = evaluate_one(repository, resolved[ticker], target, last_month, last_week)
        row["prior_same_isu_segment"] = ticker in prior
        rows.append(row)
        if i % 200 == 0:
            print(f"[{i}/{len(targets)}] {time.time() - started:.0f}s", flush=True)

    invariants = check_invariants(rows, universe)
    identity_ok = not any(problems.values())

    sample = replay_sample([r["ticker"] for r in rows if r["repository_status"] == LOADED and not r["error"]])
    replay_repo = build_production_repository_v2(data_root, end=target)
    by_ticker = {r["ticker"]: r for r in rows}
    mismatches = []
    for ticker in sample:
        again = evaluate_one(replay_repo, resolved[ticker], target, last_month, last_week)
        diff = [f for f in REPLAY_FIELDS if again[f] != by_ticker[ticker][f]]
        if diff:
            mismatches.append({"ticker": ticker, "fields": diff})

    after = authority_fingerprint(data_root)
    authority_stable = before == after

    loaded_rows = [r for r in rows if r["repository_status"] == LOADED and not r["error"]]
    by_market = {m: distribution([r for r in loaded_rows if r["market"] == m]) for m in MARKETS}
    unavailable = [r for r in loaded_rows if r["evaluation_status"] == "UNAVAILABLE"]
    summary = {
        "schema": "pattern_b_full_universe_operational_audit_v01",
        "target_as_of": target,
        "basic_info_snapshot_date": snapshot_date,
        "population_authority": "load_target_pit_common_tickers",
        "universe_count": len(universe),
        "universe_by_market": dict(Counter(r["market"] for r in resolved.values())),
        "duplicate_universe_ticker": 0,
        "active_interval_tickers": len(active),
        "classification_excluded_interval_tickers": len(classification_excluded),
        "identity": {"resolved": len(resolved), **{k: len(v) for k, v in problems.items()},
                     "problem_tickers": problems},
        "segment_diagnostics": {
            "prior_same_isu_segment": len(prior),
            "prior_same_isu_segment_unavailable": sum(r["prior_same_isu_segment"] for r in unavailable),
            "pit_interval_floor": floor,
            "effective_from_at_floor": sum(r["identity_effective_from"] == floor for r in resolved.values()),
            "effective_from_at_floor_unavailable": sum(r["identity_effective_from"] == floor for r in unavailable),
        },
        "expected_last_bars": {"monthly": last_month, "weekly": last_week},
        "stale_bars": {"monthly": sum(bool(r.get("stale_monthly_bar")) for r in loaded_rows),
                       "weekly": sum(bool(r.get("stale_weekly_bar")) for r in loaded_rows)},
        "repository": {
            "loaded": sum(r["repository_status"] == LOADED for r in rows),
            "data_unavailable": sum(r["repository_status"] == DATA_UNAVAILABLE for r in rows),
            "data_unavailable_reasons": dict(Counter(
                r["repository_reason"] for r in rows if r["repository_status"] == DATA_UNAVAILABLE)),
            "error": sum(r["repository_status"] == ERROR for r in rows),
        },
        "hard_errors": [{"ticker": r["ticker"], "error": r["error"]} for r in rows if r["error"]],
        "distribution": distribution(loaded_rows),
        "distribution_by_market": by_market,
        "invariants": invariants,
        "replay": {"sample": sample, "count": len(sample), "mismatches": mismatches},
        "authority_before": before,
        "authority_after": after,
        "authority_stable": authority_stable,
        "code_sha256": {p: _sha(ROOT / p) for p in CODE_FILES},
        "elapsed_seconds": round(time.time() - started, 1),
        "limit": limit,
    }
    summary["verdict"] = "PASS" if (
        identity_ok and invariants["pass"] and not mismatches and authority_stable
        and len(sample) == REPLAY_SIZE and limit is None
    ) else "CHECK_REQUIRED"

    target_dir = out_dir / target
    target_dir.mkdir(parents=True, exist_ok=True)
    with (target_dir / RESULTS_NAME).open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=RESULT_FIELDS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for r in rows:
            writer.writerow({k: _fmt(r.get(k)) for k in RESULT_FIELDS})
    (target_dir / SUMMARY_NAME).write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target-as-of", required=True)
    parser.add_argument("--data-root", type=Path, default=ROOT,
                        help="repository root that holds data/ (read-only)")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=None, help="smoke test only; verdict is never PASS")
    args = parser.parse_args()
    target = pd.Timestamp(args.target_as_of).date().isoformat()
    try:
        summary = run(args.data_root.resolve(), target, args.out_dir, limit=args.limit)
    except AuditCheckRequired as exc:
        raise SystemExit(f"CHECK_REQUIRED: {exc}")
    print(json.dumps({k: summary[k] for k in ("target_as_of", "universe_count", "repository", "distribution",
                                              "verdict")}, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
